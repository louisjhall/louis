import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme, loadColor } from "@/src/lib/theme";

export default function CoachAnalytics() {
  const router = useRouter();
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<any>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api<any>(`/coach/analytics?days=${days}`));
    } finally {
      setLoading(false);
    }
  }, [days]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const clients: any[] = data?.clients || [];
  const dist = data?.load_distribution || {};
  const totalLoad = Object.values(dist).reduce((s: number, v: any) => s + (v || 0), 0) as number;

  return (
    <ScrollView
      style={styles.root}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}
    >
      <View style={styles.header}>
        <View>
          <Text style={styles.h1}>ANALYTICS</Text>
          <Text style={styles.sub}>Performance metrics across the fleet</Text>
        </View>
        <View style={styles.rangeRow}>
          {[7, 30, 90].map((n) => (
            <Pressable
              key={n}
              testID={`an-range-${n}`}
              onPress={() => setDays(n)}
              style={[styles.rangeChip, days === n && styles.rangeChipActive]}
            >
              <Text style={[styles.rangeText, days === n && { color: "#fff" }]}>LAST {n}D</Text>
            </Pressable>
          ))}
        </View>
      </View>

      {loading && !data ? (
        <ActivityIndicator color={theme.color.brand} style={{ marginTop: 40 }} />
      ) : !data ? (
        <Text style={styles.empty}>No data yet.</Text>
      ) : (
        <>
          <View style={styles.kpiRow}>
            <BigKPI icon="people" label="CLIENTS" value={data.total_clients} sub="active" />
            <BigKPI icon="calendar" label="SCHEDULED" value={data.total_scheduled} sub="workouts" />
            <BigKPI icon="checkmark-done" label="COMPLETED" value={data.total_completed} sub={`${data.total_scheduled ? Math.round((data.total_completed / data.total_scheduled) * 100) : 0}% done`} tint={theme.color.green} />
            <BigKPI icon="trending-up" label="COMPLIANCE" value={`${data.global_compliance}%`} sub="fleet-wide" tint={complianceColor(data.global_compliance)} />
            <BigKPI icon="pulse" label="AVG RPE" value={data.global_avg_rpe ?? "—"} sub="perceived exertion" tint={theme.color.brand} />
          </View>

          <View style={styles.twoCol}>
            <View style={[styles.section, { flex: 1 }]}>
              <Text style={styles.sectionTitle}>COMPLIANCE BY CLIENT</Text>
              <Text style={styles.sectionSub}>Last {days} days · completed / scheduled</Text>
              {clients.length === 0 ? (
                <Text style={styles.empty}>No clients yet.</Text>
              ) : (
                <View style={{ gap: 10, marginTop: 12 }}>
                  {clients.map((c: any) => (
                    <Pressable
                      key={c.client_id}
                      testID={`an-row-${c.client_id}`}
                      onPress={() => router.push(`/coach/client/${c.client_id}` as any)}
                      style={styles.compRow}
                    >
                      <Text style={styles.compName} numberOfLines={1}>{c.client_name}</Text>
                      <View style={styles.progressTrack}>
                        <View
                          style={[
                            styles.progressFill,
                            {
                              width: `${Math.max(2, c.compliance)}%`,
                              backgroundColor: complianceColor(c.compliance),
                            },
                          ]}
                        />
                      </View>
                      <Text style={[styles.compPct, { color: complianceColor(c.compliance) }]}>
                        {c.compliance}%
                      </Text>
                      <Text style={styles.compMeta}>{c.completed}/{c.scheduled}</Text>
                      <Text style={styles.compMeta}>RPE {c.avg_rpe ?? "—"}</Text>
                      <Text style={styles.compKey}>
                        <Ionicons name="star" size={11} color={theme.color.brand} /> {c.key_sessions_completed}/{c.key_sessions_total}
                      </Text>
                    </Pressable>
                  ))}
                </View>
              )}
            </View>

            <View style={[styles.section, { width: 340 }]}>
              <Text style={styles.sectionTitle}>LOAD DISTRIBUTION</Text>
              <Text style={styles.sectionSub}>All workouts · last {days} days</Text>
              {totalLoad === 0 ? (
                <Text style={styles.empty}>No workouts yet.</Text>
              ) : (
                <>
                  <View style={styles.stackedBar}>
                    {["green", "amber", "red", "blue", "purple", "grey"].map((k) => {
                      const v = dist[k] || 0;
                      const pct = totalLoad ? (v / totalLoad) * 100 : 0;
                      if (pct === 0) return null;
                      return (
                        <View
                          key={k}
                          style={{
                            width: `${pct}%`,
                            height: "100%",
                            backgroundColor: loadColor(k),
                          }}
                        />
                      );
                    })}
                  </View>
                  <View style={{ gap: 8, marginTop: 14 }}>
                    {["green", "amber", "red", "blue", "purple", "grey"].map((k) => {
                      const v = dist[k] || 0;
                      const pct = totalLoad ? Math.round((v / totalLoad) * 100) : 0;
                      return (
                        <View key={k} style={styles.distRow}>
                          <View style={[styles.distDot, { backgroundColor: loadColor(k) }]} />
                          <Text style={styles.distLabel}>{k.toUpperCase()}</Text>
                          <Text style={styles.distVal}>{v}</Text>
                          <Text style={styles.distPct}>{pct}%</Text>
                        </View>
                      );
                    })}
                  </View>
                </>
              )}
            </View>
          </View>
        </>
      )}
    </ScrollView>
  );
}

function complianceColor(pct: number): string {
  if (pct >= 80) return theme.color.green;
  if (pct >= 60) return theme.color.amber;
  if (pct >= 40) return "#F97316";
  return theme.color.red;
}

function BigKPI({ icon, label, value, sub, tint }: any) {
  return (
    <View style={styles.kpi}>
      <View style={styles.kpiTop}>
        <Ionicons name={icon} size={16} color={tint || theme.color.brand} />
        <Text style={styles.kpiLabel}>{label}</Text>
      </View>
      <Text style={[styles.kpiVal, tint && { color: tint }]}>{value}</Text>
      <Text style={styles.kpiSub}>{sub}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  content: { padding: 32, paddingBottom: 80, maxWidth: 1600 },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 20 },
  h1: { color: theme.color.text, fontSize: 28, fontWeight: "900", letterSpacing: 2 },
  sub: { color: theme.color.textMuted, marginTop: 4 },

  rangeRow: { flexDirection: "row", gap: 6 },
  rangeChip: { paddingHorizontal: 14, paddingVertical: 8, backgroundColor: theme.color.surface2, borderRadius: 6, borderWidth: 1, borderColor: theme.color.border },
  rangeChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  rangeText: { color: theme.color.textMuted, fontWeight: "800", letterSpacing: 1, fontSize: 11 },

  kpiRow: { flexDirection: "row", gap: 12, marginBottom: 20, flexWrap: "wrap" },
  kpi: { flex: 1, minWidth: 180, padding: 18, backgroundColor: theme.color.surface2, borderRadius: 12, borderWidth: 1, borderColor: theme.color.border },
  kpiTop: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 8 },
  kpiLabel: { color: theme.color.textDim, fontSize: 10, fontWeight: "800", letterSpacing: 1.5 },
  kpiVal: { color: theme.color.text, fontSize: 30, fontWeight: "900", letterSpacing: -1 },
  kpiSub: { color: theme.color.textMuted, fontSize: 11, marginTop: 4 },

  section: { backgroundColor: theme.color.surface2, padding: 20, borderRadius: 12, borderWidth: 1, borderColor: theme.color.border, marginBottom: 20 },
  sectionTitle: { color: theme.color.text, fontSize: 12, fontWeight: "800", letterSpacing: 2 },
  sectionSub: { color: theme.color.textMuted, fontSize: 11, marginTop: 4 },

  twoCol: { flexDirection: "row", gap: 20, alignItems: "flex-start" },

  compRow: { flexDirection: "row", alignItems: "center", gap: 12, padding: 12, backgroundColor: theme.color.surface3, borderRadius: 8 },
  compName: { color: theme.color.text, fontSize: 13, fontWeight: "700", width: 200 },
  progressTrack: { flex: 1, height: 8, borderRadius: 4, backgroundColor: theme.color.border, overflow: "hidden" },
  progressFill: { height: "100%", borderRadius: 4 },
  compPct: { fontSize: 13, fontWeight: "800", width: 50, textAlign: "right" },
  compMeta: { color: theme.color.textDim, fontSize: 11, width: 70, textAlign: "right", fontWeight: "700" },
  compKey: { color: theme.color.text, fontSize: 11, width: 60, textAlign: "right", fontWeight: "700" },

  stackedBar: { flexDirection: "row", height: 24, borderRadius: 6, overflow: "hidden", backgroundColor: theme.color.border, marginTop: 12 },
  distRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  distDot: { width: 12, height: 12, borderRadius: 3 },
  distLabel: { color: theme.color.text, fontSize: 11, fontWeight: "700", letterSpacing: 1, flex: 1 },
  distVal: { color: theme.color.text, fontSize: 13, fontWeight: "800", width: 40, textAlign: "right" },
  distPct: { color: theme.color.textMuted, fontSize: 11, width: 40, textAlign: "right", fontWeight: "700" },

  empty: { color: theme.color.textMuted, textAlign: "center", padding: 30 },
});
