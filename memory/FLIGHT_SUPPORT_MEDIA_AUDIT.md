# CrewFit — Flight Support Media Audit  ·  Iter 128j
_Read-only. Audits Aviation Support / Flight Support movement identity, alternatives, and media coverage._

## 1. How Flight Support is produced

- **Deterministic selector** in `feature_aviation_support.select_interventions_for_day()`. Runs on every read; no writes.
- Selector picks 1–2 protocols per day based on the roster classification + client persona (pilot / cabin_crew) + trip context (pre-flight / post-flight / layover / turnaround / arrival).
- **Protocol library** = `PROTOCOLS: dict[str, ProtocolSpec]` in `feature_aviation_support.py` (lines 88+). Registered in Python at import time.
- Result → surfaced by `_flight_support_for_range()` (`feature_aviation_support_api.py`) into the workspace / calendar / client cards.

## 2. Protocol → movement schema

```python
@dataclass
class ProtocolSpec:
    key: str                        # stable id, e.g. "pilot_pre_flight_mobility_6"
    display_title: str
    family: str                     # walk | mobility | activation | recovery | reset | movement_break
    intensity: str                  # very_low | low
    duration_min: int
    duration_range: tuple[int, int]
    role: str                       # pilot | cabin_crew
    cues: list[str]
    equipment: list[str]
    blocks: list[dict]              # ← MOVEMENTS live here
    restricted_regions: list[str]
    required_equipment: list[str]
    environment: str                # indoor | outdoor | any
```

Each block:

```python
{
  "name":         "Thoracic rotation",
  "duration_sec": 60,
  "cue":          "Half-kneel, hand behind head, rotate open"
}
```

**Block does NOT carry `exercise_id`.** All blocks are keyed only by their free-text `name`.

## 3. Coverage against canonical Library

Sampled 19 movement names from `feature_aviation_support.py`:

```
Thoracic rotation             Hip opener                Ankle mobility
Glute activation              Breathing reset           Air squats
Glute bridges                 Standing rows             Calf pumps
Nasal breathing               Slow walk in place        Hip flexor mobility
T-spine openers               Breathing decompress      Easy walk
Comfortable walk              Easy arrival walk         T-spine reach
Breathing
```

Regex match against `exercises_v2.exercise_name`:

- **5 / 19 matched** (26%)
- **14 / 19 orphan** — no canonical row exists to attach media to.

Unmatched names include: `Hip opener`, `Glute activation`, `Breathing reset`, `Standing rows`, `Calf pumps`, `Nasal breathing`, `Slow walk in place`, `Hip flexor mobility`, `T-spine openers`, `Breathing decompress`, `Easy walk`, `Comfortable walk`, `Easy arrival walk`, `T-spine reach`.

**⇒ 14 client-visible pilot movements have no canonical identity today.**

## 4. Frame media pipeline

- `feature_flight_support_media._resolve_frames_and_maybe_queue()` accepts a `key` (id **or** name).
- If passed a name it searches: `exercises` → `exercises_v2` → `exercise_content` collections (regex, case-insensitive).
- If it resolves, it reads `exercise_content_images` filtered by `exercise_id` + `status=ready`, groups by `(persona, slot)`, produces a persona-fallback frame array over slots `["start","mid","end"]` (ordered).
- If the preferred persona ("pilot") is missing any slot → upserts a `media_queue` row with `status: "needs_media"`.
- The 3-slot ordering IS the intended 3-stage cue (start / mid / end). Auto-swipe / avatar swap is a client concern; the backend just returns the array.

### Live media_queue snapshot

```
media_queue total = 4
Sample rows carry: exercise_id, exercise_name, status="needs_media",
                    preferred_persona="pilot"
```

Only 4 rows because only 4 of the resolved names ever hit the resolver via a client scan. The 14 unresolved names never populate the queue — they silently fall through name lookup and produce nothing.

## 5. Alternatives

**Flight Support has NO alternative mechanism today.**

- `blocks[]` is a fixed list per protocol.
- Coach cannot swap blocks; client cannot substitute (e.g., "can I do the seated version?").
- `flight_support_overrides` collection exists but is used to disable / customise a whole protocol, not to swap individual movements.

If we wanted seated / standing / aircraft-seat / hotel variants (as the brief suggests), they don't exist — those would need new canonical Library rows AND a new variant-selection surface.

## 6. Training + Flight Support shared movements

- Example overlap: `Thoracic rotation` in Aviation `pilot_pre_flight_mobility_6.blocks` AND in `exercises_v2` for a strength-mobility drill.
- Because the lookup is regex-name-based, when the training movement gets an image, the Flight Support frame also picks it up automatically — provided the coach used the same string.
- Media context is currently NOT context-aware: the same image would be used for both training and Flight Support. Whether that's correct depends on product intent — for `Thoracic rotation` it probably is; for `Easy walk` (very different production context) probably not.

## 7. Feasibility of media queue including Flight Support

The mechanism ALREADY writes to `media_queue`. What's incomplete:

1. The queue is only populated **when a client actually views a Flight Support card that resolves a name** (lazy). Static enumeration of "all pilot protocols the client will see over the next N days" is not implemented — so protocols scheduled but never opened do not enter the queue.
2. Only the 5/19 matched names ever queue. The 14 orphan names silently vanish.

### Fixing this requires

- Give every `blocks[].name` a corresponding canonical `exercises_v2` row (or a Flight-Support-scoped registry with pilot-persona images).
- Store `exercise_id` on each block instead of relying on regex-name match.
- Trigger a daily deterministic scan that walks upcoming Flight Support placements and calls `_resolve_frames_and_maybe_queue()` proactively.

## 8. Component classification

| Component | Class |
|-----------|-------|
| `feature_aviation_support.PROTOCOLS` | **KEEP** (protocol definitions) |
| `blocks[].name` free-text | **MIGRATE** to `exercise_id` |
| `feature_flight_support_media._resolve_frames_and_maybe_queue` | **KEEP + EXTEND** to run proactively |
| `flight_support_overrides` | **KEEP** |
| `media_queue` | **EXTEND** to also cover training exercises |
| Pilot-persona images (`demo_slots_pilot`) | **KEEP** |
| Flight-Support alternative mechanism | **DOES NOT EXIST** — decision needed on whether product needs it |

## 9. Complexity

- **Small**: register the 14 orphan movements as `exercises_v2` rows and back-fill `blocks[].exercise_id`.
- **Medium**: proactive scan job that enumerates upcoming Flight Support placements and queues incomplete media.
- **Large**: introducing per-movement alternatives (seated / standing / aircraft-seat variants) — this changes the protocol model AND the client card UI.
