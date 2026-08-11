/**
 * Manual Session — Trainerize-style vertical scrollable list.
 *
 * Every exercise, every set, and every rest period is visible on a single
 * scrollable page. Each set row has inline logging fields (weight / reps /
 * RPE) with a checkmark to save. Tapping the exercise header or image opens
 * a detail sheet with the primary image, coaching points, video and
 * alternatives.
 *
 * Logging uses POST /workouts/{id}/sets — identical to the Guided flow —
 * so nothing changes on the server side.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput,
  ActivityIndicator, Modal, Image, Alert,
} from "react-native";
import { useLocalSearchParams, useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api, API_BASE, getToken } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { ExerciseVideoPlayer } from "@/src/components/ExerciseVideoPlayer";
import { RestTimer } from "@/src/components/RestTimer";
import { hapticSuccess } from "@/src/lib/haptics";
import { PostWorkoutRatingSheet } from "@/src/components/PostWorkoutRatingSheet";
import { formatPrescription, inferPrescription } from "@/src/lib/formatPrescription";

/* -------------------------------------------------------------------------- */
/*  Types & helpers                                                            */
/* -------------------------------------------------------------------------- */
type ExRow = {
  name: string;
  sets?: number;
  reps?: string | number;
  rest_sec?: number;
  duration_sec?: number;
  duration?: string;
  load?: string | number;      // prescription: kg / bodyweight / "3RM" etc.
  rpe?: number | string;       // prescribed RPE (may exist without weight)
  section?: "warmup" | "main" | "cooldown";
  logging_type?: string;
  cue?: string;
  notes?: string;
  alternative_exercise_id?: string;
  exercise_id?: string;
};

/**
 * Iter 161 · Per-field column resolver — drives which columns the sets
 * table shows for THIS exercise, based only on prescription data that
 * actually exists. Prevents mobility drills from getting a "DIST km"
 * column and rep-only drills from getting a "kg" column when no load is
 * prescribed.
 */
type ColSpec = { key: "weight" | "reps" | "duration" | "distance" | "rpe";
                 label: string; width?: number; flex?: number };

function _isCardioName(name?: string, reps?: any, duration?: string): boolean {
  const hay = `${name || ""} ${reps || ""} ${duration || ""}`.toLowerCase();
  // Iter 165c · Walking variants (Easy Walk, Zone 1 Walk, Power Walk, Ruck,
  // Hike, Incline Walk, Stair Climb, StairMaster) were previously routed
  // through the STRENGTH log (kg + reps). They must render as CARDIO
  // (distance/time). "Walk" is matched with a word boundary so we don't
  // accidentally match "walking lunge" — checked separately below.
  return /\b(run|running|jog|zone\s?[1235]|intervals?|tempo|treadmill|rowing|bike|cycling|assault|erg|swim|sprint|ez pace|long run|fartlek|walk|walking|hike|hiking|ruck|rucking|stair|stairs|stairmaster|stepper|incline\s?walk|power\s?walk|brisk\s?walk|recovery\s?walk|zone\s?1|z1|zone\s?2|z2)\b/.test(hay)
    // Exclude "walking lunge" / "walking plank" — those are strength
    // patterns even though they include the word "walk".
    && !/\b(walking\s+(lunge|plank|push|dead\s?bug))\b/.test(hay);
}

function resolveCols(ex: ExRow): ColSpec[] {
  const cols: ColSpec[] = [];
  const isCardio = ex.logging_type === "cardio" || _isCardioName(ex.name, ex.reps, ex.duration);
  const hasReps = ex.reps != null && String(ex.reps).trim() !== "";
  const hasDuration =
    (typeof ex.duration_sec === "number" && ex.duration_sec > 0) ||
    ex.logging_type === "timer" ||
    isCardio;
  const hasLoad =
    ex.load != null &&
    String(ex.load).trim() !== "" &&
    !["bw", "bodyweight", "n/a", "-"].includes(String(ex.load).toLowerCase());
  const nameLc = (ex.name || "").toLowerCase();
  const impliesLoad = /(dumbbell|barbell|kettlebell|kb|db|cable|machine|weighted|load)/.test(nameLc);
  // kg column: only when explicitly prescribed or implied by name — never on
  // pure cardio (running/rowing/etc).
  const showLoad = (hasLoad || impliesLoad) && !isCardio;
  const hasRpe = ex.rpe != null && String(ex.rpe).trim() !== "";

  // Iter 162 · Cleaner rule set (user spec):
  //   • duration + no reps → TIME + optional LOAD only (no REPS box)
  //   • reps + no duration → LOAD + REPS only (no TIME box)
  //   • both → LOAD + REPS + TIME
  //   • neither → LOAD + REPS as safe default
  //
  // Iter 165c · Cardio-specific override — for any cardio row (walking,
  // running, cycling, rowing…) the REPS box is meaningless: prescriptions
  // like "30 min" belong in the TIME column, not REPS. We hide REPS and
  // KG for cardio and always render TIME (+ DIST km, added below).
  if (isCardio) {
    cols.push({ key: "duration", label: "TIME", flex: 1 });
  } else if (hasDuration && !hasReps) {
    if (showLoad) cols.push({ key: "weight", label: "kg", width: 68 });
    cols.push({ key: "duration", label: "TIME", flex: 1 });
  } else if (hasReps && !hasDuration) {
    if (showLoad) cols.push({ key: "weight", label: "kg", width: 68 });
    cols.push({ key: "reps", label: "REPS", width: 58 });
  } else if (hasReps && hasDuration) {
    if (showLoad) cols.push({ key: "weight", label: "kg", width: 68 });
    cols.push({ key: "reps", label: "REPS", width: 58 });
    cols.push({ key: "duration", label: "TIME", width: 78 });
  } else {
    if (showLoad) cols.push({ key: "weight", label: "kg", width: 68 });
    cols.push({ key: "reps", label: "REPS", width: 58 });
  }

  // Iter 165c · For any cardio row (running, cycling, walking, rowing…)
  // always show the DIST km column so the client can log actual distance.
  // Previously we gated this on the name containing "km"/"mile"/"distance",
  // which meant "Easy Walk / 30 min" rendered without any distance field.
  if (isCardio) {
    cols.push({ key: "distance", label: "DIST km", flex: 1 });
  }

  if (hasRpe) cols.push({ key: "rpe", label: "RPE", width: 44 });
  return cols;
}

type SetInput = {
  reps: string;
  weight: string;
  rpe: string;
  duration: string;      // for cardio / timed sets ("MM:SS")
  distance: string;      // for cardio (km, converted to meters on save)
  logged: boolean;
  serverId?: string;
};

const ARR_INT = (n: any, fb = 3) => {
  const v = parseInt(String(n ?? ""), 10);
  return isNaN(v) || v <= 0 ? fb : v;
};

function isCardio(ex: ExRow | null | undefined): boolean {
  if (!ex) return false;
  if (ex.logging_type === "cardio" || ex.logging_type === "timer") return true;
  // Iter 165c · Delegate to the shared _isCardioName helper so cardio
  // detection stays consistent between the header/column resolver and
  // the save-time payload builder. Both used to have a copy-paste regex
  // that missed walking, hiking, and stair-climbing variants.
  return _isCardioName(ex.name, ex.reps, ex.duration);
}

function isTimed(ex: ExRow | null | undefined): boolean {
  if (!ex) return false;
  if (ex.logging_type === "timer") return true;
  if (ex.duration_sec && ex.duration_sec > 0) return true;
  return false;
}

function parseMMSS(v: string): number | null {
  if (!v) return null;
  const parts = v.split(":").map((p) => parseInt(p, 10));
  if (parts.length === 2 && !isNaN(parts[0]) && !isNaN(parts[1])) return parts[0] * 60 + parts[1];
  const n = parseFloat(v);
  return isNaN(n) ? null : Math.round(n * 60);
}

function fmtMMSS(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.max(0, sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

/**
 * PlayableTimePill — Iter 162
 *
 * A tap-to-count-down duration field for the manual workout log.
 *
 *   idle    : shows the client's typed value (or "mm:ss" placeholder). Tap
 *             to prime a countdown from the prescribed duration_sec.
 *   armed   : shows the prescribed time + a small play glyph. Tap to run.
 *   running : counts down every 250 ms; MM:SS displayed. Tap to pause.
 *   paused  : same as running but frozen. Tap to resume, long-press to reset.
 *   done    : stamps "mm:ss" into the log field via onChange, returns to idle.
 *
 * Uses a monotonic end-timestamp (Date.now()) so back-grounding briefly on
 * iOS/Android doesn't drift the countdown. No native modules, pure JS timer.
 */
function PlayableTimePill({
  value, prescribedSec, disabled, style, testID, onChange,
}: {
  value: string;
  prescribedSec?: number | null;
  disabled?: boolean;
  style?: any;
  testID?: string;
  onChange: (v: string) => void;
}) {
  type Mode = "idle" | "running" | "paused" | "done";
  const [mode, setMode] = useState<Mode>("idle");
  const [remaining, setRemaining] = useState<number>(() =>
    typeof prescribedSec === "number" && prescribedSec > 0 ? prescribedSec : 0,
  );
  const endRef = useRef<number>(0);
  const tickRef = useRef<any>(null);

  const stopTick = () => {
    if (tickRef.current) {
      clearInterval(tickRef.current);
      tickRef.current = null;
    }
  };

  const startTick = useCallback((from: number) => {
    endRef.current = Date.now() + from * 1000;
    stopTick();
    tickRef.current = setInterval(() => {
      const rem = Math.max(0, Math.round((endRef.current - Date.now()) / 1000));
      setRemaining(rem);
      if (rem <= 0) {
        stopTick();
        // Stamp the completed prescribed time into the log field.
        const stamp = fmtMMSS(prescribedSec || 0);
        onChange(stamp);
        setMode("done");
      }
    }, 250) as any;
  }, [onChange, prescribedSec]);

  useEffect(() => () => stopTick(), []);

  const handleTap = () => {
    if (disabled) return;
    if (!prescribedSec || prescribedSec <= 0) return; // no countdown available
    if (mode === "idle" || mode === "done") {
      setRemaining(prescribedSec);
      setMode("running");
      startTick(prescribedSec);
    } else if (mode === "running") {
      stopTick();
      setMode("paused");
    } else if (mode === "paused") {
      setMode("running");
      startTick(remaining);
    }
  };

  const handleLongPress = () => {
    if (disabled) return;
    // Long-press = reset back to prescribed value.
    stopTick();
    setRemaining(prescribedSec || 0);
    setMode("idle");
  };

  // If there's NO prescribed duration, degrade gracefully to a plain
  // TextInput so the client can still type an MM:SS value.
  if (!prescribedSec || prescribedSec <= 0) {
    return (
      <TextInput
        style={style}
        value={value}
        placeholder="mm:ss"
        placeholderTextColor={theme.color.textDim}
        onChangeText={onChange}
        editable={!disabled}
        testID={testID}
      />
    );
  }

  const display = mode === "running" || mode === "paused"
    ? fmtMMSS(remaining)
    : (value || fmtMMSS(prescribedSec));
  const glyph = mode === "running" ? "pause" : mode === "paused" ? "play" : "play-circle";
  const tint =
    mode === "running" ? theme.color.brand :
    mode === "done"    ? theme.color.green :
    theme.color.text;

  return (
    <Pressable
      onPress={handleTap}
      onLongPress={handleLongPress}
      disabled={disabled}
      style={[
        style,
        pillStyles.wrap,
        mode === "running" && pillStyles.wrapRunning,
        mode === "done" && pillStyles.wrapDone,
      ]}
      testID={testID}
      hitSlop={4}
    >
      <Ionicons name={glyph as any} size={13} color={tint} />
      <Text style={[pillStyles.txt, { color: tint }]}>{display}</Text>
    </Pressable>
  );
}

const pillStyles = StyleSheet.create({
  wrap: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 4,
    paddingVertical: 6, paddingHorizontal: 8,
    borderRadius: 8, backgroundColor: "transparent",
  },
  wrapRunning: {
    backgroundColor: "rgba(163,24,46,0.12)",
  },
  wrapDone: {
    backgroundColor: "rgba(16,185,129,0.14)",
  },
  txt: {
    fontSize: 13, fontWeight: "800",
    fontVariant: ["tabular-nums"],
  },
});

/* -------------------------------------------------------------------------- */
/*  Screen                                                                     */
/* -------------------------------------------------------------------------- */
export default function ManualListSession() {
  const { id, variant: variantParam } = useLocalSearchParams<{ id: string; variant?: string }>();
  const router = useRouter();
  const [w, setW] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [existingSets, setExistingSets] = useState<any[]>([]);
  const [rateOpen, setRateOpen] = useState(false);
  const [detailFor, setDetailFor] = useState<ExRow | null>(null);
  // input state keyed by "section:index" -> array of set inputs
  const [inputs, setInputs] = useState<Record<string, SetInput[]>>({});

  /* --- Load workout + previous sets --- */
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ww, s] = await Promise.all([
        api<any>(`/workouts/${id}`),
        api<any>(`/workouts/${id}/sets`).catch(() => ({ sets: [] })),
      ]);
      // Traffic-Light variant overlay — same policy as play.tsx.
      let final = ww;
      const vKey = String(variantParam || "").toLowerCase();
      if (vKey === "amber" || vKey === "red") {
        try {
          let variantsBlob = ww?.variants;
          if (!variantsBlob || !variantsBlob.green || !variantsBlob[vKey]) {
            const r = await api<any>(`/workouts/${id}/variants`);
            variantsBlob = r?.variants || null;
          }
          const chosen = variantsBlob?.[vKey];
          if (chosen && Array.isArray(chosen.exercises) && chosen.exercises.length) {
            final = {
              ...ww,
              exercises: chosen.exercises,
              warmup: chosen.warmup || ww.warmup,
              cooldown: chosen.cooldown || ww.cooldown,
            };
          }
        } catch { /* fall through */ }
      }
      setW(final);
      setExistingSets(s.sets || []);
    } catch (e: any) {
      Alert.alert("Failed to load workout", e?.message || "Please try again.");
      router.back();
    } finally { setLoading(false); }
  }, [id, variantParam, router]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  /* --- Bucketed rows: warmup / main / cooldown ---
   *
   * We prefer explicit sections if the workout doc provides `warmup` /
   * `cooldown` arrays; otherwise everything is "main".
   */
  const groups = useMemo(() => {
    if (!w) return { warmup: [], main: [], cooldown: [] };
    const warm = (w.warmup || []) as ExRow[];
    const cool = (w.cooldown || []) as ExRow[];
    const main = ((w.exercises || []) as ExRow[]).filter(
      // Ignore exercises that are actually cool-down items already merged
      // into `exercises[]` by the importer (`section === "cooldown"`).
      (e) => (e?.section || "main") !== "cooldown",
    );
    return { warmup: warm, main, cooldown: cool };
  }, [w]);

  /* --- Seed inputs whenever exercises change --- */
  useEffect(() => {
    if (!w) return;
    setInputs((prev) => {
      const next: Record<string, SetInput[]> = { ...prev };
      const seedFor = (rows: ExRow[], section: string) => {
        rows.forEach((ex, i) => {
          const key = `${section}:${i}`;
          if (next[key]) return; // don't overwrite user edits
          const nSets = ARR_INT(ex.sets, 1);
          const cardio = isCardio(ex) || isTimed(ex);
          const arr: SetInput[] = [];
          for (let n = 0; n < nSets; n++) {
            arr.push({
              reps: "", weight: "", rpe: "",
              duration: cardio && ex.duration_sec ? fmtMMSS(ex.duration_sec) : "",
              distance: "",
              logged: false,
            });
          }
          next[key] = arr;
        });
      };
      seedFor(groups.warmup, "warmup");
      seedFor(groups.main, "main");
      seedFor(groups.cooldown, "cooldown");
      return next;
    });
  }, [w, groups]);

  /* --- Merge previously-logged sets into inputs so they appear as done --- */
  useEffect(() => {
    if (!existingSets.length) return;
    setInputs((prev) => {
      const next = { ...prev };
      // Match by exercise_index — that was written by the play flow. Since
      // the LIST view uses section:index keys, we map main-only for now.
      groups.main.forEach((_ex, i) => {
        const key = `main:${i}`;
        const arr = [...(next[key] || [])];
        const priorForEx = existingSets
          .filter((s) => s.exercise_index === i && !s.warmup)
          .sort((a, b) => (a.set_number || 0) - (b.set_number || 0));
        priorForEx.forEach((s) => {
          const idx = (s.set_number || 1) - 1;
          if (idx >= 0 && idx < arr.length && !arr[idx].logged) {
            arr[idx] = {
              reps: s.actual_reps != null ? String(s.actual_reps) : "",
              weight: s.actual_weight != null ? String(s.actual_weight) : "",
              rpe: s.rpe != null ? String(s.rpe) : "",
              duration: s.duration_sec ? fmtMMSS(s.duration_sec) : "",
              distance: s.distance_m ? String(s.distance_m / 1000) : "",
              logged: true,
              serverId: s.id,
            };
          }
        });
        next[key] = arr;
      });
      return next;
    });
  }, [existingSets, groups.main]);

  /* --- Set update handlers --- */
  const patchSet = (key: string, setIdx: number, patch: Partial<SetInput>) => {
    setInputs((prev) => {
      const arr = [...(prev[key] || [])];
      arr[setIdx] = { ...arr[setIdx], ...patch };
      return { ...prev, [key]: arr };
    });
  };

  const logSet = async (
    section: "warmup" | "main" | "cooldown",
    exIdx: number,
    setIdx: number,
    ex: ExRow,
  ) => {
    const key = `${section}:${exIdx}`;
    const arr = inputs[key] || [];
    const s = arr[setIdx];
    if (!s) return;

    const cardio = isCardio(ex) || isTimed(ex);
    // For strength: require at least reps or weight to log.
    if (!cardio && !s.reps && !s.weight && !s.rpe) {
      Alert.alert("Nothing to log", "Enter reps, weight or RPE first.");
      return;
    }

    // Backend uses exercise_index that refers to the main exercises array
    // (warmup rows are flagged via warmup=true). We approximate:
    //   * warmup → exercise_index=0, warmup=true (server uses this flag)
    //   * main → real index in groups.main
    //   * cooldown → offset after main (rare — coach usually doesn't log)
    const exercise_index =
      section === "main" ? exIdx :
      section === "warmup" ? exIdx :
      groups.main.length + exIdx;

    const durSec = cardio && s.duration ? parseMMSS(s.duration) : null;
    const distM = cardio && s.distance ? Math.round(parseFloat(s.distance) * 1000) : null;

    try {
      const r = await api<any>(`/workouts/${id}/sets`, {
        method: "POST",
        body: {
          workout_id: id,
          exercise_index,
          exercise_name: ex.name,
          set_number: setIdx + 1,
          target_reps: ex.reps != null ? String(ex.reps) : null,
          actual_reps: s.reps ? parseInt(s.reps, 10) : null,
          actual_weight: s.weight ? parseFloat(s.weight) : null,
          rpe: s.rpe ? parseFloat(s.rpe) : null,
          logging_type: cardio ? "cardio" : (ex.logging_type || null),
          duration_sec: durSec,
          distance_m: distM,
          warmup: section === "warmup",
        },
      });
      patchSet(key, setIdx, { logged: true, serverId: r?.set?.id });
      hapticSuccess();
    } catch (e: any) {
      Alert.alert("Log failed", e?.message || "Please try again.");
    }
  };

  const finish = () => setRateOpen(true);
  const onRateDone = () => {
    setRateOpen(false);
    router.replace(`/workout/${id}` as any);
  };

  /* --- Progress calc: completed main sets / total main sets --- */
  const progress = useMemo(() => {
    let done = 0, total = 0;
    groups.main.forEach((ex, i) => {
      const arr = inputs[`main:${i}`] || [];
      total += arr.length;
      done += arr.filter((a) => a.logged).length;
    });
    return { done, total, pct: total > 0 ? Math.round((done / total) * 100) : 0 };
  }, [groups.main, inputs]);

  if (loading || !w) {
    return (
      <SafeAreaView style={styles.root} edges={["top"]}>
        <ActivityIndicator style={{ marginTop: 60 }} color={theme.color.brand} />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      {/* Top bar */}
      <View style={styles.top}>
        <Pressable onPress={() => router.back()} testID="list-back" hitSlop={12}>
          <Ionicons name="chevron-back" size={26} color={theme.color.text} />
        </Pressable>
        <View style={{ flex: 1, alignItems: "center" }}>
          <Text style={styles.wName} numberOfLines={1}>{w.title || "Workout"}</Text>
          <Text style={styles.wMeta}>
            MANUAL · {progress.done}/{progress.total} sets · {progress.pct}%
          </Text>
        </View>
        <View style={{ width: 26 }} />
      </View>

      {/* Progress bar */}
      <View style={styles.progressTrack}>
        <View style={[styles.progressFill, { width: `${progress.pct}%` }]} />
      </View>

      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={{ paddingBottom: 140 }}
        keyboardShouldPersistTaps="handled"
      >
        {/* Warm-up section */}
        {groups.warmup.length > 0 && (
          <SectionHeader label="WARM-UP" count={groups.warmup.length} icon="thermometer" />
        )}
        {groups.warmup.map((ex, i) => (
          <ExerciseCard
            key={`w-${i}`}
            ex={ex}
            section="warmup"
            exIdx={i}
            inputs={inputs[`warmup:${i}`] || []}
            onPatch={(setIdx, patch) => patchSet(`warmup:${i}`, setIdx, patch)}
            onLog={(setIdx) => logSet("warmup", i, setIdx, ex)}
            onOpenDetail={() => setDetailFor(ex)}
          />
        ))}

        {/* Main section */}
        {groups.main.length > 0 && (
          <SectionHeader label="WORKOUT" count={groups.main.length} icon="barbell" />
        )}
        {groups.main.map((ex, i) => (
          <ExerciseCard
            key={`m-${i}`}
            ex={ex}
            section="main"
            exIdx={i}
            inputs={inputs[`main:${i}`] || []}
            onPatch={(setIdx, patch) => patchSet(`main:${i}`, setIdx, patch)}
            onLog={(setIdx) => logSet("main", i, setIdx, ex)}
            onOpenDetail={() => setDetailFor(ex)}
          />
        ))}

        {/* Cool-down */}
        {groups.cooldown.length > 0 && (
          <SectionHeader label="COOL-DOWN" count={groups.cooldown.length} icon="leaf" />
        )}
        {groups.cooldown.map((ex, i) => (
          <ExerciseCard
            key={`c-${i}`}
            ex={ex}
            section="cooldown"
            exIdx={i}
            inputs={inputs[`cooldown:${i}`] || []}
            onPatch={(setIdx, patch) => patchSet(`cooldown:${i}`, setIdx, patch)}
            onLog={(setIdx) => logSet("cooldown", i, setIdx, ex)}
            onOpenDetail={() => setDetailFor(ex)}
          />
        ))}

        {/* Finish button */}
        <Pressable style={styles.finishBtn} onPress={finish} testID="list-finish">
          <Ionicons name="checkmark-circle" size={18} color="#fff" />
          <Text style={styles.finishBtnT}>FINISH WORKOUT</Text>
        </Pressable>
        <Text style={styles.finishNote}>
          Sets you didn't log can still be added from the review screen.
        </Text>
      </ScrollView>

      {/* Detail sheet */}
      <ExerciseDetailSheet
        ex={detailFor}
        onClose={() => setDetailFor(null)}
      />

      {/* Post-workout rating */}
      <PostWorkoutRatingSheet
        visible={rateOpen}
        workoutId={String(id)}
        workoutTitle={w?.title}
        onClose={() => setRateOpen(false)}
        onDone={onRateDone}
      />
    </SafeAreaView>
  );
}

/* -------------------------------------------------------------------------- */
/*  Section header                                                             */
/* -------------------------------------------------------------------------- */
function SectionHeader({ label, count, icon }: { label: string; count: number; icon: any }) {
  return (
    <View style={styles.sectionHead}>
      <Ionicons name={icon} size={13} color={theme.color.brand} />
      <Text style={styles.sectionHeadT}>{label}</Text>
      <Text style={styles.sectionHeadCount}>{count}</Text>
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/*  Exercise card — image + header + sets table + rest chip                    */
/* -------------------------------------------------------------------------- */
function ExerciseCard({
  ex, section, exIdx, inputs, onPatch, onLog, onOpenDetail,
}: {
  ex: ExRow;
  section: "warmup" | "main" | "cooldown";
  exIdx: number;
  inputs: SetInput[];
  onPatch: (setIdx: number, patch: Partial<SetInput>) => void;
  onLog: (setIdx: number) => void;
  onOpenDetail: () => void;
}) {
  const cols = useMemo(() => resolveCols(ex), [ex]);
  const targetReps = ex.reps != null ? String(ex.reps) : (ex.duration_sec ? fmtMMSS(ex.duration_sec) : "—");
  const rest = ex.rest_sec || 0;
  const [restRunning, setRestRunning] = useState(false);

  // Meta line: only include the pieces that make sense for the prescription.
  // Iter 163 · use the deterministic formatPrescription helper for the
  // volume + unit portion so it never breaks under Amber/Red scaling.
  const metaBits: string[] = [];
  const prescriptionLine = formatPrescription({
    ...inferPrescription(ex),
    // If the exercise came from the JSON importer with explicit structured
    // fields (sets/volume/unit), those take precedence via inferPrescription.
    sets: ex.sets ?? inferPrescription(ex).sets ?? inputs.length,
  });
  if (prescriptionLine) {
    metaBits.push(prescriptionLine);
  } else {
    // No prescription at all — just show the set count so the client still
    // sees something meaningful in the card meta line.
    metaBits.push(`${inputs.length} set${inputs.length === 1 ? "" : "s"}`);
  }
  if (ex.load != null && String(ex.load).trim() && String(ex.load).toLowerCase() !== "bw")
    metaBits.push(String(ex.load));
  if (ex.rpe != null && String(ex.rpe).trim()) metaBits.push(`RPE ${ex.rpe}`);
  if (rest > 0) metaBits.push(`rest ${rest >= 60 ? `${Math.round(rest / 60)}m` : `${rest}s`}`);
  const metaLine = metaBits.join(" · ") +
    (ex.cue ? ` · ${String(ex.cue).slice(0, 40)}${(ex.cue || "").length > 40 ? "…" : ""}` : "");

  return (
    <View style={styles.card}>
      {/* Header — image + name/meta + chevron */}
      <Pressable onPress={onOpenDetail} style={styles.cardHead} testID={`list-ex-${section}-${exIdx}`}>
        <ExerciseImage name={ex.name} />
        <View style={{ flex: 1 }}>
          <Text style={styles.exName} numberOfLines={2}>{ex.name}</Text>
          <Text style={styles.exMeta} numberOfLines={2}>{metaLine}</Text>
        </View>
        <Ionicons name="chevron-forward" size={18} color={theme.color.textDim} />
      </Pressable>

      {/* Sets header row — driven by resolveCols() */}
      <View style={styles.setsHead}>
        <Text style={[styles.setsHeadCol, { width: 32 }]}>SET</Text>
        {cols.map((c) => (
          <Text
            key={c.key}
            style={[
              styles.setsHeadCol,
              c.width ? { width: c.width, textAlign: "right" } : { flex: c.flex ?? 1 },
            ]}
          >
            {c.label}
          </Text>
        ))}
        <View style={{ width: 40 }} />
      </View>

      {/* Set rows */}
      {inputs.map((s, i) => (
        <View key={i} style={[styles.setRow, s.logged && styles.setRowDone]}>
          <Text style={styles.setNum}>{i + 1}</Text>
          {cols.map((c) => {
            const commonStyle = c.width
              ? [styles.setInput, { width: c.width, textAlign: "right" as const }]
              : [styles.setInput, { flex: c.flex ?? 1 }];
            switch (c.key) {
              case "weight":
                return (
                  <TextInput
                    key="weight"
                    style={commonStyle}
                    value={s.weight}
                    placeholder="—"
                    placeholderTextColor={theme.color.textDim}
                    keyboardType="decimal-pad"
                    onChangeText={(t) => onPatch(i, { weight: t, logged: false })}
                    editable={!s.logged}
                    testID={`list-set-${section}-${exIdx}-${i}-weight`}
                  />
                );
              case "reps":
                return (
                  <TextInput
                    key="reps"
                    style={commonStyle}
                    value={s.reps}
                    placeholder={String(targetReps).replace(/[^0-9-]/g, "").split("-")[0] || "—"}
                    placeholderTextColor={theme.color.textDim}
                    keyboardType="number-pad"
                    onChangeText={(t) => onPatch(i, { reps: t, logged: false })}
                    editable={!s.logged}
                    testID={`list-set-${section}-${exIdx}-${i}-reps`}
                  />
                );
              case "duration":
                // Iter 162 · Playable Time Pill — tap to start a countdown
                // pre-filled from the exercise's `duration_sec`. The pill
                // renders the current MM:SS remaining while running, stamps
                // the final value into the log field on completion, and can
                // be paused / reset. Falls back to a plain text input when
                // the exercise has no prescribed duration (client can type).
                return (
                  <PlayableTimePill
                    key="duration"
                    style={commonStyle as any}
                    value={s.duration}
                    prescribedSec={ex.duration_sec}
                    disabled={!!s.logged}
                    testID={`list-set-${section}-${exIdx}-${i}-dur`}
                    onChange={(t) => onPatch(i, { duration: t, logged: false })}
                  />
                );
              case "distance":
                return (
                  <TextInput
                    key="distance"
                    style={commonStyle}
                    value={s.distance}
                    placeholder="—"
                    placeholderTextColor={theme.color.textDim}
                    keyboardType="decimal-pad"
                    onChangeText={(t) => onPatch(i, { distance: t, logged: false })}
                    editable={!s.logged}
                    testID={`list-set-${section}-${exIdx}-${i}-dist`}
                  />
                );
              case "rpe":
                return (
                  <TextInput
                    key="rpe"
                    style={commonStyle}
                    value={s.rpe}
                    placeholder="—"
                    placeholderTextColor={theme.color.textDim}
                    keyboardType="decimal-pad"
                    onChangeText={(t) => onPatch(i, { rpe: t, logged: false })}
                    editable={!s.logged}
                  />
                );
              default:
                return null;
            }
          })}
          <Pressable
            style={[styles.checkBtn, s.logged && styles.checkBtnDone]}
            onPress={() => onLog(i)}
            testID={`list-set-${section}-${exIdx}-${i}-check`}
            hitSlop={6}
          >
            <Ionicons
              name={s.logged ? "checkmark-circle" : "ellipse-outline"}
              size={24}
              color={s.logged ? theme.color.green : theme.color.textDim}
            />
          </Pressable>
        </View>
      ))}

      {/* Rest area — attached to the bottom of THIS exercise card.
          Iter 161 · Reuses the shared <RestTimer/> (compact variant). Starts
          from the exercise's prescribed rest_sec; skip/end returns to idle. */}
      {rest > 0 && (
        <View style={styles.restArea}>
          {restRunning ? (
            <View style={styles.restTimerWrap}>
              <RestTimer
                seconds={rest}
                size={140}
                compact
                autoContinueOverride={false}
                onComplete={() => setRestRunning(false)}
                onSkip={() => setRestRunning(false)}
                onEndEarly={() => setRestRunning(false)}
              />
            </View>
          ) : (
            <Pressable
              onPress={() => setRestRunning(true)}
              style={styles.restStartBtn}
              testID={`list-rest-start-${section}-${exIdx}`}
              hitSlop={8}
            >
              <Ionicons name="time-outline" size={16} color={theme.color.brand} />
              <Text style={styles.restStartLabel}>REST</Text>
              <Text style={styles.restStartTime}>{fmtMMSS(rest)}</Text>
              <Ionicons name="play" size={14} color="#fff" style={styles.restStartPlay} />
            </Pressable>
          )}
        </View>
      )}
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/*  Exercise image — resolves primary image via library name lookup            */
/* -------------------------------------------------------------------------- */
function ExerciseImage({ name }: { name: string }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let cancel = false;
    (async () => {
      try {
        const r = await api<{ exercises: any[] }>(
          `/exercise-content?q=${encodeURIComponent(name)}&limit=1`,
        );
        const ex = r?.exercises?.[0];
        const imgId: string | null =
          ex?.primary_image_id || ex?.demo_start_image_id || ex?.demo_end_image_id || null;
        if (!imgId) return;
        const token = await getToken();
        const u = `${API_BASE}/exercise-content/images/${imgId}/stream${
          token ? `?token=${encodeURIComponent(token)}` : ""
        }`;
        if (!cancel) setUrl(u);
      } catch { /* silent — fall back to placeholder */ }
    })();
    return () => { cancel = true; };
  }, [name]);
  return (
    <View style={styles.thumbWrap}>
      {url ? (
        <Image source={{ uri: url }} style={styles.thumb} />
      ) : (
        <View style={[styles.thumb, styles.thumbPh]}>
          <Ionicons name="barbell-outline" size={20} color={theme.color.textDim} />
        </View>
      )}
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/*  Detail sheet — image + tips + video + alternatives                          */
/* -------------------------------------------------------------------------- */
function ExerciseDetailSheet({ ex, onClose }: { ex: ExRow | null; onClose: () => void }) {
  const [info, setInfo] = useState<any>(null);
  const [alts, setAlts] = useState<any[]>([]);
  const [imgUrl, setImgUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!ex?.name) { setInfo(null); setAlts([]); setImgUrl(null); return; }
    let cancel = false;
    (async () => {
      try {
        const r = await api<{ exercises: any[] }>(
          `/exercise-content?q=${encodeURIComponent(ex.name)}&limit=1`,
        );
        if (cancel) return;
        const doc = r?.exercises?.[0] || null;
        setInfo(doc);
        const imgId: string | null =
          doc?.primary_image_id || doc?.demo_start_image_id || doc?.demo_end_image_id || null;
        if (imgId) {
          const token = await getToken();
          setImgUrl(`${API_BASE}/exercise-content/images/${imgId}/stream${
            token ? `?token=${encodeURIComponent(token)}` : ""
          }`);
        }
      } catch { /* ignore */ }
      try {
        const a = await api<any>(`/exercises/alternatives?name=${encodeURIComponent(ex.name)}`);
        if (!cancel) setAlts(a?.alternatives || []);
      } catch { /* ignore */ }
    })();
    return () => { cancel = true; };
  }, [ex?.name]);

  const visible = !!ex;
  const coachingPoints: string[] = info?.coaching_points || [];
  const hasVideo = !!(info?.primary_video_url || info?.content_status?.video);

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <SafeAreaView style={styles.detailRoot} edges={["top"]}>
        <View style={styles.detailHead}>
          <Pressable onPress={onClose} hitSlop={12} testID="list-detail-close">
            <Ionicons name="close" size={24} color={theme.color.text} />
          </Pressable>
          <Text style={styles.detailTitle} numberOfLines={2}>{ex?.name || ""}</Text>
          <View style={{ width: 24 }} />
        </View>
        <ScrollView contentContainerStyle={{ paddingBottom: 40 }}>
          {imgUrl ? (
            <Image source={{ uri: imgUrl }} style={styles.hero} resizeMode="contain" />
          ) : (
            <View style={[styles.hero, styles.thumbPh]}>
              <Ionicons name="barbell-outline" size={44} color={theme.color.textDim} />
            </View>
          )}
          {coachingPoints.length > 0 && (
            <View style={styles.detailSection}>
              <Text style={styles.detailSectionT}>HOW TO DO IT</Text>
              {coachingPoints.map((c: string, i: number) => (
                <View key={i} style={styles.pointRow}>
                  <Text style={styles.pointNum}>{i + 1}</Text>
                  <Text style={styles.pointText}>{c}</Text>
                </View>
              ))}
            </View>
          )}
          {info?.has_video || hasVideo ? (
            <View style={styles.detailSection}>
              <Text style={styles.detailSectionT}>VIDEO</Text>
              {ex?.name && (
                <ExerciseVideoPlayer
                  exerciseName={ex.name}
                  exerciseId={ex?.exercise_id || info?.id}
                  testIDPrefix="list-detail-video"
                />
              )}
            </View>
          ) : null}
          {alts.length > 0 && (
            <View style={styles.detailSection}>
              <Text style={styles.detailSectionT}>ALTERNATIVES</Text>
              {alts.map((a: any, i: number) => (
                <View key={i} style={styles.altRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.altName}>{a.name}</Text>
                    {a.why && <Text style={styles.altWhy}>{a.why}</Text>}
                  </View>
                </View>
              ))}
            </View>
          )}
        </ScrollView>
      </SafeAreaView>
    </Modal>
  );
}

/* -------------------------------------------------------------------------- */
/*  Styles                                                                     */
/* -------------------------------------------------------------------------- */
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.bg },
  top: {
    flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 10,
    borderBottomWidth: 1, borderBottomColor: theme.color.divider,
  },
  wName: { color: theme.color.text, fontSize: 15, fontWeight: "800" },
  wMeta: { color: theme.color.textDim, fontSize: 11, marginTop: 2, letterSpacing: 1 },
  progressTrack: { height: 3, backgroundColor: theme.color.surface2, width: "100%" },
  progressFill: { height: 3, backgroundColor: theme.color.brand },

  sectionHead: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: 16, paddingTop: 22, paddingBottom: 8,
  },
  sectionHeadT: { color: theme.color.brand, fontSize: 12, fontWeight: "900", letterSpacing: 2 },
  sectionHeadCount: {
    color: theme.color.textMuted, fontSize: 10, fontWeight: "800",
    backgroundColor: theme.color.surface2, paddingHorizontal: 8, paddingVertical: 2, borderRadius: 8,
  },

  card: {
    marginHorizontal: 12, marginBottom: 12, backgroundColor: theme.color.surface,
    borderRadius: 14, borderWidth: 1, borderColor: theme.color.border, overflow: "hidden",
  },
  cardHead: {
    flexDirection: "row", alignItems: "center", gap: 12, padding: 12,
    borderBottomWidth: 1, borderBottomColor: theme.color.divider,
  },
  thumbWrap: { width: 60, height: 60, borderRadius: 10, overflow: "hidden", backgroundColor: "#0A0A0B" },
  thumb: { width: "100%", height: "100%" },
  thumbPh: {
    backgroundColor: "#0A0A0B", alignItems: "center", justifyContent: "center",
  },
  exName: { color: theme.color.text, fontSize: 15, fontWeight: "800" },
  exMeta: { color: theme.color.textDim, fontSize: 11, marginTop: 3 },

  setsHead: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 12, paddingTop: 10, paddingBottom: 4,
  },
  setsHeadCol: {
    color: theme.color.textDim, fontSize: 9, fontWeight: "900", letterSpacing: 1.4,
  },
  setRow: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 12, paddingVertical: 8, minHeight: 44,
  },
  setRowDone: { backgroundColor: theme.color.surface2 },
  setNum: {
    width: 32, color: theme.color.text, fontSize: 14, fontWeight: "800",
  },
  setInput: {
    flex: 1, minWidth: 40, paddingVertical: 8, paddingHorizontal: 10,
    borderRadius: 8, borderWidth: 1, borderColor: theme.color.border,
    color: theme.color.text, fontSize: 14, backgroundColor: theme.color.bg,
    textAlign: "center",
  },
  checkBtn: {
    width: 40, height: 40, alignItems: "center", justifyContent: "center",
  },
  checkBtnDone: {},

  restRow: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 12, paddingVertical: 10,
    backgroundColor: theme.color.bg, borderTopWidth: 1, borderTopColor: theme.color.divider,
  },
  restT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700", letterSpacing: 1 },

  // Iter 161 · Per-card rest area — reuses the shared RestTimer.
  restArea: {
    paddingHorizontal: 12, paddingVertical: 12,
    backgroundColor: theme.color.bg, borderTopWidth: 1, borderTopColor: theme.color.divider,
    alignItems: "center",
  },
  restStartBtn: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 16, paddingVertical: 10, borderRadius: 12,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.brand,
    minWidth: 220, justifyContent: "center",
  },
  restStartLabel: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  restStartTime: { color: theme.color.text, fontSize: 16, fontWeight: "900",
                   fontVariant: ["tabular-nums"], marginHorizontal: 4 },
  restStartPlay: {
    backgroundColor: theme.color.brand,
    borderRadius: 10, padding: 4, overflow: "hidden",
  },
  restTimerWrap: { width: "100%", alignItems: "center", paddingVertical: 6 },

  finishBtn: {
    marginHorizontal: 12, marginTop: 24, paddingVertical: 16,
    borderRadius: 12, backgroundColor: theme.color.brand,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
  },
  finishBtnT: { color: "#fff", fontSize: 13, fontWeight: "900", letterSpacing: 2 },
  finishNote: {
    color: theme.color.textDim, fontSize: 11, textAlign: "center", marginTop: 10, paddingHorizontal: 24,
  },

  // Detail sheet
  detailRoot: { flex: 1, backgroundColor: theme.color.surface },
  detailHead: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 16, paddingVertical: 12,
    borderBottomWidth: 1, borderBottomColor: theme.color.divider,
  },
  detailTitle: { color: theme.color.text, fontSize: 15, fontWeight: "900", flex: 1, textAlign: "center", paddingHorizontal: 8 },
  hero: {
    width: "100%",
    aspectRatio: 4 / 3,
    backgroundColor: "#0A0A0B",
    // Iter 161 · Was 240px fixed height + default resizeMode="cover" which
    // centre-cropped every Library image. Switched to contain + aspectRatio
    // so the WHOLE approved image is visible on iPhone and Android.
  },
  detailSection: { paddingHorizontal: 18, paddingTop: 20 },
  detailSectionT: {
    color: theme.color.textDim, fontSize: 11, fontWeight: "900", letterSpacing: 2, marginBottom: 10,
  },
  pointRow: { flexDirection: "row", gap: 10, marginBottom: 10 },
  pointNum: {
    width: 22, height: 22, borderRadius: 11, textAlign: "center",
    color: "#fff", backgroundColor: theme.color.brand, fontWeight: "900",
    fontSize: 12, lineHeight: 22, overflow: "hidden",
  },
  pointText: { color: theme.color.text, fontSize: 14, lineHeight: 20, flex: 1 },
  altRow: {
    flexDirection: "row", alignItems: "center", paddingVertical: 10,
    borderBottomWidth: 1, borderBottomColor: theme.color.divider,
  },
  altName: { color: theme.color.text, fontSize: 14, fontWeight: "700" },
  altWhy: { color: theme.color.textMuted, fontSize: 11, marginTop: 3 },
});
