"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json. Params go through the same schemas the API uses, so defaults
are filled in and an ID or any Transparency Center link both work.
"""
import json
import os

from google_ads import api, schemas

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


def run(schema_cls, fn, **params):
    return fn(**schema_cls().load(params))


if __name__ == "__main__":
    # an ad ID or any Transparency Center ad link — the full ad: copy,
    # variations, impressions by country and platform, targeting
    save("ad_tesla.json", run(schemas.AdSchema, api.ad_details, ad="CR17779141263526723585"))

    # every ad a domain (or advertiser, or brand name) runs, 40 per page
    save("ads_tesla_com.json", run(schemas.AdsSearchSchema, api.ads_search, query="tesla.com"))

    # brand name -> advertiser IDs and matching domains
    save("advertisers_tesla.json", run(schemas.AdvertisersSearchSchema, api.advertisers_search, query="tesla"))
