"""Command-line entry point: python -m site_archive URL [options]."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__
from .build import build_outputs
from .crawler import DEFAULT_UA, Crawler
from .model import CrawlResult


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="python -m site_archive",
        description="Archive a public website before a redesign: editable Word text, captioned screenshot "
                    "PDFs (desktop + mobile), an Excel sitemap with broken links, and an offline index.html.",
    )
    ap.add_argument("url", help="start URL, e.g. https://example.com")
    ap.add_argument("--out", help="output directory (default: out/<host>)")
    ap.add_argument("--max-pages", type=int, default=300, help="stop after this many pages (default 300)")
    ap.add_argument("--sample", type=int, metavar="N", help="sample mode: archive only the first N pages")
    mob = ap.add_mutually_exclusive_group()
    mob.add_argument("--mobile", dest="mobile", action="store_true", default=True, help="take mobile screenshots (default)")
    mob.add_argument("--no-mobile", dest="mobile", action="store_false", help="skip mobile screenshots")
    ap.add_argument("--mobile-scale", type=int, default=2, choices=(1, 2),
                    help="device pixel ratio for mobile screenshots: 2 = sharp/retina (default), 1 = smaller files")
    ap.add_argument("--delay-ms", type=int, default=1000, help="minimum gap between requests in ms (default 1000)")
    ap.add_argument("--timeout", type=int, default=45, help="per-page load timeout in seconds (default 45)")
    ap.add_argument("--dedupe-boilerplate", action="store_true",
                    help="move nav/footer text repeated on nearly every page into one shared section (default: keep exact wording on every page)")
    ap.add_argument("--include-hidden", action="store_true",
                    help="also extract text hidden by CSS (closed accordions, mobile-only menus)")
    ap.add_argument("--include-subdomains", action="store_true",
                    help="also crawl subdomains of the start host (blog.example.com, shop.example.com)")
    ap.add_argument("--exclude", action="append", default=[], metavar="REGEX",
                    help="skip URLs matching this regular expression (repeatable), e.g. --exclude '/calendar/' --exclude '\?page='")
    ap.add_argument("--keep-fixed", action="store_true",
                    help="do not pin position:fixed/sticky bars before screenshots (default pins them so headers do not float mid-page)")
    ap.add_argument("--no-external-links", action="store_true", help="do not HTTP-check links to other domains")
    ap.add_argument("--ignore-robots", action="store_true", help="crawl even if robots.txt disallows (only for sites you own)")
    ap.add_argument("--user-agent", default=DEFAULT_UA, help="custom User-Agent string")
    ap.add_argument("--rebuild", action="store_true",
                    help="skip crawling; regenerate the deliverables from <out>/crawl.json")
    ap.add_argument("--version", action="version", version=f"site-archive {__version__}")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    a = parse_args(argv)
    url = a.url if "://" in a.url else "https://" + a.url
    host = urlsplit(url).hostname or "site"
    out = Path(a.out) if a.out else Path("out") / host
    out.mkdir(parents=True, exist_ok=True)

    def log(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    t0 = time.monotonic()
    if a.rebuild:
        src = out / "crawl.json"
        if not src.exists():
            log(f"--rebuild needs {src}; run a crawl first")
            return 2
        result = CrawlResult.from_dict(json.loads(src.read_text(encoding="utf-8")))
        log(f"rebuilding deliverables from {src} ({len(result.pages)} pages)")
    else:
        crawler = Crawler(
            url, out, max_pages=a.max_pages, mobile=a.mobile, delay_ms=a.delay_ms, timeout_s=a.timeout,
            include_hidden=a.include_hidden, respect_robots=not a.ignore_robots,
            check_external=not a.no_external_links, sample=a.sample, mobile_scale=a.mobile_scale,
            include_subdomains=a.include_subdomains, pin_fixed=not a.keep_fixed, exclude=a.exclude,
            user_agent=a.user_agent, log=log,
        )
        log(f"site-archive {__version__}: crawling {crawler.start_url} -> {out}"
            + (f" (SAMPLE: {a.sample} pages)" if a.sample else f" (max {a.max_pages} pages)"))
        result = crawler.run()

    stats = build_outputs(result, out, dedupe_boilerplate=a.dedupe_boilerplate, log=log)
    mins = (time.monotonic() - t0) / 60
    log("")
    log(f"done in {mins:.1f} min: {stats['pages']} pages, {stats['broken_links']} broken links "
        f"({stats['broken_urls']} distinct URLs), {stats['verify_links']} links to verify manually, "
        f"{stats['links_checked']} links checked, {stats['skipped']} URLs skipped")
    log(f"deliverables in {out.resolve()}:")
    for name in ("content.docx", "screenshots-desktop.pdf", "screenshots-mobile.pdf", "sitemap.xlsx", "index.html", "crawl.json"):
        if (out / name).exists():
            log(f"  {name}  ({(out / name).stat().st_size / 1024:,.0f} KB)")
    return 0
