import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { REALITY_KINDS } from "@/src/components/RealityModal";

export default function RealityHistoryScreen() {
  const router = useRouter();
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<any>("/reality/history?limit=100");
      setRows(r.history || []);
    } finally { setLoading(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const iconFor = (kind: string) =>
    (REALITY_KINDS.find((k) => k.key === kind)?.icon as any) || "document-text";

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} testID="reality-history-back">
          <Ionicons name="chevron-back" size={24} color={theme.color.text} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>MOVE HISTORY</Text>
          <Text style={styles.sub}>Every adaptation, explained</Text>
        </View>
      </View>

      <ScrollView
        contentContainerStyle={styles.body}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}
      >
        {loading && !rows.length ? (
          <ActivityIndicator color={theme.color.brand} style={{ marginTop: 40 }} />
        ) : rows.length === 0 ? (
          <View style={styles.empty}>
            <Ionicons name="time" size={36} color={theme.color.textDim} />
            <Text style={styles.emptyT}>No adaptations yet</Text>
            <Text style={styles.emptyS}>
              Tap &quot;Today&apos;s Reality&quot; on the home screen when life changes — CrewFit adapts your plan.
            </Text>
          </View>
        ) : (
          rows.map((h) => (
            <View key={h.id} style={styles.card}>
              <View style={styles.cardHead}>
                <View style={styles.cardIconWrap}>
                  <Ionicons name={iconFor(h.reality_kind)} size={16} color={theme.color.brand} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.cardLabel}>{h.reality_label || h.reality_kind}</Text>
                  <Text style={styles.cardDate}>
                    {h.date} · {String(h.actor_role || "client").toUpperCase()}
                  </Text>
                </View>
                <View style={styles.optPill}>
                  <Text style={styles.optPillText}>OPT {h.option_id}</Text>
                </View>
              </View>
              <Text style={styles.cardTitle}>{h.option_title}</Text>
              {h.option_why ? (
                <Text style={styles.cardWhy}>{h.option_why}</Text>
              ) : null}
              {(h.changes || []).length > 0 && (
                <View style={styles.changeList}>
                  {(h.changes || []).slice(0, 6).map((c: any, i: number) => (
                    <View key={i} style={styles.changeChip}>
                      <Ionicons
                        name={c.changed ? "checkmark-circle" : "remove-circle"}
                        size={11}
                        color={c.changed ? theme.color.green : theme.color.textDim}
                      />
                      <Text style={styles.changeText}>{c.kind}</Text>
                    </View>
                  ))}
                </View>
              )}
              <Text style={styles.cardTime}>
                {(h.created_at || "").replace("T", " ").slice(0, 16)}
              </Text>
            </View>
          ))
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: {
    flexDirection: "row", alignItems: "center", gap: 10,
    padding: theme.space.lg,
    borderBottomWidth: 1, borderBottomColor: theme.color.divider,
  },
  title: { color: theme.color.text, fontSize: 14, fontWeight: "900", letterSpacing: 2 },
  sub: { color: theme.color.textMuted, fontSize: 11, marginTop: 3 },
  body: { padding: theme.space.lg, paddingBottom: 40 },
  empty: { alignItems: "center", padding: 40 },
  emptyT: { color: theme.color.text, fontSize: 14, fontWeight: "800", letterSpacing: 1.5, marginTop: 10 },
  emptyS: { color: theme.color.textMuted, fontSize: 12, textAlign: "center", marginTop: 8, lineHeight: 18 },

  card: {
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
    borderRadius: theme.radius.md,
    padding: theme.space.md,
    marginBottom: theme.space.md,
  },
  cardHead: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 8 },
  cardEmoji: { fontSize: 26 },
  cardIconWrap: { width: 32, height: 32, borderRadius: 16, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand, alignItems: "center", justifyContent: "center" },
  cardLabel: { color: theme.color.text, fontSize: 13, fontWeight: "800", letterSpacing: 0.5 },
  cardDate: { color: theme.color.textDim, fontSize: 10, fontWeight: "700", letterSpacing: 1.5, marginTop: 2 },
  optPill: {
    paddingHorizontal: 8, paddingVertical: 4, borderRadius: 4,
    backgroundColor: theme.color.brand,
  },
  optPillText: { color: "#fff", fontSize: 9, fontWeight: "900", letterSpacing: 1.5 },
  cardTitle: { color: theme.color.text, fontSize: 14, fontWeight: "700", marginTop: 2 },
  cardWhy: { color: theme.color.textMuted, fontSize: 12, marginTop: 4, lineHeight: 18 },
  changeList: { flexDirection: "row", flexWrap: "wrap", gap: 5, marginTop: 10 },
  changeChip: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 7, paddingVertical: 4, borderRadius: 4,
    backgroundColor: theme.color.surface3,
  },
  changeText: { color: theme.color.textMuted, fontSize: 10, fontWeight: "700" },
  cardTime: { color: theme.color.textDim, fontSize: 10, marginTop: 8, fontWeight: "700" },
});
