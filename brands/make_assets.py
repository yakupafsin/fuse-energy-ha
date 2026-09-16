#!/usr/bin/env python3
"""Build the brands artwork from a single source lockup.

Regenerates every file in `brands/fuse_energy/` at the sizes
https://github.com/home-assistant/brands requires, so new artwork only has to be
dropped in once:

    python3 brands/make_assets.py path/to/lockup.png

The source should be a landscape lockup -- square mark on the left, wordmark to
the right -- as a PNG with a transparent background. Everything else is derived:

  icon        the square mark alone, wordmark cut away, padded (never stretched)
              to 1:1 because icons must be square
  logo        the whole lockup, trimmed
  dark_logo   the same with the near-black wordmark lightened, because a dark
              wordmark disappears against Home Assistant's default dark theme

Requires Pillow.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

OUT = Path(__file__).resolve().parent / "fuse_energy"

# The mark is found by colour rather than by a hard-coded box, so a redraw that
# moves or resizes it still works.
def _is_brand_colour(p: tuple[int, int, int, int]) -> bool:
    r, g, b, a = p
    return a > 200 and r > 180 and 50 < g < 165 and b < 95


def _mark_box(im: Image.Image) -> tuple[int, int, int, int]:
    """Bounding box of the square mark: the first contiguous run of brand colour."""
    w, h = im.size
    px = im.load()
    cols = [x for x in range(w) if any(_is_brand_colour(px[x, y]) for y in range(h))]
    rows = [y for y in range(h) if any(_is_brand_colour(px[x, y]) for x in range(w))]
    if not cols or not rows:
        raise SystemExit("no brand-coloured mark found — is the source transparent?")
    x0 = x1 = cols[0]
    for x in cols:                      # stop at the gap before the wordmark
        if x <= x1 + 3:
            x1 = x
        else:
            break
    return x0, rows[0], x1, rows[-1]


def _square(im: Image.Image, box: tuple[int, int, int, int], pad: int = 6) -> Image.Image:
    """Crop the mark onto a transparent square canvas, preserving its proportions."""
    x0, y0, x1, y1 = box
    mark = im.crop((x0, y0, x1 + 1, y1 + 1))
    side = max(mark.size) + pad * 2
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(mark, ((side - mark.width) // 2, (side - mark.height) // 2), mark)
    return canvas


def _lighten_wordmark(im: Image.Image) -> Image.Image:
    """Near-black pixels to near-white. The mark's own white and orange are untouched."""
    out = im.copy()
    px = out.load()
    for y in range(out.height):
        for x in range(out.width):
            r, g, b, a = px[x, y]
            if a > 30 and r < 90 and g < 90 and b < 90:
                px[x, y] = (237, 240, 245, a)
    return out


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    src = Image.open(sys.argv[1]).convert("RGBA")
    OUT.mkdir(parents=True, exist_ok=True)

    icon = _square(src, _mark_box(src))
    for size, name in ((256, "icon.png"), (512, "icon@2x.png")):
        icon.resize((size, size), Image.LANCZOS).save(OUT / name, optimize=True)

    lockup = src.crop(src.getbbox())
    dark = _lighten_wordmark(lockup)
    for height, light, darkname in ((256, "logo.png", "dark_logo.png"),
                                    (512, "logo@2x.png", "dark_logo@2x.png")):
        width = round(lockup.width * height / lockup.height)
        lockup.resize((width, height), Image.LANCZOS).save(OUT / light, optimize=True)
        dark.resize((width, height), Image.LANCZOS).save(OUT / darkname, optimize=True)

    for f in sorted(OUT.iterdir()):
        with Image.open(f) as im:
            print(f"  {f.name:18} {im.size[0]:>4}x{im.size[1]:<4} {im.mode} "
                  f"{f.stat().st_size // 1024}KB")


if __name__ == "__main__":
    main()
