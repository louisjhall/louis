/**
 * Coach-wide Change Log — audit trail of all coach + Atlas actions.
 * Filterable by category (message, controls, programme, script, workout).
 */
import { useCallback, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Entry = {
  id: string;
  client_id?: string;
  category: string;
  title: string;
  description?: string;
  actor?: string;
  created_at: string;
  meta?: any;
};

const CATEGORIES = [
  { key: "", label: "ALL" },
  { key: "message", label: "MESSAGES" },
  { key: "controls", label: "CONTROLS" },
  { key: "script", label: "SCRIPTS" },
  { key: "programme", label: "PROGRAMME" },
];

function catColor(c: string): string {
  switch (c) {
    case "message": return theme.color.brand;
    case "controls": return theme.color.amber;
    case "programme": return theme.color.brand;
    case "script": return theme.color.brand;
    case "workout": return theme.color.green;
    default: return theme.color.textDim;
  }
}

export default function ChangeLogScreen() {
  const [loading, setLoading] = useState(true);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [filter, setFilter] = useState<string>("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q = filter ? `?category=${filter}` : "";
      const r = await api<{ entries: Entry[] }>(`/coach/change-log${q}`);
      setEntries(r.entries || []);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, [filter]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const grouped = useMemo(() => {
    const days: Record<string, Entry[]> = {};
    for (const e of entries) {
      const day = (e.created_at || "").slice(0, 10);
      if (!days[day]) days[day] = [];
      days[day].push(e);
    }
    return days;
  }, [entries]);

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Text style={styles.title}>CHANGE LOG</Text>
        <Text style={styles.subtitle}>{entries.length} entries · {filter || "all categories"}</Text>
      </View>
      <View style={styles.filterRow}>
        {CATEGORIES.map((c) => (
          <Pressable
            key={c.key || "all"}
            testID={`filter-${c.key || "all"}`}
            onPress={() => setFilter(c.key)}
            style={[styles.filterChip, filter === c.key && styles.filterChipActive]}
          >
            <Text style={[styles.filterChipT, filter === c.key && { color: "#fff" }]}>{c.label}</Text>
          </Pressable>
        ))}
      </View>
      <ScrollView
        contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 60 }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}
      >
        {loading && !entries.length ? (
          <ActivityIndicator color={theme.color.brand} style={{ marginTop: 40 }} />
        ) : entries.length === 0 ? (
          <Text style={styles.empty}>No changes logged yet.</Text>
        ) : (
          Object.keys(grouped).map((day) => (
            <View key={day} style={{ marginBottom: 22 }}>
              <Text style={styles.dayHead}>{day}</Text>
              <View style={{ gap: 6 }}>
                {grouped[day].map((e) => (
                  <View key={e.id} style={styles.card}>
                    <View style={[styles.dot, { backgroundColor: catColor(e.category) }]} />
                    <View style={{ flex: 1 }}>
                      <View style={styles.topRow}>
                        <Text style={[styles.cat, { color: catColor(e.category) }]}>{e.category?.toUpperCase()}</Text>
                        <Text style={styles.actor}>{(e.actor || "coach").toUpperCase()}</Text>
                        <Text style={styles.time}>{(e.created_at || "").slice(11, 16)}</Text>
                      </View>
                      <Text style={styles.title2}>{e.title}</Text>
                      {e.description ? <Text style={styles.desc}>{e.description}</Text> : null}
                    </View>
                  </View>
                ))}
              </View>
            </View>
          ))
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  title: { color: theme.color.text, fontSize: 20, letterSpacing: 2, fontWeight: "900" },
  subtitle: { color: theme.color.textMuted, marginTop: 4, fontSize: 12 },
  filterRow: { flexDirection: "row", gap: 6, padding: theme.space.md, flexWrap: "wrap" },
  filterChip: { paddingHorizontal: 12, paddingVertical: 7, borderRadius: theme.radius.pill, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  filterChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  filterChipT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700", letterSpacing: 1 },
  empty: { color: theme.color.textMuted, textAlign: "center", marginTop: 40 },
  dayHead: { color: theme.color.textDim, fontSize: 11, fontWeight: "800", letterSpacing: 1.5, marginBottom: 8 },
  card: { flexDirection: "row", gap: 10, padding: 12, backgroundColor: theme.color.surface2, borderRadius: 10, borderWidth: 1, borderColor: theme.color.border },
  dot: { width: 6, height: 6, borderRadius: 3, marginTop: 6 },
  topRow: { flexDirection: "row", gap: 8, alignItems: "center", marginBottom: 4 },
  cat: { fontSize: 11, fontWeight: "800", letterSpacing: 1.5 },
  actor: { color: theme.color.textDim, fontSize: 11, fontWeight: "800", letterSpacing: 1.5 },
  time: { color: theme.color.textDim, fontSize: 11, marginLeft: "auto" },
  title2: { color: theme.color.text, fontSize: 13, fontWeight: "700" },
  desc: { color: theme.color.textMuted, fontSize: 11, marginTop: 2, lineHeight: 15 },
});
