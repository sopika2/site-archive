# Handover: producing a site archive

Working directory: `E:\Proj\tools\site-archive`. Python 3.10, Playwright Chromium already installed on this machine. On a new machine run `pip install -r requirements.txt` and `python -m playwright install chromium` first.

Replace `https://vegasaviation.com` with the client's URL.

## 1. Three-page sample (send within the hour)

```bash
python -m site_archive https://vegasaviation.com --out out/vegasaviation-sample --sample 3
```

Takes about 2 minutes. Zip the whole `out/vegasaviation-sample` folder, or send just `content.docx`, `screenshots-desktop.pdf`, `screenshots-mobile.pdf` and `sitemap.xlsx` (the Word, PDF and Excel files stand alone; `index.html` needs the `screenshots/` folder next to it).

## 2. Full archive

```bash
python -m site_archive https://vegasaviation.com --out out/vegasaviation
```

Roughly 15-30 seconds per page (desktop + mobile capture at one request per second), so a 30-page site takes about 10 minutes and a 200-page site over an hour. The console shows `[n/max] status url` for every page. Everything is written at the end; if it is interrupted, run it again.

## 3. Variants you may be asked for

Collapse the repeated navigation/footer text into one section instead of repeating it on every page (regenerates from the crawl, no new requests):

```bash
python -m site_archive https://vegasaviation.com --out out/vegasaviation --rebuild --dedupe-boilerplate
```

Desktop only, smaller files:

```bash
python -m site_archive https://vegasaviation.com --out out/vegasaviation --no-mobile
```

Main pages only, no blog (links are still recorded and checked):

```bash
python -m site_archive https://vegasaviation.com --out out/vegasaviation-main --exclude '/blog/'
```

Site spread over subdomains (`blog.`, `shop.`):

```bash
python -m site_archive https://example.com --out out/example --include-subdomains
```

## 4. Before sending

- Open `sitemap.xlsx`, sheet **Summary**: page count and broken-link count go in the delivery message.
- Sheet **Broken links**: rows marked *verify manually* are external sites that block bots (Facebook, airlines, government sites); click two or three to confirm they open, and say so in the message.
- Open `screenshots-desktop.pdf` and spot-check the first and last page: header at the top, caption readable.
- `content.docx`: the Contents list links to each page section; headings use the styles Site H1 / Site H2 / Site H3 so the client can see levels in Word's navigation pane.

## 5. What the 2026-10-29 test run of vegasaviation.com produced

- 194 pages in 39 minutes: 37 navigation pages plus 157 blog posts (`sitemap-index.xml` lists the blog; the brief's "about 30 pages" counts only the menu). If the client only wants the menu pages, add `--exclude '/blog/'` (the blog index itself stays).
- Confirmed broken links: 4 (all to eaa.org, from the Scholarships page and one blog post). 111 external URLs are marked *verify manually* (Facebook, FAA, airlines, Google Maps refuse automated requests).
- File sizes: content.docx 650 KB, sitemap.xlsx 1.2 MB, desktop PDF about 220 MB, mobile PDF about 330 MB, PNGs about 1.4 GB. For hand-over, send the Word/Excel files and the PDFs via a file-transfer link; the PNG folders are optional.
- Links that answer 403/400 to automated requests are listed as *verify manually*, not as broken.
- No LLM or paid service is used; the only network traffic is to the client's site and to link targets for status checks.
