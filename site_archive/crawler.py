"""Polite same-origin crawler built on Playwright (Chromium).

One browser, two contexts (desktop 1440 wide, mobile 390 wide). For every page it records
status, title, links, visible text in reading order and full-page screenshots.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout, Error as PWError

from .extract_js import COLLECT_LINKS_JS, COLLECT_TEXT_JS, PIN_FIXED_JS, SCROLL_JS
from .model import Block, CrawlResult, LinkSeen, PageRecord
from .urls import looks_binary, normalize, origin_of, same_origin, slugify

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36 SiteArchive/1.0 (read-only site documentation crawler)"
)
MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Mobile Safari/537.36 SiteArchive/1.0 (read-only site documentation crawler)"
)


class Throttle:
    """Keeps at least `delay` seconds between requests."""

    def __init__(self, delay: float):
        self.delay = delay
        self._last = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        gap = self.delay - (now - self._last)
        if gap > 0:
            time.sleep(gap)
        self._last = time.monotonic()


class Crawler:
    def __init__(
        self,
        start_url: str,
        out_dir: Path,
        max_pages: int = 300,
        mobile: bool = True,
        delay_ms: int = 1000,
        timeout_s: int = 45,
        include_hidden: bool = False,
        respect_robots: bool = True,
        check_external: bool = True,
        sample: int | None = None,
        mobile_scale: int = 2,
        include_subdomains: bool = False,
        pin_fixed: bool = True,
        exclude: list[str] | None = None,
        user_agent: str = DEFAULT_UA,
        log: Callable[[str], None] = lambda s: print(s, file=sys.stderr, flush=True),
    ):
        start = normalize(start_url)
        if not start:
            raise ValueError(f"Not a crawlable http(s) URL: {start_url}")
        self.start_url = start
        self.origin = origin_of(start)
        self.out_dir = Path(out_dir)
        self.max_pages = sample if sample else max_pages
        self.sample = sample
        self.mobile = mobile
        self.delay = max(0.0, delay_ms / 1000.0)
        self.timeout_ms = timeout_s * 1000
        self.include_hidden = include_hidden
        self.respect_robots = respect_robots
        self.check_external = check_external
        self.mobile_scale = mobile_scale
        self.include_subdomains = include_subdomains
        self.pin_fixed = pin_fixed
        self.exclude = [re.compile(x) for x in (exclude or [])]
        self.user_agent = user_agent
        self.log = log
        self.throttle = Throttle(self.delay)

        self.pages: list[PageRecord] = []
        self.links: list[LinkSeen] = []
        self.skipped: list[dict] = []
        self.seen: set[str] = set()                # normalised URLs queued or visited
        self.redirects: dict[str, str] = {}        # requested -> final normalised URL
        self.status_cache: dict[str, str] = {}
        self.robots: urllib.robotparser.RobotFileParser | None = None

    # ---------------------------------------------------------------- http helpers
    def _http(self, url: str, method: str = "GET", timeout: int = 20) -> tuple[int, bytes, str]:
        """Minimal urllib request honouring the throttle. Returns (status, body, content_type)."""
        self.throttle.wait()
        req = urllib.request.Request(url, method=method, headers={
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read() if method == "GET" else b""
                return resp.status, body, resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            return e.code, b"", e.headers.get("Content-Type", "") if e.headers else ""

    def _fetch_text(self, url: str) -> str | None:
        try:
            status, body, _ = self._http(url)
        except Exception as e:  # noqa: BLE001
            self.log(f"  ! {url}: {e}")
            return None
        if status != 200 or not body:
            return None
        return body.decode("utf-8", errors="replace")

    def excluded(self, url: str) -> bool:
        return any(rx.search(url) for rx in self.exclude)

    def in_scope(self, url: str) -> bool:
        """Same origin, or a subdomain of the start host when --include-subdomains is set."""
        if same_origin(url, self.origin):
            return True
        if not self.include_subdomains:
            return False
        from urllib.parse import urlsplit
        host = (urlsplit(url).hostname or "").lower()
        root = (urlsplit(self.origin).hostname or "").lower()
        root = root[4:] if root.startswith("www.") else root
        return host == root or host.endswith("." + root)

    # ---------------------------------------------------------------- robots / seeds
    def load_robots(self) -> None:
        rp = urllib.robotparser.RobotFileParser()
        text = self._fetch_text(self.origin + "/robots.txt")
        if text is None:
            rp.parse([])  # allow all
            self.log("robots.txt: none found (allow all)")
        else:
            rp.parse(text.splitlines())
            self.log("robots.txt: loaded")
            cd = rp.crawl_delay(self.user_agent) or rp.crawl_delay("*")
            if cd and cd > self.delay:
                self.log(f"robots.txt asks for crawl-delay {cd}s; honouring it")
                self.throttle.delay = float(cd)
                self.delay = float(cd)
        self.robots = rp

    def allowed(self, url: str) -> bool:
        if not self.respect_robots or self.robots is None:
            return True
        return self.robots.can_fetch(self.user_agent, url) and self.robots.can_fetch("*", url)

    def seed_urls(self) -> list[tuple[str, str]]:
        """URLs from /sitemap.xml (incl. sitemap indexes) and /rss.xml, as (url, source)."""
        found: list[tuple[str, str]] = []
        sitemap_candidates = [self.origin + "/sitemap.xml", self.origin + "/sitemap_index.xml", self.origin + "/sitemap-index.xml"]
        if self.robots is not None:
            for sm in self.robots.site_maps() or []:
                if same_origin(sm, self.origin) and sm not in sitemap_candidates:
                    sitemap_candidates.append(sm)
        seen_maps: set[str] = set()
        queue = deque(sitemap_candidates)
        while queue:
            sm = queue.popleft()
            if sm in seen_maps:
                continue
            seen_maps.add(sm)
            text = self._fetch_text(sm)
            if not text:
                continue
            try:
                root = ET.fromstring(text.encode("utf-8"))
            except ET.ParseError:
                continue
            tag = root.tag.lower()
            locs = [el.text.strip() for el in root.iter() if el.tag.lower().endswith("loc") and el.text]
            if tag.endswith("sitemapindex"):
                for loc in locs:
                    if same_origin(loc, self.origin):
                        queue.append(loc)
                self.log(f"sitemap index: {sm} ({len(locs)} sitemaps)")
            else:
                self.log(f"sitemap: {sm} ({len(locs)} urls)")
                found.extend((loc, "sitemap.xml") for loc in locs)
        for feed in (self.origin + "/rss.xml", self.origin + "/feed.xml", self.origin + "/feed", self.origin + "/atom.xml"):
            text = self._fetch_text(feed)
            if not text:
                continue
            try:
                root = ET.fromstring(text.encode("utf-8"))
            except ET.ParseError:
                continue
            urls = []
            for el in root.iter():
                t = el.tag.lower().split("}")[-1]
                if t == "link":
                    href = el.get("href") or (el.text or "")
                    if href.strip():
                        urls.append(href.strip())
                elif t == "guid" and el.text and el.text.strip().startswith("http"):
                    urls.append(el.text.strip())
            self.log(f"feed: {feed} ({len(urls)} urls)")
            found.extend((u, Path(feed).name) for u in urls)
            break
        return found

    # ---------------------------------------------------------------- main crawl
    def run(self) -> CrawlResult:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / "screenshots" / "desktop").mkdir(parents=True, exist_ok=True)
        if self.mobile:
            (self.out_dir / "screenshots" / "mobile").mkdir(parents=True, exist_ok=True)

        self.load_robots()
        if not self.allowed(self.start_url):
            raise SystemExit(f"robots.txt disallows crawling {self.start_url} (use --ignore-robots if you own the site)")

        queue: deque[tuple[str, str, str, int]] = deque()  # (url, parent, found_via, depth)
        queue.append((self.start_url, "", "start", 0))
        self.seen.add(self.start_url)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            desktop = browser.new_context(
                viewport={"width": 1440, "height": 900}, user_agent=self.user_agent,
                device_scale_factor=1, locale="en-US", reduced_motion="reduce",
            )
            mobile_ctx = None
            if self.mobile:
                mobile_ctx = browser.new_context(
                    viewport={"width": 390, "height": 844}, user_agent=MOBILE_UA, device_scale_factor=self.mobile_scale,
                    is_mobile=True, has_touch=True, locale="en-US", reduced_motion="reduce",
                )
            dpage = desktop.new_page()
            mpage = mobile_ctx.new_page() if mobile_ctx else None
            dpage.set_default_timeout(self.timeout_ms)
            if mpage:
                mpage.set_default_timeout(self.timeout_ms)

            seeded = False
            try:
                while queue and len(self.pages) < self.max_pages:
                    url, parent, via, depth = queue.popleft()
                    self._visit(dpage, mpage, url, parent, via, depth, queue)
                    if not seeded:
                        seeded = True
                        for su, source in self.seed_urls():
                            n = normalize(su)
                            if not n or not self.in_scope(n) or looks_binary(n) or n in self.seen or self.excluded(n):
                                continue
                            self.seen.add(n)
                            queue.append((n, "", source, 1))
            finally:
                browser.close()

        if queue:
            self.log(f"stopped at {len(self.pages)} pages; {len(queue)} queued URLs not visited")
        self.check_links()
        result = CrawlResult(
            start_url=self.start_url, origin=self.origin,
            crawled_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            sample=self.sample, pages=self.pages, links=self.links, skipped=self.skipped,
            options={
                "max_pages": self.max_pages, "mobile": self.mobile, "delay_ms": int(self.delay * 1000),
                "include_hidden": self.include_hidden, "respect_robots": self.respect_robots,
                "check_external": self.check_external, "user_agent": self.user_agent,
                "mobile_scale": self.mobile_scale, "include_subdomains": self.include_subdomains,
                "exclude": [rx.pattern for rx in self.exclude],
            },
        )
        (self.out_dir / "crawl.json").write_text(json.dumps(result.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8")
        return result

    def _visit(self, dpage, mpage, url: str, parent: str, via: str, depth: int, queue: deque) -> None:
        if not self.allowed(url):
            self.skipped.append({"url": url, "reason": "disallowed by robots.txt"})
            self.log(f"  robots: skip {url}")
            return
        idx = len(self.pages) + 1
        self.throttle.wait()
        t0 = time.monotonic()
        try:
            resp = dpage.goto(url, wait_until="load")
        except PWTimeout:
            resp = None
            if dpage.url == "about:blank":
                self._record_error(url, parent, "timeout")
                return
        except PWError as e:
            msg = str(e).splitlines()[0]
            if "Download is starting" in msg:
                self.status_cache[url] = "file download"
                self.skipped.append({"url": url, "reason": "file download, not a page"})
                self.log(f"  skip download {url}")
                return
            self._record_error(url, parent, f"error: {msg[:160]}")
            return
        try:
            dpage.wait_for_load_state("networkidle", timeout=3500)
        except PWTimeout:
            pass

        status = resp.status if resp else 200
        ctype = (resp.headers.get("content-type", "") if resp else "text/html").lower()
        final = normalize(dpage.url) or url
        self.status_cache[url] = str(status)
        if final != url:
            self.redirects[url] = final
            self.status_cache[final] = str(status)
        if status >= 400:
            self.skipped.append({"url": url, "reason": f"HTTP {status}"})
            self.log(f"  HTTP {status} {url}")
            return
        if "text/html" not in ctype and "xhtml" not in ctype:
            self.skipped.append({"url": url, "reason": f"not HTML ({ctype.split(';')[0]})"})
            self.log(f"  skip non-HTML {url} ({ctype.split(';')[0]})")
            return
        if final != url and (final in {p.url for p in self.pages} or final in {p.final_url for p in self.pages}):
            self.skipped.append({"url": url, "reason": f"redirects to already-archived {final}"})
            return
        if final != url and not self.in_scope(final):
            self.skipped.append({"url": url, "reason": f"redirects off-site to {final}"})
            return

        title = (dpage.title() or "").strip() or final
        slug = slugify(final)
        base_name = f"{idx:03d}-{slug}"

        # Lazy-load images, then collect
        try:
            dpage.evaluate(SCROLL_JS)
        except PWError:
            pass
        raw_links = dpage.evaluate(COLLECT_LINKS_JS)
        raw_blocks = dpage.evaluate(COLLECT_TEXT_JS, {"includeHidden": self.include_hidden})
        blocks = [Block(type=b["type"], text=b["text"], region=b.get("region", "")) for b in raw_blocks]
        words = sum(len(b.text.split()) for b in blocks)

        rec = PageRecord(index=idx, url=url, final_url=final, status=status, title=title,
                         parent=parent, found_via=via, depth=depth, blocks=blocks, word_count=words)

        # Screenshots
        d_rel = f"screenshots/desktop/{base_name}.png"
        self._pin_fixed(dpage)
        self._screenshot(dpage, self.out_dir / d_rel)
        rec.desktop_png = d_rel
        if mpage is not None:
            self.throttle.wait()
            try:
                mpage.goto(final, wait_until="load")
                try:
                    mpage.wait_for_load_state("networkidle", timeout=3500)
                except PWTimeout:
                    pass
                try:
                    mpage.evaluate(SCROLL_JS)
                except PWError:
                    pass
                m_rel = f"screenshots/mobile/{base_name}.png"
                self._pin_fixed(mpage)
                self._screenshot(mpage, self.out_dir / m_rel)
                rec.mobile_png = m_rel
            except (PWTimeout, PWError) as e:
                self.log(f"  ! mobile screenshot failed: {str(e).splitlines()[0][:120]}")

        self.pages.append(rec)
        self.log(f"[{idx}/{self.max_pages}] {status} {final}  ({len(blocks)} blocks, {words} words, {time.monotonic()-t0:.1f}s)")

        # Links
        new = 0
        page_seen_targets: set[str] = set()
        for l in raw_links:
            target = normalize(l.get("abs") or l.get("href"), base=final)
            if not target:
                continue
            internal = self.in_scope(target)
            key = (target, l.get("text", ""))
            if key in page_seen_targets:
                continue
            page_seen_targets.add(key)
            self.links.append(LinkSeen(source=final, url=target, text=l.get("text", "")[:200], internal=internal))
            if internal and not looks_binary(target) and target not in self.seen and not self.excluded(target):
                self.seen.add(target)
                queue.append((target, final, "link", depth + 1))
                new += 1
        if new:
            self.log(f"      +{new} new URLs queued ({len(queue)} waiting)")

    def _pin_fixed(self, page) -> None:
        if not self.pin_fixed:
            return
        try:
            page.evaluate(PIN_FIXED_JS)
            page.wait_for_timeout(150)
        except PWError:
            pass

    def _screenshot(self, page, path: Path) -> None:
        try:
            page.screenshot(path=str(path), full_page=True, animations="disabled", caret="hide")
        except (PWTimeout, PWError):
            try:
                page.screenshot(path=str(path), full_page=False)
            except (PWTimeout, PWError) as e:
                self.log(f"  ! screenshot failed: {str(e).splitlines()[0][:120]}")

    def _record_error(self, url: str, parent: str, reason: str) -> None:
        self.status_cache[url] = reason
        self.skipped.append({"url": url, "reason": reason})
        self.log(f"  ! {reason} {url}")

    # ---------------------------------------------------------------- link checking
    def check_links(self) -> None:
        """Fill in HTTP status for every distinct link target (HEAD, falling back to GET)."""
        targets = []
        for l in self.links:
            if l.url in self.status_cache:
                continue
            if not l.internal and not self.check_external:
                continue
            if l.url not in targets:
                targets.append(l.url)
        if targets:
            self.log(f"checking {len(targets)} link targets ...")
        for i, t in enumerate(targets, 1):
            self.status_cache[t] = self._probe(t)
            if i % 20 == 0:
                self.log(f"  {i}/{len(targets)} checked")
        for l in self.links:
            l.status = self.status_cache.get(l.url, "" if (not l.internal and not self.check_external) else "not checked")

    def _probe(self, url: str) -> str:
        try:
            status, _, _ = self._http(url, method="HEAD", timeout=15)
            if status in (403, 405, 500, 501) or status >= 400 and not same_origin(url, self.origin):
                status, _, _ = self._http(url, method="GET", timeout=15)
            return str(status)
        except urllib.error.URLError as e:
            return f"error: {getattr(e, 'reason', e)}"
        except Exception as e:  # noqa: BLE001
            return f"error: {type(e).__name__}: {str(e)[:100]}"
