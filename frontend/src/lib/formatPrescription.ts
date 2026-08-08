/**
 * formatPrescription — Iter 163 · Gym Reliability
 *
 * Deterministic, LLM-free formatter for exercise prescriptions. Guarantees
 * a stable, human-readable string across Amber / Red scaling, Reality
 * mutations, and Traffic-Light variants — no upstream AI text can leak
 * through malformed and break the workout card layout.
 *
 * Schema:
 *   sets     — number of sets (default 1)
 *   volume   — the numeric value of one set (reps, seconds, minutes, km,
 *              metres, or a string like "10 each side")
 *   unit     — lowercase unit token: "reps" | "rep" | "sec" | "s"
 *              | "min" | "m" | "km" | "each side" | "each" | "hold"
 *              | "" (empty → treated as reps)
 *
 * Output examples:
 *   formatPrescription(1, 30, "min")         → "1 x 30 Minutes"
 *   formatPrescription(3, 12, "reps")        → "3 x 12 Reps"
 *   formatPrescription(4, 8,  "each side")   → "4 x 8 Each Side"
 *   formatPrescription(1, 45, "sec")         → "1 x 45 Seconds"
 *   formatPrescription(3, 5,  "km")          → "3 x 5 km"
 *
 * Legacy fallback: when only a raw `reps` string is passed via the
 * `raw` optional field, the helper still returns something sensible so
 * older workout docs don't regress.
 */

export type PrescriptionInput = {
  sets?: number | string | null;
  volume?: number | string | null;
  unit?: string | null;
  /** Legacy AI-generated string like "3 x 12" or "1 x 30 min". */
  raw?: string | null;
  /** Optional prescribed rest, in seconds. Not rendered here — kept for
   *  cards that want to append " · rest 60s" downstream. */
  rest_sec?: number | null;
};

const UNIT_LABELS: Record<string, (v: number | string) => string> = {
  reps: (v) => (Number(v) === 1 ? "Rep" : "Reps"),
  rep: (v) => (Number(v) === 1 ? "Rep" : "Reps"),
  sec: (v) => (Number(v) === 1 ? "Second" : "Seconds"),
  s: (v) => (Number(v) === 1 ? "Second" : "Seconds"),
  seconds: (v) => (Number(v) === 1 ? "Second" : "Seconds"),
  min: (v) => (Number(v) === 1 ? "Minute" : "Minutes"),
  minute: (v) => (Number(v) === 1 ? "Minute" : "Minutes"),
  minutes: (v) => (Number(v) === 1 ? "Minute" : "Minutes"),
  m: () => "m",
  metre: () => "m",
  metres: () => "m",
  meters: () => "m",
  km: () => "km",
  kilometre: () => "km",
  kilometres: () => "km",
  "each side": () => "Each Side",
  "per side": () => "Each Side",
  "each leg": () => "Each Leg",
  "each arm": () => "Each Arm",
  each: () => "Each",
  hold: () => "Hold",
  breath: () => "Breaths",
  breaths: () => "Breaths",
  round: () => "Rounds",
  rounds: () => "Rounds",
};

/** Attempt to parse a legacy prescription string like "3 x 12", "1 × 30 min",
 *  "45s hold", "5km run" into structured parts. Returns null on failure. */
export function parsePrescriptionRaw(raw?: string | null): {
  sets: number; volume: string; unit: string;
} | null {
  if (!raw) return null;
  const s = String(raw).trim().toLowerCase();
  if (!s) return null;

  // "3 x 12", "3×12", "3 * 12"
  const xMatch = s.match(/^\s*(\d+)\s*[x×*]\s*(\d+(?:\.\d+)?)\s*(.*)$/);
  if (xMatch) {
    const sets = Number(xMatch[1]);
    const volume = xMatch[2];
    const rest = xMatch[3].trim();
    // Normalize unit words in the trailing text
    const unit =
      rest.match(/^(sec(?:onds?)?|s\b)/) ? "sec" :
      rest.match(/^(min(?:utes?)?|m\b)/) && !rest.startsWith("mi") ? "min" :
      rest.match(/^(minutes?|min)/) ? "min" :
      rest.match(/^(reps?|repetitions?)/) ? "reps" :
      rest.match(/^(km|kilometres?|kilometers?)/) ? "km" :
      rest.match(/^(each side|per side)/) ? "each side" :
      rest.match(/^(each leg)/) ? "each leg" :
      rest.match(/^(each arm)/) ? "each arm" :
      rest.match(/^(hold)/) ? "hold" :
      "reps"; // sensible default
    return { sets, volume, unit };
  }

  // "45s hold" / "30 seconds" / "1 min hold"
  const durMatch = s.match(/^(\d+(?:\.\d+)?)\s*(s|sec|secs|seconds?|m|min|mins|minutes?)\b\s*(.*)$/);
  if (durMatch) {
    const volume = durMatch[1];
    const uToken = durMatch[2];
    const unit = uToken.startsWith("s") ? "sec" : "min";
    return { sets: 1, volume, unit };
  }

  // "5km run"
  const kmMatch = s.match(/^(\d+(?:\.\d+)?)\s*(km|kilometres?|kilometers?)\b/);
  if (kmMatch) {
    return { sets: 1, volume: kmMatch[1], unit: "km" };
  }

  return null;
}

/** Public — return the rendered prescription string, e.g. "3 x 12 Reps". */
export function formatPrescription(input: PrescriptionInput): string {
  let { sets, volume, unit } = input;
  const rawRes = input.raw ? parsePrescriptionRaw(input.raw) : null;
  if (rawRes) {
    if (sets == null) sets = rawRes.sets;
    if (volume == null || volume === "") volume = rawRes.volume;
    if (!unit) unit = rawRes.unit;
  }
  const setsN = Math.max(1, Math.round(Number(sets) || 1));
  if (volume == null || volume === "") return "";
  const volStr = typeof volume === "number" ? String(volume) : String(volume).trim();
  if (!volStr) return "";
  const key = String(unit || "reps").trim().toLowerCase();
  const label = (UNIT_LABELS[key] || UNIT_LABELS.reps)(volStr);
  return `${setsN} x ${volStr} ${label}`;
}

/**
 * Infer a `PrescriptionInput` from a legacy `ExRow`-shaped exercise. Prefers
 * explicit structured fields (sets/volume/unit) when present; otherwise
 * falls back to `duration_sec`, `reps`, `distance_km`, or `raw`.
 */
export function inferPrescription(ex: any): PrescriptionInput {
  if (!ex) return {};
  // Prefer explicit new-schema fields.
  if (ex.volume != null && ex.unit) {
    return { sets: ex.sets, volume: ex.volume, unit: ex.unit, rest_sec: ex.rest_sec };
  }
  // Duration_sec → convert to sec / min for the pill.
  if (typeof ex.duration_sec === "number" && ex.duration_sec > 0) {
    const secs = Math.round(ex.duration_sec);
    if (secs % 60 === 0 && secs >= 60) {
      return { sets: ex.sets || 1, volume: secs / 60, unit: "min", rest_sec: ex.rest_sec };
    }
    return { sets: ex.sets || 1, volume: secs, unit: "sec", rest_sec: ex.rest_sec };
  }
  // Distance in km (cardio).
  if (ex.distance_km != null && Number(ex.distance_km) > 0) {
    return { sets: ex.sets || 1, volume: ex.distance_km, unit: "km", rest_sec: ex.rest_sec };
  }
  // Reps — could be numeric or a legacy string like "10/side".
  if (ex.reps != null && String(ex.reps).trim() !== "") {
    const repStr = String(ex.reps).trim();
    // Side-suffix?
    if (/\/\s*side|each side|per side/i.test(repStr)) {
      const n = parseInt(repStr, 10);
      if (!Number.isNaN(n)) {
        return { sets: ex.sets || 1, volume: n, unit: "each side", rest_sec: ex.rest_sec };
      }
    }
    const n = Number(repStr);
    if (!Number.isNaN(n)) {
      return { sets: ex.sets || 1, volume: n, unit: "reps", rest_sec: ex.rest_sec };
    }
    // Non-numeric — treat as raw
    return { raw: repStr, sets: ex.sets, rest_sec: ex.rest_sec };
  }
  return {};
}
