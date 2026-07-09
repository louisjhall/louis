/**
 * Cross-platform lightweight audio cue helper.
 * Uses Web Audio API on web (Expo dev preview + real web builds).
 * On native, falls back to a haptic-only cue (soft chime not shipped in v1).
 * Never throws — respects the user's Sound setting.
 */
import { Platform } from "react-native";
import { getSoundOn } from "./workoutMode";

// Reusable AudioContext on web
let ctx: AudioContext | null = null;
function getCtx(): AudioContext | null {
  if (Platform.OS !== "web") return null;
  try {
    if (!ctx) {
      const AC = (globalThis as any).AudioContext || (globalThis as any).webkitAudioContext;
      if (!AC) return null;
      ctx = new AC();
    }
    // Resume if browser paused it (autoplay policy)
    if (ctx && ctx.state === "suspended") { ctx.resume().catch(() => {}); }
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
    // Envelope: quick attack, gentle release — feels premium, not annoying
    const now = c.currentTime;
    gain.gain.setValueAtTime(0, now);
    gain.gain.linearRampToValueAtTime(volume, now + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + durationMs / 1000);
    osc.connect(gain).connect(c.destination);
    osc.start(now);
    osc.stop(now + durationMs / 1000 + 0.02);
  } catch { /* silent */ }
}

async function guard(): Promise<boolean> {
  try { return await getSoundOn(); } catch { return true; }
}

/** Soft, low chime — "rest starting". */
export async function playRestStart(): Promise<void> {
  if (!(await guard())) return;
  beep(440, 120);
}

/** Short high pip — used for 3, 2, 1 countdown. */
export async function playCountdownTick(): Promise<void> {
  if (!(await guard())) return;
  beep(660, 80, 0.18);
}

/** Bright ready chime — "next set ready". */
export async function playRestEnd(): Promise<void> {
  if (!(await guard())) return;
  beep(880, 90, 0.2);
  setTimeout(() => beep(1108, 160, 0.2), 100);
}

/** Warm triumphant tone — workout complete. */
export async function playWorkoutComplete(): Promise<void> {
  if (!(await guard())) return;
  beep(523, 140, 0.22);      // C5
  setTimeout(() => beep(659, 140, 0.22), 130); // E5
  setTimeout(() => beep(784, 260, 0.22), 260); // G5
}
