/**
 * Coach Workout Editor — Plan C4/C5/C6.
 *
 * Route: /coach/workout/edit/[wid]
 *
 * Features:
 *   - Edit workout meta (title, duration, focus, rationale, coach notes, date, key session, day load)
 *   - CRUD exercises (add / remove / edit / reorder)
 *   - Swap an exercise via the V2 Library search with filters
 *   - Regenerate this workout with one of 12 preset options (preview → apply)
 *   - Approve / Lock / Move / Delete are already available via existing coach flows
 *
 * All edits set coach_edited=true and are audit-logged server-side.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator, Modal,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter, Stack } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

const REGEN_PRESETS: { id: string; label: string; icon: string }[] = [
  { id: "same_goal",     label: "Regenerate — same goal",       icon: "refresh" },
  { id: "shorter",       label: "Shorter (65% duration)",       icon: "contract" },
  { id: "easier",        label: "Easier (RPE-2)",               icon: "arrow-down" },
  { id: "harder",        label: "Harder (+1 set)",              icon: "arrow-up" },
  { id: "hotel_gym",     label: "For hotel gym",                icon: "bed" },
  { id: "bodyweight",    label: "Bodyweight only",              icon: "body" },
  { id: "tired",         label: "Client is tired",              icon: "moon" },
  { id: "injury_pain",   label: "Client has pain / injury",     icon: "medkit" },
  { id: "around_roster", label: "Around the roster",            icon: "calendar" },
  { id: "as_running",    label: "As a running session",         icon: "walk" },
  { id: "as_strength",   label: "As strength support",          icon: "barbell" },
  { id: "custom",        label: "Custom instruction",           icon: "chatbubble-ellipses" },
];

export default function CoachWorkoutEditor() {
  const { wid } = useLocalSearchParams<{ wid: string }>();
  const router = useRouter();
  const [w, setW] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [swapModal, setSwapModal] = useState<{ open: boolean; exIdx: number | null }>({ open: false, exIdx: null });
  const [regenModal, setRegenModal] = useState<{ open: boolean; preset: string; custom: string; preview: any | null }>({ open: false, preset: "same_goal", custom: "", preview: null });

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const r = await api<any>(`/workouts/${wid}`);
      setW(r);
    } catch (e: any) {
      setError(e?.message || "Could not load workout");
    } finally { setLoading(false); }
  }, [wid]);
  useEffect(() => { load(); }, [load]);

  const setField = (k: string, v: any) => setW((prev: any) => ({ ...prev, [k]: v }));

  const persistMeta = async (patch: Record<string, any>) => {
    setSaving(true);
    try {
      await api(`/coach/workouts/${wid}`, { method: "PATCH", body: patch });
      setW((prev: any) => ({ ...prev, ...patch, coach_edited: true }));
    } catch (e: any) {
      setError(e?.message || "Save failed");
    } finally { setSaving(false); }
  };

  const editExercise = async (idx: number, patch: Record<string, any>) => {
    setSaving(true);
    try {
      await api(`/coach/workouts/${wid}/exercises/${idx}`, { method: "PATCH", body: patch });
      setW((prev: any) => {
        const exs = [...(prev.exercises || [])];
        exs[idx] = { ...exs[idx], ...patch };
        return { ...prev, exercises: exs };
      });
    } catch (e: any) { setError(e?.message || "Edit failed"); }
    finally { setSaving(false); }
  };

  const removeExercise = async (idx: number) => {
    setSaving(true);
    try {
      await api(`/coach/workouts/${wid}/exercises/${idx}`, { method: "DELETE" });
      setW((prev: any) => ({ ...prev, exercises: prev.exercises.filter((_: any, i: number) => i !== idx) }));
    } catch (e: any) { setError(e?.message || "Delete failed"); }
    finally { setSaving(false); }
  };

  const openSwap = (idx: number) => setSwapModal({ open: true, exIdx: idx });

  const submitSwap = async (replacement_exercise_id: string, replacement_name: string) => {
    if (swapModal.exIdx == null) return;
    setSaving(true);
    try {
      await api(`/coach/workouts/${wid}/exercises/${swapModal.exIdx}/swap`, {
        method: "POST",
        body: { replacement_exercise_id, replacement_name, preserve_prescription: true },
      });
      setSwapModal({ open: false, exIdx: null });
      await load();
    } catch (e: any) { setError(e?.message || "Swap failed"); }
    finally { setSaving(false); }
  };

  const previewRegen = async (preset: string, custom = "") => {
    setSaving(true);
    try {
      const r = await api<any>(`/coach/workouts/${wid}/regenerate-preview`, {
        method: "POST",
        body: { preset, custom_instruction: custom || null },
      });
      setRegenModal({ open: true, preset, custom, preview: r });
    } catch (e: any) { setError(e?.message || "Preview failed"); }
    finally { setSaving(false); }
  };

  const applyRegen = async () => {
    setSaving(true);
    try {
      await api(`/coach/workouts/${wid}/regenerate`, {
        method: "POST",
        body: { guidance: regenModal.preview?.guidance || regenModal.preset },
      });
      setRegenModal({ open: false, preset: "same_goal", custom: "", preview: null });
      await load();
    } catch (e: any) { setError(e?.message || "Apply failed"); }
    finally { setSaving(false); }
  };

  if (loading) return <SafeAreaView style={styles.wrap}><View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View></SafeAreaView>;
  if (error && !w) return <SafeAreaView style={styles.wrap}><View style={styles.center}><Text style={{ color: theme.color.red }}>{error}</Text><Pressable onPress={load} style={styles.primaryBtn}><Text style={styles.primaryBtnT}>Retry</Text></Pressable></View></SafeAreaView>;

  return (
    <SafeAreaView style={styles.wrap} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12} style={styles.backBtn}>
          <Ionicons name="chevron-back" size={22} color={theme.color.text} />
        </Pressable>
        <Text style={styles.title} numberOfLines={1}>Edit · {w?.title || "Workout"}</Text>
        {saving ? <ActivityIndicator color={theme.color.brand} /> : <View style={{ width: 32 }} />}
      </View>

      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 40 }}>
        {error && <View style={styles.errCard}><Ionicons name="alert-circle" size={16} color={theme.color.red} /><Text style={styles.errTxt}>{error}</Text></View>}

        {/* Meta editor */}
        <Text style={styles.sectHeader}>MAIN</Text>
        <View style={styles.card}>
          {/* Iter 102 — Layover context reason line for coach */}
          {w?.layover_context ? (
            <View style={styles.layoverCard} testID="coach-layover-context">
              <View style={styles.layoverHead}>
                <Text style={styles.layoverEyebrow}>LAYOVER CONTEXT</Text>
                {w.layover_context.needs_destination_review ? (
                  <Text style={styles.layoverFlag}>DESTINATION NEEDS REVIEW</Text>
                ) : null}
              </View>
              <Text style={styles.layoverBody}>{w.layover_context.coach_reason}</Text>
              <Text style={styles.layoverHint}>You can edit the title below — your edit will be preserved.</Text>
            </View>
          ) : null}

          <Text style={styles.fieldLbl}>Title</Text>
          <TextInput
            style={styles.input}
            value={w?.title || ""}
            onChangeText={(v) => setField("title", v)}
            onBlur={() => persistMeta({ title: w?.title, title_manually_edited_by_coach: true })}
          />
          <View style={{ flexDirection: "row", gap: 10, marginTop: 10 }}>
            <View style={{ flex: 1 }}>
              <Text style={styles.fieldLbl}>Duration (min)</Text>
              <TextInput
                style={styles.input}
                value={String(w?.duration_min ?? 0)}
                onChangeText={(v) => setField("duration_min", Number(v) || 0)}
                onBlur={() => persistMeta({ duration_min: Number(w?.duration_min) || 0 })}
                keyboardType="number-pad"
              />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.fieldLbl}>Focus</Text>
              <TextInput
                style={styles.input}
                value={w?.focus || ""}
                onChangeText={(v) => setField("focus", v)}
                onBlur={() => persistMeta({ focus: w?.focus })}
              />
            </View>
          </View>
          <Text style={[styles.fieldLbl, { marginTop: 10 }]}>Date</Text>
          <TextInput
            style={styles.input}
            value={w?.date || ""}
            onChangeText={(v) => setField("date", v)}
            onBlur={() => persistMeta({ date: w?.date })}
          />
          <Text style={[styles.fieldLbl, { marginTop: 10 }]}>Rationale (why this session?)</Text>
          <TextInput
            style={[styles.input, { minHeight: 60, textAlignVertical: "top" }]}
            value={w?.rationale || ""}
            onChangeText={(v) => setField("rationale", v)}
            onBlur={() => persistMeta({ rationale: w?.rationale })}
            multiline
          />
          <Text style={[styles.fieldLbl, { marginTop: 10 }]}>Coach notes</Text>
          <TextInput
            style={[styles.input, { minHeight: 60, textAlignVertical: "top" }]}
            value={w?.coach_notes || ""}
            onChangeText={(v) => setField("coach_notes", v)}
            onBlur={() => persistMeta({ coach_notes: w?.coach_notes })}
            multiline
          />
          <View style={{ flexDirection: "row", gap: 8, marginTop: 12 }}>
            <Pressable
              onPress={() => persistMeta({ key_session: !w?.key_session })}
              style={[styles.pill, w?.key_session && styles.pillActive]}
            >
              <Ionicons name="star" size={12} color={w?.key_session ? "#fff" : theme.color.text} />
              <Text style={[styles.pillT, w?.key_session && { color: "#fff" }]}>KEY SESSION</Text>
            </Pressable>
          </View>
        </View>

        {/* Exercises */}
        <View style={styles.sectRow}>
          <Text style={styles.sectHeader}>EXERCISES ({(w?.exercises || []).length})</Text>
          <Pressable onPress={() => openSwap(-1 /* -1 means "add" */)} style={styles.smallBtn}>
            <Ionicons name="add" size={14} color={theme.color.brand} />
            <Text style={styles.smallBtnT}>ADD</Text>
          </Pressable>
        </View>

        {(w?.exercises || []).length === 0 ? (
          <View style={styles.card}><Text style={styles.muted}>No exercises yet.</Text></View>
        ) : (w?.exercises || []).map((ex: any, idx: number) => (
          <View key={idx} style={styles.card}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
              <Text style={styles.exName}>{idx + 1}. {ex.name}</Text>
              <View style={{ flexDirection: "row", gap: 6 }}>
                <Pressable onPress={() => openSwap(idx)} style={styles.iconBtn}>
                  <Ionicons name="swap-horizontal" size={14} color={theme.color.text} />
                </Pressable>
                <Pressable onPress={() => removeExercise(idx)} style={styles.iconBtn}>
                  <Ionicons name="trash-outline" size={14} color={theme.color.red} />
                </Pressable>
              </View>
            </View>
            <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
              <View style={{ flex: 1 }}>
                <Text style={styles.exFieldLbl}>Sets</Text>
                <TextInput
                  style={styles.exField}
                  value={String(ex.sets ?? "")}
                  onChangeText={(v) => setW((prev: any) => { const exs = [...prev.exercises]; exs[idx] = { ...exs[idx], sets: Number(v) || 0 }; return { ...prev, exercises: exs }; })}
                  onBlur={() => editExercise(idx, { sets: Number(ex.sets) || 0 })}
                  keyboardType="number-pad"
                />
              </View>
              <View style={{ flex: 1.5 }}>
                <Text style={styles.exFieldLbl}>Reps</Text>
                <TextInput
                  style={styles.exField}
                  value={String(ex.reps ?? "")}
                  onChangeText={(v) => setW((prev: any) => { const exs = [...prev.exercises]; exs[idx] = { ...exs[idx], reps: v }; return { ...prev, exercises: exs }; })}
                  onBlur={() => editExercise(idx, { reps: ex.reps })}
                />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.exFieldLbl}>Rest (s)</Text>
                <TextInput
                  style={styles.exField}
                  value={String(ex.rest_sec ?? "")}
                  onChangeText={(v) => setW((prev: any) => { const exs = [...prev.exercises]; exs[idx] = { ...exs[idx], rest_sec: Number(v) || 0 }; return { ...prev, exercises: exs }; })}
                  onBlur={() => editExercise(idx, { rest_sec: Number(ex.rest_sec) || 0 })}
                  keyboardType="number-pad"
                />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.exFieldLbl}>RPE</Text>
                <TextInput
                  style={styles.exField}
                  value={String(ex.rpe ?? "")}
                  onChangeText={(v) => setW((prev: any) => { const exs = [...prev.exercises]; exs[idx] = { ...exs[idx], rpe: Number(v) || 0 }; return { ...prev, exercises: exs }; })}
                  onBlur={() => editExercise(idx, { rpe: Number(ex.rpe) || 0 })}
                  keyboardType="decimal-pad"
                />
              </View>
            </View>
            <TextInput
              style={[styles.input, { marginTop: 8, minHeight: 40 }]}
              value={ex.notes || ""}
              onChangeText={(v) => setW((prev: any) => { const exs = [...prev.exercises]; exs[idx] = { ...exs[idx], notes: v }; return { ...prev, exercises: exs }; })}
              onBlur={() => editExercise(idx, { notes: ex.notes || "" })}
              placeholder="Coach notes for this exercise"
              placeholderTextColor={theme.color.textMuted}
              multiline
            />
          </View>
        ))}

        {/* Regenerate */}
        <Text style={styles.sectHeader}>REGENERATE THIS WORKOUT</Text>
        <View style={styles.presetGrid}>
          {REGEN_PRESETS.map((p) => (
            <Pressable key={p.id} onPress={() => previewRegen(p.id)} style={styles.presetBtn}>
              <Ionicons name={p.icon as any} size={14} color={theme.color.brand} />
              <Text style={styles.presetBtnT}>{p.label}</Text>
            </Pressable>
          ))}
        </View>
      </ScrollView>

      {/* Exercise Swap / Add modal — Plan C5 */}
      <Modal visible={swapModal.open} transparent animationType="slide" onRequestClose={() => setSwapModal({ open: false, exIdx: null })}>
        <ExerciseSwapSheet
          onClose={() => setSwapModal({ open: false, exIdx: null })}
          onPick={async (exId, name) => {
            if (swapModal.exIdx === -1) {
              // ADD path
              setSaving(true);
              try {
                await api(`/coach/workouts/${wid}/exercises/add`, {
                  method: "POST",
                  body: { exercise_id: exId, exercise_name: name },
                });
                setSwapModal({ open: false, exIdx: null });
                await load();
              } catch (e: any) { setError(e?.message || "Add failed"); }
              finally { setSaving(false); }
            } else {
              await submitSwap(exId, name);
            }
          }}
        />
      </Modal>

      {/* Regen preview modal */}
      <Modal visible={regenModal.open} transparent animationType="slide" onRequestClose={() => setRegenModal({ ...regenModal, open: false })}>
        <View style={styles.modalBg}>
          <View style={styles.sheet}>
            <View style={styles.sheetHandle} />
            <Text style={styles.sheetTitle}>Regeneration preview · {regenModal.preset}</Text>
            {regenModal.preview?.guidance ? (
              <Text style={styles.sheetSub}>{regenModal.preview.guidance}</Text>
            ) : null}
            <View style={{ flexDirection: "row", gap: 10, marginTop: 12 }}>
              <View style={{ flex: 1, backgroundColor: theme.color.cardBg, padding: 10, borderRadius: 8, borderWidth: 1, borderColor: theme.color.line }}>
                <Text style={styles.diffLbl}>CURRENT</Text>
                <Text style={styles.diffV}>{regenModal.preview?.original?.title}</Text>
                <Text style={styles.diffSub}>{regenModal.preview?.original?.duration_min} min · {regenModal.preview?.original?.exercises_count} ex</Text>
              </View>
              <View style={{ flex: 1, backgroundColor: "#0d2018", padding: 10, borderRadius: 8, borderWidth: 1, borderColor: theme.color.green }}>
                <Text style={styles.diffLbl}>PREVIEW</Text>
                <Text style={styles.diffV}>{regenModal.preview?.preview?.title}</Text>
                <Text style={styles.diffSub}>{regenModal.preview?.preview?.duration_min} min · {(regenModal.preview?.preview?.exercises || []).length} ex</Text>
              </View>
            </View>
            {regenModal.preset === "custom" && (
              <TextInput
                style={[styles.input, { minHeight: 60, marginTop: 12 }]}
                placeholder="Custom instruction for this regen"
                placeholderTextColor={theme.color.textMuted}
                value={regenModal.custom}
                onChangeText={(v) => setRegenModal({ ...regenModal, custom: v })}
                multiline
              />
            )}
            <View style={styles.sheetBtnRow}>
              <Pressable onPress={() => setRegenModal({ ...regenModal, open: false })} style={styles.secondaryBtn}>
                <Text style={styles.secondaryBtnT}>Cancel</Text>
              </Pressable>
              <Pressable onPress={applyRegen} style={styles.primaryBtn}>
                <Text style={styles.primaryBtnT}>Apply Regeneration</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

// ---- Exercise Swap sheet — V2 Library search ----
function ExerciseSwapSheet({ onClose, onPick }: { onClose: () => void; onPick: (id: string, name: string) => void }) {
  const [q, setQ] = useState("");
  const [filters, setFilters] = useState<Record<string, boolean>>({});
  const [results, setResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  const filterKeys = useMemo(() => (
    [
      { id: "hotel_friendly", label: "Hotel" },
      { id: "bodyweight", label: "Bodyweight" },
      { id: "injury_friendly", label: "Injury-friendly" },
      { id: "running_support", label: "Running support" },
      { id: "mobility", label: "Mobility" },
      { id: "strength", label: "Strength" },
      { id: "conditioning", label: "Conditioning" },
    ]
  ), []);

  const doSearch = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (q) params.set("q", q);
      Object.entries(filters).forEach(([k, v]) => v && params.set(k, "true"));
      params.set("limit", "30");
      const r = await api<any>(`/exercises/v2/search?${params.toString()}`);
      setResults(r?.exercises || []);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, [q, filters]);
  useEffect(() => { doSearch(); }, [doSearch]);

  return (
    <View style={styles.modalBg}>
      <View style={[styles.sheet, { maxHeight: "92%" }]}>
        <View style={styles.sheetHandle} />
        <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
          <Text style={styles.sheetTitle}>Exercise Swap</Text>
          <Pressable onPress={onClose} hitSlop={12}><Ionicons name="close" size={22} color={theme.color.text} /></Pressable>
        </View>
        <TextInput
          style={styles.input}
          placeholder="Search the approved V2 library..."
          placeholderTextColor={theme.color.textMuted}
          value={q}
          onChangeText={setQ}
          returnKeyType="search"
          onSubmitEditing={doSearch}
        />
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 8 }}>
          <View style={{ flexDirection: "row", gap: 6 }}>
            {filterKeys.map((f) => {
              const on = filters[f.id];
              return (
                <Pressable key={f.id} onPress={() => setFilters((prev) => ({ ...prev, [f.id]: !on }))} style={[styles.filterPill, on && styles.filterPillOn]}>
                  <Text style={[styles.filterPillT, on && { color: "#fff" }]}>{f.label}</Text>
                </Pressable>
              );
            })}
          </View>
        </ScrollView>
        <ScrollView style={{ marginTop: 12, maxHeight: 380 }}>
          {loading ? <ActivityIndicator color={theme.color.brand} /> : results.map((ex) => (
            <Pressable key={ex.id} onPress={() => onPick(ex.id, ex.exercise_name)} style={styles.resultRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.resName}>{ex.exercise_name}</Text>
                <Text style={styles.resMeta}>{[ex.movement_pattern, ex.equipment_type, ex.difficulty].filter(Boolean).join(" · ")}</Text>
                {(ex.tags || []).length ? <Text style={styles.resTags}>{(ex.tags || []).slice(0, 4).join(" · ")}</Text> : null}
              </View>
              <Ionicons name="chevron-forward" size={16} color={theme.color.textMuted} />
            </Pressable>
          ))}
          {!loading && results.length === 0 && <Text style={styles.muted}>No exercises match your filters.</Text>}
        </ScrollView>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: theme.color.bg },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 12, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: theme.color.line },
  backBtn: { width: 32, height: 32, alignItems: "center", justifyContent: "center" },
  title: { color: theme.color.text, fontSize: 15, fontWeight: "800", flex: 1, marginHorizontal: 6 },
  sectHeader: { color: theme.color.textMuted, fontSize: 11, fontWeight: "800", letterSpacing: 1.2, marginTop: 12, marginBottom: 8 },
  sectRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: 8 },
  card: { backgroundColor: theme.color.cardBg, borderWidth: 1, borderColor: theme.color.line, borderRadius: 10, padding: 12, marginBottom: 10 },
  // Iter 102 — Layover context (coach edit page)
  layoverCard: {
    padding: 10,
    borderRadius: 8,
    backgroundColor: theme.color.brandTint,
    borderLeftWidth: 3,
    borderLeftColor: theme.color.brand,
    marginBottom: 12,
  },
  layoverHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 4 },
  layoverEyebrow: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  layoverFlag: {
    color: theme.color.amber,
    fontSize: 11, fontWeight: "900", letterSpacing: 0.8,
    borderWidth: 1, borderColor: theme.color.amber,
    paddingHorizontal: 5, paddingVertical: 2, borderRadius: 3,
  },
  layoverBody: { color: theme.color.text, fontSize: 12, lineHeight: 16 },
  layoverHint: { color: theme.color.textMuted, fontSize: 11, marginTop: 6, fontStyle: "italic" },
  fieldLbl: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 0.8, fontWeight: "700", marginBottom: 6, textTransform: "uppercase" },
  input: { backgroundColor: theme.color.bg, borderWidth: 1, borderColor: theme.color.line, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 8, color: theme.color.text, fontSize: 13 },
  exName: { color: theme.color.text, fontSize: 14, fontWeight: "700", flex: 1 },
  exField: { backgroundColor: theme.color.bg, borderWidth: 1, borderColor: theme.color.line, borderRadius: 6, paddingHorizontal: 8, paddingVertical: 6, color: theme.color.text, fontSize: 13, textAlign: "center" },
  exFieldLbl: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700", letterSpacing: 0.6, marginBottom: 3, textAlign: "center" },
  iconBtn: { padding: 6, borderRadius: 6, borderWidth: 1, borderColor: theme.color.line, backgroundColor: theme.color.bg },
  smallBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6, borderWidth: 1, borderColor: theme.color.brand },
  smallBtnT: { color: theme.color.brand, fontSize: 11, letterSpacing: 0.8, fontWeight: "800" },
  pill: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6, borderWidth: 1, borderColor: theme.color.line },
  pillActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  pillT: { color: theme.color.text, fontSize: 11, fontWeight: "800", letterSpacing: 0.8 },
  presetGrid: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  presetBtn: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 10, paddingVertical: 8, borderRadius: 8, borderWidth: 1, borderColor: theme.color.line, backgroundColor: theme.color.cardBg, marginBottom: 6 },
  presetBtnT: { color: theme.color.text, fontSize: 12, fontWeight: "600" },
  muted: { color: theme.color.textMuted, fontSize: 12 },
  primaryBtn: { backgroundColor: theme.color.brand, borderRadius: 8, paddingVertical: 12, paddingHorizontal: 16, alignItems: "center", flex: 1 },
  primaryBtnT: { color: "#fff", fontWeight: "800", letterSpacing: 0.5 },
  secondaryBtn: { flex: 1, paddingVertical: 12, borderRadius: 8, borderWidth: 1, borderColor: theme.color.line, alignItems: "center" },
  secondaryBtnT: { color: theme.color.text, fontWeight: "700" },
  errCard: { flexDirection: "row", alignItems: "center", gap: 8, padding: 10, borderRadius: 8, backgroundColor: "#2a1010", marginBottom: 12 },
  errTxt: { color: theme.color.red, flex: 1, fontSize: 12 },
  // modal
  modalBg: { flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(0,0,0,0.6)" },
  sheet: { backgroundColor: theme.color.bg, borderTopLeftRadius: 16, borderTopRightRadius: 16, padding: 18, maxHeight: "85%" },
  sheetHandle: { width: 44, height: 4, backgroundColor: theme.color.line, borderRadius: 2, alignSelf: "center", marginBottom: 12 },
  sheetTitle: { color: theme.color.text, fontSize: 16, fontWeight: "800" },
  sheetSub: { color: theme.color.textMuted, fontSize: 12, marginTop: 6, lineHeight: 16 },
  sheetBtnRow: { flexDirection: "row", gap: 10, marginTop: 16 },
  diffLbl: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1, fontWeight: "800" },
  diffV: { color: theme.color.text, fontSize: 13, fontWeight: "800", marginTop: 4 },
  diffSub: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },
  filterPill: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, borderWidth: 1, borderColor: theme.color.line, backgroundColor: theme.color.cardBg },
  filterPillOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  filterPillT: { color: theme.color.text, fontSize: 11, fontWeight: "700" },
  resultRow: { flexDirection: "row", alignItems: "center", gap: 10, padding: 10, borderBottomWidth: 1, borderBottomColor: theme.color.line },
  resName: { color: theme.color.text, fontSize: 13, fontWeight: "700" },
  resMeta: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },
  resTags: { color: theme.color.brand, fontSize: 11, marginTop: 2, letterSpacing: 0.5 },
});
