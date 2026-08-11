/**
 * ManualWorkoutBuilderSheet — Phase 1 Manual Workout Builder.
 *
 * Right drawer on desktop, full-screen modal on phone.
 * Reused from create + edit flows.
 * Writes to POST /coach/clients/{cid}/workouts/manual
 * and    PATCH /coach/workouts/{wid}/manual
 *
 * Uses the existing exercise picker /exercises/v2/search for exercise
 * selection — no new library.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, Pressable, StyleSheet, ScrollView, TextInput,
  Modal, ActivityIndicator, Alert, Platform, useWindowDimensions,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type ExerciseRow = {
  exercise_id: string;
  name?: string;
  sets?: number | null;
  reps?: string | null;
  duration_sec?: number | null;
  load?: string | null;
  rest_sec?: number | null;
  tempo?: string | null;
  rpe?: number | null;
  notes?: string | null;
  equipment?: string | null;
  alternative_exercise_id?: string | null;
};

const WORKOUT_TYPES = [
  { key: "strength", label: "Strength" },
  { key: "run", label: "Run" },
  { key: "cardio", label: "Cardio" },
  { key: "mobility", label: "Mobility" },
  { key: "recovery", label: "Recovery" },
  { key: "other", label: "Other" },
];

type Props = {
  visible: boolean;
  onClose: () => void;
  onSaved: (result: { workout: any; missing_media?: { exercise_id: string; name: string }[]; override_id?: string }) => void;
  clientId: string;
  date: string;
  // When editing, pass the existing manual workout doc.
  editing?: any | null;
  // If true, on create we also set a replace_day override pointing at the new workout.
  replaceGenerated?: boolean;
};

export default function ManualWorkoutBuilderSheet(props: Props) {
  const { visible, onClose, onSaved, clientId, date, editing, replaceGenerated } = props;
  const { width } = useWindowDimensions();
  const isDesktop = width >= 900;

  const isEdit = !!editing;
  const [busy, setBusy] = useState(false);
  const [title, setTitle] = useState("");
  const [workoutType, setWorkoutType] = useState("strength");
  const [duration, setDuration] = useState<string>("");
  const [location, setLocation] = useState<string>("");
  const [equipmentContext, setEquipmentContext] = useState<string>("");
  const [rpe, setRpe] = useState<string>("");
  const [coachNotes, setCoachNotes] = useState<string>("");
  const [warmup, setWarmup] = useState<ExerciseRow[]>([]);
  const [main, setMain] = useState<ExerciseRow[]>([]);
  const [cool, setCool] = useState<ExerciseRow[]>([]);

  const [pickerOpen, setPickerOpen] = useState<null | "warmup" | "main" | "cooldown">(null);

  // Reset / hydrate on open
  useEffect(() => {
    if (!visible) return;
    if (editing) {
      setTitle(editing.title || "");
      setWorkoutType(editing.workout_type || editing.focus || "strength");
      setDuration(editing.duration_min ? String(editing.duration_min) : "");
      setLocation(editing.location || "");
      setEquipmentContext(editing.equipment_context || "");
      setRpe(editing.rpe ? String(editing.rpe) : "");
      setCoachNotes(editing.coach_notes || "");
      const norm = (arr: any[]) => (arr || []).map((e: any) => ({
        exercise_id: e.exercise_id,
        name: e.name,
        sets: e.sets, reps: e.reps, duration_sec: e.duration_sec, load: e.load,
        rest_sec: e.rest_sec, tempo: e.tempo, rpe: e.rpe, notes: e.notes,
        equipment: e.equipment, alternative_exercise_id: e.alternative_exercise_id,
      }));
      setWarmup(norm(editing.warmup));
      setMain(norm(editing.exercises));
      setCool(norm(editing.cooldown));
    } else {
      setTitle("");
      setWorkoutType("strength");
      setDuration("");
      setLocation("");
      setEquipmentContext("");
      setRpe("");
      setCoachNotes("");
      setWarmup([]); setMain([]); setCool([]);
    }
  }, [visible, editing]);

  const addExercise = useCallback((section: "warmup" | "main" | "cooldown", ex: ExerciseRow) => {
    if (section === "warmup") setWarmup(w => [...w, ex]);
    else if (section === "main") setMain(w => [...w, ex]);
    else setCool(w => [...w, ex]);
  }, []);

  const removeExercise = useCallback((section: "warmup" | "main" | "cooldown", idx: number) => {
    if (section === "warmup") setWarmup(w => w.filter((_, i) => i !== idx));
    else if (section === "main") setMain(w => w.filter((_, i) => i !== idx));
    else setCool(w => w.filter((_, i) => i !== idx));
  }, []);

  const updateExercise = useCallback((section: "warmup" | "main" | "cooldown", idx: number, patch: Partial<ExerciseRow>) => {
    const upd = (arr: ExerciseRow[]) => arr.map((e, i) => i === idx ? { ...e, ...patch } : e);
    if (section === "warmup") setWarmup(upd);
    else if (section === "main") setMain(upd);
    else setCool(upd);
  }, []);

  const moveExercise = useCallback((section: "warmup" | "main" | "cooldown", idx: number, dir: -1 | 1) => {
    const move = (arr: ExerciseRow[]) => {
      const next = [...arr];
      const j = idx + dir;
      if (j < 0 || j >= next.length) return next;
      [next[idx], next[j]] = [next[j], next[idx]];
      return next;
    };
    if (section === "warmup") setWarmup(move);
    else if (section === "main") setMain(move);
    else setCool(move);
  }, []);

  const canSave = useMemo(
    () => title.trim().length > 0 && main.length > 0 && !busy,
    [title, main.length, busy],
  );

  const save = useCallback(async () => {
    if (!canSave) return;
    setBusy(true);
    try {
      const body: any = {
        title: title.trim(),
        workout_type: workoutType,
        duration_min: duration ? Number(duration) : undefined,
        location: location || undefined,
        equipment_context: equipmentContext || undefined,
        rpe: rpe ? Number(rpe) : undefined,
        coach_notes: coachNotes || undefined,
        warmup, exercises: main, cooldown: cool,
      };
      let result: any;
      if (isEdit) {
        result = await api(`/coach/workouts/${editing.id}/manual`, { method: "PATCH", body });
      } else {
        body.date = date;
        if (replaceGenerated) body.override_mode = "replace_day";
        result = await api(`/coach/clients/${clientId}/workouts/manual`, { method: "POST", body });
      }
      onSaved(result);
      onClose();
    } catch (e: any) {
      Alert.alert("Could not save", e?.message || "Please try again.");
    } finally {
      setBusy(false);
    }
  }, [canSave, title, workoutType, duration, location, equipmentContext, rpe,
      coachNotes, warmup, main, cool, isEdit, editing, date, clientId, replaceGenerated, onSaved, onClose]);

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.overlay}>
        <Pressable style={{ flex: 1 }} onPress={onClose} />
        <View style={[styles.sheet, isDesktop ? styles.sheetDesktop : styles.sheetMobile]}>
          <View style={styles.head}>
            <Text style={styles.headTitle} testID="manual-sheet-title">
              {isEdit ? "Edit manual workout" : "New manual workout"} · {date}
            </Text>
            <Pressable onPress={onClose} testID="manual-sheet-close">
              <Ionicons name="close" size={22} color={theme.color.textHi} />
            </Pressable>
          </View>
          <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: 16, paddingBottom: 120 }}>
            <Field label="Title" value={title} onChange={setTitle} wide />
            <View style={styles.typeRow}>
              {WORKOUT_TYPES.map(t => (
                <Pressable
                  key={t.key}
                  style={[styles.typePill, workoutType === t.key && styles.typePillActive]}
                  onPress={() => setWorkoutType(t.key)}
                  testID={`manual-type-${t.key}`}
                >
                  <Text style={[styles.typePillText, workoutType === t.key && styles.typePillTextActive]}>{t.label}</Text>
                </Pressable>
              ))}
            </View>
            <View style={styles.metaRow}>
              <Field label="Duration (min)" value={duration} onChange={setDuration} kbd="number-pad" />
              <Field label="RPE" value={rpe} onChange={setRpe} kbd="decimal-pad" />
              <Field label="Location" value={location} onChange={setLocation} />
              <Field label="Equipment context" value={equipmentContext} onChange={setEquipmentContext} />
            </View>
            <Text style={styles.fieldLabel}>Coach notes</Text>
            <TextInput
              style={styles.notesInput}
              value={coachNotes}
              onChangeText={setCoachNotes}
              placeholder="Anything the client needs to know…"
              placeholderTextColor="#666"
              multiline
            />

            <Section
              label="Warm-up" section="warmup" items={warmup}
              onAdd={setPickerOpen} onMove={moveExercise}
              onRemove={removeExercise} onUpdate={updateExercise}
            />
            <Section
              label="Main workout" section="main" items={main}
              onAdd={setPickerOpen} onMove={moveExercise}
              onRemove={removeExercise} onUpdate={updateExercise}
            />
            <Section
              label="Cool-down" section="cooldown" items={cool}
              onAdd={setPickerOpen} onMove={moveExercise}
              onRemove={removeExercise} onUpdate={updateExercise}
            />
          </ScrollView>

          <View style={styles.footer}>
            <Pressable onPress={onClose} style={styles.footerCancel} testID="manual-sheet-cancel">
              <Text style={styles.footerCancelText}>Cancel</Text>
            </Pressable>
            <Pressable
              onPress={save}
              disabled={!canSave}
              style={[styles.footerSave, !canSave && { opacity: 0.5 }]}
              testID="manual-sheet-save"
            >
              {busy ? <ActivityIndicator color="#fff" /> :
                <Text style={styles.footerSaveText}>{isEdit ? "Save changes" : (replaceGenerated ? "Save & replace day" : "Save workout")}</Text>}
            </Pressable>
          </View>
        </View>
      </View>

      <ExercisePickerModal
        visible={!!pickerOpen}
        onClose={() => setPickerOpen(null)}
        onPick={(ex) => {
          if (pickerOpen) addExercise(pickerOpen, ex);
          setPickerOpen(null);
        }}
      />
    </Modal>
  );
}

function Field({ label, value, onChange, kbd, wide }: {
  label: string; value: string; onChange: (v: string) => void;
  kbd?: any; wide?: boolean;
}) {
  // `wide` = title / single-column field: render as a normal block so it
  // sits above the meta row. `wide=false` = one of the meta-row grid cells
  // (flexBasis 48% inside a flexDirection:"row" wrap parent).
  return (
    <View style={wide ? styles.fieldWide : styles.field}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <TextInput
        style={styles.fieldInput}
        value={value}
        onChangeText={onChange}
        placeholderTextColor="#666"
        keyboardType={kbd}
      />
    </View>
  );
}

/**
 * Module-scope Section — MUST NOT be redefined inside the parent component
 * because that recreates the component reference on every parent re-render
 * (which happens on every keystroke to Title/Duration/etc.), unmounts the
 * TextInputs inside, and produces a "crash" on React Native Web where inputs
 * become unresponsive after the first character.
 */
function Section({
  label, section, items, onAdd, onMove, onRemove, onUpdate,
}: {
  label: string;
  section: "warmup" | "main" | "cooldown";
  items: ExerciseRow[];
  onAdd: (s: "warmup" | "main" | "cooldown") => void;
  onMove: (s: "warmup" | "main" | "cooldown", idx: number, dir: -1 | 1) => void;
  onRemove: (s: "warmup" | "main" | "cooldown", idx: number) => void;
  onUpdate: (s: "warmup" | "main" | "cooldown", idx: number, patch: Partial<ExerciseRow>) => void;
}) {
  return (
    <View style={styles.section}>
      <View style={styles.sectionHead}>
        <Text style={styles.sectionTitle}>{label}</Text>
        <Pressable
          style={styles.addBtn}
          onPress={() => onAdd(section)}
          testID={`manual-add-${section}`}
        >
          <Ionicons name="add" size={16} color="#fff" />
          <Text style={styles.addBtnText}>Add exercise</Text>
        </Pressable>
      </View>
      {items.length === 0 ? (
        <Text style={styles.sectionEmpty}>No exercises yet</Text>
      ) : items.map((e, i) => (
        <View key={`${section}-${i}`} style={styles.exRow}>
          <View style={styles.exHead}>
            <Text style={styles.exName} numberOfLines={1}>{i + 1}. {e.name || e.exercise_id}</Text>
            <View style={styles.exActions}>
              <Pressable onPress={() => onMove(section, i, -1)} disabled={i === 0} style={styles.exIcon}>
                <Ionicons name="arrow-up" size={14} color={i === 0 ? "#666" : theme.color.textHi} />
              </Pressable>
              <Pressable onPress={() => onMove(section, i, 1)} disabled={i === items.length - 1} style={styles.exIcon}>
                <Ionicons name="arrow-down" size={14} color={i === items.length - 1 ? "#666" : theme.color.textHi} />
              </Pressable>
              <Pressable onPress={() => onRemove(section, i)} style={styles.exIcon}>
                <Ionicons name="trash" size={14} color="#ff6b6b" />
              </Pressable>
            </View>
          </View>
          <View style={styles.exFields}>
            <Field label="Sets" value={e.sets ? String(e.sets) : ""}
              onChange={v => onUpdate(section, i, { sets: v ? Number(v) : null })} kbd="number-pad" />
            <Field label="Reps / time" value={e.reps || ""} onChange={v => onUpdate(section, i, { reps: v })} />
            <Field label="Duration (sec)" value={e.duration_sec ? String(e.duration_sec) : ""}
              onChange={v => onUpdate(section, i, { duration_sec: v ? Number(v) : null })} kbd="number-pad" />
            <Field label="Load" value={e.load || ""} onChange={v => onUpdate(section, i, { load: v })} />
            <Field label="Rest (sec)" value={e.rest_sec ? String(e.rest_sec) : ""}
              onChange={v => onUpdate(section, i, { rest_sec: v ? Number(v) : null })} kbd="number-pad" />
            <Field label="Tempo" value={e.tempo || ""} onChange={v => onUpdate(section, i, { tempo: v })} />
            <Field label="RPE" value={e.rpe ? String(e.rpe) : ""}
              onChange={v => onUpdate(section, i, { rpe: v ? Number(v) : null })} kbd="decimal-pad" />
            <Field label="Equipment" value={e.equipment || ""} onChange={v => onUpdate(section, i, { equipment: v })} />
          </View>
          <TextInput
            style={styles.notesInput}
            value={e.notes || ""}
            onChangeText={v => onUpdate(section, i, { notes: v })}
            placeholder="Coaching notes"
            placeholderTextColor="#666"
            multiline
          />
        </View>
      ))}
    </View>
  );
}

function ExercisePickerModal({ visible, onClose, onPick }: {
  visible: boolean; onClose: () => void;
  onPick: (ex: ExerciseRow) => void;
}) {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);

  // "Create new exercise" inline form state.
  const [createOpen, setCreateOpen] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createCategory, setCreateCategory] = useState<string>("strength");
  const [createEquipment, setCreateEquipment] = useState<string>("");
  const [createSaving, setCreateSaving] = useState(false);

  const openCreate = useCallback((prefill: string) => {
    setCreateName(prefill);
    setCreateEquipment("");
    setCreateCategory("strength");
    setCreateOpen(true);
  }, []);

  const submitCreate = useCallback(async () => {
    const name = (createName || "").trim();
    if (!name) { Alert.alert("Name required", "Please enter an exercise name."); return; }
    setCreateSaving(true);
    try {
      // Endpoint already exists: POST /exercise-content → inserts into
      // db.exercises_v2 with content_status.images/video/coaching_points=false,
      // so it appears in the coach media library's "Needs Media" filter.
      const equipment = createEquipment
        .split(",").map(e => e.trim()).filter(Boolean);
      const res = await api<{ exercise: any }>("/exercise-content", {
        method: "POST",
        body: {
          exercise_name: name,
          category: createCategory,
          equipment_type: equipment.length ? equipment : undefined,
        },
      });
      const newEx = res.exercise;
      // Auto-pick so it's added to the workout immediately.
      onPick({ exercise_id: newEx.id, name: newEx.exercise_name });
      setCreateOpen(false);
    } catch (e: any) {
      Alert.alert("Could not create", e?.message || "Try a different name.");
    } finally {
      setCreateSaving(false);
    }
  }, [createName, createCategory, createEquipment, onPick]);

  useEffect(() => {
    if (!visible) return;
    setQ(""); setCreateOpen(false);
    let cancel = false;
    (async () => {
      setBusy(true);
      try {
        const res = await api<{ exercises: any[] }>(`/exercises/v2/search?limit=60`);
        if (!cancel) setRows(res.exercises || []);
      } finally { if (!cancel) setBusy(false); }
    })();
    return () => { cancel = true; };
  }, [visible]);

  useEffect(() => {
    if (!visible) return;
    const t = setTimeout(async () => {
      setBusy(true);
      try {
        const res = await api<{ exercises: any[] }>(`/exercises/v2/search?limit=60${q ? `&q=${encodeURIComponent(q)}` : ""}`);
        setRows(res.exercises || []);
      } finally { setBusy(false); }
    }, 250);
    return () => clearTimeout(t);
  }, [q, visible]);

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.pickerOverlay}>
        <View style={styles.pickerBox}>
          <View style={styles.pickerHead}>
            <Text style={styles.pickerTitle}>Add exercise from library</Text>
            <Pressable onPress={onClose} testID="picker-close">
              <Ionicons name="close" size={20} color={theme.color.textHi} />
            </Pressable>
          </View>
          <TextInput
            style={styles.pickerSearch}
            value={q}
            onChangeText={setQ}
            placeholder="Search…"
            placeholderTextColor="#666"
            autoFocus
            testID="picker-search"
          />
          {!createOpen ? (
            <Pressable
              style={styles.createNewRow}
              onPress={() => openCreate(q)}
              testID="picker-create-new"
            >
              <Ionicons name="add-circle" size={20} color={theme.color.brand} />
              <View style={{ flex: 1, marginLeft: 8 }}>
                <Text style={styles.createNewTitle}>
                  Create new exercise{q ? ` "${q}"` : ""}
                </Text>
                <Text style={styles.createNewSub}>
                  Adds to library · appears in coach media queue for content generation
                </Text>
              </View>
            </Pressable>
          ) : (
            <View style={styles.createBox}>
              <Text style={styles.fieldLabel}>Exercise name</Text>
              <TextInput
                style={styles.fieldInput}
                value={createName}
                onChangeText={setCreateName}
                placeholder="e.g. Single-arm Landmine Press"
                placeholderTextColor="#666"
                autoCapitalize="words"
              />
              <Text style={styles.fieldLabel}>Category</Text>
              <View style={styles.typeRow}>
                {["strength","cardio","mobility","warmup","core","conditioning"].map(c => (
                  <Pressable
                    key={c}
                    style={[styles.typePill, createCategory === c && styles.typePillActive]}
                    onPress={() => setCreateCategory(c)}
                  >
                    <Text style={[styles.typePillText, createCategory === c && styles.typePillTextActive]}>
                      {c}
                    </Text>
                  </Pressable>
                ))}
              </View>
              <Text style={styles.fieldLabel}>Equipment (comma-separated, optional)</Text>
              <TextInput
                style={styles.fieldInput}
                value={createEquipment}
                onChangeText={setCreateEquipment}
                placeholder="e.g. barbell, bench"
                placeholderTextColor="#666"
              />
              <View style={{ flexDirection: "row", gap: 8, marginTop: 10 }}>
                <Pressable
                  style={[styles.footerCancel, { flex: 1 }]}
                  onPress={() => setCreateOpen(false)}
                  disabled={createSaving}
                >
                  <Text style={styles.footerCancelText}>Cancel</Text>
                </Pressable>
                <Pressable
                  style={[styles.footerSave, { flex: 2 }]}
                  onPress={submitCreate}
                  disabled={createSaving || !(createName || "").trim()}
                  testID="picker-create-submit"
                >
                  {createSaving
                    ? <ActivityIndicator color="#000" />
                    : <Text style={styles.footerSaveText}>Create + add to workout</Text>}
                </Pressable>
              </View>
            </View>
          )}
          <ScrollView style={{ maxHeight: 360 }}>
            {busy && <ActivityIndicator color={theme.color.brand} style={{ margin: 16 }} />}
            {!busy && rows.length === 0 && !createOpen && (
              <View style={{ paddingHorizontal: 20, paddingVertical: 24 }}>
                <Text style={styles.pickerEmpty}>
                  No matching exercises found. Use &ldquo;Create new exercise&rdquo; above.
                </Text>
              </View>
            )}
            {!busy && rows.map((r) => (
              <Pressable
                key={r.id}
                style={styles.pickerRow}
                onPress={() => onPick({ exercise_id: r.id, name: r.exercise_name })}
                testID={`picker-pick-${r.id}`}
              >
                <View style={{ flex: 1 }}>
                  <Text style={styles.pickerName}>{r.exercise_name}</Text>
                  <Text style={styles.pickerMeta} numberOfLines={1}>
                    {(r.movement_pattern || "—")} · {Array.isArray(r.equipment_type) ? r.equipment_type.join(", ") : (r.equipment_type || "—")}
                  </Text>
                </View>
                <Ionicons name="add-circle" size={20} color={theme.color.brand} />
              </Pressable>
            ))}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.6)", flexDirection: "row" },
  sheet: { backgroundColor: theme.color.bg, borderLeftWidth: 1, borderColor: theme.color.border, flexDirection: "column" },
  sheetDesktop: { width: 720, height: "100%" },
  sheetMobile: { width: "100%", height: "92%", borderTopLeftRadius: 16, borderTopRightRadius: 16, alignSelf: "flex-end" },
  head: { flexDirection: "row", alignItems: "center", padding: 16, borderBottomWidth: 1, borderBottomColor: theme.color.border, justifyContent: "space-between" },
  headTitle: { color: theme.color.textHi, fontSize: 16, fontWeight: "700" },
  field: { flexBasis: "48%", flexGrow: 1, marginBottom: 12, marginRight: 8 },
  fieldWide: { width: "100%", marginBottom: 12 },
  fieldLabel: { color: theme.color.textDim, fontSize: 11, marginBottom: 4, textTransform: "uppercase", letterSpacing: 0.5 },
  fieldInput: { backgroundColor: theme.color.card, color: theme.color.textHi, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 8, borderWidth: 1, borderColor: theme.color.border },
  metaRow: { flexDirection: "row", flexWrap: "wrap", marginTop: 4 },
  typeRow: { flexDirection: "row", flexWrap: "wrap", marginBottom: 12 },
  typePill: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 16, borderWidth: 1, borderColor: theme.color.border, marginRight: 6, marginBottom: 6 },
  typePillActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  typePillText: { color: theme.color.textHi, fontSize: 12 },
  typePillTextActive: { color: "#000", fontWeight: "700" },
  notesInput: { minHeight: 60, backgroundColor: theme.color.card, color: theme.color.textHi, borderRadius: 8, padding: 10, borderWidth: 1, borderColor: theme.color.border, marginBottom: 12, textAlignVertical: "top" },
  section: { marginTop: 8, marginBottom: 8, borderTopWidth: 1, borderTopColor: theme.color.border, paddingTop: 12 },
  sectionHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 8 },
  sectionTitle: { color: theme.color.textHi, fontSize: 14, fontWeight: "700", letterSpacing: 0.5 },
  sectionEmpty: { color: theme.color.textDim, fontSize: 12, fontStyle: "italic", marginBottom: 8 },
  addBtn: { flexDirection: "row", alignItems: "center", backgroundColor: theme.color.brand, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 16 },
  addBtnText: { color: "#000", fontWeight: "700", fontSize: 12, marginLeft: 4 },
  exRow: { backgroundColor: theme.color.card, borderRadius: 10, padding: 10, marginBottom: 8, borderWidth: 1, borderColor: theme.color.border },
  exHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 6 },
  exName: { color: theme.color.textHi, fontWeight: "600", flex: 1 },
  exActions: { flexDirection: "row", gap: 6 },
  exIcon: { padding: 4 },
  exFields: { flexDirection: "row", flexWrap: "wrap", marginRight: -8 },
  footer: { flexDirection: "row", padding: 12, borderTopWidth: 1, borderTopColor: theme.color.border, gap: 8 },
  footerCancel: { flex: 1, paddingVertical: 12, borderRadius: 8, alignItems: "center", borderWidth: 1, borderColor: theme.color.border },
  footerCancelText: { color: theme.color.textHi, fontWeight: "600" },
  footerSave: { flex: 2, paddingVertical: 12, borderRadius: 8, alignItems: "center", backgroundColor: theme.color.brand },
  footerSaveText: { color: "#000", fontWeight: "700" },
  pickerOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.7)", alignItems: "center", justifyContent: "center", padding: 20 },
  pickerBox: { backgroundColor: theme.color.bg, borderRadius: 12, width: "100%", maxWidth: 460, borderWidth: 1, borderColor: theme.color.border, overflow: "hidden" },
  pickerHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 12, borderBottomWidth: 1, borderBottomColor: theme.color.border },
  pickerTitle: { color: theme.color.textHi, fontWeight: "700" },
  pickerSearch: { margin: 10, padding: 10, backgroundColor: theme.color.card, color: theme.color.textHi, borderRadius: 8, borderWidth: 1, borderColor: theme.color.border },
  pickerRow: { flexDirection: "row", alignItems: "center", padding: 12, borderTopWidth: 1, borderTopColor: theme.color.border },
  pickerName: { color: theme.color.textHi, fontWeight: "600" },
  pickerMeta: { color: theme.color.textDim, fontSize: 11 },
  pickerEmpty: { color: theme.color.textDim, textAlign: "center", padding: 24 },
  /* Create new exercise (Manual Builder → picker → new exercise flow) */
  createNewRow: {
    flexDirection: "row", alignItems: "center", padding: 12,
    marginHorizontal: 10, marginBottom: 4,
    backgroundColor: theme.color.card,
    borderWidth: 1, borderColor: theme.color.brand + "88",
    borderRadius: 8,
  },
  createNewTitle: { color: theme.color.textHi, fontWeight: "700", fontSize: 13 },
  createNewSub: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },
  createBox: {
    marginHorizontal: 10, marginBottom: 8, padding: 12,
    backgroundColor: theme.color.card, borderRadius: 8,
    borderWidth: 1, borderColor: theme.color.border,
  },
});
