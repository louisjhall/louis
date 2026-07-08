import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl } from "react-native";
import { useLocalSearchParams, useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme, loadColor } from "@/src/lib/theme";
import { StatusBadge, deriveStatus } from "@/src/components/StatusBadge";

export default function ClientDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try { setData(await api<any>(`/coach/clients/${id}`)); } finally { setLoading(false); }
  }, [id]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (loading || !data) {
    return <View style={{ flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: theme.color.surface }}><ActivityIndicator color={theme.color.brand} /></View>;
  }

  const { client, roster, workouts, checkins, overrides = [], change_log: changeLog = [] } = data;
  const p = client.profile || {};

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()}><Ionicons name="chevron-back" size={26} color={theme.color.text} /></Pressable>
        <Text style={styles.headerT}>CLIENT</Text>
        <View style={{ width: 26 }} />
      </View>
      <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 60 }} refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}>
        <Text style={styles.name}>{client.name}</Text>
        <Text style={styles.email}>{client.email}</Text>

        <View style={styles.actionRow}>
          <Pressable testID="cd-script-btn" onPress={() => router.push(`/coach/scripts/${client.id}`)} style={styles.actionBtn}>
            <Ionicons name="videocam" size={16} color="#fff" />
            <Text style={styles.actionText}>WEEKLY SCRIPT</Text>
          </Pressable>
        </View>

        <View style={styles.card}>
          <Text style={styles.sect}>PROFILE</Text>
          <Row label="Airline" value={p.airline || "—"} />
          <Row label="Position" value={p.position || "—"} />
          <Row label="Level" value={p.experience_level || "—"} />
          <Row label="Days/week" value={String(p.training_days_per_week || "—")} />
          <Row label="Weight" value={p.weight_kg ? `${p.weight_kg}kg` : "—"} />
          <Row label="Calorie target" value={String(p.calorie_target || "—")} />
        </View>

        {roster ? (
          <View style={styles.card}>
            <Text style={styles.sect}>ROSTER · {roster.week_start}</Text>
            {roster.days?.map((d: any, i: number) => (
              <View key={i} style={styles.dayRow}>
                <View style={[styles.bar, { backgroundColor: loadColor(d.load) }]} />
                <Text style={styles.dText}>{d.date} · {d.type?.toUpperCase()}</Text>
                {d.flights?.[0] && <Text style={styles.fText}>  {d.flights[0].from}→{d.flights[0].to}</Text>}
              </View>
            ))}
          </View>
        ) : (
          <View style={styles.card}><Text style={{ color: theme.color.textMuted }}>No roster uploaded.</Text></View>
        )}

        <View style={styles.card}>
          <Text style={styles.sect}>WEEK PLAN · {workouts.length} WORKOUTS</Text>
          {workouts.length === 0 ? <Text style={{ color: theme.color.textMuted, marginTop: 6 }}>No workouts yet.</Text> :
            workouts.map((w: any) => (
              <Pressable key={w.id} testID={`cd-workout-${w.id}`} onPress={() => router.push(`/workout/${w.id}`)} style={styles.wRow}>
                <View style={[styles.bar, { backgroundColor: loadColor(w.day_load) }]} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.wTitle}>{w.title}</Text>
                  <Text style={styles.wMeta}>{w.date} · {w.exercises?.length || 0} ex</Text>
                </View>
                {w.approved && <Text style={styles.approved}>✓</Text>}
                {!w.approved && <StatusBadge status={deriveStatus(w)} />}
              </Pressable>
            ))
          }
        </View>

        {overrides.length > 0 && (
          <View style={styles.card}>
            <Text style={styles.sect}>CLIENT DAY EDITS · {overrides.length}</Text>
            {overrides.slice(0, 12).map((o: any, idx: number) => {
              const tagsList: string[] = o.tags || [];
              const topTag = tagsList[0] || o.day_type || o.training_preference || "edit";
              return (
                <View key={o.id || `${o.date}-${idx}`} style={styles.ovRow}>
                  <View style={styles.ovLeft}>
                    <Ionicons name="create" size={14} color={theme.color.amber} />
                    <Text style={styles.ovDate}>{o.date}</Text>
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.ovTags} numberOfLines={1}>
                      {tagsList.length
                        ? tagsList.map((t: string) => t.replace(/_/g, " ").toUpperCase()).join(" · ")
                        : String(topTag).replace(/_/g, " ").toUpperCase()}
                    </Text>
                    {o.notes ? (
                      <Text style={styles.ovNotes} numberOfLines={2}>
                        {`"${o.notes}"`}
                      </Text>
                    ) : null}
                  </View>
                </View>
              );
            })}
            {overrides.length > 12 && (
              <Text style={styles.ovMore}>+{overrides.length - 12} more</Text>
            )}
          </View>
        )}

        {checkins.length > 0 && (
          <View style={styles.card}>
            <Text style={styles.sect}>LATEST CHECK-IN</Text>
            <Row label="Energy" value={String(checkins[0].energy)} />
            <Row label="Sleep" value={String(checkins[0].sleep)} />
            <Row label="Soreness" value={String(checkins[0].soreness)} />
            <Row label="Stress" value={String(checkins[0].stress)} />
            {checkins[0].weight_kg && <Row label="Weight" value={`${checkins[0].weight_kg}kg`} />}
            {checkins[0].notes && <Text style={{ color: theme.color.textMuted, marginTop: 8, fontStyle: "italic" }}>{`"${checkins[0].notes}"`}</Text>}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const Row = ({ label, value }: any) => (
  <View style={styles.row}><Text style={styles.rowL}>{label}</Text><Text style={styles.rowV}>{value}</Text></View>
);

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  headerT: { color: theme.color.text, fontSize: 14, letterSpacing: 2, fontWeight: "900" },
  name: { color: theme.color.text, fontSize: 26, fontWeight: "900" },
  email: { color: theme.color.textMuted, marginTop: 2 },
  actionRow: { flexDirection: "row", gap: 8, marginTop: theme.space.md },
  actionBtn: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: theme.color.brand, paddingVertical: 10, paddingHorizontal: 14, borderRadius: theme.radius.md },
  actionText: { color: "#fff", fontWeight: "800", letterSpacing: 1.5, fontSize: 11 },
  card: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, padding: theme.space.md, marginTop: theme.space.md },
  sect: { color: theme.color.textMuted, letterSpacing: 2, fontSize: 10, fontWeight: "800", marginBottom: theme.space.sm },
  row: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 6, borderTopWidth: 1, borderTopColor: theme.color.divider },
  rowL: { color: theme.color.textMuted, fontSize: 13 },
  rowV: { color: theme.color.text, fontWeight: "700", fontSize: 13 },
  dayRow: { flexDirection: "row", alignItems: "center", paddingVertical: 8, borderTopWidth: 1, borderTopColor: theme.color.divider },
  bar: { width: 4, height: 24, marginRight: 10, borderRadius: 2 },
  dText: { color: theme.color.text, fontSize: 13, letterSpacing: 1, fontWeight: "700" },
  fText: { color: theme.color.brand, fontSize: 12, fontWeight: "600" },
  wRow: { flexDirection: "row", alignItems: "center", paddingVertical: 10, borderTopWidth: 1, borderTopColor: theme.color.divider },
  wTitle: { color: theme.color.text, fontSize: 14, fontWeight: "700" },
  wMeta: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },
  approved: { color: theme.color.green, fontSize: 20, marginRight: 4 },
  pending: { color: theme.color.amber, fontSize: 10, fontWeight: "800", letterSpacing: 1.5 },
  ovRow: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 8, borderTopWidth: 1, borderTopColor: theme.color.divider },
  ovLeft: { flexDirection: "row", alignItems: "center", gap: 6, width: 118 },
  ovDate: { color: theme.color.text, fontSize: 11, fontWeight: "700", letterSpacing: 0.5 },
  ovTags: { color: theme.color.amber, fontSize: 10, fontWeight: "800", letterSpacing: 1 },
  ovNotes: { color: theme.color.textMuted, fontSize: 11, fontStyle: "italic", marginTop: 2 },
  ovMore: { color: theme.color.textDim, fontSize: 10, fontWeight: "700", letterSpacing: 1, marginTop: 6, textAlign: "center" },
});
