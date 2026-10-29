"""URL normalisation and classification."""
from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, urljoin, unquote

TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "msclkid", "yclid", "igshid", "mc_cid", "mc_eid",
    "ref", "ref_src", "source", "_ga", "_gl", "s_kwcid", "ttclid", "twclid", "li_fat_id",
}
TRACKING_PREFIXES = ("utm_", "pk_", "piwik_", "mtm_", "hsa_", "oly_")

BINARY_EXT = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".rar", ".7z", ".gz", ".tar",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp", ".tiff", ".avif", ".heic",
    ".mp3", ".mp4", ".m4a", ".m4v", ".mov", ".avi", ".wmv", ".webm", ".ogg", ".wav", ".flac",
    ".css", ".js", ".mjs", ".json", ".xml", ".rss", ".atom", ".txt", ".csv", ".ics", ".vcf",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".exe", ".dmg", ".apk", ".msi", ".iso", ".epub",
    ".kml", ".gpx", ".wasm", ".map",
}

_slug_re = re.compile(r"[^a-z0-9]+")


def origin_of(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme.lower()}://{p.netloc.lower()}"


def normalize(url: str, base: str | None = None) -> str | None:
    """Return a canonical absolute http(s) URL or None if it is not a crawlable web URL."""
    if url is None:
        return None
    url = url.strip()
    if not url or url.startswith(("#", "javascript:", "mailto:", "tel:", "sms:", "data:", "blob:")):
        return None
    if base:
        url = urljoin(base, url)
    p = urlsplit(url)
    if p.scheme.lower() not in ("http", "https"):
        return None
    scheme = p.scheme.lower()
    host = p.hostname.lower() if p.hostname else ""
    if not host:
        return None
    port = p.port
    netloc = host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    path = unquote(p.path) or "/"
    path = re.sub(r"/{2,}", "/", path)
    # trailing slash: strip it except for the root; also drop "index.html"-style defaults
    path = re.sub(r"/(index|default)\.(html?|php|aspx?)$", "/", path, flags=re.I)
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    # re-quote minimal unsafe characters
    path = path.replace(" ", "%20")
    query_items = [
        (k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS and not k.lower().startswith(TRACKING_PREFIXES)
    ]
    query = urlencode(sorted(query_items)) if query_items else ""
    return urlunsplit((scheme, netloc, path, query, ""))


def same_origin(url: str, origin: str) -> bool:
    return origin_of(url) == origin


def looks_binary(url: str) -> bool:
    path = urlsplit(url).path.lower()
    m = re.search(r"(\.[a-z0-9]{1,5})$", path)
    return bool(m and m.group(1) in BINARY_EXT)


def slugify(url: str, maxlen: int = 60) -> str:
    p = urlsplit(url)
    raw = p.path.strip("/")
    if p.query:
        raw += "-" + p.query
    raw = raw.lower().replace("/", "-")
    slug = _slug_re.sub("-", raw).strip("-")
    if not slug:
        slug = "home"
    return slug[:maxlen].rstrip("-")
