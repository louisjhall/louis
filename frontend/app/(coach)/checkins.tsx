/**
 * Coach — Sunday Check-ins section.
 * Filters + full history table backed by /coach/checkins.
 */
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

const FILTERS = [
  { key: null, label: "ALL" },
  { key: "needs_review", label: "NEEDS REVIEW" },
  { key: "video_needed", label: "VIDEO NEEDED" },
  { key: "video_sent", label: "VIDEO SENT" },
  { key: "injury", label: "INJURY FLAG" },
  { key: "low_recovery", label: "LOW RECOVERY" },
];

export default function CoachCheckinsScreen() {
  const router = useRouter();
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q = filter ? `?filter_type=${filter}` : "";
      const r = await api<any>(`/coach/checkins${q}`);
      setRows(r.check_ins || []);
    } catch { setRows([]); } finally { setLoading(false); }
  }, [filter]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12}><Ionicons name="chevron-back" size={24} color={theme.color.text} /></Pressable>
        <Text style={styles.title}>SUNDAY CHECK-INS</Text>
        <View style={{ width: 24 }} />
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.filters}>
        {FILTERS.map((f) => (
          <Pressable key={String(f.key)} onPress={() => setFilter(f.key)} style={[styles.chip, filter === f.key && styles.chipOn]}>
            <Text style={[styles.chipT, filter === f.key && styles.chipTOn]}>{f.label}</Text>
          </Pressable>
        ))}
      </ScrollView>

      {loading ? (
        <View style={styles.centre}><ActivityIndicator color={theme.color.brand} /></View>
      ) : rows.length === 0 ? (
        <View style={styles.centre}>
          <Ionicons name="checkmark-circle" size={30} color={theme.color.green} />
          <Text style={styles.emptyT}>Nothing matches this filter.</Text>
        </View>
      ) : (
        <ScrollView contentContainerStyle={{ padding: 16 }}>
          {rows.map((ci) => (
            <Pressable key={ci.id} onPress={() => router.push(`/coach/checkin/${ci.id}` as any)} style={styles.card}>
              <View style={styles.cardTop}>
                <Text style={styles.name}>{ci.user_name}</Text>
                <StatusPill status={ci.weekly_video_status} />
              </View>
              <Text style={styles.week}>{ci.week_start} → {ci.week_end}</Text>
              <View style={styles.tagRow}>
                {ci.urgent_safety_flag && <Tag t="URGENT" color="#c94a4a" />}
                {ci.injury_flag && <Tag t={`INJURY: ${ci.injury_flag.toUpperCase()}`} color="#c94a4a" />}
                {typeof ci.recovery_score === "number" && ci.recovery_score <= 2 && <Tag t="LOW RECOVERY" color={theme.color.amber} />}
                {ci.coach_review_required && !ci.reviewed_at && <Tag t="REVIEW" color={theme.color.brand} />}
                {ci.submitted_time_zone && <Tag t={ci.submitted_time_zone} color={theme.color.textMuted} />}
              </View>
              {ci.atlas_coach_summary?.suggested_focus_next_week && (
                <Text style={styles.focus} numberOfLines={2}>
                  {ci.atlas_coach_summary.suggested_focus_next_week}
                </Text>
              )}
            </Pressable>
          ))}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

function StatusPill({ status }: { status: string }) {
  const map: Record<string, { l: string; c: string }> = {
    sent: { l: "SENT", c: theme.color.green },
    recorded: { l: "READY TO SEND", c: theme.color.brand },
    draft: { l: "DRAFT", c: theme.color.amber },
    script_ready: { l: "SCRIPT READY", c: theme.color.textMuted },
  };
  const m = map[status] || { l: status?.toUpperCase() || "PENDING", c: theme.color.textMuted };
  return (<View style={[styles.pill, { borderColor: m.c }]}><Text style={[styles.pillT, { color: m.c }]}>{m.l}</Text></View>);
}
function Tag({ t, color }: { t: string; color: string }) {
  return (<View style={[styles.tag, { borderColor: color }]}><Text style={[styles.tagT, { color }]}>{t}</Text></View>);
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 16, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  title: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  filters: { padding: 12, gap: 8 },
  chip: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 8, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  chipOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipT: { color: theme.color.text, fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },
  chipTOn: { color: "#fff" },
  centre: { flex: 1, alignItems: "center", justifyContent: "center", gap: 10 },
  emptyT: { color: theme.color.textMuted, fontSize: 12 },
  card: { padding: 14, marginBottom: 10, borderRadius: 12, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  cardTop: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  name: { color: theme.color.text, fontSize: 15, fontWeight: "900" },
  week: { color: theme.color.textMuted, fontSize: 10, marginTop: 3, letterSpacing: 1 },
  tagRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 10 },
  tag: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 4, borderWidth: 1 },
  tagT: { fontSize: 8, fontWeight: "900", letterSpacing: 1 },
  pill: { paddingHorizontal: 10, paddingVertical: 3, borderRadius: 12, borderWidth: 1 },
  pillT: { fontSize: 9, fontWeight: "900", letterSpacing: 1.2 },
  focus: { color: theme.color.text, fontSize: 12, marginTop: 10, lineHeight: 17, fontStyle: "italic" },
});
