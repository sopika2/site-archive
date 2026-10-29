"""screenshots-desktop.pdf / screenshots-mobile.pdf: one captioned full-page screenshot per PDF page."""
from __future__ import annotations

import io
from pathlib import Path

import img2pdf
from PIL import Image, ImageDraw, ImageFont

from ..model import CrawlResult

DPI = 150
MAX_PAGE_INCHES = 195  # Acrobat refuses pages above 200 in
BAND_BG = (243, 244, 246)
TEXT = (17, 24, 39)
URL_COLOR = (37, 99, 235)
RULE = (209, 213, 219)


def _font(size: int):
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _fit(draw, text: str, font, max_w: int) -> str:
    if draw.textlength(text, font=font) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text + "…"


def _compose(png_path: Path | None, caption_lines: list[tuple[str, tuple]], width_hint: int) -> bytes:
    """Return JPEG bytes of the screenshot with a caption band above it."""
    img = Image.open(png_path).convert("RGB") if png_path and png_path.exists() else None
    w = img.width if img else width_hint
    scale = max(1.0, w / 1000)
    big = _font(int(26 * scale))
    small = _font(int(18 * scale))
    pad = int(18 * scale)
    gap = int(8 * scale)
    fonts = [big] + [small] * (len(caption_lines) - 1)
    line_h = [int(f.size * 1.35) for f in fonts]
    band_h = pad * 2 + sum(line_h) + gap * (len(caption_lines) - 1)

    h = img.height if img else int(width_hint * 0.6)
    canvas = Image.new("RGB", (w, band_h + h), "white")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, 0, w, band_h], fill=BAND_BG)
    y = pad
    for (text, color), f, lh in zip(caption_lines, fonts, line_h):
        draw.text((pad, y), _fit(draw, text, f, w - 2 * pad), fill=color, font=f)
        y += lh + gap
    draw.line([(0, band_h - 1), (w, band_h - 1)], fill=RULE, width=max(1, int(scale)))
    if img:
        canvas.paste(img, (0, band_h))
    else:
        draw.text((pad, band_h + pad), "(screenshot not available)", fill=TEXT, font=big)

    # keep the PDF page under the viewer limit
    max_h_px = MAX_PAGE_INCHES * DPI
    if canvas.height > max_h_px:
        ratio = max_h_px / canvas.height
        canvas = canvas.resize((max(1, int(canvas.width * ratio)), max_h_px), Image.LANCZOS)

    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=85, dpi=(DPI, DPI), optimize=True)
    return buf.getvalue()


def write_screenshot_pdf(result: CrawlResult, out_dir: Path, kind: str, path: Path) -> None:
    images: list[bytes] = []
    width_hint = 1440 if kind == "desktop" else 780
    for p in result.pages:
        rel = p.desktop_png if kind == "desktop" else p.mobile_png
        png = (out_dir / rel) if rel else None
        caption = [
            (f"{p.index}. {p.title}", TEXT),
            (p.final_url, URL_COLOR),
            (f"{kind.capitalize()} view  |  {result.crawled_at}  |  {p.nav_path}", (107, 114, 128)),
        ]
        images.append(_compose(png, caption, width_hint))
    if not images:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(img2pdf.convert(images))
