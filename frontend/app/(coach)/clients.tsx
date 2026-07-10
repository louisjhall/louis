import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, RefreshControl, ActivityIndicator } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { api } from "@/src/lib/api";
import { theme, loadColor } from "@/src/lib/theme";
import { ProfileAvatar } from "@/src/components/ProfileAvatar";
import { PreviewClientButton } from "@/src/components/PreviewLauncher";

const FILTERS = [
  { key: "all", label: "ALL" },
  { key: "expiring_soon", label: "EXPIRING" },
  { key: "expired", label: "EXPIRED" },
  { key: "no_roster", label: "NO ROSTER" },
  { key: "needs_confirmation", label: "NEEDS CONFIRM" },
  { key: "pending_approval", label: "PENDING" },
  { key: "red_days", label: "RED DAYS" },
  { key: "missed", label: "MISSED" },
];

export default function Clients() {
  const router = useRouter();
  const [filter, setFilter] = useState("all");
  const [data, setData] = useState<any>({ clients: [], counts: {}, total: 0 });
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try { setData(await api<any>(`/coach/dashboard?filter=${filter}`)); } finally { setLoading(false); }
  }, [filter]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const c = data.counts || {};

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Text style={styles.title}>CLIENTS</Text>
        <Text style={styles.sub}>{data.total || 0} active</Text>
      </View>

      <View style={styles.widgets}>
        <Widget dotColor={theme.color.green} label="Active" value={Math.max(0, (data.total || 0) - Math.max(c.expired || 0, c.no_roster || 0))} />
        <Widget dotColor={theme.color.amber} label="Expiring" value={c.expiring_soon || 0} tint={theme.color.amber} />
        <Widget dotColor={theme.color.red}   label="Expired"  value={c.expired || 0} tint={theme.color.red} />
        <Widget dotColor={theme.color.textDim} label="No Roster" value={c.no_roster || 0} />
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.filtersRow}>
        {FILTERS.map((f) => (
          <Pressable key={f.key} testID={`filter-${f.key}`} onPress={() => setFilter(f.key)} style={[styles.chip, filter === f.key && styles.chipActive]}>
            <Text style={[styles.chipText, filter === f.key && { color: "#fff" }]}>{f.label}</Text>
            {c[f.key] !== undefined && f.key !== "all" && <Text style={[styles.chipCount, filter === f.key && { color: "#fff" }]}> {c[f.key]}</Text>}
          </Pressable>
        ))}
      </ScrollView>

      <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 60 }} refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}>
        {loading && data.clients.length === 0 ? <ActivityIndicator color={theme.color.brand} /> :
          data.clients.length === 0 ? <Text style={{ color: theme.color.textMuted, textAlign: "center", marginTop: 40 }}>No clients in this bucket.</Text> :
          data.clients.map((cl: any) => {
            const days = cl.latest_roster?.days || [];
            const exp = cl.roster_expiry || {};
            return (
              <Pressable key={cl.id} testID={`client-card-${cl.id}`} onPress={() => router.push(`/coach/client/${cl.id}`)} style={styles.card}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
                  <ProfileAvatar userId={cl.id} name={cl.name} photoUrl={cl.profile_photo_url || null} size={44} ring={false} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.name}>{cl.name}</Text>
                    {cl.profile?.job_title || cl.profile?.airline ? (
                      <Text style={styles.roleLine} numberOfLines={1}>
                        {cl.profile?.job_title || "Crew"}
                        {cl.profile?.airline ? ` · ${cl.profile.airline}` : ""}
                      </Text>
                    ) : null}
                    {cl.profile?.home_base || cl.current_location_city ? (
                      <Text style={styles.locLine} numberOfLines={1}>
                        {cl.profile?.home_base ? String(cl.profile.home_base).toUpperCase() : ""}
                        {cl.current_location_city ? `  ·  in ${cl.current_location_city}` : ""}
                      </Text>
                    ) : (
                      <Text style={styles.email} numberOfLines={1}>{cl.email}</Text>
                    )}
                  </View>
                  <View style={{ alignItems: "flex-end", gap: 4 }}>
                    {cl.pending_approvals > 0 && (
                      <View style={styles.pendingPill}><Text style={styles.pendingText}>{cl.pending_approvals} PENDING</Text></View>
                    )}
                    {exp.expired && <View style={[styles.pendingPill, { backgroundColor: theme.color.red }]}><Text style={styles.pendingText}>EXPIRED</Text></View>}
                    {!exp.expired && exp.coverage === "critical" && <View style={[styles.pendingPill, { backgroundColor: theme.color.amber }]}><Text style={styles.pendingText}>{exp.days_remaining}D LEFT</Text></View>}
                  </View>
                </View>
                {days.length > 0 && (
                  <View style={styles.loadRow}>
                    {days.slice(0, 14).map((d: any, i: number) => (
                      <View key={i} style={[styles.loadBlock, { backgroundColor: loadColor(d.load) }]} />
                    ))}
                    <Text style={styles.rosterText}>{cl.latest_roster?.start_date} → {cl.latest_roster?.end_date}</Text>
                  </View>
                )}
                <View style={styles.actionRow}>
                  <Text style={styles.metaSmall}>{cl.missed_workouts > 0 ? `${cl.missed_workouts} missed` : ""}</Text>
                  <View style={{ flexDirection: "row", gap: 12, alignItems: "center" }}>
                    <PreviewClientButton clientId={cl.id} clientName={cl.name} />
                    <Text style={styles.action}>REVIEW →</Text>
                  </View>
                </View>
              </Pressable>
            );
          })
        }
      </ScrollView>
    </SafeAreaView>
  );
}

function Widget({ dotColor, label, value, tint }: any) {
  return (
    <View style={styles.widget}>
      <View style={[styles.wDot, { backgroundColor: dotColor || theme.color.textDim }]} />
      <View>
        <Text style={[styles.wVal, tint && { color: tint }]}>{value}</Text>
        <Text style={styles.wLabel}>{label}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  title: { color: theme.color.text, fontSize: 22, fontWeight: "900", letterSpacing: 2 },
  sub: { color: theme.color.textMuted, marginTop: 2 },
  widgets: { flexDirection: "row", padding: theme.space.md, gap: theme.space.sm },
  widget: { flex: 1, flexDirection: "row", alignItems: "center", gap: 8, padding: 10, borderRadius: theme.radius.md, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  wIcon: { fontSize: 16 },
  wDot: { width: 10, height: 10, borderRadius: 5 },
  wVal: { color: theme.color.text, fontSize: 20, fontWeight: "900", fontFamily: theme.font.display },
  wLabel: { color: theme.color.textDim, fontSize: 9, letterSpacing: 1, fontWeight: "700", fontFamily: theme.font.textSemi },
  roleLine: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700", letterSpacing: 0.5, marginTop: 1, fontFamily: theme.font.text },
  locLine: { color: theme.color.textDim, fontSize: 10, letterSpacing: 1, fontWeight: "800", marginTop: 2, fontFamily: theme.font.textSemi },
  filtersRow: { paddingHorizontal: theme.space.lg, paddingBottom: theme.space.sm, gap: 6 },
  chip: { flexDirection: "row", paddingHorizontal: 12, paddingVertical: 6, borderRadius: theme.radius.pill, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, flexShrink: 0 },
  chipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipText: { color: theme.color.textMuted, fontSize: 10, fontWeight: "800", letterSpacing: 1 },
  chipCount: { color: theme.color.brand, fontSize: 10, fontWeight: "800" },
  card: { padding: theme.space.md, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, marginBottom: theme.space.sm },
  name: { color: theme.color.text, fontSize: 16, fontWeight: "800" },
  email: { color: theme.color.textMuted, fontSize: 12, marginTop: 2 },
  pendingPill: { backgroundColor: theme.color.brand, paddingHorizontal: 8, paddingVertical: 3, borderRadius: theme.radius.sm },
  pendingText: { color: "#fff", fontSize: 9, letterSpacing: 1.5, fontWeight: "800" },
  loadRow: { flexDirection: "row", gap: 3, marginTop: 10, alignItems: "center" },
  loadBlock: { flex: 1, height: 6, borderRadius: 2 },
  rosterText: { color: theme.color.textDim, fontSize: 9, letterSpacing: 0.5, marginLeft: 6, fontWeight: "700" },
  actionRow: { marginTop: 8, borderTopWidth: 1, borderTopColor: theme.color.divider, paddingTop: 8, flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  metaSmall: { color: theme.color.amber, fontSize: 10, fontWeight: "700", letterSpacing: 1 },
  action: { color: theme.color.brand, letterSpacing: 2, fontWeight: "800", fontSize: 11 },
});
