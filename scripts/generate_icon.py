"""Generate the default 轻录 icon (record-button style) at multiple resolutions.

Outputs:
- src/assets/icons/app.png   (256x256 PNG — used by Qt at runtime)
- src/assets/icons/app.ico   (multi-res ICO 16/32/48/64/128/256 — for exe + installer)

Re-run this any time you want to refresh the bundled icon. To use a custom
image instead, just drop your own app.ico + app.png into src/assets/icons/.
"""
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "src" / "assets" / "icons"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def draw_icon(size: int) -> Image.Image:
    """Single-canvas icon: rounded dark square with a red recording dot."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    pad = max(1, size // 32)
    corner_r = size // 5
    # Dark gradient background (top→bottom subtle)
    # Pillow has no native gradient — fake it by drawing horizontal stripes.
    bg_top = (40, 44, 60)
    bg_bot = (24, 26, 36)
    for y in range(pad, size - pad):
        t = (y - pad) / max(1, size - 2 * pad)
        r = int(bg_top[0] + (bg_bot[0] - bg_top[0]) * t)
        g = int(bg_top[1] + (bg_bot[1] - bg_top[1]) * t)
        b = int(bg_top[2] + (bg_bot[2] - bg_top[2]) * t)
        d.line([(pad, y), (size - pad, y)], fill=(r, g, b, 255))
    # Rounded mask
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((pad, pad, size - pad, size - pad), corner_r, fill=255)
    img.putalpha(mask)

    # Soft outer glow for the red dot
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    dot_r = int(size * 0.30)
    cx = cy = size // 2
    gd.ellipse((cx - dot_r - 6, cy - dot_r - 6, cx + dot_r + 6, cy + dot_r + 6),
               fill=(230, 57, 70, 110))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=max(1, size // 16)))
    img.alpha_composite(glow)

    # Red dot (record symbol)
    d2 = ImageDraw.Draw(img)
    d2.ellipse((cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r),
               fill=(230, 57, 70, 255))
    # Highlight on top-left for glossy feel
    hi_r = int(dot_r * 0.45)
    d2.ellipse((cx - dot_r // 2 - hi_r // 2, cy - dot_r // 2 - hi_r // 2,
                cx - dot_r // 2 + hi_r, cy - dot_r // 2 + hi_r),
               fill=(255, 180, 185, 110))

    return img


def main() -> int:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    layers = {sz: draw_icon(sz) for sz in sizes}

    png_path = OUT_DIR / "app.png"
    layers[256].save(png_path, format="PNG")

    ico_path = OUT_DIR / "app.ico"
    layers[256].save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=[layers[s] for s in sizes if s != 256],
    )

    print(f"Wrote {png_path}  ({png_path.stat().st_size} bytes)")
    print(f"Wrote {ico_path}  ({ico_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
