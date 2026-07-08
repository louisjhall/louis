import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, RefreshControl, ActivityIndicator } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { api } from "@/src/lib/api";
import { theme, loadColor } from "@/src/lib/theme";

export default function Approvals() {
  const router = useRouter();
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    setLoading(true);
    try { setItems(await api<any[]>("/coach/pending-approvals")); } finally { setLoading(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Text style={styles.title}>ATLAS RECOMMENDATIONS</Text>
        <Text style={styles.sub}>Prepared using the CrewFit Coaching System · Awaiting Coach Review</Text>
        <Text style={styles.count}>{items.length} workouts awaiting your approval</Text>
      </View>
      <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 60 }} refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}>
        {loading && items.length === 0 ? <ActivityIndicator color={theme.color.brand} /> : items.length === 0 ? (
          <Text style={{ color: theme.color.textMuted, textAlign: "center", marginTop: 60 }}>No plans pending. Great work.</Text>
        ) : items.map((w) => (
          <Pressable key={w.id} testID={`approval-${w.id}`} onPress={() => router.push(`/workout/${w.id}`)} style={styles.card}>
            <View style={[styles.loadBar, { backgroundColor: loadColor(w.day_load) }]} />
            <View style={{ flex: 1, padding: theme.space.md }}>
              <Text style={styles.client}>{w.client_name}</Text>
              <Text style={styles.title2}>{w.title}</Text>
              <Text style={styles.meta}>{w.date} · {w.exercises?.length || 0} exercises</Text>
            </View>
            <Text style={styles.review}>REVIEW →</Text>
          </Pressable>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  title: { color: theme.color.text, fontSize: 16, letterSpacing: 2, fontWeight: "900" },
  sub: { color: theme.color.brand, marginTop: 4, fontSize: 10, fontWeight: "800", letterSpacing: 1.5 },
  count: { color: theme.color.textMuted, marginTop: 4, fontSize: 12 },
  card: { flexDirection: "row", alignItems: "center", backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, marginBottom: theme.space.sm, overflow: "hidden" },
  loadBar: { width: 4, alignSelf: "stretch" },
  client: { color: theme.color.brand, fontSize: 11, letterSpacing: 1.5, fontWeight: "800" },
  title2: { color: theme.color.text, fontSize: 15, fontWeight: "700", marginTop: 2 },
  meta: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  review: { color: theme.color.brand, letterSpacing: 2, fontWeight: "800", fontSize: 11, marginRight: theme.space.md },
});
