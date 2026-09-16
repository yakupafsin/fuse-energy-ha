#!/usr/bin/env python3
"""Resize the artwork in brands/src/ to the sizes home-assistant/brands requires.

    python3 brands/make_assets.py

See brands/README.md for the source files, the output sizes, and how to replace
the artwork. Requires Pillow.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"
OUT = HERE / "fuse_energy"

# Home Assistant asks for each asset at 1x and 2x. Icons are square; logos keep
# their own proportions and are sized by height.
SIZES = ((256, ""), (512, "@2x"))
ASSETS = (
    ("mark.png", "icon", True),
    ("lockup.png", "logo", False),
    ("lockup-dark.png", "dark_logo", False),
)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for filename, stem, square in ASSETS:
        source = Image.open(SRC / filename).convert("RGBA")
        for size, suffix in SIZES:
            width = size if square else round(source.width * size / source.height)
            out = OUT / f"{stem}{suffix}.png"
            source.resize((width, size), Image.LANCZOS).save(out, optimize=True)
            print(f"  {out.name:18} {width:>4}x{size:<4} {out.stat().st_size // 1024}KB")


if __name__ == "__main__":
    main()
