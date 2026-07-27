/**
 * CrewFitIntroAnimation — Iter 105
 *
 * Premium branded cold-launch animation for CrewFit. Full-screen 9:16 video
 * on pure black background. Fires on:
 *   1. Cold launch — the very first render of the app in a session, gated
 *      to no more than once every 12 hours.
 *   2. First appearance of the client dashboard right after onboarding
 *      completes. That single fire REPLACES the cold-launch play for the
 *      day — never both back to back.
 *
 * It does NOT fire on:
 *   - Tab changes / navigation between screens
 *   - Returning from background
 *   - Pull-to-refresh / dashboard reloads
 *   - Coach routes (only client-facing brand moment)
 *
 * Behaviour:
 *   - Autoplays instantly, unmuted (respects device silent mode via
 *     expo-video defaults — will play silently if the ringer is muted).
 *   - Plays through to end (~10s), then fades out gently over 400ms into
 *     whatever screen sits behind it (already loaded in parallel).
 *   - No skip button, no tap interception — the intro is a short branded
 *     moment, not a modal the user has to dismiss.
 *   - Safety net: 12.5s watchdog force-finishes if `playToEnd` is swallowed
 *     by a driver quirk, so a stuck video can never freeze the launch.
 *
 * Persistence:
 *   AsyncStorage keys:
 *     crewfit_intro_last_played_at   ISO string
 *     crewfit_intro_pending_reason   "cold_launch" | "onboarded" | undefined
 *
 * To FORCE the intro on next launch (e.g. right after onboarding), call
 * `queueIntroForNextMount("onboarded")` — the wrapper will honour it once
 * and clear the flag.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, Animated, Dimensions,
  ActivityIndicator, Platform,
} from "react-native";
import { VideoView, useVideoPlayer } from "expo-video";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { theme } from "@/src/lib/theme";

const INTRO_SOURCE = require("@/assets/louis/intro.mp4");
const KEY_LAST = "crewfit_intro_last_played_at";
const KEY_PENDING = "crewfit_intro_pending_reason";
const TWELVE_HOURS_MS = 12 * 60 * 60 * 1000;
const FADE_OUT_MS = 400;

// Module-level flag so we NEVER play the intro twice in the same JS runtime
// (i.e. same app session — not the same as a "cold launch"). This survives
// hot re-mounts of the wrapper but resets on a real app process kill.
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
      // Consume the flag immediately so we don't fire again.
      await AsyncStorage.removeItem(KEY_PENDING);
      return true;
    }
    const last = await AsyncStorage.getItem(KEY_LAST);
    if (!last) return true;                    // first-ever launch
    const ts = Date.parse(last);
    if (isNaN(ts)) return true;
    return (Date.now() - ts) >= TWELVE_HOURS_MS;
  } catch {
    // If AsyncStorage is unavailable, err on the side of showing the intro
    // once — better UX than never.
    return !alreadyPlayedThisSession;
  }
}

async function stampPlayed(): Promise<void> {
  try { await AsyncStorage.setItem(KEY_LAST, new Date().toISOString()); } catch { /* ignore */ }
}

export function CrewFitIntroAnimation({ children }: { children: React.ReactNode }) {
  // State machine: undecided → visible → dismissed
  const [decided, setDecided] = useState(false);
  const [visible, setVisible] = useState(false);
  const [errored, setErrored] = useState(false);
  const opacity = useRef(new Animated.Value(1)).current;

  // Decide on first mount whether to show the intro. We DON'T mount the
  // video player at all until we've decided — this keeps startup lean for
  // the 99% of screens that won't be showing it.
  useEffect(() => {
    (async () => {
      const play = await shouldPlayIntro();
      if (play) {
        alreadyPlayedThisSession = true;
        setVisible(true);
      }
      setDecided(true);
    })();
  }, []);

  if (!decided) {
    // Very brief — while AsyncStorage resolves. Render a black tile
    // instead of children to avoid a "flash of dashboard then intro"
    // sequence which would look ugly.
    return (
      <View style={{ flex: 1, backgroundColor: "#000", alignItems: "center", justifyContent: "center" }}>
        <ActivityIndicator color={theme.color.brand} />
      </View>
    );
  }

  return (
    <View style={{ flex: 1 }}>
      {/* Dashboard mounts UNDERNEATH the intro so it can load in parallel */}
      {children}
      {visible ? (
        <IntroOverlay
          opacity={opacity}
          errored={errored}
          onError={() => setErrored(true)}
          onFinished={() => {
            stampPlayed();
            // Fade the overlay out for a soft, non-jarring reveal.
            Animated.timing(opacity, {
              toValue: 0,
              duration: FADE_OUT_MS,
              useNativeDriver: true,
            }).start(() => setVisible(false));
          }}
        />
      ) : null}
    </View>
  );
}

/* --------------------------------- overlay -------------------------------- */
function IntroOverlay({
  opacity, errored, onFinished, onError,
}: {
  opacity: Animated.Value;
  errored: boolean;
  onFinished: () => void;
  onError: () => void;
}) {
  const finishedRef = useRef(false);

  const player = useVideoPlayer(INTRO_SOURCE, (p) => {
    // Pure branded moment. Autoplay with sound — respects device silent
    // mode natively (iOS/Android ringer mute silences it automatically).
    p.loop = false;
    p.muted = false;
    p.play();
  });

  const finish = useCallback(() => {
    if (finishedRef.current) return;
    finishedRef.current = true;
    onFinished();
  }, [onFinished]);

  useEffect(() => {
    // "playToEnd" is the canonical expo-video event; fall back to a hard
    // timeout in case any driver quirk swallows it. Duration is ~10s so
    // give it 12s of grace.
    const sub = player.addListener("playToEnd", finish);
    const hard = setTimeout(finish, 12_500);
    // If the player errored (rare), skip the intro rather than block the app.
    const err = player.addListener("statusChange", (e: any) => {
      if (e?.status === "error") {
        onError();
        finish();
      }
    });
    return () => {
      try { sub.remove(); } catch { /* ignore */ }
      try { err.remove(); } catch { /* ignore */ }
      clearTimeout(hard);
    };
  }, [player, finish, onError]);

  const { width, height } = Dimensions.get("window");

  return (
    <Animated.View
      style={[styles.bg, { opacity, width, height }]}
      pointerEvents="none"
      testID="crewfit-intro-animation"
    >
      <View style={StyleSheet.absoluteFill} pointerEvents="none">
        <VideoView
          player={player}
          style={StyleSheet.absoluteFill}
          contentFit="contain"
          nativeControls={false}
          allowsFullscreen={false}
          allowsPictureInPicture={false}
        />
      </View>

      {errored ? (
        // Fallback brand tile if the video engine croaks — never leaves
        // the user staring at black.
        <View style={styles.fallback} pointerEvents="none">
          <Text style={styles.fallbackBrand}>CREW<Text style={{ color: theme.color.brand }}>FIT</Text></Text>
        </View>
      ) : null}
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  bg: {
    position: "absolute",
    left: 0, top: 0,
    backgroundColor: "#000",
    // Ensure the intro sits above every navigator layer.
    ...Platform.select({
      ios: { zIndex: 10_000 },
      android: { elevation: 100 },
      web: { zIndex: 10_000 } as any,
      default: {},
    }),
  },
  fallback: {
    ...StyleSheet.absoluteFillObject,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#000",
  },
  fallbackBrand: { color: "#fff", fontSize: 34, fontWeight: "900", letterSpacing: 4 },
});

export default CrewFitIntroAnimation;
