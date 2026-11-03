"""Reference resolvers, link builders and the vocabulary tables for
/google-ads/* (the Google Ads Transparency Center,
adstransparency.google.com).

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair). Resolvers raise ValueError with a user-facing message
(RefField turns it into a 400):

  * advertiser  an advertiser id (AR + 20 digits) OR any Transparency Center
                advertiser / creative link (the id is its /advertiser/ segment)
  * ad          a creative id (CR + 20 digits) OR a Transparency Center
                creative link
  * query       (ads/search) an advertiser id, an advertiser link, a domain
                ("nike.com", "https://www.nike.com/…", or the Center's own
                ?domain= search link) or a brand / advertiser name, which
                api.py resolves through the site's own suggestions

Identifier shapes (the site's own, 2026-11-03): AR06641858037806006273,
CR09405416287280037889. Links: /advertiser/<AR>?region=US,
/advertiser/<AR>/creative/<CR>?region=US, /?domain=nike.com&region=US,
/political?region=US; `topic=political` marks the political view.

Enums (captured from the site's own RPC bodies while flipping the UI
filters, 2026-11-03): a region code is 2000 + the country's ISO 3166-1
numeric code (US 840 -> 2840, GB 826 -> 2826, DE 276 -> 2276); formats
TEXT 1 / IMAGE 2 / VIDEO 3; platforms PLAY 1 / MAPS 2 / SEARCH 3 /
SHOPPING 4 / YOUTUBE 5 (the five surfaces the UI offers; no Display). The
country table below is ISO 3166-1 (pycountry 24.6.1, 249 entries), kept
static so the pod image needs no extra package.
"""
import re
from urllib.parse import parse_qs, urlparse

SITE = "https://adstransparency.google.com"
ANYWHERE = "anywhere"

ADVERTISER_ID_RE = re.compile(r"^AR\d{20}$")
CREATIVE_ID_RE = re.compile(r"^CR\d{20}$")
_LINK_ADVERTISER_RE = re.compile(r"/advertiser/(AR\d{20})(?:/|$|\?)")
_LINK_CREATIVE_RE = re.compile(r"/creative/(CR\d{20})(?:/|$|\?)")
_DOMAIN_RE = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")

# Caps measured on 2026-11-03: SearchCreatives serves at most 100 creatives
# a page (a request for 200 answers an empty page); SearchSuggestions
# answered 174 advertisers for "nike" when asked for 200.
PAGE_MAX = 100
PAGE_DEFAULT = 40
SUGGESTIONS_MAX = 100
# Deepest page a client may ask for (100 x 100 = 10,000 creatives, the
# largest advertiser seen so far — Nike, Inc. — has 8,000-9,000).
MAX_PAGE = 100
# Renders fetched per ads/details call (one per variation that has one; a
# text ad carries one render + image screenshots of its other variations).
RENDERS_MAX = 5

FORMATS = {"text": 1, "image": 2, "video": 3}
FORMAT_NAMES = {code: name.upper() for name, code in FORMATS.items()}
PLATFORMS = {"play": 1, "maps": 2, "search": 3, "shopping": 4, "youtube": 5}
PLATFORM_NAMES = {code: name.upper() for name, code in PLATFORMS.items()}
TOPICS = {"commercial": 1, "political": 2}
TOPIC_NAMES = {code: name for name, code in TOPICS.items()}
# The audience-selection categories of a creative's targeting block
# (field 13.4, one {included, excluded} pair per category). 1-3 are the
# labels the EU "Audience selection" section shows in that order
# (Demographic info / Geographic locations / Contextual signals, page
# capture 2026-11-03); 4-5 appear on video creatives only and carry the
# next two categories of Google's audience-selection key (customer lists,
# topics of interest) — not yet seen rendered on a page.
TARGETING_CATEGORIES = {
    1: "demographic_info",
    2: "geographic_locations",
    3: "contextual_signals",
    4: "customer_lists",
    5: "topics_of_interest",
}

# ISO 3166-1: alpha-2 -> (numeric, common name). The site's region enum is
# 2000 + numeric.
COUNTRIES = {
    "AD": (20, 'Andorra'),
    "AE": (784, 'United Arab Emirates'),
    "AF": (4, 'Afghanistan'),
    "AG": (28, 'Antigua and Barbuda'),
    "AI": (660, 'Anguilla'),
    "AL": (8, 'Albania'),
    "AM": (51, 'Armenia'),
    "AO": (24, 'Angola'),
    "AQ": (10, 'Antarctica'),
    "AR": (32, 'Argentina'),
    "AS": (16, 'American Samoa'),
    "AT": (40, 'Austria'),
    "AU": (36, 'Australia'),
    "AW": (533, 'Aruba'),
    "AX": (248, 'Åland Islands'),
    "AZ": (31, 'Azerbaijan'),
    "BA": (70, 'Bosnia and Herzegovina'),
    "BB": (52, 'Barbados'),
    "BD": (50, 'Bangladesh'),
    "BE": (56, 'Belgium'),
    "BF": (854, 'Burkina Faso'),
    "BG": (100, 'Bulgaria'),
    "BH": (48, 'Bahrain'),
    "BI": (108, 'Burundi'),
    "BJ": (204, 'Benin'),
    "BL": (652, 'Saint Barthélemy'),
    "BM": (60, 'Bermuda'),
    "BN": (96, 'Brunei Darussalam'),
    "BO": (68, 'Bolivia'),
    "BQ": (535, 'Bonaire, Sint Eustatius and Saba'),
    "BR": (76, 'Brazil'),
    "BS": (44, 'Bahamas'),
    "BT": (64, 'Bhutan'),
    "BV": (74, 'Bouvet Island'),
    "BW": (72, 'Botswana'),
    "BY": (112, 'Belarus'),
    "BZ": (84, 'Belize'),
    "CA": (124, 'Canada'),
    "CC": (166, 'Cocos (Keeling) Islands'),
    "CD": (180, 'Congo, The Democratic Republic of the'),
    "CF": (140, 'Central African Republic'),
    "CG": (178, 'Congo'),
    "CH": (756, 'Switzerland'),
    "CI": (384, "Côte d'Ivoire"),
    "CK": (184, 'Cook Islands'),
    "CL": (152, 'Chile'),
    "CM": (120, 'Cameroon'),
    "CN": (156, 'China'),
    "CO": (170, 'Colombia'),
    "CR": (188, 'Costa Rica'),
    "CU": (192, 'Cuba'),
    "CV": (132, 'Cabo Verde'),
    "CW": (531, 'Curaçao'),
    "CX": (162, 'Christmas Island'),
    "CY": (196, 'Cyprus'),
    "CZ": (203, 'Czechia'),
    "DE": (276, 'Germany'),
    "DJ": (262, 'Djibouti'),
    "DK": (208, 'Denmark'),
    "DM": (212, 'Dominica'),
    "DO": (214, 'Dominican Republic'),
    "DZ": (12, 'Algeria'),
    "EC": (218, 'Ecuador'),
    "EE": (233, 'Estonia'),
    "EG": (818, 'Egypt'),
    "EH": (732, 'Western Sahara'),
    "ER": (232, 'Eritrea'),
    "ES": (724, 'Spain'),
    "ET": (231, 'Ethiopia'),
    "FI": (246, 'Finland'),
    "FJ": (242, 'Fiji'),
    "FK": (238, 'Falkland Islands (Malvinas)'),
    "FM": (583, 'Micronesia, Federated States of'),
    "FO": (234, 'Faroe Islands'),
    "FR": (250, 'France'),
    "GA": (266, 'Gabon'),
    "GB": (826, 'United Kingdom'),
    "GD": (308, 'Grenada'),
    "GE": (268, 'Georgia'),
    "GF": (254, 'French Guiana'),
    "GG": (831, 'Guernsey'),
    "GH": (288, 'Ghana'),
    "GI": (292, 'Gibraltar'),
    "GL": (304, 'Greenland'),
    "GM": (270, 'Gambia'),
    "GN": (324, 'Guinea'),
    "GP": (312, 'Guadeloupe'),
    "GQ": (226, 'Equatorial Guinea'),
    "GR": (300, 'Greece'),
    "GS": (239, 'South Georgia and the South Sandwich Islands'),
    "GT": (320, 'Guatemala'),
    "GU": (316, 'Guam'),
    "GW": (624, 'Guinea-Bissau'),
    "GY": (328, 'Guyana'),
    "HK": (344, 'Hong Kong'),
    "HM": (334, 'Heard Island and McDonald Islands'),
    "HN": (340, 'Honduras'),
    "HR": (191, 'Croatia'),
    "HT": (332, 'Haiti'),
    "HU": (348, 'Hungary'),
    "ID": (360, 'Indonesia'),
    "IE": (372, 'Ireland'),
    "IL": (376, 'Israel'),
    "IM": (833, 'Isle of Man'),
    "IN": (356, 'India'),
    "IO": (86, 'British Indian Ocean Territory'),
    "IQ": (368, 'Iraq'),
    "IR": (364, 'Iran'),
    "IS": (352, 'Iceland'),
    "IT": (380, 'Italy'),
    "JE": (832, 'Jersey'),
    "JM": (388, 'Jamaica'),
    "JO": (400, 'Jordan'),
    "JP": (392, 'Japan'),
    "KE": (404, 'Kenya'),
    "KG": (417, 'Kyrgyzstan'),
    "KH": (116, 'Cambodia'),
    "KI": (296, 'Kiribati'),
    "KM": (174, 'Comoros'),
    "KN": (659, 'Saint Kitts and Nevis'),
    "KP": (408, 'North Korea'),
    "KR": (410, 'South Korea'),
    "KW": (414, 'Kuwait'),
    "KY": (136, 'Cayman Islands'),
    "KZ": (398, 'Kazakhstan'),
    "LA": (418, 'Laos'),
    "LB": (422, 'Lebanon'),
    "LC": (662, 'Saint Lucia'),
    "LI": (438, 'Liechtenstein'),
    "LK": (144, 'Sri Lanka'),
    "LR": (430, 'Liberia'),
    "LS": (426, 'Lesotho'),
    "LT": (440, 'Lithuania'),
    "LU": (442, 'Luxembourg'),
    "LV": (428, 'Latvia'),
    "LY": (434, 'Libya'),
    "MA": (504, 'Morocco'),
    "MC": (492, 'Monaco'),
    "MD": (498, 'Moldova'),
    "ME": (499, 'Montenegro'),
    "MF": (663, 'Saint Martin (French part)'),
    "MG": (450, 'Madagascar'),
    "MH": (584, 'Marshall Islands'),
    "MK": (807, 'North Macedonia'),
    "ML": (466, 'Mali'),
    "MM": (104, 'Myanmar'),
    "MN": (496, 'Mongolia'),
    "MO": (446, 'Macao'),
    "MP": (580, 'Northern Mariana Islands'),
    "MQ": (474, 'Martinique'),
    "MR": (478, 'Mauritania'),
    "MS": (500, 'Montserrat'),
    "MT": (470, 'Malta'),
    "MU": (480, 'Mauritius'),
    "MV": (462, 'Maldives'),
    "MW": (454, 'Malawi'),
    "MX": (484, 'Mexico'),
    "MY": (458, 'Malaysia'),
    "MZ": (508, 'Mozambique'),
    "NA": (516, 'Namibia'),
    "NC": (540, 'New Caledonia'),
    "NE": (562, 'Niger'),
    "NF": (574, 'Norfolk Island'),
    "NG": (566, 'Nigeria'),
    "NI": (558, 'Nicaragua'),
    "NL": (528, 'Netherlands'),
    "NO": (578, 'Norway'),
    "NP": (524, 'Nepal'),
    "NR": (520, 'Nauru'),
    "NU": (570, 'Niue'),
    "NZ": (554, 'New Zealand'),
    "OM": (512, 'Oman'),
    "PA": (591, 'Panama'),
    "PE": (604, 'Peru'),
    "PF": (258, 'French Polynesia'),
    "PG": (598, 'Papua New Guinea'),
    "PH": (608, 'Philippines'),
    "PK": (586, 'Pakistan'),
    "PL": (616, 'Poland'),
    "PM": (666, 'Saint Pierre and Miquelon'),
    "PN": (612, 'Pitcairn'),
    "PR": (630, 'Puerto Rico'),
    "PS": (275, 'Palestine, State of'),
    "PT": (620, 'Portugal'),
    "PW": (585, 'Palau'),
    "PY": (600, 'Paraguay'),
    "QA": (634, 'Qatar'),
    "RE": (638, 'Réunion'),
    "RO": (642, 'Romania'),
    "RS": (688, 'Serbia'),
    "RU": (643, 'Russian Federation'),
    "RW": (646, 'Rwanda'),
    "SA": (682, 'Saudi Arabia'),
    "SB": (90, 'Solomon Islands'),
    "SC": (690, 'Seychelles'),
    "SD": (729, 'Sudan'),
    "SE": (752, 'Sweden'),
    "SG": (702, 'Singapore'),
    "SH": (654, 'Saint Helena, Ascension and Tristan da Cunha'),
    "SI": (705, 'Slovenia'),
    "SJ": (744, 'Svalbard and Jan Mayen'),
    "SK": (703, 'Slovakia'),
    "SL": (694, 'Sierra Leone'),
    "SM": (674, 'San Marino'),
    "SN": (686, 'Senegal'),
    "SO": (706, 'Somalia'),
    "SR": (740, 'Suriname'),
    "SS": (728, 'South Sudan'),
    "ST": (678, 'Sao Tome and Principe'),
    "SV": (222, 'El Salvador'),
    "SX": (534, 'Sint Maarten (Dutch part)'),
    "SY": (760, 'Syria'),
    "SZ": (748, 'Eswatini'),
    "TC": (796, 'Turks and Caicos Islands'),
    "TD": (148, 'Chad'),
    "TF": (260, 'French Southern Territories'),
    "TG": (768, 'Togo'),
    "TH": (764, 'Thailand'),
    "TJ": (762, 'Tajikistan'),
    "TK": (772, 'Tokelau'),
    "TL": (626, 'Timor-Leste'),
    "TM": (795, 'Turkmenistan'),
    "TN": (788, 'Tunisia'),
    "TO": (776, 'Tonga'),
    "TR": (792, 'Türkiye'),
    "TT": (780, 'Trinidad and Tobago'),
    "TV": (798, 'Tuvalu'),
    "TW": (158, 'Taiwan'),
    "TZ": (834, 'Tanzania'),
    "UA": (804, 'Ukraine'),
    "UG": (800, 'Uganda'),
    "UM": (581, 'United States Minor Outlying Islands'),
    "US": (840, 'United States'),
    "UY": (858, 'Uruguay'),
    "UZ": (860, 'Uzbekistan'),
    "VA": (336, 'Holy See (Vatican City State)'),
    "VC": (670, 'Saint Vincent and the Grenadines'),
    "VE": (862, 'Venezuela'),
    "VG": (92, 'Virgin Islands, British'),
    "VI": (850, 'Virgin Islands, U.S.'),
    "VN": (704, 'Vietnam'),
    "VU": (548, 'Vanuatu'),
    "WF": (876, 'Wallis and Futuna'),
    "WS": (882, 'Samoa'),
    "YE": (887, 'Yemen'),
    "YT": (175, 'Mayotte'),
    "ZA": (710, 'South Africa'),
    "ZM": (894, 'Zambia'),
    "ZW": (716, 'Zimbabwe'),
}
# Google's own content-topic labels ("Topic (labelled by Google): Apparel"
# on an EU creative page): the id -> label table of the site's Flutter
# bundle (main.dart.js, build 20261026-0645, read 2026-11-03).
CONTENT_TOPICS = {
    10001: "Autos & Vehicles",
    10002: "Family & Community",
    10003: "Real Estate",
    10004: "Business & Industrial",
    10005: "Beauty & Personal Care",
    10006: "Occasions & Gifts",
    10007: "Internet & Telecom",
    10009: "Home & Garden",
    10010: "Food & Groceries",
    10011: "Health",
    10012: "Finance",
    10013: "Arts & Entertainment",
    10014: "Sports & Fitness",
    10015: "Hobbies, Games & Leisure",
    10016: "Jobs & Education",
    10017: "Travel & Tourism",
    10018: "Law & Government",
    10019: "Computers & Consumer Electronics",
    10020: "Dining & Nightlife",
    10021: "Apparel",
    10108: "News, Books & Publications",
    13934: "Mobile App Utilities",
}

REGION_CODES = {cc: 2000 + numeric for cc, (numeric, _) in COUNTRIES.items()}
_COUNTRY_BY_REGION_CODE = {code: cc for cc, code in REGION_CODES.items()}


def region_code(country):
    """ISO alpha-2 -> the site's region enum (None for "anywhere" / unknown)."""
    if not country or country == ANYWHERE:
        return None
    return REGION_CODES.get(country.upper())


def country_of_region(code):
    """The site's region enum (int or numeric string) -> ISO alpha-2, or the
    bare code as a string when it is not a country we know."""
    try:
        return _COUNTRY_BY_REGION_CODE.get(int(code)) or str(code)
    except (TypeError, ValueError):
        return None


def country_name(country):
    entry = COUNTRIES.get((country or "").upper())
    return entry[1] if entry else None


# ---- links --------------------------------------------------------------------

def _region_query(region, political=False):
    query = f"?region={region or ANYWHERE}"
    return query + ("&topic=political" if political else "")


def advertiser_link(advertiser, region=None, political=False):
    return f"{SITE}/advertiser/{advertiser}{_region_query(region, political)}"


def creative_link(advertiser, creative, region=None, political=False):
    return f"{SITE}/advertiser/{advertiser}/creative/{creative}{_region_query(region, political)}"


def domain_link(domain, region=None):
    return f"{SITE}/{_region_query(region)}&domain={domain}"


def political_link(region):
    return f"{SITE}/political?region={region}"


# ---- resolvers ----------------------------------------------------------------

def _is_link(value):
    return value.startswith(("http://", "https://", "//"))


def _as_url(value):
    return value if not value.startswith("//") else "https:" + value


def _is_site_link(value):
    host = (urlparse(_as_url(value)).hostname or "").lower()
    return host == "adstransparency.google.com"


def resolve_advertiser(value):
    """Bare AR id or a Transparency Center advertiser / creative link -> the AR id."""
    value = (value or "").strip()
    candidate = value.upper()
    if ADVERTISER_ID_RE.match(candidate):
        return candidate
    if _is_link(value):
        if not _is_site_link(value):
            raise ValueError("Must be an adstransparency.google.com link.")
        match = _LINK_ADVERTISER_RE.search(_as_url(value))
        if match:
            return match.group(1)
        raise ValueError("Must be a Transparency Center advertiser link "
                         "(https://adstransparency.google.com/advertiser/AR…).")
    raise ValueError("Must be an advertiser id (AR + 20 digits) or a Transparency Center advertiser link.")


def resolve_ad(value):
    """Bare CR id or a Transparency Center creative link -> the CR id."""
    value = (value or "").strip()
    candidate = value.upper()
    if CREATIVE_ID_RE.match(candidate):
        return candidate
    if _is_link(value):
        if not _is_site_link(value):
            raise ValueError("Must be an adstransparency.google.com link.")
        match = _LINK_CREATIVE_RE.search(_as_url(value))
        if match:
            return match.group(1)
        raise ValueError("Must be a Transparency Center creative link "
                         "(https://adstransparency.google.com/advertiser/AR…/creative/CR…).")
    raise ValueError("Must be a creative id (CR + 20 digits) or a Transparency Center creative link.")


def normalize_domain(value):
    """'https://www.Nike.com/shoes' / 'www.nike.com' / 'nike.com' -> 'nike.com'
    (None when the value is not a hostname)."""
    value = (value or "").strip().lower()
    if _is_link(value):
        value = urlparse(_as_url(value)).hostname or ""
    value = value.split("/")[0].split("?")[0].split("#")[0].strip().rstrip(".")
    if value.startswith("www."):
        value = value[4:]
    return value if _DOMAIN_RE.match(value) else None


def resolve_ads_query(value):
    """The ads/search `query`: an AR id, an advertiser link, a domain (bare,
    as a website link, or the Center's ?domain= search link) or a brand
    name -> the normalized string classify_query() sorts out."""
    value = (value or "").strip()
    if not value:
        raise ValueError("Must not be empty.")
    if ADVERTISER_ID_RE.match(value.upper()):
        return value.upper()
    if _is_link(value):
        if _is_site_link(value):
            url = _as_url(value)
            match = _LINK_ADVERTISER_RE.search(url)
            if match:
                return match.group(1)
            domain = normalize_domain((parse_qs(urlparse(url).query).get("domain") or [""])[0])
            if domain:
                return domain
            raise ValueError("Must be a Transparency Center advertiser link or a ?domain= search link.")
        domain = normalize_domain(value)
        if domain:
            return domain
        raise ValueError("Must be a website link with a hostname (https://www.nike.com/).")
    domain = normalize_domain(value)
    if domain:
        return domain
    if len(value) > 100:
        raise ValueError("A name must be at most 100 characters.")
    return value


def classify_query(value):
    """'advertiser' (AR id) | 'domain' | 'name' for a resolved ads/search query."""
    if ADVERTISER_ID_RE.match(value or ""):
        return "advertiser"
    if normalize_domain(value):
        return "domain"
    return "name"


def link_params(value):
    """{region} carried by a pasted Transparency Center link's ?region=
    (empty for a bare id, "anywhere" or a link without one)."""
    value = (value or "").strip()
    if not _is_link(value) or not _is_site_link(value):
        return {}
    region = (parse_qs(urlparse(_as_url(value)).query).get("region") or [""])[0].strip().upper()
    if region and region != ANYWHERE.upper() and region in COUNTRIES:
        return {"region": region}
    return {}
