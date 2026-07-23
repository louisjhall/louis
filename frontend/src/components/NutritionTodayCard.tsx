/**
 * NutritionTodayCard — Iter 94t (Phase 1)
 *
 * Compact card shown near the top of the client home. Displays today's
 * calories + protein progress against target, with a Log Food CTA. Renders
 * a friendly empty state when nothing is logged yet — never "content missing".
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Totals = { calories: number; protein_g: number; carbs_g?: number; fats_g?: number; count?: number };
type Target  = { calories?: number; protein_g?: number };
type Payload = { totals?: Totals; target?: Target; date_local?: string };

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n));
}
function fmt(n: number | undefined): string {
  if (n === undefined || n === null || isNaN(n as any)) return "0";
  return Math.round(n).toLocaleString();
}
function pct(v?: number, t?: number): number {
  if (!v || !t) return 0;
  return clamp(v / t, 0, 1);
}

export function NutritionTodayCard({ refreshKey = 0 }: { refreshKey?: number }) {
  const router = useRouter();
  const [data, setData] = useState<Payload | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<Payload>("/nutrition/today");
      setData(r || null);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load, refreshKey]);

  const totals = data?.totals || { calories: 0, protein_g: 0 };
  const target = data?.target || {};
  const nothingLogged = (totals.count ?? 0) === 0 && (totals.calories ?? 0) === 0;

  const openFood = () => router.push("/nutrition/log" as any);
  const openSummary = () => router.push("/nutrition" as any);

  if (loading && !data) {
    return (
      <View style={styles.card} testID="nutrition-card-loading">
        <ActivityIndicator color={theme.color.brand} />
      </View>
    );
  }

  return (
    <View style={styles.card} testID="nutrition-today-card">
      <View style={styles.head}>
        <Ionicons name="restaurant" size={16} color={theme.color.brand} />
        <Text style={styles.title}>TODAY&apos;S NUTRITION</Text>
        <Pressable onPress={openSummary} hitSlop={10} testID="nutrition-open">
          <Ionicons name="chevron-forward" size={16} color={theme.color.textMuted} />
        </Pressable>
      </View>

      {nothingLogged ? (
        <>
          <Text style={styles.empty}>No meals logged yet today.</Text>
          <Pressable onPress={openFood} style={styles.primaryBtn} testID="nutrition-log-first">
            <Ionicons name="add-circle" size={14} color="#fff" />
            <Text style={styles.primaryBtnT}>LOG FIRST MEAL</Text>
          </Pressable>
        </>
      ) : (
        <>
          <View style={styles.row}>
            <View style={{ flex: 1 }}>
              <Text style={styles.metricLbl}>CALORIES</Text>
              <Text style={styles.metricV}>
                {fmt(totals.calories)}
                {target.calories ? <Text style={styles.metricTgt}> / {fmt(target.calories)} kcal</Text> : <Text style={styles.metricTgt}> kcal</Text>}
              </Text>
              {target.calories ? (
                <View style={styles.barBg}><View style={[styles.barFill, { width: `${pct(totals.calories, target.calories) * 100}%` }]} /></View>
              ) : null}
            </View>
            <View style={{ flex: 1, marginLeft: 12 }}>
              <Text style={styles.metricLbl}>PROTEIN</Text>
              <Text style={styles.metricV}>
                {fmt(totals.protein_g)}
                {target.protein_g ? <Text style={styles.metricTgt}> / {fmt(target.protein_g)} g</Text> : <Text style={styles.metricTgt}> g</Text>}
              </Text>
              {target.protein_g ? (
                <View style={styles.barBg}><View style={[styles.barFill, { width: `${pct(totals.protein_g, target.protein_g) * 100}%`, backgroundColor: theme.color.brand }]} /></View>
              ) : null}
            </View>
          </View>

          <View style={styles.actions}>
            <Pressable onPress={openFood} style={[styles.btn, styles.primaryBtn]} testID="nutrition-log">
              <Ionicons name="add" size={14} color="#fff" />
              <Text style={styles.primaryBtnT}>LOG FOOD</Text>
            </Pressable>
            <Pressable onPress={openSummary} style={[styles.btn, styles.ghostBtn]} testID="nutrition-summary">
              <Text style={styles.ghostBtnT}>VIEW DAY</Text>
            </Pressable>
          </View>
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.color.border,
    padding: 12,
    marginBottom: 12,
    gap: 10,
  },
  head: { flexDirection: "row", alignItems: "center", gap: 8 },
  title: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 2, flex: 1 },

  empty: { color: theme.color.textMuted, fontSize: 12 },

  row: { flexDirection: "row", alignItems: "flex-start", marginTop: 4 },
  metricLbl: { color: theme.color.textMuted, fontSize: 9, fontWeight: "800", letterSpacing: 1.5, marginBottom: 3 },
  metricV: { color: theme.color.text, fontSize: 15, fontWeight: "900" },
  metricTgt: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700" },
  barBg: { marginTop: 6, height: 4, backgroundColor: theme.color.surface3, borderRadius: 2, overflow: "hidden" },
  barFill: { height: 4, backgroundColor: theme.color.green, borderRadius: 2 },

  actions: { flexDirection: "row", gap: 8, marginTop: 6 },
  btn: { flex: 1, flexDirection: "row", justifyContent: "center", alignItems: "center", gap: 4, padding: 10, borderRadius: 8 },
  primaryBtn: { backgroundColor: theme.color.brand },
  primaryBtnT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  ghostBtn: { borderWidth: 1, borderColor: theme.color.border },
  ghostBtnT: { color: theme.color.text, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
});
