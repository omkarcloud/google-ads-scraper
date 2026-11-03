"""Raw anji RPC JSON / preview-render JS -> clean dicts for every
/google-ads/* endpoint. Pure functions, no I/O.

The RPCs answer protobuf-as-JSON (numeric keys). Field map, read off the
site's own traffic and the rendered pages on 2026-11-03:

  SearchSuggestions   "1"[] entries: {"1": advertiser {"1" name, "2" AR id,
                      "3" country, "4"{"2"{"1" ads min, "2" ads max}},
                      "5" true = verified}} | {"2": {"1" domain}}; "3" token
  SearchCreatives     "1"[] creatives, "2" continuation token, "4"/"5" the
                      total-count range. A creative: "1" AR, "2" CR, "3"
                      preview, "4" format, "6"/"7" first / last shown
                      ({"1" epoch s, "2" ns}), "12" advertiser name, "13"
                      days shown, "14" domain (domain searches only);
                      political feed extras "8"/"9" impressions min / max,
                      "10"/"11" spend min / max ({"1"[{"1" currency,
                      "2" amount}]}), "15" the regions the ad ran in.
  GetCreativeById     "1": {"1" AR, "2" CR, "3"/"4" first / last shown,
                      "5"[] variations (preview shapes), "6" days shown,
                      "7"[] countries shown (political), "8" format, "9"
                      impressions min (political), "11"/"12" spend min /
                      max, "13" targeting ("3"{"1"[region codes]} =
                      targeted locations, "4"{category: {"1" included,
                      "2" excluded}}), "16" ("1"{"1" content topic id},
                      "5"/"6" unknown), "17"[] per-region stats ("1" region
                      code, "2"/"3" impressions min / max, "4"/"5" first /
                      last shown, "7" = "4" again, "8"[] per platform
                      {"1" platform, "2"/"3" impressions}), "19" the same
                      shape summed over the regions that carry impression
                      ranges, "22"{"1" advertiser name}, "23" political
                      totals ("2"/"3" impressions, "4"/"5" dates).
  GetAdvertiserById   "1": {"1" AR, "2" name, "3" country, "9"{"1" legal
                      name, "2" display name, "4" 1 = verified}, "10"
                      political {"4"{"2"[region codes], "3" country}, "6"
                      unknown}, "11" country, "15"[] topics (1 commercial,
                      2 political)}
  preview             {"3": {"2": "<img src=… height width>"}} an archived
                      screenshot (text ads, political) | {"1": {"4": url}}
                      a render link (content.js) | {"4": 1} nothing
  render (content.js) previewservice.insertPreviewHtmlContent('…', '…',
                      '<JS-escaped HTML>') whose data-p blobs carry
                      [1, [headline, description, display domain, business
                      name, [[location…]], …]] for text ads and
                      [thumbnail, title, brand] for Shopping;
                      insertPreviewImageContent('…', '…', url, w, h) for
                      image-only renders; YouTube ids sit in the embed URL.
                      Display / YouTube renders also carry `var adData =
                      {visible_url, destination_url, google_template_data:
                      {'adData': [{headline, longHeadline, description,
                      callToActionText, channelName, videoDuration,
                      video_videoId, highResThumbnail, …}]}}` (17 of 29
                      live renders sampled 2026-11-03; VAST-hosted video
                      carries none).

Value conventions: timestamps as ISO UTC ("2026-11-03T09:00:53Z"), day
fields as "YYYY-MM-DD", ranges as {"min", "max"} (null bound = open end,
e.g. "over 10M"), money as {"amount", "currency"}; absent = null, never "".

Fixtures (google_ads/fixtures/, captured 2026-11-03): suggestions for
"nike" and a nonsense term; Nike, Inc.'s creative feed pages 1-2, nike.com
in GB, Nike Retail BV YouTube videos, the US political feed, an unknown
advertiser and an unknown domain; creatives: a text ad (3 screenshots + 1
render), an image ad, a video ad, an EU text ad with impression ranges,
a political ad with spend, an unknown id; advertisers: Nike, Money Metals
(political), unknown; renders: text / image (Shopping) / video /
political (image-only); the bad-token error body.
"""
import json
import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from google_ads import refs

_IMG_SRC_RE = re.compile(r'<img[^>]*\ssrc="([^"]+)"', re.I)
_IMG_DIM_RE = re.compile(r'\s(height|width)="(\d+)"', re.I)
_HTML_CALL_RE = re.compile(r"insertPreviewHtmlContent\('[^']*',\s*'[^']*',\s*'((?:[^'\\]|\\.)*)'", re.S)
_IMAGE_CALL_RE = re.compile(r"insertPreviewImageContent\('[^']*',\s*'[^']*',\s*'((?:[^'\\]|\\.)*)'(?:,\s*(\d+))?(?:,\s*(\d+))?", re.S)
_YOUTUBE_RE = re.compile(r"(?:youtube\.com/embed/|youtube\.com/watch\?v=|youtu\.be/|ytimg\.com/vi/)([A-Za-z0-9_-]{11})")
_JS_ESC_RE = re.compile(r"\\(x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|.)", re.S)
_PLACEHOLDER_RE = re.compile(r"<[^<>]*>|\[[^\[\]]*\]")
_AD_DATA_RE = re.compile(r"google_template_data:\s*\{\s*'adData'\s*:\s*\[\s*\{(.*?)\}\s*\]", re.S)
_JS_PAIR_RE = re.compile(r"'(\w+)'\s*:\s*'((?:[^'\\]|\\.)*)'")
_JS_TOP_FIELD_RE = re.compile(r"\b(visible_url|destination_url|final_url)\s*:\s*'((?:[^'\\]|\\.)*)'")
_DURATION_RE = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})$")
_JS_SIMPLE = {"n": "\n", "t": "\t", "r": "\r", "'": "'", '"': '"', "\\": "\\", "/": "/", "0": "\0"}


# ---- value helpers ----------------------------------------------------------

def _get(obj, *path):
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _timestamp(obj):
    """{"1": epoch seconds, "2": nanos} -> ISO UTC (seconds)."""
    secs = _int(_get(obj, "1")) if isinstance(obj, dict) else _int(obj)
    if secs is None:
        return None
    return datetime.fromtimestamp(secs, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _day(value):
    """20231203 -> "2023-12-03"."""
    number = _int(value)
    if number is None or number < 10000101:
        return None
    text = str(number)
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}"


def _range(low, high):
    low, high = _int(low), _int(high)
    if low is None and high is None:
        return None
    return {"min": low, "max": high}


def _money(obj):
    """{"1": [{"1": "USD", "2": "1500000"}]} -> {"amount", "currency"} (the first entry)."""
    entries = _get(obj, "1")
    if not isinstance(entries, list) or not entries:
        return None
    first = entries[0] if isinstance(entries[0], dict) else {}
    amount = _int(first.get("2"))
    if amount is None and not first.get("1"):
        return None
    return {"amount": amount, "currency": first.get("1") or None}


def _spend(low, high):
    low, high = _money(low), _money(high)
    if low is None and high is None:
        return None
    return {"min": low, "max": high}


def _region_fields(code):
    country = refs.country_of_region(code)
    return {"region": country, "region_name": refs.country_name(country) if country else None}


def _format(code):
    code = _int(code)
    return refs.FORMAT_NAMES.get(code) if code is not None else None


def _platform(code):
    code = _int(code)
    if code is None:
        return None
    return refs.PLATFORM_NAMES.get(code, f"PLATFORM_{code}")


def _preview(obj):
    """A creative's "3" / a variation entry -> {type, image, width, height, render_link}."""
    out = {"type": None, "image": None, "width": None, "height": None, "render_link": None}
    if not isinstance(obj, dict):
        return out
    html = _get(obj, "3", "2")
    if isinstance(html, str):
        match = _IMG_SRC_RE.search(html)
        if match:
            out["type"] = "image"
            out["image"] = match.group(1)
            for name, value in _IMG_DIM_RE.findall(html):
                out[name.lower()] = _int(value)
    link = _get(obj, "1", "4")
    if isinstance(link, str) and link:
        out["type"] = out["type"] or "render"
        out["render_link"] = link
    return out


# ---- advertisers/search ------------------------------------------------------

def parse_suggestions(raw):
    """SearchSuggestions -> {"advertisers": [...], "domains": [...], "next_token"}."""
    advertisers, domains = [], []
    for entry in (_get(raw, "1") or []):
        if not isinstance(entry, dict):
            continue
        adv = entry.get("1")
        if isinstance(adv, dict) and adv.get("2"):
            advertisers.append({
                "id": adv.get("2"),
                "name": adv.get("1") or None,
                "country": adv.get("3") or None,
                "is_verified": bool(adv.get("5")),
                "ads_count": _range(_get(adv, "4", "2", "1"), _get(adv, "4", "2", "2")),
                "link": refs.advertiser_link(adv.get("2")),
            })
        dom = entry.get("2")
        if isinstance(dom, dict) and dom.get("1"):
            domains.append({"domain": dom["1"], "link": refs.domain_link(dom["1"])})
    return {"advertisers": advertisers, "domains": domains, "next_token": _get(raw, "3") or None}


def pick_advertiser(advertisers, name):
    """The advertiser a brand name most plausibly means: among the
    suggestions whose name contains the query (case-insensitive) — else
    all of them — the one with the most ads ("Nike" -> Nike, Inc. with
    9,000+ ads, not the one-ad "Nike" in Kenya). None when there is none."""
    if not advertisers:
        return None
    needle = (name or "").strip().lower()
    pool = [a for a in advertisers if needle and needle in (a.get("name") or "").lower()] or advertisers

    def ads(a):
        count = a.get("ads_count") or {}
        return (count.get("max") or 0, count.get("min") or 0)
    return max(pool, key=ads)


# ---- advertisers/details -----------------------------------------------------

def parse_advertiser(raw, region=None):
    """GetAdvertiserById -> the advertiser record, or None for an empty answer."""
    adv = _get(raw, "1")
    if not isinstance(adv, dict) or not adv.get("1"):
        return None
    topics = [refs.TOPIC_NAMES.get(_int(t), f"topic_{t}") for t in (adv.get("15") or []) if _int(t) is not None]
    political = adv.get("10") if isinstance(adv.get("10"), dict) else None
    political_out = None
    if political:
        codes = _get(political, "4", "2") or []
        regions = [refs.country_of_region(c) for c in codes if refs.country_of_region(c)]
        political_out = {
            "country": _get(political, "4", "3") or None,
            "regions": regions or None,
            "link": refs.advertiser_link(adv["1"], region, political=True),
        }
    return {
        "id": adv["1"],
        "name": adv.get("2") or _get(adv, "9", "2") or None,
        "legal_name": _get(adv, "9", "1") or None,
        "country": adv.get("3") or adv.get("11") or None,
        "is_verified": _int(_get(adv, "9", "4")) == 1,
        "link": refs.advertiser_link(adv["1"], region),
        "topics": sorted(set(topics)) or None,
        "political": political_out,
    }


# ---- ads/search + political/search -------------------------------------------

def _political_summary(item):
    if not any(k in item for k in ("8", "9", "10", "11", "15")):
        return None
    regions = [r for r in (item.get("15") or []) if isinstance(r, str)]
    return {
        "regions": regions or None,
        "impressions": _range(item.get("8"), item.get("9")),
        "spend": _spend(item.get("10"), item.get("11")),
    }


def _ad_summary(item, region=None, political=False):
    advertiser, creative = item.get("1"), item.get("2")
    return {
        "id": creative,
        "link": refs.creative_link(advertiser, creative, region, political) if advertiser and creative else None,
        "advertiser": {
            "id": advertiser,
            "name": item.get("12") or None,
            "link": refs.advertiser_link(advertiser, region, political) if advertiser else None,
        },
        "domain": item.get("14") or None,
        "format": _format(item.get("4")),
        "first_shown": _timestamp(item.get("6")),
        "last_shown": _timestamp(item.get("7")),
        "days_shown": _int(item.get("13")),
        "preview": _preview(item.get("3")),
        "political": _political_summary(item),
    }


def parse_creatives(raw, region=None, political=False):
    """SearchCreatives -> {"ads": [...], "next_token", "total_ads": {min, max}}."""
    ads = [_ad_summary(item, region, political) for item in (_get(raw, "1") or []) if isinstance(item, dict) and item.get("2")]
    return {
        "ads": ads,
        "next_token": _get(raw, "2") or None,
        "total_ads": _range(_get(raw, "4"), _get(raw, "5")),
    }


# ---- ads/details -------------------------------------------------------------

def _stats(entry):
    """A "17" region entry / the "19" total -> {first_shown, last_shown,
    impressions, platforms}."""
    platforms = []
    for p in (entry.get("8") or []):
        if isinstance(p, dict):
            platforms.append({"platform": _platform(p.get("1")), "impressions": _range(p.get("2"), p.get("3"))})
    return {
        "first_shown": _day(entry.get("4")),
        "last_shown": _day(entry.get("5")),
        "impressions": _range(entry.get("2"), entry.get("3")),
        "platforms": platforms or None,
    }


def _targeting(block):
    if not isinstance(block, dict):
        return None
    locations = [refs.country_of_region(c) for c in (_get(block, "3", "1") or [])]
    categories = block.get("4") if isinstance(block.get("4"), dict) else {}
    audience = {}
    for key, flags in categories.items():
        name = refs.TARGETING_CATEGORIES.get(_int(key), f"category_{key}")
        audience[name] = {
            "is_included": bool(_get(flags, "1")),
            "is_excluded": bool(_get(flags, "2")),
        }
    if not locations and not audience:
        return None
    return {
        "locations": [c for c in locations if c] or None,
        "audience_selection": audience or None,
    }


def _content_topic(value):
    """The content topic Google labelled the creative with (EU pages show
    it as "Topic (labelled by Google)"), id + label from refs.CONTENT_TOPICS."""
    topic_id = _int(value)
    if topic_id is None:
        return None
    return {"id": topic_id, "name": refs.CONTENT_TOPICS.get(topic_id)}


def parse_creative(raw, region=None, political=False):
    """GetCreativeById -> the creative record (variations without their
    copy, which api.py fills from the renders), or None for an empty answer."""
    cr = _get(raw, "1")
    if not isinstance(cr, dict) or not cr.get("2"):
        return None
    advertiser, creative = cr.get("1"), cr.get("2")
    variations = [{**_preview(v), "copy": None} for v in (cr.get("5") or []) if isinstance(v, dict)]
    region_stats = [{**_region_fields(e.get("1")), **_stats(e)} for e in (cr.get("17") or []) if isinstance(e, dict)]
    region_stats.sort(key=lambda s: (-((s["impressions"] or {}).get("min") or 0), s["region"] or ""))
    total = cr.get("19") if isinstance(cr.get("19"), dict) else None
    political_out = None
    if political or any(k in cr for k in ("9", "11", "12", "23")):
        totals = cr.get("23") if isinstance(cr.get("23"), dict) else {}
        political_out = {
            "regions": [r for r in (cr.get("7") or []) if isinstance(r, str)] or None,
            "impressions": _range(totals.get("2") or cr.get("9"), totals.get("3")),
            "spend": _spend(cr.get("11"), cr.get("12")),
            "first_shown": _day(totals.get("4")),
            "last_shown": _day(totals.get("5")),
        }
    return {
        "id": creative,
        "link": refs.creative_link(advertiser, creative, region, political) if advertiser else None,
        "advertiser": {
            "id": advertiser,
            "name": _get(cr, "22", "1") or None,
            "link": refs.advertiser_link(advertiser, region, political) if advertiser else None,
        },
        "format": _format(cr.get("8")),
        "topic": "political" if political else "commercial",
        "first_shown": _timestamp(cr.get("3")),
        "last_shown": _timestamp(cr.get("4")),
        "days_shown": _int(cr.get("6")),
        "content_topic": _content_topic(_get(cr, "16", "1", "1")),
        "copy": None,
        "variations": variations,
        "targeting": _targeting(cr.get("13")),
        "region_stats": region_stats or None,
        "region_stats_total": _stats(total) if total else None,
        "political": political_out,
    }


# ---- renders -----------------------------------------------------------------

def _js_unescape(text):
    def one(match):
        token = match.group(1)
        if token[0] in "xu" and len(token) > 1:
            return chr(int(token[1:], 16))
        return _JS_SIMPLE.get(token, token)
    return _JS_ESC_RE.sub(one, text)


def _data_blobs(soup):
    """Every data-p attribute (wiz model data: "%.@." + a JSON value, which
    the renderer follows with one stray closing bracket) decoded."""
    blobs = []
    decoder = json.JSONDecoder()
    for el in soup.find_all(attrs={"data-p": True}):
        raw = (el.get("data-p") or "").strip()
        if raw.startswith("%.@."):
            raw = raw[4:]
        try:
            value, _ = decoder.raw_decode(raw)
        except ValueError:
            continue
        blobs.append(value)
    return blobs


def _text_ad_blob(blob):
    """[1, [headline, description, domain, business, [[locations]], …]] -> fields."""
    if not (isinstance(blob, list) and len(blob) >= 2 and isinstance(blob[1], list) and len(blob[1]) >= 3):
        return None
    inner = blob[1]
    if not all(isinstance(v, str) or v is None for v in inner[:4]):
        return None
    if not any(isinstance(v, str) and v for v in inner[:2]):
        return None
    locations = []
    for loc in (inner[4] if len(inner) > 4 and isinstance(inner[4], list) else []):
        if not isinstance(loc, list):
            continue
        parts = [p if isinstance(p, str) and p else None for p in loc] + [None] * 7
        locations.append({"name": parts[0], "street": parts[1], "street_2": parts[2], "city": parts[3],
                          "region": parts[4], "postal_code": parts[5], "country": parts[6]})
    return {
        "headline": inner[0] or None,
        "description": inner[1] or None,
        "display_domain": inner[2] or None,
        "business_name": inner[3] if len(inner) > 3 else None,
        "locations": locations or None,
    }


def _product_blob(blob):
    """[thumbnail, title, brand] (a Shopping render) -> product."""
    if not (isinstance(blob, list) and len(blob) >= 2 and isinstance(blob[0], str)
            and blob[0].startswith("http") and isinstance(blob[1], str)):
        return None
    return {"title": blob[1] or None, "brand": blob[2] if len(blob) > 2 and isinstance(blob[2], str) and blob[2] else None,
            "image": blob[0]}


def _duration_seconds(text):
    """'0:32' / '1:02:05' -> 32 / 3725."""
    match = _DURATION_RE.match((text or "").strip())
    if not match:
        return None
    hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _ad_data(js):
    """The template data a display / YouTube render carries in its
    `var adData = {visible_url: '…', destination_url: '…',
    google_template_data: {'adData': [{'headline': '…', …}]}}` object
    (JS literal, single-quoted): headline, long headline, description,
    call to action, display URL and path, landing page, YouTube video id,
    channel, duration and thumbnail. The template's `video` field is a
    signed googlevideo.com MP4 link bound to the fetcher's IP, so it is
    never returned. None when the render has no such object (text ads,
    VAST-hosted video)."""
    text = _js_unescape(js or "")
    match = _AD_DATA_RE.search(text)
    top = {}
    for key, value in _JS_TOP_FIELD_RE.findall(text):
        top.setdefault(key, _js_unescape(value).strip())
    if not match and not top:
        return None
    data = {}
    if match:
        for key, value in _JS_PAIR_RE.findall(match.group(1)):
            data.setdefault(key, _js_unescape(value).strip())

    def pick(*keys):
        return next((data[k] for k in keys if data.get(k)), None)

    landing = pick("destination_url", "final_url") or top.get("destination_url") or top.get("final_url")
    path = [p for p in (pick("breadcrumb1"), pick("breadcrumb2")) if p]
    return {
        "headline": pick("headline"),
        "long_headline": pick("longHeadline"),
        "description": pick("description"),
        "call_to_action": pick("callToActionText", "button_label", "call_to_action"),
        "display_domain": pick("visible_url") or top.get("visible_url") or None,
        "display_path": "/".join(path) or None,
        "landing_link": landing if landing and landing.startswith("http") else None,
        "youtube_video_id": pick("video_videoId", "video_id"),
        "youtube_channel": pick("channelName"),
        "video_duration_seconds": _duration_seconds(pick("videoDuration", "video_duration")),
        "video_thumbnail": pick("highResThumbnail", "thumbnail"),
        "companion_banner": pick("companion_banner"),
    }


def parse_render(js):
    """A preview render (content.js) -> the ad copy, or None when the file
    holds no preview at all."""
    out = {"headline": None, "long_headline": None, "description": None, "call_to_action": None,
           "display_domain": None, "display_path": None, "landing_link": None, "business_name": None,
           "locations": None, "product": None, "youtube_video_id": None, "youtube_link": None,
           "youtube_channel": None, "video_duration_seconds": None, "video_thumbnail": None,
           "companion_banner": None, "image": None, "images": None, "text": None}
    found = False
    match = _HTML_CALL_RE.search(js or "")
    if match:
        found = True
        soup = BeautifulSoup(_js_unescape(match.group(1)), "lxml")
        for blob in _data_blobs(soup):
            text_ad = _text_ad_blob(blob)
            if text_ad and not out["headline"]:
                out.update(text_ad)
                continue
            product = _product_blob(blob)
            if product and not out["product"]:
                out["product"] = product
        for tag in soup(["script", "style", "noscript", "template", "title"]):
            tag.decompose()
        lines = []
        for piece in soup.stripped_strings:
            # the renderer's placeholders ("<Open Hours>", "[Price]",
            # "<Rating (Reviews)> · <Distance> · Memphis") are not ad copy
            line = " ".join(_PLACEHOLDER_RE.sub(" ", piece).split()).strip(" ·|-")
            if line and line not in lines:
                lines.append(line)
        out["text"] = lines or None
        images = []
        for img in soup.find_all("img"):
            src = img.get("src") or ""
            if src.startswith("http") and src not in images:
                images.append(src)
        out["images"] = images or None
    image_call = _IMAGE_CALL_RE.search(js or "")
    if image_call:
        found = True
        out["image"] = _js_unescape(image_call.group(1)) or None
    ad_data = _ad_data(js)
    if ad_data:
        found = True
        for key, value in ad_data.items():
            if value is not None and out.get(key) is None:
                out[key] = value
    video = _YOUTUBE_RE.search(js or "")
    if video:
        found = True
        out["youtube_video_id"] = out["youtube_video_id"] or video.group(1)
    if out["youtube_video_id"]:
        out["youtube_link"] = f"https://www.youtube.com/watch?v={out['youtube_video_id']}"
    return out if found else None


def merge_copy(variations):
    """The creative-level `copy`: the first variation copy with a headline,
    else the first with a product, else the first with any text / video."""
    copies = [v.get("copy") for v in variations if v.get("copy")]
    for key in ("headline", "product", "youtube_video_id", "text"):
        for copy in copies:
            if copy.get(key):
                return copy
    return copies[0] if copies else None
