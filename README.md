# site-archive

Document a public website before a redesign. One command produces:

| File | What it is |
|---|---|
| `content.docx` | Every page's visible text, editable, one section per page (title + URL heading, then headings with their H1/H2/H3 levels, paragraphs, list items, link / button / call-to-action labels, in reading order). |
| `screenshots-desktop.pdf` | One full-page desktop screenshot (1440 px wide) per page, each PDF page captioned with the page title and URL, in the same order as the Word document. |
| `screenshots-mobile.pdf` | Same for mobile (390 px wide, retina). |
| `screenshots/desktop/*.png`, `screenshots/mobile/*.png` | The raw screenshots, named `001-home.png`, `002-about.png`, ... |
| `sitemap.xlsx` | Sheet **Pages** (Index, Title, URL, Parent page, Navigation path, Depth, Word count, screenshot files, empty Keep / Rewrite / Eliminate columns), **Broken links** (source page, link, status, assessment), **All links** (every link seen with its HTTP status), **Skipped URLs**, **Summary**. |
| `index.html` | Offline index: page table, extracted text, screenshot thumbnails, links to the files above. Open it in any browser. |
| `crawl.json` | Raw crawl data; lets you regenerate the deliverables with `--rebuild` without crawling again. |

The crawler is read-only and polite: same-origin only, obeys `robots.txt` (including `Crawl-delay`), one request per second by default, identifies itself in the User-Agent, never submits forms. No LLM or paid API is involved.

## Install

Python 3.10+.

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

## Usage

```bash
python -m site_archive https://example.com --out out/example
```

Three-page sample for a client (same deliverables, first 3 pages only):

```bash
python -m site_archive https://example.com --out out/example-sample --sample 3
```

Options:

| Option | Default | Meaning |
|---|---|---|
| `--out DIR` | `out/<host>` | Output directory. |
| `--max-pages N` | 300 | Stop after N pages. |
| `--sample N` | off | Archive only the first N pages (overrides `--max-pages`). |
| `--mobile` / `--no-mobile` | mobile on | Take mobile screenshots too. |
| `--mobile-scale 1|2` | 2 | Device pixel ratio for mobile PNGs (2 = sharp, 1 = smaller files). |
| `--delay-ms N` | 1000 | Minimum gap between requests. `robots.txt` `Crawl-delay` overrides it when larger. |
| `--timeout N` | 45 | Per-page load timeout in seconds. |
| `--dedupe-boilerplate` | off | Move text repeated on 80 %+ of pages (nav, footer) into one "Shared elements" section instead of repeating it in every page section. Off by default so each page keeps its exact wording. |
| `--include-hidden` | off | Also extract text hidden by CSS (closed accordions, mobile-only menus). |
| `--include-subdomains` | off | Also crawl `blog.example.com`, `shop.example.com`, ... |
| `--exclude REGEX` | none | Skip URLs matching a regular expression; repeatable. Use it for crawler traps such as calendars (`--exclude '/calendar/'`) or faceted filters (`--exclude '\?sort='`). The links are still recorded and checked. |
| `--no-external-links` | off | Skip HTTP-checking links to other domains (faster). |
| `--keep-fixed` | off | Do not pin fixed/sticky bars before screenshots. By default they are pinned so a sticky header does not float mid-page in a full-page capture. |
| `--ignore-robots` | off | Crawl even where `robots.txt` disallows. Only for sites you own. |
| `--user-agent STR` | Chrome-like + `SiteArchive/1.0` | Custom User-Agent. |
| `--rebuild` | off | Skip crawling; regenerate the deliverables from `<out>/crawl.json` (for example to add `--dedupe-boilerplate` afterwards). |

## How pages are discovered

1. The start URL, then every same-origin `a[href]` found in the rendered HTML, breadth-first (so the navigation structure and "Parent page" / "Navigation path" columns follow the menus).
2. `/sitemap.xml` (and sitemap indexes, plus any sitemap listed in `robots.txt`) and `/rss.xml` / `/feed.xml`, appended after the start page's links.

URLs are normalised (fragment and tracking parameters removed, trailing slash dropped, `index.html` folded) and deduplicated. Binary assets (PDF, images, media, CSS/JS) are recorded as links but not crawled. Redirects to an already archived page are skipped.

## Broken links

Every distinct link target is checked with a HEAD request (GET on 403/405). The **Broken links** sheet lists each occurrence with an *Assessment* column:

- **broken**: 404/410, DNS failure, or any 4xx on the site itself.
- **server error**: 5xx.
- **verify manually**: external sites that answered 403/400/429 (bot protection), timed out, or had a TLS problem. These are often fine in a browser; the client should click them.

## Limits

- Pages behind logins, forms or cookie walls are captured as a visitor sees them.
- Text extraction is DOM-based: it keeps reading order and heading levels but cannot know which block is the "main" content, so by default nav and footer text appear on every page (labelled `[Navigation]`, `[Footer]`). Use `--dedupe-boilerplate` to collapse them.
- Links that start a file download (CSV exports, generated PDFs) are recorded as "file download" and not archived as pages.
- Very tall pages are scaled down in the PDFs to stay under the 200-inch page limit of PDF viewers; the PNGs are untouched.
- Screenshots of 300 pages at retina mobile scale can take a few GB of disk; use `--mobile-scale 1` for big sites.

## Project layout

```
site_archive/
  cli.py            argument parsing, entry point
  crawler.py        Playwright crawl, robots.txt, sitemap/RSS seeds, link checking
  extract_js.py     in-page JavaScript: links, visible text in reading order, scrolling, pinning fixed bars
  urls.py           normalisation, slugs, binary-asset filter
  build.py          navigation paths, boilerplate detection, runs the writers
  linkstatus.py     broken / verify-manually classification
  writers/          docx, pdf, xlsx, html
```

License: use freely for client work.
