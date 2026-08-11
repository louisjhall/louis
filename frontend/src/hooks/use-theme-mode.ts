/**
 * useThemeMode — Iter169
 *
 * React hook to read the current theme mode ("dark" | "light") and change it.
 * The theme palette lives in src/lib/theme.ts as a mutable object; the
 * hook wires re-renders to the subscribeThemeMode/broadcast mechanism.
 *
 * On first app boot, ThemeBootstrapper (below) loads the saved preference
 * from AsyncStorage BEFORE the app renders — so StyleSheet.create() calls
 * pick up the correct colours on first paint.
 */
import { useEffect, useState, useCallback } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import {
  type ThemeMode,
  getThemeMode,
  setThemeMode as _setThemeModeInPlace,
  subscribeThemeMode,
} from "@/src/lib/theme";

const STORAGE_KEY = "crewfit.theme.mode";

/** Read + change the current theme mode from any component. */
export function useThemeMode() {
  const [mode, setMode] = useState<ThemeMode>(getThemeMode());

  useEffect(() => {
    return subscribeThemeMode((m) => setMode(m));
  }, []);

  const change = useCallback((next: ThemeMode) => {
    _setThemeModeInPlace(next);
    AsyncStorage.setItem(STORAGE_KEY, next).catch(() => {});
  }, []);

  return { mode, setMode: change, isDark: mode === "dark", isLight: mode === "light" };
}

/**
 * Load the saved theme mode from AsyncStorage. Call from the very top of
 * _layout.tsx BEFORE any child screens render (via a synchronous-ish
 * boot gate). Returns a Promise that resolves once the palette is
 * mutated so the first paint uses the right colours.
 */
export async function bootstrapThemeMode(): Promise<ThemeMode> {
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEY);
    if (raw === "light" || raw === "dark") {
      _setThemeModeInPlace(raw);
      return raw;
    }
  } catch {
    /* ignore */
  }
  return getThemeMode();
}
