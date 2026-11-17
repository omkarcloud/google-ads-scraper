"""The one network helper the google_ads module needs: the Accept-Language
its sessions send. Requests go out direct from your own connection (or your
GOOGLE_ADS_PROXY), so every session announces the plain English list a
desktop Chrome sends. Ad copy comes back in the language the advertiser
wrote it in, whatever this header says."""

ACCEPT_LANGUAGE = "en-US,en;q=0.9"


def site_accept_language(site=None):
    return ACCEPT_LANGUAGE


def accept_language(proxy=None, country=None):
    return ACCEPT_LANGUAGE


def exit_proxy(exit=None):
    return exit if exit and "://" in str(exit) else None


def new_session(exit=None, impersonate="chrome", **kw):
    from curl_cffi import requests as curl
    sess = curl.Session(impersonate=impersonate, **kw)
    proxy = exit_proxy(exit)
    if proxy:
        sess.proxies = {"http": proxy, "https": proxy}
    return sess
