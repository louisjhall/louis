/**
 * loggingTypeOverrides — Iter188
 *
 * In-memory cache of coach-defined logging_type overrides. The workout
 * player's classifier (`workoutMode.ts::isTimeBased` / `isCardio`)
 * consults this map BEFORE running its name-regex fallback so any
 * exercise the coach has explicitly forced into a bucket is respected
 * regardless of name/reps content.
 *
 * Lifecycle
 * ---------
 *  - Loaded lazily on the first classifier call.
 *  - Refetched at most every `TTL_MS` (5 minutes) so a coach override
 *    made in the admin UI propagates to the client without a reload.
 *  - Silent no-op on network failure — the classifier falls back to
 *    name/reps regex, which is what we've always done.
 */
import { api } from "@/src/lib/api";

const TTL_MS = 5 * 60 * 1000;

type OverrideValue = "timer" | "cardio" | "reps";
type OverrideMap = { by_id: Record<string, OverrideValue>; by_name: Record<string, OverrideValue> };

let cache: OverrideMap = { by_id: {}, by_name: {} };
let fetchedAt = 0;
let inflight: Promise<void> | null = null;

async function refresh(): Promise<void> {
  if (inflight) return inflight;
  inflight = (async () => {
    try {
      const r = await api<OverrideMap>("/coach/library/logging-overrides");
      cache = {
        by_id: r?.by_id ?? {},
        by_name: r?.by_name ?? {},
      };
      fetchedAt = Date.now();
    } catch {
      // Silently swallow — clients without coach role get 403 here, and
      // that's fine: only the coach's device needs the override map; a
      // client will see the same override baked into `logging_type` on
      // the workout exercise (server-side merge, follow-up if needed).
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

/** Trigger a background refresh if the cache is stale. Non-blocking. */
export function ensureOverridesFresh(): void {
  if (Date.now() - fetchedAt > TTL_MS) {
    refresh(); // fire and forget
  }
}

/**
 * Look up an override for an exercise. Checks `logging_type_override`
 * on the object first (in case the server has already merged it), then
 * by canonical library ID, then by lower-cased name.
 */
export function getLoggingOverride(ex: any): OverrideValue | null {
  if (!ex) return null;
  ensureOverridesFresh();

  // Server-merged override wins.
  const inline = String(ex.logging_type_override || "").toLowerCase().trim();
  if (inline === "timer" || inline === "cardio" || inline === "reps") return inline;

  // Canonical library ID match.
  const id = ex.exercise_id || ex.canonical_id || ex.id;
  if (id && cache.by_id[id]) return cache.by_id[id];

  // Name match (case-insensitive) — catches embedded workout exercises
  // that just have a `name` string, not a canonical id.
  const nm = String(ex.name || ex.exercise_name || "").trim().toLowerCase();
  if (nm && cache.by_name[nm]) return cache.by_name[nm];

  return null;
}

/**
 * Force-refresh — call after a coach saves an override in the admin UI
 * so the classifier picks it up immediately without waiting 5 min.
 */
export async function reloadOverrides(): Promise<void> {
  fetchedAt = 0;
  await refresh();
}
