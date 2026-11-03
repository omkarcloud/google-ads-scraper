"""The /google-ads/* endpoint functions (route_glue's route_table calls them
with the schema's loaded kwargs).

Every endpoint caches its own response here (tofler-style, keyed on the
validated params). The two feeds (ads/search, political/search) are paged
the site's way — an opaque continuation token per page — but served as
plain page numbers: page N asks the cache for page N-1 (which stored the
token of the page after it in its `pagination` block, popped by
route_glue.paginate before the response leaves) and follows that token,
so a client walking the pages pays one upstream call per page and a
client jumping to page N pays at most N. A page past the end is an
empty page.

ads/details makes one lookup (two for a political creative, which only
answers under the political topic) plus one GET per variation that has a
preview render, where the ad copy lives.
"""
import math

from cache import DontCache, cached_call
from google_ads import cache_config as ttl
from google_ads import parsers, refs
from google_ads.fetch import (GoogleAdsNotFound, GoogleAdsUpstreamError, get_advertiser, get_creative, render,
                              search_creatives, search_suggestions)


# ---- advertisers/search --------------------------------------------------------------

def _advertisers_search(query, limit):
    parsed = parsers.parse_suggestions(search_suggestions(query, limit, limit))
    advertisers = parsed["advertisers"][:limit]
    return {
        "query": query,
        "count": len(advertisers),
        "results": advertisers,
        "domains": parsed["domains"][:limit],
    }


def advertisers_search(**data):
    """Find advertisers by brand name or domain: advertiser id, name, country,
    verification and ad-count range, plus the matching domains."""
    return cached_call("google-ads.advertisers_search", data, _advertisers_search, ttl.SUGGESTIONS_CACHE)


# ---- advertisers/details -------------------------------------------------------------

def _region_codes(region):
    code = refs.region_code(region)
    return [code] if code else None


def _advertiser_details(advertiser, region):
    record = parsers.parse_advertiser(get_advertiser(advertiser), region)
    if record is None:
        raise GoogleAdsNotFound(f"advertiser {advertiser} not found")
    # the cheap count call: a zero-size page answers the total range alone
    counts = parsers.parse_creatives(search_creatives(advertiser=advertiser, region_codes=_region_codes(region),
                                                      page_size=0), region)
    record["region"] = region
    record["ads_count"] = counts["total_ads"]
    return record


def advertiser_details(**data):
    """One advertiser's profile: name, legal name, country, verification,
    topics (commercial / political), political regions and how many ads it
    runs in the region."""
    return cached_call("google-ads.advertiser_details", data, _advertiser_details, ttl.ADVERTISER_CACHE)


# ---- ads/search + political/search ---------------------------------------------------

def _resolve_name(name):
    """A brand / advertiser name -> the site's best advertiser for it
    (parsers.pick_advertiser over the site's own suggestions)."""
    advertisers = parsers.parse_suggestions(search_suggestions(name, refs.SUGGESTIONS_MAX, 0))["advertisers"]
    best = parsers.pick_advertiser(advertisers, name)
    if best is None:
        raise GoogleAdsNotFound(f"no advertiser named {name!r}")
    return {"id": best["id"], "name": best["name"], "link": best["link"]}


def resolve_name(name):
    return cached_call("google-ads.resolve_name", {"name": name}, _resolve_name, ttl.RESOLVE_CACHE)


def _yyyymmdd(value):
    return int(value.replace("-", "")) if value else None


def _empty_page(page, limit):
    return {"page": page, "items_per_page": limit, "has_next": False, "total_pages": None,
            "total_count": None, "next_token": None}


def _feed_page(political, data):
    query, region, page, limit = data["query"], data["region"], data["page"], data["limit"]
    endpoint = political_search if political else ads_search
    token = None
    if page > 1:
        previous = endpoint(**{**data, "page": page - 1})
        token = (previous.get("pagination") or {}).get("next_token")
    # what the query names
    target = {"kind": None, "value": None, "advertiser": None, "domain": None}
    advertiser_id = domain = None
    if query:
        kind = refs.classify_query(query)
        target["kind"], target["value"] = kind, query
        if kind == "advertiser":
            advertiser_id = query
            target["advertiser"] = {"id": query, "link": refs.advertiser_link(query, region, political)}
        elif kind == "domain":
            domain = query
            target["domain"] = {"domain": query, "link": refs.domain_link(query, region)}
        else:
            resolved = resolve_name(query)
            advertiser_id = resolved["id"]
            target["advertiser"] = {**resolved, "link": refs.advertiser_link(advertiser_id, region, political)}
    if page > 1 and not token:
        parsed = {"ads": [], "next_token": None, "total_ads": None}
    else:
        raw = search_creatives(advertiser=advertiser_id, domain=domain, region_codes=_region_codes(region),
                               format_code=data.get("format"), platform_codes=data.get("platform"),
                               start=_yyyymmdd(data.get("start_date")), end=_yyyymmdd(data.get("end_date")),
                               page_size=limit, token=token, political=political)
        parsed = parsers.parse_creatives(raw, region, political)
        if not parsed["ads"] and page == 1 and advertiser_id and not token:
            # an unknown advertiser id answers an empty object, exactly like
            # an advertiser with no ads under these filters: tell them apart
            if parsers.parse_advertiser(get_advertiser(advertiser_id)) is None:
                raise GoogleAdsNotFound(f"advertiser {advertiser_id} not found")
    total = parsed["total_ads"]
    exact_total = total["max"] if total and total["min"] is not None and total["min"] == total["max"] else None
    pagination = {
        "page": page,
        "items_per_page": limit,
        "has_next": bool(parsed["next_token"]) and bool(parsed["ads"]),
        "total_pages": math.ceil(exact_total / limit) if exact_total else None,
        "total_count": exact_total,
        "next_token": parsed["next_token"] if parsed["ads"] else None,
    }
    return {
        "query": target,
        "region": region,
        "topic": "political" if political else "commercial",
        "format": next((k.upper() for k, v in refs.FORMATS.items() if v == data.get("format")), None),
        "platform": [refs.PLATFORM_NAMES[p] for p in (data.get("platform") or [])] or None,
        "start_date": data.get("start_date"),
        "end_date": data.get("end_date"),
        "total_ads": total,
        "results": parsed["ads"],
        "pagination": pagination,
    }


def _ads_search(**data):
    return _feed_page(False, data)


def ads_search(**data):
    """Every ad an advertiser or a domain runs, newest first, up to 100 a
    page: ad id, advertiser, format, first / last shown, days shown and the
    preview image, filtered by region, format, platform and date window."""
    return cached_call("google-ads.ads_search", data, _ads_search, ttl.ADS_CACHE)


def _political_search(**data):
    return _feed_page(True, data)


def political_search(**data):
    """The political ads shown in one country, optionally of one advertiser
    or domain: spend range, impressions range and the regions each ad ran
    in, with the same filters as ads/search."""
    return cached_call("google-ads.political_search", data, _political_search, ttl.ADS_CACHE)


# ---- ads/details ---------------------------------------------------------------------

def _ad_details(ad, region):
    raw, political = get_creative(ad), False
    record = parsers.parse_creative(raw, region)
    if record is None:
        # a political creative answers only under the political topic
        raw, political = get_creative(ad, political=True), True
        record = parsers.parse_creative(raw, region, political=True)
    if record is None:
        raise GoogleAdsNotFound(f"ad {ad} not found")
    if not record["advertiser"]["name"] and record["advertiser"]["id"]:
        # a political creative carries no advertiser name; one lookup does
        advertiser = parsers.parse_advertiser(get_advertiser(record["advertiser"]["id"]))
        if advertiser:
            record["advertiser"]["name"] = advertiser["name"]
    failed = False
    rendered = 0
    for variation in record["variations"]:
        link = variation.get("render_link")
        if not link or rendered >= refs.RENDERS_MAX:
            continue
        rendered += 1
        try:
            variation["copy"] = parsers.parse_render(render(link))
        except GoogleAdsUpstreamError as e:
            print(f"google-ads: render of {ad} failed: {e}")
            failed = True
    record["copy"] = parsers.merge_copy(record["variations"])
    record["region"] = region
    # a record missing its copy because a render failed is served but not
    # kept, so the next call tries the renders again
    return DontCache(record) if failed else record


def ad_details(**data):
    """One ad in full: the ad copy (headline, description, display domain,
    business name and address, Shopping product, YouTube video), every
    variation, per-country impression ranges by platform, audience
    targeting, content topic and political spend."""
    return cached_call("google-ads.ad_details", data, _ad_details, ttl.AD_CACHE)
