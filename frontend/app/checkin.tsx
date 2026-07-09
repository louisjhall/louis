/**
 * Sunday Weekly Check-in — Atlas-driven client flow.
 * Fetches dynamic questions from /checkins/questions, submits to /checkins/submit,
 * shows the Atlas summary + next-week focus + status of the coach's video.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator, Alert,
} from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Question = {
  id: string; label: string;
  type: "choice" | "scale" | "text";
  options?: string[]; min?: number; max?: number;
  show_if?: Record<string, string[]>;
};

export default function CheckinScreen() {
  const router = useRouter();
  const [core, setCore] = useState<Question[]>([]);
  const [dynamic, setDynamic] = useState<Question[]>([]);
  const [answers, setAnswers] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState<any>(null);

  const load = useCallback(async () => {
    try {
      const [q, cur] = await Promise.all([
        api<any>("/checkins/questions"),
        api<any>("/checkins/current"),
      ]);
      setCore(q.core || []);
      setDynamic(q.dynamic || []);
      if (cur?.check_in) setSubmitted(cur.check_in);
    } catch (e: any) {
      Alert.alert("Could not load check-in", e?.message || "");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const all = useMemo(() => [...core, ...dynamic], [core, dynamic]);

  const visible = (q: Question) => {
    if (!q.show_if) return true;
    for (const [k, allowed] of Object.entries(q.show_if)) {
      if (!allowed.includes(String(answers[k] || ""))) return false;
    }
    return true;
  };

  const setAnswer = (id: string, v: any) => setAnswers((a) => ({ ...a, [id]: v }));

  const canSubmit = useMemo(() => {
    const required = ["overall", "energy", "sleep", "stress", "recovery", "pain", "nutrition"];
    return required.every((k) => answers[k] !== undefined && answers[k] !== "");
  }, [answers]);

  const submit = async () => {
    if (!canSubmit || submitting) return;
    setSubmitting(true);
    try {
      let tz = "Europe/London";
      try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone || tz; } catch { /* ignore */ }
      const r = await api<any>("/checkins/submit", { method: "POST", body: { answers, submitted_time_zone: tz } });
      setSubmitted(r.check_in);
    } catch (e: any) {
      Alert.alert("Submit failed", e?.message || "Please try again.");
    } finally { setSubmitting(false); }
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
        <Pressable onPress={() => router.back()} hitSlop={12}><Ionicons name="close" size={26} color={theme.color.text} /></Pressable>
        <Text style={styles.headerT}>WEEKLY CHECK-IN</Text>
        <View style={{ width: 26 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: 20, paddingBottom: 40 }}>
        {submitted ? (
          <SubmittedView ci={submitted} onDone={() => router.replace("/(client)/home" as any)} />
        ) : (
          <>
            <View style={styles.introCard}>
              <Text style={styles.introEyebrow}>ATLAS</Text>
              <Text style={styles.introT}>
                Answer honestly. Louis reads every one of these before recording your weekly video.
              </Text>
              <Text style={styles.introHint}>
                Flying today? You can complete this after your sector or when you&apos;re back at the hotel.
                No rush if you&apos;re on duty — do this when it&apos;s safe and practical.
              </Text>
            </View>

            {all.filter(visible).map((q, i) => (
              <QuestionCard key={q.id} q={q} value={answers[q.id]} onChange={(v) => setAnswer(q.id, v)} index={i + 1} />
            ))}

            <Pressable
              onPress={submit}
              disabled={!canSubmit || submitting}
              style={[styles.submitBtn, (!canSubmit || submitting) && { opacity: 0.35 }]}
              testID="checkin-submit"
            >
              {submitting ? <ActivityIndicator color="#fff" /> : <Ionicons name="send" size={16} color="#fff" />}
              <Text style={styles.submitT}>{submitting ? "ATLAS IS REVIEWING…" : "SUBMIT CHECK-IN"}</Text>
            </Pressable>
            {!canSubmit && (
              <Text style={styles.requiredHint}>Answer overall, all 4 scales, pain and nutrition to submit.</Text>
            )}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function QuestionCard({ q, value, onChange, index }: { q: Question; value: any; onChange: (v: any) => void; index: number }) {
  return (
    <View style={styles.qCard}>
      <Text style={styles.qLbl}>{index}. {q.label}</Text>
      {q.type === "choice" && (
        <View style={styles.choiceRow}>
          {(q.options || []).map((opt) => (
            <Pressable key={opt} onPress={() => onChange(opt)} style={[styles.chip, value === opt && styles.chipOn]}>
              <Text style={[styles.chipT, value === opt && styles.chipTOn]}>{opt}</Text>
            </Pressable>
          ))}
        </View>
      )}
      {q.type === "scale" && (
        <View style={styles.scaleRow}>
          {Array.from({ length: (q.max || 5) - (q.min || 1) + 1 }, (_, i) => (q.min || 1) + i).map((n) => (
            <Pressable key={n} onPress={() => onChange(n)} style={[styles.scaleChip, value === n && styles.scaleChipOn]}>
              <Text style={[styles.scaleT, value === n && styles.scaleTOn]}>{n}</Text>
            </Pressable>
          ))}
        </View>
      )}
      {q.type === "text" && (
        <TextInput
          value={String(value || "")}
          onChangeText={onChange}
          placeholder="Type your answer..."
          placeholderTextColor={theme.color.textDim}
          multiline
          style={styles.textInput}
        />
      )}
    </View>
  );
}

function SubmittedView({ ci, onDone }: { ci: any; onDone: () => void }) {
  return (
    <View>
      <View style={styles.thanksCard}>
        <View style={styles.thanksIcon}><Ionicons name="checkmark-circle" size={44} color={theme.color.green} /></View>
        <Text style={styles.thanksT}>CHECK-IN COMPLETE</Text>
        <Text style={styles.thanksS}>Louis will review this and send your weekly video.</Text>
      </View>

      {ci.atlas_client_summary && (
        <View style={styles.summaryBlock}>
          <Text style={styles.blockEyebrow}>ATLAS SUMMARY</Text>
          <Text style={styles.blockBody}>{ci.atlas_client_summary}</Text>
        </View>
      )}
      {ci.next_week_focus && (
        <View style={styles.summaryBlock}>
          <Text style={styles.blockEyebrow}>NEXT WEEK FOCUS</Text>
          <Text style={styles.blockBody}>{ci.next_week_focus}</Text>
        </View>
      )}
      {ci.weekly_video_status === "sent" ? (
        <View style={[styles.summaryBlock, { backgroundColor: theme.color.brandTint, borderColor: theme.color.brand }]}>
          <Text style={styles.blockEyebrow}>VIDEO FROM LOUIS</Text>
          <Text style={styles.blockBody}>Your weekly coaching review is ready.</Text>
        </View>
      ) : (
        <View style={styles.summaryBlock}>
          <Text style={styles.blockEyebrow}>WEEKLY VIDEO</Text>
          <Text style={styles.blockBody}>Louis is preparing your personal video. You&apos;ll be notified when it&apos;s ready.</Text>
        </View>
      )}

      <Pressable onPress={onDone} style={styles.doneBtn}>
        <Text style={styles.doneT}>BACK TO HOME</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  centre: { flex: 1, alignItems: "center", justifyContent: "center" },
  topBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 16, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  headerT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  introCard: { padding: 16, marginBottom: 20, borderRadius: 12, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand },
  introEyebrow: { color: theme.color.brand, fontSize: 9, fontWeight: "900", letterSpacing: 2 },
  introT: { color: theme.color.text, fontSize: 14, fontWeight: "700", marginTop: 8, lineHeight: 19 },
  introHint: { color: theme.color.textMuted, fontSize: 11, marginTop: 10, lineHeight: 15, fontStyle: "italic" },
  qCard: { padding: 14, marginBottom: 12, borderRadius: 12, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  qLbl: { color: theme.color.text, fontSize: 14, fontWeight: "800", marginBottom: 10, lineHeight: 19 },
  choiceRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8, backgroundColor: theme.color.surface3, borderWidth: 1, borderColor: theme.color.border },
  chipOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipT: { color: theme.color.text, fontSize: 12, fontWeight: "700" },
  chipTOn: { color: "#fff" },
  scaleRow: { flexDirection: "row", gap: 8 },
  scaleChip: { flex: 1, paddingVertical: 10, borderRadius: 8, alignItems: "center", backgroundColor: theme.color.surface3, borderWidth: 1, borderColor: theme.color.border },
  scaleChipOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  scaleT: { color: theme.color.text, fontSize: 15, fontWeight: "900" },
  scaleTOn: { color: "#fff" },
  textInput: { minHeight: 60, backgroundColor: theme.color.surface3, borderWidth: 1, borderColor: theme.color.border, borderRadius: 8, padding: 10, color: theme.color.text, fontSize: 13, textAlignVertical: "top" },
  submitBtn: { marginTop: 16, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, padding: 16, borderRadius: 12, backgroundColor: theme.color.brand },
  submitT: { color: "#fff", fontSize: 13, fontWeight: "900", letterSpacing: 2 },
  requiredHint: { color: theme.color.textMuted, fontSize: 11, textAlign: "center", marginTop: 10, fontStyle: "italic" },
  thanksCard: { padding: 20, borderRadius: 14, alignItems: "center", backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  thanksIcon: { marginBottom: 10 },
  thanksT: { color: theme.color.text, fontSize: 16, fontWeight: "900", letterSpacing: 2 },
  thanksS: { color: theme.color.textMuted, fontSize: 12, marginTop: 8, textAlign: "center" },
  summaryBlock: { padding: 16, marginTop: 14, borderRadius: 12, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  blockEyebrow: { color: theme.color.brand, fontSize: 9, fontWeight: "900", letterSpacing: 2 },
  blockBody: { color: theme.color.text, fontSize: 13, lineHeight: 19, marginTop: 8 },
  doneBtn: { marginTop: 20, padding: 14, borderRadius: 12, backgroundColor: theme.color.brand, alignItems: "center" },
  doneT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 2 },
});
