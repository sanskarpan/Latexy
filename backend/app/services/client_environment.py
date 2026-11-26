"""Bounded first-party client-environment and country helpers.

This module is the only place that turns a stored user agent into report
labels. It never returns or logs the source string, and every result comes
from a fixed allowlist: device class, browser family, OS family.

Country capture is deliberately country-only. The value is read from the
edge-owned ``CF-IPCountry`` header only when proxy headers are trusted, then
validated against the ISO 3166-1 alpha-2 set before it is written into
``usage_analytics.event_metadata``. No city, region, latitude, longitude or
raw IP is read from that header.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from ..core.config import settings

COUNTRY_HEADER = "CF-IPCountry"
COUNTRY_METADATA_KEY = "country"

DEVICE_CLASSES = ("mobile", "tablet", "desktop", "unknown")
DEVICE_LABELS = {
    "mobile": "Mobile",
    "tablet": "Tablet",
    "desktop": "Desktop",
    "unknown": "Unknown device",
}

BROWSER_FAMILIES = (
    "chrome",
    "safari",
    "firefox",
    "edge",
    "opera",
    "samsung_internet",
    "internet_explorer",
    "other",
    "unknown",
)
BROWSER_LABELS = {
    "chrome": "Chrome",
    "safari": "Safari",
    "firefox": "Firefox",
    "edge": "Edge",
    "opera": "Opera",
    "samsung_internet": "Samsung Internet",
    "internet_explorer": "Internet Explorer",
    "other": "Other browser",
    "unknown": "Unknown browser",
}

OS_FAMILIES = (
    "windows",
    "macos",
    "ios",
    "android",
    "linux",
    "chromeos",
    "other",
    "unknown",
)
OS_LABELS = {
    "windows": "Windows",
    "macos": "macOS",
    "ios": "iOS",
    "android": "Android",
    "linux": "Linux",
    "chromeos": "ChromeOS",
    "other": "Other OS",
    "unknown": "Unknown OS",
}

UNKNOWN_COUNTRY = "unknown"
COUNTRY_LABEL = "Country (ISO 3166-1 alpha-2)"

# Official ISO 3166-1 alpha-2 codes. Cloudflare's ``XX`` (unknown) and ``T1``
# (Tor) are intentionally absent: both bucket as unknown.
_ISO_ALPHA2 = frozenset(
    """
    AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ
    BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ
    CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ
    DE DJ DK DM DO DZ
    EC EE EG EH ER ES ET
    FI FJ FK FM FO FR
    GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY
    HK HM HN HR HT HU
    ID IE IL IM IN IO IQ IR IS IT
    JE JM JO JP
    KE KG KH KI KM KN KP KR KW KY KZ
    LA LB LC LI LK LR LS LT LU LV LY
    MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ
    NA NC NE NF NG NI NL NO NP NR NU NZ
    OM
    PA PE PF PG PH PK PL PM PN PR PS PT PW PY
    QA
    RE RO RS RU RW
    SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ
    TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ
    UA UG UM US UY UZ
    VA VC VE VG VI VN VU
    WF WS
    YE YT
    ZA ZM ZW
    """.split()
)

_TABLET_MARKERS = (
    "ipad",
    "tablet",
    "kindle",
    "silk",
    "playbook",
    "nexus 7",
    "nexus 9",
)
_MOBILE_MARKERS = (
    "mobi",
    "iphone",
    "ipod",
    "android",
    "windows phone",
    "blackberry",
    "opera mini",
    "opera mobi",
)


def normalize_country_code(value: Any) -> Optional[str]:
    """Return an uppercase ISO alpha-2 code, or ``None`` for anything else.

    The input is untrusted (an edge header or historical event metadata), so
    values are stripped, uppercased and checked against the complete code set.
    ``XX``, ``T1``, free-form names, numeric codes and injection attempts all
    become ``None`` rather than being persisted or echoed.
    """

    if not isinstance(value, str):
        return None
    code = value.strip().upper()
    if code in _ISO_ALPHA2:
        return code
    return None


def country_from_request(request: Any) -> Optional[str]:
    """Read the validated country code from a trusted edge header.

    Proxy headers are only trusted when ``TRUST_PROXY_HEADERS`` is enabled,
    matching the repository's existing X-Forwarded-For boundary. A direct
    caller therefore cannot invent a country when the app is exposed without
    an edge proxy.
    """

    if request is None or not getattr(settings, "TRUST_PROXY_HEADERS", False):
        return None
    headers = getattr(request, "headers", None)
    if headers is None:
        return None
    return normalize_country_code(headers.get(COUNTRY_HEADER))


def with_server_country(metadata: Optional[Mapping[str, Any]], request: Any) -> Optional[dict[str, Any]]:
    """Return event metadata with only the server-validated country attached.

    Any client-supplied ``country``/``country_code`` is discarded first. This
    keeps older clients and spoofed payloads from being mistaken for
    edge-derived geography, while leaving all unrelated metadata untouched.
    """

    clean = dict(metadata) if isinstance(metadata, Mapping) else {}
    clean.pop(COUNTRY_METADATA_KEY, None)
    clean.pop("country_code", None)
    country = country_from_request(request)
    if country is not None:
        clean[COUNTRY_METADATA_KEY] = country
    return clean or None


def country_from_metadata(metadata: Any) -> Optional[str]:
    """Extract a previously captured, already-validated country code."""

    if not isinstance(metadata, Mapping):
        return None
    return normalize_country_code(metadata.get(COUNTRY_METADATA_KEY))


def classify_device_class(user_agent: str | None) -> str:
    """Coarse mobile/tablet/desktop bucket from a user agent.

    Android tablets usually omit the ``Mobile`` token; treating Android without
    that token as a tablet keeps the device split useful without storing or
    returning any part of the source string.
    """

    if not user_agent:
        return "unknown"
    ua = user_agent.lower()
    if not ua.strip():
        return "unknown"
    if any(marker in ua for marker in _TABLET_MARKERS):
        return "tablet"
    if "android" in ua and "mobile" not in ua:
        return "tablet"
    if any(marker in ua for marker in _MOBILE_MARKERS):
        return "mobile"
    return "desktop"


def classify_browser_family(user_agent: str | None) -> str:
    """Map a user agent onto a fixed browser-family label."""

    if not user_agent or not user_agent.strip():
        return "unknown"
    ua = user_agent.lower()

    # Order matters: Edge, Opera and Samsung Internet all embed Chrome/Safari
    # tokens, while Chrome embeds Safari.
    if "edg/" in ua or "edga/" in ua or "edgios/" in ua:
        return "edge"
    if "opr/" in ua or "opios/" in ua or "opera mini" in ua or "opera mobi" in ua:
        return "opera"
    if "samsungbrowser" in ua:
        return "samsung_internet"
    if "firefox/" in ua or "fxios/" in ua:
        return "firefox"
    if "msie " in ua or "trident/" in ua:
        return "internet_explorer"
    if "chrome/" in ua or "crios/" in ua or "chromium/" in ua:
        return "chrome"
    if "safari/" in ua and "version/" in ua:
        return "safari"
    return "other"


def classify_os_family(user_agent: str | None) -> str:
    """Map a user agent onto a fixed OS-family label."""

    if not user_agent or not user_agent.strip():
        return "unknown"
    ua = user_agent.lower()

    if "iphone" in ua or "ipad" in ua or "ipod" in ua:
        return "ios"
    if "android" in ua:
        return "android"
    if "cros" in ua:
        return "chromeos"
    if "windows" in ua:
        return "windows"
    if "mac os x" in ua or "macintosh" in ua:
        return "macos"
    if "linux" in ua:
        return "linux"
    return "other"


def parse_user_agent(user_agent: str | None) -> dict[str, str]:
    """Return the three bounded report dimensions for one stored user agent."""

    return {
        "device_class": classify_device_class(user_agent),
        "browser_family": classify_browser_family(user_agent),
        "os_family": classify_os_family(user_agent),
    }
