"""Generate the DiffAnyDoc app icon.

Run from the repository root:

    .venv/bin/python tools/make_icon.py

The icon is a single document between back/forward arrows, with a two-tone
diff line: comparison is the product, not decoration.  SVG is the source of
truth for the UI; PNG/ICO are rasterised here for the native window and for
the Windows build.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 512
SCALE = 4
BLUE = "#3584e4"
WHITE = "#ffffff"
FOLD = "#cfe1fb"
NEUTRAL = "#9fb3c8"
REMOVED = "#e01b24"
ADDED = "#2ec27e"

OUT = Path(__file__).resolve().parents[1] / "src" / "diffanydoc" / "web" / "static"

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="112" fill="#3584e4"/>
  <g fill="none" stroke="#ffffff" stroke-width="24" stroke-linecap="round" stroke-linejoin="round">
    <path d="M140 256H64m0 0 38-36m-38 36 38 36"/>
    <path d="M372 256h76m0 0-38-36m38 36-38 36"/>
  </g>
  <rect x="166" y="104" width="180" height="304" rx="20" fill="#ffffff"/>
  <path d="M298 104h28a20 20 0 0 1 20 20v28h-48z" fill="#cfe1fb"/>
  <rect x="198" y="186" width="116" height="14" rx="7" fill="#9fb3c8"/>
  <rect x="198" y="232" width="52" height="14" rx="7" fill="#e01b24"/>
  <rect x="262" y="232" width="52" height="14" rx="7" fill="#2ec27e"/>
  <rect x="198" y="278" width="116" height="14" rx="7" fill="#9fb3c8"/>
</svg>
"""


def _s(value: float) -> int:
    return round(value * SCALE)


def _line(draw: ImageDraw.ImageDraw, points: list[tuple[float, float]], fill: str) -> None:
    width = _s(24)
    scaled = [(_s(x), _s(y)) for x, y in points]
    draw.line(scaled, fill=fill, width=width, joint="curve")
    radius = width // 2
    for x, y in scaled:
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)


def _bar(draw: ImageDraw.ImageDraw, x: float, y: float, w: float, fill: str) -> None:
    draw.rounded_rectangle(
        (_s(x), _s(y), _s(x + w), _s(y + 14)),
        radius=_s(7),
        fill=fill,
    )


def render() -> Image.Image:
    image = Image.new("RGBA", (SIZE * SCALE, SIZE * SCALE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle(
        (0, 0, SIZE * SCALE - 1, SIZE * SCALE - 1), radius=_s(112), fill=BLUE
    )

    # Back / forward arrows.
    _line(draw, [(140, 256), (64, 256)], WHITE)
    _line(draw, [(102, 220), (64, 256), (102, 292)], WHITE)
    _line(draw, [(372, 256), (448, 256)], WHITE)
    _line(draw, [(410, 220), (448, 256), (410, 292)], WHITE)

    # Document and folded corner.
    draw.rounded_rectangle(
        (_s(166), _s(104), _s(346), _s(408)),
        radius=_s(20),
        fill=WHITE,
    )
    draw.polygon(
        [(_s(298), _s(104)), (_s(346), _s(104)), (_s(346), _s(152))],
        fill=FOLD,
    )

    # Text lines; the middle one is split red/green to read as a diff.
    _bar(draw, 198, 186, 116, NEUTRAL)
    _bar(draw, 198, 232, 52, REMOVED)
    _bar(draw, 262, 232, 52, ADDED)
    _bar(draw, 198, 278, 116, NEUTRAL)

    return image.resize((SIZE, SIZE), Image.Resampling.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    icon = render()
    icon.save(OUT / "icon.png")
    icon.resize((32, 32), Image.Resampling.LANCZOS).save(OUT / "icon-32.png")
    icon.save(
        OUT / "icon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    (OUT / "icon.svg").write_text(SVG, encoding="utf-8")
    print(f"wrote {OUT / 'icon.svg'}, icon.png, icon-32.png and icon.ico")


if __name__ == "__main__":
    main()
