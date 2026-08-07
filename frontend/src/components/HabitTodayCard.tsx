/**
 * HabitTodayCard — client-facing "Today's Habits" row.
 *
 * Iter 151 (Dashboard refresh) — replaces the large card list with a
 * compact horizontal row of circles + icons. Tap to mark done; long-press
 * opens the "Skipped / Not possible + reason" sheet so the kind-tone
 * telemetry pipeline is preserved.
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

/**
 * Best-effort icon picker driven by habit_type / title keywords.
 * Falls back to a generic checkmark ring so the row never renders empty.
 */
function iconForHabit(h: Habit): keyof typeof Ionicons.glyphMap {
  const hay = `${(h.habit_type || "")} ${(h.title || "")}`.toLowerCase();
  if (/water|hydrat|drink/.test(hay)) return "water";
  if (/sleep|bed|rest/.test(hay))     return "moon";
  if (/step|walk/.test(hay))          return "footsteps";
  if (/protein|meal|food|nutri/.test(hay)) return "nutrition";
  if (/mobil|stretch/.test(hay))      return "body";
  if (/breath|calm|medit/.test(hay))  return "leaf";
  if (/sun|daylight|light/.test(hay)) return "sunny";
  if (/journal|reflect|note/.test(hay)) return "book";
  if (/read/.test(hay))               return "book";
  if (/screen|phone/.test(hay))       return "phone-portrait";
  if (/coffee|caffeine/.test(hay))    return "cafe";
  if (/vitamin|supplement/.test(hay)) return "medkit";
  if (/cold|ice|shower/.test(hay))    return "snow";
  if (/warm|heat|sauna/.test(hay))    return "flame";
  if (/weight|scale/.test(hay))       return "scale";
  return "checkmark";
}

/* -------------------------------------------------------------------------- */
export function HabitTodayCard() {
  const [loading, setLoading] = useState(true);
  const [habits, setHabits] = useState<Habit[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [reasonFor, setReasonFor] = useState<{ habit: Habit; status: "skipped" | "not_possible" } | null>(null);
  const [seedTried, setSeedTried] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<{ habits: Habit[] }>("/habits/today");
      const list = r.habits || [];
      if (list.length === 0 && !seedTried) {
        setSeedTried(true);
        try {
          await api("/habits/seed", { method: "POST" });
          const r2 = await api<{ habits: Habit[] }>("/habits/today");
          setHabits(r2.habits || []);
          return;
        } catch { /* seed is best-effort */ }
      }
      setHabits(list);
    } catch { /* silent — habits are optional on the home screen */ } finally { setLoading(false); }
  }, [seedTried]);

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

  const onLongPress = (habit: Habit) => {
    setReasonFor({ habit, status: "skipped" });
  };

  const onTap = (habit: Habit) => {
    // Toggle done → not_started.
    if (habit.today_log?.status === "done") {
      log(habit, "not_possible");
    } else {
      log(habit, "done");
    }
  };

  if (loading && !habits.length) return null;
  if (!habits.length) return null;

  const doneCount = habits.filter((h) => h.today_log?.status === "done").length;

  return (
    <View style={styles.wrap}>
      <View style={styles.headRow}>
        <View>
          <Text style={styles.head}>TODAY&apos;S HABITS</Text>
          <Text style={styles.sub}>Tap to mark done · long-press for options</Text>
        </View>
        <View style={styles.countPill}>
          <Text style={styles.countPillT}>{doneCount}/{habits.length}</Text>
        </View>
      </View>

      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.row}
      >
        {habits.map((h) => {
          const status = h.today_log?.status;
          const isDone = status === "done";
          const isSkipped = status === "skipped";
          const isNotPossible = status === "not_possible";
          const ring = isDone ? theme.color.green :
                       isSkipped ? theme.color.amber :
                       isNotPossible ? theme.color.textDim :
                       theme.color.brand;
          const fill = isDone ? theme.color.green :
                       isSkipped ? "#3A2B10" :
                       isNotPossible ? theme.color.surface2 :
                       theme.color.brandTint;
          const iconColor = isDone ? "#fff" :
                            isSkipped ? theme.color.amber :
                            isNotPossible ? theme.color.textDim :
                            theme.color.brand;
          const iconName: keyof typeof Ionicons.glyphMap =
            isSkipped ? "remove" :
            isNotPossible ? "airplane" :
            iconForHabit(h);

          return (
            <View key={h.id} style={styles.item}>
              <Pressable
                onPress={() => onTap(h)}
                onLongPress={() => onLongPress(h)}
                disabled={!!busyId}
                style={[styles.circle, { borderColor: ring, backgroundColor: fill }]}
                testID={`habit-${h.id}-circle`}
                accessibilityLabel={`Habit ${h.title}, ${status || "not logged"}`}
                accessibilityRole="button"
                hitSlop={6}
              >
                {busyId === h.id ? (
                  <ActivityIndicator color={iconColor} />
                ) : (
                  <Ionicons name={iconName} size={26} color={iconColor} />
                )}
                {isDone && (
                  <View style={styles.doneBadge}>
                    <Ionicons name="checkmark" size={11} color="#fff" />
                  </View>
                )}
                {typeof h.streak === "number" && h.streak > 0 && !isDone && (
                  <View style={styles.streakBadge}>
                    <Ionicons name="flame" size={9} color="#fff" />
                    <Text style={styles.streakBadgeT}>{h.streak}</Text>
                  </View>
                )}
              </Pressable>
              <Text style={styles.itemLabel} numberOfLines={2}>{h.title}</Text>
            </View>
          );
        })}
      </ScrollView>

      <Modal visible={!!reasonFor} transparent animationType="slide" onRequestClose={() => setReasonFor(null)}>
        <Pressable style={styles.modalBg} onPress={() => setReasonFor(null)}>
          <Pressable style={styles.sheet} onPress={(e) => e.stopPropagation()}>
            <View style={styles.sheetHandle} />
            <Text style={styles.sheetTitle}>
              {reasonFor?.habit.title}
            </Text>
            <Text style={styles.sheetSub}>
              Choose how today went — Atlas will use this to adapt around your roster.
            </Text>

            {/* Status toggle */}
            <View style={styles.statusRow}>
              <Pressable
                onPress={() => reasonFor && setReasonFor({ ...reasonFor, status: "skipped" })}
                style={[styles.statusChip, reasonFor?.status === "skipped" && { borderColor: theme.color.amber }]}
              >
                <Ionicons name="remove-circle" size={16} color={theme.color.amber} />
                <Text style={styles.statusChipT}>SKIPPED</Text>
              </Pressable>
              <Pressable
                onPress={() => reasonFor && setReasonFor({ ...reasonFor, status: "not_possible" })}
                style={[styles.statusChip, reasonFor?.status === "not_possible" && { borderColor: theme.color.textMuted }]}
              >
                <Ionicons name="airplane" size={16} color={theme.color.textMuted} />
                <Text style={styles.statusChipT}>NOT POSSIBLE</Text>
              </Pressable>
            </View>

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
                <Text style={styles.reasonSkipT}>JUST LOG IT</Text>
              </Pressable>
            </ScrollView>
          </Pressable>
        </Pressable>
      </Modal>
    </View>
  );
}

const CIRCLE = 60;
const styles = StyleSheet.create({
  wrap: {},
  headRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    marginBottom: 12,
  },
  head: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  sub: { color: theme.color.textMuted, fontSize: 12, marginTop: 3 },
  countPill: {
    paddingHorizontal: 10, paddingVertical: 4, borderRadius: 6,
    backgroundColor: theme.color.brandTint,
    borderWidth: 1, borderColor: theme.color.brand,
  },
  countPillT: { color: theme.color.brand, fontSize: 12, fontWeight: "900" },

  row: {
    gap: 14, paddingVertical: 4, paddingHorizontal: 2,
    alignItems: "flex-start",
  },
  item: {
    alignItems: "center", width: 72,
  },
  circle: {
    width: CIRCLE, height: CIRCLE, borderRadius: CIRCLE / 2,
    borderWidth: 2,
    alignItems: "center", justifyContent: "center",
    position: "relative",
  },
  doneBadge: {
    position: "absolute", top: -4, right: -4,
    width: 20, height: 20, borderRadius: 10,
    backgroundColor: theme.color.green,
    alignItems: "center", justifyContent: "center",
    borderWidth: 2, borderColor: theme.color.bg,
  },
  streakBadge: {
    position: "absolute", top: -4, right: -4,
    minWidth: 22, paddingHorizontal: 4, height: 18, borderRadius: 9,
    backgroundColor: theme.color.brand,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 2,
    borderWidth: 1.5, borderColor: theme.color.bg,
  },
  streakBadgeT: { color: "#fff", fontSize: 9, fontWeight: "900" },
  itemLabel: {
    color: theme.color.textMuted,
    fontSize: 11,
    marginTop: 8,
    textAlign: "center",
    lineHeight: 14,
  },

  // Modal
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  sheet: {
    backgroundColor: theme.color.surface,
    borderTopLeftRadius: 20, borderTopRightRadius: 20,
    padding: theme.space.lg, paddingBottom: theme.space.xl, maxHeight: "70%",
  },
  sheetHandle: {
    alignSelf: "center", width: 40, height: 4,
    backgroundColor: theme.color.borderStrong, borderRadius: 2, marginBottom: 12,
  },
  sheetTitle: { color: theme.color.text, fontSize: 16, fontWeight: "800" },
  sheetSub: { color: theme.color.textMuted, fontSize: 13, marginTop: 4, marginBottom: 12 },

  statusRow: { flexDirection: "row", gap: 8, marginBottom: 14 },
  statusChip: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    paddingVertical: 10, borderRadius: 8,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
  },
  statusChipT: { color: theme.color.text, fontSize: 11, fontWeight: "900", letterSpacing: 1 },

  reasonWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  reasonChip: {
    paddingHorizontal: 12, paddingVertical: 10, borderRadius: 8,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
  },
  reasonT: { color: theme.color.text, fontSize: 13, fontWeight: "700" },
  reasonSkipBtn: {
    marginTop: 16, padding: 14, borderRadius: 10, alignItems: "center",
    backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand,
  },
  reasonSkipT: { color: theme.color.brand, fontSize: 12, fontWeight: "900", letterSpacing: 1.5 },
});
