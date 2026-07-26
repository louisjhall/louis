/**
 * Atlas Guided Flow — step-by-step follow-along player.
 * Reuses the SAME workout data + logging endpoints as Manual Mode.
 *
 * Flow: warm-up → exercise 1 (set 1 → rest → set 2 → rest → set 3) → next exercise → complete.
 * Every set is logged to /workouts/{id}/sets, same as Manual Mode.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput,
  ActivityIndicator, Image, Modal, Vibration, Dimensions, Alert,
} from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { ExerciseVideoPlayer } from "@/src/components/ExerciseVideoPlayer";
import { WorkoutMediaCarousel } from "@/src/components/WorkoutMediaCarousel";
import { PostWorkoutRatingSheet } from "@/src/components/PostWorkoutRatingSheet";
import { RestTimer } from "@/src/components/RestTimer";
import {
  getAutoContinue, getSoundOn, setAutoContinue as saveAutoContinue,
  getAutoRest, getVoiceOn, setVoiceOn as saveVoiceOn,
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
 *   the exercise (or fall back to 60s).
 * - Weighted / bodyweight sets: rough tempo of ~3s per rep, clamped 20-90s
 *   so a 5-rep heavy set doesn't fly by and a 20-rep set doesn't drag on.
 */
function autopilotWorkSeconds(ex: any, targetReps: number, isCardio: boolean): number {
  const explicit = parseInt(String(ex?.work_sec || ex?.duration_sec || 0), 10);
  if (explicit && explicit > 0) return Math.max(10, Math.min(600, explicit));
  if (isCardio) return 60;
  const est = Math.round((targetReps || 10) * 3);
  return Math.max(20, Math.min(90, est));
}

function isCardioExercise(ex: any): boolean {
  if (!ex) return false;
  if (ex.logging_type === "cardio" || ex.logging_type === "timer") return true;
  const hay = `${ex.name || ""} ${ex.reps || ""} ${ex.duration || ""} ${ex.category || ""}`.toLowerCase();
  // Strict cardio patterns — exclude "row" alone since "bent-over row" is weighted.
  return /\b(run|running|jog|zone\s?[235]|intervals?|tempo|treadmill|rowing|bike|cycling|assault|erg|swim|sprint|ez pace|long run|fartlek)\b/.test(hay);
}

// Iter 94t (Phase 2) — Mobility / stretch exercises deserve slower image
// auto-scroll (5–7s) so clients can actually study each position.
function isMobilityLike(ex: any): boolean {
  if (!ex) return false;
  const hay = `${ex.name || ""} ${ex.category || ""} ${ex.section || ""}`.toLowerCase();
  return /\b(mobility|stretch|flow|breath|activation|cool.?down|warm.?up|rock|rotation|open.?book|hip.?flex|thoracic|foam|glute.?bridge|cat.?cow)\b/.test(hay);
}

function parseTargetReps(ex: any): number {
  const r = String(ex?.reps || "").trim();
  const first = r.split(/[-\s]/)[0];
  const n = parseInt(first, 10);
  return isNaN(n) ? 10 : n;
}

export default function GuidedFlow() {
  const { id } = useLocalSearchParams<{ id: string }>();
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
  // Iter 94t (Phase 2) — When the client opens the demo/how-to sheet during
  // a work set, we auto-pause the workout so they can actually study the
  // video. On close we restore whatever paused state they were in before.
  const pausedBeforeHowTo = useRef<boolean>(false);
  const openHowTo = useCallback(() => {
    pausedBeforeHowTo.current = paused;
    setPaused(true);
    setHowToOpen(true);
  }, [paused]);
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

  // Load workout + settings
  useEffect(() => {
    warmupSoundEngine(); // Pre-warm native audio players so first cue has no lag.
    (async () => {
      const [w, ac, ar, so, vo] = await Promise.all([
        api<any>(`/workouts/${id}`),
        getAutoContinue(),
        getAutoRest(),
        getSoundOn(),
        getVoiceOn(),
      ]);
      setWorkout(w);
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
  }, [id]);

  const totalExercises = workout?.exercises?.length || 0;
  const currentEx = workout?.exercises?.[exIdx];
  const isCardio = isCardioExercise(currentEx);
  const targetSets = Math.max(1, parseInt(String(currentEx?.sets || 3), 10));
  const targetReps = parseTargetReps(currentEx);
  const restSec = Math.max(15, parseInt(String(currentEx?.rest_sec || 90), 10));
  const isLastSet = setIdx >= targetSets;
  const isLastExercise = exIdx >= totalExercises - 1;
  const workSec = autopilotWorkSeconds(currentEx, targetReps, isCardio);
  const isAutopilot = logMode === "autopilot";

  // Fetch content + previous performance whenever exercise changes
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
    setLogMode(mode);
    // Force auto-continue after rest ON when the client picks autopilot so
    // the workout truly flows without any tapping needed.
    if (mode === "autopilot") {
      setAutoCont(true);
      setAutoRest(true);
    }
    if (Array.isArray(workout?.warmup) && workout.warmup.length > 0) {
      setPhase("warmup");
      setWarmupIdx(0);
    } else {
      setPhase("work");
    }
  }, [workout]);

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
        target_reps: String(targetReps),
      };
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

  // Media priority: custom_image → coach_image → video thumb → placeholder
  const media = useMemo(() => {
    if (!content && !currentEx) return null;
    return content?.custom_image_b64 || content?.coach_image_url || null;
  }, [content, currentEx]);

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
        exercise={currentEx}
        content={content}
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
            const r = await api<{ workout: any }>(`/workouts/${id}/swap-exercise`, {
              method: "POST",
              body: { exercise_index: exIdx, new_name: newName, reason: reason || null },
            });
            if (r?.workout) setWorkout(r.workout);
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
  item, index, total, timeLeft, paused, onSkipItem, onSkipAll, nextUp,
}: {
  item: any; index: number; total: number; timeLeft: number; paused: boolean;
  onSkipItem: () => void; onSkipAll: () => void; nextUp: string;
}) {
  const [content, setContent] = useState<any>(null);
  useEffect(() => {
    if (!item?.name) return;
    setContent(null);
    api<any>(`/exercises/content?name=${encodeURIComponent(item.name)}`)
      .then((r) => setContent(r?.exercise || null)).catch(() => setContent(null));
  }, [item?.name]);
  const total_sec = Math.max(10, parseInt(String(item.duration_sec || 30), 10));
  const pct = Math.round(((total_sec - timeLeft) / total_sec) * 100);
  const img = content?.custom_image_b64 || content?.coach_image_url;
  const cues = Array.isArray(content?.cues) ? content.cues : [];

  return (
    <View>
      <Text style={styles.phaseLabel}>WARM-UP</Text>
      <Text style={styles.exName}>{item.name}</Text>
      <Text style={styles.exMeta}>Move {index} of {total}</Text>

      <View style={styles.mediaBox}>
        <WorkoutMediaCarousel
          exerciseName={item?.name || ""}
          height={180}
          autoScroll={!paused}
          autoScrollIntervalMs={6000}
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
  ex, setIdx, targetSets, targetReps, cue, media, prev, isCardio,
  logWeight, setLogWeight, logReps, setLogReps, logRpe, setLogRpe, logNote, setLogNote,
  saving, paused, autopilot, workTimer, workSec,
  onTogglePause, onComplete, onHowTo, onSwap,
}: any) {
  const suggested = prev?.suggested_load;
  const suggestedT = suggested ? `${suggested}kg × ${targetReps}` : null;
  const progReason = prev?.progression_hint?.reason;
  const workPct = workSec ? Math.max(0, Math.min(100, Math.round(((workSec - workTimer) / workSec) * 100))) : 0;

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
        {isCardio ? "" : ` · ${targetReps} reps`}
      </Text>

      <View style={styles.mediaBox}>
        <WorkoutMediaCarousel
          exerciseName={ex?.name || ""}
          height={200}
          autoScroll={!paused && (isCardio || isMobilityLike(ex) || autopilot)}
          autoScrollIntervalMs={isMobilityLike(ex) ? 6000 : 4000}
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

          {/* Log inputs */}
          {isCardio ? (
            <View style={styles.logGrid}>
              <LogInput label="TIME (mm:ss)" value={logWeight} onChangeText={setLogWeight} placeholder="30:00" />
              <LogInput label="DIST (km)" value={logReps} onChangeText={setLogReps} placeholder="5.0" />
              <LogInput label="RPE" value={logRpe} onChangeText={setLogRpe} placeholder="1-10" />
            </View>
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
          <View style={sheetStyles.head}>
            <View style={{ flex: 1 }}>
              <Text style={sheetStyles.eyebrow}>PAUSED · LEARN THIS EXERCISE</Text>
              <Text style={sheetStyles.pausedNote}>
                Your workout is paused. Tap RESUME when you&apos;re ready.
              </Text>
            </View>
            <Pressable onPress={onClose} hitSlop={12} testID="gf-howto-close"><Ionicons name="close" size={22} color={theme.color.text} /></Pressable>
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
  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={sheetStyles.root}>
        <Pressable style={sheetStyles.backdrop} onPress={onClose} />
        <View style={sheetStyles.sheet}>
          <View style={sheetStyles.head}>
            <Text style={sheetStyles.eyebrow}>SWAP EXERCISE</Text>
            <Pressable onPress={onClose} hitSlop={12}><Ionicons name="close" size={22} color={theme.color.text} /></Pressable>
          </View>
          <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 24 }}>
            <Text style={sheetStyles.title}>{exercise?.name}</Text>
            <Text style={sheetStyles.subtle}>
              Atlas suggests alternatives with the same movement pattern and muscle group.
            </Text>
            {loading && <ActivityIndicator color={theme.color.brand} style={{ marginTop: 20 }} />}
            {!loading && alts.length === 0 && (
              <Text style={{ color: theme.color.textMuted, marginTop: 20, fontStyle: "italic" }}>
                No alternatives available for this move.
              </Text>
            )}
            {alts.map((alt, i) => (
              <Pressable
                key={i}
                style={sheetStyles.altCard}
                onPress={() => onSwapped({ ...exercise, name: alt.name, notes: alt.reason }, alt.reason)}
              >
                <View style={{ flex: 1 }}>
                  <Text style={sheetStyles.altName}>{alt.name}</Text>
                  <Text style={sheetStyles.altReason} numberOfLines={2}>{alt.reason}</Text>
                </View>
                <Ionicons name="arrow-forward" size={16} color={theme.color.brand} />
              </Pressable>
            ))}
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
  eyebrow: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 2.5 },
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
  wMeta: { color: theme.color.textMuted, fontSize: 10, fontWeight: "800", letterSpacing: 1.5, marginTop: 2 },
  progressTrack: { height: 3, backgroundColor: theme.color.surface3 },
  progressFill: { height: 3, backgroundColor: theme.color.brand },
  body: { padding: 20, paddingBottom: 40 },

  phaseLabel: {
    color: theme.color.brand,
    fontSize: 11, fontWeight: "900", letterSpacing: 3, marginBottom: 8,
  },
  exName: { color: theme.color.text, fontSize: 26, fontWeight: "900", letterSpacing: -0.5 },
  exMeta: { color: theme.color.textMuted, fontSize: 12, marginTop: 6, fontWeight: "700", letterSpacing: 1 },

  mediaBox: {
    marginTop: 16, borderRadius: 14, overflow: "hidden",
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  mediaImg: { width: "100%", height: SCREEN_W * 0.55 },
  mediaFallback: { height: SCREEN_W * 0.55, alignItems: "center", justifyContent: "center" },
  mediaFbT: { color: theme.color.textMuted, fontSize: 10, fontWeight: "800", letterSpacing: 1.5, marginTop: 8 },

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
  prevHead: { color: theme.color.textMuted, fontSize: 9, fontWeight: "900", letterSpacing: 1.5 },
  prevBig: { color: theme.color.text, fontSize: 16, fontWeight: "900", marginTop: 6 },
  prevSub: { color: theme.color.textMuted, fontSize: 10, marginTop: 4, fontStyle: "italic" },

  logGrid: { flexDirection: "row", gap: 8, marginTop: 16 },
  logField: { flex: 1 },
  logFieldLbl: { color: theme.color.textMuted, fontSize: 9, fontWeight: "900", letterSpacing: 1.5, marginBottom: 4 },
  logInput: {
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
    borderRadius: 8, padding: 10,
    color: theme.color.text, fontSize: 15, fontWeight: "800", textAlign: "center",
  },
  noteInput: {
    marginTop: 10, backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border, borderRadius: 8,
    padding: 10, color: theme.color.text, fontSize: 13,
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

  restBig: { color: theme.color.brand, fontSize: 96, fontWeight: "900", fontVariant: ["tabular-nums"], textAlign: "center", marginTop: 20 },
  restHint: { color: theme.color.textMuted, fontSize: 12, textAlign: "center", marginTop: 8, letterSpacing: 1 },
  countdownBox: { marginTop: 40, alignItems: "center" },
  countdownT: { color: theme.color.brand, fontSize: 160, fontWeight: "900" },

  autoContRow: { flexDirection: "row", alignItems: "center", gap: 10, marginTop: 20, justifyContent: "center" },
  autoContT: { color: theme.color.text, fontSize: 12, fontWeight: "600" },
  autopilotHint: {
    color: theme.color.brand, fontSize: 10, fontWeight: "900",
    letterSpacing: 2, textAlign: "center", marginTop: 14,
  },
  check: {
    width: 22, height: 22, borderRadius: 6,
    borderWidth: 1.5, borderColor: theme.color.border,
    alignItems: "center", justifyContent: "center",
  },
  checkOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },

  pausedHint: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 2, textAlign: "center", marginTop: 12, fontWeight: "800" },
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
  nextUpEyebrow: { color: theme.color.brand, fontSize: 9, fontWeight: "900", letterSpacing: 2 },
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
  summaryL: { color: theme.color.textMuted, fontSize: 10, fontWeight: "900", letterSpacing: 1.5, marginTop: 4 },
  atlasSummary: {
    marginTop: 24, padding: 16, borderRadius: 12,
    backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand,
  },
  atlasEyebrow: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 2 },
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
  head: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    padding: 16, borderBottomWidth: 1, borderBottomColor: theme.color.divider,
  },
  eyebrow: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 2 },
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
  h: { color: theme.color.brand, fontSize: 9, fontWeight: "900", letterSpacing: 1.5, marginBottom: 8 },
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
