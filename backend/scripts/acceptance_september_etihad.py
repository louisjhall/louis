"""Iter200 acceptance — run the REAL September Etihad PDF through the
Gemini extraction path + universal normalizer + presenter, and print a
side-by-side 1-30 September classification report.

Run: python scripts/acceptance_september_etihad.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Make backend/ importable when run as a script.
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv
load_dotenv(BACKEND / ".env")

PDF = "/tmp/sep_etihad.pdf"


async def main():
    # 1) Extract via the SAME Gemini call used in production.
    from server import ROSTER_SYSTEM, call_gemini_file, parse_json_from_text
    print("Calling Gemini 2.5 Flash on the real September Etihad PDF...")
    raw = await call_gemini_file(
        ROSTER_SYSTEM,
        "Extract the complete roster shown. Return only JSON.",
        PDF,
        "application/pdf",
    )
    parsed = parse_json_from_text(raw) if raw else {}
    llm_days = parsed.get("days", []) if isinstance(parsed, dict) else []
    print(f"Gemini emitted {len(llm_days)} day rows.")

    # Save raw LLM output for repeatable testing.
    Path("/tmp/sep_llm_raw.json").write_text(json.dumps(llm_days, indent=2))
    print("Raw LLM output saved to /tmp/sep_llm_raw.json")

    # 2) OLD path: what the customer would have seen BEFORE Iter200.
    old_days = json.loads(json.dumps(llm_days))  # deep copy
    old_days.sort(key=lambda d: d.get("date") or "")

    # 3) NEW path: same rows through the universal normalizer.
    from parsers.roster_normalizer import normalize_roster
    new_res = normalize_roster(
        json.loads(json.dumps(llm_days)),   # normalizer is destructive — clone first
        home_base="AUH",
        month_range=("2026-09-01", "2026-09-30"),
    )
    new_days = {d["date"]: d for d in new_res["days"]}

    # 4) Print side-by-side 1-30 September.
    print("\n" + "=" * 100)
    print("SEPTEMBER 2026 ETIHAD — CLASSIFICATION COMPARISON")
    print("=" * 100)
    print(f"{'DATE':<12}{'OLD (raw LLM)':<28}{'NEW (normalizer)':<28}{'CUSTOMER LABEL':<40}")
    print("-" * 100)

    all_dates = sorted({d.get("date") for d in llm_days if d.get("date")})
    for iso in all_dates:
        old = next((d for d in old_days if d.get("date") == iso), {})
        new = new_days.get(iso, {})
        old_type = (old.get("day_type") or "-")[:26]
        new_type = (new.get("day_type") or "-")[:26]
        client = (new.get("client_label") or "-")[:38]
        # highlight if OLD said "Layover in None" style
        marker = ""
        if "layover" in old_type.lower() and not old.get("layover_city"):
            marker = "  ← would have shown 'Layover in None'"
        if not (iso >= "2026-09-01" and iso <= "2026-09-30"):
            marker += "  ← OUT-OF-MONTH (clipped)"
        # Show clipped separately
        if iso not in new_days:
            new_type = "(clipped)"
            client = "-"
        print(f"{iso:<12}{old_type:<28}{new_type:<28}{client:<40}{marker}")

    print("-" * 100)
    a = new_res["audit"]
    print(f"AUDIT: clipped={a['clipped_month_boundary']} deduped={a['deduped_dates']} "
          f"night_downgrades={a['downgraded_midnight_crossings']} "
          f"preserved_off={a['preserved_off_days']} "
          f"fixed_standby={a['fixed_standby_equipment']} "
          f"flagged={a['flagged_needs_review']} "
          f"fixed_layover_in_none={a['fixed_layover_in_none']}")
    print(f"Total OLD days: {len(all_dates)}  |  Total NEW days: {len(new_res['days'])}")
    print("=" * 100)


if __name__ == "__main__":
    asyncio.run(main())
