/**
 * Persist the user's workout preferences per-device via AsyncStorage.
 * All getters default sensibly if nothing is saved.
 */
import { useEffect, useState } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { getLoggingOverride } from "@/src/lib/loggingTypeOverrides";

export type WorkoutMode = "manual" | "guided";

/* -------------------------------------------------------------------------- */
/*  Iter167 · Master Brain — cardio-vs-strength classification.               */
/*  Used by workout/[id]/index.tsx, list.tsx, play.tsx and guided.tsx so      */
/*  every screen agrees on which rendering path an exercise takes.            */
/* -------------------------------------------------------------------------- */

/**
 * Priority order (iter189m hardened):
 *   1. Coach `logging_type_override` — hard win.
 *   2. `logging_type` = "cardio" | "timer" — hard win (true).
 *      Any OTHER logging_type value (weighted / bodyweight / mobility /
 *      unknown) does NOT short-circuit — we still run the name-regex
 *      so mis-typed library rows (e.g. "Easy Walk" tagged as bodyweight)
 *      are still recognised as cardio by name.
 *   3. Fallback keyword regex over name + reps + duration + category.
 *
 * NOTE: `tempo` is intentionally excluded — "Tempo Back Squat" is a lift.
 * `zone[\s-]?[1235]` matches "zone 2", "zone-2", "z2" and captures the
 * hyphenated intervals seen in the JSON importer output.
 */
export function isCardioExercise(ex: any): boolean {
  if (!ex) return false;

  // Iter188 · Coach override wins over every other signal.
  const override = getLoggingOverride(ex);
  if (override === "cardio") return true;
  if (override === "timer" || override === "reps") return false;

  // Iter189m · Only positive cardio/timer values short-circuit. Any
  // other value (weighted / bodyweight / mobility / unknown) still
  // lets the name regex run so mis-typed rows can be corrected.
  const lt = (ex.logging_type || "").toString().toLowerCase().trim();
  if (lt === "cardio" || lt === "timer") return true;

  const hay = `${ex.name || ""} ${ex.reps || ""} ${ex.duration || ""} ${ex.category || ""}`.toLowerCase();

  // Full keyword list — merged from guided.tsx (walk, hike, ruck, stair
  // variants) and augmented with row + cycle per iter167 request.
  const cardioHit = /\b(run|running|jog|zone[\s-]?[1235]|z[1235]|intervals?|treadmill|row|rowing|erg|bike|biking|cycling|cycle|assault|swim|swimming|sprint|ez pace|long run|fartlek|walk|walking|hike|hiking|ruck|rucking|stair|stairs|stairmaster|stepper|incline\s?walk|power\s?walk|brisk\s?walk|recovery\s?walk)\b/.test(hay);

  // Strength patterns that CONTAIN a cardio keyword must be excluded.
  // Rows in the gym (barbell / dumbbell / cable / seal / pendlay …) are
  // strength, not cardio. "Walking lunge" and "walking plank" are strength.
  const strengthNameExclude = /\b(walking\s+(lunge|plank|push|dead\s?bug)|bent[- ]?over\s?row|barbell\s?row|dumbbell\s?row|db\s?row|kb\s?row|pendlay\s?row|seal\s?row|meadows\s?row|chest[- ]?supported\s?row|inverted\s?row|single[- ]?arm\s?row|renegade\s?row|t[- ]?bar\s?row|kroc\s?row|upright\s?row|face\s?pull|cable\s?row|iso\s?row|smith\s?row|helms\s?row|hip\s?thrust)\b/.test(hay);

  return cardioHit && !strengthNameExclude;
}

/* -------------------------------------------------------------------------- */
/*  Iter188 · Time-based exercise detection — shared between guided.tsx and    */
/*  play.tsx so both flows agree that side plank, farmer's carry, dead-hang    */
/*  and cardio blocks show a live TIMER, never kg/reps.                        */
/*                                                                             */
/*  Priority order:                                                            */
/*    1. Any cardio exercise → time-based by definition (bike, treadmill, …)   */
/*    2. `logging_type` = "timer" | "hold" | "time" → explicit signal          */
/*    3. Explicit `work_sec` / `duration_sec` field on the row                 */
/*    4. `reps` string mentions seconds / minutes / mm:ss / "hold"             */
/*    5. Name regex — canonical hold-and-carry moves                           */
/* -------------------------------------------------------------------------- */

export function isTimeBased(ex: any): boolean {
  if (!ex) return false;

  // Iter188 · Coach override wins over every other signal.
  const override = getLoggingOverride(ex);
  if (override === "timer" || override === "cardio") return true;
  if (override === "reps") return false;

  // Priority 1: cardio is always time-based.
  if (isCardioExercise(ex)) return true;

  // Priority 2: explicit logging_type from the coach / library.
  const lt = (ex.logging_type || "").toString().toLowerCase().trim();
  if (lt === "timer" || lt === "hold" || lt === "time" || lt === "duration") return true;

  // Priority 3: explicit duration seconds field.
  const explicit = parseInt(String(ex?.work_sec || ex?.duration_sec || 0), 10);
  if (explicit > 0) return true;

  // Priority 4: reps string looks like a time.
  const reps = String(ex?.reps || "").toLowerCase();
  if (/\b\d+\s*(s|sec|secs|second|seconds|min|mins|minute|minutes)\b/.test(reps)) return true;
  if (/^\d+:\d{2}$/.test(reps.trim())) return true;
  if (/\b(hold|for time|until failure|max time|steady|steady state|steady ride)\b/.test(reps)) return true;

  // Priority 5: canonical hold-and-carry name regex.
  const name = String(ex?.name || "").toLowerCase();
  return /\b(side plank|front plank|plank|hollow hold|wall sit|dead ?hang|l[- ]?sit|farmer'?s? (walk|carry)|suitcase carry|overhead carry|superman hold|bridge hold|forearm plank|hollow rock|dish hold|bear crawl hold|hanging (l[- ]?sit|leg hold)|copenhagen (hold|plank)|couch stretch|pigeon (hold|stretch)|isometric)\b/.test(name);
}

/**
 * Extract the target duration in seconds for a time-based exercise.
 * Falls back to 30 s when the exercise is timed but no explicit target
 * is parseable. Iter188 — moved to shared lib so play.tsx and guided.tsx
 * never disagree on what "60 seconds" means.
 */
export function extractTargetSeconds(ex: any): number {
  const explicit = parseInt(String(ex?.work_sec || ex?.duration_sec || 0), 10);
  if (explicit > 0) return Math.max(5, Math.min(3600, explicit));
  const reps = String(ex?.reps || "").trim();
  const mmss = /^(\d+):(\d{2})$/.exec(reps);
  if (mmss) return parseInt(mmss[1], 10) * 60 + parseInt(mmss[2], 10);
  const minMatch = /(\d+)\s*(?:min|mins|minute|minutes)/i.exec(reps);
  if (minMatch) return parseInt(minMatch[1], 10) * 60;
  const secMatch = /(\d+)\s*(?:s|sec|secs|second|seconds)/i.exec(reps);
  if (secMatch) return Math.max(5, parseInt(secMatch[1], 10));
  const plainNum = /^(\d+)/.exec(reps);
  if (plainNum) {
    const n = parseInt(plainNum[1], 10);
    if (n >= 5 && n <= 3600) return n;
  }
  // Cardio without a stated duration defaults to 20 min (steady ride,
  // steady run, etc.). Non-cardio holds default to 30 s.
  return isCardioExercise(ex) ? 20 * 60 : 30;
}

export function formatMMSS(totalSec: number): string {
  const s = Math.max(0, Math.floor(totalSec));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r.toString().padStart(2, "0")}`;
}

/* -------------------------------------------------------------------------- */

const MODE_KEY = "crewfit.workout.mode";
const REMEMBER_KEY = "crewfit.workout.mode.remember";
const AUTO_CONTINUE_KEY = "crewfit.workout.autoContinue";
const AUTO_REST_KEY = "crewfit.workout.autoRest";
const SOUND_KEY = "crewfit.workout.sound";
const HAPTICS_KEY = "crewfit.workout.haptics";
const VOICE_KEY = "crewfit.workout.voice";

/* Mode preference ---------------------------------------------------------- */
export async function getRememberedMode(): Promise<WorkoutMode | null> {
  try {
    const remember = await AsyncStorage.getItem(REMEMBER_KEY);
    if (remember !== "1") return null;
    const m = await AsyncStorage.getItem(MODE_KEY);
    return m === "manual" || m === "guided" ? m : null;
  } catch { return null; }
}

export async function setPreferredMode(mode: WorkoutMode, remember: boolean): Promise<void> {
  try {
    await AsyncStorage.setItem(MODE_KEY, mode);
    await AsyncStorage.setItem(REMEMBER_KEY, remember ? "1" : "0");
  } catch { /* ignore */ }
}

/* Generic boolean setting helpers ----------------------------------------- */
async function getBool(key: string, defaultVal: boolean): Promise<boolean> {
  try {
    const v = await AsyncStorage.getItem(key);
    if (v === null) return defaultVal;
    return v === "1";
  } catch { return defaultVal; }
}

async function setBool(key: string, on: boolean): Promise<void> {
  try { await AsyncStorage.setItem(key, on ? "1" : "0"); } catch { /* ignore */ }
}

/* Auto Continue (default OFF per spec) ------------------------------------ */
export const getAutoContinue = () => getBool(AUTO_CONTINUE_KEY, false);
export const setAutoContinue = (on: boolean) => setBool(AUTO_CONTINUE_KEY, on);

/* Auto Rest Timer (default ON) -------------------------------------------- */
export const getAutoRest = () => getBool(AUTO_REST_KEY, true);
export const setAutoRest = (on: boolean) => setBool(AUTO_REST_KEY, on);

/* Sound (default ON) ------------------------------------------------------ */
export const getSoundOn = () => getBool(SOUND_KEY, true);
export const setSoundOn = (on: boolean) => setBool(SOUND_KEY, on);

/* Haptics (default ON) ---------------------------------------------------- */
export const getHapticsOn = () => getBool(HAPTICS_KEY, true);
export const setHapticsOn = (on: boolean) => setBool(HAPTICS_KEY, on);

/* Voice narration (default ON) — used by the Guided Flow only ------------- */
export const getVoiceOn = () => getBool(VOICE_KEY, true);
export const setVoiceOn = (on: boolean) => setBool(VOICE_KEY, on);

/* Reactive hook for the settings screen ----------------------------------- */
export type WorkoutSettings = {
  sound: boolean;
  haptics: boolean;
  voice: boolean;
  autoRest: boolean;
  autoContinue: boolean;
};

export function useWorkoutSettings() {
  const [settings, setSettings] = useState<WorkoutSettings>({
    sound: true, haptics: true, voice: true, autoRest: true, autoContinue: false,
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const [sound, haptics, voice, autoRest, autoContinue] = await Promise.all([
        getSoundOn(), getHapticsOn(), getVoiceOn(), getAutoRest(), getAutoContinue(),
      ]);
      setSettings({ sound, haptics, voice, autoRest, autoContinue });
      setLoading(false);
    })();
  }, []);

  const update = async (patch: Partial<WorkoutSettings>) => {
    const next = { ...settings, ...patch };
    setSettings(next);
    if ("sound" in patch) await setSoundOn(next.sound);
    if ("haptics" in patch) await setHapticsOn(next.haptics);
    if ("voice" in patch) await setVoiceOn(next.voice);
    if ("autoRest" in patch) await setAutoRest(next.autoRest);
    if ("autoContinue" in patch) await setAutoContinue(next.autoContinue);
  };

  return { settings, update, loading };
}
