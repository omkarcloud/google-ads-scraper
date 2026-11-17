"""Configuration for the Google Ads Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT                port the API listens on (default 8000)
    GOOGLE_ADS_PROXY    proxy URL for every request, e.g.
                        http://user:pass@host:port (default: none — direct).
                        The Google Ads Transparency Center answers home,
                        office and cloud server IPs alike, so you very likely
                        don't need this. Set it only if Google starts showing
                        its "unusual traffic" page at high volume.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

GOOGLE_ADS_PROXY = os.environ.get("GOOGLE_ADS_PROXY") or None


def google_ads_proxy(*args, **kwargs):
    """The proxy for one curl session (None = direct). A failed request drops
    its session, so a rotating proxy hands the retry a fresh IP."""
    return os.environ.get("GOOGLE_ADS_PROXY") or None
