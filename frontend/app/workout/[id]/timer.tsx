import { useEffect, useRef, useState } from "react";
import { View, Text, StyleSheet, Pressable, ScrollView, ActivityIndicator, AppState } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme, loadColor } from "@/src/lib/theme";

export default function GuidedTimer() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [w, setW] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [idx, setIdx] = useState(0);          // exercise index
  const [phase, setPhase] = useState<"warmup" | "work" | "rest" | "done">("warmup");
  const [warmIdx, setWarmIdx] = useState(0);
  const [set, setSet] = useState(1);          // current set number
  const [remaining, setRemaining] = useState(0);
  const [running, setRunning] = useState(false);
  const [saving, setSaving] = useState(false);
  const intv = useRef<any>(null);

  useEffect(() => {
    (async () => {
      try {
        const data = await api<any>(`/workouts/${id}`);
        setW(data);
        // seed timer with first warmup
        const wu = data.warmup?.[0];
        setRemaining(wu?.duration_sec || 30);
      } finally { setLoading(false); }
    })();
  }, [id]);

  useEffect(() => {
    if (!running) return;
    intv.current = setInterval(() => {
      setRemaining((r) => (r > 0 ? r - 1 : 0));
    }, 1000);
    return () => clearInterval(intv.current);
  }, [running]);

  useEffect(() => {
    if (remaining === 0 && running) {
      advance();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [remaining, running]);

  useEffect(() => {
    const sub = AppState.addEventListener("change", (s) => { if (s !== "active") setRunning(false); });
    return () => sub.remove();
  }, []);

  const advance = () => {
    if (!w) return;
    if (phase === "warmup") {
      const nextWarm = warmIdx + 1;
      const list = w.warmup || [];
      if (nextWarm < list.length) {
        setWarmIdx(nextWarm);
        setRemaining(list[nextWarm]?.duration_sec || 30);
        return;
      }
      // enter first exercise
      setPhase("work");
      setSet(1);
      const first = w.exercises?.[0];
      setRemaining(inferSecs(first));
      return;
    }
    if (phase === "work") {
      // finished a set → rest, unless last set of last exercise
      const ex = w.exercises?.[idx];
      const isLastSet = set >= (ex?.sets || 1);
      const isLastEx = idx >= (w.exercises?.length || 0) - 1;
      if (isLastSet && isLastEx) {
        setPhase("done"); setRunning(false); return;
      }
      setPhase("rest");
      setRemaining(ex?.rest_sec || 45);
      return;
    }
    if (phase === "rest") {
      const ex = w.exercises?.[idx];
      const isLastSet = set >= (ex?.sets || 1);
      if (isLastSet) {
        // advance exercise
        const next = idx + 1;
        setIdx(next);
        setSet(1);
        setPhase("work");
        setRemaining(inferSecs(w.exercises?.[next]));
      } else {
        setSet((s) => s + 1);
        setPhase("work");
        setRemaining(inferSecs(w.exercises?.[idx]));
      }
      return;
    }
  };

  const inferSecs = (ex: any) => {
    if (!ex) return 30;
    // If reps is a time string like "45s" or "45", treat as seconds; else default 40
    const raw = String(ex.reps || "");
    const m = raw.match(/(\d+)\s*s/i) || raw.match(/^(\d+)$/);
    if (m) {
      const n = parseInt(m[1]);
      if (n >= 5 && n <= 300) return n;
    }
    return 40;
  };

  const skip = () => { setRemaining(0); };
  const restart = () => {
    const ex = w.exercises?.[idx];
    setRemaining(phase === "rest" ? (ex?.rest_sec || 45) : inferSecs(ex));
  };

  const finish = async () => {
    setSaving(true);
    try {
      await api(`/workouts/${id}/complete`, {
        method: "POST",
        body: { completed_exercises: w.exercises, rpe: null, notes: "Completed via Guided Timer" },
      });
      router.back();
    } finally { setSaving(false); }
  };

  if (loading || !w) {
    return <View style={{ flex: 1, backgroundColor: theme.color.surface, alignItems: "center", justifyContent: "center" }}><ActivityIndicator color={theme.color.brand} /></View>;
  }

  const ex = w.exercises?.[idx];
  const wu = w.warmup?.[warmIdx];
  const mm = String(Math.floor(remaining / 60)).padStart(2, "0");
  const ss = String(remaining % 60).padStart(2, "0");
  const currentLabel = phase === "warmup" ? (wu?.name || "Warm-up")
    : phase === "work" ? (ex?.name || "Exercise")
    : phase === "rest" ? "REST"
    : "Complete";
  const phaseColor = phase === "work" ? theme.color.brand
    : phase === "rest" ? theme.color.info
    : phase === "warmup" ? "#3B82F6"
    : theme.color.green;

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} testID="gt-back"><Ionicons name="close" size={26} color={theme.color.text} /></Pressable>
        <View style={[styles.pill, { backgroundColor: loadColor(w.day_load) }]}>
          <Text style={styles.pillText}>{String(w.day_load || "").toUpperCase()}</Text>
        </View>
        <View style={{ width: 26 }} />
      </View>

      <View style={styles.body}>
        <Text style={styles.workoutTitle}>{w.title}</Text>
        <Text style={styles.progress}>
          {phase === "warmup" ? `Warm-up ${warmIdx + 1} / ${w.warmup?.length || 0}` :
           phase === "done" ? "Workout Complete!" :
           `Exercise ${idx + 1} / ${w.exercises?.length || 0}  ·  Set ${set} / ${ex?.sets || 1}`}
        </Text>

        <View style={[styles.timerCircle, { borderColor: phaseColor }]} testID="gt-timer">
          <Text style={[styles.timerBig, { color: phaseColor }]}>{mm}:{ss}</Text>
          <Text style={styles.phaseLabel}>{phase.toUpperCase()}</Text>
        </View>

        <Text style={styles.currentName} testID="gt-current-name">{currentLabel}</Text>
        {phase === "work" && ex && (
          <Text style={styles.exMeta}>{ex.sets} × {ex.reps} · RPE {ex.rpe || "-"}{ex.notes ? `\n${ex.notes}` : ""}</Text>
        )}

        {phase !== "done" ? (
          <View style={styles.controls}>
            <Pressable testID="gt-restart" onPress={restart} style={styles.iconBtn}><Ionicons name="refresh" size={22} color={theme.color.text} /></Pressable>
            <Pressable
              testID="gt-play"
              onPress={() => setRunning((r) => !r)}
              style={[styles.playBtn, running && { backgroundColor: theme.color.amber }]}
            >
              <Ionicons name={running ? "pause" : "play"} size={32} color="#fff" />
            </Pressable>
            <Pressable testID="gt-skip" onPress={skip} style={styles.iconBtn}><Ionicons name="play-skip-forward" size={22} color={theme.color.text} /></Pressable>
          </View>
        ) : (
          <Pressable testID="gt-finish" onPress={finish} disabled={saving} style={[styles.finishBtn, saving && { opacity: 0.6 }]}>
            {saving ? <ActivityIndicator color="#fff" /> : <Text style={styles.finishText}>MARK COMPLETE</Text>}
          </Pressable>
        )}
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.stripRow}>
        {(w.exercises || []).map((e: any, i: number) => (
          <View key={i} style={[styles.strip, i === idx && styles.stripActive]}>
            <Text style={[styles.stripText, i === idx && { color: "#fff" }]}>{e.name}</Text>
            <Text style={[styles.stripMeta, i === idx && { color: "#fff" }]}>{e.sets}×{e.reps}</Text>
          </View>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  pill: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: theme.radius.sm },
  pillText: { color: "#fff", fontWeight: "800", fontSize: 10, letterSpacing: 1.5 },
  body: { flex: 1, alignItems: "center", justifyContent: "center", padding: theme.space.lg },
  workoutTitle: { color: theme.color.text, fontSize: 22, fontWeight: "900", textAlign: "center", letterSpacing: -0.5 },
  progress: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 2, fontWeight: "800", marginTop: theme.space.sm },
  timerCircle: { width: 240, height: 240, borderRadius: 120, borderWidth: 8, alignItems: "center", justifyContent: "center", marginTop: theme.space.xl },
  timerBig: { fontSize: 60, fontWeight: "900", letterSpacing: -2 },
  phaseLabel: { color: theme.color.textMuted, letterSpacing: 4, fontSize: 11, fontWeight: "800", marginTop: 4 },
  currentName: { color: theme.color.text, fontSize: 24, fontWeight: "900", marginTop: theme.space.lg, textAlign: "center" },
  exMeta: { color: theme.color.textMuted, marginTop: theme.space.sm, textAlign: "center", fontSize: 13, lineHeight: 19 },
  controls: { flexDirection: "row", alignItems: "center", gap: theme.space.xl, marginTop: theme.space.xl },
  iconBtn: { width: 56, height: 56, borderRadius: 28, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, alignItems: "center", justifyContent: "center" },
  playBtn: { width: 84, height: 84, borderRadius: 42, backgroundColor: theme.color.brand, alignItems: "center", justifyContent: "center" },
  finishBtn: { marginTop: theme.space.xl, backgroundColor: theme.color.green, paddingVertical: 16, paddingHorizontal: theme.space.xxl, borderRadius: theme.radius.md },
  finishText: { color: "#fff", fontWeight: "800", letterSpacing: 2, fontSize: 13 },
  stripRow: { paddingHorizontal: theme.space.lg, paddingBottom: theme.space.md, gap: 8 },
  strip: { padding: theme.space.sm, borderRadius: theme.radius.sm, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, minWidth: 100 },
  stripActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  stripText: { color: theme.color.text, fontSize: 12, fontWeight: "700" },
  stripMeta: { color: theme.color.textDim, fontSize: 10, marginTop: 2 },
});
