"""Live endpoint smoke tests: one call per /google-ads/* route against a
running service, with example values proven to return data (2026-11-03).
The listing tooling reads these calls as each route's working example.

Skipped unless GOOGLE_ADS_BASE points at a running service:

    ONLY_SCRAPER=google-ads python run.py --dev
    GOOGLE_ADS_BASE=http://127.0.0.1:6002 python -m pytest google_ads/test_endpoints.py -q
"""
import os

import pytest

BASE = os.environ.get("GOOGLE_ADS_BASE", "").rstrip("/")

pytestmark = pytest.mark.skipif(not BASE, reason="set GOOGLE_ADS_BASE to run live endpoint tests")

TESLA = "AR17828074650563772417"           # Tesla Inc., ~6,000 ads
TESLA_AD = "CR17779141263526723585"        # "Lowest Price Guaranteed", impressions in 4 countries


def call(path, status=200, **params):
    from curl_cffi import requests
    resp = requests.get(BASE + path, params=params, timeout=300)
    assert resp.status_code == status, f"{path} {params} -> {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body, f"{path} returned an empty body"
    return body


def test_ad_details():
    body = call("/google-ads/ads/details", ad="CR17779141263526723585")
    assert body["id"] == TESLA_AD and body["advertiser"]["name"] == "Tesla Inc."
    assert body["format"] == "TEXT" and body["copy"]["headline"]
    assert any(r["impressions"] for r in body["region_stats"])
    call("/google-ads/ads/details", status=404, ad="CR00000000000000000001")


def test_ads_search():
    body = call("/google-ads/ads/search", query="tesla.com")
    assert body["results"] and body["next"] and body["total_ads"]["min"] >= 100
    assert all(ad["id"].startswith("CR") and ad["format"] for ad in body["results"])
    page2 = call("/google-ads/ads/search", query="tesla.com", page=2)
    assert not {a["id"] for a in body["results"]} & {a["id"] for a in page2["results"]}
    video = call("/google-ads/ads/search", query=TESLA, format="video", platform="youtube", limit=5)
    assert all(ad["format"] == "VIDEO" for ad in video["results"])


def test_advertisers_search():
    body = call("/google-ads/advertisers/search", query="tesla")
    assert any(a["id"] == TESLA for a in body["results"])
    assert any(d["domain"] == "tesla.com" for d in body["domains"])


def test_advertiser_details():
    body = call("/google-ads/advertisers/details", advertiser="AR17828074650563772417")
    assert body["name"] == "Tesla Inc." and body["country"] == "US"
    assert body["ads_count"]["min"] >= 1000
    call("/google-ads/advertisers/details", status=404, advertiser="AR00000000000000000001")


def test_political_search():
    body = call("/google-ads/political/search", region="US")
    assert body["results"] and all(ad["political"] for ad in body["results"])
    call("/google-ads/political/search", status=400)
