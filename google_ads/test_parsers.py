"""Offline tests for the Google Ads Transparency Center parsers and the
transport's response classifier.

    python -m pytest google_ads/test_parsers.py -q

Fixtures are real anji RPC answers and preview renders captured 2026-11-03
(google_ads/fixtures/): suggestions, creative feeds (advertiser / domain /
political / unknown), creatives (text, image, video, EU impressions,
political, unknown), advertisers (commercial, political, unknown), four
renders and the bad-token error body. No network.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google_ads import fetch, parsers as P, refs  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
NIKE = "AR16735076323512287233"
NIKE_BV = "AR18378488041124659201"
MONEY = "AR10536869552476651521"


def fixture(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return json.load(f) if name.endswith(".json") else f.read()


# ---- advertisers/search ----------------------------------------------------------------

def test_parse_suggestions():
    out = P.parse_suggestions(fixture("suggestions_rpc_nike.json"))
    first = out["advertisers"][0]
    assert first == {
        "id": "AR06641858037806006273", "name": "Nike", "country": "KE", "is_verified": True,
        "ads_count": {"min": 1, "max": 1},
        "link": "https://adstransparency.google.com/advertiser/AR06641858037806006273?region=anywhere",
    }
    nike = next(a for a in out["advertisers"] if a["id"] == NIKE)
    assert nike["name"] == "Nike, Inc." and nike["country"] == "US"
    assert nike["ads_count"] == {"min": 9000, "max": 10000}
    assert nike["is_verified"] is False
    assert len(out["advertisers"]) == 10 and len(out["domains"]) == 10
    assert {"domain": "nike.com", "link": "https://adstransparency.google.com/?region=anywhere&domain=nike.com"} in out["domains"]
    assert out["next_token"]


def test_pick_advertiser_prefers_the_biggest_matching_name():
    advertisers = P.parse_suggestions(fixture("suggestions_rpc_nike.json"))["advertisers"]
    assert P.pick_advertiser(advertisers, "Nike")["id"] == NIKE          # Nike, Inc., 9,000+ ads
    assert P.pick_advertiser(advertisers, "nike srl")["name"] == "NIKE SRL"
    assert P.pick_advertiser(advertisers, "zzz")["id"] == NIKE           # no name match: the biggest
    assert P.pick_advertiser([], "Nike") is None


def test_parse_suggestions_nonsense():
    assert P.parse_suggestions(fixture("suggestions_rpc_nonsense.json")) == \
        {"advertisers": [], "domains": [], "next_token": None}
    assert P.parse_suggestions({})["advertisers"] == []


# ---- advertisers/details ---------------------------------------------------------------

def test_parse_advertiser():
    out = P.parse_advertiser(fixture("advertiser_rpc_nike.json"), "US")
    assert out == {
        "id": NIKE, "name": "Nike, Inc.", "legal_name": "Nike, Inc.", "country": "US", "is_verified": True,
        "link": f"https://adstransparency.google.com/advertiser/{NIKE}?region=US",
        "topics": ["commercial"], "political": None,
    }


def test_parse_advertiser_political():
    out = P.parse_advertiser(fixture("advertiser_rpc_money_metals_political.json"))
    assert out["name"] == "Money Metals Exchange LLC"
    assert out["topics"] == ["commercial", "political"]
    assert out["political"]["country"] == "US"
    assert set(out["political"]["regions"]) == {"US", "AS", "VI", "PR", "GU", "MP"}
    assert out["political"]["link"].endswith("?region=anywhere&topic=political")


def test_parse_advertiser_unknown():
    assert P.parse_advertiser(fixture("advertiser_rpc_unknown.json")) is None
    assert P.parse_advertiser({"1": {}}) is None


# ---- ads/search ------------------------------------------------------------------------

def test_parse_creatives_advertiser_page():
    out = P.parse_creatives(fixture("creatives_rpc_nike_page1.json"), "anywhere")
    assert len(out["ads"]) == 40
    assert out["next_token"]
    assert out["total_ads"] == {"min": 8000, "max": 9000}
    first = out["ads"][0]
    assert first["id"] == "CR01371934471284064257"
    assert first["link"] == f"https://adstransparency.google.com/advertiser/{NIKE}/creative/CR01371934471284064257?region=anywhere"
    assert first["advertiser"] == {"id": NIKE, "name": "Nike, Inc.",
                                   "link": f"https://adstransparency.google.com/advertiser/{NIKE}?region=anywhere"}
    assert first["domain"] is None
    assert first["format"] == "TEXT"
    assert first["first_shown"] == "2025-04-03T19:41:16Z"
    assert first["last_shown"].startswith("2026-11-03T")
    assert first["days_shown"] == 170
    assert first["preview"]["type"] == "image"
    assert first["political"] is None
    image = next(a for a in out["ads"] if a["id"] == "CR12797452823390322689")
    assert image["format"] == "IMAGE" and image["days_shown"] == 16
    assert image["first_shown"] == "2026-10-19T07:00:00Z"
    assert image["preview"]["type"] == "render" and image["preview"]["image"] is None
    assert image["preview"]["render_link"].startswith("https://displayads-formats.googleusercontent.com/ads/preview/content.js?")
    text = next(a for a in out["ads"] if a["id"] == "CR15578629406669668353")
    assert text["format"] == "TEXT" and text["days_shown"] == 909
    assert text["preview"] == {"type": "image", "width": 348, "height": 273, "render_link": None,
                               "image": "https://tpc.googlesyndication.com/archive/simgad/10568602953494613691"}


def test_parse_creatives_second_page_is_disjoint():
    page1 = P.parse_creatives(fixture("creatives_rpc_nike_page1.json"))
    page2 = P.parse_creatives(fixture("creatives_rpc_nike_page2.json"))
    assert len(page2["ads"]) == 40 and page2["next_token"]
    assert not {a["id"] for a in page1["ads"]} & {a["id"] for a in page2["ads"]}


def test_parse_creatives_domain_search():
    out = P.parse_creatives(fixture("creatives_rpc_domain_nike_gb.json"), "GB")
    assert out["total_ads"] == {"min": 2000, "max": 3000}
    first = out["ads"][0]
    assert first["id"] == "CR12206472564775583745"
    assert first["domain"] == "nike.com"
    assert first["advertiser"]["id"] == NIKE_BV and first["advertiser"]["name"] == "Nike Retail BV"
    assert first["format"] == "TEXT" and first["days_shown"] == 1797
    assert first["first_shown"] == "2021-10-25T07:00:00Z"
    assert first["link"].endswith("?region=GB")


def test_parse_creatives_political_feed():
    out = P.parse_creatives(fixture("creatives_rpc_political_us.json"), "US", political=True)
    assert len(out["ads"]) == 20 and out["next_token"]
    assert out["total_ads"] is None
    first = out["ads"][0]
    assert first["id"] == "CR17560398381572947969" and first["advertiser"]["name"] == "HMP"
    assert first["format"] == "VIDEO" and first["days_shown"] == 7
    assert first["political"] == {
        "regions": ["US"],
        "impressions": {"min": 900000, "max": 1000000},
        "spend": {"min": {"amount": 30000, "currency": "USD"}, "max": {"amount": 35000, "currency": "USD"}},
    }
    assert first["link"].endswith("?region=US&topic=political")
    assert all(a["political"] for a in out["ads"])


def test_parse_creatives_video_filter():
    out = P.parse_creatives(fixture("creatives_rpc_nike_bv_video_youtube.json"))
    assert out["ads"] and all(a["format"] == "VIDEO" for a in out["ads"])
    assert all(a["preview"]["type"] == "render" for a in out["ads"])


@pytest.mark.parametrize("name", ["creatives_rpc_unknown_advertiser.json", "creatives_rpc_unknown_domain.json"])
def test_parse_creatives_empty(name):
    assert P.parse_creatives(fixture(name)) == {"ads": [], "next_token": None, "total_ads": None}


# ---- ads/details -----------------------------------------------------------------------

def test_parse_creative_text():
    out = P.parse_creative(fixture("creative_rpc_nike_text.json"), "US")
    assert out["id"] == "CR15578629406669668353"
    assert out["link"] == f"https://adstransparency.google.com/advertiser/{NIKE}/creative/CR15578629406669668353?region=US"
    assert out["advertiser"] == {"id": NIKE, "name": "Nike, Inc.",
                                 "link": f"https://adstransparency.google.com/advertiser/{NIKE}?region=US"}
    assert out["format"] == "TEXT" and out["topic"] == "commercial"
    assert out["first_shown"] is None and out["last_shown"].startswith("2026-11-03T")
    assert out["days_shown"] is None
    assert out["content_topic"] is None
    assert out["copy"] is None
    assert [v["type"] for v in out["variations"]] == ["image", "image", "image", "render"]
    assert out["variations"][0]["image"] == "https://tpc.googlesyndication.com/archive/simgad/10568602953494613691"
    assert out["variations"][3]["render_link"].startswith("https://displayads-formats.googleusercontent.com/")
    assert all(v["copy"] is None for v in out["variations"])
    assert out["region_stats"] == [{"region": "US", "region_name": "United States", "first_shown": None,
                                    "last_shown": "2026-11-03", "impressions": None, "platforms": None}]
    assert out["region_stats_total"] is None
    assert out["targeting"] is None
    assert out["political"] is None


def test_parse_creative_eu_impressions():
    out = P.parse_creative(fixture("creative_rpc_nike_bv_eu_impressions.json"), "NL")
    assert out["format"] == "TEXT"
    assert out["content_topic"] == {"id": 10021, "name": "Apparel"}
    poland = out["region_stats"][0]
    assert poland["region"] == "PL" and poland["region_name"] == "Poland"
    assert poland["impressions"] == {"min": 175000, "max": 200000}
    assert poland["first_shown"] == "2025-10-24" and poland["last_shown"] == "2026-11-03"
    assert poland["platforms"] == [{"platform": "SEARCH", "impressions": {"min": 175000, "max": 200000}},
                                   {"platform": "SHOPPING", "impressions": {"min": None, "max": 1000}}]
    assert len(out["region_stats"]) == 11
    assert out["region_stats_total"]["impressions"] == {"min": 175000, "max": 200000}
    assert out["targeting"] == {"locations": None, "audience_selection": {
        "demographic_info": {"is_included": True, "is_excluded": False},
        "geographic_locations": {"is_included": True, "is_excluded": False},
        "contextual_signals": {"is_included": True, "is_excluded": False},
    }}
    assert out["political"] is None


def test_parse_creative_video():
    out = P.parse_creative(fixture("creative_rpc_nike_bv_video.json"))
    assert out["format"] == "VIDEO"
    assert [v["type"] for v in out["variations"]] == ["render"]
    assert set(out["targeting"]["audience_selection"]) == set(refs.TARGETING_CATEGORIES.values())
    assert out["targeting"]["audience_selection"]["geographic_locations"] == {"is_included": True, "is_excluded": True}
    assert out["region_stats"][0]["region"] == "IE"


def test_parse_creative_political():
    out = P.parse_creative(fixture("creative_rpc_political_money_metals.json"), "US", political=True)
    assert out["topic"] == "political" and out["format"] == "TEXT"
    assert out["advertiser"]["id"] == MONEY
    assert out["link"].endswith("?region=US&topic=political")
    assert out["first_shown"] == "2023-11-28T07:01:01Z" and out["days_shown"] == 1060
    assert out["political"]["impressions"] == {"min": 10000000, "max": None}
    assert out["political"]["spend"] == {"min": {"amount": 1500000, "currency": "USD"},
                                         "max": {"amount": 2000000, "currency": "USD"}}
    assert out["political"]["first_shown"] == "2023-11-27" and out["political"]["last_shown"] == "2026-11-03"
    assert "US" in out["political"]["regions"] and len(out["political"]["regions"]) > 100
    assert out["targeting"]["locations"] == ["US"]
    us = out["region_stats"][0]
    assert us["region"] == "US" and us["impressions"] == {"min": 10000000, "max": None}
    assert us["first_shown"] == "2023-11-27" and us["last_shown"] == "2026-11-03"
    assert len(out["region_stats"]) == 133
    total = out["region_stats_total"]
    assert total["impressions"] == {"min": 100000, "max": 125000}
    assert {p["platform"] for p in total["platforms"]} == {"YOUTUBE", "SEARCH", "SHOPPING"}


def test_parse_creative_unknown():
    assert P.parse_creative(fixture("creative_rpc_unknown.json")) is None
    assert P.parse_creative({}) is None


# ---- renders ---------------------------------------------------------------------------

def test_parse_render_text_ad():
    out = P.parse_render(fixture("render_nike_text.js"))
    assert out["headline"] == "Nike® Official Site"
    assert out["description"].startswith("Shop the new Nike® softball cleats")
    assert out["display_domain"] == "nike.com" and out["business_name"] == "Nike"
    assert out["locations"] == [{"name": "Nike Clearance Store - Memphis", "street": "4099 South Plaza Drive",
                                 "street_2": None, "city": "Memphis", "region": "Tennessee",
                                 "postal_code": "38116", "country": "US"}]
    assert out["product"] is None and out["youtube_video_id"] is None
    assert "Sponsored" in out["text"] and "Nike® Official Site" in out["text"]
    assert "Memphis" in out["text"] and "4099 South Plaza Drive" in out["text"]
    assert not any("<" in line or "[" in line for line in out["text"])
    assert "Local Ad Rendering Service" not in out["text"]


def test_parse_render_shopping_ad():
    out = P.parse_render(fixture("render_nike_image.js"))
    assert out["headline"] is None
    assert out["product"]["title"].startswith("Nick Emmanwori Seattle Seahawks Nike")
    assert out["product"]["brand"] == "Nike"
    assert out["product"]["image"].startswith("https://encrypted-tbn3.gstatic.com/shopping?q=tbn:")
    assert out["product"]["image"] in out["images"]
    assert out["product"]["title"] in out["text"]


def test_parse_render_video_ad():
    out = P.parse_render(fixture("render_nike_bv_video.js"))
    assert out["youtube_video_id"] == "5fMrOgp_W1U"
    assert out["youtube_link"] == "https://www.youtube.com/watch?v=5fMrOgp_W1U"
    # the render's adData template carries the copy of display / YouTube ads
    assert out["headline"] == "The Official Nike Site"
    assert out["long_headline"].startswith("Nike Products Designed For Performance")
    assert out["description"] == "Choose Nike And Make Your Mark On The World."
    assert out["call_to_action"] == "Shop now"
    assert out["display_domain"] == "nike.com"
    assert out["landing_link"] == "https://www.nike.com/ie/"
    assert out["youtube_channel"] == "Nike"
    assert out["video_duration_seconds"] == 12
    assert out["video_thumbnail"] == "https://i3.ytimg.com/vi/5fMrOgp_W1U/hqdefault.jpg"
    # the template's signed MP4 link is bound to the fetcher's IP: never returned
    assert "googlevideo" not in json.dumps(out)


def test_ad_data_handles_youtube_player_layout():
    js = ("var adData = {google_template_data: {'adData': [{'layout': 'youtube_player_media_mobile', "
          "'video_id': 'Lwt39yBJWQg', 'destination_url': 'https://www.netflix.com/title/81426967', "
          "'video_duration': '0:15', 'visible_url': 'netflix.com', 'headline': 'Moje \\u017cycie z Walterami', "
          "'button_label': 'Ogl\\u0105daj', 'channelName': 'Netflix Polska', 'breadcrumb1': 'Netflix', 'breadcrumb2': 'Polska'}]}};")
    out = P._ad_data(js)
    assert out["youtube_video_id"] == "Lwt39yBJWQg"
    assert out["landing_link"] == "https://www.netflix.com/title/81426967"
    assert out["headline"] == "Moje życie z Walterami" and out["call_to_action"] == "Oglądaj"
    assert out["display_domain"] == "netflix.com" and out["display_path"] == "Netflix/Polska"
    assert out["video_duration_seconds"] == 15 and out["youtube_channel"] == "Netflix Polska"
    assert P._ad_data("(function(){})();") is None
    assert P._duration_seconds("1:02:05") == 3725 and P._duration_seconds("") is None


def test_parse_render_image_only():
    out = P.parse_render(fixture("render_political.js"))
    assert out["image"] == "https://i.ytimg.com/vi/PY4al1mJgCQ/hqdefault.jpg"
    assert out["youtube_video_id"] == "PY4al1mJgCQ"
    assert out["text"] is None


def test_parse_render_empty():
    assert P.parse_render("") is None
    assert P.parse_render("(function(){})();") is None


def test_merge_copy_prefers_a_headline():
    variations = [{"copy": None}, {"copy": {"headline": None, "product": {"title": "x"}}},
                  {"copy": {"headline": "H", "product": None}}]
    assert P.merge_copy(variations)["headline"] == "H"
    assert P.merge_copy([{"copy": None}]) is None


# ---- the transport's classifier --------------------------------------------------------

class _Resp:
    def __init__(self, status, text, url="https://adstransparency.google.com/anji/_/rpc/x"):
        self.status_code, self.text, self.url = status, text, url


def test_classify_maps_the_site_errors():
    bad_token = json.dumps(fixture("creatives_rpc_bad_token.json"))
    with pytest.raises(fetch.GoogleAdsBadRequest):
        fetch._classify(_Resp(500, bad_token), "x")
    with pytest.raises(fetch.GoogleAdsBadRequest):
        fetch._classify(_Resp(400, '{"2":"Trouble converting f.req"}'), "x")
    with pytest.raises(fetch.GoogleAdsBlocked):
        fetch._classify(_Resp(403, ""), "x")
    with pytest.raises(fetch.GoogleAdsBlocked):
        fetch._classify(_Resp(429, ""), "x")
    with pytest.raises(fetch.GoogleAdsBlocked):
        fetch._classify(_Resp(200, "<html>", url="https://www.google.com/sorry/index"), "x")
    with pytest.raises(fetch.GoogleAdsUpstreamError):
        fetch._classify(_Resp(503, ""), "x")
    assert fetch._classify(_Resp(200, "{}"), "x") == "{}"
    assert issubclass(fetch.GoogleAdsBlocked, fetch.GoogleAdsUpstreamError)
