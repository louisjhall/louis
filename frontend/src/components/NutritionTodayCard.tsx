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
import type { ThemeMode } from "@/src/lib/theme";
import { useThemeMode } from "@/src/hooks/use-theme-mode";

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
  label, current, target, unit, testID, styles,
}: {
  label: string;
  current: number;
  target?: number;
  unit: string;
  testID?: string;
  styles: any;
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
  const { mode } = useThemeMode();
  // Iter180 · Dynamic styles so the red card's text/icons/CTA repaint on
  // theme toggle. The user requires WHITE text/icons on the red card in
  // Light Mode and a BLACK "LOG FIRST MEAL" CTA button inside the card.
  const styles = useMemo(() => makeStyles(mode), [mode]);
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
        <Ionicons name="chevron-forward" size={16} color={theme.color.onRed} />
      </Pressable>

      {/* Calories */}
      <ProgressRow
        label="Calories"
        current={totals.calories || 0}
        target={target.calories}
        unit="kcal"
        testID="nutrition-calories-row"
        styles={styles}
      />

      {/* Protein */}
      <ProgressRow
        label="Protein"
        current={totals.protein_g || 0}
        target={target.protein_g}
        unit="g"
        testID="nutrition-protein-row"
        styles={styles}
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

// Iter180 · Style factory — swapped from static `StyleSheet.create` so the
// user-requested Pure Rule (WHITE text/icons on the red card) applies in
// Light Mode and the CTA button flips to BLACK inside the red card per
// spec. Dark Mode keeps its charcoal-card look via `surface2` and the
// same white text tokens.
function makeStyles(mode: ThemeMode) {
  const isLight = mode === "light";
  return StyleSheet.create({
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
    color: theme.color.onRed,
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
    color: theme.color.onRed,
    fontSize: 13,
  },
  metricLblStrong: {
    color: theme.color.onRed,
    fontSize: 13,
    fontWeight: "800",
  },
  metricSep: { fontSize: 13 },
  metricV: {
    color: theme.color.onRed,
    fontSize: 13,
    fontWeight: "800",
  },
  metricTgt: {
    color: theme.color.onRed,
    fontSize: 13,
    fontWeight: "600",
  },
  metricPctInline: {
    fontSize: 12,
    fontWeight: "800",
  },
  metricLeft: {
    color: theme.color.onRed,
    fontSize: 12,
    fontWeight: "600",
  },

  barBg: {
    height: 8,
    // Iter180 · Bar track: subtle white wash in Light Mode (on the red
    // card) so the empty portion of the progress bar is readable but not
    // aggressive. Dark Mode keeps the existing surface3 charcoal.
    backgroundColor: isLight ? "rgba(255,255,255,0.28)" : theme.color.surface3,
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
    color: theme.color.onRed,
    fontSize: 12,
    fontWeight: "600",
  },
  footMealsN: {
    color: theme.color.onRed,
    fontWeight: "900",
  },

  cta: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 8,
    // Iter180 · CTA button lives INSIDE the red nutrition card. Per user
    // spec: RED CARD → WHITE TEXT → BLACK ACTION BUTTON → WHITE TEXT.
    // Dark Mode keeps the classic brand-red primary button.
    backgroundColor: isLight ? "#000000" : theme.color.brand,
  },
  ctaT: {
    color: "#fff",
    fontSize: 11,
    fontWeight: "900",
    letterSpacing: 1.5,
  },
});
}
