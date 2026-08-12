/**
 * useThemeMode — Iter169 (updated Iter176)
 *
 * React hook to read the current theme mode ("dark" | "light") and change it.
 * The theme palette lives in src/lib/theme.ts as a mutable object; the
 * hook wires re-renders to the subscribeThemeMode/broadcast mechanism.
 *
 * On first app boot, `theme.ts::_readInitialModeSync()` reads the saved
 * preference SYNCHRONOUSLY from localStorage (web) or expo-secure-store
 * (native) so `StyleSheet.create()` calls pick up the correct colours on
 * their very first evaluation.
 *
 * Iter176 · On toggle we ALSO mirror-write the choice into SecureStore
 * (native) via `persistThemeModeSync` and then request a full JS bundle
 * reload with `Updates.reloadAsync()` so any StyleSheets that captured
 * stale hex values fully repaint in the new palette immediately — no
 * force-quit / reopen needed.
 */
import { useEffect, useState, useCallback } from "react";
import { Platform } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Updates from "expo-updates";
import {
  type ThemeMode,
  getThemeMode,
  setThemeMode as _setThemeModeInPlace,
  subscribeThemeMode,
  persistThemeModeSync,
} from "@/src/lib/theme";

const STORAGE_KEY = "crewfit.theme.mode";

/** Read + change the current theme mode from any component. */
export function useThemeMode() {
  const [mode, setMode] = useState<ThemeMode>(getThemeMode());

  useEffect(() => {
    return subscribeThemeMode((m) => setMode(m));
  }, []);

  const change = useCallback((next: ThemeMode) => {
    // 1) In-place mutate the palette so live JSX reads pick up new colours.
    _setThemeModeInPlace(next);
    // 2) Durable sync persistence — SecureStore on native + localStorage
    //    on web. Guarantees the next cold-start reads the correct mode
    //    BEFORE any StyleSheet.create runs.
    persistThemeModeSync(next);
    // 3) Also keep AsyncStorage in step for legacy code paths.
    AsyncStorage.setItem(STORAGE_KEY, next).catch(() => {});
    // 4) Iter176 · Force a full JS reload so any StyleSheet objects that
    //    captured the previous palette rebuild cleanly. Skipped on web
    //    preview (Updates isn't wired there) — the `key={mode}` remount
    //    in _layout.tsx handles the web repaint.
    if (Platform.OS !== "web") {
      Updates.reloadAsync().catch(() => {
        // Non-fatal — the palette mutation + subscribe path still
        // repaints anything that reads theme.color inline.
      });
    }
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
