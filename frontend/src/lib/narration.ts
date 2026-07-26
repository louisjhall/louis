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
 *
 * Iter 103 — Voice = British male ("Louis voice").
 *   On first call we enumerate the device's TTS voices and pick the best
 *   available en-GB male. Selection is cached for the app lifetime. Order
 *   of preference:
 *     iOS   → Daniel (com.apple.voice.compact.en-GB.Daniel)
 *             → Arthur / Oliver / any en-GB voice tagged male
 *             → any en-GB voice (fallback)
 *     Android / Web → any voice with language starting "en-GB" whose name
 *             matches known male markers, else any en-GB, else default.
 */
import { Platform } from "react-native";
import * as Speech from "expo-speech";
import { getVoiceOn } from "./workoutMode";

let lastKey = "";
let lastAt = 0;

// Cached British-male voice identifier (or null if none found / not looked
// up yet). Lookup is triggered lazily on the first speak() call.
let selectedVoiceId: string | null | undefined = undefined;

async function shouldSpeak(): Promise<boolean> {
  try { return await getVoiceOn(); } catch { return true; }
}

/** Preference order for iOS voice identifiers (most desirable first). */
const IOS_PREFERRED_IDS = [
  "com.apple.voice.enhanced.en-GB.Daniel",     // Daniel Enhanced (best UK male)
  "com.apple.voice.compact.en-GB.Daniel",      // Daniel Compact
  "com.apple.ttsbundle.Daniel-compact",        // legacy id for Daniel
  "com.apple.voice.enhanced.en-GB.Oliver",
  "com.apple.voice.compact.en-GB.Oliver",
  "com.apple.voice.enhanced.en-GB.Arthur",
  "com.apple.voice.compact.en-GB.Arthur",
];

/** Substrings that STRONGLY suggest a male en-GB voice (Android / Web / iOS fallback). */
const MALE_NAME_MARKERS = [
  "daniel", "oliver", "arthur", "george", "james", "harry",
  "male", "-male", "_male", "man",
];

/** Substrings that suggest a FEMALE voice — we skip these when picking Louis. */
const FEMALE_NAME_MARKERS = [
  "kate", "serena", "martha", "susan", "female", "-female", "_female", "woman",
  "victoria", "moira", "tessa", "fiona",
];

function isEnGB(v: Speech.Voice): boolean {
  const lang = (v.language || "").toLowerCase();
  return lang.startsWith("en-gb") || lang.startsWith("en_gb");
}

function looksMale(v: Speech.Voice): boolean {
  const s = `${v.identifier} ${v.name || ""}`.toLowerCase();
  if (FEMALE_NAME_MARKERS.some((m) => s.includes(m))) return false;
  return MALE_NAME_MARKERS.some((m) => s.includes(m));
}

async function pickVoice(): Promise<string | null> {
  try {
    const voices = await Speech.getAvailableVoicesAsync();
    if (!voices || voices.length === 0) return null;

    // 1. On iOS, prefer known Daniel/Oliver/Arthur identifiers explicitly.
    if (Platform.OS === "ios") {
      for (const pref of IOS_PREFERRED_IDS) {
        const hit = voices.find((v) => v.identifier === pref);
        if (hit) return hit.identifier;
      }
    }

    // 2. Any en-GB voice with a clear male marker in identifier or name.
    const gbMale = voices.find((v) => isEnGB(v) && looksMale(v));
    if (gbMale) return gbMale.identifier;

    // 3. Any en-GB voice that isn't clearly female — most iOS/Android en-GB
    //    default voices are male-ish.
    const gbNonFemale = voices.find((v) => {
      const s = `${v.identifier} ${v.name || ""}`.toLowerCase();
      return isEnGB(v) && !FEMALE_NAME_MARKERS.some((m) => s.includes(m));
    });
    if (gbNonFemale) return gbNonFemale.identifier;

    // 4. Any en-GB voice at all.
    const anyGB = voices.find(isEnGB);
    if (anyGB) return anyGB.identifier;

    return null;
  } catch {
    return null;
  }
}

async function ensureVoicePicked(): Promise<void> {
  if (selectedVoiceId !== undefined) return;
  selectedVoiceId = await pickVoice();
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
    // Warm up the picked voice on the first call — done lazily to avoid
    // touching the TTS engine before it's needed.
    await ensureVoicePicked();

    // Stop whatever was mid-flight so the newer cue lands cleanly.
    try { Speech.stop(); } catch { /* ignore */ }

    const speakOpts: Speech.SpeechOptions = {
      language: "en-GB",
      rate: opts?.rate ?? 1.0,
      // Slightly lower default pitch — matches a warmer British male tone
      // and avoids the higher-pitched "assistant" cadence some default
      // voices ship with.
      pitch: opts?.pitch ?? 0.95,
    };
    if (selectedVoiceId) {
      speakOpts.voice = selectedVoiceId;
    }
    Speech.speak(text, speakOpts);
  } catch { /* silent */ }
}

/** Immediately halt any in-progress narration (used when unmounting). */
export function stopNarration(): void {
  try { Speech.stop(); } catch { /* ignore */ }
  lastKey = "";
  lastAt = 0;
}

/**
 * Force a re-pick of the voice — useful if the user changes the device's
 * default language mid-session, or if we want to expose a "try again"
 * button in settings.
 */
export function resetVoiceSelection(): void {
  selectedVoiceId = undefined;
}

/** Exposed for a debug/diagnostic tap in settings (which voice are we using?). */
export async function getSelectedVoiceInfo(): Promise<{ id: string | null; all: Speech.Voice[] }> {
  await ensureVoicePicked();
  try {
    const all = await Speech.getAvailableVoicesAsync();
    return { id: selectedVoiceId || null, all: all || [] };
  } catch {
    return { id: selectedVoiceId || null, all: [] };
  }
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
