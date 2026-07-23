/**
 * Cross-platform audio cue helper for the workout flow.
 *
 * - Web: Web Audio API (synth tones — small, no assets)
 * - Native (iOS/Android): pre-bundled short WAV files loaded with expo-audio.
 *   Players are created lazily and reused, and calls to play() reset the
 *   playhead so back-to-back beeps (e.g. 3-2-1) all fire.
 * - Silently no-ops if the user disabled Sound in workout settings, or if
 *   audio init fails on the device (never throws).
 */
import { Platform } from "react-native";
import { createAudioPlayer, setAudioModeAsync, type AudioPlayer } from "expo-audio";
import { getSoundOn } from "./workoutMode";

/* ------------------------------------------------------------------ */
/*  Guard                                                              */
/* ------------------------------------------------------------------ */
async function guard(): Promise<boolean> {
  try { return await getSoundOn(); } catch { return true; }
}

/* ------------------------------------------------------------------ */
/*  Web synth (unchanged)                                              */
/* ------------------------------------------------------------------ */
let ctx: AudioContext | null = null;
function getCtx(): AudioContext | null {
  if (Platform.OS !== "web") return null;
  try {
    if (!ctx) {
      const AC = (globalThis as any).AudioContext || (globalThis as any).webkitAudioContext;
      if (!AC) return null;
      ctx = new AC();
    }
    if (ctx && ctx.state === "suspended") ctx.resume().catch(() => {});
    return ctx;
  } catch { return null; }
}

function beep(frequency: number, durationMs: number, volume = 0.15, type: OscillatorType = "sine"): void {
  const c = getCtx();
  if (!c) return;
  try {
    const osc = c.createOscillator();
    const gain = c.createGain();
    osc.type = type;
    osc.frequency.value = frequency;
    const now = c.currentTime;
    gain.gain.setValueAtTime(0, now);
    gain.gain.linearRampToValueAtTime(volume, now + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + durationMs / 1000);
    osc.connect(gain).connect(c.destination);
    osc.start(now);
    osc.stop(now + durationMs / 1000 + 0.02);
  } catch { /* silent */ }
}

/* ------------------------------------------------------------------ */
/*  Native players (expo-audio)                                        */
/* ------------------------------------------------------------------ */
type SoundKey = "tick" | "chime" | "restStart" | "success";

// Static requires so Metro bundles the assets.
const SOURCES = {
  tick: require("../../assets/audio/tick.wav"),
  chime: require("../../assets/audio/chime.wav"),
  restStart: require("../../assets/audio/rest_start.wav"),
  success: require("../../assets/audio/success.wav"),
} as const;

const players: Partial<Record<SoundKey, AudioPlayer>> = {};
let audioModeConfigured = false;

async function configureAudioModeOnce(): Promise<void> {
  if (audioModeConfigured) return;
  audioModeConfigured = true;
  try {
    // Play through the media channel, respect the silent switch. Workouts
    // are foreground-only for the audio cues in v1 — no background playback.
    await setAudioModeAsync({
      playsInSilentMode: false,
      shouldPlayInBackground: false,
      interruptionMode: "mixWithOthers",
    });
  } catch { /* ignore — cues are best-effort */ }
}

function ensurePlayer(key: SoundKey): AudioPlayer | null {
  if (Platform.OS === "web") return null;
  try {
    if (!players[key]) {
      const p = createAudioPlayer(SOURCES[key] as unknown as number);
      // Keep the player around; we reuse it on every cue.
      players[key] = p;
    }
    return players[key] || null;
  } catch { return null; }
}

function playNative(key: SoundKey): void {
  configureAudioModeOnce();
  const p = ensurePlayer(key);
  if (!p) return;
  try {
    // Reset playhead so consecutive triggers (e.g. 3-2-1) all fire.
    try { p.seekTo(0); } catch { /* not always available before load */ }
    p.play();
  } catch { /* silent */ }
}

/* ------------------------------------------------------------------ */
/*  Public API                                                         */
/* ------------------------------------------------------------------ */

/** Soft, low chime — "rest starting". */
export async function playRestStart(): Promise<void> {
  if (!(await guard())) return;
  if (Platform.OS === "web") beep(440, 120);
  else playNative("restStart");
}

/** Short high pip — used for 3, 2, 1 countdown. */
export async function playCountdownTick(): Promise<void> {
  if (!(await guard())) return;
  if (Platform.OS === "web") beep(660, 80, 0.18);
  else playNative("tick");
}

/** Bright ready chime — "next set ready". */
export async function playRestEnd(): Promise<void> {
  if (!(await guard())) return;
  if (Platform.OS === "web") {
    beep(880, 90, 0.2);
    setTimeout(() => beep(1108, 160, 0.2), 100);
  } else {
    playNative("chime");
  }
}

/** Warm triumphant tone — workout complete. */
export async function playWorkoutComplete(): Promise<void> {
  if (!(await guard())) return;
  if (Platform.OS === "web") {
    beep(523, 140, 0.22);
    setTimeout(() => beep(659, 140, 0.22), 130);
    setTimeout(() => beep(784, 260, 0.22), 260);
  } else {
    playNative("success");
  }
}

/**
 * Pre-warm players on native so the first cue doesn't have any startup lag.
 * Safe to call multiple times — no-ops after the first success.
 */
export function warmupSoundEngine(): void {
  if (Platform.OS === "web") { getCtx(); return; }
  configureAudioModeOnce();
  ensurePlayer("tick");
  ensurePlayer("chime");
  ensurePlayer("restStart");
  ensurePlayer("success");
}
