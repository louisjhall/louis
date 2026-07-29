/**
 * CrewFitIntroAnimation — Iter 125 (structural startup gate)
 *
 * TRUE STARTUP GATE — this component does NOT overlay the intro on top of the
 * running app. During the intro, the main app tree ({children}) is NOT
 * mounted at all. This makes it structurally impossible for the CrewFit
 * startup video (intro.mp4) and the Coach Louis welcome video (welcome.mp4)
 * to play at the same time.
 *
 *   State machine
 *   ─────────────
 *     undecided       → resolving the 12-hour cooldown from AsyncStorage.
 *                       Renders a black tile only. Children NOT mounted.
 *     showing_intro   → renders ONLY the intro player. Children NOT mounted.
 *     done            → renders ONLY {children}. Intro player unmounted +
 *                       disposed.
 *
 * When it fires
 *   - First-ever cold launch: play once, stamp timestamp on completion.
 *   - Cold launch 12+ hours after the last successful play: play once.
 *   - Cold launch inside the 12-hour window: skip entirely, go straight to
 *     the normal app.
 *   - `queueIntroForNextMount("onboarded")` bypasses the cooldown once.
 *
 * When it does NOT fire
 *   - Same-session foreground return (module-level flag).
 *   - Tab / route changes.
 *
 * Persistence
 *   AsyncStorage keys (local device only — no server field):
 *     crewfit_intro_last_played_at   ISO string of the last completed intro
 *     crewfit_intro_pending_reason   "cold_launch" | "onboarded" | undefined
 *
 * Behaviour of the intro itself
 *   - Silent (intro.mp4 has no audio track; also player.muted = true).
 *   - No native controls, no fullscreen, no PiP, no loop.
 *   - Plays once, then unmounts (player disposed by React GC).
 *   - 12.5s watchdog force-completes if `playToEnd` is swallowed.
 *   - On playback error, falls back to the brand tile and moves on.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, Dimensions, Platform,
} from "react-native";
import { VideoView, useVideoPlayer } from "expo-video";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { theme } from "@/src/lib/theme";

const INTRO_SOURCE = require("@/assets/louis/crewfit-startup-minimalist-v2.mp4");
const KEY_LAST = "crewfit_intro_last_played_at";
const KEY_PENDING = "crewfit_intro_pending_reason";
const TWELVE_HOURS_MS = 12 * 60 * 60 * 1000;

// Module-level flag so we NEVER play the intro twice in the same JS runtime
// (i.e. same app session — different from a real cold launch). This survives
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

type Phase = "undecided" | "showing_intro" | "done";

export function CrewFitIntroAnimation({ children }: { children: React.ReactNode }) {
  const [phase, setPhase] = useState<Phase>("undecided");

  // Decide on first mount whether to show the intro. The main app is NOT
  // mounted while we're resolving this. This is the whole point of the gate.
  useEffect(() => {
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

  // Called when the intro finishes (either via playToEnd, watchdog, or error).
  // We stamp the timestamp and transition to "done", which unmounts the
  // intro player and mounts the main app for the first time.
  const handleIntroFinished = useCallback(() => {
    // Fire-and-forget — the transition should not wait on storage IO.
    stampPlayed();
    setPhase("done");
  }, []);

  // ── UNDECIDED ────────────────────────────────────────────────────────────
  // Very brief black tile while AsyncStorage resolves. We deliberately do
  // NOT render {children} here to prevent the "flash of underlying app"
  // problem before the decision is made.
  if (phase === "undecided") {
    return <View style={styles.blackFill} />;
  }

  // ── SHOWING INTRO ────────────────────────────────────────────────────────
  // ONLY the intro player is mounted. {children} is not in the tree at all,
  // so no Louis welcome player, no /welcome screen, no home dashboard can
  // exist concurrently — media isolation is structural, not defensive.
  if (phase === "showing_intro") {
    return <IntroGate onFinished={handleIntroFinished} />;
  }

  // ── DONE ─────────────────────────────────────────────────────────────────
  // The main CrewFit app mounts here for the first time. The intro player
  // has been unmounted; its native resources are released by expo-video's
  // SharedObject GC (see expo-modules-core docs).
  return <>{children}</>;
}

/* --------------------------- intro gate content --------------------------- */
function IntroGate({ onFinished }: { onFinished: () => void }) {
  const finishedRef = useRef(false);
  const [errored, setErrored] = useState(false);

  // Iter 125 — Lifecycle logs for native diagnostic. Use [STARTUP_VIDEO] tag.
  useEffect(() => {
    console.log("[STARTUP_VIDEO] component mount");
    return () => { console.log("[STARTUP_VIDEO] component unmounted"); };
  }, []);

  // Player is created here — this component only exists in phase
  // "showing_intro", so the player is guaranteed not to overlap with
  // welcome.mp4's player.
  const player = useVideoPlayer(INTRO_SOURCE, (p) => {
    console.log("[STARTUP_VIDEO] player created");
    p.loop = false;
    p.muted = true;         // belt-and-braces; the file has no audio track
    p.play();
    console.log("[STARTUP_VIDEO] play");
  });

  const finish = useCallback(() => {
    if (finishedRef.current) return;
    finishedRef.current = true;
    console.log("[STARTUP_VIDEO] finish");
    // Best-effort stop; the player will be unmounted immediately after.
    try { player.pause(); } catch { /* ignore */ }
    onFinished();
  }, [player, onFinished]);

  useEffect(() => {
    // `playToEnd` is the canonical expo-video event; fall back to a hard
    // timeout in case any driver quirk swallows it. Intro is ~10s so give
    // it 12s of grace.
    const sub = player.addListener("playToEnd", finish);
    const hard = setTimeout(finish, 12_500);
    // On player error, skip the intro rather than block the app.
    const errSub = player.addListener("statusChange", (e: any) => {
      if (e?.status === "error") {
        console.log("[STARTUP_VIDEO] statusChange:error");
        setErrored(true);
        finish();
      }
    });
    return () => {
      try { sub.remove(); } catch { /* ignore */ }
      try { errSub.remove(); } catch { /* ignore */ }
      clearTimeout(hard);
    };
  }, [player, finish]);

  const { width, height } = Dimensions.get("window");

  return (
    <View style={[styles.bg, { width, height }]} testID="crewfit-intro-animation">
      <VideoViewLogged
        player={player}
        style={StyleSheet.absoluteFill}
        contentFit="contain"
        nativeControls={false}
        allowsFullscreen={false}
        allowsPictureInPicture={false}
      />
      {errored ? (
        <View style={styles.fallback} pointerEvents="none">
          <Text style={styles.fallbackBrand}>
            CREW<Text style={{ color: theme.color.brand }}>FIT</Text>
          </Text>
        </View>
      ) : null}
    </View>
  );
}

/** Wrapper that logs the native VideoView mount/unmount lifecycle. */
function VideoViewLogged(props: React.ComponentProps<typeof VideoView>) {
  useEffect(() => {
    console.log("[STARTUP_VIDEO] VideoView mounted");
    return () => { console.log("[STARTUP_VIDEO] VideoView unmounted"); };
  }, []);
  return <VideoView {...props} />;
}

const styles = StyleSheet.create({
  blackFill: {
    flex: 1,
    backgroundColor: "#000",
  },
  bg: {
    flex: 1,
    backgroundColor: "#000",
    // Belt-and-braces: keep the intro above any accidental sibling render.
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
