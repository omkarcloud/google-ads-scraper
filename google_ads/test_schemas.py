"""Offline tests for the /google-ads/* request schemas and reference
resolvers.

    python -m pytest google_ads/test_schemas.py -q
"""
import os
import sys

import pytest
from marshmallow import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google_ads import refs, schemas  # noqa: E402

AR = "AR16735076323512287233"
CR = "CR09405416287280037889"
CREATIVE_LINK = f"https://adstransparency.google.com/advertiser/{AR}/creative/{CR}?region=US"


def _load(schema, data):
    return schema().load(data)


def _error(schema, data):
    with pytest.raises(ValidationError) as info:
        schema().load(data)
    return info.value.normalized_messages()


# ---- refs --------------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    (AR, AR), (AR.lower(), AR),
    (f"https://adstransparency.google.com/advertiser/{AR}?region=US", AR),
    (f"https://adstransparency.google.com/advertiser/{AR}", AR),
    (CREATIVE_LINK, AR),
    (f"//adstransparency.google.com/advertiser/{AR}?region=anywhere&topic=political", AR),
])
def test_resolve_advertiser(value, expected):
    assert refs.resolve_advertiser(value) == expected


@pytest.mark.parametrize("value", ["", "nike", "AR123", "https://example.com/advertiser/" + AR,
                                   "https://adstransparency.google.com/?region=US"])
def test_resolve_advertiser_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_advertiser(value)


@pytest.mark.parametrize("value,expected", [
    (CR, CR), (CR.lower(), CR), (CREATIVE_LINK, CR),
])
def test_resolve_ad(value, expected):
    assert refs.resolve_ad(value) == expected


@pytest.mark.parametrize("value", ["", AR, "CR1", f"https://adstransparency.google.com/advertiser/{AR}?region=US",
                                   "https://example.com/creative/" + CR])
def test_resolve_ad_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_ad(value)


@pytest.mark.parametrize("value,expected,kind", [
    (AR, AR, "advertiser"),
    (f"https://adstransparency.google.com/advertiser/{AR}?region=DE", AR, "advertiser"),
    ("nike.com", "nike.com", "domain"),
    ("WWW.Nike.com", "nike.com", "domain"),
    ("https://www.nike.com/w/mens-shoes", "nike.com", "domain"),
    ("https://adstransparency.google.com/?region=US&domain=nike.com", "nike.com", "domain"),
    ("Nike", "Nike", "name"),
    ("Nike, Inc.", "Nike, Inc.", "name"),
])
def test_resolve_ads_query(value, expected, kind):
    resolved = refs.resolve_ads_query(value)
    assert resolved == expected
    assert refs.classify_query(resolved) == kind


@pytest.mark.parametrize("value", ["", "   ", "https://adstransparency.google.com/?region=US", "x" * 101])
def test_resolve_ads_query_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_ads_query(value)


def test_region_codes_follow_iso_numeric():
    assert refs.region_code("US") == 2840
    assert refs.region_code("gb") == 2826
    assert refs.region_code("DE") == 2276
    assert refs.region_code("anywhere") is None
    assert refs.region_code("ZZ") is None
    assert refs.country_of_region(2616) == "PL"
    assert refs.country_of_region("2840") == "US"
    assert refs.country_of_region(1) == "1"
    assert refs.country_name("NL") == "Netherlands"
    assert refs.CONTENT_TOPICS[10021] == "Apparel"


def test_links():
    assert refs.advertiser_link(AR) == f"https://adstransparency.google.com/advertiser/{AR}?region=anywhere"
    assert refs.advertiser_link(AR, "US", political=True) == \
        f"https://adstransparency.google.com/advertiser/{AR}?region=US&topic=political"
    assert refs.creative_link(AR, CR, "DE") == f"https://adstransparency.google.com/advertiser/{AR}/creative/{CR}?region=DE"
    assert refs.domain_link("nike.com", "GB") == "https://adstransparency.google.com/?region=GB&domain=nike.com"
    assert refs.political_link("US") == "https://adstransparency.google.com/political?region=US"


def test_link_params():
    assert refs.link_params(CREATIVE_LINK) == {"region": "US"}
    assert refs.link_params(f"https://adstransparency.google.com/advertiser/{AR}?region=anywhere") == {}
    assert refs.link_params(AR) == {}
    assert refs.link_params("https://www.nike.com/?region=US") == {}


# ---- advertisers/search ------------------------------------------------------------------

def test_advertisers_search_schema():
    assert _load(schemas.AdvertisersSearchSchema, {"query": " nike "}) == {"query": "nike", "limit": 20}
    assert _load(schemas.AdvertisersSearchSchema, {"query": "nike", "limit": "100"})["limit"] == 100
    assert "query" in _error(schemas.AdvertisersSearchSchema, {})
    assert "limit" in _error(schemas.AdvertisersSearchSchema, {"query": "nike", "limit": "101"})
    assert "limit" in _error(schemas.AdvertisersSearchSchema, {"query": "nike", "limit": "0"})


# ---- advertisers/details -----------------------------------------------------------------

def test_advertiser_schema_accepts_id_and_link():
    assert _load(schemas.AdvertiserSchema, {"advertiser": AR.lower()}) == {"advertiser": AR, "region": "anywhere"}
    loaded = _load(schemas.AdvertiserSchema, {"advertiser": f"https://adstransparency.google.com/advertiser/{AR}?region=DE"})
    assert loaded == {"advertiser": AR, "region": "DE"}
    # an explicit region wins over the link's
    loaded = _load(schemas.AdvertiserSchema, {"advertiser": CREATIVE_LINK, "region": "gb"})
    assert loaded == {"advertiser": AR, "region": "GB"}


@pytest.mark.parametrize("value", ["", "nike", "https://example.com/advertiser/" + AR])
def test_advertiser_schema_rejects(value):
    messages = _error(schemas.AdvertiserSchema, {"advertiser": value})
    assert "advertiser" in messages


def test_advertiser_schema_rejects_sibling_params():
    assert "url" in _error(schemas.AdvertiserSchema, {"advertiser": AR, "url": "x"})


def test_region_field():
    assert _load(schemas.AdvertiserSchema, {"advertiser": AR, "region": "Anywhere"})["region"] == "anywhere"
    assert _load(schemas.AdvertiserSchema, {"advertiser": AR, "region": "us"})["region"] == "US"
    messages = _error(schemas.AdvertiserSchema, {"advertiser": AR, "region": "USA"})
    assert messages["region"][0].startswith("Must be a 2-letter ISO country code")


# ---- ads/search --------------------------------------------------------------------------

def test_ads_search_defaults():
    loaded = _load(schemas.AdsSearchSchema, {"query": "nike.com"})
    assert loaded == {"query": "nike.com", "region": "anywhere", "format": None, "platform": None,
                      "start_date": None, "end_date": None, "page": 1, "limit": 40}


def test_ads_search_filters():
    loaded = _load(schemas.AdsSearchSchema, {
        "query": f"https://adstransparency.google.com/advertiser/{AR}?region=US",
        "format": "Video", "platform": "youtube, search,YOUTUBE", "start_date": "2026-01-01",
        "end_date": "2026-10-01", "page": "3", "limit": "100"})
    assert loaded["query"] == AR
    assert loaded["region"] == "US"
    assert loaded["format"] == 3
    assert loaded["platform"] == [3, 5]
    assert loaded["start_date"] == "2026-01-01" and loaded["end_date"] == "2026-10-01"
    assert loaded["page"] == 3 and loaded["limit"] == 100


def test_ads_search_rejects():
    assert "query" in _error(schemas.AdsSearchSchema, {})
    assert "format" in _error(schemas.AdsSearchSchema, {"query": "nike", "format": "gif"})
    assert "platform" in _error(schemas.AdsSearchSchema, {"query": "nike", "platform": "display"})
    assert "start_date" in _error(schemas.AdsSearchSchema, {"query": "nike", "start_date": "2026/01/01"})
    assert "end_date" in _error(schemas.AdsSearchSchema, {"query": "nike", "start_date": "2026-02-01", "end_date": "2026-01-01"})
    assert "limit" in _error(schemas.AdsSearchSchema, {"query": "nike", "limit": "101"})
    assert "page" in _error(schemas.AdsSearchSchema, {"query": "nike", "page": "0"})
    assert "page" in _error(schemas.AdsSearchSchema, {"query": "nike", "page": str(refs.MAX_PAGE + 1)})
    assert "url" in _error(schemas.AdsSearchSchema, {"query": "nike", "url": "x"})


# ---- political/search --------------------------------------------------------------------

def test_political_search_needs_a_country():
    loaded = _load(schemas.PoliticalSearchSchema, {"region": "us"})
    assert loaded["region"] == "US" and loaded["query"] is None and loaded["page"] == 1
    assert "region" in _error(schemas.PoliticalSearchSchema, {})
    messages = _error(schemas.PoliticalSearchSchema, {"region": "anywhere"})
    assert "political feed is per country" in messages["region"][0]
    loaded = _load(schemas.PoliticalSearchSchema, {"region": "US", "query": "actblue.com", "format": "text"})
    assert loaded["query"] == "actblue.com" and loaded["format"] == 1


# ---- ads/details -------------------------------------------------------------------------

def test_ad_schema():
    assert _load(schemas.AdSchema, {"ad": CR.lower()}) == {"ad": CR, "region": "anywhere"}
    assert _load(schemas.AdSchema, {"ad": CREATIVE_LINK}) == {"ad": CR, "region": "US"}
    messages = _error(schemas.AdSchema, {"ad": AR})
    assert messages["ad"][0].startswith("Must be a creative id")
    assert "ad" in _error(schemas.AdSchema, {})
