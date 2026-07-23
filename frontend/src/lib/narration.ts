/**
 * Louis coach voice narration for the guided workout flow.
 *
 * - Uses expo-speech (works on iOS, Android, and web via SpeechSynthesis).
 * - Respects the user's Voice setting (persisted in workoutMode.ts).
 * - Every call cancels the previous utterance so cues don't stack when
 *   phases change rapidly (e.g. quick skips).
 * - All text is coach-voice — never mentions AI, bots, or generation.
 * - Never throws. Speech is a nice-to-have; app must keep working if it
 *   isn't available on the device.
 */
import { Platform } from "react-native";
import * as Speech from "expo-speech";
import { getVoiceOn } from "./workoutMode";

let lastKey = "";
let lastAt = 0;

async function shouldSpeak(): Promise<boolean> {
  try { return await getVoiceOn(); } catch { return true; }
}

/**
 * Speak text with sensible defaults for coaching cues.
 * `dedupeKey`: if provided, blocks a repeat of the same cue within 800ms
 * (protects against React double-renders / rapid phase toggles).
 */
export async function speak(text: string, opts?: { dedupeKey?: string; rate?: number; pitch?: number }): Promise<void> {
  if (!text) return;
  if (!(await shouldSpeak())) return;

  const now = Date.now();
  const key = opts?.dedupeKey || text;
  if (key === lastKey && now - lastAt < 800) return;
  lastKey = key;
  lastAt = now;

  try {
    // Stop whatever was mid-flight so the newer cue lands cleanly.
    try { Speech.stop(); } catch { /* ignore */ }
    Speech.speak(text, {
      language: Platform.OS === "ios" ? "en-GB" : "en-US",
      rate: opts?.rate ?? 1.0,
      pitch: opts?.pitch ?? 1.0,
      // No completion callback — we're fire-and-forget on purpose.
    });
  } catch { /* silent */ }
}

/** Immediately halt any in-progress narration (used when unmounting). */
export function stopNarration(): void {
  try { Speech.stop(); } catch { /* ignore */ }
  lastKey = "";
  lastAt = 0;
}

/* ------------------------------------------------------------------ */
/*  Cue helpers — build the coach line, then speak                    */
/* ------------------------------------------------------------------ */

export function narrateWorkStart(exerciseName: string, setIdx: number, totalSets: number, targetReps: number, isCardio: boolean): void {
  if (!exerciseName) return;
  const name = cleanName(exerciseName);
  const line = isCardio
    ? `Set ${setIdx} of ${totalSets}. ${name}.`
    : `Set ${setIdx} of ${totalSets}. ${name}. ${targetReps || ""} reps.`.trim();
  speak(line, { dedupeKey: `work:${exerciseName}:${setIdx}` });
}

export function narrateWarmup(moveName: string, index: number, total: number): void {
  if (!moveName) return;
  speak(`Warm up ${index} of ${total}. ${cleanName(moveName)}.`, { dedupeKey: `wu:${moveName}:${index}` });
}

export function narrateRestStart(seconds: number, nextLabel?: string): void {
  const sec = Math.round(seconds);
  const base = `Rest ${sec} seconds.`;
  const line = nextLabel ? `${base} Next up, ${cleanName(nextLabel)}.` : base;
  speak(line, { dedupeKey: `rest:${sec}:${nextLabel || ""}` });
}

export function narrateRestReady(): void {
  speak("Ready. Let's go.", { dedupeKey: "rest:end" });
}

export function narrateWorkoutComplete(): void {
  speak("Workout complete. Great work.", { dedupeKey: "wo:complete" });
}

/** Announce a swap or feature — kept plain so it never sounds robotic. */
export function narrate(text: string): void {
  speak(text);
}

/* ------------------------------------------------------------------ */
/*  Utils                                                              */
/* ------------------------------------------------------------------ */

function cleanName(s: string): string {
  // Strip parentheticals & tidy whitespace so the TTS voice flows better.
  return String(s)
    .replace(/\s*\([^)]*\)\s*/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}
