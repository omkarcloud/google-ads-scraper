"""Google Ads Transparency Center transport: plain curl_cffi with chrome
TLS. No browser, no cookies, no tokens, no login. Egress: one sticky proxy
exit per thread session (config.google_ads_proxy(); the hosted service
runs every call through a datacenter proxy, owner decision 2026-11-03).
A retryable failure drops the session, so the retry rides a fresh exit.

adstransparency.google.com is a pure JS app (no server-rendered data): the
page's own calls are POSTs to /anji/_/rpc/<Service>/<Method>?authuser=
with a form field f.req=<protobuf-as-JSON> (numeric keys) and the header
x-same-domain: 1. Mapped 2026-11-03 (field numbers in parsers.py):

  SearchService/SearchSuggestions  {"1": text, "2": max advertisers, "3": max
        domains, "5": {"1": 1}} -> advertisers (name, AR id, country, ad-count
        range, verified flag) and matching domains. No region filter.
  SearchService/SearchCreatives    {"2": page size (<= 100), "3": {filters},
        "4": continuation token, "7": {"1": 1 commercial | 2 political,
        "2": 0, "3": client region code}} -> up to 100 creatives, a
        continuation token and the advertiser's total ad-count range. The
        filters: "12": {"1": domain or "", "2": true}, "13": {"1": [AR ids]},
        "4": format, "14": [platforms], "8": [region codes], "6" / "7":
        YYYYMMDD start / end. The political feed (7.1 = 2) needs a region.
        A bad token is an HTTP 500 "Couldn't parse continuation token".
  LookupService/GetCreativeById    {"2": CR id, "5": {"1": topic, "2": 0,
        "3": client region}} -> the creative: variations, per-region stats
        (impression ranges for EU regions), targeting flags, political spend.
        The AR id is optional. A commercial creative answers only under
        topic 1 and a political one only under topic 2.
  LookupService/GetAdvertiserById  {"1": AR id, "3": {"1": 1}} -> name,
        legal name, country, verification, topics, political regions.
  An unknown id answers HTTP 200 with an empty object, never a 404.

  RENDER  GET displayads-formats.googleusercontent.com/ads/preview/content.js?…
        (the link the creative carries for its image / video / text render):
        a JS file whose previewservice.insertPreviewHtmlContent(...) call holds
        the ad's rendered HTML — headline, description, display domain,
        business name and location extension in a data-p blob, product title
        / brand / thumbnail for Shopping, the YouTube id for video.

Enums (captured from the site's own requests 2026-11-03): region code =
2000 + ISO 3166-1 numeric (US 2840, GB 2826, DE 2276); format TEXT 1 /
IMAGE 2 / VIDEO 3; platform PLAY 1 / MAPS 2 / SEARCH 3 / SHOPPING 4 /
YOUTUBE 5 (the UI offers no Display filter).

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  GoogleAdsUpstreamError  transport failure / 5xx / non-JSON   — retryable
  GoogleAdsBlocked        403 / 429 / captcha / consent page  — retryable on a fresh exit
  GoogleAdsBadRequest     HTTP 400 / unparseable token         — never retried
  GoogleAdsNotFound       raised by api.py on an empty object  — never retried
"""
import json
import os
import sys
import threading
import time
from urllib.parse import urlparse

# Allow direct execution (python google_ads/fetch.py): flat imports resolve
# like under the server. Idempotent when imported normally.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import egress
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from google_ads.refs import SITE, TOPICS

IMPERSONATE = "chrome"
RPC_TIMEOUT = 30
RENDER_TIMEOUT = 30
RPC_PATH = "/anji/_/rpc/"
RENDER_HOST = "displayads-formats.googleusercontent.com"
# The site sends the viewer's own region as 7.3 / 5.3 ("client context");
# any code answers identically (2026-11-03: India, the US and 2 all served
# the same pages), so the pod announces the US like its exits.
CLIENT_REGION = 2840

RPC_HEADERS = {
    "accept": "*/*",
    "accept-language": egress.site_accept_language("google-ads"),
    "content-type": "application/x-www-form-urlencoded",
    "origin": SITE,
    "referer": SITE + "/?region=anywhere",
    "x-same-domain": "1",
}
RENDER_HEADERS = {
    "accept": "*/*",
    "accept-language": egress.site_accept_language("google-ads"),
    "referer": SITE + "/",
}

_BLOCK_MARKERS = ("unusual traffic", "/sorry/", "recaptcha", "captcha-form", "consent.google")


class GoogleAdsUpstreamError(UpstreamError):
    """Transport failure, 5xx or an unparseable answer — retryable."""


class GoogleAdsBlocked(GoogleAdsUpstreamError, Blocked):
    """403 / 429 / captcha / consent page — retried on a fresh exit."""


class GoogleAdsBadRequest(BadRequest):
    """Google rejected the request (HTTP 400, bad continuation token) — never retried."""


class GoogleAdsNotFound(NotFound):
    """No such advertiser / creative — never retried."""


# ---- sessions ------------------------------------------------------------------------

# One curl session per cheroot worker thread (a curl handle must not be
# shared across threads); its Accept-Language is the exit's.
_local = threading.local()


def _new_state(proxy):
    from curl_cffi import requests as curl_requests
    sess = curl_requests.Session(impersonate=IMPERSONATE)
    if proxy:
        sess.proxies = {"http": proxy, "https": proxy}
    language = egress.accept_language(proxy)
    return {
        "session": sess,
        "proxy": proxy,
        "rpc_headers": {**RPC_HEADERS, "accept-language": language},
        "render_headers": {**RENDER_HEADERS, "accept-language": language},
    }


def _state():
    state = getattr(_local, "state", None)
    if state is None:
        state = _local.state = _new_state(config.google_ads_proxy())
    return state


def _drop_session():
    """Close the thread's session so the retry rides a fresh exit."""
    state = getattr(_local, "state", None)
    _local.state = None
    if state is not None:
        try:
            state["session"].close()
        except Exception:
            pass


def _retrying(fn, label):
    """Run fn() under the shared retry policy (GoogleAdsUpstreamError only,
    Blocked included, each retry on a fresh session / exit; BadRequest and
    NotFound surface immediately)."""
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except GoogleAdsUpstreamError as e:
            last = e
            _drop_session()
        print(f"google-ads: {label} attempt {attempt}/{config.MAX_RETRIES} failed: {last}")
        if attempt < config.MAX_RETRIES:
            time.sleep(config.RETRY_BACKOFF * attempt)
    raise last


def _classify(resp, label):
    """Map an HTTP response to the error taxonomy; return the body text."""
    status = resp.status_code
    text = resp.text
    if status == 400:
        raise GoogleAdsBadRequest(f"Google rejected {label}")
    if status in (401, 403, 429):
        raise GoogleAdsBlocked(f"HTTP {status} for {label}")
    if status == 500 and "continuation token" in text:
        raise GoogleAdsBadRequest("the page token is not valid (it belongs to another query or has expired)")
    if status != 200:
        raise GoogleAdsUpstreamError(f"HTTP {status} for {label}")
    final = str(resp.url)
    if any(m in final for m in ("/sorry/", "consent.google")) or any(m in text[:20000] for m in _BLOCK_MARKERS[:1]):
        raise GoogleAdsBlocked(f"captcha / consent page for {label}")
    return text


# ---- RPCs ----------------------------------------------------------------------------

def rpc(method, body, label):
    """POST one anji RPC -> its decoded JSON object (an empty dict when the
    site has nothing for the id — unknown advertiser / creative)."""
    url = f"{SITE}{RPC_PATH}{method}?authuser="
    payload = {"f.req": json.dumps(body, separators=(",", ":"), ensure_ascii=False)}

    def once():
        state = _state()
        try:
            resp = state["session"].post(url, data=payload, headers=state["rpc_headers"], timeout=RPC_TIMEOUT)
        except Exception as e:
            raise GoogleAdsUpstreamError(f"{label}: request failed: {type(e).__name__}: {e}")
        text = _classify(resp, label)
        try:
            data = json.loads(text)
        except ValueError:
            raise GoogleAdsBlocked(f"{label}: non-JSON answer ({text[:80]!r})")
        if not isinstance(data, dict):
            raise GoogleAdsUpstreamError(f"{label}: unexpected payload shape")
        return data
    return _retrying(once, label)


def _context(political):
    return {"1": TOPICS["political"] if political else TOPICS["commercial"], "2": 0, "3": CLIENT_REGION}


def search_suggestions(query, max_advertisers, max_domains):
    """SearchService/SearchSuggestions -> raw {"1": [...], "3": token}."""
    body = {"1": query, "2": max_advertisers, "3": max_domains, "5": {"1": 1}}
    return rpc("SearchService/SearchSuggestions", body, f"suggestions {query!r}")


def search_creatives(advertiser=None, domain=None, region_codes=None, format_code=None,
                     platform_codes=None, start=None, end=None, page_size=40, token=None,
                     political=False):
    """SearchService/SearchCreatives -> raw {"1": [creatives], "2": token,
    "4" / "5": total-count range}. `start` / `end` are YYYYMMDD ints,
    `region_codes` / `platform_codes` lists of the site's enums. A page size
    of 0 answers the totals alone (the cheap count call)."""
    filters = {"12": {"1": domain or "", "2": True}}
    if advertiser:
        filters["13"] = {"1": [advertiser]}
    if format_code:
        filters["4"] = format_code
    if start:
        filters["6"] = start
    if end:
        filters["7"] = end
    if region_codes:
        filters["8"] = list(region_codes)
    if platform_codes:
        filters["14"] = list(platform_codes)
    body = {"2": page_size, "3": filters, "7": _context(political)}
    if token:
        body["4"] = token
    label = f"{'political ' if political else ''}creatives of {advertiser or domain or 'anyone'}"
    return rpc("SearchService/SearchCreatives", body, label)


def get_creative(creative, political=False):
    """LookupService/GetCreativeById -> raw {"1": {...}} or {} when unknown
    under this topic (a political creative answers only with political=True)."""
    body = {"2": creative, "5": _context(political)}
    return rpc("LookupService/GetCreativeById", body, f"creative {creative}")


def get_advertiser(advertiser):
    """LookupService/GetAdvertiserById -> raw {"1": {...}} or {} when unknown."""
    body = {"1": advertiser, "3": {"1": TOPICS["commercial"]}}
    return rpc("LookupService/GetAdvertiserById", body, f"advertiser {advertiser}")


# ---- renders -------------------------------------------------------------------------

def render(link):
    """GET a creative's preview render (content.js on
    displayads-formats.googleusercontent.com) -> the JS text."""
    host = (urlparse(link).hostname or "").lower()
    if host != RENDER_HOST:
        raise GoogleAdsUpstreamError(f"render link on an unexpected host: {host}")

    def once():
        state = _state()
        try:
            resp = state["session"].get(link, headers=state["render_headers"], timeout=RENDER_TIMEOUT)
        except Exception as e:
            raise GoogleAdsUpstreamError(f"render: request failed: {type(e).__name__}: {e}")
        text = _classify(resp, "render")
        if "previewservice" not in text[:400000]:
            raise GoogleAdsUpstreamError("render: unexpected body (no previewservice call)")
        return text
    return _retrying(once, "render")
