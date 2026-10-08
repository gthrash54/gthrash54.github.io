#!/usr/bin/env python3
"""One-off generator for og.png (1200x630 share card). Not run by update.sh.

Usage: tools/make-og.py [FONT_DIR]
FONT_DIR holds TTFs for Space Grotesk and Inter (downloaded from Google Fonts into a
non-committed folder); falls back to DejaVu Sans when a face is missing.
"""
import math, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
NAME = "Garrett W. Thrash"
TAGLINE = "Teaching brain implants to listen."
STATUS = "MD Candidate (Class of 2027)\nIncoming PhD Student, Neuroengineering (2027)\nUniversity of Alabama at Birmingham"
URL = "garrettthrash.com"
BG, INK, INK2, ACCENT, ACCENT2 = "#0a0f1c", "#e9eef8", "#aab4c8", "#46d3c2", "#f2b352"
W, H = 1200, 630

def find_font(font_dir, family, weight, size):
    fallback = {"Space Grotesk": "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
                "Inter": "/usr/share/fonts/TTF/DejaVuSans.ttf"}[family]
    best = None
    for p in sorted(Path(font_dir).glob("*.ttf")) if font_dir else []:
        try:
            f = ImageFont.truetype(str(p), size)
        except OSError:
            continue
        fam, style = f.getname()
        if fam.startswith(family):
            try:
                f.set_variation_by_axes([weight])
            except Exception:
                pass
            best = f if best is None or str(weight) in style else best
    if best:
        return best
    for cand in (fallback, "/usr/share/fonts/dejavu/" + Path(fallback).name):
        if Path(cand).exists():
            return ImageFont.truetype(cand, size)
    return ImageFont.load_default(size)

def main():
    font_dir = sys.argv[1] if len(sys.argv) > 1 else None
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    # faint LFP trace along the bottom
    pts = [(x, 575 + 14 * math.sin(x / 38) * math.sin(x / 9 + 1) + 6 * math.sin(x / 3.1)) for x in range(0, W, 3)]
    d.line(pts, fill=(70, 211, 194, 90), width=2)
    # portrait with ring
    cx, cy, r = 250, 300, 170
    src = Image.open(ROOT / "headshot.jpg").convert("RGB").resize((2 * r, 2 * r), Image.LANCZOS)
    mask = Image.new("L", (4 * r, 4 * r), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 4 * r, 4 * r), fill=255)
    mask = mask.resize((2 * r, 2 * r), Image.LANCZOS)
    im.paste(src, (cx - r, cy - r), mask)
    d.ellipse((cx - r - 10, cy - r - 10, cx + r + 10, cy + r + 10), outline=(70, 211, 194, 60), width=2)
    for k in range(4):  # segmented lead-contact ring
        a0 = -90 + k * 90 + 6
        d.arc((cx - r - 14, cy - r - 14, cx + r + 14, cy + r + 14), a0, a0 + 78, fill=ACCENT, width=6)
    d.arc((cx - r - 14, cy - r - 14, cx + r + 14, cy + r + 14), -84, -60, fill=ACCENT2, width=6)
    # text
    x0 = 480
    f_name = find_font(font_dir, "Space Grotesk", 600, 66)
    f_tag = find_font(font_dir, "Inter", 500, 36)
    f_stat = find_font(font_dir, "Inter", 400, 23)
    f_url = find_font(font_dir, "Inter", 500, 24)
    d.text((x0, 150), NAME, font=f_name, fill=INK)
    d.text((x0, 240), TAGLINE, font=f_tag, fill=ACCENT)
    d.multiline_text((x0, 318), STATUS, font=f_stat, fill=INK2, spacing=10)
    d.text((x0, 455), URL, font=f_url, fill=ACCENT2)
    out = ROOT / "og.png"
    im.save(out, optimize=True)
    print(f"wrote {out} {im.size}")

if __name__ == "__main__":
    main()
