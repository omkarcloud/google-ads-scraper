"""Marshmallow request schemas for every /google-ads/* route.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair):

    advertiser  an advertiser id (AR06641858037806006273) OR any
                adstransparency.google.com advertiser / creative link
    ad          a creative id (CR09405416287280037889) OR a Transparency
                Center creative link
    query       (ads/search, political/search) an advertiser id, an
                advertiser link, a domain (nike.com, https://www.nike.com/,
                the Center's ?domain= link) or a brand / advertiser name
    region      "anywhere" (default) or a 2-letter country: where the ads
                were shown. The political feed needs a country.

A pasted Transparency Center link's ?region= fills `region` when the caller
leaves it out. Filters mirror the site's own: format (text / image /
video), platform (search, youtube, maps, play, shopping; comma list),
start_date / end_date (YYYY-MM-DD, the ad's shown period overlaps it).
"""
from marshmallow import ValidationError, post_load, pre_load, validate, validates_schema

from schema_fields import (BaseSchema, ChoiceField, CommaListField, DateField, LimitField, PageField,
                           QueryField, RefField, StrippedString)
from google_ads import refs


class AdvertiserRefField(RefField):
    resolver = staticmethod(refs.resolve_advertiser)


class AdRefField(RefField):
    resolver = staticmethod(refs.resolve_ad)


class AdsQueryField(RefField):
    resolver = staticmethod(refs.resolve_ads_query)


class RegionField(StrippedString):
    """'anywhere' (default) or a 2-letter ISO country, upper-cased."""

    def __init__(self, allow_anywhere=True, **kwargs):
        self.allow_anywhere = allow_anywhere
        kwargs.setdefault("required", not allow_anywhere)
        if allow_anywhere:
            kwargs.setdefault("load_default", refs.ANYWHERE)
        kwargs.setdefault("metadata", {
            "description": "where the ads were shown: a 2-letter country code (US, GB, DE, ...) or anywhere (default)"
            if allow_anywhere else "the country the political ads were shown in, as a 2-letter code (US, GB, DE, ...)"})
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        if value is None:
            return refs.ANYWHERE if self.allow_anywhere else None
        if value.lower() == refs.ANYWHERE:
            if self.allow_anywhere:
                return refs.ANYWHERE
            raise ValidationError("Must be a 2-letter ISO country code (US, GB, DE, ...); the political feed is per country.")
        code = value.upper()
        if code not in refs.COUNTRIES:
            raise ValidationError("Must be a 2-letter ISO country code (US, GB, DE, ...)"
                                  + (" or anywhere." if self.allow_anywhere else "."))
        return code


class _LinkRegion(BaseSchema):
    """A pasted Transparency Center link's ?region= fills `region`."""
    link_field = "advertiser"

    @pre_load
    def from_link(self, data, **kwargs):
        data = dict(data)
        if "region" in self.fields and not data.get("region"):
            params = refs.link_params(data.get(self.link_field, ""))
            if params.get("region"):
                data["region"] = params["region"]
        return data


# ---- advertisers/search ---------------------------------------------------------------

class AdvertisersSearchSchema(BaseSchema):
    query = QueryField(max_length=100, metadata={
        "description": "advertiser / brand name or a domain to look up (nike, nike.com)"})
    limit = LimitField(default=20, max_size=refs.SUGGESTIONS_MAX, metadata={
        "description": f"advertisers (and domains) to return, 1-{refs.SUGGESTIONS_MAX} (default 20)"})


# ---- advertisers/details --------------------------------------------------------------

class AdvertiserSchema(_LinkRegion):
    advertiser = AdvertiserRefField(metadata={
        "description": "advertiser id (AR06641858037806006273) or a Transparency Center advertiser link"})
    region = RegionField()


# ---- ads/search -----------------------------------------------------------------------

class AdsSearchSchema(_LinkRegion):
    link_field = "query"
    query = AdsQueryField(metadata={
        "description": "advertiser id (AR…), advertiser link, domain (nike.com) or advertiser name (Nike)"})
    region = RegionField()
    format = ChoiceField(dict(refs.FORMATS), metadata={
        "description": "only this creative format: text, image or video (default all)"})
    platform = CommaListField(value_map=refs.PLATFORMS, max_items=len(refs.PLATFORMS), metadata={
        "description": "only ads shown on these Google surfaces, comma-separated: search, youtube, maps, play, shopping (default all)"})
    start_date = DateField(metadata={
        "description": "only ads shown on or after this date, YYYY-MM-DD"})
    end_date = DateField(metadata={
        "description": "only ads shown on or before this date, YYYY-MM-DD"})
    page = PageField(max_page=refs.MAX_PAGE, metadata={
        "description": f"page number, 1-{refs.MAX_PAGE} (default 1)"})
    limit = LimitField(default=refs.PAGE_DEFAULT, max_size=refs.PAGE_MAX, metadata={
        "description": f"ads per page, 1-{refs.PAGE_MAX} (default {refs.PAGE_DEFAULT})"})

    @validates_schema
    def _dates_in_order(self, data, **kwargs):
        start, end = data.get("start_date"), data.get("end_date")
        if start and end and end < start:
            raise ValidationError("end_date must not be before start_date.", "end_date")

    @post_load
    def _sort_platforms(self, data, **kwargs):
        if data.get("platform"):
            data["platform"] = sorted(data["platform"])
        return data


# ---- political/search -----------------------------------------------------------------

class PoliticalSearchSchema(AdsSearchSchema):
    query = AdsQueryField(required=False, load_default=None, metadata={
        "description": "optional: advertiser id (AR…), advertiser link, domain or advertiser name; "
                       "leave empty for every political ad shown in the region"})
    region = RegionField(allow_anywhere=False, required=True)


# ---- ads/details ----------------------------------------------------------------------

class AdSchema(_LinkRegion):
    link_field = "ad"
    ad = AdRefField(metadata={
        "description": "creative id (CR09405416287280037889) or a Transparency Center creative link"})
    region = RegionField()
