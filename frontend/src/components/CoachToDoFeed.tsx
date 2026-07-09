/**
 * CoachToDoFeed — surfaces the coach's action items on the overview dashboard.
 * Groups tasks by priority. Opens the review sheet for check-in tasks.
 */
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

export function CoachToDoFeed() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [tasks, setTasks] = useState<any[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<any>("/coach/tasks");
      setTasks(r.tasks || []);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const dismiss = async (id: string) => {
    try {
      await api<any>(`/coach/tasks/${id}`, { method: "PATCH", body: { status: "dismissed" } });
      load();
    } catch { /* ignore */ }
  };

  const open = (t: any) => {
    if (t.task_type === "check_in_review" || t.task_type === "record_weekly_video" || t.task_type === "injury_urgent") {
      if (t.check_in_id) router.push(`/coach/checkin/${t.check_in_id}` as any);
    }
  };

  if (loading) return null;
  if (!tasks.length) {
    return (
      <View style={styles.wrap}>
        <Text style={styles.head}>COACH TO-DO</Text>
        <View style={styles.emptyCard}>
          <Ionicons name="checkmark-circle" size={20} color={theme.color.green} />
          <Text style={styles.emptyT}>Inbox clear. Nothing needs your attention right now.</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.wrap}>
      <View style={styles.headRow}>
        <Text style={styles.head}>COACH TO-DO</Text>
        <View style={styles.countPill}><Text style={styles.countPillT}>{tasks.length}</Text></View>
      </View>
      <View style={{ gap: 8 }}>
        {tasks.slice(0, 8).map((t) => (
          <Pressable key={t.id} onPress={() => open(t)} style={styles.card} testID={`todo-${t.id}`}>
            <View style={[styles.pri, { backgroundColor: priorityColor(t.priority) }]} />
            <View style={{ flex: 1 }}>
              <View style={styles.rowTop}>
                <Text style={styles.taskType}>{prettyType(t.task_type)}</Text>
                {t.priority === "urgent" && <View style={styles.urgent}><Text style={styles.urgentT}>URGENT</Text></View>}
              </View>
              <Text style={styles.title} numberOfLines={2}>{t.title}</Text>
              {t.description && <Text style={styles.desc} numberOfLines={2}>{t.description}</Text>}
              <Text style={styles.meta}>{t.user_name} · {t.due_time_zone}</Text>
            </View>
            <Pressable onPress={(e) => { e.stopPropagation?.(); dismiss(t.id); }} hitSlop={8}>
              <Ionicons name="close" size={16} color={theme.color.textDim} />
            </Pressable>
          </Pressable>
        ))}
      </View>
    </View>
  );
}

function priorityColor(p: string): string {
  if (p === "urgent") return "#c94a4a";
  if (p === "high") return theme.color.brand;
  if (p === "low") return theme.color.textDim;
  return theme.color.amber;
}

function prettyType(t: string): string {
  return {
    check_in_review: "CHECK-IN REVIEW",
    record_weekly_video: "RECORD WEEKLY VIDEO",
    injury_urgent: "INJURY FLAG",
    missed_check_in: "MISSED CHECK-IN",
    programme_adjustment: "PROGRAMME REVIEW",
    coach_follow_up: "FOLLOW UP",
    roster_expired: "ROSTER EXPIRED",
  }[t] || t.toUpperCase().replace(/_/g, " ");
}

const styles = StyleSheet.create({
  wrap: { paddingHorizontal: 16, marginTop: 20 },
  headRow: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 12 },
  head: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  countPill: { paddingHorizontal: 10, paddingVertical: 3, borderRadius: 4, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand },
  countPillT: { color: theme.color.brand, fontSize: 10, fontWeight: "900" },
  emptyCard: { flexDirection: "row", alignItems: "center", gap: 10, padding: 14, borderRadius: 10, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  emptyT: { color: theme.color.textMuted, fontSize: 12 },
  card: { flexDirection: "row", gap: 10, padding: 12, borderRadius: 10, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, alignItems: "center" },
  pri: { width: 4, alignSelf: "stretch", borderRadius: 2 },
  rowTop: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 4 },
  taskType: { color: theme.color.brand, fontSize: 9, fontWeight: "900", letterSpacing: 1.5 },
  urgent: { backgroundColor: "#c94a4a", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 3 },
  urgentT: { color: "#fff", fontSize: 8, fontWeight: "900", letterSpacing: 1 },
  title: { color: theme.color.text, fontSize: 13, fontWeight: "800" },
  desc: { color: theme.color.textMuted, fontSize: 11, marginTop: 2, lineHeight: 15 },
  meta: { color: theme.color.textDim, fontSize: 10, marginTop: 4, letterSpacing: 1 },
});
