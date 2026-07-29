/**
 * CrewFitIntroAnimation
 *
 * Root startup gate for the CrewFit intro video.
 *
 *   App starts
 *      ↓
 *   Resolve whether the intro should play (12-hour rule)
 *      ↓
 *   If YES  → render ONLY the intro video; children are NOT mounted
 *              ↓
 *          video finishes
 *              ↓
 *          intro fully unmounts → children mount for the first time
 *   If NO   → children mount immediately
 *
 * Contract
 *   - The startup video and the main CrewFit app never coexist in the
 *     React tree. There is no overlay, no crossfade, no children rendered
 *     behind the video. Media isolation is structural.
 *   - The intro asset is bundled locally.
 *   - The intro's own audio (if the file contains any) plays natively.
 *   - The intro plays once. No loop. No native controls.
 *   - The 12-hour cooldown is stored locally on-device only.
 *   - A hard safety fallback (video error, or watchdog timeout) always
 *     hands control back to the main app so a broken video can never
 *     block access.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { View, StyleSheet, Dimensions } from "react-native";
import { VideoView, useVideoPlayer } from "expo-video";
import AsyncStorage from "@react-native-async-storage/async-storage";

// Asset — bundled at build-time. Keep the require at module scope; the
// asset registration happens once and cannot instantiate a player by
// itself.
const INTRO_SOURCE = require("@/assets/louis/crewfit-startup-minimalist-v2.mp4");

// Local-storage key for the 12-hour rule.
const KEY_LAST = "crewfit_intro_last_played_at";
const TWELVE_HOURS_MS = 12 * 60 * 60 * 1000;

// Hard watchdog: even if the video never emits playToEnd (driver quirk,
// codec issue, etc.) we hand control to the main app after this many ms.
// Intro is ~10s long; give it 5 seconds of headroom.
const HARD_WATCHDOG_MS = 15_000;

// Module-level flag: prevents the intro from firing twice in the same JS
// runtime. A background → foreground return doesn't create a new runtime,
// so this flag persists across it. A real cold launch (process killed)
// resets it because the module is re-evaluated.
let playedInThisSession = false;

/** Decide whether the intro should play on this launch. */
async function shouldPlayIntro(): Promise<boolean> {
  if (playedInThisSession) return false;
  try {
    const last = await AsyncStorage.getItem(KEY_LAST);
    if (!last) return true;                              // first ever launch
    const ts = Date.parse(last);
    if (isNaN(ts)) return true;                          // corrupt value
    return (Date.now() - ts) >= TWELVE_HOURS_MS;         // 12h cooldown
  } catch {
    // Storage unavailable — err on the side of showing the intro once.
    return true;
  }
}

/** Persist the completion timestamp. Fire-and-forget. */
function stampPlayed(): void {
  AsyncStorage.setItem(KEY_LAST, new Date().toISOString()).catch(() => {});
}

type Phase = "undecided" | "playing" | "done";

export function CrewFitIntroAnimation({ children }: { children: React.ReactNode }) {
  const [phase, setPhase] = useState<Phase>("undecided");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const play = await shouldPlayIntro();
      if (cancelled) return;
      if (play) {
        playedInThisSession = true;
        setPhase("playing");
      } else {
        setPhase("done");
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const handleFinished = useCallback(() => {
    stampPlayed();
    setPhase("done");
  }, []);

  // Undecided — plain black tile while AsyncStorage resolves. Children are
  // deliberately NOT mounted here so the app cannot flash underneath.
  if (phase === "undecided") {
    return <View style={styles.black} />;
  }

  // Playing — ONLY the intro exists in the tree. No Stack, no Welcome,
  // no Louis. Structurally impossible for another player to coexist.
  if (phase === "playing") {
    return <IntroPlayer onFinished={handleFinished} />;
  }

  // Done — main app mounts here for the first (and only) time.
  return <>{children}</>;
}

/* -------------------------------------------------------------------------- */
/*  IntroPlayer                                                               */
/*                                                                            */
/*  The video player is created inside this component, which only exists     */
/*  while phase === "playing". When it unmounts, expo-video releases the     */
/*  underlying native player (AVPlayer on iOS, ExoPlayer on Android).        */
/* -------------------------------------------------------------------------- */
function IntroPlayer({ onFinished }: { onFinished: () => void }) {
  const finishedRef = useRef(false);

  const player = useVideoPlayer(INTRO_SOURCE, (p) => {
    p.loop = false;
    p.play();
  });

  const finish = useCallback(() => {
    if (finishedRef.current) return;
    finishedRef.current = true;
    try { player.pause(); } catch { /* ignore */ }
    onFinished();
  }, [player, onFinished]);

  useEffect(() => {
    // Primary completion signal.
    const endSub = player.addListener("playToEnd", finish);
    // Safety fallback: if the video errors, don't block the app.
    const statusSub = player.addListener("statusChange", (e: any) => {
      if (e?.status === "error") finish();
    });
    // Hard watchdog: guaranteed exit even if all events are swallowed.
    const watchdog = setTimeout(finish, HARD_WATCHDOG_MS);
    return () => {
      try { endSub.remove(); } catch { /* ignore */ }
      try { statusSub.remove(); } catch { /* ignore */ }
      clearTimeout(watchdog);
    };
  }, [player, finish]);

  const { width, height } = Dimensions.get("window");

  return (
    <View style={[styles.black, { width, height }]}>
      <VideoView
        player={player}
        style={StyleSheet.absoluteFill}
        contentFit="contain"
        nativeControls={false}
        allowsFullscreen={false}
        allowsPictureInPicture={false}
        // Android-only: force a TextureView-backed surface for the startup
        // player. expo-video's default on Android is SurfaceView, which is
        // known to cause overlapping-video rendering artefacts because a
        // SurfaceView punches a hole through the view hierarchy — content
        // rendered above it can be visually retained/leaked from a
        // previous SurfaceView allocation. TextureView renders into the
        // regular hardware-accelerated view layer, so no hole punching
        // occurs. iOS ignores this prop.
        surfaceType="textureView"
      />
    </View>
  );
}

const styles = StyleSheet.create({
  black: { flex: 1, backgroundColor: "#000" },
});

export default CrewFitIntroAnimation;
