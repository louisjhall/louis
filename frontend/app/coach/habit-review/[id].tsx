/**
 * Coach Habit Review — Louis approves/edits/rejects Atlas's habit recommendations.
 */
import { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput,
  ActivityIndicator, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Review = {
  id: string;
  user_name: string;
  week_start: string;
  week_end: string;
  atlas_summary: string;
  coach_summary?: string;
  completion_rate: number;
  what_worked?: string;
  what_did_not?: string;
  stats?: any[];
  recommendations: any[];
  new_habits: any[];
  coach_review_status: string;
  coach_review_required: boolean;
};

const RISK_STYLES: Record<string, string> = {
  high: "#c94a4a", medium: theme.color.amber, low: theme.color.green,
};

export default function HabitReviewApproval() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [review, setReview] = useState<Review | null>(null);
  const [coachNote, setCoachNote] = useState("");
  const [excluded, setExcluded] = useState<Set<number>>(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // The review isn't fetched via /habits/reviews/latest because we need per-review lookup;
      // use the coach's client habits endpoint which surfaces pending/latest reviews.
      // We derive client_id from the review payload — fetch via /coach/change-log meta pattern.
      // Simplest: request the client id through the coach tasks list and cross-reference id.
      const tasks = await api<any>("/coach/tasks");
      const t = (tasks.tasks || []).find((x: any) => x.payload?.habit_review_id === id);
      const clientId = t?.user_id;
      if (!clientId) { Alert.alert("Review not found"); router.back(); return; }
      const r = await api<any>(`/coach/clients/${clientId}/habits`);
      const found = r.pending_review?.id === id ? r.pending_review : (r.latest_review?.id === id ? r.latest_review : null);
      if (!found) { Alert.alert("Review not found"); router.back(); return; }
      setReview(found);
    } catch (e: any) {
      Alert.alert("Load failed", e?.message || "Try again");
    } finally { setLoading(false); }
  }, [id, router]);

  useEffect(() => { load(); }, [load]);

  const toggleExclude = (idx: number) => {
    setExcluded((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx); else next.add(idx);
      return next;
    });
  };

  const approve = async () => {
    if (!review) return;
    setBusy("approve");
    try {
      const filtered = (review.recommendations || []).filter((_, i) => !excluded.has(i));
      await api(`/coach/habits/reviews/${review.id}/approve`, {
        method: "POST",
        body: { coach_note: coachNote, modified_recommendations: filtered },
      });
      router.back();
    } catch (e: any) {
      Alert.alert("Approve failed", e?.message || "Try again");
    } finally { setBusy(null); }
  };

  const reject = async () => {
    if (!review) return;
    setBusy("reject");
    try {
      await api(`/coach/habits/reviews/${review.id}/reject`, {
        method: "POST", body: { coach_note: coachNote },
      });
      router.back();
    } catch (e: any) {
      Alert.alert("Reject failed", e?.message || "Try again");
    } finally { setBusy(null); }
  };

  if (loading || !review) {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: theme.color.surface }}>
        <ActivityIndicator color={theme.color.brand} />
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={8}>
          <Ionicons name="chevron-back" size={26} color={theme.color.text} />
        </Pressable>
        <Text style={styles.headerT}>HABIT REVIEW</Text>
        <View style={{ width: 26 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 160 }}>
        <Text style={styles.client}>{review.user_name}</Text>
        <Text style={styles.week}>{review.week_start} → {review.week_end}</Text>

        <View style={styles.summaryBlock}>
          <Text style={styles.summaryHead}>ATLAS SUMMARY</Text>
          <Text style={styles.summaryText}>{review.atlas_summary}</Text>
          <View style={{ height: 6 }} />
          <Text style={styles.completionT}>Weekly completion · {(review.completion_rate * 100).toFixed(0)}%</Text>
        </View>

        {review.what_worked ? (
          <View style={styles.wrapBlock}>
            <Text style={styles.blockHead}>WHAT WORKED</Text>
            <Text style={styles.blockText}>{review.what_worked}</Text>
          </View>
        ) : null}
        {review.what_did_not ? (
          <View style={styles.wrapBlock}>
            <Text style={styles.blockHead}>WHAT DIDN&apos;T</Text>
            <Text style={styles.blockText}>{review.what_did_not}</Text>
          </View>
        ) : null}

        {(review.recommendations || []).length > 0 ? (
          <>
            <Text style={styles.sect}>RECOMMENDATIONS · {review.recommendations.length}</Text>
            {review.recommendations.map((r: any, i: number) => {
              const ex = excluded.has(i);
              return (
                <Pressable
                  key={i}
                  onPress={() => toggleExclude(i)}
                  testID={`rec-${i}`}
                  style={[styles.recCard, ex && { opacity: 0.45 }]}
                >
                  <View style={{ flexDirection: "row", gap: 8, alignItems: "center", marginBottom: 6 }}>
                    <View style={[styles.riskDot, { backgroundColor: RISK_STYLES[r.risk_level] || theme.color.textDim }]} />
                    <Text style={styles.recAction}>{(r.action || "").toUpperCase().replace(/_/g, " ")}</Text>
                    <Text style={styles.recRisk}>{(r.risk_level || "low").toUpperCase()} RISK</Text>
                    <View style={{ flex: 1 }} />
                    <Ionicons name={ex ? "square-outline" : "checkbox"} size={20} color={ex ? theme.color.textDim : theme.color.brand} />
                  </View>
                  {r.change ? <Text style={styles.recChange}>{r.change}</Text> : null}
                  {r.reason ? <Text style={styles.recReason}>{r.reason}</Text> : null}
                  {r.new_title ? <Text style={styles.recField}>→ {r.new_title}</Text> : null}
                  {r.new_target !== undefined ? <Text style={styles.recField}>Target: {String(r.new_target)}</Text> : null}
                  {r.new_frequency ? <Text style={styles.recField}>Frequency: {r.new_frequency}</Text> : null}
                </Pressable>
              );
            })}
          </>
        ) : null}

        {(review.new_habits || []).length > 0 ? (
          <>
            <Text style={styles.sect}>NEW HABITS · {review.new_habits.length}</Text>
            {review.new_habits.map((h: any, i: number) => (
              <View key={i} style={styles.recCard}>
                <Text style={styles.recAction}>NEW HABIT</Text>
                <Text style={styles.recChange}>{h.title}</Text>
                {h.reason ? <Text style={styles.recReason}>{h.reason}</Text> : null}
              </View>
            ))}
          </>
        ) : null}

        <Text style={styles.sect}>COACH NOTE (OPTIONAL)</Text>
        <TextInput
          testID="coach-note"
          value={coachNote}
          onChangeText={setCoachNote}
          placeholder="Any note for the change log…"
          placeholderTextColor={theme.color.textDim}
          multiline
          style={styles.noteInput}
        />
      </ScrollView>

      <View style={styles.actionBar}>
        <Pressable testID="rev-reject" onPress={reject} disabled={!!busy} style={[styles.rejectBtn, busy && { opacity: 0.5 }]}>
          {busy === "reject" ? <ActivityIndicator color={theme.color.textMuted} /> : <Text style={styles.rejectT}>REJECT</Text>}
        </Pressable>
        <Pressable testID="rev-approve" onPress={approve} disabled={!!busy} style={[styles.approveBtn, busy && { opacity: 0.5 }]}>
          {busy === "approve" ? <ActivityIndicator color="#fff" /> : (
            <>
              <Ionicons name="checkmark" size={16} color="#fff" />
              <Text style={styles.approveT}>APPROVE ({(review.recommendations || []).length - excluded.size})</Text>
            </>
          )}
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  headerT: { color: theme.color.text, fontSize: 14, letterSpacing: 2, fontWeight: "900" },
  client: { color: theme.color.text, fontSize: 22, fontWeight: "900" },
  week: { color: theme.color.textMuted, marginTop: 4, fontSize: 12, letterSpacing: 1 },
  summaryBlock: { marginTop: 16, padding: 14, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand, borderRadius: 12 },
  summaryHead: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  summaryText: { color: theme.color.text, fontSize: 13, marginTop: 6, lineHeight: 18 },
  completionT: { color: theme.color.brand, fontSize: 12, fontWeight: "800", marginTop: 4 },
  wrapBlock: { marginTop: 14, padding: 12, backgroundColor: theme.color.surface2, borderRadius: 10, borderWidth: 1, borderColor: theme.color.border },
  blockHead: { color: theme.color.textDim, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  blockText: { color: theme.color.text, fontSize: 12, marginTop: 4, lineHeight: 17 },
  sect: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2, marginTop: 22, marginBottom: 8 },
  recCard: { padding: 12, backgroundColor: theme.color.surface2, borderRadius: 10, borderWidth: 1, borderColor: theme.color.border, marginBottom: 8 },
  riskDot: { width: 8, height: 8, borderRadius: 4 },
  recAction: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  recRisk: { color: theme.color.textDim, fontSize: 11, fontWeight: "800", letterSpacing: 1 },
  recChange: { color: theme.color.text, fontSize: 13, fontWeight: "700", marginTop: 4 },
  recReason: { color: theme.color.textMuted, fontSize: 11, marginTop: 4, lineHeight: 15 },
  recField: { color: theme.color.text, fontSize: 11, marginTop: 4 },
  noteInput: { minHeight: 80, backgroundColor: theme.color.surface2, borderRadius: 10, padding: 12, color: theme.color.text, borderWidth: 1, borderColor: theme.color.border, textAlignVertical: "top" },
  actionBar: { position: "absolute", left: 0, right: 0, bottom: 0, flexDirection: "row", gap: 10, padding: 14, backgroundColor: theme.color.surface, borderTopWidth: 1, borderTopColor: theme.color.divider },
  rejectBtn: { paddingHorizontal: 20, paddingVertical: 14, backgroundColor: theme.color.surface2, borderRadius: 10, borderWidth: 1, borderColor: theme.color.border },
  rejectT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "800", letterSpacing: 1.5 },
  approveBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingVertical: 14, backgroundColor: theme.color.brand, borderRadius: 10 },
  approveT: { color: "#fff", fontSize: 13, fontWeight: "900", letterSpacing: 1.5 },
});
