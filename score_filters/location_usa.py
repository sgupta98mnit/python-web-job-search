"""Lenient USA-location detector.

Returns True / False / None. Callers should only auto-reject on explicit
False -- ambiguous (None) means we lack enough signal and the LLM score
should be trusted. Bias: false negatives (wrongly rejecting a US role)
are worse than false positives (wrongly keeping a non-US role), since
the latter is recoverable via the manual `irrelevant` status.
"""

from __future__ import annotations

import re

# Country/region tokens that unambiguously place a role outside the US.
# Compared via substring match against the lowercased location string,
# so multi-word entries must include spaces / punctuation as written.
_NON_US_TOKENS: tuple[str, ...] = (
    # Country names
    " india", "india,", "india ", "(india)",
    "canada", "united kingdom", " u.k.", " uk ", "uk,", "(uk)",
    "ireland", "germany", "france", "spain", "italy", "netherlands",
    "belgium", "switzerland", "sweden", "norway", "finland", "denmark",
    "poland", "portugal", "romania", "czech", "hungary", "austria",
    "greece", "turkey", "ukraine", "russia",
    "singapore", "malaysia", "indonesia", "philippines", "thailand",
    "vietnam", "japan", " china", "china,", "hong kong", "taiwan",
    "south korea", " korea", "korea,",
    "australia", "new zealand",
    "mexico", "brazil", "argentina", "chile", "colombia", "peru",
    "south africa", "nigeria", "kenya", "egypt", "morocco",
    "israel", "uae", "u.a.e.", "saudi arabia", "qatar", "bahrain",
    "lebanon", "jordan",
    # Common non-US cities that show up in JD location fields
    "bangalore", "bengaluru", "hyderabad", "pune", "mumbai", "chennai",
    "kolkata", "noida", "gurgaon", "gurugram", "ahmedabad", "kochi",
    "trivandrum", "thiruvananthapuram", "indore",
    "toronto", "vancouver", "montreal", "calgary", "ottawa", "edmonton",
    "london", "manchester", "edinburgh", "glasgow", "birmingham",
    "dublin", "berlin", "munich", "hamburg", "frankfurt",
    "paris", "lyon", "marseille",
    "madrid", "barcelona", "lisbon", "porto",
    "amsterdam", "rotterdam", "utrecht",
    "stockholm", "copenhagen", "oslo", "helsinki",
    "warsaw", "krakow", "prague", "budapest", "vienna", "zurich",
    "milan", "rome", "naples",
    "tokyo", "osaka", "kyoto", "seoul", "taipei", "beijing", "shanghai",
    "sydney", "melbourne", "brisbane", "auckland", "wellington",
    "sao paulo", "rio de janeiro", "buenos aires", "mexico city",
    # Remote markers that explicitly exclude the US
    "remote - emea", "remote - apac", "remote - latam", "remote - india",
    "remote (emea)", "remote (apac)", "remote (latam)", "remote (india)",
    "remote - europe", "remote (europe)", "emea remote", "apac remote",
)

# Explicit US country/region tokens (substring match on lowercased text).
_US_COUNTRY_TOKENS: tuple[str, ...] = (
    "united states",
    "u.s.a",
    "(usa)",
    "(us)",
    "us-remote",
    "us remote",
    "remote (us)",
    "remote - us",
    "remote, us",
    "remote-us",
    "remote in the us",
    "remote within the us",
    "americas",
    "north america",
)

# Short country tokens that need word-boundary matching to avoid false hits
# like "fusa" or "bus". Matched on the lowercased string.
_US_SHORT_RE = re.compile(r"\b(?:usa|u\.s\.a\.?|u\.s\.|us)\b")

# US state full names (lowercase) used for substring match.
_US_STATE_NAMES: tuple[str, ...] = (
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming",
    "district of columbia",
)

# US state two-letter abbreviations. Matched only when delimited (", CA"
# or " CA," or end of string) so we don't false-match "CA" inside words.
_US_STATE_ABBR: tuple[str, ...] = (
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI",
    "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI",
    "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC",
    "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT",
    "VT", "VA", "WA", "WV", "WI", "WY", "DC",
)
_US_STATE_ABBR_RE = re.compile(
    r"(?:,|\s)(?:" + "|".join(_US_STATE_ABBR) + r")(?:\b|,|$)"
)

# Major US cities. Helps when the JD lists only a city.
_US_CITY_TOKENS: tuple[str, ...] = (
    "new york city", "san francisco", "san jose", "los angeles",
    "san diego", "seattle", "portland", "boston", "cambridge",
    "chicago", "austin", "dallas", "houston", "san antonio", "fort worth",
    "atlanta", "miami", "tampa", "orlando", "jacksonville",
    "denver", "boulder", "phoenix", "tucson", "las vegas",
    "philadelphia", "pittsburgh", "baltimore", "washington dc",
    "washington, d.c.", "minneapolis", "st. paul", "saint paul",
    "st. louis", "saint louis", "kansas city", "indianapolis",
    "columbus", "cleveland", "cincinnati", "detroit", "milwaukee",
    "nashville", "charlotte", "raleigh", "durham", "salt lake city",
    "buffalo", "rochester",
)


def is_usa_location(location: str | None, remote: bool) -> bool | None:
    """Return True if the role looks US-based, False if explicitly non-US,
    None if we cannot tell.

    `remote=True` alone is not enough: many "Remote" roles exclude the US.
    """
    text_raw = (location or "").strip()
    if not text_raw:
        # Empty location is ambiguous; do not auto-reject.
        return None

    lowered = text_raw.lower()

    non_us_hit = any(tok in lowered for tok in _NON_US_TOKENS)

    us_country_hit = any(tok in lowered for tok in _US_COUNTRY_TOKENS)
    us_short_hit = bool(_US_SHORT_RE.search(lowered))
    us_state_name_hit = any(name in lowered for name in _US_STATE_NAMES)
    us_city_hit = any(city in lowered for city in _US_CITY_TOKENS)
    # State-abbrev regex runs on the original case.
    us_abbr_hit = bool(_US_STATE_ABBR_RE.search(text_raw))
    us_any = (
        us_country_hit
        or us_short_hit
        or us_state_name_hit
        or us_city_hit
        or us_abbr_hit
    )

    if non_us_hit and not us_any:
        return False
    if us_any:
        return True
    return None
