/**
 * useThemeMode — Iter179 · CENTRAL RELOAD FIX.
 *
 * Root problem this hook solves:
 *   ~130+ files in the app use `const styles = StyleSheet.create({ ... })`
 *   at MODULE SCOPE, referencing `theme.color.*`. RN evaluates the object
 *   literal ONCE at import time and freezes every hex string. Any later
 *   mutation of `theme.color` cannot repaint those stylesheets — only a
 *   full JS bundle re-execution can.
 *
 * Contract:
 *   1. Persist the user's choice SYNCHRONOUSLY via `persistThemeModeSync`
 *      so the very next boot reads the correct value.
 *   2. Immediately force a **full JS bundle reload** on every platform:
 *        • Web  → `window.location.reload()`
 *        • Native (prod / dev build) → `Updates.reloadAsync()`
 *        • Native (Expo Go / dev) → `DevSettings.reload()` fallback
 *   3. On next boot, `theme.ts::_readInitialModeSync()` reads the saved
 *      preference synchronously (SecureStore on native, localStorage on
 *      web) BEFORE any child module runs `StyleSheet.create`, so every
 *      static stylesheet in the app captures the correct palette on
 *      its very first evaluation.
 *
 * Dark Mode is not modified — same reload flow, same DARK_PALETTE.
 */
import { useEffect, useState, useCallback } from "react";
import { Platform, DevSettings } from "react-native";
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

/** Trigger a hard, cross-platform JS bundle reload. */
function _hardReload(): void {
  if (Platform.OS === "web") {
    try {
      // Web preview / Expo Web: full page reload re-imports every module
      // and re-runs `StyleSheet.create` with the freshly persisted palette.
      const w: any = globalThis as any;
      if (w && w.location && typeof w.location.reload === "function") {
        w.location.reload();
        return;
      }
    } catch { /* fall through */ }
    return;
  }
  // Native path — try Updates first (works in dev-client & production
  // standalone builds), then DevSettings (works in Expo Go & Metro dev).
  try {
    Updates.reloadAsync()
      .catch(() => {
        try { DevSettings.reload(); } catch { /* last-resort no-op */ }
      });
  } catch {
    try { DevSettings.reload(); } catch { /* last-resort no-op */ }
  }
}

/** Read + change the current theme mode from any component. */
export function useThemeMode() {
  const [mode, setMode] = useState<ThemeMode>(getThemeMode());

  useEffect(() => {
    return subscribeThemeMode((m) => setMode(m));
  }, []);

  const change = useCallback((next: ThemeMode) => {
    // 1) In-place mutate the palette so the very brief window before
    //    the reload lands still shows the new colours where possible.
    _setThemeModeInPlace(next);
    // 2) Durable SYNCHRONOUS persistence — SecureStore on native +
    //    localStorage on web. Guarantees the next cold-start reads
    //    the correct mode BEFORE any StyleSheet.create runs.
    persistThemeModeSync(next);
    // 3) Keep AsyncStorage in step for legacy code paths.
    AsyncStorage.setItem(STORAGE_KEY, next).catch(() => {});
    // 4) Force a full JS bundle reload on every platform. This is the
    //    ONLY reliable way to un-freeze the ~130 module-scope
    //    `StyleSheet.create` calls that captured the previous palette.
    _hardReload();
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
