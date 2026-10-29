"""Post-processing of a crawl result and orchestration of the deliverable writers."""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

from .model import Block, CrawlResult, PageRecord
from .writers.docx_writer import write_docx
from .writers.html_writer import write_index
from .writers.pdf_writer import write_screenshot_pdf
from .writers.xlsx_writer import write_xlsx

TITLE_SEPS = re.compile(r"\s+(\||-|–|—|::|·|•|»|>)\s+")


def site_name_from_titles(pages: list[PageRecord]) -> str:
    """The segment most titles share (e.g. 'Vegas Aviation' in 'Contact | Vegas Aviation')."""
    counts: Counter[str] = Counter()
    for p in pages:
        parts = [s for s in TITLE_SEPS.split(p.title) if s and not TITLE_SEPS.fullmatch(" " + s + " ")]
        parts = [s.strip() for s in parts if s.strip() and s.strip() not in "|-–—::·•»>"]
        if len(parts) >= 2:
            counts[parts[0]] += 1
            counts[parts[-1]] += 1
    if not counts:
        return ""
    seg, n = counts.most_common(1)[0]
    if n >= max(2, math.ceil(0.4 * len(pages))):
        return seg
    return ""


def short_title(title: str, site_name: str, is_root: bool) -> str:
    t = title.strip()
    if site_name:
        parts = [s.strip() for s in TITLE_SEPS.split(t) if s.strip() and s.strip() not in "|-–—::·•»>"]
        if len(parts) >= 2 and parts[-1] == site_name:
            t = " - ".join(parts[:-1])
        elif len(parts) >= 2 and parts[0] == site_name:
            t = " - ".join(parts[1:])
    if is_root:
        return "Home"
    # use the first segment as the navigation label ("How it Works | Guide" -> "How it Works")
    parts = [s.strip() for s in TITLE_SEPS.split(t) if s.strip() and s.strip() not in "|-–—::·•»>"]
    if len(parts) >= 2 and len(parts[0]) >= 3:
        t = parts[0]
    return t or title


def adopt_parents(result: CrawlResult) -> None:
    """Pages seeded from the sitemap/RSS get a parent if a crawled page links to them (lowest depth wins)."""
    pages = result.pages
    by_url: dict[str, PageRecord] = {}
    for p in pages:
        by_url[p.url] = p
        by_url[p.final_url] = p
    inbound: dict[str, list[PageRecord]] = {}
    for l in result.links:
        src = by_url.get(l.source)
        tgt = by_url.get(l.url)
        if src is None or tgt is None or src is tgt:
            continue
        inbound.setdefault(tgt.final_url, []).append(src)
    root = result.origin
    changed = True
    rounds = 0
    while changed and rounds < 20:
        changed = False
        rounds += 1
        for p in sorted(pages, key=lambda x: x.depth):
            if p.parent or p.final_url.rstrip("/") == root:
                continue
            cands = [s for s in inbound.get(p.final_url, []) if s.parent or s.final_url.rstrip("/") == root]
            if not cands:
                continue
            best = min(cands, key=lambda s: (s.depth, s.index))
            p.parent = best.final_url
            p.depth = best.depth + 1
            changed = True


def assign_nav_paths(result: CrawlResult) -> None:
    pages = result.pages
    adopt_parents(result)
    site_name = site_name_from_titles(pages)
    by_url: dict[str, PageRecord] = {}
    for p in pages:
        by_url[p.url] = p
        by_url[p.final_url] = p
    for p in pages:
        p.short_title = short_title(p.title, site_name, is_root=(p.final_url.rstrip("/") == result.origin))
    for p in pages:
        chain = [p.short_title]
        cur = p
        guard = 0
        while cur.parent and cur.parent in by_url and guard < 50:
            cur = by_url[cur.parent]
            if cur is p:
                break
            chain.append(cur.short_title)
            guard += 1
        chain.reverse()
        p.nav_path = " > ".join(chain)
    result.options["site_name"] = site_name


def strip_boilerplate(result: CrawlResult) -> list[Block]:
    """Remove blocks repeated on (almost) every page; return them once, in first-seen order."""
    pages = result.pages
    if len(pages) < 3:
        return []
    threshold = max(2, math.ceil(0.8 * len(pages)))
    per_page_keys = [{(b.type, b.text) for b in p.blocks} for p in pages]
    counts: Counter[tuple[str, str]] = Counter()
    for keys in per_page_keys:
        counts.update(keys)
    common = {k for k, n in counts.items() if n >= threshold}
    if not common:
        return []
    shared: list[Block] = []
    seen: set[tuple[str, str]] = set()
    for p in pages:
        kept = []
        for b in p.blocks:
            key = (b.type, b.text)
            if key in common:
                if key not in seen:
                    seen.add(key)
                    shared.append(b)
                continue
            kept.append(b)
        p.blocks = kept
        p.word_count = sum(len(b.text.split()) for b in kept)
    return shared


def build_outputs(result: CrawlResult, out_dir: Path, dedupe_boilerplate: bool = False, log=print,
                  save_json: bool = True) -> dict:
    out_dir = Path(out_dir)
    assign_nav_paths(result)
    if save_json:  # persist titles/paths before any boilerplate removal so --rebuild is repeatable
        (out_dir / "crawl.json").write_text(json.dumps(result.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8")
    shared = strip_boilerplate(result) if dedupe_boilerplate else []

    log("writing content.docx ...")
    write_docx(result, out_dir / "content.docx", shared_blocks=shared)
    log("writing screenshots-desktop.pdf ...")
    write_screenshot_pdf(result, out_dir, "desktop", out_dir / "screenshots-desktop.pdf")
    if result.options.get("mobile", True):
        log("writing screenshots-mobile.pdf ...")
        write_screenshot_pdf(result, out_dir, "mobile", out_dir / "screenshots-mobile.pdf")
    log("writing sitemap.xlsx ...")
    stats = write_xlsx(result, out_dir / "sitemap.xlsx")
    log("writing index.html ...")
    write_index(result, out_dir / "index.html", shared_blocks=shared, stats=stats)
    return stats
