"""
scripts/generate_store_heroes.py — Iter 95c

Generates the hero images used behind the phone frames in the App Store /
Play Store screenshots. Uses Gemini Nano Banana (gemini-3.1-flash-image-preview)
via the Emergent LLM Key. All output is written to /app/store_assets/heroes/.

Cast direction:
  * A male pilot (Louis-like: mid-30s, brown hair, athletic build).
  * A female cabin crew, diverse (South Asian / Filipino heritage, mid-20s,
    athletic build, natural dark hair pulled back).
  * Both dressed in black CrewFit tees (small white "CREWFIT" wordmark on
    the chest) + red running shoes. No aviation uniform — this is training kit.

Scene direction:
  Aviation-adjacent premium coaching aesthetic. Muted natural light, no cheesy
  gym cliché, no logos other than CrewFit.
"""
from __future__ import annotations

import asyncio
import base64
import os
import sys
from pathlib import Path
from typing import Iterable

sys.path.insert(0, "/app/backend")

from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

from emergentintegrations.llm.chat import LlmChat, UserMessage  # noqa: E402

EMERGENT_LLM_KEY = os.environ["EMERGENT_LLM_KEY"]
MODEL_ID = "gemini-3.1-flash-image-preview"

OUT_DIR = Path("/app/store_assets/heroes")
OUT_DIR.mkdir(parents=True, exist_ok=True)

BRAND = (
    "Wardrobe (BOTH): plain black athletic short-sleeve t-shirt with a small "
    "white 'CREWFIT' wordmark centred on the chest (approx 40mm wide), "
    "matching black joggers or leggings, and BRIGHT RED trainers/running shoes. "
    "No visible aviation uniform, no airline logos, no watches or phones on show. "
    "No text or logos anywhere in the image except the small white 'CREWFIT' "
    "wordmark on the chest."
)

STYLE = (
    "Style: high-end fitness editorial photography, cinematic, natural warm "
    "morning light with soft shadows, shot on a full-frame camera at 50mm, "
    "shallow depth of field, no motion blur, ultra-sharp. Warm neutral colour "
    "grade with a subtle red accent from the shoes. 4:5 vertical portrait crop, "
    "leaving clean empty space at the top for a marketing headline."
)

CAST_PILOT = (
    "Subject A — the male pilot: mid-30s, athletic build, brown short hair, "
    "clean trimmed light stubble, warm confident expression, tanned but pale-white skin."
)

CAST_CREW = (
    "Subject B — the female cabin crew: mid-20s, mixed South Asian / Filipino "
    "heritage with warm brown skin, athletic build, natural dark hair pulled "
    "back into a low ponytail, calm focused expression, no visible makeup beyond a subtle look."
)


SCENES = [
    # 1 — Pilot in hangar mobility warm-up
    (
        "hero_pilot_hangar",
        (
            f"{CAST_PILOT} He is standing in an empty aircraft hangar at dawn, "
            "performing a controlled thoracic-rotation mobility warm-up (arms "
            "extended horizontally, torso rotated to one side). A large commercial "
            "airliner is softly visible in the background, out of focus. The floor "
            "is polished concrete, catching a warm morning glow from the open "
            "hangar door. He looks composed and ready, not straining. "
            f"{BRAND} {STYLE}"
        ),
    ),
    # 2 — Cabin crew hotel-room bodyweight
    (
        "hero_crew_hotel",
        (
            f"{CAST_CREW} She is in a modern minimalist hotel room, performing a "
            "controlled bodyweight squat with perfect form, arms extended forward "
            "for balance. Behind her a floor-to-ceiling window overlooks a runway "
            "at sunrise with an aircraft taxiing (softly out of focus). The bed is "
            "neatly made in white linen. She is focused and strong, not smiling. "
            f"{BRAND} {STYLE}"
        ),
    ),
    # 3 — Cabin crew doing calf raises in the airport concourse (short-haul feel)
    (
        "hero_crew_concourse",
        (
            f"{CAST_CREW} She is by a large airport concourse window with jet "
            "bridges visible outside, doing calf raises on the balls of her feet. "
            "Soft empty airport in the background (no passengers), warm sunrise "
            "light spilling through the glass. She looks quietly determined. "
            f"{BRAND} {STYLE}"
        ),
    ),
    # 4 — Pilot dumbbell row in a boutique hotel gym
    (
        "hero_pilot_gym",
        (
            f"{CAST_PILOT} He is in a small premium hotel gym, performing a "
            "single-arm dumbbell row with a moderate weight, back flat, elbow "
            "tight to his ribs. The gym has warm wood floors, a black-painted "
            "wall, and a single strip of ambient lighting. He looks composed, "
            "not straining. "
            f"{BRAND} {STYLE}"
        ),
    ),
    # 5 — Both together, side by side, looking down at a phone / training plan
    (
        "hero_duo_planning",
        (
            f"{CAST_PILOT} {CAST_CREW} They are standing side by side in a "
            "minimal, warmly-lit coach studio (dark grey walls, wood floor), "
            "shoulder-to-shoulder, looking together at a phone held by the crew "
            "member. Both are calm and focused. Show them from roughly the "
            "waist up. The pilot slightly taller, the cabin crew standing "
            "confidently beside him. Do not show the phone screen content — "
            "keep the phone angle so the screen is not readable. "
            f"{BRAND} {STYLE}"
        ),
    ),
    # 6 — Nutrition scene — cabin crew building a high-protein meal
    (
        "hero_nutrition_crew",
        (
            f"{CAST_CREW} She is at a clean white marble kitchen counter in a "
            "sunlit apartment, assembling a high-protein lunch bowl (grilled "
            "chicken, brown rice, roasted vegetables, sliced avocado). One hand "
            "steadies the glass bowl, the other places a lemon wedge. Warm "
            "natural light streams from a window on the left. She looks calm "
            "and present. "
            f"{BRAND} {STYLE}"
        ),
    ),
]


async def _generate(scene_key: str, prompt: str) -> Path:
    out_path = OUT_DIR / f"{scene_key}.png"
    if out_path.exists():
        print(f"  ↳ skip (exists): {out_path}")
        return out_path
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"crewfit-hero-{scene_key}",
        system_message=(
            "You are the CrewFit brand photographer — an award-winning editorial "
            "fitness photographer who shoots elite performance athletes. Produce a "
            "single photorealistic image. Never include text, watermarks, logos or "
            "letters other than the small 'CREWFIT' wordmark on the chest as "
            "described."
        ),
    )
    chat.with_model("gemini", MODEL_ID).with_params(modalities=["image", "text"])
    text, images = await chat.send_message_multimodal_response(UserMessage(text=prompt))
    if not images:
        raise RuntimeError(f"no image returned for {scene_key}: {text!r}")
    data = images[0].get("data") if isinstance(images[0], dict) else None
    if not data:
        raise RuntimeError(f"empty image data for {scene_key}")
    out_path.write_bytes(base64.b64decode(data))
    print(f"  ✓ wrote {out_path} ({out_path.stat().st_size // 1024} KB)")
    return out_path


async def _main(scene_keys: Iterable[str] | None = None) -> None:
    print(f"Generating heroes into {OUT_DIR}")
    for key, prompt in SCENES:
        if scene_keys and key not in scene_keys:
            continue
        print(f"→ {key}")
        try:
            await _generate(key, prompt)
        except Exception as e:
            print(f"  ✗ FAILED {key}: {e}")


if __name__ == "__main__":
    only = set(sys.argv[1:]) or None
    asyncio.run(_main(only))
