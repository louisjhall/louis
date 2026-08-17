/**
 * Iter182 · Shared workout section bucketing + preview helpers.
 *
 * Both `/app/workout/[id]/index.tsx` (preview / read-only card layout)
 * and `/app/workout/[id]/list.tsx` (workout player) render the same
 * three sections — WARM-UP · MAIN · COOL-DOWN — but until this file
 * existed they each implemented the bucketing logic independently and
 * drifted apart (the preview forgot cool-down entirely, and both
 * screens differed on whether items tagged `section: "cooldown"` inside
 * `exercises[]` were counted in "main").
 *
 * Contract (`bucketWorkout`):
 *   · Prefer explicit `w.warmup[]` for warm-up.
 *   · Prefer explicit `w.cooldown[]` for cool-down; otherwise pull
 *     items from `w.exercises[]` whose `section === "cooldown"`.
 *   · "Main" is `w.exercises[]` with any `section === "cooldown"`
 *     items removed so nothing renders twice.
 *
 * Also exports `formatCardioMeta`, which centralises the fallback chain
 * for cardio preview lines — duration → distance → RPE → coach's raw
 * `load` / `load_prescription` string — so preview and player agree.
 */

/**
 * Loose row type used across screens. We intentionally keep this
 * `any`-typed at the top level so consumers can pass their own richer
 * types without a TS cast; the helper only reads a small subset.
 */
export type BucketedExRow = any;

export interface WorkoutBuckets {
  warmup: BucketedExRow[];
  main: BucketedExRow[];
  cooldown: BucketedExRow[];
}

/**
 * Split a workout doc into warm-up / main / cool-down buckets.
 *
 * Accepts either the full workout doc (`w`) or a variant-overlayed
 * `view` — both share the same top-level shape (`warmup[]`,
 * `cooldown[]`, `exercises[]`).
 */
export function bucketWorkout(w: any | null | undefined): WorkoutBuckets {
  if (!w) return { warmup: [], main: [], cooldown: [] };
  const warm = Array.isArray(w.warmup) ? w.warmup : [];
  // Cool-down source of truth priority:
  //   1. Explicit `w.cooldown[]` (JSON importer / coach edit).
  //   2. Fallback: items inside `exercises[]` tagged with `section: "cooldown"`.
  const explicitCool = Array.isArray(w.cooldown) ? w.cooldown : [];
  const inlineCool = (Array.isArray(w.exercises) ? w.exercises : [])
    .filter((e: any) => (e?.section || "").toLowerCase() === "cooldown");
  const cool = explicitCool.length > 0 ? explicitCool : inlineCool;
  // Main = exercises MINUS any cool-down-tagged rows so they don't
  // double-list when the coach used the inline-tag fallback.
  const main = (Array.isArray(w.exercises) ? w.exercises : []).filter(
    (e: any) => (e?.section || "main").toLowerCase() !== "cooldown",
  );
  return { warmup: warm, main, cooldown: cool };
}

/**
 * Build the one-line meta string shown under a cardio exercise's name
 * in the preview card. Falls back through duration → distance → RPE
 * → the coach's raw load prescription string, so a coach who typed
 * "Zone 2 · 45 min steady" as `load_prescription` still sees something
 * useful when `duration_sec` and `distance_m` are blank.
 */
export function formatCardioMeta(ex: any): string {
  const bits: string[] = [];
  if (typeof ex?.duration_sec === "number" && ex.duration_sec > 0) {
    const mins = Math.round(ex.duration_sec / 60);
    bits.push(`${mins} min`);
  } else if (typeof ex?.duration === "string" && ex.duration.trim()) {
    bits.push(String(ex.duration).trim());
  } else if (typeof ex?.duration === "number" && ex.duration > 0) {
    bits.push(`${ex.duration} min`);
  }
  if (typeof ex?.distance_m === "number" && ex.distance_m > 0) {
    bits.push(`${(ex.distance_m / 1000).toFixed(1)} km`);
  }
  if (ex?.rpe) bits.push(`RPE ${ex.rpe}`);
  if (bits.length === 0) {
    // Iter182 · No structured data — fall back to whatever the coach
    // typed as a free-text prescription instead of leaving the meta
    // line blank (which used to happen when a cardio exercise had
    // only `load_prescription: "45 min zone 2"` on it).
    const raw = ex?.load_prescription || ex?.load || ex?.prescription;
    if (typeof raw === "string" && raw.trim()) {
      return raw.trim();
    }
  }
  return bits.join(" · ");
}

/**
 * Build the one-line meta string for a WARM-UP row shown in preview
 * mode. If the coach set an explicit `duration_sec`, we show that
 * (matches list.tsx's rendering). Otherwise we surface set × rep data
 * so the client still knows what to do — the old preview screen
 * hardcoded `30s` for every row that lacked a duration, which was
 * often wrong when the warm-up was actually a "3 × 8 cat-cow"
 * mobility drill.
 */
export function formatWarmupMeta(ex: any): string {
  const dsec = typeof ex?.duration_sec === "number" ? ex.duration_sec : 0;
  if (dsec > 0) return `${dsec}s`;
  const dur = ex?.duration;
  if (typeof dur === "string" && dur.trim()) return dur.trim();
  if (typeof dur === "number" && dur > 0) return `${dur}s`;
  // Fall through to sets × reps ONLY when we have real data — otherwise
  // return an empty string so the row doesn't print a misleading "30s".
  const sets = ex?.sets;
  const reps = ex?.reps;
  if (sets && reps) return `${sets} × ${reps}`;
  if (reps)         return String(reps);
  if (sets)         return `${sets} sets`;
  return "";
}
