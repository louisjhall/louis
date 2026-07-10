/**
 * HabitTodayCard — client-facing "Today's Habits" card for the home screen.
 * Kind by design: skipped/not-possible never breaks streak, warm supportive language.
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ActivityIndicator, Modal, ScrollView, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Habit = {
  id: string;
  title: string;
  reason?: string;
  linked_goal?: string;
  habit_type: string;
  target?: string;
  unit?: string;
  streak?: number;
  today_log?: { status: string; reason?: string; note?: string };
};

const REASONS: { key: string; label: string }[] = [
  { key: "roster", label: "Roster" },
  { key: "fatigue", label: "Fatigue" },
  { key: "time", label: "No time" },
  { key: "family", label: "Family" },
  { key: "illness", label: "Illness" },
  { key: "forgot", label: "Forgot" },
  { key: "no_equipment", label: "No kit" },
  { key: "poor_sleep", label: "Poor sleep" },
  { key: "stress", label: "Stress" },
  { key: "not_relevant", label: "Not relevant" },
  { key: "other", label: "Other" },
];

export function HabitTodayCard() {
  const [loading, setLoading] = useState(true);
  const [habits, setHabits] = useState<Habit[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [reasonFor, setReasonFor] = useState<{ habit: Habit; status: "skipped" | "not_possible" } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<{ habits: Habit[] }>("/habits/today");
      setHabits(r.habits || []);
    } catch { /* silent — habits are optional on the home screen */ } finally { setLoading(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const log = async (habit: Habit, status: "done" | "skipped" | "not_possible", reason?: string) => {
    setBusyId(habit.id);
    try {
      const r = await api<any>(`/habits/${habit.id}/log`, {
        method: "POST", body: { status, reason },
      });
      setHabits((prev) => prev.map((h) => (h.id === habit.id ? { ...h, today_log: r.log, streak: r.streak } : h)));
    } catch (e: any) {
      Alert.alert("Couldn't save", e?.message || "Try again");
    } finally { setBusyId(null); setReasonFor(null); }
  };

  const onSkipOrNot = (habit: Habit, status: "skipped" | "not_possible") => {
    setReasonFor({ habit, status });
  };

  if (loading && !habits.length) return null;
  if (!habits.length) return null;

  return (
    <View style={styles.wrap}>
      <View style={styles.headRow}>
        <View>
          <Text style={styles.head}>TODAY&apos;S HABITS</Text>
          <Text style={styles.sub}>Small actions matched to your goal and roster.</Text>
        </View>
        <View style={styles.countPill}><Text style={styles.countPillT}>{habits.length}</Text></View>
      </View>
      <View style={{ gap: 10 }}>
        {habits.map((h) => {
          const status = h.today_log?.status;
          return (
            <View key={h.id} style={styles.card}>
              <View style={{ flexDirection: "row", alignItems: "flex-start", gap: 10 }}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.hTitle}>{h.title}</Text>
                  {h.reason ? <Text style={styles.hReason}>{h.reason}</Text> : null}
                  <View style={styles.metaRow}>
                    {h.linked_goal ? <Text style={styles.metaChip}>{h.linked_goal.toUpperCase().replace(/_/g, " ")}</Text> : null}
                    {typeof h.streak === "number" && h.streak > 0 ? (
                      <Text style={[styles.metaChip, { color: theme.color.brand }]}>🔥 {h.streak} day{h.streak === 1 ? "" : "s"}</Text>
                    ) : null}
                  </View>
                </View>
                {busyId === h.id ? <ActivityIndicator color={theme.color.brand} /> : (
                  status === "done" ? <Ionicons name="checkmark-circle" size={26} color={theme.color.green} /> :
                  status === "skipped" ? <Ionicons name="remove-circle" size={26} color={theme.color.amber} /> :
                  status === "not_possible" ? <Ionicons name="airplane" size={22} color={theme.color.textDim} /> :
                  null
                )}
              </View>
              <View style={styles.actionRow}>
                <Pressable
                  testID={`habit-${h.id}-done`}
                  onPress={() => log(h, "done")}
                  disabled={!!busyId}
                  style={[styles.doneBtn, status === "done" && styles.doneBtnActive]}
                >
                  <Ionicons name="checkmark" size={14} color={status === "done" ? "#000" : "#fff"} />
                  <Text style={[styles.doneT, status === "done" && { color: "#000" }]}>DONE</Text>
                </Pressable>
                <Pressable
                  testID={`habit-${h.id}-skip`}
                  onPress={() => onSkipOrNot(h, "skipped")}
                  disabled={!!busyId}
                  style={[styles.altBtn, status === "skipped" && { borderColor: theme.color.amber }]}
                >
                  <Text style={styles.altT}>SKIPPED</Text>
                </Pressable>
                <Pressable
                  testID={`habit-${h.id}-notpossible`}
                  onPress={() => onSkipOrNot(h, "not_possible")}
                  disabled={!!busyId}
                  style={[styles.altBtn, status === "not_possible" && { borderColor: theme.color.textMuted }]}
                >
                  <Text style={styles.altT}>NOT POSSIBLE</Text>
                </Pressable>
              </View>
              {status === "skipped" || status === "not_possible" ? (
                <Text style={styles.kindNote}>Logged. Atlas will use this to understand what works around your roster.</Text>
              ) : null}
            </View>
          );
        })}
      </View>

      <Modal visible={!!reasonFor} transparent animationType="slide" onRequestClose={() => setReasonFor(null)}>
        <Pressable style={styles.modalBg} onPress={() => setReasonFor(null)}>
          <Pressable style={styles.sheet} onPress={(e) => e.stopPropagation()}>
            <View style={styles.sheetHandle} />
            <Text style={styles.sheetTitle}>
              {reasonFor?.status === "skipped" ? "Anything to add?" : "What made it not possible?"}
            </Text>
            <Text style={styles.sheetSub}>Optional — this helps Atlas adapt your habits.</Text>
            <ScrollView contentContainerStyle={{ paddingBottom: 20 }}>
              <View style={styles.reasonWrap}>
                {REASONS.map((r) => (
                  <Pressable
                    key={r.key}
                    testID={`reason-${r.key}`}
                    onPress={() => reasonFor && log(reasonFor.habit, reasonFor.status, r.key)}
                    style={styles.reasonChip}
                  >
                    <Text style={styles.reasonT}>{r.label}</Text>
                  </Pressable>
                ))}
              </View>
              <Pressable
                testID="reason-skip"
                onPress={() => reasonFor && log(reasonFor.habit, reasonFor.status)}
                style={styles.reasonSkipBtn}
              >
                <Text style={styles.reasonSkipT}>SKIP · JUST LOG IT</Text>
              </Pressable>
            </ScrollView>
          </Pressable>
        </Pressable>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { marginTop: theme.space.md, marginBottom: theme.space.md },
  headRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 10 },
  head: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  sub: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },
  countPill: { paddingHorizontal: 10, paddingVertical: 3, borderRadius: 4, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand },
  countPillT: { color: theme.color.brand, fontSize: 10, fontWeight: "900" },
  card: { padding: 12, backgroundColor: theme.color.surface2, borderRadius: 12, borderWidth: 1, borderColor: theme.color.border },
  hTitle: { color: theme.color.text, fontSize: 14, fontWeight: "800" },
  hReason: { color: theme.color.textMuted, fontSize: 11, marginTop: 3, lineHeight: 15 },
  metaRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 8 },
  metaChip: { color: theme.color.textDim, fontSize: 9, fontWeight: "800", letterSpacing: 1 },
  actionRow: { flexDirection: "row", gap: 6, marginTop: 10 },
  doneBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 4, paddingVertical: 10, borderRadius: 8, backgroundColor: theme.color.brand },
  doneBtnActive: { backgroundColor: theme.color.green },
  doneT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  altBtn: { flex: 1, alignItems: "center", justifyContent: "center", paddingVertical: 10, borderRadius: 8, backgroundColor: theme.color.surface3, borderWidth: 1, borderColor: theme.color.border },
  altT: { color: theme.color.textMuted, fontSize: 10, fontWeight: "800", letterSpacing: 1 },
  kindNote: { color: theme.color.textDim, fontSize: 10, marginTop: 8, fontStyle: "italic" },
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  sheet: { backgroundColor: theme.color.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: theme.space.lg, paddingBottom: theme.space.xl, maxHeight: "70%" },
  sheetHandle: { alignSelf: "center", width: 40, height: 4, backgroundColor: theme.color.borderStrong, borderRadius: 2, marginBottom: 12 },
  sheetTitle: { color: theme.color.text, fontSize: 15, fontWeight: "800" },
  sheetSub: { color: theme.color.textMuted, fontSize: 12, marginTop: 4, marginBottom: 12 },
  reasonWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  reasonChip: { paddingHorizontal: 12, paddingVertical: 10, borderRadius: 8, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  reasonT: { color: theme.color.text, fontSize: 12, fontWeight: "700" },
  reasonSkipBtn: { marginTop: 16, padding: 14, borderRadius: 10, alignItems: "center", backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand },
  reasonSkipT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
});
