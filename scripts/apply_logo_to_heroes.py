"""
scripts/apply_logo_to_heroes.py — Iter 95d

Uses Gemini Nano Banana image-editing (two-image input) to replace the
generic 'CREWFIT' text on each hero's chest with the ACTUAL CrewFit
winged logo (red wings + white CREWFIT wordmark) supplied as a reference.

Nano Banana handles fabric curvature, lighting and perspective naturally,
which manual PIL compositing cannot.

Input:
  - /app/store_assets/heroes/hero_*.png          (current heroes)
  - /app/store_assets/brand/crewfit_logo_transparent.png (reference)

Output:
  - /app/store_assets/heroes_v2/hero_*.png       (branded heroes)

We keep the originals untouched so we can iterate.
"""
from __future__ import annotations

import asyncio
import base64
import os
import sys
from pathlib import Path

sys.path.insert(0, "/app/backend")

from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent  # noqa: E402

EMERGENT_LLM_KEY = os.environ["EMERGENT_LLM_KEY"]
MODEL_ID = "gemini-3.1-flash-image-preview"

SRC_DIR   = Path("/app/store_assets/heroes")
OUT_DIR   = Path("/app/store_assets/heroes_v2")
OUT_DIR.mkdir(parents=True, exist_ok=True)

LOGO_PATH = Path("/app/store_assets/brand/crewfit_logo_transparent.png")

HERO_KEYS = [
    "hero_pilot_hangar",
    "hero_crew_hotel",
    "hero_crew_concourse",
    "hero_pilot_gym",
    "hero_duo_planning",
    "hero_nutrition_crew",
]

PROMPT = (
    "You are given TWO images. Image 1 is a photograph of an athlete (or two "
    "athletes) in a plain black training t-shirt. Image 2 is the CrewFit brand "
    "logo — red winged emblem with a white 'CREWFIT' wordmark below — on a "
    "transparent background. "
    "\n\n"
    "Task: Return Image 1 EDITED so that the CrewFit logo from Image 2 appears "
    "printed on the chest of the black t-shirt. The logo must:\n"
    "  • sit centred on the chest, roughly 40–55 mm wide (about the size of a "
    "     traditional brand chest print);\n"
    "  • follow the natural fabric curvature, lighting and shadow of the shirt;\n"
    "  • preserve the exact wing shape and 'CREWFIT' spelling from Image 2 — "
    "     the red wings above the white wordmark;\n"
    "  • look like a real high-quality screen-printed graphic (not a floating "
    "     sticker, not glossy, no drop-shadow, not scaled larger than a real "
    "     chest print);\n"
    "  • replace any existing generic 'CREWFIT' text on the shirt.\n"
    "\n"
    "If there are TWO athletes visible in Image 1, apply the logo to BOTH chests "
    "at the same natural size, matching each shirt's own lighting and pose.\n"
    "\n"
    "Do NOT change the subject's face, hair, skin tone, pose, background, "
    "lighting, colour grading or the red shoes. Do NOT add any other text or "
    "logos anywhere in the image. Return one image."
)


async def _edit(key: str) -> Path:
    src_path = SRC_DIR / f"{key}.png"
    out_path = OUT_DIR / f"{key}.png"
    if out_path.exists():
        print(f"  ↳ skip (already exists): {out_path.name}")
        return out_path

    with open(src_path, "rb") as f:
        hero_b64 = base64.b64encode(f.read()).decode("ascii")
    with open(LOGO_PATH, "rb") as f:
        logo_b64 = base64.b64encode(f.read()).decode("ascii")

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"crewfit-brand-{key}",
        system_message=(
            "You are a professional retoucher. When editing photos, you preserve "
            "the subject's identity, pose and lighting perfectly, and only change "
            "what the user asks for. Output exactly one image."
        ),
    )
    chat.with_model("gemini", MODEL_ID).with_params(modalities=["image", "text"])

    msg = UserMessage(
        text=PROMPT,
        file_contents=[
            ImageContent(image_base64=hero_b64),
            ImageContent(image_base64=logo_b64),
        ],
    )
    text, images = await chat.send_message_multimodal_response(msg)
    if not images:
        raise RuntimeError(f"no image returned for {key}: {text!r}")
    data = images[0].get("data") if isinstance(images[0], dict) else None
    if not data:
        raise RuntimeError(f"empty image data for {key}")
    out_path.write_bytes(base64.b64decode(data))
    print(f"  ✓ {out_path.name}  ({out_path.stat().st_size // 1024} KB)")
    return out_path


async def _main(keys):
    print(f"Editing heroes into {OUT_DIR}")
    for k in keys:
        print(f"→ {k}")
        try:
            await _edit(k)
        except Exception as e:
            print(f"  ✗ FAILED {k}: {e}")


if __name__ == "__main__":
    keys = sys.argv[1:] or HERO_KEYS
    asyncio.run(_main(keys))
