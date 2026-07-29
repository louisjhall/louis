/**
 * Reassessment micro-form — short, kind-specific questionnaire so a client
 * NEVER has to rerun the full DNA assessment because they missed a session
 * or uploaded a new roster.
 *
 * Route: /reassessment/[kind]
 * Kinds:
 *   - missed_workouts  → Quick check-in
 *   - life_change      → Quick update
 *   - roster_uploaded  → Quick availability check
 *   - event_completed  → Event debrief
 */
import { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, TextInput,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter, Stack } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Question = {
  id: string;
  text: string;
  type: "single_select" | "multi_select" | "long_text" | "short_text" | "range";
  options?: { id: string; label: string }[];
  meta?: { min?: number; max?: number; step?: number; left_label?: string; right_label?: string };
  optional?: boolean;
};

type Form = {
  kind: string;
  title: string;
  intro: string;
  duration_estimate: string;
  questions: Question[];
};

export default function ReassessmentMicro() {
  const { kind, prompt_id } = useLocalSearchParams<{ kind: string; prompt_id?: string }>();
  const router = useRouter();
  const [form, setForm] = useState<Form | null>(null);
  const [answers, setAnswers] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await api<Form>(`/reassessment/short-form?kind=${encodeURIComponent(String(kind))}`);
      setForm(r);
    } catch (e: any) {
      setError(e?.message || "Could not load form");
    } finally {
      setLoading(false);
    }
  }, [kind]);
  useEffect(() => { load(); }, [load]);

  const set = (qid: string, v: any) => setAnswers((prev) => ({ ...prev, [qid]: v }));

  const canSubmit = form?.questions.every((q) => q.optional || answers[q.id] !== undefined) ?? false;

  const submit = async () => {
    if (!form) return;
    setSubmitting(true);
    setError(null);
    try {
      const r = await api<any>("/reassessment/short-form", {
        method: "POST",
        body: {
          kind: form.kind,
          prompt_id: prompt_id || null,
          answers,
        },
      });
      setDone(r.message || "Thanks — Louis has been notified.");
    } catch (e: any) {
      setError(e?.message || "Could not submit. Try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <SafeAreaView style={styles.wrap} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12} style={styles.backBtn}>
          <Ionicons name="close" size={22} color={theme.color.text} />
        </Pressable>
        <Text style={styles.title}>{form?.title || "Quick Check-in"}</Text>
        <View style={{ width: 32 }} />
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>
      ) : error && !form ? (
        <View style={styles.center}>
          <Text style={styles.err}>{error}</Text>
          <Pressable onPress={load} style={styles.primaryBtn}><Text style={styles.primaryBtnT}>Retry</Text></Pressable>
        </View>
      ) : done ? (
        <View style={styles.center}>
          <Ionicons name="checkmark-circle" size={48} color={theme.color.green} />
          <Text style={styles.doneTitle}>Thanks — got it</Text>
          <Text style={styles.doneBody}>{done}</Text>
          <Pressable onPress={() => router.replace("/(client)/home" as any)} style={styles.primaryBtn}>
            <Text style={styles.primaryBtnT}>Back to home</Text>
          </Pressable>
        </View>
      ) : form ? (
        <>
          <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 100 }}>
            <View style={styles.introCard}>
              <Text style={styles.introTxt}>{form.intro}</Text>
              <Text style={styles.duration}>~{form.duration_estimate} · your answers go straight to Louis</Text>
            </View>

            {form.questions.map((q) => (
              <View key={q.id} style={styles.qBlock}>
                <Text style={styles.qText}>
                  {q.text}
                  {q.optional && <Text style={styles.optional}>  (optional)</Text>}
                </Text>

                {q.type === "single_select" && (q.options || []).map((o) => (
                  <Pressable
                    key={o.id}
                    onPress={() => set(q.id, o.id)}
                    style={[styles.optRow, answers[q.id] === o.id && styles.optRowSel]}
                  >
                    <Ionicons name={answers[q.id] === o.id ? "radio-button-on" : "radio-button-off"} size={20} color={theme.color.brand} />
                    <Text style={styles.optLabel}>{o.label}</Text>
                  </Pressable>
                ))}

                {q.type === "multi_select" && (q.options || []).map((o) => {
                  const cur = (answers[q.id] as string[]) || [];
                  const picked = cur.includes(o.id);
                  return (
                    <Pressable
                      key={o.id}
                      onPress={() => set(q.id, picked ? cur.filter((x) => x !== o.id) : [...cur, o.id])}
                      style={[styles.optRow, picked && styles.optRowSel]}
                    >
                      <Ionicons name={picked ? "checkbox" : "square-outline"} size={20} color={theme.color.brand} />
                      <Text style={styles.optLabel}>{o.label}</Text>
                    </Pressable>
                  );
                })}

                {q.type === "range" && (
                  <View style={styles.rangeWrap}>
                    <Text style={styles.rangeSide}>{q.meta?.left_label || String(q.meta?.min ?? 1)}</Text>
                    <View style={styles.rangeBtns}>
                      {Array.from({ length: ((q.meta?.max ?? 5) - (q.meta?.min ?? 1)) / (q.meta?.step ?? 1) + 1 }).map((_, idx) => {
                        const val = (q.meta?.min ?? 1) + idx * (q.meta?.step ?? 1);
                        const active = answers[q.id] === val;
                        return (
                          <Pressable
                            key={val}
                            onPress={() => set(q.id, val)}
                            style={[styles.rangeBtn, active && styles.rangeBtnSel]}
                          >
                            <Text style={[styles.rangeBtnT, active && { color: "#fff" }]}>{val}</Text>
                          </Pressable>
                        );
                      })}
                    </View>
                    <Text style={styles.rangeSide}>{q.meta?.right_label || String(q.meta?.max ?? 5)}</Text>
                  </View>
                )}

                {(q.type === "long_text" || q.type === "short_text") && (
                  <TextInput
                    value={(answers[q.id] as string) || ""}
                    onChangeText={(v) => set(q.id, v)}
                    style={[styles.input, q.type === "long_text" && { minHeight: 80, textAlignVertical: "top" }]}
                    multiline={q.type === "long_text"}
                    placeholder={q.type === "long_text" ? "Louis will read this personally" : "Type here"}
                    placeholderTextColor={theme.color.textMuted}
                  />
                )}
              </View>
            ))}

            {error && (
              <View style={styles.errCard}>
                <Ionicons name="alert-circle" size={16} color={theme.color.red} />
                <Text style={styles.errTxt}>{error}</Text>
              </View>
            )}
          </ScrollView>

          <View style={styles.footer}>
            <Pressable
              onPress={submit}
              disabled={!canSubmit || submitting}
              style={[styles.primaryBtn, (!canSubmit || submitting) && { opacity: 0.5 }]}
            >
              {submitting ? <ActivityIndicator color="#fff" /> : <Text style={styles.primaryBtnT}>Send to Louis</Text>}
            </Pressable>
          </View>
        </>
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: theme.color.bg },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 12, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: theme.color.line },
  backBtn: { width: 32, height: 32, alignItems: "center", justifyContent: "center" },
  title: { color: theme.color.text, fontSize: 16, fontWeight: "800", letterSpacing: 0.5 },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 32 },
  err: { color: theme.color.red, textAlign: "center", marginBottom: 16 },
  introCard: { backgroundColor: theme.color.cardBg, borderRadius: 10, padding: 14, borderWidth: 1, borderColor: theme.color.line, marginBottom: 12 },
  introTxt: { color: theme.color.text, fontSize: 14, lineHeight: 20 },
  duration: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 0.6, fontWeight: "700", marginTop: 8, textTransform: "uppercase" },
  qBlock: { marginBottom: 18 },
  qText: { color: theme.color.text, fontSize: 15, fontWeight: "700", marginBottom: 10 },
  optional: { color: theme.color.textMuted, fontSize: 12, fontWeight: "500" },
  optRow: { flexDirection: "row", alignItems: "center", gap: 10, padding: 12, borderRadius: 10, borderWidth: 1, borderColor: theme.color.line, backgroundColor: theme.color.cardBg, marginBottom: 6 },
  optRowSel: { borderColor: theme.color.brand, backgroundColor: theme.color.brand + "1a" },
  optLabel: { color: theme.color.text, fontSize: 14, flex: 1 },
  input: { backgroundColor: theme.color.cardBg, borderWidth: 1, borderColor: theme.color.line, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, color: theme.color.text, fontSize: 14 },
  rangeWrap: { flexDirection: "row", alignItems: "center", gap: 8, padding: 12, borderRadius: 10, borderWidth: 1, borderColor: theme.color.line, backgroundColor: theme.color.cardBg },
  rangeSide: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 0.6, fontWeight: "700", textTransform: "uppercase" },
  rangeBtns: { flex: 1, flexDirection: "row", justifyContent: "space-around" },
  rangeBtn: { minWidth: 34, height: 34, borderRadius: 17, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: theme.color.line },
  rangeBtnSel: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  rangeBtnT: { color: theme.color.text, fontWeight: "800" },
  footer: { padding: 16, borderTopWidth: 1, borderTopColor: theme.color.line, backgroundColor: theme.color.bg },
  primaryBtn: { backgroundColor: theme.color.brand, borderRadius: 10, paddingVertical: 14, alignItems: "center" },
  primaryBtnT: { color: "#fff", fontWeight: "800", letterSpacing: 0.5 },
  errCard: { flexDirection: "row", alignItems: "center", gap: 8, padding: 10, borderRadius: 8, backgroundColor: "#2a1010", marginTop: 8 },
  errTxt: { color: theme.color.red, flex: 1, fontSize: 12 },
  doneTitle: { color: theme.color.text, fontSize: 18, fontWeight: "800", marginTop: 12 },
  doneBody: { color: theme.color.textMuted, fontSize: 13, textAlign: "center", marginTop: 8, marginBottom: 24, lineHeight: 18 },
});
