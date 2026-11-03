"""Cache TTL per /google-ads/* endpoint (cache.py, keyed on the validated
params, so region and every filter are part of the key). The Transparency
Center refreshes once a day (a creative's "last shown" moves by a day, new
creatives appear with a lag of days), so hours of caching never serve a
materially stale page.
"""
from datetime import timedelta

# advertisers/search: the suggestions index moves when advertisers verify.
SUGGESTIONS_CACHE = timedelta(hours=12)
# advertisers/details: name / legal name / verification change rarely; the
# ad-count range it carries moves by the day.
ADVERTISER_CACHE = timedelta(hours=12)
# A brand name resolved to its advertiser id (ads/search by name).
RESOLVE_CACHE = timedelta(hours=12)
# ads/search and political/search pages: new creatives land daily; each
# page is keyed on its filters and page number and carries the token of the
# next one, so page N+1 rides page N's cached row.
ADS_CACHE = timedelta(hours=3)
# ads/details: variations and region stats refresh daily.
AD_CACHE = timedelta(hours=12)
