import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, RefreshControl, ActivityIndicator } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme, loadColor } from "@/src/lib/theme";

export default function Clients() {
  const router = useRouter();
  const [clients, setClients] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try { setClients(await api<any[]>("/coach/clients")); } finally { setLoading(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <View>
          <Text style={styles.title}>CLIENTS</Text>
          <Text style={styles.sub}>{clients.length} active</Text>
        </View>
      </View>
      <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 60 }} refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}>
        {loading && clients.length === 0 ? <ActivityIndicator color={theme.color.brand} /> : clients.length === 0 ? <Text style={{ color: theme.color.textMuted }}>No clients yet.</Text> :
          clients.map((c) => {
            const days = c.latest_roster?.days || [];
            return (
              <Pressable key={c.id} testID={`client-card-${c.id}`} onPress={() => router.push(`/coach/client/${c.id}`)} style={styles.card}>
                <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
                  <View>
                    <Text style={styles.name}>{c.name}</Text>
                    <Text style={styles.email}>{c.email}</Text>
                  </View>
                  {c.pending_approvals > 0 && (
                    <View style={styles.pendingPill}>
                      <Text style={styles.pendingText}>{c.pending_approvals} PENDING</Text>
                    </View>
                  )}
                </View>
                {days.length > 0 && (
                  <View style={styles.loadRow}>
                    {days.slice(0, 7).map((d: any, i: number) => (
                      <View key={i} style={[styles.loadBlock, { backgroundColor: loadColor(d.load) }]} />
                    ))}
                    <Text style={styles.rosterText}>ROSTER · {c.latest_roster?.week_start}</Text>
                  </View>
                )}
                <View style={styles.actionRow}>
                  <Text style={styles.action}>REVIEW →</Text>
                </View>
              </Pressable>
            );
          })
        }
      </ScrollView>
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  title: { color: theme.color.text, fontSize: 22, fontWeight: "900", letterSpacing: 2 },
  sub: { color: theme.color.textMuted, marginTop: 2 },
  card: { padding: theme.space.md, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, marginBottom: theme.space.sm },
  name: { color: theme.color.text, fontSize: 16, fontWeight: "800" },
  email: { color: theme.color.textMuted, fontSize: 12, marginTop: 2 },
  pendingPill: { backgroundColor: theme.color.brand, paddingHorizontal: 10, paddingVertical: 4, borderRadius: theme.radius.sm },
  pendingText: { color: "#fff", fontSize: 9, letterSpacing: 1.5, fontWeight: "800" },
  loadRow: { flexDirection: "row", gap: 4, marginTop: 10, alignItems: "center" },
  loadBlock: { flex: 1, height: 6, borderRadius: 2 },
  rosterText: { color: theme.color.textDim, fontSize: 10, letterSpacing: 1, marginLeft: 8, fontWeight: "700" },
  actionRow: { marginTop: 8, borderTopWidth: 1, borderTopColor: theme.color.divider, paddingTop: 8, alignItems: "flex-end" },
  action: { color: theme.color.brand, letterSpacing: 2, fontWeight: "800", fontSize: 11 },
});
