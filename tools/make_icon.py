"""Generate assets/mdec.ico — the app icon.

The mark is the app's own signature: a docket ledger with a stamp-red notch on
the sequence spine, which is exactly what the Docket tab draws for a new filing.
It stays legible at 16px, where a letterform would turn to mush.

    python tools/make_icon.py

Needs Pillow (already a dependency via pdfplumber).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

# Same palette as the UI (mdec/server/static/app.css).
SLATE = (27, 34, 51, 255)        # --ink, the card
PAPER = (233, 236, 241, 255)     # --paper, the ledger rows
RAIL = (90, 107, 140, 255)       # --rail, secondary rows
STAMP = (168, 50, 74, 255)       # --stamp, the notch
STAMP_LIGHT = (225, 96, 122, 255)

SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def draw_icon(px: int) -> Image.Image:
    """Render at 8x then downsample — cheap supersampling, clean edges."""
    s = px * 8
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Rounded slate card, with a small margin so it doesn't touch the edges.
    m = round(s * 0.055)
    d.rounded_rectangle([m, m, s - m, s - m], radius=round(s * 0.16), fill=SLATE)

    # The spine notch: a red bar down the left, the ledger's defining edge.
    notch_x0 = round(s * 0.165)
    notch_w = round(s * 0.085)
    d.rounded_rectangle(
        [notch_x0, round(s * 0.235), notch_x0 + notch_w, round(s * 0.765)],
        radius=round(notch_w * 0.4),
        fill=STAMP if px >= 32 else STAMP_LIGHT,   # brighter when tiny
    )

    # Ledger rows. Fewer, thicker rows at small sizes so they stay separable.
    rows = 4 if px >= 32 else 3
    row_x0 = notch_x0 + notch_w + round(s * 0.075)
    row_x1 = s - round(s * 0.175)
    top, bottom = s * 0.265, s * 0.735
    gap = (bottom - top) / (rows - 1)
    thick = round(s * (0.062 if px >= 32 else 0.085))

    for i in range(rows):
        y = round(top + i * gap)
        # The top row is the newest filing — full width and bright, like the
        # stamped entry it represents. The rest recede.
        if i == 0:
            x1, fill = row_x1, PAPER
        else:
            x1 = round(row_x1 - (row_x1 - row_x0) * (0.16 * i))
            fill = RAIL if i > 1 else PAPER
        d.rounded_rectangle([row_x0, y, x1, y + thick],
                            radius=round(thick * 0.45), fill=fill)

    return img.resize((px, px), Image.LANCZOS)


def main() -> int:
    out_dir = Path(__file__).resolve().parent.parent / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = [draw_icon(px) for px in SIZES]
    ico = out_dir / "mdec.ico"
    frames[-1].save(ico, format="ICO",
                    sizes=[(px, px) for px in SIZES])
    frames[-1].save(out_dir / "mdec-256.png", format="PNG")
    print(f"wrote {ico} ({', '.join(str(p) for p in SIZES)} px)")
    print(f"wrote {out_dir / 'mdec-256.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
