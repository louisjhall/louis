"""
scripts/build_play_tablet_10.py

Regenerates the 10-inch tablet screenshots for Google Play at portrait
9:16 = 4320 x 7680, the maximum dimension Play Console accepts.

Sources the pre-composed iOS 1290x2796 screenshots from /app/store_assets/final
and letterboxes them onto a branded 4320x7680 tablet canvas so the phone
mockup is huge (~2.7x scale) and the file is clearly a tablet asset.

Output: /app/store_assets/play_tablet_10/*.jpg (JPEG, 24-bit, no alpha)
"""
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path("/app/store_assets")
SRC = ROOT / "final"          # 1290x2796 iOS-ready hero comps
OUT = ROOT / "play_tablet_10"
OUT.mkdir(parents=True, exist_ok=True)

# Portrait 9:16 max Play Console tablet dimensions
TW, TH = 4320, 7680

BG_DARK = (10, 10, 12)
BRAND_RED = (215, 42, 62)
INK_DIM = (170, 174, 180)

FONT_BODY = "/app/frontend/assets/fonts/SourceSans3-SemiBold.ttf"


def make_bg(w: int, h: int) -> Image.Image:
    """Dark canvas with a subtle brand-red radial glow so side pillars don't look flat."""
    bg = Image.new("RGB", (w, h), BG_DARK)
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    cx, cy = w // 2, int(h * 0.55)
    max_r = int(max(w, h) * 0.9)
    for r in range(max_r, 0, -60):
        t = r / max_r
        a = int(60 * (1 - t))
        col = (BRAND_RED[0], BRAND_RED[1], BRAND_RED[2], a)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=180))
    bg_rgba = bg.convert("RGBA")
    bg_rgba.alpha_composite(overlay)
    return bg_rgba.convert("RGB")


def compose_tablet(src_path: Path, out_path: Path) -> None:
    src = Image.open(src_path).convert("RGB")
    sw, sh = src.size

    # Fit by height so the iOS composition dominates the tablet canvas.
    scale = TH / sh
    new_w = int(sw * scale)
    new_h = TH
    scaled = src.resize((new_w, new_h), Image.LANCZOS)

    canvas = make_bg(TW, TH)

    # Center horizontally.
    off_x = (TW - new_w) // 2
    canvas.paste(scaled, (off_x, 0))

    # (Source PNG already contains the CrewFit footer — no need to add another.)

    # Save as 24-bit JPEG, no alpha (Play Console requirement).
    canvas.convert("RGB").save(out_path, "JPEG", quality=92, optimize=True, progressive=False)
    kb = out_path.stat().st_size // 1024
    print(f"✓ {out_path.name}  {canvas.size}  {kb} KB")


PLAN = [
    ("01_home_briefing.png",   "01_01_home_briefing.jpg"),
    ("03_roster_upload.png",   "02_03_roster_upload.jpg"),
    ("02_guided_workout.png",  "03_02_guided_workout.jpg"),
    ("04_nutrition.png",       "04_04_nutrition.jpg"),
    ("05_real_coach.png",      "05_05_real_coach.jpg"),
    ("06_crew_hotel.png",      "06_06_crew_hotel.jpg"),
]


def build_all() -> None:
    for src_name, out_name in PLAN:
        compose_tablet(SRC / src_name, OUT / out_name)


if __name__ == "__main__":
    build_all()
