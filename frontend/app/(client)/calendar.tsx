import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, RefreshControl, ActivityIndicator } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme, loadColor } from "@/src/lib/theme";

export default function Calendar() {
  const router = useRouter();
  const [roster, setRoster] = useState<any>(null);
  const [workouts, setWorkouts] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [r, w] = await Promise.all([api<any>("/roster/current"), api<any[]>("/workouts/week")]);
      setRoster(r && r.id ? r : null);
      setWorkouts(w || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const generate = async () => {
    if (!roster) return;
    setGenerating(true);
    setErr(null);
    try {
      const r = await api<{ workouts: any[] }>("/workouts/generate", {
        method: "POST",
        body: { roster_id: roster.id },
      });
      setWorkouts(r.workouts);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setGenerating(false);
    }
  };

  const byDate = new Map(workouts.map((w) => [w.date, w]));

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Text style={styles.title}>WEEKLY PLAN</Text>
        <Pressable onPress={() => router.push("/roster-upload")} testID="calendar-upload-btn" style={styles.upload}>
          <Ionicons name="cloud-upload" size={14} color={theme.color.brand} />
          <Text style={styles.uploadText}>UPLOAD</Text>
        </Pressable>
      </View>
      <ScrollView
        contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 40 }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}
      >
        {!roster ? (
          <View style={styles.emptyCard}>
            <Ionicons name="airplane" size={40} color={theme.color.brand} />
            <Text style={styles.emptyTitle}>No roster uploaded</Text>
            <Text style={styles.emptySub}>Upload your flight schedule to build the week.</Text>
            <Pressable onPress={() => router.push("/roster-upload")} style={styles.cta} testID="empty-upload-roster">
              <Text style={styles.ctaText}>UPLOAD ROSTER</Text>
            </Pressable>
          </View>
        ) : (
          <>
            <View style={styles.rosterBox}>
              <Text style={styles.sectLabel}>ROSTER · WEEK OF {roster.week_start}</Text>
              {(roster.days || []).map((d: any) => {
                const w = byDate.get(d.date);
                return (
                  <Pressable
                    key={d.date}
                    testID={`calendar-day-${d.date}`}
                    onPress={() => w && router.push(`/workout/${w.id}`)}
                    style={styles.dayRow}
                  >
                    <View style={[styles.loadBar, { backgroundColor: loadColor(d.load) }]} />
                    <View style={{ flex: 1, padding: theme.space.md }}>
                      <Text style={styles.dayDate}>{d.date} · {d.type?.toUpperCase()}</Text>
                      {d.flights?.[0] && (
                        <Text style={styles.dayFlight}>
                          ✈ {d.flights.map((f: any) => `${f.from}→${f.to}`).join("  ")}
                        </Text>
                      )}
                      <Text style={styles.dayWk}>{w ? w.title : "— No workout"}</Text>
                    </View>
                    {w?.completed && <Ionicons name="checkmark-circle" size={20} color={theme.color.green} style={{ marginRight: theme.space.md }} />}
                    {w && !w.completed && <Ionicons name="chevron-forward" size={18} color={theme.color.textDim} style={{ marginRight: theme.space.md }} />}
                  </Pressable>
                );
              })}
            </View>

            {err && <Text style={{ color: theme.color.red, marginTop: theme.space.md }}>{err}</Text>}

            <Pressable
              testID="generate-week-btn"
              onPress={generate}
              disabled={generating}
              style={[styles.generateBtn, generating && { opacity: 0.6 }]}
            >
              {generating ? (
                <>
                  <ActivityIndicator color="#fff" />
                  <Text style={styles.ctaText}>  AI IS BUILDING YOUR WEEK…</Text>
                </>
              ) : (
                <>
                  <Ionicons name="sparkles" size={16} color="#fff" />
                  <Text style={styles.ctaText}>  {workouts.length ? "REGENERATE" : "GENERATE"} WEEKLY PLAN</Text>
                </>
              )}
            </Pressable>
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  title: { color: theme.color.text, fontSize: 20, letterSpacing: 2, fontWeight: "900" },
  upload: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: theme.color.surface2, paddingHorizontal: 12, paddingVertical: 6, borderRadius: theme.radius.pill, borderWidth: 1, borderColor: theme.color.border },
  uploadText: { color: theme.color.brand, fontWeight: "800", fontSize: 10, letterSpacing: 1.5 },
  emptyCard: { alignItems: "center", padding: theme.space.xxl, borderWidth: 1, borderColor: theme.color.border, borderRadius: theme.radius.md, backgroundColor: theme.color.surface2 },
  emptyTitle: { color: theme.color.text, fontSize: 18, fontWeight: "800", marginTop: theme.space.md },
  emptySub: { color: theme.color.textMuted, marginTop: 4, textAlign: "center" },
  cta: { backgroundColor: theme.color.brand, paddingVertical: 14, paddingHorizontal: theme.space.xl, borderRadius: theme.radius.md, marginTop: theme.space.lg },
  ctaText: { color: "#fff", fontWeight: "800", letterSpacing: 2, fontSize: 13 },
  rosterBox: { borderRadius: theme.radius.md, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, overflow: "hidden" },
  sectLabel: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 2, fontWeight: "800", padding: theme.space.md, paddingBottom: theme.space.sm },
  dayRow: { flexDirection: "row", alignItems: "stretch", borderTopWidth: 1, borderTopColor: theme.color.divider },
  loadBar: { width: 4 },
  dayDate: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1.5, fontWeight: "700" },
  dayFlight: { color: theme.color.brand, fontSize: 12, marginTop: 2, fontWeight: "600" },
  dayWk: { color: theme.color.text, fontSize: 15, marginTop: 4, fontWeight: "700" },
  generateBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", backgroundColor: theme.color.brand, paddingVertical: 16, borderRadius: theme.radius.md, marginTop: theme.space.lg },
});
