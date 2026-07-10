/**
 * CoachToDoFeed — the coach's daily briefing.
 * Groups Atlas-generated tasks by category:
 *   URGENT SAFETY · MESSAGES · REVIEWS · VIDEOS · PROGRAMME · ROSTER · OTHER
 * Message-draft tasks route to the Draft Review screen for edit/approve/send.
 */
import React, { useCallback, useMemo, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Task = {
  id: string;
  task_type: string;
  category?: string;
  title: string;
  description?: string;
  priority: string;
  risk_level?: string;
  user_name?: string;
  due_time_zone?: string;
  check_in_id?: string | null;
  message_draft_id?: string | null;
  payload?: any;
};

const CATEGORY_ORDER = [
  { key: "urgent_safety", label: "URGENT SAFETY", color: "#c94a4a" },
  { key: "messages",      label: "MESSAGES",       color: theme.color.brand },
  { key: "reviews",       label: "CHECK-IN REVIEWS", color: theme.color.amber },
  { key: "videos",        label: "WEEKLY VIDEOS",  color: theme.color.brand },
  { key: "programme",     label: "PROGRAMME",      color: theme.color.brand },
  { key: "roster",        label: "ROSTER",         color: theme.color.amber },
  { key: "other",         label: "OTHER",          color: theme.color.textDim },
];

function categoryOf(t: Task): string {
  if (t.category) return t.category;
  if (t.task_type === "injury_urgent") return "urgent_safety";
  if (t.task_type === "message_draft_ready") return "messages";
  if (t.task_type === "check_in_review" || t.task_type === "missed_check_in") return "reviews";
  if (t.task_type === "record_weekly_video") return "videos";
  if (t.task_type === "programme_adjustment" || t.task_type === "habit_review" || t.task_type === "standby_key_affected") return "programme";
  if (t.task_type === "roster_expired") return "roster";
  return "other";
}

export function CoachToDoFeed() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [tasks, setTasks] = useState<Task[]>([]);

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

  const open = (t: Task) => {
    if (t.task_type === "message_draft_ready" && t.message_draft_id) {
      router.push(`/coach/draft/${t.message_draft_id}` as any);
      return;
    }
    if (t.task_type === "habit_review" && (t as any).payload?.habit_review_id) {
      router.push(`/coach/habit-review/${(t as any).payload.habit_review_id}` as any);
      return;
    }
    if (t.check_in_id) {
      router.push(`/coach/checkin/${t.check_in_id}` as any);
    }
  };

  const grouped = useMemo(() => {
    const map: Record<string, Task[]> = {};
    for (const t of tasks) {
      const cat = categoryOf(t);
      if (!map[cat]) map[cat] = [];
      map[cat].push(t);
    }
    // Sort within each group by priority
    const order: Record<string, number> = { urgent: 0, high: 1, normal: 2, low: 3 };
    for (const k of Object.keys(map)) {
      map[k].sort((a, b) => (order[a.priority] ?? 5) - (order[b.priority] ?? 5));
    }
    return map;
  }, [tasks]);

  if (loading && !tasks.length) {
    return (
      <View style={styles.wrap}>
        <Text style={styles.head}>COACH TO-DO</Text>
        <ActivityIndicator color={theme.color.brand} style={{ marginVertical: 20 }} />
      </View>
    );
  }
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
      <View style={{ gap: 18 }}>
        {CATEGORY_ORDER.filter((c) => (grouped[c.key] || []).length > 0).map((cat) => (
          <View key={cat.key}>
            <View style={styles.catHead}>
              <View style={[styles.catDot, { backgroundColor: cat.color }]} />
              <Text style={[styles.catLabel, { color: cat.color }]}>{cat.label}</Text>
              <Text style={styles.catCount}>{grouped[cat.key].length}</Text>
            </View>
            <View style={{ gap: 8 }}>
              {grouped[cat.key].map((t) => (
                <Pressable
                  key={t.id}
                  onPress={() => open(t)}
                  style={styles.card}
                  testID={`todo-${t.id}`}
                >
                  <View style={[styles.pri, { backgroundColor: priorityColor(t.priority, t.risk_level) }]} />
                  <View style={{ flex: 1 }}>
                    <View style={styles.rowTop}>
                      <Text style={styles.taskType}>{prettyType(t.task_type)}</Text>
                      {t.priority === "urgent" ? <View style={styles.urgent}><Text style={styles.urgentT}>URGENT</Text></View> : null}
                      {t.risk_level === "high" && t.priority !== "urgent" ? <View style={styles.riskHigh}><Text style={styles.riskHighT}>HIGH RISK</Text></View> : null}
                      {t.risk_level === "medium" ? <View style={styles.riskMed}><Text style={styles.riskMedT}>REVIEW</Text></View> : null}
                    </View>
                    <Text style={styles.title} numberOfLines={2}>{t.title}</Text>
                    {t.description ? <Text style={styles.desc} numberOfLines={2}>{t.description}</Text> : null}
                    <Text style={styles.meta}>{t.user_name}{t.due_time_zone ? ` · ${t.due_time_zone}` : ""}</Text>
                  </View>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                    {t.task_type === "message_draft_ready" ? (
                      <Ionicons name="chevron-forward" size={16} color={theme.color.brand} />
                    ) : null}
                    <Pressable onPress={(e) => { e.stopPropagation?.(); dismiss(t.id); }} hitSlop={8}>
                      <Ionicons name="close" size={16} color={theme.color.textDim} />
                    </Pressable>
                  </View>
                </Pressable>
              ))}
            </View>
          </View>
        ))}
      </View>
    </View>
  );
}

function priorityColor(p: string, risk?: string): string {
  if (risk === "high" || p === "urgent") return "#c94a4a";
  if (risk === "medium" || p === "high") return theme.color.amber;
  if (p === "low") return theme.color.textDim;
  return theme.color.brand;
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
    message_draft_ready: "MESSAGE DRAFT",
    habit_review: "HABIT REVIEW",
    standby_key_affected: "STANDBY · KEY SESSION",
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
  catHead: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 8 },
  catDot: { width: 6, height: 6, borderRadius: 3 },
  catLabel: { fontSize: 10, fontWeight: "900", letterSpacing: 2 },
  catCount: { color: theme.color.textDim, fontSize: 10, fontWeight: "800" },
  card: { flexDirection: "row", gap: 10, padding: 12, borderRadius: 10, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, alignItems: "center" },
  pri: { width: 4, alignSelf: "stretch", borderRadius: 2 },
  rowTop: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 4, flexWrap: "wrap" },
  taskType: { color: theme.color.brand, fontSize: 9, fontWeight: "900", letterSpacing: 1.5 },
  urgent: { backgroundColor: "#c94a4a", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 3 },
  urgentT: { color: "#fff", fontSize: 8, fontWeight: "900", letterSpacing: 1 },
  riskHigh: { backgroundColor: "#c94a4a", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 3 },
  riskHighT: { color: "#fff", fontSize: 8, fontWeight: "900", letterSpacing: 1 },
  riskMed: { backgroundColor: theme.color.amber, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 3 },
  riskMedT: { color: "#000", fontSize: 8, fontWeight: "900", letterSpacing: 1 },
  title: { color: theme.color.text, fontSize: 13, fontWeight: "800" },
  desc: { color: theme.color.textMuted, fontSize: 11, marginTop: 2, lineHeight: 15 },
  meta: { color: theme.color.textDim, fontSize: 10, marginTop: 4, letterSpacing: 1 },
});
