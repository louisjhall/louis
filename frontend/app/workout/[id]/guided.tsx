/**
 * Atlas Guided Flow — step-by-step follow-along player.
 * Reuses the SAME workout data + logging endpoints as Manual Mode.
 *
 * Flow: warm-up → exercise 1 (set 1 → rest → set 2 → rest → set 3) → next exercise → complete.
 * Every set is logged to /workouts/{id}/sets, same as Manual Mode.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput,
  ActivityIndicator, Image, Modal, Vibration, Dimensions, Alert,
} from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useExerciseMedia } from "@/src/lib/useExerciseMedia";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { ExerciseVideoPlayer } from "@/src/components/ExerciseVideoPlayer";
import { WorkoutMediaCarousel } from "@/src/components/WorkoutMediaCarousel";
import { PostWorkoutRatingSheet } from "@/src/components/PostWorkoutRatingSheet";
import { RestTimer } from "@/src/components/RestTimer";
import {
  getAutoContinue, getSoundOn, setAutoContinue as saveAutoContinue,
  getAutoRest, getVoiceOn, setVoiceOn as saveVoiceOn,
  isCardioExercise, isTimeBased, extractTargetSeconds, isTimerLocked,
} from "@/src/lib/workoutMode";
import { hapticSuccess } from "@/src/lib/haptics";
import { playWorkoutComplete, playCountdownTick, warmupSoundEngine } from "@/src/lib/sounds";
import {
  narrateWarmup, narrateWorkStart, narrateWorkoutComplete, stopNarration,
} from "@/src/lib/narration";

const { width: SCREEN_W } = Dimensions.get("window");

type Phase = "loading" | "warmup" | "work" | "rest" | "complete";
type LogMode = "asking" | "log" | "autopilot";

function fmtMMSS(sec: number): string {
  const m = Math.max(0, Math.floor(sec / 60));
  const s = Math.max(0, sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

/**
 * Autopilot / Flow Mode — compute how long each work interval should run for.
 * - Cardio / timed exercises: honour explicit `duration_sec` / `work_sec` on
 *   the exercise. Cardio uses a wide clamp (10s..3h) so long runs / rides
 *   aren't chopped down; timed strength holds share the same wide clamp.
 * - Weighted / bodyweight sets: rough tempo of ~3s per rep, clamped 20-90s
 *   so a 5-rep heavy set doesn't fly by and a 20-rep set doesn't drag on.
 *
 * Iter189r bug fix: previously clamped explicit durations to 600s (10 min)
 * unconditionally — a 30-minute Easy Run timer opened at 10:00 instead of
 * 30:00. The clamp is now cardio-aware.
 */
function autopilotWorkSeconds(ex: any, targetReps: number, isCardio: boolean): number {
  const explicit = parseInt(String(ex?.work_sec || ex?.duration_sec || 0), 10);
  if (explicit && explicit > 0) {
    // Cardio / long holds → 3h ceiling (long runs, treadmill sessions,
    // extended rows). Strength holds still cap at 10 min for safety.
    const ceiling = isCardio ? 10800 : 600;
    return Math.max(10, Math.min(ceiling, explicit));
  }
  if (isCardio) return 60;
  const est = Math.round((targetReps || 10) * 3);
  return Math.max(20, Math.min(90, est));
}

function isMobilityLike(ex: any): boolean {
// Iter 94t (Phase 2) — Mobility / stretch exercises deserve slower image
// auto-scroll (5–7s) so clients can actually study each position.
  if (!ex) return false;
  const hay = `${ex.name || ""} ${ex.category || ""} ${ex.section || ""}`.toLowerCase();
  return /\b(mobility|stretch|flow|breath|activation|cool.?down|warm.?up|rock|rotation|open.?book|hip.?flex|thoracic|foam|glute.?bridge|cat.?cow)\b/.test(hay);
}

// Iter189q · Format the cardio target header. Cardio must NEVER show a
// bare rep count — always show a duration or a distance/pace hint.
function _fmtCardioTarget(ex: any): string {
  const secs = extractTargetSeconds(ex);
  if (secs && secs > 0) {
    if (secs >= 60) {
      const m = Math.floor(secs / 60);
      const s = secs % 60;
      return s === 0 ? `${m} min` : `${m}:${String(s).padStart(2, "0")}`;
    }
    return `${secs}s`;
  }
  // No duration hint? Show distance if present, else a generic label.
  const dist = ex?.distance_km || ex?.distance_m;
  if (dist) {
    return ex?.distance_km ? `${ex.distance_km} km` : `${ex.distance_m} m`;
  }
  return "steady effort";
}

// Iter189q · Returns true when the reps string is a genuine cardio hint
// (pace/zone/RPE/distance/time) rather than a bare rep count. Guards the
// cardio-meta line so we never render "40" — which reads as "40 reps".
function _looksLikeCardioHint(reps: any): boolean {
  const s = String(reps || "").trim();
  if (!s) return false;
  // Bare integer or bare rep range → NOT a cardio hint, skip it.
  if (/^\d+(-\d+)?$/.test(s)) return false;
  // Otherwise assume it's coaching text (Zone 2, MP+90s, 5:30/km, RPE 7…)
  return true;
}



/**
 * Iter188 · `isTimeBased` and `extractTargetSeconds` moved to
 * `src/lib/workoutMode.ts` so play.tsx (Manual mode) and guided.tsx
 * (Guided mode) share ONE definition of "this exercise is a timer".
 * Previously play.tsx had no time-based check at all — side plank / wall
 * sit / farmer's carry all showed kg + reps fields. Fixed in Iter188.
 */

function parseTargetReps(ex: any): number {
  const r = String(ex?.reps || "").trim();
  const first = r.split(/[-\s]/)[0];
  const n = parseInt(first, 10);
  return isNaN(n) ? 10 : n;
}

/**
 * Iter 115 — Adapt V2 workouts (source="engine_v2") for the guided flow.
 *
 * V2 running / cycling / mobility workouts arrive with:
 *   - warmup:   null (blocks[0] holds the warmup cue + drills)
 *   - exercises: [] (V2 cardio has no gym-style exercise list)
 *   - blocks[]: warmup + main + cooldown (+ segments) with hr_zone /
 *               pace_target / duration_min / cue / drills
 *
 * The guided flow reads `workout.warmup` (drill list) and iterates
 * `workout.exercises[]` — so without this adapter it either skips warmup
 * entirely OR has zero exercises to run (guided screen stalls). We flatten
 * blocks into guided-friendly shape without mutating the manual view path.
 */
function adaptWorkoutForGuided(w: any): any {
  if (!w) return w;
  const hasExercises = Array.isArray(w.exercises) && w.exercises.length > 0;
  const hasWarmup = Array.isArray(w.warmup) && w.warmup.length > 0;
  const blocks: any[] = Array.isArray(w.blocks) ? w.blocks : [];
  const isV2 = w.source === "engine_v2" || w.v2_placement === true;
  if (!isV2 && (hasExercises || hasWarmup)) return w; // legacy shape — untouched

  const out: any = { ...w };

  // 1) Warmup: extract drills from the first "warmup"-typed block.
  if (!hasWarmup) {
    const wuBlock = blocks.find((b) => String(b.type || "").toLowerCase() === "warmup");
    const drills = Array.isArray(wuBlock?.drills) ? wuBlock.drills : [];
    if (drills.length > 0) {
      out.warmup = drills.map((d: any) => ({
        name: d.name || "Drill",
        duration_sec: d.duration_sec || d.duration || 30,
        cue: d.cue,
        reps: d.reps,
        rest_sec: d.rest_sec,
      }));
    } else if (wuBlock?.duration_min) {
      // Fall back to a single "Warm-up" block when no drills exist
      out.warmup = [{
        name: "Warm-up",
        duration_sec: (wuBlock.duration_min || 5) * 60,
        cue: wuBlock.cue || "",
      }];
    }
  }

  // 2) Exercises: for cardio / mobility V2 blocks, expand non-warmup blocks
  //    into cardio-style "exercises" so the guided flow has something to
  //    run. Each block becomes a single-set timed exercise with sensible
  //    metadata for the meta line + haptics.
  if (!hasExercises && blocks.length > 0) {
    const nonWarmup = blocks.filter(
      (b) => String(b.type || "").toLowerCase() !== "warmup"
    );
    if (nonWarmup.length > 0) {
      out.exercises = nonWarmup.map((b: any) => {
        const label = String(b.type || "block")
          .replace(/_/g, " ")
          .replace(/\b\w/g, (c: string) => c.toUpperCase());
        const secs = (b.duration_min || 0) * 60 || (b.work_sec || 60);
        const bits: string[] = [];
        if (b.hr_zone)       bits.push(String(b.hr_zone).toUpperCase());
        if (b.pace_target)   bits.push(String(b.pace_target));
        if (b.power_target)  bits.push(String(b.power_target));
        if (b.cadence)       bits.push(`cad ${b.cadence}`);
        if (b.effort_rpe)    bits.push(`RPE ${b.effort_rpe}`);
        const notes = [b.cue, b.fuel_cue ? `Fuel: ${b.fuel_cue}` : ""]
          .filter(Boolean).join("  ·  ");
        return {
          name: label,
          exercise_name_display: label,
          sets: 1,
          reps: bits.join(" · ") || `${b.duration_min || 1}min`,
          duration_sec: secs,
          rest_sec: 15,           // short micro-pause between blocks
          logging_type: "cardio", // triggers autopilot cardio timer path
          notes,
          category: "cardio",
        };
      });
    }
  }

  return out;
}

export default function GuidedFlow() {
  const { id, variant: variantParam } = useLocalSearchParams<{ id: string; variant?: string }>();
  const router = useRouter();
  const [workout, setWorkout] = useState<any>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [warmupIdx, setWarmupIdx] = useState(0);
  const [exIdx, setExIdx] = useState(0);
  const [setIdx, setSetIdx] = useState(1);
  const [paused, setPaused] = useState(false);
  const [warmupTimer, setWarmupTimer] = useState(0);
  const [autoCont, setAutoCont] = useState(true);
  const [autoRest, setAutoRest] = useState(true);
  const [soundOn, setSoundOn] = useState(true);
  const [voiceOn, setVoiceOnState] = useState(true);
  // Iter 95i — Flow / Autopilot mode. Client picks at workout start:
  //   log       → track lifts, tap COMPLETE SET each time (legacy behaviour)
  //   autopilot → hands-free class experience, work timer + auto-rest, no tapping
  const [logMode, setLogMode] = useState<LogMode>("asking");
  const [workTimer, setWorkTimer] = useState(0);
  const [previousLabel, setPreviousLabel] = useState<string>("");
  const [howToOpen, setHowToOpen] = useState(false);
  // Iter 161 · When the "HOW TO" button is tapped from the WARM-UP phase we
  // need the sheet to show the *warmup drill*, not the (upcoming) main
  // exercise. Track the exercise the sheet was opened against + its content.
  const [howToTargetEx, setHowToTargetEx] = useState<any>(null);
  const [howToTargetContent, setHowToTargetContent] = useState<any>(null);
  // Iter 94t (Phase 2) — When the client opens the demo/how-to sheet during
  // a work set, we auto-pause the workout so they can actually study the
  // video. On close we restore whatever paused state they were in before.
  const pausedBeforeHowTo = useRef<boolean>(false);

  // Iter189r · Hoisted currentEx (and related derivations) BEFORE the
  // `openHowTo` useCallback below so that its dep array can safely
  // evaluate `currentEx?.name` without hitting a TDZ error on first
  // render. Previously these were declared ~100 lines further down which
  // meant the guided-flow screen crashed on mount with
  // "Cannot access 'currentEx' before initialization".
  const currentEx = workout?.exercises?.[exIdx];
  // Iter189s · logging_type is the source of truth for whether this row
  // is time-locked (badge = TIME, auto-timer runs, no reps toggle).
  // `isCardioExercise` remains for sub-classification (cardio vs hold UI).
  const timerLocked = isTimerLocked(currentEx);
  const isCardio = isCardioExercise(currentEx);
  const targetSets = Math.max(1, parseInt(String(currentEx?.sets || 3), 10));
  const targetReps = parseTargetReps(currentEx);
  const restSec = Math.max(15, parseInt(String(currentEx?.rest_sec || 90), 10));
  const workSec = autopilotWorkSeconds(currentEx, targetReps, timerLocked);

  const openHowTo = useCallback(() => {
    pausedBeforeHowTo.current = paused;
    setPaused(true);
    // Snapshot the exercise the user tapped from — could be main OR warmup.
    // The sheet reads from this snapshot so it never flips mid-view.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    const target = phase === "warmup" ? (workout?.warmup?.[warmupIdx] || null) : (currentEx || null);
    setHowToTargetEx(target);
    setHowToTargetContent(null);
    if (target?.name) {
      api<any>(`/exercises/content?name=${encodeURIComponent(target.name)}`)
        .then((r) => setHowToTargetContent(r?.exercise || null))
        .catch(() => setHowToTargetContent(null));
    }
    setHowToOpen(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paused, phase, warmupIdx, currentEx?.name, workout?.warmup]);
  const closeHowTo = useCallback(() => {
    setHowToOpen(false);
    setPaused(pausedBeforeHowTo.current);
  }, []);
  const [swapOpen, setSwapOpen] = useState(false);
  const [content, setContent] = useState<any>(null);
  const [prev, setPrev] = useState<any>(null);
  const [logs, setLogs] = useState<any[]>([]);
  const [saving, setSaving] = useState(false);
  const startedAt = useRef<number>(Date.now());

  // Log form fields
  const [logWeight, setLogWeight] = useState("");
  const [logReps, setLogReps] = useState("");
  const [logRpe, setLogRpe] = useState("");
  const [logNote, setLogNote] = useState("");

  const restTick = useRef<any>(null);
  const warmupTick = useRef<any>(null);
  const workTick = useRef<any>(null);
  const restSeconds = useRef<number>(0);

  // Iter189r · Extracted so the Alternatives Swap handler can re-hydrate
  // the workout AFTER a successful swap. Previously the raw workout from
  // the swap endpoint replaced state directly, but that payload lacks the
  // exercise media hydration `GET /workouts/:id` performs — so the tile
  // went blank giving the illusion that "tapping alternatives did nothing".
  const reloadWorkout = useCallback(async () => {
    const w = await api<any>(`/workouts/${id}`);
    let wWithVariant = w;
    const vKey = String(variantParam || "").toLowerCase();
    if (vKey === "amber" || vKey === "red") {
      try {
        let variantsBlob = w?.variants;
        if (!variantsBlob || !variantsBlob.green || !variantsBlob[vKey]) {
          const r = await api<any>(`/workouts/${id}/variants`);
          variantsBlob = r?.variants || null;
        }
        const chosen = variantsBlob?.[vKey];
        if (chosen && Array.isArray(chosen.exercises) && chosen.exercises.length) {
          wWithVariant = {
            ...w,
            exercises: chosen.exercises,
            warmup: chosen.warmup || w.warmup,
            cooldown: chosen.cooldown || w.cooldown,
            _variant_key: vKey,
            _variant_label: chosen.label || null,
            _variant_intensity_note: chosen.intensity_note || null,
          };
        }
      } catch (_e) { /* fall through to base */ }
    }
    const wAdapted = adaptWorkoutForGuided(wWithVariant);
    setWorkout(wAdapted);
    return wAdapted;
  }, [id, variantParam]);

  // Load workout + settings
  useEffect(() => {
    warmupSoundEngine(); // Pre-warm native audio players so first cue has no lag.
    (async () => {
      const [, ac, ar, so, vo] = await Promise.all([
        reloadWorkout(),
        getAutoContinue(),
        getAutoRest(),
        getSoundOn(),
        getVoiceOn(),
      ]);
      setAutoCont(ac);
      setAutoRest(ar);
      setSoundOn(so);
      setVoiceOnState(vo);
      // Iter 95i — hold on the mode picker until the client chooses.
      // We still keep phase="loading" so the body doesn't flash the
      // warmup / work UI behind the modal.
      setLogMode("asking");
    })().catch(() => setLogMode("asking"));
    return () => {
      if (restTick.current) clearInterval(restTick.current);
      if (warmupTick.current) clearInterval(warmupTick.current);
      if (workTick.current) clearInterval(workTick.current);
      stopNarration();
    };
  }, [id, reloadWorkout]);

  const totalExercises = workout?.exercises?.length || 0;
  // Iter189r · currentEx / isCardio / targetSets / targetReps / restSec /
  // workSec are hoisted ~100 lines up so `openHowTo`'s useCallback dep
  // array doesn't TDZ. Only per-render values that don't feed into
  // openHowTo remain here.
  const isLastSet = setIdx >= targetSets;
  const isLastExercise = exIdx >= totalExercises - 1;
  const isAutopilot = logMode === "autopilot";

  // Fetch content + previous performance whenever exercise changes.
  // Iter189q · media resolution now runs via useExerciseMedia (below) so
  // guided flow gets the same V2 image stream that manual mode uses.
  useEffect(() => {
    if (!currentEx?.name || phase !== "work") return;
    setContent(null); setPrev(null);
    api<any>(`/exercises/content?name=${encodeURIComponent(currentEx.name)}`)
      .then((r) => setContent(r?.exercise || null)).catch(() => setContent(null));
    api<any>(`/exercises/previous?name=${encodeURIComponent(currentEx.name)}`)
      .then((r) => setPrev(r || null)).catch(() => setPrev(null));
    // Prefill inputs with previous / suggested values
    setLogWeight(""); setLogReps(String(targetReps || "")); setLogRpe(""); setLogNote("");
    // Coach voice cue for the incoming set.
    narrateWorkStart(currentEx.name, setIdx, targetSets, targetReps, isCardio);
  }, [currentEx?.name, phase, exIdx, setIdx, targetReps, targetSets, isCardio]);

  // Iter189q · Shared media hook — same fallback ladder as manual mode
  // (V2 primary_image_id → legacy custom_image → legacy coach_image).
  const mainMedia = useExerciseMedia(phase === "work" ? currentEx?.name : null);

  // Warmup timer
  useEffect(() => {
    if (phase !== "warmup" || paused) return;
    const item = workout?.warmup?.[warmupIdx];
    if (!item) return;
    const dur = Math.max(10, parseInt(String(item.duration_sec || 30), 10));
    setWarmupTimer(dur);
    // Announce the move as it kicks off.
    narrateWarmup(item.name, warmupIdx + 1, workout?.warmup?.length || 1);
    if (warmupTick.current) clearInterval(warmupTick.current);
    warmupTick.current = setInterval(() => {
      setWarmupTimer((s) => {
        // 3-2-1 audio cues on the tail end of each warm-up move
        if (s === 4) playCountdownTick();
        else if (s === 3) playCountdownTick();
        else if (s === 2) playCountdownTick();
        if (s <= 1) {
          clearInterval(warmupTick.current);
          Vibration.vibrate([0, 200, 100, 200]);
          // Auto-advance to next warmup item or first exercise
          setTimeout(() => {
            const next = warmupIdx + 1;
            if (next < (workout?.warmup?.length || 0)) {
              setWarmupIdx(next);
            } else {
              setPhase("work");
            }
          }, 400);
          return 0;
        }
        return s - 1;
      });
    }, 1000);
    return () => { if (warmupTick.current) clearInterval(warmupTick.current); };
  }, [phase, warmupIdx, paused, workout]);

  // Rest phase — kicks in via `setPhase("rest")`. The RestTimer component
  // owns its own countdown; on complete we advance.
  const startRest = useCallback((sec: number, prevLabel: string) => {
    restSeconds.current = sec;
    setPreviousLabel(prevLabel);
    setPhase("rest");
  }, []);

  // Iter 95i — Flow / Autopilot mode. Runs the strength work interval as a
  // timer so the client never has to tap anything. On zero we auto-log the
  // set (target reps) and slide straight into the RestTimer, which is
  // already wired to auto-continue when we pass autopilot=true below.
  useEffect(() => {
    if (!isAutopilot) return;
    if (phase !== "work") return;
    if (paused) return;
    if (!currentEx) return;
    if (saving) return;
    setWorkTimer(workSec);
    if (workTick.current) clearInterval(workTick.current);
    workTick.current = setInterval(() => {
      setWorkTimer((s) => {
        if (s === 4) playCountdownTick();
        else if (s === 3) playCountdownTick();
        else if (s === 2) playCountdownTick();
        if (s <= 1) {
          clearInterval(workTick.current);
          workTick.current = null;
          // Fire outside the setState updater so we don't double-schedule.
          setTimeout(() => { completeSet({ autopilot: true }); }, 250);
          return 0;
        }
        return s - 1;
      });
    }, 1000);
    return () => { if (workTick.current) { clearInterval(workTick.current); workTick.current = null; } };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAutopilot, phase, exIdx, setIdx, paused, currentEx?.name, workSec, saving]);

  const beginWorkout = useCallback((mode: "log" | "autopilot") => {
    // Iter 115 — guard against a workout that arrived with no runnable
    // content (e.g. an old plan or a mobility flow without drills). Bail
    // back to the detail screen with a friendly message instead of showing
    // a blank guided player.
    const wuLen = Array.isArray(workout?.warmup) ? workout.warmup.length : 0;
    const exLen = Array.isArray(workout?.exercises) ? workout.exercises.length : 0;
    if (wuLen === 0 && exLen === 0) {
      Alert.alert(
        "Nothing to guide yet",
        "This session doesn't have a runnable structure (warm-up / blocks). Open it in Manual Mode to review the plan.",
        [{ text: "OK", onPress: () => router.back() }],
      );
      return;
    }
    setLogMode(mode);
    // Force auto-continue after rest ON when the client picks autopilot so
    // the workout truly flows without any tapping needed.
    if (mode === "autopilot") {
      setAutoCont(true);
      setAutoRest(true);
    }
    if (wuLen > 0) {
      setPhase("warmup");
      setWarmupIdx(0);
    } else {
      setPhase("work");
    }
  }, [workout, router]);

  const advanceAfterRest = () => {
    goToNextSetOrExercise();
  };

  const goToNextSetOrExercise = () => {
    if (isLastSet) {
      if (isLastExercise) {
        setPhase("complete");
      } else {
        setExIdx((i) => i + 1);
        setSetIdx(1);
        setPhase("work");
      }
    } else {
      setSetIdx((s) => s + 1);
      setPhase("work");
    }
  };

  // Complete a set: log to backend, then rest
  const completeSet = async (opts?: { autopilot?: boolean }) => {
    if (saving) return;
    setSaving(true);
    const ap = !!opts?.autopilot;
    try {
      const body: any = {
        workout_id: String(id),
        exercise_index: exIdx,
        exercise_name: currentEx.name,
        set_number: setIdx,
      };
      // Iter189q · Only strength / bodyweight sets carry `target_reps`.
      // Cardio must never send a reps target — the log is purely time
      // and distance.
      if (!isCardio) {
        body.target_reps = String(targetReps);
      }
      if (isCardio) {
        // For cardio, treat weight box as time (mm:ss), reps box as distance km
        if (!ap) {
          const t = logWeight.split(":").map((n) => parseInt(n, 10));
          const timeSec = t.length === 2 ? t[0] * 60 + (t[1] || 0) : (parseFloat(logWeight) * 60 || null);
          const distKm = parseFloat(logReps);
          if (timeSec) body.duration_sec = timeSec;
          if (!isNaN(distKm)) body.distance_m = Math.round(distKm * 1000);
          if (logRpe) body.rpe = parseFloat(logRpe);
        } else {
          // Autopilot: log the planned interval so history has *something*.
          body.duration_sec = workSec;
        }
        body.logging_type = "cardio";
      } else if (!ap) {
        body.actual_weight = parseFloat(logWeight) || null;
        body.actual_reps = parseInt(logReps, 10) || null;
        body.rpe = parseFloat(logRpe) || null;
      } else {
        // Autopilot for strength: no weight / no RPE, target reps assumed.
        body.actual_reps = targetReps || null;
        body.autopilot = true;
      }
      if (!ap && logNote.trim()) body.notes = logNote.trim();
      const r = await api<any>(`/workouts/${id}/sets`, { method: "POST", body });
      setLogs((all) => [...all, r.set]);

      // Reset log inputs for next set
      if (!ap) {
        setLogNote("");
        setLogRpe("");
      }

      if (isLastSet && isLastExercise) {
        hapticSuccess();
        playWorkoutComplete();
        narrateWorkoutComplete();
        setPhase("complete");
      } else if (ap || autoRest) {
        startRest(restSec, `${currentEx.name} Set ${setIdx} complete`);
      } else {
        // Skip rest — advance immediately
        goToNextSetOrExercise();
      }
    } catch (e: any) {
      // Non-blocking — in autopilot we still advance so the flow keeps moving.
      if (ap) {
        if (isLastSet && isLastExercise) {
          hapticSuccess();
          playWorkoutComplete();
          narrateWorkoutComplete();
          setPhase("complete");
        } else {
          startRest(restSec, `${currentEx.name} Set ${setIdx} complete`);
        }
      }
    } finally { setSaving(false); }
  };

  const skipRest = () => {
    goToNextSetOrExercise();
  };

  const skipWarmup = () => {
    if (warmupTick.current) clearInterval(warmupTick.current);
    const next = warmupIdx + 1;
    if (next < (workout?.warmup?.length || 0)) {
      setWarmupIdx(next);
    } else {
      setPhase("work");
    }
  };

  const skipAllWarmup = () => {
    if (warmupTick.current) clearInterval(warmupTick.current);
    setPhase("work");
  };

  const toggleAutoCont = async () => {
    const next = !autoCont;
    setAutoCont(next);
    await saveAutoContinue(next);
  };

  // Progress
  const totalUnits = (workout?.warmup?.length || 0) + totalExercises;
  const completedUnits =
    phase === "warmup" ? warmupIdx :
    phase === "complete" ? totalUnits :
    (workout?.warmup?.length || 0) + exIdx + ((setIdx - 1) / Math.max(1, targetSets));
  const pct = totalUnits ? Math.min(100, Math.round((completedUnits / totalUnits) * 100)) : 0;

  // Media priority (iter189q): V2 stream → legacy custom_image → legacy coach_image.
  // Sourced from the shared useExerciseMedia hook so guided flow matches manual mode.
  const media = mainMedia.thumbUrl;

  const primaryCue: string = useMemo(() => {
    const cues = content?.cues;
    if (Array.isArray(cues) && cues.length) return String(cues[0]);
    return "Control the movement. Own every rep.";
  }, [content]);

  // Next Up label
  const nextUpLabel = useMemo(() => {
    if (phase === "warmup") {
      const next = workout?.warmup?.[warmupIdx + 1];
      return next?.name || (totalExercises ? workout.exercises[0].name + " Set 1" : "");
    }
    if (phase === "work" || phase === "rest") {
      if (!isLastSet) return `${currentEx?.name} Set ${setIdx + 1}`;
      if (!isLastExercise) return `${workout?.exercises[exIdx + 1]?.name} Set 1`;
      return "Workout complete";
    }
    return "";
  }, [phase, warmupIdx, workout, isLastSet, isLastExercise, currentEx, setIdx, exIdx, totalExercises]);

  const nextThenLabel = useMemo(() => {
    if (phase === "warmup") {
      const then = workout?.warmup?.[warmupIdx + 2];
      return then?.name || "";
    }
    if (phase === "work" || phase === "rest") {
      if (!isLastSet && setIdx + 1 < targetSets) return `${currentEx?.name} Set ${setIdx + 2}`;
      if (!isLastExercise) return workout?.exercises[exIdx + 1]?.name;
      return "";
    }
    return "";
  }, [phase, warmupIdx, workout, isLastSet, targetSets, isLastExercise, currentEx, setIdx, exIdx]);

  if (phase === "loading" || !workout) {
    return (
      <SafeAreaView style={styles.root}>
        <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
          <ActivityIndicator color={theme.color.brand} size="large" />
          <Text style={{ color: theme.color.textMuted, marginTop: 12, fontSize: 12, letterSpacing: 2 }}>PREPARING GUIDED FLOW</Text>
        </View>
        {/* Iter 95i — Once the workout has loaded, ask the client whether
            they want to track lifts or just flow. We keep phase="loading"
            behind the sheet so the UI doesn't flash the warmup / work UI
            before they've chosen. */}
        <StartModeSheet
          visible={!!workout && logMode === "asking"}
          workoutTitle={workout?.title || "Session"}
          hasWarmup={Array.isArray(workout?.warmup) && workout.warmup.length > 0}
          exerciseCount={workout?.exercises?.length || 0}
          onPick={beginWorkout}
        />
      </SafeAreaView>
    );
  }

  if (phase === "complete") {
    return <WorkoutComplete workout={workout} logs={logs} durationMin={Math.round((Date.now() - startedAt.current) / 60000)} onDone={() => router.replace(`/workout/${id}` as any)} />;
  }

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      {/* Top Bar */}
      <View style={styles.topBar}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="gf-close">
          <Ionicons name="close" size={26} color={theme.color.text} />
        </Pressable>
        <View style={{ flex: 1, marginHorizontal: 12 }}>
          <Text style={styles.wName} numberOfLines={1}>{workout.title || "Workout"}</Text>
          <Text style={styles.wMeta}>
            {phase === "warmup" && `WARM-UP ${warmupIdx + 1} of ${workout.warmup.length}`}
            {(phase === "work" || phase === "rest") && `EX ${exIdx + 1}/${totalExercises} · SET ${setIdx}/${targetSets}`}
          </Text>
        </View>
        <Pressable
          onPress={async () => {
            const next = !voiceOn;
            setVoiceOnState(next);
            await saveVoiceOn(next);
            if (!next) stopNarration();
          }}
          hitSlop={12}
          testID="gf-voice-toggle"
          style={{ marginRight: 14 }}
        >
          <Ionicons
            name={voiceOn ? "mic" : "mic-off"}
            size={20}
            color={voiceOn ? theme.color.brand : theme.color.textMuted}
          />
        </Pressable>
        <Pressable onPress={() => setPaused((v) => !v)} hitSlop={12} testID="gf-pause">
          <Ionicons name={paused ? "play" : "pause"} size={22} color={theme.color.text} />
        </Pressable>
      </View>

      {/* Progress bar */}
      <View style={styles.progressTrack}><View style={[styles.progressFill, { width: `${pct}%` }]} /></View>

      <ScrollView contentContainerStyle={styles.body}>
        {/* Phase label */}
        {phase === "rest" ? (
          <View style={{ paddingVertical: 8 }}>
            <RestTimer
              seconds={restSeconds.current}
              previousLabel={previousLabel}
              nextLabel={nextUpLabel}
              onComplete={advanceAfterRest}
              onSkip={skipRest}
              autoContinueOverride={isAutopilot ? true : autoCont}
              size={260}
            />
            {isAutopilot ? (
              <Text style={styles.autopilotHint}>FLOW MODE · REST WILL AUTO-CONTINUE</Text>
            ) : (
              <Pressable onPress={toggleAutoCont} style={styles.autoContRow} testID="gf-auto-toggle">
                <View style={[styles.check, autoCont && styles.checkOn]}>
                  {autoCont && <Ionicons name="checkmark" size={14} color="#fff" />}
                </View>
                <Text style={styles.autoContT}>Auto-continue after rest</Text>
              </Pressable>
            )}
          </View>
        ) : phase === "warmup" ? (
          <WarmupPanel
            item={workout.warmup[warmupIdx]}
            index={warmupIdx + 1}
            total={workout.warmup.length}
            timeLeft={warmupTimer}
            paused={paused}
            onSkipItem={skipWarmup}
            onSkipAll={skipAllWarmup}
            onHowTo={openHowTo}
            nextUp={nextUpLabel}
          />
        ) : (
          <WorkPanel
            ex={currentEx}
            setIdx={setIdx}
            targetSets={targetSets}
            targetReps={targetReps}
            cue={primaryCue}
            media={media}
            prev={prev}
            isCardio={isCardio}
            timerLocked={timerLocked}
            logWeight={logWeight} setLogWeight={setLogWeight}
            logReps={logReps} setLogReps={setLogReps}
            logRpe={logRpe} setLogRpe={setLogRpe}
            logNote={logNote} setLogNote={setLogNote}
            saving={saving}
            paused={paused}
            autopilot={isAutopilot}
            workTimer={workTimer}
            workSec={workSec}
            onTogglePause={() => setPaused((v) => !v)}
            onComplete={() => completeSet()}
            onHowTo={openHowTo}
            onSwap={() => setSwapOpen(true)}
          />
        )}

        {/* Next Up */}
        {nextUpLabel && phase !== "rest" && (
          <View style={styles.nextUpCard}>
            <Text style={styles.nextUpEyebrow}>NEXT UP</Text>
            <Text style={styles.nextUpT}>{nextUpLabel}</Text>
            {nextThenLabel && <Text style={styles.nextThenT}>Then · {nextThenLabel}</Text>}
          </View>
        )}
      </ScrollView>

      {/* How-to bottom sheet */}
      <HowToSheet
        visible={howToOpen}
        exercise={howToTargetEx || currentEx}
        content={howToTargetContent || content}
        onClose={closeHowTo}
        onSwap={() => { closeHowTo(); setSwapOpen(true); }}
      />

      {/* Swap sheet */}
      <SwapSheet
        visible={swapOpen}
        workoutId={String(id)}
        exercise={currentEx}
        onClose={() => setSwapOpen(false)}
        onSwapped={async (newEx, reason) => {
          // Persist the swap so it survives reloads and Louis can see it
          // in the coach dashboard. Falls back to local-only update if the
          // API is unreachable so the user isn't stranded mid-workout.
          const newName = newEx?.name;
          try {
            await api<{ workout: any }>(`/workouts/${id}/swap-exercise`, {
              method: "POST",
              body: { exercise_index: exIdx, new_name: newName, reason: reason || null },
            });
            // Iter189r · Re-hydrate via GET /workouts/:id so the swapped
            // exercise picks up its images/video/how-to. Previously the
            // raw workout returned by the swap endpoint replaced state
            // directly, but it lacked the exercise media hydration —
            // making the tile go blank and creating the illusion that
            // "tapping alternatives did nothing".
            await reloadWorkout();
          } catch (e: any) {
            // Non-fatal — apply locally so the guided flow keeps moving.
            setWorkout((w: any) => ({
              ...w,
              exercises: w.exercises.map((e: any, i: number) => (i === exIdx ? { ...e, ...newEx } : e)),
            }));
            Alert.alert(
              "Couldn't sync swap",
              "Continuing with the alternative locally. Reopen the workout to retry sync.",
            );
          }
          setSwapOpen(false);
        }}
      />
    </SafeAreaView>
  );
}

/* -------------------------------------------------------------------------- */
/*  Warmup Panel                                                               */
/* -------------------------------------------------------------------------- */
function WarmupPanel({
  item, index, total, timeLeft, paused, onSkipItem, onSkipAll, onHowTo, nextUp,
}: {
  item: any; index: number; total: number; timeLeft: number; paused: boolean;
  onSkipItem: () => void; onSkipAll: () => void; onHowTo?: () => void; nextUp: string;
}) {
  const [content, setContent] = useState<any>(null);
  useEffect(() => {
    if (!item?.name) return;
    setContent(null);
    api<any>(`/exercises/content?name=${encodeURIComponent(item.name)}`)
      .then((r) => setContent(r?.exercise || null)).catch(() => setContent(null));
  }, [item?.name]);
  // Iter189q · V2-aware thumbnail (same fallback ladder as manual mode).
  const warmupMedia = useExerciseMedia(item?.name);
  const total_sec = Math.max(10, parseInt(String(item.duration_sec || 30), 10));
  const pct = Math.round(((total_sec - timeLeft) / total_sec) * 100);
  const img = warmupMedia.thumbUrl;
  const cues = Array.isArray(content?.cues) ? content.cues : [];

  return (
    <View>
      <Text style={styles.phaseLabel}>WARM-UP</Text>
      <Text style={styles.exName}>{item.name}</Text>
      <Text style={styles.exMeta}>Move {index} of {total}</Text>

      <View style={styles.mediaBox}>
        <WorkoutMediaCarousel
          exerciseName={item?.name || ""}
          height={260}
          autoScroll={!paused}
          autoScrollIntervalMs={6000}
          contentFit="contain"
        />
      </View>

      <View style={styles.timerBox}>
        <Text style={styles.timerBig}>{fmtMMSS(timeLeft)}</Text>
        <View style={styles.timerBarTrack}>
          <View style={[styles.timerBarFill, { width: `${pct}%` }]} />
        </View>
      </View>

      {cues[0] && (
        <View style={styles.cueBox}>
          <Ionicons name="chatbubble-ellipses" size={12} color={theme.color.brand} />
          <Text style={styles.cueT}>{cues[0]}</Text>
        </View>
      )}

      <View style={styles.rowActions}>
        {onHowTo ? (
          <Pressable onPress={onHowTo} style={styles.secondaryBtn} testID="gf-warmup-howto">
            <Ionicons name="play-circle" size={14} color={theme.color.brand} />
            <Text style={styles.secondaryBtnT}>HOW TO</Text>
          </Pressable>
        ) : null}
        <Pressable onPress={onSkipItem} style={styles.secondaryBtn} testID="gf-warmup-skip">
          <Ionicons name="play-forward" size={14} color={theme.color.brand} />
          <Text style={styles.secondaryBtnT}>SKIP MOVE</Text>
        </Pressable>
        <Pressable onPress={onSkipAll} style={styles.secondaryBtn} testID="gf-warmup-skip-all">
          <Text style={styles.secondaryBtnT}>SKIP WARM-UP</Text>
        </Pressable>
      </View>

      {paused && <Text style={styles.pausedHint}>PAUSED · TAP PLAY TO RESUME</Text>}
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/*  Work Panel                                                                 */
/* -------------------------------------------------------------------------- */
function WorkPanel({
  ex, setIdx, targetSets, targetReps, cue, media, prev, isCardio, timerLocked,
  logWeight, setLogWeight, logReps, setLogReps, logRpe, setLogRpe, logNote, setLogNote,
  saving, paused, autopilot, workTimer, workSec,
  onTogglePause, onComplete, onHowTo, onSwap,
}: any) {
  const suggested = prev?.suggested_load;
  const suggestedT = suggested ? `${suggested}kg × ${targetReps}` : null;
  const progReason = prev?.progression_hint?.reason;
  const workPct = workSec ? Math.max(0, Math.min(100, Math.round(((workSec - workTimer) / workSec) * 100))) : 0;
  // Iter189s · timerLocked (logging_type === 'timer' | 'cardio') is the
  // SINGLE source of truth for whether this row shows the TIME badge +
  // auto-timer. Other classifiers (`isCardio`, `isTimeBased`) are used
  // ONLY to pick the *style* of time UI (cardio TIME+DIST vs hold timer).
  const showTimeBadge = timerLocked;

  return (
    <View>
      {paused ? (
        <Pressable onPress={onTogglePause} style={styles.pausedBanner} testID="gf-paused-banner">
          <Ionicons name="pause-circle" size={18} color={theme.color.amber} />
          <View style={{ flex: 1 }}>
            <Text style={styles.pausedBannerT}>WORKOUT PAUSED</Text>
            <Text style={styles.pausedBannerS}>Tap here or press play to resume</Text>
          </View>
          <Ionicons name="play" size={18} color={theme.color.amber} />
        </Pressable>
      ) : null}
      <Text style={styles.phaseLabel}>{autopilot ? "WORK · FLOW" : "WORK"}</Text>
      <Text style={styles.exName}>{ex?.name}</Text>
      <Text style={styles.exMeta}>
        Set {setIdx} of {targetSets}
        {showTimeBadge
          ? ` · ${_fmtCardioTarget(ex)}`
          : ` · ${targetReps} reps`}
      </Text>
      {/* Iter189q · Cardio meta line — extra context (Zone 2 / MP+90s /
          cadence / RPE) only when it's a text hint, NOT a bare rep count.
          A bare "40" would be misread as "40 reps" (Iter189q bug fix). */}
      {showTimeBadge && ex?.reps && _looksLikeCardioHint(ex.reps) ? (
        <Text style={styles.exMetaCardio}>{String(ex.reps)}</Text>
      ) : null}

      <View style={styles.mediaBox}>
        <WorkoutMediaCarousel
          exerciseName={ex?.name || ""}
          height={280}
          autoScroll={!paused && (showTimeBadge || isMobilityLike(ex) || autopilot)}
          autoScrollIntervalMs={isMobilityLike(ex) ? 6000 : 4000}
          contentFit="contain"
        />
      </View>

      <View style={styles.cueBox}>
        <Ionicons name="chatbubble-ellipses" size={12} color={theme.color.brand} />
        <Text style={styles.cueT}>{cue}</Text>
      </View>

      {/* Autopilot: big work-timer numeral in place of log inputs. */}
      {autopilot ? (
        <View style={styles.timerBox}>
          <Text style={styles.timerBig}>{fmtMMSS(workTimer)}</Text>
          <View style={styles.timerBarTrack}>
            <View style={[styles.timerBarFill, { width: `${workPct}%` }]} />
          </View>
          <Text style={styles.autopilotHint}>
            FLOW MODE · SET WILL AUTO-LOG · REST WILL AUTO-CONTINUE
          </Text>
        </View>
      ) : (
        <>
          {/* Last time / Today's target */}
          {prev?.last_session?.length > 0 && (
            <View style={styles.prevRow}>
              <View style={styles.prevCol}>
                <Text style={styles.prevHead}>LAST TIME</Text>
                <Text style={styles.prevBig}>
                  {prev.last_session[0]?.actual_weight
                    ? `${prev.last_session[0].actual_weight}kg × ${prev.last_session[0].actual_reps || "?"}`
                    : `${prev.last_session[0]?.actual_reps || "?"} reps`}
                </Text>
                {prev.last_session[0]?.rpe != null && (
                  <Text style={styles.prevSub}>RPE {prev.last_session[0].rpe}</Text>
                )}
              </View>
              {suggestedT && (
                <View style={styles.prevCol}>
                  <Text style={[styles.prevHead, { color: theme.color.brand }]}>TODAY&apos;S TARGET</Text>
                  <Text style={[styles.prevBig, { color: theme.color.brand }]}>{suggestedT}</Text>
                  {progReason && <Text style={styles.prevSub} numberOfLines={2}>{progReason}</Text>}
                </View>
              )}
            </View>
          )}

          {/* Log inputs — Iter189s · timerLocked (logging_type) drives
              which layout to show. Within timer-locked exercises, we
              still use `isCardio` (name/category-based) to pick between
              cardio-style TIME+DIST fields and hold-style live timer. */}
          {showTimeBadge && isCardio ? (
            <View style={styles.logGrid}>
              <LogInput label="TIME (mm:ss)" value={logWeight} onChangeText={setLogWeight} placeholder="30:00" />
              <LogInput label="DIST (km)" value={logReps} onChangeText={setLogReps} placeholder="5.0" />
              <LogInput label="RPE" value={logRpe} onChangeText={setLogRpe} placeholder="1-10" />
            </View>
          ) : showTimeBadge ? (
            /* Iter186 · Time-based (hold) exercises get a live HOLD TIMER. */
            <HoldTimerLog
              targetSeconds={extractTargetSeconds(ex)}
              onLogged={(sec) => setLogReps(String(sec))}
              currentValue={logReps}
              logWeight={logWeight}
              setLogWeight={setLogWeight}
              logRpe={logRpe}
              setLogRpe={setLogRpe}
            />
          ) : (
            <View style={styles.logGrid}>
              <LogInput label="WEIGHT (kg)" value={logWeight} onChangeText={setLogWeight} placeholder={suggested ? String(suggested) : "0"} />
              <LogInput label="REPS" value={logReps} onChangeText={setLogReps} placeholder={String(targetReps)} />
              <LogInput label="RPE" value={logRpe} onChangeText={setLogRpe} placeholder="1-10" />
            </View>
          )}

          <TextInput
            value={logNote}
            onChangeText={setLogNote}
            placeholder="Notes (optional)"
            placeholderTextColor={theme.color.textDim}
            style={styles.noteInput}
            testID="gf-log-note"
          />

          <Pressable
            onPress={onComplete}
            disabled={saving}
            style={[styles.completeBtn, saving && { opacity: 0.4 }]}
            testID="gf-complete-set"
          >
            {saving ? <ActivityIndicator color="#fff" /> : <Ionicons name="checkmark" size={18} color="#fff" />}
            <Text style={styles.completeBtnT}>{saving ? "LOGGING..." : "COMPLETE SET"}</Text>
          </Pressable>
        </>
      )}

      <View style={styles.rowActions}>
        <Pressable onPress={onHowTo} style={[styles.secondaryBtn, styles.secondaryBtnPrimary]} testID="gf-howto">
          <Ionicons name="play-circle" size={16} color="#fff" />
          <Text style={[styles.secondaryBtnT, { color: "#fff" }]}>PAUSE & WATCH DEMO</Text>
        </Pressable>
        <Pressable onPress={onSwap} style={styles.secondaryBtn} testID="gf-swap">
          <Ionicons name="swap-horizontal" size={14} color={theme.color.brand} />
          <Text style={styles.secondaryBtnT}>SWAP</Text>
        </Pressable>
      </View>
    </View>
  );
}

function LogInput({ label, value, onChangeText, placeholder }: any) {
  return (
    <View style={styles.logField}>
      <Text style={styles.logFieldLbl}>{label}</Text>
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={theme.color.textDim}
        keyboardType="decimal-pad"
        style={styles.logInput}
      />
    </View>
  );
}

// Iter186 · Hold-timer used by ExerciseBlock for time-based moves in
// LOG MODE. Presents a big countdown, START / STOP buttons, and once
// the client stops (or the target is reached) it stamps the elapsed
// seconds into the parent's `logReps` state so the "COMPLETE SET"
// button records the exact hold time in workout history.
//
// Rendered alongside a compact WEIGHT + RPE row so weighted variants
// (loaded farmer's carry, dumbbell suitcase carry, etc.) can still
// record the load. Weight column collapses gracefully when unused.
function HoldTimerLog({
  targetSeconds, onLogged, currentValue, logWeight, setLogWeight, logRpe, setLogRpe,
}: {
  targetSeconds: number;
  onLogged: (elapsedSec: number) => void;
  currentValue: string;
  logWeight: string;
  setLogWeight: (v: string) => void;
  logRpe: string;
  setLogRpe: (v: string) => void;
}) {
  const [running, setRunning] = React.useState(false);
  const [elapsed, setElapsed] = React.useState(0);
  const tick = React.useRef<any>(null);

  React.useEffect(() => {
    if (!running) return;
    tick.current = setInterval(() => {
      setElapsed((s) => {
        const next = s + 1;
        // Buzz once when target reached — client can keep going or stop.
        if (next === targetSeconds) {
          try { Vibration.vibrate([0, 200, 100, 200]); } catch { /* web */ }
        }
        return next;
      });
    }, 1000);
    return () => { if (tick.current) clearInterval(tick.current); };
  }, [running, targetSeconds]);

  const toggle = () => {
    if (!running) {
      setElapsed(0);
      setRunning(true);
      return;
    }
    // stopping — commit elapsed seconds into the parent form
    setRunning(false);
    if (elapsed > 0) onLogged(elapsed);
  };

  const reset = () => {
    if (tick.current) clearInterval(tick.current);
    setRunning(false);
    setElapsed(0);
    onLogged(0);
  };

  const pct = Math.min(100, Math.round((elapsed / Math.max(1, targetSeconds)) * 100));
  const displayValue = running ? elapsed : (parseInt(currentValue, 10) || elapsed);

  return (
    <View style={styles.holdBox} testID="hold-timer-box">
      <Text style={styles.holdEyebrow}>
        HOLD TIMER · TARGET {fmtMMSS(targetSeconds)}
      </Text>
      <Text style={[styles.timerBig, running && { color: theme.color.brand }]}>
        {fmtMMSS(displayValue)}
      </Text>
      <View style={styles.timerBarTrack}>
        <View style={[styles.timerBarFill, { width: `${pct}%` }]} />
      </View>
      <View style={styles.holdBtnRow}>
        <Pressable onPress={reset} style={styles.holdResetBtn} testID="hold-timer-reset">
          <Ionicons name="refresh" size={14} color={theme.color.text} />
          <Text style={styles.holdResetT}>RESET</Text>
        </Pressable>
        <Pressable
          onPress={toggle}
          style={[styles.holdStartBtn, running && styles.holdStopBtn]}
          testID={running ? "hold-timer-stop" : "hold-timer-start"}
        >
          <Ionicons name={running ? "stop" : "play"} size={16} color="#fff" />
          <Text style={styles.holdStartT}>{running ? "STOP" : (elapsed > 0 ? "RESUME" : "START HOLD")}</Text>
        </Pressable>
      </View>
      <Text style={styles.holdHint}>
        Elapsed {fmtMMSS(displayValue)} will be logged as your set time.
      </Text>
      {/* Compact weight + RPE row so weighted holds (farmer's carry,
          weighted planks, etc.) still record load. */}
      <View style={[styles.logGrid, { marginTop: 6 }]}>
        <LogInput label="WEIGHT (kg)" value={logWeight} onChangeText={setLogWeight} placeholder="0" />
        <LogInput label="RPE" value={logRpe} onChangeText={setLogRpe} placeholder="1-10" />
      </View>
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/*  How-To Bottom Sheet                                                        */
/* -------------------------------------------------------------------------- */
function HowToSheet({
  visible, exercise, content, onClose, onSwap,
}: {
  visible: boolean; exercise: any; content: any; onClose: () => void; onSwap: () => void;
}) {
  if (!visible) return null;
  const instr = Array.isArray(content?.instructions) ? content.instructions : [];
  const cues = Array.isArray(content?.cues) ? content.cues : [];
  const mistakes = Array.isArray(content?.mistakes) ? content.mistakes : [];
  const hasVideo = !!(content?.coach_video_url || content?.video_url);

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={sheetStyles.root}>
        <Pressable style={sheetStyles.backdrop} onPress={onClose} />
        <View style={sheetStyles.sheet}>
          {/* Iter186 · Prominent back-to-workout chip pinned above the
              header text so the client can't miss the exit path. Plus
              the original close-X remains at the top-right + the footer
              RESUME WORKOUT button below. Three exit paths total. */}
          <Pressable
            onPress={onClose}
            style={sheetStyles.backChip}
            testID="gf-howto-back"
            hitSlop={12}
            accessibilityRole="button"
            accessibilityLabel="Back to workout"
          >
            <Ionicons name="chevron-back" size={16} color={theme.color.brand} />
            <Text style={sheetStyles.backChipT}>BACK TO WORKOUT</Text>
          </Pressable>
          <View style={sheetStyles.head}>
            <View style={{ flex: 1 }}>
              <Text style={sheetStyles.eyebrow}>PAUSED · LEARN THIS EXERCISE</Text>
              <Text style={sheetStyles.pausedNote}>
                Your workout is paused. Tap RESUME when you&apos;re ready.
              </Text>
            </View>
            <Pressable
              onPress={onClose}
              hitSlop={12}
              testID="gf-howto-close"
              style={sheetStyles.closeXBtn}
              accessibilityLabel="Close explanation"
            >
              <Ionicons name="close" size={22} color={theme.color.text} />
            </Pressable>
          </View>
          <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 100 }}>
            <Text style={sheetStyles.title}>{exercise?.name}</Text>
            {hasVideo ? (
              <View style={{ marginTop: 12, borderRadius: 12, overflow: "hidden" }}>
                <ExerciseVideoPlayer exerciseName={exercise?.name || ""} />
              </View>
            ) : (
              <View style={sheetStyles.noVideoCard}>
                <Ionicons name="videocam-off" size={20} color={theme.color.textMuted} />
                <View style={{ flex: 1 }}>
                  <Text style={sheetStyles.noVideoT}>No demo for this one yet</Text>
                  <Text style={sheetStyles.noVideoS}>Louis is filming this exercise. Follow the coaching cues below for now.</Text>
                </View>
              </View>
            )}
            {instr.length > 0 && (
              <View style={{ marginTop: 16 }}>
                <Text style={sheetStyles.h}>STEPS</Text>
                {instr.map((s: string, i: number) => (
                  <View key={i} style={sheetStyles.line}>
                    <Text style={sheetStyles.n}>{i + 1}</Text>
                    <Text style={sheetStyles.lineT}>{s}</Text>
                  </View>
                ))}
              </View>
            )}
            {cues.length > 0 && (
              <View style={{ marginTop: 16 }}>
                <Text style={sheetStyles.h}>COACHING CUES</Text>
                {cues.map((c: string, i: number) => (
                  <View key={i} style={sheetStyles.cueLine}>
                    <Ionicons name="ellipse" size={5} color={theme.color.brand} />
                    <Text style={sheetStyles.lineT}>{c}</Text>
                  </View>
                ))}
              </View>
            )}
            {mistakes.length > 0 && (
              <View style={{ marginTop: 16 }}>
                <Text style={sheetStyles.h}>AVOID</Text>
                {mistakes.map((m: string, i: number) => (
                  <View key={i} style={sheetStyles.mistakeLine}>
                    <Ionicons name="warning" size={11} color="#c94a4a" />
                    <Text style={sheetStyles.lineT}>{m}</Text>
                  </View>
                ))}
              </View>
            )}
            {instr.length === 0 && cues.length === 0 && !hasVideo && (
              <Text style={{ color: theme.color.textMuted, marginTop: 12, fontStyle: "italic" }}>
                Move guidance will appear once your coach adds it.
              </Text>
            )}
            <Pressable onPress={onSwap} style={sheetStyles.swapBtn}>
              <Ionicons name="swap-horizontal" size={14} color={theme.color.brand} />
              <Text style={sheetStyles.swapBtnT}>SUGGEST ALTERNATIVES</Text>
            </Pressable>
          </ScrollView>
          <View style={sheetStyles.footer}>
            <Pressable onPress={onClose} style={sheetStyles.resumeBtn} testID="gf-howto-resume">
              <Ionicons name="play" size={16} color="#fff" />
              <Text style={sheetStyles.resumeBtnT}>RESUME WORKOUT</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

/* -------------------------------------------------------------------------- */
/*  Swap Sheet                                                                 */
/* -------------------------------------------------------------------------- */
function SwapSheet({
  visible, workoutId, exercise, onClose, onSwapped,
}: {
  visible: boolean; workoutId: string; exercise: any; onClose: () => void; onSwapped: (ex: any, reason?: string) => void;
}) {
  const [loading, setLoading] = useState(false);
  const [alts, setAlts] = useState<any[]>([]);
  useEffect(() => {
    if (!visible || !exercise?.name) return;
    setLoading(true);
    api<any>(`/exercises/alternatives?name=${encodeURIComponent(exercise.name)}`)
      .then((r) => setAlts(r?.alternatives || []))
      .catch(() => setAlts([]))
      .finally(() => setLoading(false));
  }, [visible, exercise?.name]);

  if (!visible) return null;
  // Iter189g · Purpose badge colours — subtle brand tint per category
  // so the coach's intent is instantly readable in the swap picker.
  const purposeColor: Record<string, string> = {
    equipment_swap: "#4a90e2",
    easier_regression: "#7ac74f",
    injury_mobility_friendly: "#d99a3f",
  };
  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={sheetStyles.root}>
        <Pressable style={sheetStyles.backdrop} onPress={onClose} />
        <View style={sheetStyles.sheet}>
          <View style={sheetStyles.head}>
            <Text style={sheetStyles.eyebrow}>SWAP EXERCISE</Text>
            <Pressable onPress={onClose} hitSlop={12} testID="swap-close"><Ionicons name="close" size={22} color={theme.color.text} /></Pressable>
          </View>
          <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 24 }}>
            <Text style={sheetStyles.title}>{exercise?.name}</Text>
            <Text style={sheetStyles.subtle}>
              Louis suggests up to three alternatives — one equipment swap, one easier regression,
              one injury-friendly option. Choose one and we'll swap it in for this session only.
            </Text>
            {loading && <ActivityIndicator color={theme.color.brand} style={{ marginTop: 20 }} testID="swap-loading" />}
            {!loading && alts.length === 0 && (
              // Iter189g · Empty state — clear message + explicit
              // "Back to Workout" affordance so the client isn't stuck.
              <View style={sheetStyles.empty} testID="swap-empty">
                <Ionicons name="information-circle-outline" size={32} color={theme.color.textMuted} />
                <Text style={sheetStyles.emptyT}>No alternatives available for this exercise</Text>
                <Text style={sheetStyles.emptyM}>
                  Louis hasn't authored substitutes for this move yet. Skip it, adjust the reps,
                  or message your coach if you can't perform it today.
                </Text>
                <Pressable onPress={onClose} style={sheetStyles.emptyBtn} testID="swap-back-to-workout">
                  <Ionicons name="arrow-back" size={16} color="#fff" />
                  <Text style={sheetStyles.emptyBtnT}>BACK TO WORKOUT</Text>
                </Pressable>
              </View>
            )}
            {alts.map((alt, i) => {
              const purpose: string | null = alt?.purpose || null;
              const label: string | null = alt?.purpose_label || null;
              const badgeColor = (purpose && purposeColor[purpose]) || theme.color.brand;
              return (
                <View key={i} style={sheetStyles.altCard} testID={`swap-alt-${i}`}>
                  <View style={{ flex: 1 }}>
                    {label && (
                      <View style={[sheetStyles.altBadge, { backgroundColor: badgeColor + "22", borderColor: badgeColor }]}>
                        <Text style={[sheetStyles.altBadgeT, { color: badgeColor }]}>{label.toUpperCase()}</Text>
                      </View>
                    )}
                    <Text style={sheetStyles.altName}>{alt.name}</Text>
                    {(alt.why || alt.reason) && (
                      <Text style={sheetStyles.altReason} numberOfLines={2}>{alt.why || alt.reason}</Text>
                    )}
                  </View>
                  <Pressable
                    style={sheetStyles.swapPickBtn}
                    onPress={() => onSwapped({ ...exercise, name: alt.name, notes: alt.why || alt.reason }, alt.why || alt.reason)}
                    testID={`swap-btn-${i}`}
                    accessibilityLabel={`Swap to ${alt.name}`}
                  >
                    <Text style={sheetStyles.swapPickBtnT}>SWAP</Text>
                  </Pressable>
                </View>
              );
            })}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

/* -------------------------------------------------------------------------- */
/*  Workout Complete                                                           */
/* -------------------------------------------------------------------------- */
function WorkoutComplete({ workout, logs, durationMin, onDone }: {
  workout: any; logs: any[]; durationMin: number; onDone: () => void;
}) {
  const totalVolume = logs.reduce((sum, s) => sum + ((s.actual_weight || 0) * (s.actual_reps || 0)), 0);
  const rpes = logs.map((s) => s.rpe).filter((v) => typeof v === "number");
  const avgRpe = rpes.length ? (rpes.reduce((a, b) => a + b, 0) / rpes.length).toFixed(1) : "—";
  const setsCompleted = logs.length;
  const [rateOpen, setRateOpen] = useState(true);
  const [ratingResult, setRatingResult] = useState<any>(null);

  useEffect(() => {
    // Fire the completion cue as soon as user lands on this screen.
    // The actual /complete POST now happens inside the rating sheet so
    // the rating + note + pain payload lands in a single call.
    playWorkoutComplete(); hapticSuccess();
  }, []);

  return (
    <SafeAreaView style={styles.root}>
      <ScrollView contentContainerStyle={{ padding: 24 }}>
        <View style={{ alignItems: "center", marginTop: 24 }}>
          <View style={styles.trophyCircle}>
            <Ionicons name="trophy" size={44} color="#fff" />
          </View>
          <Text style={styles.completeTitle}>WORKOUT COMPLETE</Text>
          <Text style={styles.completeSubtitle}>{workout.title}</Text>
        </View>

        <View style={styles.summaryGrid}>
          <SummaryCard label="SETS" value={String(setsCompleted)} />
          <SummaryCard label="DURATION" value={`${durationMin}m`} />
          <SummaryCard label="VOLUME" value={totalVolume ? `${Math.round(totalVolume)}kg` : "—"} />
          <SummaryCard label="AVG RPE" value={String(avgRpe)} />
        </View>

        <View style={styles.atlasSummary}>
          <Text style={styles.atlasEyebrow}>SESSION SUMMARY</Text>
          <Text style={styles.atlasBody}>
            You completed {setsCompleted} logged {setsCompleted === 1 ? "set" : "sets"} across {workout.exercises?.length || 0} exercises in {durationMin} minutes.
            {totalVolume ? ` Total load lifted: ${Math.round(totalVolume)}kg.` : ""}
          </Text>
        </View>

        {ratingResult?.rating ? (
          <Pressable onPress={onDone} style={styles.doneBtn} testID="gf-complete-done">
            <Text style={styles.doneBtnT}>DONE</Text>
          </Pressable>
        ) : (
          <Pressable onPress={() => setRateOpen(true)} style={styles.doneBtn} testID="gf-complete-rate">
            <Text style={styles.doneBtnT}>RATE THIS SESSION</Text>
          </Pressable>
        )}
      </ScrollView>

      <PostWorkoutRatingSheet
        visible={rateOpen}
        workoutId={workout.id}
        workoutTitle={workout.title}
        extraPayload={{
          rpe: rpes.length ? Math.round(rpes.reduce((a, b) => a + b, 0) / rpes.length) : null,
        }}
        onClose={() => setRateOpen(false)}
        onDone={(r) => { setRateOpen(false); setRatingResult(r); onDone(); }}
      />
    </SafeAreaView>
  );
}

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.summaryCard}>
      <Text style={styles.summaryV}>{value}</Text>
      <Text style={styles.summaryL}>{label}</Text>
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/*  Start-of-Workout Mode Picker  (Iter 95i)                                  */
/*  Asked once at the top of the Guided Flow — client picks between           */
/*  tracking lifts (tap COMPLETE SET) or hands-free flow mode.                */
/* -------------------------------------------------------------------------- */
function StartModeSheet({
  visible, workoutTitle, hasWarmup, exerciseCount, onPick,
}: {
  visible: boolean;
  workoutTitle: string;
  hasWarmup: boolean;
  exerciseCount: number;
  onPick: (mode: "log" | "autopilot") => void;
}) {
  if (!visible) return null;
  return (
    <Modal visible transparent animationType="fade">
      <View style={startStyles.root}>
        <View style={startStyles.card}>
          <Text style={startStyles.eyebrow}>GUIDED FLOW</Text>
          <Text style={startStyles.title}>{workoutTitle}</Text>
          <Text style={startStyles.sub}>
            {hasWarmup ? "Warm-up first · " : ""}{exerciseCount} exercises
          </Text>
          <Text style={startStyles.q}>How do you want to run today&apos;s session?</Text>

          <Pressable
            onPress={() => onPick("log")}
            style={[startStyles.opt, startStyles.optSecondary]}
            testID="gf-mode-log"
          >
            <View style={startStyles.optIconWrapSecondary}>
              <Ionicons name="barbell" size={20} color={theme.color.brand} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={startStyles.optT}>Track my lifts</Text>
              <Text style={startStyles.optS}>
                Tap COMPLETE SET after each set so weight and reps are saved for progression.
              </Text>
            </View>
          </Pressable>

          <Pressable
            onPress={() => onPick("autopilot")}
            style={[startStyles.opt, startStyles.optPrimary]}
            testID="gf-mode-autopilot"
          >
            <View style={startStyles.optIconWrapPrimary}>
              <Ionicons name="infinite" size={20} color="#fff" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={[startStyles.optT, { color: "#fff" }]}>Just flow</Text>
              <Text style={[startStyles.optS, { color: "rgba(255,255,255,0.85)" }]}>
                Hands-free class experience. Louis calls out every set, a work timer runs, then straight into rest. Nothing to tap.
              </Text>
            </View>
          </Pressable>

          <Text style={startStyles.foot}>You can pause any time with the play/pause button up top.</Text>
        </View>
      </View>
    </Modal>
  );
}

const startStyles = StyleSheet.create({
  root: {
    flex: 1, backgroundColor: "rgba(0,0,0,0.75)",
    alignItems: "center", justifyContent: "center", padding: 24,
  },
  card: {
    width: "100%", maxWidth: 420,
    backgroundColor: theme.color.surface,
    borderRadius: 20, padding: 24,
    borderWidth: 1, borderColor: theme.color.border,
  },
  eyebrow: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2.5 },
  title: { color: theme.color.text, fontSize: 22, fontWeight: "900", marginTop: 6, letterSpacing: -0.3 },
  sub: { color: theme.color.textMuted, fontSize: 12, marginTop: 4, fontWeight: "700", letterSpacing: 1 },
  q: { color: theme.color.text, fontSize: 15, fontWeight: "800", marginTop: 22, marginBottom: 14, lineHeight: 21 },
  opt: {
    flexDirection: "row", alignItems: "center", gap: 14,
    padding: 16, borderRadius: 14, marginBottom: 10,
    borderWidth: 1,
  },
  optSecondary: { backgroundColor: theme.color.surface2, borderColor: theme.color.border },
  optPrimary: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  optIconWrapSecondary: {
    width: 42, height: 42, borderRadius: 21,
    alignItems: "center", justifyContent: "center",
    backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand,
  },
  optIconWrapPrimary: {
    width: 42, height: 42, borderRadius: 21,
    alignItems: "center", justifyContent: "center",
    backgroundColor: "rgba(255,255,255,0.15)", borderWidth: 1, borderColor: "rgba(255,255,255,0.5)",
  },
  optT: { color: theme.color.text, fontSize: 15, fontWeight: "900", letterSpacing: -0.2 },
  optS: { color: theme.color.textMuted, fontSize: 12, marginTop: 4, lineHeight: 17 },
  foot: {
    color: theme.color.textMuted, fontSize: 11, textAlign: "center",
    marginTop: 8, lineHeight: 15,
  },
});

/* -------------------------------------------------------------------------- */
/*  Styles                                                                     */
/* -------------------------------------------------------------------------- */
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  topBar: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: 16, paddingVertical: 12,
    borderBottomWidth: 1, borderBottomColor: theme.color.divider,
  },
  wName: { color: theme.color.text, fontSize: 15, fontWeight: "800" },
  wMeta: { color: theme.color.textMuted, fontSize: 11, fontWeight: "800", letterSpacing: 1.5, marginTop: 2 },
  progressTrack: { height: 3, backgroundColor: theme.color.surface3 },
  progressFill: { height: 3, backgroundColor: theme.color.brand },
  body: { padding: 20, paddingBottom: 40 },

  phaseLabel: {
    color: theme.color.brand,
    fontSize: 11, fontWeight: "900", letterSpacing: 3, marginBottom: 8,
  },
  exName: { color: theme.color.text, fontSize: 26, fontWeight: "900", letterSpacing: -0.5 },
  exMeta: { color: theme.color.textMuted, fontSize: 12, marginTop: 6, fontWeight: "700", letterSpacing: 1 },
  exMetaCardio: {
    color: theme.color.brand, fontSize: 13, marginTop: 4,
    fontWeight: "700", letterSpacing: 0.5, textAlign: "center",
  },

  mediaBox: {
    marginTop: 16, borderRadius: 14, overflow: "hidden",
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  mediaImg: { width: "100%", height: SCREEN_W * 0.55 },
  mediaFallback: { height: SCREEN_W * 0.55, alignItems: "center", justifyContent: "center" },
  mediaFbT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "800", letterSpacing: 1.5, marginTop: 8 },

  cueBox: {
    flexDirection: "row", alignItems: "center", gap: 8,
    marginTop: 12, padding: 12, borderRadius: 10,
    backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand,
  },
  cueT: { color: theme.color.text, fontSize: 13, lineHeight: 18, flex: 1, fontStyle: "italic" },

  prevRow: { flexDirection: "row", gap: 12, marginTop: 16 },
  prevCol: {
    flex: 1, padding: 12, borderRadius: 10,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  prevHead: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  prevBig: { color: theme.color.text, fontSize: 16, fontWeight: "900", marginTop: 6 },
  prevSub: { color: theme.color.textMuted, fontSize: 11, marginTop: 4, fontStyle: "italic" },

  logGrid: { flexDirection: "row", gap: 8, marginTop: 16 },
  logField: { flex: 1 },
  logFieldLbl: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1.5, marginBottom: 4 },
  logInput: {
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
    borderRadius: 8, padding: 10,
    color: theme.color.onRed, fontSize: 15, fontWeight: "800", textAlign: "center",
  },
  noteInput: {
    marginTop: 10, backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border, borderRadius: 8,
    padding: 10, color: theme.color.onRed, fontSize: 13,
  },

  completeBtn: {
    marginTop: 16, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    padding: 16, borderRadius: 12, backgroundColor: theme.color.brand,
  },
  completeBtnT: { color: "#fff", fontSize: 13, fontWeight: "900", letterSpacing: 2 },

  rowActions: { flexDirection: "row", gap: 10, marginTop: 12 },
  secondaryBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    padding: 12, borderRadius: 10,
    backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand,
  },
  secondaryBtnT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },

  timerBox: { marginTop: 20, alignItems: "center" },
  timerBig: { color: theme.color.brand, fontSize: 56, fontWeight: "900", fontVariant: ["tabular-nums"] },
  timerBarTrack: { width: "100%", height: 6, borderRadius: 3, backgroundColor: theme.color.surface3, overflow: "hidden", marginTop: 8 },
  timerBarFill: { height: 6, backgroundColor: theme.color.brand },
  // Iter186 · Hold-timer container styles (in-log-mode time-based moves)
  holdBox: {
    marginTop: 12, padding: 16, borderRadius: 12,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.brand,
    alignItems: "center",
    gap: 6,
  },
  holdEyebrow: {
    color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2,
    marginBottom: 2,
  },
  holdBtnRow: {
    flexDirection: "row", gap: 10, marginTop: 10, alignSelf: "stretch",
  },
  holdResetBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    paddingHorizontal: 14, paddingVertical: 12, borderRadius: 10,
    borderWidth: 1, borderColor: theme.color.border,
  },
  holdResetT: { color: theme.color.text, fontSize: 11, fontWeight: "900", letterSpacing: 1 },
  holdStartBtn: {
    flex: 1,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    paddingVertical: 12, borderRadius: 10,
    backgroundColor: theme.color.brand,
  },
  holdStopBtn: { backgroundColor: "#c94a4a" },
  holdStartT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 1.4 },
  holdHint: {
    color: theme.color.textMuted, fontSize: 11, fontStyle: "italic",
    marginTop: 4, textAlign: "center",
  },

  restBig: { color: theme.color.brand, fontSize: 96, fontWeight: "900", fontVariant: ["tabular-nums"], textAlign: "center", marginTop: 20 },
  restHint: { color: theme.color.textMuted, fontSize: 12, textAlign: "center", marginTop: 8, letterSpacing: 1 },
  countdownBox: { marginTop: 40, alignItems: "center" },
  countdownT: { color: theme.color.brand, fontSize: 160, fontWeight: "900" },

  autoContRow: { flexDirection: "row", alignItems: "center", gap: 10, marginTop: 20, justifyContent: "center" },
  autoContT: { color: theme.color.text, fontSize: 12, fontWeight: "600" },
  autopilotHint: {
    color: theme.color.brand, fontSize: 11, fontWeight: "900",
    letterSpacing: 2, textAlign: "center", marginTop: 14,
  },
  check: {
    width: 22, height: 22, borderRadius: 6,
    borderWidth: 1.5, borderColor: theme.color.border,
    alignItems: "center", justifyContent: "center",
  },
  checkOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },

  pausedHint: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 2, textAlign: "center", marginTop: 12, fontWeight: "800" },
  pausedBanner: {
    flexDirection: "row", alignItems: "center", gap: 10,
    padding: 12, borderRadius: 10, marginBottom: 12,
    backgroundColor: "rgba(245,158,11,0.10)",
    borderWidth: 1, borderColor: "rgba(245,158,11,0.55)",
  },
  pausedBannerT: { color: theme.color.amber, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  pausedBannerS: { color: theme.color.textMuted, fontSize: 12, marginTop: 2 },
  secondaryBtnPrimary: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },

  nextUpCard: {
    marginTop: 20, padding: 14, borderRadius: 12,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  nextUpEyebrow: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  nextUpT: { color: theme.color.text, fontSize: 13, fontWeight: "800", marginTop: 4 },
  nextThenT: { color: theme.color.textMuted, fontSize: 11, marginTop: 3 },

  /* Complete screen */
  trophyCircle: {
    width: 90, height: 90, borderRadius: 45,
    backgroundColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
  },
  completeTitle: { color: theme.color.text, fontSize: 20, fontWeight: "900", letterSpacing: 2, marginTop: 20 },
  completeSubtitle: { color: theme.color.textMuted, fontSize: 13, marginTop: 6 },
  summaryGrid: { flexDirection: "row", flexWrap: "wrap", gap: 12, marginTop: 30 },
  summaryCard: {
    width: "47%", padding: 16, borderRadius: 12,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
    alignItems: "center",
  },
  summaryV: { color: theme.color.text, fontSize: 26, fontWeight: "900" },
  summaryL: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1.5, marginTop: 4 },
  atlasSummary: {
    marginTop: 24, padding: 16, borderRadius: 12,
    backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand,
  },
  atlasEyebrow: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  atlasBody: { color: theme.color.text, fontSize: 13, lineHeight: 20, marginTop: 8 },
  doneBtn: {
    marginTop: 30, padding: 16, borderRadius: 12, backgroundColor: theme.color.brand,
    alignItems: "center",
  },
  doneBtnT: { color: "#fff", fontSize: 13, fontWeight: "900", letterSpacing: 2 },
});

const sheetStyles = StyleSheet.create({
  root: { flex: 1, justifyContent: "flex-end" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.5)" },
  sheet: { backgroundColor: theme.color.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20, maxHeight: "88%" },
  // Iter186 · Pinned "BACK TO WORKOUT" chip — sits above the header so
  // the client always has a visible exit path from the how-to sheet.
  backChip: {
    alignSelf: "flex-start",
    flexDirection: "row", alignItems: "center", gap: 4,
    marginTop: 12, marginLeft: 12,
    paddingLeft: 6, paddingRight: 12, paddingVertical: 8,
    borderRadius: 20,
    backgroundColor: theme.color.brandTint,
    borderWidth: 1, borderColor: theme.color.brand,
  },
  backChipT: {
    color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.4,
  },
  closeXBtn: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: theme.color.surface2,
    alignItems: "center", justifyContent: "center",
  },
  head: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    padding: 16, borderBottomWidth: 1, borderBottomColor: theme.color.divider,
  },
  eyebrow: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  pausedNote: { color: theme.color.textMuted, fontSize: 11, marginTop: 4 },
  noVideoCard: {
    flexDirection: "row", alignItems: "center", gap: 10,
    padding: 12, marginTop: 12, borderRadius: 10,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  noVideoT: { color: theme.color.text, fontSize: 13, fontWeight: "800" },
  noVideoS: { color: theme.color.textMuted, fontSize: 11, marginTop: 2, lineHeight: 15 },
  title: { color: theme.color.text, fontSize: 18, fontWeight: "800" },
  subtle: { color: theme.color.textMuted, fontSize: 12, marginTop: 6, lineHeight: 17 },
  h: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5, marginBottom: 8 },
  line: { flexDirection: "row", gap: 10, marginBottom: 6 },
  n: { color: theme.color.brand, fontSize: 12, fontWeight: "900", width: 18 },
  lineT: { color: theme.color.text, fontSize: 13, lineHeight: 18, flex: 1 },
  cueLine: { flexDirection: "row", gap: 10, alignItems: "center", marginBottom: 6 },
  mistakeLine: { flexDirection: "row", gap: 10, alignItems: "center", marginBottom: 6 },
  swapBtn: {
    marginTop: 20, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    padding: 12, borderRadius: 10,
    backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand,
  },
  swapBtnT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  altCard: {
    flexDirection: "row", alignItems: "center", gap: 12,
    padding: 14, marginTop: 10, borderRadius: 10,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  altName: { color: theme.color.text, fontSize: 13, fontWeight: "800" },
  altReason: { color: theme.color.textMuted, fontSize: 11, marginTop: 3, lineHeight: 15 },
  // Iter189g · Purpose badge — small chip above alt name.
  altBadge: {
    alignSelf: "flex-start", paddingHorizontal: 8, paddingVertical: 3,
    borderRadius: 4, borderWidth: 1, marginBottom: 4,
  },
  altBadgeT: { fontSize: 9, fontWeight: "900", letterSpacing: 1.2 },
  // Iter189g · Explicit SWAP button per alternative (previously the
  // whole card was pressable, which felt ambiguous).
  swapPickBtn: {
    paddingHorizontal: 14, paddingVertical: 10, borderRadius: 8,
    backgroundColor: theme.color.brand, minWidth: 72, alignItems: "center",
  },
  swapPickBtnT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 1.5 },
  // Iter189g · Empty state block for the "No alternatives" case.
  empty: {
    alignItems: "center", padding: 32, marginTop: 20,
    borderRadius: 12, backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border, borderStyle: "dashed",
  },
  emptyT: {
    color: theme.color.text, fontSize: 14, fontWeight: "800",
    marginTop: 10, textAlign: "center",
  },
  emptyM: {
    color: theme.color.textMuted, fontSize: 12, lineHeight: 18,
    marginTop: 8, textAlign: "center",
  },
  emptyBtn: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: 18, paddingVertical: 12, borderRadius: 10,
    backgroundColor: theme.color.brand, marginTop: 18,
  },
  emptyBtnT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 1.5 },
  footer: {
    position: "absolute", bottom: 0, left: 0, right: 0,
    padding: 16, paddingBottom: 24,
    backgroundColor: theme.color.surface,
    borderTopWidth: 1, borderTopColor: theme.color.divider,
  },
  resumeBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    padding: 14, borderRadius: 12, backgroundColor: theme.color.brand,
  },
  resumeBtnT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 1.5 },
});
