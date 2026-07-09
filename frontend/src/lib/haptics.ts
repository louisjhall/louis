/**
 * Cross-platform haptics helper.
 * Uses expo-haptics on native. Silently no-ops on web (browsers don't support real haptics).
 * Never throws — respects the user's Haptics setting.
 */
import { Platform } from "react-native";
import * as Haptics from "expo-haptics";
import { getHapticsOn } from "./workoutMode";

async function guard(): Promise<boolean> {
  if (Platform.OS === "web") return false;
  try { return await getHapticsOn(); } catch { return true; }
}

export async function hapticLight(): Promise<void> {
  if (!(await guard())) return;
  try { await Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light); } catch { /* silent */ }
}

export async function hapticMedium(): Promise<void> {
  if (!(await guard())) return;
  try { await Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium); } catch { /* silent */ }
}

export async function hapticHeavy(): Promise<void> {
  if (!(await guard())) return;
  try { await Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy); } catch { /* silent */ }
}

export async function hapticSuccess(): Promise<void> {
  if (!(await guard())) return;
  try { await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success); } catch { /* silent */ }
}

export async function hapticSelection(): Promise<void> {
  if (!(await guard())) return;
  try { await Haptics.selectionAsync(); } catch { /* silent */ }
}

export async function hapticWarning(): Promise<void> {
  if (!(await guard())) return;
  try { await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning); } catch { /* silent */ }
}
