/**
 * CrewFitIntroAnimation — Iter 125-DIAG (BUNDLE_PROBE build)
 *
 * DIAGNOSTIC MODE: expo-video is temporarily removed from the startup gate.
 * During phase "showing_intro" we render ONLY a plain React Native screen
 * (black background, centred white text). No useVideoPlayer, no VideoView,
 * no MP4 require() anywhere on cold launch.
 *
 * Purpose: prove the physical device is actually running THIS bundle. If
 * the iPhone still shows either the minimalist startup video or the Louis
 * overlay during the intro window, the device is running a stale bundle.
 *
 * Structural gate contract is unchanged:
 *   undecided     → black screen, {children} NOT mounted
 *   showing_intro → diagnostic text screen, {children} NOT mounted
 *   done          → {children} only
 *
 * 12-hour persistence is unchanged (crewfit_intro_last_played_at).
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, Platform,
} from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { theme } from "@/src/lib/theme";

const KEY_LAST = "crewfit_intro_last_played_at";
const KEY_PENDING = "crewfit_intro_pending_reason";
const TWELVE_HOURS_MS = 12 * 60 * 60 * 1000;

// Bundle probe: log once at module load so the [BUNDLE_PROBE] tag is
// definitely emitted before any user interaction. If this line doesn't
// appear in Metro logs on cold launch, the device is running a stale bundle.
console.log("[BUNDLE_PROBE] CREWFIT_2026_07_29_0946");

// Module-level flag so we NEVER play the intro twice in the same JS runtime
// (same app session — different from a real cold launch). Resets on process
// kill; survives hot re-mounts.
let alreadyPlayedThisSession = false;

/** Persistently queue the intro to fire on the very next mount, regardless
 *  of the 12-hour cooldown. Use after onboarding completes. */
export async function queueIntroForNextMount(reason: "onboarded" | "cold_launch" = "onboarded"): Promise<void> {
  try { await AsyncStorage.setItem(KEY_PENDING, reason); } catch { /* ignore */ }
}

async function shouldPlayIntro(): Promise<boolean> {
  if (alreadyPlayedThisSession) return false;
  try {
    const pending = await AsyncStorage.getItem(KEY_PENDING);
    if (pending) {
      await AsyncStorage.removeItem(KEY_PENDING);
      return true;
    }
    const last = await AsyncStorage.getItem(KEY_LAST);
    if (!last) return true;
    const ts = Date.parse(last);
    if (isNaN(ts)) return true;
    return (Date.now() - ts) >= TWELVE_HOURS_MS;
  } catch {
    return !alreadyPlayedThisSession;
  }
}

async function stampPlayed(): Promise<void> {
  try { await AsyncStorage.setItem(KEY_LAST, new Date().toISOString()); } catch { /* ignore */ }
}

type Phase = "undecided" | "showing_intro" | "done";

export function CrewFitIntroAnimation({ children }: { children: React.ReactNode }) {
  const [phase, setPhase] = useState<Phase>("undecided");

  useEffect(() => {
    console.log("[BUNDLE_PROBE] CrewFitIntroAnimation mounted");
    let cancelled = false;
    (async () => {
      const play = await shouldPlayIntro();
      if (cancelled) return;
      if (play) {
        alreadyPlayedThisSession = true;
        setPhase("showing_intro");
      } else {
        setPhase("done");
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const handleIntroFinished = useCallback(() => {
    stampPlayed();
    setPhase("done");
  }, []);

  if (phase === "undecided") {
    return <View style={styles.blackFill} />;
  }

  if (phase === "showing_intro") {
    return <IntroGate onFinished={handleIntroFinished} />;
  }

  return <>{children}</>;
}

/* --------------------------- diagnostic gate ------------------------------ */
function IntroGate({ onFinished }: { onFinished: () => void }) {
  const finishedRef = useRef(false);

  useEffect(() => {
    console.log("[STARTUP_DIAG] gate mounted (no video)");
    // Hold the diagnostic screen for 8 seconds, then hand off to the app.
    const timer = setTimeout(() => {
      if (finishedRef.current) return;
      finishedRef.current = true;
      console.log("[STARTUP_DIAG] 8s elapsed — finishing");
      onFinished();
    }, 8000);
    return () => {
      clearTimeout(timer);
      console.log("[STARTUP_DIAG] gate unmounted");
    };
  }, [onFinished]);

  return (
    <View style={styles.bg} testID="crewfit-intro-animation-diag">
      <Text style={styles.headline}>CREWFIT STARTUP TEST 0946</Text>
      <Text style={styles.subline}>NO VIDEO LOADED</Text>
      <View style={styles.spacer} />
      <Text style={styles.bundleTag}>BUNDLE 0946</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  blackFill: {
    flex: 1,
    backgroundColor: "#000",
  },
  bg: {
    flex: 1,
    backgroundColor: "#000",
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 24,
    ...Platform.select({
      ios: { zIndex: 10_000 },
      android: { elevation: 100 },
      web: { zIndex: 10_000 } as any,
      default: {},
    }),
  },
  headline: {
    color: "#fff",
    fontSize: 22,
    fontWeight: "900",
    letterSpacing: 2,
    textAlign: "center",
  },
  subline: {
    color: "#fff",
    fontSize: 14,
    fontWeight: "700",
    letterSpacing: 3,
    marginTop: 14,
    textAlign: "center",
  },
  spacer: { height: 40 },
  bundleTag: {
    color: theme.color.brand,
    fontSize: 12,
    fontWeight: "800",
    letterSpacing: 3,
  },
});

export default CrewFitIntroAnimation;
