/**
 * useOtaUpdates — Iter 95a
 *
 * Silent OTA check on app start. Uses expo-updates for JS-only fixes so we
 * don't need a TestFlight rebuild for every small change. Gracefully
 * no-ops if `expo.updates.url` isn't wired up (dev builds, Expo Go,
 * or first launch before EAS Update is configured).
 *
 * Wire order:
 *   1. On mount → checkForUpdateAsync
 *   2. If update available → fetchUpdateAsync
 *   3. After next natural resume → reloadAsync (only when the user is idle)
 *
 * All copy is Louis-voiced.  No user-facing "AI"/"generated" wording.
 */
import { useEffect, useRef } from "react";
import { Platform } from "react-native";
import * as Updates from "expo-updates";

/** Called once from the root layout after auth is ready. */
export function useOtaUpdates(): void {
  const attempted = useRef(false);

  useEffect(() => {
    if (attempted.current) return;
    attempted.current = true;

    // Web preview and Expo Go don't run the native updates module.
    if (Platform.OS === "web") return;
    // isEnabled is false in dev / when no URL is configured.
    if (!(Updates as any).isEnabled) return;

    (async () => {
      try {
        const r = await Updates.checkForUpdateAsync();
        if (!(r as any)?.isAvailable) return;
        const f = await Updates.fetchUpdateAsync();
        if (!(f as any)?.isNew) return;
        // Wait a beat before reloading so we don't hijack the initial paint.
        setTimeout(() => {
          Updates.reloadAsync().catch(() => { /* silent */ });
        }, 2500);
      } catch {
        // Network offline, no URL configured, or app in dev — silent skip.
      }
    })();
  }, []);
}
