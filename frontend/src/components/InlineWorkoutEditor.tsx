/**
 * InlineWorkoutEditor — Coach Dashboard V2 inline workout editor.
 *
 * Priority 5 of the Coach Dashboard V2 PRD:
 *   Coach can tweak reps / sets / RPE / rest / equipment / add/remove
 *   exercises WITHOUT leaving the workspace drawer. Edits mutate the
 *   DRAFT implementation and mark the assignment coach-edited.
 *
 * Two-mode drawer:
 *   - VIEW  → read-only (existing WorkoutDrawer content)
 *   - EDIT  → inline form (this component)
 *
 * Guardrails:
 *   - LIVE-only implementations refuse edit (backend returns 409).
 *   - No AI wording; “Coach note” free-text is opt-in.
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, TextInput, StyleSheet, ScrollView, Pressable, ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Exercise = {
  exercise_name_display?: string;
  exercise_id?: string;
  slot_role?: string;
  sets?: number;
  reps?: string;
  rest_sec?: number;
  rpe?: number;
  hr_zone?: string;
  duration_sec?: number;
  coaching_cue?: string;
};

type Impl = {
  id: string;
  title?: string;
  focus?: string;
  duration_min?: number;
  key_session?: boolean;
  location_label?: string;
  coach_notes?: string;
  rationale?: string;
  needs_coach_review?: boolean;
  equipment_context?: { equipment?: string[] };
  exercises?: Exercise[];
};

export function InlineWorkoutEditor({
  clientId, impl, onExit, onSaved, onError,
}: {
  clientId: string;
  impl: Impl;
  onExit: () => void;
  onSaved: (fresh: Impl) => void;
  onError?: (msg: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [local, setLocal] = useState<Impl>({ ...impl });
  // Track the last server-known baseline for meta diff, so successful
  // PATCHes don't cause the next commitMeta to re-issue redundant work.
  const baselineRef = React.useRef<Impl>({ ...impl });

  const patchMeta = useCallback(
    async (fields: Partial<Impl>) => {
      setBusy(true);
      try {
        const fresh = await api<Impl>(
          `/v2/coach/clients/${clientId}/plan/implementations/${impl.id}`,
          { method: "PATCH", body: fields }
        );
        setLocal(fresh);
        baselineRef.current = fresh;
        setDirty(false);
        onSaved(fresh);
      } catch (e: any) {
        onError?.(e?.message || String(e));
      } finally {
        setBusy(false);
      }
    },
    [clientId, impl.id, onSaved, onError]
  );

  const patchExercise = useCallback(
    async (idx: number, patch: Partial<Exercise>) => {
      setBusy(true);
      try {
        const fresh = await api<Impl>(
          `/v2/coach/clients/${clientId}/plan/implementations/${impl.id}/exercises/${idx}`,
          { method: "PATCH", body: patch }
        );
        setLocal(fresh);
        baselineRef.current = fresh;
        setDirty(false);
        onSaved(fresh);
      } catch (e: any) {
        onError?.(e?.message || String(e));
      } finally {
        setBusy(false);
      }
    },
    [clientId, impl.id, onSaved, onError]
  );

  const deleteExercise = useCallback(
    async (idx: number) => {
      setBusy(true);
      try {
        const fresh = await api<Impl>(
          `/v2/coach/clients/${clientId}/plan/implementations/${impl.id}/exercises/${idx}`,
          { method: "DELETE" }
        );
        setLocal(fresh);
        baselineRef.current = fresh;
        onSaved(fresh);
      } catch (e: any) {
        onError?.(e?.message || String(e));
      } finally {
        setBusy(false);
      }
    },
    [clientId, impl.id, onSaved, onError]
  );

  const addExercise = useCallback(async () => {
    setBusy(true);
    try {
      const fresh = await api<Impl>(
        `/v2/coach/clients/${clientId}/plan/implementations/${impl.id}/exercises`,
        {
          method: "POST",
          body: {
            exercise_name_display: "New exercise",
            slot_role: "accessory",
            sets: 3, reps: "8-10", rest_sec: 90,
          },
        }
      );
      setLocal(fresh);
      baselineRef.current = fresh;
      onSaved(fresh);
    } catch (e: any) {
      onError?.(e?.message || String(e));
    } finally {
      setBusy(false);
    }
  }, [clientId, impl.id, onSaved, onError]);

  const reorder = useCallback(async (idx: number, dir: -1 | 1) => {
    const exs = local.exercises || [];
    const j = idx + dir;
    if (j < 0 || j >= exs.length) return;
    const order = exs.map((_, i) => i);
    [order[idx], order[j]] = [order[j], order[idx]];
    setBusy(true);
    try {
      const fresh = await api<Impl>(
        `/v2/coach/clients/${clientId}/plan/implementations/${impl.id}/exercises/reorder`,
        { method: "POST", body: { order } }
      );
      setLocal(fresh);
      baselineRef.current = fresh;
      onSaved(fresh);
    } catch (e: any) {
      onError?.(e?.message || String(e));
    } finally {
      setBusy(false);
    }
  }, [clientId, impl.id, local.exercises, onSaved, onError]);

  // Local staging for meta edits (title/duration/rationale) — commit on blur
  const commitMeta = useCallback(() => {
    if (!dirty) return;
    const base = baselineRef.current;
    const changed: Partial<Impl> = {};
    if (local.title !== base.title) changed.title = local.title;
    if (local.duration_min !== base.duration_min) changed.duration_min = local.duration_min;
    if (local.focus !== base.focus) changed.focus = local.focus;
    if (local.location_label !== base.location_label) changed.location_label = local.location_label;
    if (local.coach_notes !== base.coach_notes) changed.coach_notes = local.coach_notes;
    if (local.rationale !== base.rationale) changed.rationale = local.rationale;
    if (local.key_session !== base.key_session) changed.key_session = local.key_session;
    if (Object.keys(changed).length > 0) {
      patchMeta(changed);
    } else {
      setDirty(false);
    }
  }, [dirty, local, patchMeta]);

  return (
    <ScrollView contentContainerStyle={styles.wrap} testID="inline-editor">
      <View style={styles.headRow}>
        <Text style={styles.head}>EDIT SESSION</Text>
        <View style={{ flex: 1 }} />
        <Pressable style={styles.exitBtn} onPress={() => { commitMeta(); onExit(); }} testID="inline-editor-done">
          <Ionicons name="checkmark" size={14} color={theme.color.brand} />
          <Text style={styles.exitBtnText}>Done</Text>
        </Pressable>
      </View>

      {/* Meta block */}
      <Text style={styles.label}>Title</Text>
      <TextInput
        style={styles.input}
        value={local.title || ""}
        onChangeText={(v) => { setLocal({ ...local, title: v }); setDirty(true); }}
        onBlur={commitMeta}
        placeholder="Session title"
        placeholderTextColor={theme.color.textDim}
        testID="editor-title"
      />

      <View style={styles.row2}>
        <View style={styles.col2}>
          <Text style={styles.label}>Duration (min)</Text>
          <TextInput
            style={styles.input}
            keyboardType="number-pad"
            value={local.duration_min != null ? String(local.duration_min) : ""}
            onChangeText={(v) => {
              const n = v ? parseInt(v, 10) : undefined;
              setLocal({ ...local, duration_min: Number.isNaN(n as any) ? undefined : n });
              setDirty(true);
            }}
            onBlur={commitMeta}
            testID="editor-duration"
          />
        </View>
        <View style={styles.col2}>
          <Text style={styles.label}>Focus</Text>
          <TextInput
            style={styles.input}
            value={local.focus || ""}
            onChangeText={(v) => { setLocal({ ...local, focus: v }); setDirty(true); }}
            onBlur={commitMeta}
            placeholder="e.g. lower_strength"
            placeholderTextColor={theme.color.textDim}
          />
        </View>
      </View>

      <Text style={styles.label}>Location note (optional)</Text>
      <TextInput
        style={styles.input}
        value={local.location_label || ""}
        onChangeText={(v) => { setLocal({ ...local, location_label: v }); setDirty(true); }}
        onBlur={commitMeta}
        placeholder="Hotel gym / home / commercial gym"
        placeholderTextColor={theme.color.textDim}
      />

      <Text style={styles.label}>Coach note (private — visible to coach only)</Text>
      <TextInput
        style={[styles.input, { minHeight: 60 }]}
        value={local.coach_notes || ""}
        onChangeText={(v) => { setLocal({ ...local, coach_notes: v }); setDirty(true); }}
        onBlur={commitMeta}
        multiline
        placeholder="Reminders, cues, why this changed…"
        placeholderTextColor={theme.color.textDim}
        testID="editor-coach-note"
      />

      <View style={styles.togglesRow}>
        <Pressable
          style={[styles.toggleBtn, local.key_session && styles.toggleOn]}
          onPress={() => patchMeta({ key_session: !local.key_session })}
          testID="editor-key-session"
        >
          <Ionicons name={local.key_session ? "star" : "star-outline"} size={12}
            color={local.key_session ? "#f5b543" : theme.color.textDim} />
          <Text style={[styles.toggleText, local.key_session && { color: "#f5b543" }]}>Key session</Text>
        </Pressable>
        {local.needs_coach_review && (
          <Pressable
            style={styles.reviewClear}
            onPress={() => patchMeta({ needs_coach_review: false })}
            testID="editor-clear-review"
          >
            <Ionicons name="checkmark-circle" size={12} color="#61c982" />
            <Text style={styles.reviewClearText}>Mark reviewed</Text>
          </Pressable>
        )}
      </View>

      {/* Exercises */}
      <View style={styles.exHead}>
        <Text style={styles.label}>Exercises ({(local.exercises || []).length})</Text>
        <Pressable style={styles.addBtn} onPress={addExercise} testID="editor-add-exercise">
          <Ionicons name="add" size={14} color="#000" />
          <Text style={styles.addBtnText}>Add</Text>
        </Pressable>
      </View>

      {(local.exercises || []).map((ex, i) => (
        <ExerciseCard
          key={i}
          idx={i}
          count={(local.exercises || []).length}
          ex={ex}
          onPatch={(p) => patchExercise(i, p)}
          onDelete={() => deleteExercise(i)}
          onMove={(d) => reorder(i, d)}
        />
      ))}

      {busy && (
        <View style={styles.busyBar}>
          <ActivityIndicator size="small" color={theme.color.brand} />
          <Text style={styles.busyText}>Saving…</Text>
        </View>
      )}
      <View style={{ height: 32 }} />
    </ScrollView>
  );
}

function ExerciseCard({
  idx, count, ex, onPatch, onDelete, onMove,
}: {
  idx: number;
  count: number;
  ex: Exercise;
  onPatch: (p: Partial<Exercise>) => void;
  onDelete: () => void;
  onMove: (d: -1 | 1) => void;
}) {
  const [name, setName] = useState(ex.exercise_name_display || "");
  const [sets, setSets] = useState(ex.sets != null ? String(ex.sets) : "");
  const [reps, setReps] = useState(ex.reps || "");
  const [rest, setRest] = useState(ex.rest_sec != null ? String(ex.rest_sec) : "");
  const [rpe, setRpe] = useState(ex.rpe != null ? String(ex.rpe) : "");
  const [dirty, setDirty] = useState(false);
  const [cue, setCue] = useState(ex.coaching_cue || "");

  React.useEffect(() => {
    setName(ex.exercise_name_display || "");
    setSets(ex.sets != null ? String(ex.sets) : "");
    setReps(ex.reps || "");
    setRest(ex.rest_sec != null ? String(ex.rest_sec) : "");
    setRpe(ex.rpe != null ? String(ex.rpe) : "");
    setCue(ex.coaching_cue || "");
    setDirty(false);
  }, [ex]);

  const commit = () => {
    if (!dirty) return;
    const patch: Partial<Exercise> = {};
    if (name !== (ex.exercise_name_display || "")) patch.exercise_name_display = name;
    if (sets !== (ex.sets != null ? String(ex.sets) : "")) {
      const n = sets ? parseInt(sets, 10) : undefined;
      patch.sets = Number.isNaN(n as any) ? undefined : n;
    }
    if (reps !== (ex.reps || "")) patch.reps = reps || undefined;
    if (rest !== (ex.rest_sec != null ? String(ex.rest_sec) : "")) {
      const n = rest ? parseInt(rest, 10) : undefined;
      patch.rest_sec = Number.isNaN(n as any) ? undefined : n;
    }
    if (rpe !== (ex.rpe != null ? String(ex.rpe) : "")) {
      const n = rpe ? parseFloat(rpe) : undefined;
      patch.rpe = Number.isNaN(n as any) ? undefined : n;
    }
    if (cue !== (ex.coaching_cue || "")) patch.coaching_cue = cue || undefined;
    if (Object.keys(patch).length > 0) onPatch(patch);
    setDirty(false);
  };

  return (
    <View style={styles.exCard}>
      <View style={styles.exTop}>
        <TextInput
          style={styles.exName}
          value={name}
          onChangeText={(v) => { setName(v); setDirty(true); }}
          onBlur={commit}
          placeholder="Exercise name"
          placeholderTextColor={theme.color.textDim}
          testID={`ex-${idx}-name`}
        />
        <View style={styles.exActions}>
          {idx > 0 && (
            <Pressable style={styles.iconBtn} onPress={() => onMove(-1)} testID={`ex-${idx}-up`}>
              <Ionicons name="chevron-up" size={16} color={theme.color.textDim} />
            </Pressable>
          )}
          {idx < count - 1 && (
            <Pressable style={styles.iconBtn} onPress={() => onMove(1)} testID={`ex-${idx}-down`}>
              <Ionicons name="chevron-down" size={16} color={theme.color.textDim} />
            </Pressable>
          )}
          <Pressable style={styles.iconBtn} onPress={onDelete} testID={`ex-${idx}-delete`}>
            <Ionicons name="trash-outline" size={14} color="#ff6666" />
          </Pressable>
        </View>
      </View>

      <View style={styles.exGrid}>
        <MiniField label="Sets" val={sets} onChange={(v) => { setSets(v); setDirty(true); }}
          onBlur={commit} keyboardType="number-pad" testID={`ex-${idx}-sets`} />
        <MiniField label="Reps" val={reps} onChange={(v) => { setReps(v); setDirty(true); }}
          onBlur={commit} testID={`ex-${idx}-reps`} />
        <MiniField label="Rest (s)" val={rest} onChange={(v) => { setRest(v); setDirty(true); }}
          onBlur={commit} keyboardType="number-pad" testID={`ex-${idx}-rest`} />
        <MiniField label="RPE" val={rpe} onChange={(v) => { setRpe(v); setDirty(true); }}
          onBlur={commit} keyboardType="decimal-pad" testID={`ex-${idx}-rpe`} />
      </View>

      <TextInput
        style={styles.exCue}
        value={cue}
        onChangeText={(v) => { setCue(v); setDirty(true); }}
        onBlur={commit}
        placeholder="Coaching cue"
        placeholderTextColor={theme.color.textDim}
        multiline
      />
    </View>
  );
}

function MiniField({ label, val, onChange, onBlur, keyboardType, testID }: {
  label: string;
  val: string;
  onChange: (v: string) => void;
  onBlur: () => void;
  keyboardType?: any;
  testID?: string;
}) {
  return (
    <View style={styles.miniFieldWrap}>
      <Text style={styles.miniFieldLabel}>{label}</Text>
      <TextInput
        style={styles.miniFieldInput}
        value={val}
        onChangeText={onChange}
        onBlur={onBlur}
        keyboardType={keyboardType}
        testID={testID}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { padding: 16 },
  headRow: { flexDirection: "row", alignItems: "center", marginBottom: 12 },
  head: { color: theme.color.textDim, fontSize: 10, letterSpacing: 1.5, fontWeight: "800" },
  exitBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 10, paddingVertical: 5, borderRadius: 5,
    borderWidth: 1, borderColor: theme.color.brand,
  },
  exitBtnText: { color: theme.color.brand, fontSize: 11, fontWeight: "700" },

  label: {
    color: theme.color.textDim, fontSize: 10, letterSpacing: 0.8,
    fontWeight: "700", marginBottom: 4, marginTop: 8, textTransform: "uppercase",
  },
  input: {
    backgroundColor: "#00000030", borderWidth: 1, borderColor: theme.color.border,
    borderRadius: 6, paddingHorizontal: 10, paddingVertical: 8,
    color: theme.color.textHi, fontSize: 13, minHeight: 38,
  },
  row2: { flexDirection: "row", gap: 8 },
  col2: { flex: 1 },

  togglesRow: {
    flexDirection: "row", gap: 8, marginTop: 10, flexWrap: "wrap",
  },
  toggleBtn: {
    flexDirection: "row", alignItems: "center", gap: 5,
    paddingHorizontal: 10, paddingVertical: 5, borderRadius: 5,
    borderWidth: 1, borderColor: theme.color.border,
  },
  toggleOn: { borderColor: "#f5b543", backgroundColor: "#3b2d0d" },
  toggleText: { color: theme.color.textDim, fontSize: 11, fontWeight: "700" },
  reviewClear: {
    flexDirection: "row", alignItems: "center", gap: 5,
    paddingHorizontal: 10, paddingVertical: 5, borderRadius: 5,
    borderWidth: 1, borderColor: "#61c982", backgroundColor: "#0d2c1a",
  },
  reviewClearText: { color: "#61c982", fontSize: 11, fontWeight: "700" },

  exHead: {
    flexDirection: "row", alignItems: "center",
    marginTop: 20, marginBottom: 8,
  },
  addBtn: {
    marginLeft: "auto",
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 10, paddingVertical: 5, borderRadius: 5,
    backgroundColor: theme.color.brand,
  },
  addBtnText: { color: "#000", fontSize: 11, fontWeight: "800" },

  exCard: {
    backgroundColor: "#00000030", borderRadius: 8,
    borderWidth: 1, borderColor: theme.color.border,
    padding: 10, marginBottom: 8,
  },
  exTop: { flexDirection: "row", alignItems: "center", gap: 8 },
  exName: {
    flex: 1, color: theme.color.textHi, fontWeight: "700",
    fontSize: 13, paddingVertical: 4,
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  exActions: { flexDirection: "row", gap: 2 },
  iconBtn: {
    width: 26, height: 26, borderRadius: 4, alignItems: "center", justifyContent: "center",
    backgroundColor: "#00000030",
  },
  exGrid: { flexDirection: "row", gap: 6, marginTop: 8 },
  miniFieldWrap: { flex: 1 },
  miniFieldLabel: { color: theme.color.textDim, fontSize: 9, letterSpacing: 0.5, fontWeight: "700" },
  miniFieldInput: {
    backgroundColor: theme.color.bg, borderWidth: 1, borderColor: theme.color.border,
    borderRadius: 4, paddingHorizontal: 6, paddingVertical: 4,
    color: theme.color.textHi, fontSize: 12,
    marginTop: 2, textAlign: "center",
  },
  exCue: {
    marginTop: 8, backgroundColor: theme.color.bg,
    borderWidth: 1, borderColor: theme.color.border, borderRadius: 4,
    padding: 6, color: theme.color.textHi, fontSize: 11, minHeight: 32,
  },

  busyBar: {
    flexDirection: "row", alignItems: "center", gap: 8,
    padding: 10, backgroundColor: theme.color.surface2,
    borderRadius: 6, marginTop: 12,
  },
  busyText: { color: theme.color.textDim, fontSize: 12 },
});
