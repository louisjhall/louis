"""
scripts/build_wix_mockups.py — Iter 95i

Produces clean iPhone-style phone mockups for the CrewFit Wix landing page.
Each output is a transparent-background PNG with a rounded-corner device
frame, subtle stroke and soft drop shadow — safe to drop on any Wix
section (light or dark).

Output: /app/store_assets/wix_mockups/*.png at 900×1950 (retina-friendly).
"""
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

SRC = Path("/app/store_assets/screens")
OUT = Path("/app/store_assets/wix_mockups")
OUT.mkdir(parents=True, exist_ok=True)

# Final canvas per mockup (with padding for the shadow).
CANVAS_W, CANVAS_H = 900, 1950
DEVICE_W = 760                          # phone body width
DEVICE_CORNER = 76
STROKE = 8
BEZEL = (18, 20, 22, 255)
STROKE_COLOR = (60, 62, 66, 255)
SHADOW_RADIUS = 40
SHADOW_ALPHA = 190

FEATURES = [
    ("01_home_briefing.png",     "screen_01_home.jpeg"),
    ("02_roster_upload.png",     "screen_06_roster.jpeg"),
    ("03_guided_workout.png",    "screen_02b_guided.jpeg"),
    ("04_nutrition.png",         "screen_04_nutrition.jpeg"),
    ("05_progress.png",          "screen_05_profile.jpeg"),
    ("06_messages_louis.png",    "screen_07_messages.jpeg"),
    ("07_calendar.png",          "screen_03_calendar.jpeg"),
    ("08_workout_detail.png",    "screen_02_workout.jpeg"),
]


def build_mockup(shot_path: Path, out_path: Path) -> None:
    shot = Image.open(shot_path).convert("RGB")
    sw, sh = shot.size
    aspect = sh / sw
    tw = DEVICE_W
    th = int(tw * aspect)
    shot = shot.resize((tw, th), Image.LANCZOS)

    canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    dx = (CANVAS_W - tw) // 2 - STROKE
    dy = (CANVAS_H - th) // 2 - STROKE

    # Drop shadow.
    shadow = Image.new("RGBA", (tw + STROKE * 2 + 80, th + STROKE * 2 + 80), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [40, 40, tw + STROKE * 2 + 40, th + STROKE * 2 + 40],
        radius=DEVICE_CORNER + STROKE, fill=(0, 0, 0, SHADOW_ALPHA),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=SHADOW_RADIUS))
    canvas.alpha_composite(shadow, (dx - 40, dy - 20))

    # Bezel.
    bezel = Image.new("RGBA", (tw + STROKE * 2, th + STROKE * 2), BEZEL)
    bm = Image.new("L", bezel.size, 0)
    ImageDraw.Draw(bm).rounded_rectangle(
        [0, 0, bezel.size[0], bezel.size[1]],
        radius=DEVICE_CORNER + STROKE, fill=255,
    )
    bezel.putalpha(bm)

    # Screen with rounded corners.
    mask = Image.new("L", (tw, th), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, tw, th], radius=DEVICE_CORNER, fill=255)
    screen_rgba = shot.convert("RGBA"); screen_rgba.putalpha(mask)
    bezel.paste(screen_rgba, (STROKE, STROKE), screen_rgba)

    # Stroke.
    ImageDraw.Draw(bezel).rounded_rectangle(
        [1, 1, bezel.size[0] - 2, bezel.size[1] - 2],
        radius=DEVICE_CORNER + STROKE, outline=STROKE_COLOR, width=2,
    )

    canvas.alpha_composite(bezel, (dx, dy))
    canvas.save(out_path, "PNG", optimize=True)
    print(f"✓ {out_path.name}  ({out_path.stat().st_size // 1024} KB)")


for out_name, src_name in FEATURES:
    src = SRC / src_name
    if not src.exists():
        print(f"  ↳ skip missing {src_name}")
        continue
    build_mockup(src, OUT / out_name)
