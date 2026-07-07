import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator } from "react-native";
import { useLocalSearchParams, useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { useAuth } from "@/src/lib/auth";
import { theme, loadColor } from "@/src/lib/theme";

export default function WorkoutDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const isCoach = user?.role === "coach";
  const [w, setW] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [rpe, setRpe] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api<any>(`/workouts/${id}`);
      setW(data);
    } finally { setLoading(false); }
  }, [id]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const updateEx = (idx: number, key: string, val: any) => {
    setW((prev: any) => ({
      ...prev,
      exercises: prev.exercises.map((e: any, i: number) => (i === idx ? { ...e, [key]: val } : e)),
    }));
  };

  const removeEx = (idx: number) => {
    setW((prev: any) => ({ ...prev, exercises: prev.exercises.filter((_: any, i: number) => i !== idx) }));
  };

  const addEx = () => {
    setW((prev: any) => ({
      ...prev,
      exercises: [...(prev.exercises || []), { name: "New Exercise", sets: 3, reps: "10", rest_sec: 60, notes: "" }],
    }));
  };

  const save = async (extra: any = {}) => {
    setSaving(true);
    try {
      const updated = await api<any>(`/workouts/${id}`, { method: "PATCH", body: { exercises: w.exercises, title: w.title, coach_notes: w.coach_notes, ...extra } });
      setW(updated);
      setEditing(false);
    } finally { setSaving(false); }
  };

  const approve = () => save({ approved: true });
  const cycleLoad = () => {
    const order = ["green", "amber", "red"];
    const next = order[(order.indexOf(w.day_load) + 1) % 3];
    save({ day_load: next });
  };

  const complete = async () => {
    setSaving(true);
    try {
      const done = await api<any>(`/workouts/${id}/complete`, {
        method: "POST",
        body: {
          completed_exercises: w.exercises,
          rpe: rpe ? parseInt(rpe) : null,
          notes: null,
        },
      });
      setW(done);
    } finally { setSaving(false); }
  };

  if (loading || !w) {
    return (
      <View style={{ flex: 1, backgroundColor: theme.color.surface, alignItems: "center", justifyContent: "center" }}>
        <ActivityIndicator color={theme.color.brand} />
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} testID="workout-back"><Ionicons name="chevron-back" size={26} color={theme.color.text} /></Pressable>
        <View style={[styles.loadPill, { backgroundColor: loadColor(w.day_load) }]}>
          <Text style={styles.loadPillText}>{w.day_load?.toUpperCase()}</Text>
        </View>
        <Pressable testID="edit-toggle" onPress={() => setEditing((e) => !e)}>
          <Text style={{ color: theme.color.brand, letterSpacing: 2, fontWeight: "800", fontSize: 12 }}>{editing ? "DONE" : "EDIT"}</Text>
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 140 }}>
        <Text style={styles.date}>{w.date}</Text>
        {editing ? (
          <TextInput value={w.title} onChangeText={(v) => setW({ ...w, title: v })} style={styles.titleInput} testID="edit-title" />
        ) : (
          <Text style={styles.title}>{w.title}</Text>
        )}
        <Text style={styles.meta}>{w.duration_min}min · {w.focus?.toUpperCase()}</Text>

        {w.rationale && (
          <View style={styles.rationale}>
            <Text style={styles.rLabel}>WHY THIS WORKOUT</Text>
            <Text style={styles.rText}>{w.rationale}</Text>
          </View>
        )}

        {isCoach && editing && (
          <Pressable testID="cycle-load" onPress={cycleLoad} style={styles.cycleBtn}>
            <Text style={{ color: theme.color.brand, fontWeight: "800", letterSpacing: 1.5 }}>CYCLE LOAD → NEXT</Text>
          </Pressable>
        )}

        <Text style={styles.sect}>EXERCISES</Text>
        {(w.exercises || []).map((ex: any, idx: number) => (
          <View key={idx} style={styles.exCard} testID={`ex-${idx}`}>
            {editing ? (
              <>
                <TextInput style={styles.exNameInput} value={ex.name} onChangeText={(v) => updateEx(idx, "name", v)} />
                <View style={styles.exRow}>
                  <TextInput style={styles.exSmall} value={String(ex.sets ?? "")} onChangeText={(v) => updateEx(idx, "sets", parseInt(v) || 0)} keyboardType="number-pad" placeholder="sets" placeholderTextColor={theme.color.textDim} />
                  <TextInput style={styles.exSmall} value={String(ex.reps ?? "")} onChangeText={(v) => updateEx(idx, "reps", v)} placeholder="reps" placeholderTextColor={theme.color.textDim} />
                  <TextInput style={styles.exSmall} value={String(ex.rest_sec ?? "")} onChangeText={(v) => updateEx(idx, "rest_sec", parseInt(v) || 0)} keyboardType="number-pad" placeholder="rest" placeholderTextColor={theme.color.textDim} />
                  <Pressable onPress={() => removeEx(idx)} testID={`remove-ex-${idx}`}><Ionicons name="trash" size={20} color={theme.color.red} /></Pressable>
                </View>
              </>
            ) : (
              <>
                <Text style={styles.exName}>{ex.name}</Text>
                <Text style={styles.exMeta}>{ex.sets} × {ex.reps} · rest {ex.rest_sec}s</Text>
                {ex.notes && <Text style={styles.exNotes}>{ex.notes}</Text>}
              </>
            )}
          </View>
        ))}

        {editing && (
          <Pressable testID="add-ex" onPress={addEx} style={styles.addExBtn}>
            <Ionicons name="add" size={18} color={theme.color.brand} />
            <Text style={{ color: theme.color.brand, marginLeft: 6, fontWeight: "700" }}>ADD EXERCISE</Text>
          </Pressable>
        )}

        {isCoach && (
          <View style={{ marginTop: theme.space.lg }}>
            <Text style={styles.sect}>COACH NOTES</Text>
            <TextInput
              testID="coach-notes"
              style={[styles.exNameInput, { minHeight: 80 }]}
              value={w.coach_notes || ""}
              onChangeText={(v) => setW({ ...w, coach_notes: v })}
              placeholder="Add note for client…"
              placeholderTextColor={theme.color.textDim}
              multiline
            />
          </View>
        )}
        {!isCoach && w.coach_notes && (
          <View style={styles.rationale}>
            <Text style={styles.rLabel}>COACH NOTE</Text>
            <Text style={styles.rText}>{w.coach_notes}</Text>
          </View>
        )}

        {!isCoach && !w.completed && (
          <View style={styles.compBox}>
            <Text style={styles.sectSm}>RATE THIS SESSION (RPE 1-10)</Text>
            <TextInput style={styles.exNameInput} value={rpe} onChangeText={setRpe} keyboardType="number-pad" placeholder="7" placeholderTextColor={theme.color.textDim} testID="rpe-input" />
          </View>
        )}
      </ScrollView>

      <View style={styles.sticky}>
        {editing ? (
          <Pressable testID="save-workout" onPress={() => save()} disabled={saving} style={[styles.cta, saving && { opacity: 0.6 }]}>
            {saving ? <ActivityIndicator color="#fff" /> : <Text style={styles.ctaText}>SAVE CHANGES</Text>}
          </Pressable>
        ) : isCoach ? (
          <View style={{ flexDirection: "row", gap: 8 }}>
            <Pressable testID="reject-workout" onPress={() => save({ approved: false })} style={[styles.ctaSecondary, { flex: 1 }]}>
              <Text style={styles.ctaSecondaryText}>REJECT</Text>
            </Pressable>
            <Pressable testID="approve-workout" onPress={approve} disabled={saving || w.approved} style={[styles.cta, { flex: 1 }, w.approved && { backgroundColor: theme.color.green }]}>
              <Text style={styles.ctaText}>{w.approved ? "APPROVED ✓" : "APPROVE"}</Text>
            </Pressable>
          </View>
        ) : (
          <Pressable
            testID="complete-workout"
            onPress={complete}
            disabled={saving || w.completed}
            style={[styles.cta, w.completed && { backgroundColor: theme.color.green }, saving && { opacity: 0.6 }]}
          >
            {saving ? <ActivityIndicator color="#fff" /> : <Text style={styles.ctaText}>{w.completed ? "COMPLETED ✓" : "COMPLETE WORKOUT"}</Text>}
          </Pressable>
        )}
      </View>
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  loadPill: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: theme.radius.sm },
  loadPillText: { color: "#fff", fontWeight: "800", fontSize: 10, letterSpacing: 1.5 },
  date: { color: theme.color.textMuted, letterSpacing: 2, fontSize: 11, fontWeight: "700" },
  title: { color: theme.color.text, fontSize: 30, fontWeight: "900", marginTop: 6, letterSpacing: -0.5 },
  titleInput: { color: theme.color.text, fontSize: 26, fontWeight: "900", marginTop: 6, backgroundColor: theme.color.surface2, padding: 12, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border },
  meta: { color: theme.color.textMuted, marginTop: 4 },
  rationale: { marginTop: theme.space.lg, padding: theme.space.md, backgroundColor: theme.color.brandTint, borderRadius: theme.radius.md, borderLeftWidth: 3, borderLeftColor: theme.color.brand },
  rLabel: { color: theme.color.brand, letterSpacing: 2, fontSize: 10, fontWeight: "800" },
  rText: { color: theme.color.text, marginTop: 6, fontSize: 13, lineHeight: 19 },
  cycleBtn: { marginTop: theme.space.md, padding: 10, borderRadius: theme.radius.sm, borderWidth: 1, borderColor: theme.color.brand, alignItems: "center" },
  sect: { color: theme.color.textMuted, letterSpacing: 2, fontSize: 11, fontWeight: "800", marginTop: theme.space.lg, marginBottom: theme.space.sm },
  sectSm: { color: theme.color.textMuted, letterSpacing: 1.5, fontSize: 10, fontWeight: "800" },
  exCard: { padding: theme.space.md, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, marginBottom: theme.space.sm },
  exName: { color: theme.color.text, fontSize: 15, fontWeight: "800" },
  exMeta: { color: theme.color.brand, marginTop: 4, letterSpacing: 1, fontWeight: "600", fontSize: 13 },
  exNotes: { color: theme.color.textMuted, marginTop: 4, fontSize: 12 },
  exNameInput: { color: theme.color.text, fontSize: 15, fontWeight: "700", backgroundColor: theme.color.surface3, padding: 10, borderRadius: theme.radius.sm, borderWidth: 1, borderColor: theme.color.border },
  exRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 8 },
  exSmall: { flex: 1, color: theme.color.text, backgroundColor: theme.color.surface3, padding: 8, borderRadius: theme.radius.sm, borderWidth: 1, borderColor: theme.color.border, textAlign: "center" },
  addExBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", padding: 12, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.brand, marginTop: 8 },
  compBox: { marginTop: theme.space.lg },
  sticky: { position: "absolute", left: 0, right: 0, bottom: 0, padding: theme.space.lg, backgroundColor: theme.color.surface, borderTopWidth: 1, borderTopColor: theme.color.border },
  cta: { backgroundColor: theme.color.brand, paddingVertical: 16, borderRadius: theme.radius.md, alignItems: "center" },
  ctaText: { color: "#fff", fontWeight: "800", letterSpacing: 2, fontSize: 13 },
  ctaSecondary: { backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.red, paddingVertical: 16, borderRadius: theme.radius.md, alignItems: "center" },
  ctaSecondaryText: { color: theme.color.red, fontWeight: "800", letterSpacing: 2, fontSize: 13 },
});
