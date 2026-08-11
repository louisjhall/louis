/**
 * Persist the user's workout preferences per-device via AsyncStorage.
 * All getters default sensibly if nothing is saved.
 */
import { useEffect, useState } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";

export type WorkoutMode = "manual" | "guided";

/* -------------------------------------------------------------------------- */
/*  Iter167 · Master Brain — cardio-vs-strength classification.               */
/*  Used by workout/[id]/index.tsx, list.tsx, play.tsx and guided.tsx so      */
/*  every screen agrees on which rendering path an exercise takes.            */
/* -------------------------------------------------------------------------- */

/**
 * Priority order:
 *   1. `logging_type` — always wins if set by coach / JSON importer / library.
 *        · "cardio" | "timer"  → cardio
 *        · any other explicit value → strength (name-regex is skipped so
 *          e.g. "Tempo Back Squat" typed as "strength" never flips)
 *   2. Fallback keyword regex over name + reps + duration + category. Only
 *      runs when `logging_type` is missing / blank.
 *
 * NOTE: `tempo` is intentionally excluded — "Tempo Back Squat" is a lift.
 * `zone[\s-]?[1235]` matches "zone 2", "zone-2", "z2" and captures the
 * hyphenated intervals seen in the JSON importer output.
 */
export function isCardioExercise(ex: any): boolean {
  if (!ex) return false;
  const lt = (ex.logging_type || "").toString().toLowerCase().trim();
  if (lt === "cardio" || lt === "timer") return true;
  if (lt) return false;

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
