"""
scripts/build_store_screens.py — Iter 95c

Composites the 6 App Store screenshots from the hero images (nano-banana)
and the real app screenshots.

Layout (per screen):

    ┌─────────────────────────────────┐
    │  [ CREWFIT · TESTFLIGHT BETA ]  │  ← small eyebrow (red)
    │                                 │
    │        HEADLINE TAGLINE         │  ← Creo ExtraBold, 88pt
    │        Second line supporting   │  ← Source Sans 3, 40pt
    │                                 │
    │  ┌─────────────────────────┐    │
    │  │                         │    │
    │  │   HERO IMAGE (56% ht)   │    │
    │  │                         │    │
    │  │     ┌───────────┐       │    │
    │  │     │  DEVICE   │       │    │  ← phone frame with real screen
    │  │     │  FRAME +  │       │    │
    │  │     │  SCREEN   │       │    │
    │  │     └───────────┘       │    │
    │  └─────────────────────────┘    │
    │                                 │
    └─────────────────────────────────┘

Output: 1290×2796 (6.7" iPhone) — Apple's declared 6.7" pixel size that
also satisfies the 6.9" iPhone requirement.
"""
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT   = Path("/app/store_assets")
HEROES = ROOT / "heroes"
SCREENS = ROOT / "screens"
OUT    = ROOT / "final"
OUT.mkdir(parents=True, exist_ok=True)
OUT_PLAY = ROOT / "final_play"
OUT_PLAY.mkdir(parents=True, exist_ok=True)

W, H = 1290, 2796
PLAY_W, PLAY_H = 1080, 1920

# Brand palette (from theme.ts).
BG_DARK     = (12, 12, 14)        # near-black
INK         = (245, 245, 247)
INK_DIM     = (170, 174, 180)
BRAND_RED   = (215, 42, 62)       # theme.color.brand approx
ACCENT_RED  = (255, 90, 100)

FONT_DISPLAY = "/app/frontend/assets/fonts/CreoExtraBold.ttf"
FONT_HEADING = "/app/frontend/assets/fonts/SourceSans3-Bold.ttf"
FONT_BODY    = "/app/frontend/assets/fonts/SourceSans3-SemiBold.ttf"
FONT_LIGHT   = "/app/frontend/assets/fonts/SourceSans3-Regular.ttf"

def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


# --- device frame ---------------------------------------------------------

DEVICE_CORNER_R = 96
DEVICE_STROKE   = 10
DEVICE_BEZEL    = (18, 20, 22)
DEVICE_STROKE_C = (60, 62, 66)

def make_device_shot(screen_path: Path, target_w: int) -> Image.Image:
    """Wrap the raw app screenshot in a subtle rounded-rect device frame."""
    shot = Image.open(screen_path).convert("RGB")
    sw, sh = shot.size
    aspect = sh / sw
    tw = target_w
    th = int(tw * aspect)
    shot = shot.resize((tw, th), Image.LANCZOS)

    # Rounded-rect mask.
    mask = Image.new("L", (tw, th), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, tw, th], radius=DEVICE_CORNER_R, fill=255)

    # Bezel canvas (slightly larger to draw stroke).
    pad = DEVICE_STROKE
    dev = Image.new("RGBA", (tw + pad * 2, th + pad * 2), DEVICE_BEZEL + (255,))
    dev_mask = Image.new("L", dev.size, 0)
    ImageDraw.Draw(dev_mask).rounded_rectangle(
        [0, 0, dev.size[0], dev.size[1]],
        radius=DEVICE_CORNER_R + pad, fill=255,
    )
    dev.putalpha(dev_mask)

    # Paste the screen with rounded corners.
    shot_rgba = shot.convert("RGBA"); shot_rgba.putalpha(mask)
    dev.paste(shot_rgba, (pad, pad), shot_rgba)

    # Add a subtle stroke.
    draw = ImageDraw.Draw(dev)
    draw.rounded_rectangle(
        [1, 1, dev.size[0] - 2, dev.size[1] - 2],
        radius=DEVICE_CORNER_R + pad, outline=DEVICE_STROKE_C, width=2,
    )
    return dev


def make_hero_bg(hero_path: Path, canvas_w: int, canvas_h: int, dark_amount: float = 0.55) -> Image.Image:
    """Cover-crop the hero image and darken it so headline text is legible."""
    hero = Image.open(hero_path).convert("RGB")
    hw, hh = hero.size

    src_aspect = hw / hh
    dst_aspect = canvas_w / canvas_h
    if src_aspect > dst_aspect:
        # crop width
        new_w = int(hh * dst_aspect); off = (hw - new_w) // 2
        hero = hero.crop((off, 0, off + new_w, hh))
    else:
        new_h = int(hw / dst_aspect); off = (hh - new_h) // 2
        hero = hero.crop((0, off, hw, off + new_h))
    hero = hero.resize((canvas_w, canvas_h), Image.LANCZOS)

    # Vertical gradient darken (darker at top for the headline).
    overlay = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for y in range(canvas_h):
        t = y / canvas_h
        # Stronger at top (0.75) → lighter at bottom (0.25)
        a = int(255 * (0.75 - 0.50 * t) * dark_amount + 255 * 0.25)
        a = max(0, min(255, a))
        draw.rectangle([0, y, canvas_w, y + 1], fill=(0, 0, 0, a))
    hero_rgba = hero.convert("RGBA")
    hero_rgba.alpha_composite(overlay)
    return hero_rgba.convert("RGB")


def wrap_text(text: str, fnt: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = f"{cur} {w}".strip()
        bbox = fnt.getbbox(trial)
        if bbox[2] - bbox[0] <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines


def compose(
    idx: int,
    key: str,
    hero_key: str,
    screen_key: str,
    eyebrow: str,
    headline: str,
    subhead: str,
    hero_dark: float = 0.55,
) -> Path:
    canvas = Image.new("RGB", (W, H), BG_DARK)

    # Hero background covers the whole canvas.
    hero_bg = make_hero_bg(HEROES / f"{hero_key}.png", W, H, dark_amount=hero_dark)
    canvas.paste(hero_bg, (0, 0))

    draw = ImageDraw.Draw(canvas)

    # --- Eyebrow (small red uppercase) ---
    fnt_eyebrow = font(FONT_HEADING, 34)
    ew, eh = draw.textbbox((0, 0), eyebrow, font=fnt_eyebrow)[2:]
    draw.text(
        ((W - ew) // 2, 150),
        eyebrow,
        fill=BRAND_RED,
        font=fnt_eyebrow,
    )
    # underline dash
    dash_y = 150 + eh + 20
    draw.rounded_rectangle(
        [(W // 2 - 40, dash_y), (W // 2 + 40, dash_y + 6)],
        radius=3, fill=BRAND_RED,
    )

    # --- Headline (big Creo bold) ---
    fnt_head = font(FONT_DISPLAY, 118)
    fnt_sub  = font(FONT_LIGHT, 42)

    head_lines = wrap_text(headline, fnt_head, W - 160)
    y = 260
    for line in head_lines:
        bbox = draw.textbbox((0, 0), line, font=fnt_head)
        tw = bbox[2] - bbox[0]; th = bbox[3] - bbox[1]
        # Soft shadow for legibility
        draw.text(((W - tw) // 2 + 3, y + 3), line, fill=(0, 0, 0), font=fnt_head)
        draw.text(((W - tw) // 2, y), line, fill=INK, font=fnt_head)
        y += th + 18

    # Subhead
    if subhead:
        y += 10
        sub_lines = wrap_text(subhead, fnt_sub, W - 240)
        for line in sub_lines:
            bbox = draw.textbbox((0, 0), line, font=fnt_sub)
            tw = bbox[2] - bbox[0]; th = bbox[3] - bbox[1]
            draw.text(((W - tw) // 2, y), line, fill=INK_DIM, font=fnt_sub)
            y += th + 12

    # --- Device with app screenshot ---
    dev = make_device_shot(SCREENS / f"{screen_key}.jpeg", target_w=int(W * 0.62))
    dw, dh = dev.size

    # Position — bottom-centered with margin.
    dx = (W - dw) // 2
    dy = H - dh - 120

    # Drop shadow.
    shadow = Image.new("RGBA", (dw + 80, dh + 80), (0, 0, 0, 0))
    sh_draw = ImageDraw.Draw(shadow)
    sh_draw.rounded_rectangle(
        [40, 60, dw + 40, dh + 60],
        radius=DEVICE_CORNER_R + DEVICE_STROKE, fill=(0, 0, 0, 200),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=32))
    canvas.paste(shadow, (dx - 40, dy - 20), shadow)

    canvas.paste(dev, (dx, dy), dev)

    # --- Bottom brand strip ---
    strip_y = H - 60
    fnt_foot = font(FONT_BODY, 28)
    foot = "CrewFit  ·  Coaching for aviation crew"
    fb = draw.textbbox((0, 0), foot, font=fnt_foot)
    fw = fb[2] - fb[0]
    draw.text(((W - fw) // 2, strip_y - 20), foot, fill=INK_DIM, font=fnt_foot)

    out_path = OUT / f"{idx:02d}_{key}.png"
    canvas.save(out_path, "PNG", optimize=True)
    print(f"✓ {out_path.name}  ({out_path.stat().st_size // 1024} KB)")
    return out_path


SCREENS_PLAN = [
    dict(idx=1, key="home_briefing", hero_key="hero_pilot_hangar",
         screen_key="screen_01_home",
         eyebrow="CREWFIT",
         headline="Coaching that flies with you.",
         subhead="Personal training built around your roster, layovers and body clock."),

    dict(idx=2, key="guided_workout", hero_key="hero_pilot_gym",
         screen_key="screen_02b_guided",
         eyebrow="GUIDED WORKOUTS",
         headline="Never train alone in a hotel again.",
         subhead="Timer, breathing cues and demo videos in every session."),

    dict(idx=3, key="calendar", hero_key="hero_crew_concourse",
         screen_key="screen_03_calendar",
         eyebrow="ROSTER-AWARE",
         headline="Never train on the wrong day.",
         subhead="Your calendar reads your roster — training moves with you."),

    dict(idx=4, key="nutrition", hero_key="hero_nutrition_crew",
         screen_key="screen_04_nutrition",
         eyebrow="NUTRITION",
         headline="Fuel across every timezone.",
         subhead="Protein, hydration and hotel-friendly meals — logged in seconds."),

    dict(idx=5, key="weekly_review", hero_key="hero_duo_planning",
         screen_key="screen_01_home",
         eyebrow="A REAL COACH",
         headline="A weekly review from Louis.",
         subhead="Every Sunday — training, nutrition and habits, side by side."),

    dict(idx=6, key="crew_hotel", hero_key="hero_crew_hotel",
         screen_key="screen_02_workout",
         eyebrow="BUILT FOR CREW",
         headline="Hotel room. 20 minutes. Done.",
         subhead="Bodyweight-safe fallbacks for the days the gym isn't an option."),
]


def build_all() -> None:
    for spec in SCREENS_PLAN:
        ios_path = compose(**spec)
        # Google Play 9:16 variant: fit-height crop the middle of the wider iOS canvas.
        ios_img = Image.open(ios_path).convert("RGB")
        iw, ih = ios_img.size
        target_w = int(ih * PLAY_W / PLAY_H)
        if target_w > iw:
            # Fall back to width-fit (shouldn't happen with our aspects, but safe).
            target_h = int(iw * PLAY_H / PLAY_W)
            off = (ih - target_h) // 2
            crop = ios_img.crop((0, off, iw, off + target_h))
        else:
            off = (iw - target_w) // 2
            crop = ios_img.crop((off, 0, off + target_w, ih))
        play = crop.resize((PLAY_W, PLAY_H), Image.LANCZOS)
        play_path = OUT_PLAY / ios_path.name
        play.save(play_path, "PNG", optimize=True)
        print(f"    ↳ play {play_path.name}")


if __name__ == "__main__":
    build_all()
