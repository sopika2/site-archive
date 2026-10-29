"""index.html: offline browser for the archive (text, screenshots, deliverable links)."""
from __future__ import annotations

import html
from pathlib import Path

from ..linkstatus import OK, classify
from ..model import Block, CrawlResult

CSS = """
:root{--bg:#fff;--fg:#111827;--muted:#6b7280;--line:#e5e7eb;--accent:#2563eb;--band:#f9fafb}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif;color:var(--fg);background:var(--bg)}
header{padding:24px 32px;border-bottom:1px solid var(--line);background:var(--band)}
header h1{margin:0 0 6px;font-size:22px}header p{margin:2px 0;color:var(--muted)}
.deliverables a{display:inline-block;margin:10px 10px 0 0;padding:6px 12px;border:1px solid var(--line);border-radius:6px;background:#fff;text-decoration:none;color:var(--accent)}
main{padding:24px 32px;max-width:1400px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{background:var(--band);position:sticky;top:0}td.num{color:var(--muted);text-align:right}
a{color:var(--accent)}
section.page{margin-top:40px;padding-top:24px;border-top:2px solid var(--line)}
section.page h2{margin:0 0 4px;font-size:20px}section.page .meta{color:var(--muted);font-size:13px;margin-bottom:12px}
.cols{display:grid;grid-template-columns:minmax(0,1fr) 360px;gap:24px}
@media(max-width:900px){.cols{grid-template-columns:1fr}}
.shots img{display:block;max-width:100%;max-height:420px;object-fit:cover;object-position:top;border:1px solid var(--line);border-radius:4px;margin-bottom:6px}
.shots a{font-size:13px}
.text h3,.text h4,.text h5{margin:14px 0 4px}.text h3{font-size:18px}.text h4{font-size:16px}.text h5{font-size:15px}
.text p{margin:4px 0}.text li{margin:2px 0}.text .lab{color:var(--muted);font-size:12px;font-style:italic;margin-right:6px}
.text .region{margin:14px 0 4px;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.06em}
.text .cta{font-weight:600}.top{font-size:13px}
"""
REGION_NAMES = {"nav": "Navigation", "header": "Header", "footer": "Footer", "": "Main content"}


def _block_html(b: Block) -> str:
    t, x = b.type, html.escape(b.text)
    if t == "h1":
        return f"<h3>{x}</h3>"
    if t == "h2":
        return f"<h4>{x}</h4>"
    if t in ("h3", "h4", "h5", "h6"):
        return f"<h5>{x}</h5>"
    if t == "li":
        return f"<li>{x}</li>"
    if t == "link":
        return f'<p><span class="lab">Link:</span>{x}</p>'
    if t == "cta":
        return f'<p class="cta"><span class="lab">Call to action:</span>{x}</p>'
    if t == "button":
        return f'<p><span class="lab">Button:</span>{x}</p>'
    return "".join(f"<p>{html.escape(line)}</p>" for line in b.text.split("\n") if line.strip())


def _blocks_html(blocks: list[Block]) -> str:
    out = []
    has_regions = any(b.region for b in blocks)
    region = None
    in_list = False
    for b in blocks:
        if has_regions and b.region != region:
            if in_list:
                out.append("</ul>")
                in_list = False
            region = b.region
            out.append(f'<div class="region">{REGION_NAMES.get(region, region)}</div>')
        if b.type == "li" and not in_list:
            out.append("<ul>")
            in_list = True
        elif b.type != "li" and in_list:
            out.append("</ul>")
            in_list = False
        out.append(_block_html(b))
    if in_list:
        out.append("</ul>")
    return "\n".join(out) or '<p class="lab">(no visible text extracted)</p>'


def write_index(result: CrawlResult, path: Path, shared_blocks: list[Block] | None = None, stats: dict | None = None) -> None:
    stats = stats or {}
    site = result.options.get("site_name") or result.origin.split("//", 1)[-1]
    mobile = result.options.get("mobile", True)
    e = html.escape
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>Archive of {e(site)}</title><style>{CSS}</style></head><body>"]
    parts.append(f"<header><h1>Website archive: {e(site)}</h1>"
                 f"<p>Source: <a href='{e(result.start_url)}'>{e(result.start_url)}</a> &nbsp;|&nbsp; Crawled {e(result.crawled_at)}"
                 f" &nbsp;|&nbsp; {len(result.pages)} pages &nbsp;|&nbsp; {stats.get('broken_links', 0)} broken links, {stats.get('verify_links', 0)} to verify"
                 + (f" &nbsp;|&nbsp; <strong>SAMPLE: first {result.sample} pages</strong>" if result.sample else "") + "</p>"
                 "<div class='deliverables'><a href='content.docx'>content.docx (all page text)</a>"
                 "<a href='screenshots-desktop.pdf'>screenshots-desktop.pdf</a>"
                 + ("<a href='screenshots-mobile.pdf'>screenshots-mobile.pdf</a>" if mobile else "")
                 + "<a href='sitemap.xlsx'>sitemap.xlsx (navigation, broken links, Keep/Rewrite/Eliminate)</a></div></header><main>")

    parts.append("<h2 id='pages'>Pages</h2><table><thead><tr><th>#</th><th>Title</th><th>Navigation path</th><th>Words</th>"
                 "<th>Text</th><th>Desktop</th>" + ("<th>Mobile</th>" if mobile else "") + "<th>Sitemap row</th></tr></thead><tbody>")
    for p in result.pages:
        parts.append(
            f"<tr><td class='num'>{p.index}</td><td><a href='{e(p.final_url)}'>{e(p.title)}</a><br><small style='color:var(--muted)'>{e(p.final_url)}</small></td>"
            f"<td>{e(p.nav_path)}</td><td class='num'>{p.word_count}</td><td><a href='#page-{p.index}'>text</a></td>"
            f"<td>{'<a href=' + repr(p.desktop_png) + '>PNG</a>' if p.desktop_png else '-'}</td>"
            + (f"<td>{'<a href=' + repr(p.mobile_png) + '>PNG</a>' if p.mobile_png else '-'}</td>" if mobile else "")
            + f"<td class='num'>Pages!A{p.index + 1}</td></tr>")
    parts.append("</tbody></table>")

    for p in result.pages:
        parts.append(f"<section class='page' id='page-{p.index}'><h2>{p.index}. {e(p.title)}</h2>"
                     f"<div class='meta'><a href='{e(p.final_url)}'>{e(p.final_url)}</a> &nbsp;|&nbsp; {e(p.nav_path)} &nbsp;|&nbsp; "
                     f"depth {p.depth} &nbsp;|&nbsp; {p.word_count} words &nbsp;|&nbsp; <a class='top' href='#pages'>back to list</a></div>"
                     "<div class='cols'><div class='text'>" + _blocks_html(p.blocks) + "</div><div class='shots'>")
        if p.desktop_png:
            parts.append(f"<a href='{e(p.desktop_png)}'><img loading='lazy' src='{e(p.desktop_png)}' alt='desktop screenshot'></a>"
                         f"<a href='{e(p.desktop_png)}'>Desktop screenshot (full page)</a><br>")
        if p.mobile_png:
            parts.append(f"<a href='{e(p.mobile_png)}'><img loading='lazy' src='{e(p.mobile_png)}' alt='mobile screenshot' style='max-width:200px'></a>"
                         f"<a href='{e(p.mobile_png)}'>Mobile screenshot (full page)</a>")
        parts.append("</div></div></section>")

    if shared_blocks:
        parts.append("<section class='page' id='shared'><h2>Shared elements (navigation, header, footer)</h2>"
                     "<div class='meta'>Repeated on almost every page; removed from the page sections above.</div>"
                     "<div class='text'>" + _blocks_html(shared_blocks) + "</div></section>")

    problems = [(l, *classify(l)) for l in result.links]
    problems = [x for x in problems if x[1] != OK]
    problems.sort(key=lambda x: (x[1] != "broken", not x[0].internal, x[0].url))
    if problems:
        parts.append("<section class='page' id='broken'><h2>Broken links and links to verify</h2><table><thead><tr><th>Source page</th><th>Link</th><th>Status</th><th>Assessment</th></tr></thead><tbody>")
        for l, cat, note in problems:
            parts.append(f"<tr><td>{e(l.source)}</td><td>{e(l.url)}<br><small>{e(l.text)}</small></td><td>{e(l.status)}</td><td><strong>{e(cat)}</strong><br><small>{e(note)}</small></td></tr>")
        parts.append("</tbody></table></section>")

    parts.append("</main></body></html>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")
