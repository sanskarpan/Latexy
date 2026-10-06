"""Export the selected Imprint mark to browser and install assets.

Run from anywhere with: python docs/brand/export-icons.py
The SVG files are the vector source; Pillow only produces raster fallbacks.
"""

from pathlib import Path
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
NAVY = "#19375D"
PAPER = "#F7F3E9"
MARK = "M16 13h29v14H30v42h44v14H16V13Zm39 0h25v37H66V27H55V13Z"


def svg(size: int) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" width="{size}" height="{size}" role="img" aria-label="Latexy">
  <rect width="96" height="96" rx="18" fill="{NAVY}"/>
  <path fill="{PAPER}" d="{MARK}"/>
</svg>
'''


def mark_svg(color: str) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" role="img" aria-label="Latexy mark">
  <path fill="{color}" d="{MARK}"/>
</svg>
'''


def raster(size: int, maskable: bool = False) -> Image.Image:
    scale = 8
    canvas = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    if maskable:
        draw.rectangle((0, 0, size * scale, size * scale), fill=NAVY)
    else:
        draw.rounded_rectangle((0, 0, size * scale - 1, size * scale - 1), radius=round(size * scale * 18 / 96), fill=NAVY)

    def rect(box: tuple[int, int, int, int]) -> None:
        factor = .66 if maskable else 1.0
        coords = [round((48 + (n - 48) * factor) * size * scale / 96) for n in box]
        draw.rectangle(coords, fill=PAPER)

    # Exact rectangular construction of the five contiguous parts of MARK.
    rect((16, 13, 30, 83))
    rect((16, 69, 74, 83))
    rect((16, 13, 45, 27))
    rect((55, 13, 80, 27))
    rect((66, 13, 80, 50))
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    icons = FRONTEND / "public" / "icons"
    brand = FRONTEND / "public" / "brand"
    icons.mkdir(parents=True, exist_ok=True)
    brand.mkdir(parents=True, exist_ok=True)
    (FRONTEND / "src" / "app" / "icon.svg").write_text(svg(96), encoding="utf-8")
    (icons / "icon-192.svg").write_text(svg(192), encoding="utf-8")
    (icons / "icon-512.svg").write_text(svg(512), encoding="utf-8")
    (brand / "latexy-mark.svg").write_text(mark_svg(NAVY), encoding="utf-8")
    (brand / "latexy-mark-reversed.svg").write_text(mark_svg(PAPER), encoding="utf-8")
    raster(192).save(icons / "icon-192.png", optimize=True)
    raster(512).save(icons / "icon-512.png", optimize=True)
    raster(512, maskable=True).save(icons / "icon-512-maskable.png", optimize=True)
    raster(180).save(icons / "apple-touch-icon.png", optimize=True)
    favicon = raster(64)
    favicon.save(FRONTEND / "public" / "favicon.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])


if __name__ == "__main__":
    main()
