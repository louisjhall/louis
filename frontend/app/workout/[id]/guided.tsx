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
  ActivityIndicator, Image, Modal, Vibration, Dimensions,
} from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { ExerciseVideoPlayer } from "@/src/components/ExerciseVideoPlayer";
import { RestTimer } from "@/src/components/RestTimer";
import { getAutoContinue, getSoundOn, setAutoContinue as saveAutoContinue, getAutoRest } from "@/src/lib/workoutMode";
import { hapticSuccess } from "@/src/lib/haptics";
import { playWorkoutComplete } from "@/src/lib/sounds";

const { width: SCREEN_W } = Dimensions.get("window");

type Phase = "loading" | "warmup" | "work" | "rest" | "complete";

function fmtMMSS(sec: number): string {
  const m = Math.max(0, Math.floor(sec / 60));
  const s = Math.max(0, sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function isCardioExercise(ex: any): boolean {
  if (!ex) return false;
  if (ex.logging_type === "cardio" || ex.logging_type === "timer") return true;
  const hay = `${ex.name || ""} ${ex.reps || ""} ${ex.duration || ""} ${ex.category || ""}`.toLowerCase();
  // Strict cardio patterns — exclude "row" alone since "bent-over row" is weighted.
  return /\b(run|running|jog|zone\s?[235]|intervals?|tempo|treadmill|rowing|bike|cycling|assault|erg|swim|sprint|ez pace|long run|fartlek)\b/.test(hay);
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
  const [previousLabel, setPreviousLabel] = useState<string>("");
  const [howToOpen, setHowToOpen] = useState(false);
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
  const restSeconds = useRef<number>(0);

  // Load workout + settings
  useEffect(() => {
    (async () => {
      const [w, ac, ar, so] = await Promise.all([
        api<any>(`/workouts/${id}`),
        getAutoContinue(),
        getAutoRest(),
        getSoundOn(),
      ]);
      setWorkout(w);
      setAutoCont(ac);
      setAutoRest(ar);
      setSoundOn(so);
      // Start with warmup if any, else jump to first exercise
      if (Array.isArray(w.warmup) && w.warmup.length > 0) {
        setPhase("warmup");
        setWarmupIdx(0);
      } else {
        setPhase("work");
      }
    })().catch(() => setPhase("work"));
    return () => {
      if (restTick.current) clearInterval(restTick.current);
      if (warmupTick.current) clearInterval(warmupTick.current);
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
  }, [currentEx?.name, phase, exIdx, targetReps]);

  // Warmup timer
  useEffect(() => {
    if (phase !== "warmup" || paused) return;
    const item = workout?.warmup?.[warmupIdx];
    if (!item) return;
    const dur = Math.max(10, parseInt(String(item.duration_sec || 30), 10));
    setWarmupTimer(dur);
    if (warmupTick.current) clearInterval(warmupTick.current);
    warmupTick.current = setInterval(() => {
      setWarmupTimer((s) => {
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
  const completeSet = async () => {
    if (saving) return;
    setSaving(true);
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
        const t = logWeight.split(":").map((n) => parseInt(n, 10));
        const timeSec = t.length === 2 ? t[0] * 60 + (t[1] || 0) : (parseFloat(logWeight) * 60 || null);
        const distKm = parseFloat(logReps);
        body.logging_type = "cardio";
        if (timeSec) body.duration_sec = timeSec;
        if (!isNaN(distKm)) body.distance_m = Math.round(distKm * 1000);
        if (logRpe) body.rpe = parseFloat(logRpe);
      } else {
        body.actual_weight = parseFloat(logWeight) || null;
        body.actual_reps = parseInt(logReps, 10) || null;
        body.rpe = parseFloat(logRpe) || null;
      }
      if (logNote.trim()) body.notes = logNote.trim();
      const r = await api<any>(`/workouts/${id}/sets`, { method: "POST", body });
      setLogs((all) => [...all, r.set]);

      // Reset log inputs for next set
      setLogNote("");
      // Keep weight, reset RPE
      setLogRpe("");

      if (isLastSet && isLastExercise) {
        hapticSuccess();
        playWorkoutComplete();
        setPhase("complete");
      } else if (autoRest) {
        startRest(restSec, `${currentEx.name} Set ${setIdx} complete`);
      } else {
        // Skip rest — advance immediately
        goToNextSetOrExercise();
      }
    } catch (e: any) {
      // Non-blocking — user can retry
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
              autoContinueOverride={autoCont}
              size={260}
            />
            <Pressable onPress={toggleAutoCont} style={styles.autoContRow} testID="gf-auto-toggle">
              <View style={[styles.check, autoCont && styles.checkOn]}>
                {autoCont && <Ionicons name="checkmark" size={14} color="#fff" />}
              </View>
              <Text style={styles.autoContT}>Auto-continue after rest</Text>
            </Pressable>
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
            onComplete={completeSet}
            onHowTo={() => setHowToOpen(true)}
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
        onClose={() => setHowToOpen(false)}
        onSwap={() => { setHowToOpen(false); setSwapOpen(true); }}
      />

      {/* Swap sheet */}
      <SwapSheet
        visible={swapOpen}
        workoutId={String(id)}
        exercise={currentEx}
        onClose={() => setSwapOpen(false)}
        onSwapped={(newEx) => {
          setSwapOpen(false);
          // Update workout in place
          setWorkout((w: any) => ({
            ...w,
            exercises: w.exercises.map((e: any, i: number) => (i === exIdx ? { ...e, ...newEx } : e)),
          }));
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
        {img ? (
          <Image source={{ uri: img }} style={styles.mediaImg} resizeMode="cover" />
        ) : (
          <View style={styles.mediaFallback}>
            <Ionicons name="flame" size={60} color={theme.color.brand} />
            <Text style={styles.mediaFbT}>WARM-UP IMAGE COMING</Text>
          </View>
        )}
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
  saving, onComplete, onHowTo, onSwap,
}: any) {
  const suggested = prev?.suggested_load;
  const suggestedT = suggested ? `${suggested}kg × ${targetReps}` : null;
  const progReason = prev?.progression_hint?.reason;

  return (
    <View>
      <Text style={styles.phaseLabel}>WORK</Text>
      <Text style={styles.exName}>{ex?.name}</Text>
      <Text style={styles.exMeta}>Set {setIdx} of {targetSets} · {targetReps} reps</Text>

      <View style={styles.mediaBox}>
        {media ? (
          <Image source={{ uri: media }} style={styles.mediaImg} resizeMode="cover" />
        ) : (
          <View style={styles.mediaFallback}>
            <Ionicons name="body" size={70} color={theme.color.brand} />
            <Text style={styles.mediaFbT}>ATLAS IMAGE COMING</Text>
          </View>
        )}
      </View>

      <View style={styles.cueBox}>
        <Ionicons name="chatbubble-ellipses" size={12} color={theme.color.brand} />
        <Text style={styles.cueT}>{cue}</Text>
      </View>

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

      <View style={styles.rowActions}>
        <Pressable onPress={onHowTo} style={styles.secondaryBtn} testID="gf-howto">
          <Ionicons name="book" size={14} color={theme.color.brand} />
          <Text style={styles.secondaryBtnT}>HOW TO</Text>
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
            <Text style={sheetStyles.eyebrow}>HOW TO</Text>
            <Pressable onPress={onClose} hitSlop={12}><Ionicons name="close" size={22} color={theme.color.text} /></Pressable>
          </View>
          <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 24 }}>
            <Text style={sheetStyles.title}>{exercise?.name}</Text>
            {hasVideo && (
              <View style={{ marginTop: 12, borderRadius: 12, overflow: "hidden" }}>
                <ExerciseVideoPlayer exerciseName={exercise?.name || ""} />
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
  visible: boolean; workoutId: string; exercise: any; onClose: () => void; onSwapped: (ex: any) => void;
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
                onPress={() => onSwapped({ ...exercise, name: alt.name, notes: alt.reason })}
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
  const [saving, setSaving] = useState(false);
  const totalVolume = logs.reduce((sum, s) => sum + ((s.actual_weight || 0) * (s.actual_reps || 0)), 0);
  const rpes = logs.map((s) => s.rpe).filter((v) => typeof v === "number");
  const avgRpe = rpes.length ? (rpes.reduce((a, b) => a + b, 0) / rpes.length).toFixed(1) : "—";
  const setsCompleted = logs.length;

  useEffect(() => {
    (async () => {
      if (saving) return;
      setSaving(true);
      // Fire the completion cue as soon as user lands on this screen
      playWorkoutComplete(); hapticSuccess();
      try {
        await api<any>(`/workouts/${workout.id}/complete`, {
          method: "POST",
          body: { rpe: rpes.length ? Math.round(rpes.reduce((a, b) => a + b, 0) / rpes.length) : null, notes: null },
        });
      } catch { /* ignore */ } finally { setSaving(false); }
    })();
  // eslint-disable-next-line react-hooks/exhaustive-deps
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
          <Text style={styles.atlasEyebrow}>ATLAS SUMMARY</Text>
          <Text style={styles.atlasBody}>
            You completed {setsCompleted} logged {setsCompleted === 1 ? "set" : "sets"} across {workout.exercises?.length || 0} exercises in {durationMin} minutes.
            {totalVolume ? ` Total load lifted: ${Math.round(totalVolume)}kg.` : ""}
            {avgRpe !== "—" && Number(avgRpe) <= 8
              ? " Effort looks controlled — Atlas will progress the load next session."
              : avgRpe !== "—" && Number(avgRpe) >= 9
              ? " Effort was high today — Atlas will hold the load next session to consolidate."
              : ""}
          </Text>
        </View>

        <Pressable onPress={onDone} style={styles.doneBtn} testID="gf-complete-done">
          <Text style={styles.doneBtnT}>DONE</Text>
        </Pressable>
      </ScrollView>
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
  check: {
    width: 22, height: 22, borderRadius: 6,
    borderWidth: 1.5, borderColor: theme.color.border,
    alignItems: "center", justifyContent: "center",
  },
  checkOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },

  pausedHint: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 2, textAlign: "center", marginTop: 12, fontWeight: "800" },

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
});
