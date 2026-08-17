/**
 * Coach — Check-in question editor (Iter181e).
 *
 * Lists the 10-question set the client will see, split into WEEKLY /
 * MONTHLY. Coach can:
 *   · toggle between weekly/monthly sets (both tracked independently)
 *   · delete any question
 *   · add a custom question (short label + type)
 *   · trigger a full LLM regeneration (discards edits for this week)
 *
 * PUT enforces the 10-item cap server-side.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput,
  ActivityIndicator, Alert,
} from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Q = {
  id: string;
  label: string;
  type: "scale" | "choice" | "text";
  min?: number; max?: number;
  options?: string[];
};

type Mode = "weekly" | "monthly";

export default function CoachCheckinQuestionsScreen() {
  const { clientId } = useLocalSearchParams<{ clientId: string }>();
  const router = useRouter();

  const [mode, setMode] = useState<Mode>("weekly");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [questions, setQuestions] = useState<Q[]>([]);
  const [meta, setMeta] = useState<any>(null);

  // Add-question form state.
  const [newLabel, setNewLabel] = useState("");
  const [newType, setNewType] = useState<Q["type"]>("text");
  const [newOptions, setNewOptions] = useState("");   // comma-separated

  const load = useCallback(async (m: Mode = mode) => {
    setLoading(true);
    try {
      const r = await api<any>(`/coach/checkins/questions/${clientId}?type=${m}`);
      const doc = r?.check_in_questions || {};
      setQuestions((doc.questions || []) as Q[]);
      setMeta(doc);
    } catch (e: any) {
      Alert.alert("Load failed", e?.message || "");
    } finally { setLoading(false); }
  }, [clientId, mode]);

  useEffect(() => { load(mode); }, [load, mode]);

  const persist = useCallback(async (next: Q[]) => {
    setSaving(true);
    try {
      const r = await api<any>(`/coach/checkins/questions/${clientId}`, {
        method: "PUT", body: { type: mode, questions: next },
      });
      const doc = r?.check_in_questions || {};
      setQuestions((doc.questions || []) as Q[]);
      setMeta(doc);
    } catch (e: any) {
      Alert.alert("Save failed", e?.message || "");
    } finally { setSaving(false); }
  }, [clientId, mode]);

  const removeAt = (idx: number) => {
    const next = questions.filter((_, i) => i !== idx);
    persist(next);
  };

  const addQuestion = () => {
    if (!newLabel.trim()) return;
    if (questions.length >= 10) {
      Alert.alert("Cap reached", "Maximum 10 questions per set. Delete one first.");
      return;
    }
    const id = newLabel.trim().toLowerCase()
      .replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40) || `q_${Date.now()}`;
    const q: Q = { id, label: newLabel.trim(), type: newType };
    if (newType === "scale") { q.min = 1; q.max = 5; }
    if (newType === "choice") {
      const opts = newOptions.split(",").map((s) => s.trim()).filter(Boolean).slice(0, 5);
      if (opts.length < 2) {
        Alert.alert("Options required", "Choice questions need at least 2 comma-separated options.");
        return;
      }
      q.options = opts;
    }
    const next = [...questions, q];
    setNewLabel(""); setNewOptions(""); setNewType("text");
    persist(next);
  };

  const regenerate = async () => {
    setRegenerating(true);
    try {
      const r = await api<any>(`/coach/checkins/questions/${clientId}/regenerate?type=${mode}`, {
        method: "POST",
      });
      const doc = r?.check_in_questions || {};
      setQuestions((doc.questions || []) as Q[]);
      setMeta(doc);
    } catch (e: any) {
      Alert.alert("Regenerate failed", e?.message || "");
    } finally { setRegenerating(false); }
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.root}>
        <View style={styles.centre}><ActivityIndicator color={theme.color.brand} /></View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <View style={styles.topBar}>
        <Pressable onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="chevron-back" size={24} color={theme.color.text} />
        </Pressable>
        <Text style={styles.header}>CHECK-IN QUESTIONS</Text>
        <View style={{ width: 24 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 40 }}>
        <View style={styles.tabs}>
          {(["weekly", "monthly"] as const).map((m) => (
            <Pressable
              key={m}
              onPress={() => setMode(m)}
              style={[styles.tab, mode === m && styles.tabOn]}
              testID={`ci-mode-${m}`}
            >
              <Text style={[styles.tabT, mode === m && styles.tabTOn]}>{m.toUpperCase()}</Text>
            </Pressable>
          ))}
        </View>

        <View style={styles.metaLine}>
          <Text style={styles.metaT}>
            {questions.length}/10 questions ·{" "}
            {meta?.coach_edited_at
              ? `edited by coach ${new Date(meta.coach_edited_at).toLocaleDateString()}`
              : "auto-generated by Atlas"}
          </Text>
        </View>

        {questions.map((q, i) => (
          <View key={`${q.id}-${i}`} style={styles.qCard}>
            <View style={styles.qHead}>
              <Text style={styles.qIdx}>{i + 1}</Text>
              <Text style={styles.qTypePill}>{q.type.toUpperCase()}</Text>
              <View style={{ flex: 1 }} />
              <Pressable onPress={() => removeAt(i)} hitSlop={10} testID={`ci-delete-${i}`}>
                <Ionicons name="trash" size={18} color="#c94a4a" />
              </Pressable>
            </View>
            <Text style={styles.qLbl}>{q.label}</Text>
            {q.type === "choice" && q.options ? (
              <Text style={styles.qMeta}>{q.options.join(" · ")}</Text>
            ) : null}
            {q.type === "scale" ? (
              <Text style={styles.qMeta}>{q.min ?? 1}–{q.max ?? 5}</Text>
            ) : null}
          </View>
        ))}

        {/* Add question form */}
        <View style={styles.addCard}>
          <Text style={styles.addH}>ADD QUESTION</Text>
          <TextInput
            value={newLabel}
            onChangeText={setNewLabel}
            placeholder="Question label (e.g. How did your long run feel?)"
            placeholderTextColor={theme.color.textDim}
            style={styles.input}
            testID="ci-new-label"
          />
          <View style={styles.tabs}>
            {(["scale", "choice", "text"] as const).map((t) => (
              <Pressable
                key={t}
                onPress={() => setNewType(t)}
                style={[styles.tab, newType === t && styles.tabOn]}
                testID={`ci-new-type-${t}`}
              >
                <Text style={[styles.tabT, newType === t && styles.tabTOn]}>{t.toUpperCase()}</Text>
              </Pressable>
            ))}
          </View>
          {newType === "choice" ? (
            <TextInput
              value={newOptions}
              onChangeText={setNewOptions}
              placeholder="Options, comma-separated (e.g. Yes, No, Maybe)"
              placeholderTextColor={theme.color.textDim}
              style={styles.input}
              testID="ci-new-options"
            />
          ) : null}
          <Pressable
            onPress={addQuestion}
            disabled={saving || !newLabel.trim() || questions.length >= 10}
            style={[styles.addBtn,
              (saving || !newLabel.trim() || questions.length >= 10) && { opacity: 0.4 }]}
            testID="ci-add"
          >
            <Ionicons name="add" size={16} color="#fff" />
            <Text style={styles.addBtnT}>ADD QUESTION</Text>
          </Pressable>
        </View>

        <Pressable
          onPress={regenerate}
          disabled={regenerating}
          style={[styles.regenBtn, regenerating && { opacity: 0.5 }]}
          testID="ci-regen"
        >
          {regenerating
            ? <ActivityIndicator color={theme.color.brand} size="small" />
            : <Ionicons name="refresh" size={14} color={theme.color.brand} />}
          <Text style={styles.regenBtnT}>REGENERATE FROM ATLAS (discards edits)</Text>
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root:   { flex: 1, backgroundColor: theme.color.bg },
  centre: { flex: 1, alignItems: "center", justifyContent: "center" },
  topBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between",
            paddingHorizontal: 16, paddingVertical: 12,
            borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: theme.color.border },
  header: { color: theme.color.text, fontSize: 14, fontWeight: "900", letterSpacing: 1.5 },
  tabs:   { flexDirection: "row", gap: 8, marginBottom: 12 },
  tab:    { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 6,
            backgroundColor: theme.color.cardAlt, borderWidth: 1, borderColor: theme.color.border },
  tabOn:  { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  tabT:   { color: theme.color.textDim, fontSize: 11, fontWeight: "900", letterSpacing: 1.2 },
  tabTOn: { color: "#fff" },
  metaLine: { paddingHorizontal: 4, marginBottom: 12 },
  metaT:  { color: theme.color.textDim, fontSize: 11, letterSpacing: 0.5 },
  qCard:  { backgroundColor: theme.color.card, borderRadius: 10, padding: 14, marginBottom: 10,
            borderWidth: 1, borderColor: theme.color.border },
  qHead:  { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 6 },
  qIdx:   { color: theme.color.brand, fontSize: 12, fontWeight: "900", width: 16 },
  qTypePill: { color: theme.color.textDim, fontSize: 10, fontWeight: "700", letterSpacing: 1,
               paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
               backgroundColor: theme.color.cardAlt },
  qLbl:   { color: theme.color.text, fontSize: 14, lineHeight: 19, fontWeight: "600" },
  qMeta:  { color: theme.color.textDim, fontSize: 11, marginTop: 4 },
  addCard: { backgroundColor: theme.color.card, borderRadius: 10, padding: 14,
             marginTop: 6, borderWidth: 1, borderColor: theme.color.border },
  addH:   { color: theme.color.text, fontSize: 11, fontWeight: "900", letterSpacing: 1.4, marginBottom: 10 },
  input:  { backgroundColor: theme.color.bg, color: theme.color.text, borderRadius: 8,
            paddingHorizontal: 12, paddingVertical: 10, fontSize: 14, marginBottom: 10,
            borderWidth: 1, borderColor: theme.color.border },
  addBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
            backgroundColor: theme.color.brand, borderRadius: 8, paddingVertical: 11,
            marginTop: 4 },
  addBtnT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 1.2 },
  regenBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
              paddingVertical: 12, marginTop: 20, borderRadius: 8,
              borderWidth: 1, borderColor: theme.color.brand },
  regenBtnT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.2 },
});
