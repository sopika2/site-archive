"""Plain data records shared by the crawler and the writers."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Block:
    """One piece of visible text in reading order."""
    type: str          # h1..h6, p, li, link, cta, button
    text: str
    region: str = ""   # "", "nav", "header", "footer"


@dataclass
class LinkSeen:
    source: str        # page URL the link was found on
    url: str           # normalised absolute link target
    text: str = ""
    internal: bool = True
    status: str = ""   # "200", "404", "error: ..." (filled by link checker)


@dataclass
class PageRecord:
    index: int
    url: str
    final_url: str
    status: int
    title: str
    short_title: str = ""
    parent: str = ""            # parent page URL ("" for root / sitemap-found)
    found_via: str = "link"     # link | start | sitemap.xml | rss.xml
    depth: int = 0
    nav_path: str = ""
    word_count: int = 0
    blocks: list[Block] = field(default_factory=list)
    desktop_png: str = ""       # relative path inside out dir
    mobile_png: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PageRecord":
        d = dict(d)
        d["blocks"] = [Block(**b) for b in d.get("blocks", [])]
        return cls(**d)


@dataclass
class CrawlResult:
    start_url: str
    origin: str
    crawled_at: str
    sample: int | None
    pages: list[PageRecord]
    links: list[LinkSeen]
    skipped: list[dict[str, Any]]   # non-HTML / blocked / errored URLs with reason
    options: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_url": self.start_url,
            "origin": self.origin,
            "crawled_at": self.crawled_at,
            "sample": self.sample,
            "options": self.options,
            "pages": [p.to_dict() for p in self.pages],
            "links": [asdict(l) for l in self.links],
            "skipped": self.skipped,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CrawlResult":
        return cls(
            start_url=d["start_url"],
            origin=d["origin"],
            crawled_at=d["crawled_at"],
            sample=d.get("sample"),
            options=d.get("options", {}),
            pages=[PageRecord.from_dict(p) for p in d["pages"]],
            links=[LinkSeen(**l) for l in d["links"]],
            skipped=d.get("skipped", []),
        )
