/**
 * Reusable premium-dark edit modals for the Exercise Content Library.
 *
 *   • EditListModal      — edit an ordered string[] (coaching points, mistakes, alternatives).
 *   • EditTextModal      — edit a single text field (video URL, instructions, notes).
 *   • CreateExerciseModal — new exercise form.
 */
import React, { useEffect, useState } from "react";
import {
  ActivityIndicator, KeyboardAvoidingView, Modal, Platform, Pressable,
  ScrollView, StyleSheet, Text, TextInput, View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";

/* -------------------------------------------------------------------------- */
/* Shared shell                                                                */
/* -------------------------------------------------------------------------- */

function ModalShell({
  visible, title, onClose, children, saving, onSave, saveLabel = "SAVE",
  scroll = true,
}: {
  visible: boolean; title: string; onClose: () => void; children: React.ReactNode;
  saving?: boolean; onSave?: () => void; saveLabel?: string; scroll?: boolean;
}) {
  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <KeyboardAvoidingView
        style={s.backdrop}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <View style={s.sheet}>
          <View style={s.head}>
            <Text style={s.headT}>{title}</Text>
            <Pressable onPress={onClose} hitSlop={12}>
              <Ionicons name="close" size={22} color={theme.color.textMuted} />
            </Pressable>
          </View>
          {scroll ? (
            <ScrollView contentContainerStyle={{ padding: 14, paddingBottom: 24 }} keyboardShouldPersistTaps="handled">
              {children}
            </ScrollView>
          ) : (
            <View style={{ padding: 14 }}>{children}</View>
          )}
          {onSave ? (
            <View style={s.footer}>
              <Pressable onPress={onClose} style={[s.btn, s.btnGhost]}>
                <Text style={s.btnGhostT}>CANCEL</Text>
              </Pressable>
              <Pressable onPress={onSave} disabled={saving} style={[s.btn, s.btnPri, saving && { opacity: 0.5 }]}>
                {saving ? <ActivityIndicator color="#fff" /> : <Text style={s.btnPriT}>{saveLabel}</Text>}
              </Pressable>
            </View>
          ) : null}
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

/* -------------------------------------------------------------------------- */
/* EditListModal                                                              */
/* -------------------------------------------------------------------------- */

export function EditListModal({
  visible, title, items, placeholder, onSave, onClose,
}: {
  visible: boolean; title: string; items: string[]; placeholder?: string;
  onSave: (next: string[]) => Promise<void> | void; onClose: () => void;
}) {
  const [rows, setRows] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => { if (visible) setRows(items?.length ? [...items] : [""]); }, [visible, items]);

  const update = (i: number, v: string) => setRows((r) => r.map((x, idx) => (idx === i ? v : x)));
  const remove = (i: number) => setRows((r) => (r.length <= 1 ? [""] : r.filter((_, idx) => idx !== i)));
  const add = () => setRows((r) => [...r, ""]);
  const move = (i: number, dir: -1 | 1) => setRows((r) => {
    const n = [...r]; const j = i + dir;
    if (j < 0 || j >= n.length) return n;
    [n[i], n[j]] = [n[j], n[i]]; return n;
  });

  const doSave = async () => {
    const clean = rows.map((x) => x.trim()).filter(Boolean);
    setSaving(true);
    try { await onSave(clean); onClose(); } finally { setSaving(false); }
  };

  return (
    <ModalShell visible={visible} title={title} onClose={onClose} saving={saving} onSave={doSave}>
      {rows.map((row, i) => (
        <View key={i} style={s.rowWrap}>
          <View style={s.rowNum}>
            <Text style={s.rowNumT}>{i + 1}</Text>
          </View>
          <TextInput
            style={s.rowInput}
            value={row}
            onChangeText={(v) => update(i, v)}
            placeholder={placeholder || "Add a coaching point…"}
            placeholderTextColor={theme.color.textDim}
            multiline
          />
          <View style={s.rowActs}>
            <Pressable onPress={() => move(i, -1)} disabled={i === 0} hitSlop={8}
              style={[s.iconBtn, i === 0 && { opacity: 0.3 }]}>
              <Ionicons name="chevron-up" size={14} color={theme.color.textMuted} />
            </Pressable>
            <Pressable onPress={() => move(i, 1)} disabled={i === rows.length - 1} hitSlop={8}
              style={[s.iconBtn, i === rows.length - 1 && { opacity: 0.3 }]}>
              <Ionicons name="chevron-down" size={14} color={theme.color.textMuted} />
            </Pressable>
            <Pressable onPress={() => remove(i)} hitSlop={8} style={s.iconBtn}>
              <Ionicons name="trash-outline" size={14} color="#c94a4a" />
            </Pressable>
          </View>
        </View>
      ))}
      <Pressable onPress={add} style={s.addBtn}>
        <Ionicons name="add" size={16} color={theme.color.brand} />
        <Text style={s.addT}>ADD ITEM</Text>
      </Pressable>
    </ModalShell>
  );
}

/* -------------------------------------------------------------------------- */
/* EditTextModal                                                              */
/* -------------------------------------------------------------------------- */

export function EditTextModal({
  visible, title, value, placeholder, multiline = true, onSave, onClose,
}: {
  visible: boolean; title: string; value?: string | null; placeholder?: string;
  multiline?: boolean;
  onSave: (next: string) => Promise<void> | void; onClose: () => void;
}) {
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (visible) setText(value || ""); }, [visible, value]);

  const doSave = async () => {
    setSaving(true);
    try { await onSave(text.trim()); onClose(); } finally { setSaving(false); }
  };

  return (
    <ModalShell visible={visible} title={title} onClose={onClose} saving={saving} onSave={doSave} scroll={false}>
      <TextInput
        style={[s.textArea, multiline && { minHeight: 140 }]}
        value={text}
        onChangeText={setText}
        placeholder={placeholder}
        placeholderTextColor={theme.color.textDim}
        multiline={multiline}
        autoFocus
        autoCapitalize="none"
        autoCorrect={multiline}
      />
    </ModalShell>
  );
}

/* -------------------------------------------------------------------------- */
/* CreateExerciseModal                                                        */
/* -------------------------------------------------------------------------- */

const CATEGORY_OPTS = ["strength", "mobility", "cardio", "rehab", "warmup", "cooldown"];
const TRAINING_TYPES = ["warmup", "strength", "cardio", "mobility", "cooldown", "rehab"];
const BODY_AREAS = ["upper", "lower", "core", "full-body", "shoulders", "back", "chest", "arms", "legs", "glutes", "hips"];

export function CreateExerciseModal({
  visible, onCreate, onClose,
}: {
  visible: boolean;
  onCreate: (body: {
    exercise_name: string; category?: string; training_type?: string;
    body_area?: string; equipment_type?: string[]; coaching_points?: string[];
  }) => Promise<void> | void;
  onClose: () => void;
}) {
  const [name, setName] = useState("");
  const [category, setCategory] = useState<string>("");
  const [tType, setTType] = useState<string>("");
  const [bodyArea, setBodyArea] = useState<string>("");
  const [equipment, setEquipment] = useState<string>("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (visible) { setName(""); setCategory(""); setTType(""); setBodyArea(""); setEquipment(""); }
  }, [visible]);

  const doSave = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      await onCreate({
        exercise_name: name.trim(),
        category: category || undefined,
        training_type: tType || undefined,
        body_area: bodyArea || undefined,
        equipment_type: equipment
          ? equipment.split(",").map((x) => x.trim()).filter(Boolean)
          : undefined,
      });
      onClose();
    } finally { setSaving(false); }
  };

  return (
    <ModalShell visible={visible} title="NEW EXERCISE" onClose={onClose}
      saving={saving} onSave={doSave} saveLabel="CREATE">
      <Text style={s.label}>NAME *</Text>
      <TextInput style={s.input} value={name} onChangeText={setName}
        placeholder="e.g. Kettlebell Turkish Get-Up" placeholderTextColor={theme.color.textDim} autoFocus />

      <Text style={s.label}>CATEGORY</Text>
      <Chips values={CATEGORY_OPTS} selected={category} onSelect={setCategory} />

      <Text style={s.label}>TRAINING TYPE</Text>
      <Chips values={TRAINING_TYPES} selected={tType} onSelect={setTType} />

      <Text style={s.label}>BODY AREA</Text>
      <Chips values={BODY_AREAS} selected={bodyArea} onSelect={setBodyArea} />

      <Text style={s.label}>EQUIPMENT (comma-separated)</Text>
      <TextInput style={s.input} value={equipment} onChangeText={setEquipment}
        placeholder="kettlebell, mat" placeholderTextColor={theme.color.textDim} autoCapitalize="none" />
    </ModalShell>
  );
}

function Chips({ values, selected, onSelect }: { values: string[]; selected: string; onSelect: (v: string) => void; }) {
  return (
    <View style={s.chipsRow}>
      {values.map((v) => {
        const on = selected === v;
        return (
          <Pressable key={v} onPress={() => onSelect(on ? "" : v)}
            style={[s.chip, on && s.chipOn]}>
            <Text style={[s.chipT, on && s.chipTOn]}>{v.toUpperCase()}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/* ChangeLogModal                                                             */
/* -------------------------------------------------------------------------- */

export function ChangeLogModal({
  visible, log, onClose, loading,
}: {
  visible: boolean; loading: boolean;
  log: Array<{ id: string; kind: string; detail?: string; created_at: string; actor_id?: string }>;
  onClose: () => void;
}) {
  return (
    <ModalShell visible={visible} title="CHANGE LOG" onClose={onClose}>
      {loading ? (
        <ActivityIndicator color={theme.color.brand} style={{ marginTop: 30 }} />
      ) : !log.length ? (
        <Text style={s.empty}>No entries yet.</Text>
      ) : (
        log.map((row) => (
          <View key={row.id} style={s.logRow}>
            <View style={s.logDot} />
            <View style={{ flex: 1 }}>
              <Text style={s.logKind}>{row.kind.replace(/_/g, " ").toUpperCase()}</Text>
              {row.detail ? <Text style={s.logDetail}>{row.detail}</Text> : null}
              <Text style={s.logTime}>{new Date(row.created_at).toLocaleString()}</Text>
            </View>
          </View>
        ))
      )}
    </ModalShell>
  );
}

/* -------------------------------------------------------------------------- */
/* Styles                                                                     */
/* -------------------------------------------------------------------------- */

const s = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.7)", justifyContent: "flex-end" },
  sheet: { backgroundColor: theme.color.surface2, borderTopLeftRadius: 16, borderTopRightRadius: 16, maxHeight: "88%" },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 14, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  headT: { color: theme.color.text, fontSize: 13, fontWeight: "900", letterSpacing: 2, fontFamily: theme.font.display },

  footer: { flexDirection: "row", gap: 8, padding: 14, borderTopWidth: 1, borderTopColor: theme.color.divider },
  btn: { flex: 1, paddingVertical: 12, borderRadius: 8, alignItems: "center", justifyContent: "center" },
  btnGhost: { backgroundColor: theme.color.surface3, borderWidth: 1, borderColor: theme.color.border },
  btnGhostT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  btnPri: { backgroundColor: theme.color.brand },
  btnPriT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },

  rowWrap: { flexDirection: "row", alignItems: "flex-start", gap: 6, marginBottom: 10 },
  rowNum: { width: 22, height: 22, borderRadius: 11, backgroundColor: theme.color.brandTint, alignItems: "center", justifyContent: "center", marginTop: 6 },
  rowNumT: { color: theme.color.brand, fontSize: 11, fontWeight: "900" },
  rowInput: { flex: 1, minHeight: 40, color: theme.color.text, backgroundColor: theme.color.surface3, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 8, fontSize: 13, textAlignVertical: "top", borderWidth: 1, borderColor: theme.color.border },
  rowActs: { flexDirection: "column", gap: 4, marginTop: 4 },
  iconBtn: { width: 28, height: 22, alignItems: "center", justifyContent: "center", borderRadius: 6, backgroundColor: theme.color.surface3, borderWidth: 1, borderColor: theme.color.border },
  addBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, marginTop: 10, paddingVertical: 12, borderRadius: 8, borderWidth: 1, borderStyle: "dashed", borderColor: theme.color.brand, backgroundColor: theme.color.brandTint },
  addT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1 },

  textArea: { color: theme.color.text, backgroundColor: theme.color.surface3, borderRadius: 8, padding: 10, fontSize: 13, textAlignVertical: "top", borderWidth: 1, borderColor: theme.color.border, minHeight: 44 },

  label: { color: theme.color.brand, fontSize: 11, letterSpacing: 2, fontWeight: "900", fontFamily: theme.font.textSemi, marginTop: 10, marginBottom: 6 },
  input: { color: theme.color.text, backgroundColor: theme.color.surface3, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 10, fontSize: 13, borderWidth: 1, borderColor: theme.color.border },
  chipsRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: { paddingHorizontal: 10, paddingVertical: 7, borderRadius: 20, backgroundColor: theme.color.surface3, borderWidth: 1, borderColor: theme.color.border },
  chipOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1 },
  chipTOn: { color: "#fff" },

  empty: { color: theme.color.textDim, textAlign: "center", marginTop: 30, fontStyle: "italic" },
  logRow: { flexDirection: "row", gap: 10, paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: theme.color.divider },
  logDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: theme.color.brand, marginTop: 6 },
  logKind: { color: theme.color.text, fontSize: 11, fontWeight: "900", letterSpacing: 1 },
  logDetail: { color: theme.color.textMuted, fontSize: 12, marginTop: 2, fontFamily: theme.font.text },
  logTime: { color: theme.color.textDim, fontSize: 11, marginTop: 4 },
});
