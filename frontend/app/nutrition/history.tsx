/**
 * Nutrition · History (last 7 days).
 */
import React, { useCallback, useState } from "react";
import { ActivityIndicator, FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useFocusEffect } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { confirm, toast } from "@/src/lib/ux";

type Log = { id: string; date_local: string; meal_type: string; food_name: string; calories: number; protein_g: number; carbs_g: number; fats_g: number; portion?: string; notes?: string; roster_context?: string; created_at: string; };

export default function NutritionHistory() {
  const router = useRouter();
  const [logs, setLogs] = useState<Log[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api<{ logs: Log[] }>("/nutrition/logs?days=7");
      setLogs(r.logs);
    } catch (e: any) { toast(e?.message || "Load failed", "error"); }
  }, []);

  useFocusEffect(useCallback(() => { setLoading(true); load().finally(() => setLoading(false)); }, [load]));

  const removeLog = async (id: string) => {
    const ok = await confirm({ title: "Delete this log?", destructive: true, confirmLabel: "DELETE" });
    if (!ok) return;
    try {
      await api(`/nutrition/logs/${id}`, { method: "DELETE" });
      setLogs((prev) => prev.filter((x) => x.id !== id));
      toast("Removed", "success");
    } catch (e: any) { toast(e?.message || "Failed", "error"); }
  };

  // Group by date
  const grouped: { date: string; rows: Log[]; total: number }[] = [];
  const byDate: Record<string, Log[]> = {};
  logs.forEach((l) => { byDate[l.date_local] = byDate[l.date_local] || []; byDate[l.date_local].push(l); });
  Object.keys(byDate).sort((a, b) => b.localeCompare(a)).forEach((d) => {
    grouped.push({ date: d, rows: byDate[d], total: byDate[d].reduce((sum, r) => sum + (r.calories || 0), 0) });
  });

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="chevron-back" size={24} color={theme.color.text} />
        </Pressable>
        <Text style={styles.headerT}>HISTORY · 7 DAYS</Text>
        <View style={{ width: 24 }} />
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>
      ) : logs.length === 0 ? (
        <View style={styles.center}>
          <Ionicons name="restaurant-outline" size={40} color={theme.color.textDim} />
          <Text style={styles.empty}>No meals logged yet.\nTap the plate below to add your first.</Text>
          <Pressable onPress={() => router.push("/nutrition/log" as any)} style={styles.emptyBtn}>
            <Text style={styles.emptyBtnT}>LOG A MEAL</Text>
          </Pressable>
        </View>
      ) : (
        <FlatList
          data={grouped}
          keyExtractor={(g) => g.date}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} tintColor={theme.color.brand} />}
          contentContainerStyle={{ padding: 16, gap: 14 }}
          renderItem={({ item }) => (
            <View>
              <View style={styles.dayHead}>
                <Text style={styles.dayHeadT}>{formatDate(item.date)}</Text>
                <Text style={styles.dayHeadTotal}>{item.total} kcal</Text>
              </View>
              {item.rows.map((row) => (
                <View key={row.id} style={styles.card}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.cardName}>{row.food_name}</Text>
                    <Text style={styles.cardMeta}>{row.meal_type.replace(/_/g, " ").toUpperCase()}{row.portion ? " · " + row.portion : ""}{row.roster_context ? " · " + row.roster_context.replace(/_/g, " ").toUpperCase() : ""}</Text>
                    <View style={styles.macroPills}>
                      <MacroPill label="kcal" value={row.calories} />
                      <MacroPill label="P" value={`${Math.round(row.protein_g)}g`} />
                      <MacroPill label="C" value={`${Math.round(row.carbs_g)}g`} />
                      <MacroPill label="F" value={`${Math.round(row.fats_g)}g`} />
                    </View>
                  </View>
                  <Pressable onPress={() => removeLog(row.id)} hitSlop={10} style={styles.trash}>
                    <Ionicons name="trash-outline" size={16} color="#c94a4a" />
                  </Pressable>
                </View>
              ))}
            </View>
          )}
        />
      )}
    </SafeAreaView>
  );
}

function MacroPill({ label, value }: { label: string; value: any }) {
  return (
    <View style={styles.macroPill}>
      <Text style={styles.macroPillT}><Text style={styles.macroPillK}>{label} </Text>{value}</Text>
    </View>
  );
}

function formatDate(d: string) {
  const today = new Date().toISOString().slice(0, 10);
  const yest = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  if (d === today) return "TODAY";
  if (d === yest) return "YESTERDAY";
  return new Date(d).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" }).toUpperCase();
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 14, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  headerT: { color: theme.color.text, fontSize: 14, letterSpacing: 3, fontWeight: "900", fontFamily: theme.font.display },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 20, gap: 12 },
  empty: { color: theme.color.textMuted, textAlign: "center", fontStyle: "italic", fontSize: 13 },
  emptyBtn: { paddingHorizontal: 20, paddingVertical: 12, borderRadius: 8, backgroundColor: theme.color.brand, marginTop: 10 },
  emptyBtnT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  dayHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 8 },
  dayHeadT: { color: theme.color.brand, fontSize: 11, letterSpacing: 2, fontWeight: "900", fontFamily: theme.font.textSemi },
  dayHeadTotal: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1.5, fontWeight: "800" },
  card: { flexDirection: "row", padding: 12, borderRadius: 10, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, marginBottom: 6, alignItems: "center" },
  cardName: { color: theme.color.text, fontSize: 14, fontWeight: "800", fontFamily: theme.font.textSemi },
  cardMeta: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1, marginTop: 2, fontWeight: "700" },
  macroPills: { flexDirection: "row", gap: 6, marginTop: 6, flexWrap: "wrap" },
  macroPill: { paddingHorizontal: 6, paddingVertical: 3, borderRadius: 4, backgroundColor: theme.color.surface3 },
  macroPillT: { color: theme.color.text, fontSize: 11, fontWeight: "800" },
  macroPillK: { color: theme.color.textDim, fontWeight: "700" },
  trash: { padding: 8 },
});
