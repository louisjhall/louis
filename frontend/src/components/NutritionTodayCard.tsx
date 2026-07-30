/**
 * NutritionTodayCard — Iter 129g compact refresh.
 *
 * Feedback: previous card ate ~1/3 of vertical screen. This version keeps
 * the progress bars (strongest signal) but shaves ~30% height by:
 *   • removing the large per-metric icon circles
 *   • inlining the % with the label (no separate 0% row)
 *   • collapsing the "meals logged" row and the "Log Meal" CTA into a
 *     single final row (label left, chip on the right)
 *
 * NO nutrition logic changes — same `/nutrition/today` payload, same
 * logging flow (`/nutrition/pick`), same targets, same totals.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Totals = { calories: number; protein_g: number; carbs_g?: number; fats_g?: number; count?: number };
type Target  = { calories?: number; protein_g?: number };
type Payload = {
  totals?: Totals;
  target?: Target;
  date_local?: string;
  remaining?: { calories?: number; protein_g?: number };
};

function clamp(n: number, lo: number, hi: number): number { return Math.max(lo, Math.min(hi, n)); }
function fmt(n: number | undefined): string {
  if (n === undefined || n === null || isNaN(n as any)) return "0";
  return Math.round(n).toLocaleString();
}
function pct01(v?: number, t?: number): number {
  if (!v || !t || t <= 0) return 0;
  return clamp(v / t, 0, 1);
}

/**
 * Bar colour rules:
 *   • no target or nothing logged → neutral brand
 *   • over target (>110%)         → red
 *   • on track (≥ 60% consumed)   → green
 *   • otherwise                   → brand
 */
function barColor(current: number, target?: number): string {
  if (!target || current <= 0) return theme.color.brand;
  const p = current / target;
  if (p > 1.1) return theme.color.red;
  if (p >= 0.6) return theme.color.green;
  return theme.color.brand;
}

function ProgressRow({
  label, current, target, unit, testID,
}: {
  label: string;
  current: number;
  target?: number;
  unit: string;
  testID?: string;
}) {
  const p = pct01(current, target);
  const pctLabel = target ? `${Math.round(p * 100)}%` : "";
  const left = target ? Math.max(0, Math.round(target - current)) : 0;
  const color = barColor(current, target);
  const hasData = (current || 0) > 0;
  return (
    <View style={styles.metricBlock} testID={testID}>
      <View style={styles.metricHead}>
        <Text style={styles.metricLbl} numberOfLines={1}>
          <Text style={styles.metricLblStrong}>{label}</Text>
          <Text style={styles.metricSep}>  </Text>
          <Text style={styles.metricV}>{fmt(current)}</Text>
          {target ? <Text style={styles.metricTgt}>{` / ${fmt(target)} ${unit}`}</Text> : <Text style={styles.metricTgt}>{` ${unit}`}</Text>}
          {target && hasData ? <Text style={[styles.metricPctInline, { color }]}>{`  ·  ${pctLabel}`}</Text> : null}
        </Text>
        {target ? (
          <Text style={styles.metricLeft} numberOfLines={1}>{fmt(left)} {unit} left</Text>
        ) : null}
      </View>
      <View style={styles.barBg} accessibilityRole="progressbar"
        accessibilityValue={{ min: 0, max: 100, now: Math.round(p * 100) }}>
        <View style={[styles.barFill, { width: `${p * 100}%`, backgroundColor: color }]} />
      </View>
    </View>
  );
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

  const totals = data?.totals || { calories: 0, protein_g: 0, count: 0 };
  const target = data?.target || {};
  const mealsCount = totals.count ?? 0;
  const nothingLogged = mealsCount === 0 && (totals.calories ?? 0) === 0;

  const openLog = () => router.push("/nutrition/pick" as any);
  const openSummary = () => router.push("/nutrition" as any);

  const cta = useMemo(() => nothingLogged ? "LOG FIRST MEAL" : "LOG MEAL", [nothingLogged]);

  if (loading && !data) {
    return (
      <View style={styles.card} testID="nutrition-card-loading">
        <ActivityIndicator color={theme.color.brand} />
      </View>
    );
  }

  return (
    <View style={styles.card} testID="nutrition-today-card">
      {/* Header — click opens Nutrition detail */}
      <Pressable onPress={openSummary} style={styles.head} testID="nutrition-open">
        <Text style={styles.title}>TODAY&apos;S NUTRITION</Text>
        <Ionicons name="chevron-forward" size={16} color={theme.color.textMuted} />
      </Pressable>

      {/* Calories */}
      <ProgressRow
        label="Calories"
        current={totals.calories || 0}
        target={target.calories}
        unit="kcal"
        testID="nutrition-calories-row"
      />

      {/* Protein */}
      <ProgressRow
        label="Protein"
        current={totals.protein_g || 0}
        target={target.protein_g}
        unit="g"
        testID="nutrition-protein-row"
      />

      {/* Combined meals + CTA row */}
      <View style={styles.footRow}>
        <Pressable onPress={openSummary} hitSlop={6} style={styles.footLeft} testID="nutrition-meals-row">
          <Text style={styles.footMeals}>
            <Text style={styles.footMealsN}>{mealsCount}</Text>{" "}
            {mealsCount === 1 ? "meal logged" : "meals logged"}
          </Text>
        </Pressable>
        <Pressable onPress={openLog} style={styles.cta} testID="nutrition-log">
          <Ionicons name="add" size={14} color="#fff" />
          <Text style={styles.ctaT}>{cta}</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.color.border,
    paddingHorizontal: 12,
    paddingTop: 10,
    paddingBottom: 10,
    marginBottom: 12,
    gap: 10,
  },
  head: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  title: {
    color: theme.color.brand,
    fontSize: 11,
    fontWeight: "900",
    letterSpacing: 2,
    flex: 1,
  },

  metricBlock: { gap: 6 },
  metricHead: {
    flexDirection: "row",
    alignItems: "baseline",
    justifyContent: "space-between",
    gap: 8,
  },
  metricLbl: {
    flex: 1,
    color: theme.color.text,
    fontSize: 13,
  },
  metricLblStrong: {
    color: theme.color.text,
    fontSize: 13,
    fontWeight: "800",
  },
  metricSep: { fontSize: 13 },
  metricV: {
    color: theme.color.text,
    fontSize: 13,
    fontWeight: "800",
  },
  metricTgt: {
    color: theme.color.textMuted,
    fontSize: 13,
    fontWeight: "600",
  },
  metricPctInline: {
    fontSize: 12,
    fontWeight: "800",
  },
  metricLeft: {
    color: theme.color.textMuted,
    fontSize: 12,
    fontWeight: "600",
  },

  barBg: {
    height: 8,
    backgroundColor: theme.color.surface3,
    borderRadius: 4,
    overflow: "hidden",
  },
  barFill: { height: 8, borderRadius: 4 },

  footRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
    marginTop: 2,
  },
  footLeft: { flex: 1 },
  footMeals: {
    color: theme.color.textMuted,
    fontSize: 12,
    fontWeight: "600",
  },
  footMealsN: {
    color: theme.color.text,
    fontWeight: "900",
  },

  cta: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 8,
    backgroundColor: theme.color.brand,
  },
  ctaT: {
    color: "#fff",
    fontSize: 11,
    fontWeight: "900",
    letterSpacing: 1.5,
  },
});
