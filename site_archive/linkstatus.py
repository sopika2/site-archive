"""Classify a checked link's HTTP status into something a client can act on."""
from __future__ import annotations

from urllib.parse import urlsplit

from .model import LinkSeen

BROKEN = "broken"
SERVER_ERROR = "server error"
VERIFY = "verify manually"
OK = "ok"

BOT_BLOCK_CODES = {400, 401, 403, 405, 406, 418, 429, 451, 999}
# Services that answer automated requests with 404/400 even for valid URLs
BOT_HOSTS = ("google.com", "facebook.com", "instagram.com", "linkedin.com", "x.com", "twitter.com",
             "youtube.com", "tiktok.com", "pinterest.com", "threads.net", "yelp.com")


def classify(link: LinkSeen) -> tuple[str, str]:
    """Return (category, note). Category is one of ok / broken / server error / verify manually."""
    s = (link.status or "").strip()
    if not s or s in ("not checked", "file download"):
        return OK, ""
    if s.isdigit():
        code = int(s)
        if code < 400:
            return OK, ""
        host = (urlsplit(link.url).hostname or "").lower()
        if not link.internal and any(host == h or host.endswith("." + h) for h in BOT_HOSTS):
            return VERIFY, f"HTTP {code}: {host} blocks automated checks; open it in a browser to confirm"
        if code in (404, 410):
            return BROKEN, "page not found"
        if code >= 500:
            return SERVER_ERROR, f"server returned HTTP {code}"
        if link.internal:
            return BROKEN, f"HTTP {code} on this site"
        if code in BOT_BLOCK_CODES:
            return VERIFY, f"HTTP {code}: the site may block automated checks; open it in a browser to confirm"
        return BROKEN, f"HTTP {code}"
    low = s.lower()
    if "timed out" in low or "timeout" in low:
        return VERIFY, "no response within 15 s"
    if "ssl" in low or "certificate" in low:
        return VERIFY, "TLS certificate problem (may be local)"
    if "name or service not known" in low or "getaddrinfo" in low or "nodename" in low or "11001" in low:
        return BROKEN, "domain does not resolve"
    return VERIFY, s[:120]


def is_problem(link: LinkSeen) -> bool:
    return classify(link)[0] != OK
