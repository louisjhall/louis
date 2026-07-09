/**
 * Persist the user's workout preferences per-device via AsyncStorage.
 * All getters default sensibly if nothing is saved.
 */
import { useEffect, useState } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";

export type WorkoutMode = "manual" | "guided";

const MODE_KEY = "crewfit.workout.mode";
const REMEMBER_KEY = "crewfit.workout.mode.remember";
const AUTO_CONTINUE_KEY = "crewfit.workout.autoContinue";
const AUTO_REST_KEY = "crewfit.workout.autoRest";
const SOUND_KEY = "crewfit.workout.sound";
const HAPTICS_KEY = "crewfit.workout.haptics";

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

/* Reactive hook for the settings screen ----------------------------------- */
export type WorkoutSettings = {
  sound: boolean;
  haptics: boolean;
  autoRest: boolean;
  autoContinue: boolean;
};

export function useWorkoutSettings() {
  const [settings, setSettings] = useState<WorkoutSettings>({
    sound: true, haptics: true, autoRest: true, autoContinue: false,
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const [sound, haptics, autoRest, autoContinue] = await Promise.all([
        getSoundOn(), getHapticsOn(), getAutoRest(), getAutoContinue(),
      ]);
      setSettings({ sound, haptics, autoRest, autoContinue });
      setLoading(false);
    })();
  }, []);

  const update = async (patch: Partial<WorkoutSettings>) => {
    const next = { ...settings, ...patch };
    setSettings(next);
    if ("sound" in patch) await setSoundOn(next.sound);
    if ("haptics" in patch) await setHapticsOn(next.haptics);
    if ("autoRest" in patch) await setAutoRest(next.autoRest);
    if ("autoContinue" in patch) await setAutoContinue(next.autoContinue);
  };

  return { settings, update, loading };
}
