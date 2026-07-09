/**
 * Persist the user's preferred workout mode (Manual or Guided Flow).
 * Stored per-device via AsyncStorage.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";

export type WorkoutMode = "manual" | "guided";

const MODE_KEY = "crewfit.workout.mode";
const REMEMBER_KEY = "crewfit.workout.mode.remember";
const AUTO_CONTINUE_KEY = "crewfit.workout.autoContinue";
const SOUND_KEY = "crewfit.workout.sound";

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

export async function getAutoContinue(): Promise<boolean> {
  try {
    const v = await AsyncStorage.getItem(AUTO_CONTINUE_KEY);
    return v !== "0"; // default ON
  } catch { return true; }
}

export async function setAutoContinue(on: boolean): Promise<void> {
  try { await AsyncStorage.setItem(AUTO_CONTINUE_KEY, on ? "1" : "0"); } catch { /* ignore */ }
}

export async function getSoundOn(): Promise<boolean> {
  try {
    const v = await AsyncStorage.getItem(SOUND_KEY);
    return v !== "0"; // default ON
  } catch { return true; }
}

export async function setSoundOn(on: boolean): Promise<void> {
  try { await AsyncStorage.setItem(SOUND_KEY, on ? "1" : "0"); } catch { /* ignore */ }
}
