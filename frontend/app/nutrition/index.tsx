/**
 * CrewFit · Nutrition Centre · Home (Phase 1).
 *
 * Today's calorie / protein / carb / fat / hydration progress + Atlas tip,
 * quick-log entry, weekly summary card, and clearly-labelled navigation to
 * later-phase features (Barcode, Photo Scan, Travel Guidance).
 */
import React, { useCallback, useState } from "react";
import {
  ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet,
  Text, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useFocusEffect } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast } from "@/src/lib/ux";

type Today = {
  date_local: string;
  target: { calories?: number; protein_g?: number; carbs_g?: number; fats_g?: number; hydration_ml?: number; goal?: string; is_default?: boolean };
  totals: { calories: number; protein_g: number; carbs_g: number; fats_g: number; count: number };
  hydration_ml: number;
  remaining: { calories: number; protein_g: number; hydration_ml: number };
};

type Summary = {
  days_logged: number; days_total: number;
  avg_calories: number; avg_protein_g: number;
  per_day: { date: string; calories: number; protein_g: number }[];
};

export default function NutritionHome() {
  const router = useRouter();
  const [today, setToday] = useState<Today | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [tip, setTip] = useState<string>("");
  const [insight, setInsight] = useState<{ id: string; action: string; atlas_summary: string; coach_review_required: boolean } | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [hydrating, setHydrating] = useState(false);

  const load = useCallback(async () => {
    try {
      const [t, s] = await Promise.all([
        api<Today>("/nutrition/today"),
        api<Summary>("/nutrition/week-summary"),
      ]);
      setToday(t); setSummary(s);
      // Atlas tip is a separate async call — fire and forget.
      api<{ tip: string }>("/nutrition/atlas-tip").then((r) => setTip(r.tip)).catch(() => setTip(""));
      // Weekly insight — same fire-and-forget.
      api<{ insight: any }>("/nutrition/insights/latest").then((r) => setInsight(r.insight || null)).catch(() => setInsight(null));
    } catch (e: any) {
      toast(e?.message || "Load failed", "error");
    }
  }, []);

  useFocusEffect(useCallback(() => {
    setLoading(true);
    load().finally(() => setLoading(false));
  }, [load]));

  const onRefresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };

  const addWater = async (ml: number) => {
    setHydrating(true);
    try {
      const r = await api<{ amount_ml: number }>("/nutrition/hydration", { method: "POST", body: { amount_ml: ml } });
      setToday((prev) => prev ? { ...prev, hydration_ml: r.amount_ml, remaining: { ...prev.remaining, hydration_ml: Math.max(0, (prev.target.hydration_ml || 0) - r.amount_ml) } } : prev);
      if (ml > 0) toast(`+${ml}ml water`, "success");
    } catch (e: any) { toast(e?.message || "Failed", "error"); }
    finally { setHydrating(false); }
  };

  if (loading && !today) {
    return <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>;
  }

  const t = today;
  const targetCal = t?.target.calories || 2200;
  const targetPro = t?.target.protein_g || 140;
  const targetHyd = t?.target.hydration_ml || 2500;

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="chevron-back" size={24} color={theme.color.text} />
        </Pressable>
        <Text style={styles.headerT}>NUTRITION</Text>
        <Pressable onPress={() => router.push("/nutrition/history" as any)} hitSlop={12}>
          <Ionicons name="time-outline" size={20} color={theme.color.textMuted} />
        </Pressable>
      </View>

      <ScrollView
        contentContainerStyle={{ padding: 16, paddingBottom: 120, gap: 14 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.color.brand} />}>

        {/* Header row — goal + date */}
        <View style={styles.headRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.dateT}>{formatDate(t?.date_local)}</Text>
            <Text style={styles.goalT}>{goalLabel(t?.target.goal)} · {(t?.target.is_default ? "Atlas default" : "Coach set").toUpperCase()}</Text>
          </View>
          <Pressable onPress={() => router.push("/nutrition/targets" as any)} style={styles.headBtn}>
            <Ionicons name="options-outline" size={13} color={theme.color.brand} />
            <Text style={styles.headBtnT}>TARGETS</Text>
          </Pressable>
        </View>

        {/* Big calorie ring + protein ring */}
        <View style={styles.ringsRow}>
          <MetricCard
            label="CALORIES"
            value={t?.totals.calories || 0}
            target={targetCal}
            unit="kcal"
            color={theme.color.brand}
          />
          <MetricCard
            label="PROTEIN"
            value={t?.totals.protein_g || 0}
            target={targetPro}
            unit="g"
            color={theme.color.green}
          />
        </View>

        {/* Carbs + fats + hydration */}
        <View style={styles.smallRow}>
          <SmallMetric label="CARBS" value={t?.totals.carbs_g || 0} unit="g" target={t?.target.carbs_g} />
          <SmallMetric label="FATS" value={t?.totals.fats_g || 0} unit="g" target={t?.target.fats_g} />
          <SmallMetric label="HYDRATION" value={t?.hydration_ml || 0} unit="ml" target={targetHyd} />
        </View>

        {/* Hydration quick actions */}
        <View style={styles.hydCard}>
          <View style={styles.hydCardHead}>
            <Ionicons name="water" size={18} color="#3B82F6" />
            <Text style={styles.hydCardT}>HYDRATION</Text>
            <Text style={styles.hydCardV}>{(t?.hydration_ml || 0)} / {targetHyd}ml</Text>
          </View>
          <View style={styles.hydBtnRow}>
            {[250, 500, 750].map((ml) => (
              <Pressable key={ml} onPress={() => addWater(ml)} disabled={hydrating}
                style={[styles.hydBtn, hydrating && { opacity: 0.4 }]}>
                <Text style={styles.hydBtnT}>+{ml}ml</Text>
              </Pressable>
            ))}
            <Pressable onPress={() => addWater(-250)} disabled={hydrating}
              style={[styles.hydBtn, styles.hydBtnGhost, hydrating && { opacity: 0.4 }]}>
              <Ionicons name="remove" size={14} color={theme.color.textMuted} />
            </Pressable>
          </View>
        </View>

        {/* Atlas tip */}
        <View style={styles.tipCard}>
          <View style={styles.tipHead}>
            <Ionicons name="sparkles" size={13} color={theme.color.brand} />
            <Text style={styles.tipHeadT}>ATLAS INSIGHT</Text>
          </View>
          <Text style={styles.tipT}>{tip || "Analysing today\u2019s nutrition\u2026"}</Text>
        </View>

        {/* Weekly Insight card */}
        {insight ? (
          <Pressable onPress={() => router.push("/nutrition/insights" as any)} style={styles.weeklyCard}
            testID="weekly-insight-card">
            <View style={styles.weeklyHead}>
              <View style={styles.weeklyIcon}>
                <Ionicons name="analytics" size={13} color={theme.color.brand} />
              </View>
              <Text style={styles.weeklyHeadT}>WEEKLY ATLAS INSIGHT</Text>
              <View style={[styles.weeklyBadge, actionBadgeColor(insight.action)]}>
                <Text style={styles.weeklyBadgeT}>{actionLabel(insight.action)}</Text>
              </View>
            </View>
            <Text style={styles.weeklyT} numberOfLines={3}>{insight.atlas_summary}</Text>
            <View style={styles.weeklyFoot}>
              {insight.coach_review_required ? (
                <View style={styles.weeklyPending}>
                  <Ionicons name="hourglass" size={10} color={theme.color.amber} />
                  <Text style={styles.weeklyPendingT}>AWAITING LOUIS</Text>
                </View>
              ) : <View />}
              <Text style={styles.weeklyLink}>VIEW ALL <Ionicons name="chevron-forward" size={11} color={theme.color.brand} /></Text>
            </View>
          </Pressable>
        ) : null}

        {/* Quick actions */}
        <Text style={styles.sect}>LOG A MEAL</Text>
        <View style={styles.actionsGrid}>
          <ActionBtn icon="restaurant" label="MANUAL LOG" onPress={() => router.push("/nutrition/log" as any)} testID="nutr-manual" primary />
          <ActionBtn icon="search" label="FOOD SEARCH" onPress={() => router.push("/nutrition/food-search" as any)} testID="nutr-search" />
          <ActionBtn icon="barcode-outline" label="BARCODE" onPress={() => router.push("/nutrition/barcode" as any)} testID="nutr-barcode" />
          <ActionBtn icon="camera" label="PHOTO SCAN" onPress={() => router.push("/nutrition/photo-scan" as any)} testID="nutr-photo" />
          <ActionBtn icon="heart" label="FAVOURITES" onPress={() => router.push("/nutrition/favourites" as any)} testID="nutr-favs" />
        </View>

        {/* Travel section */}
        <Text style={styles.sect}>TRAVEL &amp; ROSTER</Text>
        <View style={styles.actionsGrid}>
          <ActionBtn icon="airplane" label="TRAVEL FOOD" onPress={() => router.push("/nutrition/travel" as any)} testID="nutr-travel" />
          <ActionBtn icon="help-circle" label="ATLAS DECIDE" onPress={() => router.push("/nutrition/decision" as any)} testID="nutr-decide" />
          <ActionBtn icon="business" label="AIRPORT MODE" onPress={() => router.push("/nutrition/airport" as any)} testID="nutr-airport" />
          <ActionBtn icon="time" label="MEAL TIMING" onPress={() => router.push("/nutrition/timing" as any)} testID="nutr-timing" />
        </View>

        {/* Weekly summary */}
        <Text style={styles.sect}>WEEKLY SUMMARY</Text>
        <View style={styles.summaryCard}>
          <View style={styles.summaryTop}>
            <View style={{ flex: 1 }}>
              <Text style={styles.summaryK}>LOGGED</Text>
              <Text style={styles.summaryV}>{summary?.days_logged || 0} / {summary?.days_total || 7} days</Text>
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.summaryK}>AVG KCAL</Text>
              <Text style={styles.summaryV}>{summary?.avg_calories || 0}</Text>
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.summaryK}>AVG PROTEIN</Text>
              <Text style={styles.summaryV}>{summary?.avg_protein_g || 0}g</Text>
            </View>
          </View>
          {/* Bars per day */}
          <View style={styles.barsRow}>
            {(summary?.per_day || []).map((d) => {
              const pct = Math.min(100, Math.round(((d.calories || 0) / (targetCal || 1)) * 100));
              return (
                <View key={d.date} style={styles.barCol}>
                  <View style={styles.barTrack}>
                    <View style={[styles.barFill, { height: `${pct}%` }]} />
                  </View>
                  <Text style={styles.barT}>{new Date(d.date).toLocaleDateString(undefined, { weekday: "short" }).slice(0, 1).toUpperCase()}</Text>
                </View>
              );
            })}
          </View>
        </View>

        <Text style={styles.disclaimer}>
          Targets are coaching estimates and can be adjusted by Louis.
          {"\n"}Atlas is a nutrition coaching assistant, not a medical tool.
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}

/* -------------------------------------------------------------------------- */

function MetricCard({ label, value, target, unit, color }: { label: string; value: number; target: number; unit: string; color: string; }) {
  const pct = Math.min(1, target ? value / target : 0);
  return (
    <View style={styles.metricCard}>
      <View style={styles.metricRingBg}>
        <View style={[styles.metricRingFill, { backgroundColor: color, width: `${pct * 100}%` }]} />
      </View>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={styles.metricValue}>{typeof value === "number" ? Math.round(value) : value}<Text style={styles.metricUnit}> / {target}{unit}</Text></Text>
      <Text style={[styles.metricPct, { color }]}>{Math.round(pct * 100)}%</Text>
    </View>
  );
}

function SmallMetric({ label, value, target, unit }: { label: string; value: number; target?: number; unit: string; }) {
  return (
    <View style={styles.smallCard}>
      <Text style={styles.smallLabel}>{label}</Text>
      <Text style={styles.smallValue}>{Math.round(value)}{unit}</Text>
      {target ? <Text style={styles.smallTarget}>of {target}{unit}</Text> : null}
    </View>
  );
}

function ActionBtn({ icon, label, onPress, primary, soon, testID }: { icon: any; label: string; onPress: () => void; primary?: boolean; soon?: boolean; testID?: string; }) {
  return (
    <Pressable onPress={onPress} style={[styles.action, primary && styles.actionPri]} testID={testID}>
      <Ionicons name={icon} size={20} color={primary ? "#fff" : theme.color.brand} />
      <Text style={[styles.actionT, primary && { color: "#fff" }]}>{label}</Text>
      {soon ? <View style={styles.soonPill}><Text style={styles.soonT}>SOON</Text></View> : null}
    </Pressable>
  );
}

/* -------------------------------------------------------------------------- */

function formatDate(d?: string) {
  if (!d) return "TODAY";
  return new Date(d).toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" }).toUpperCase();
}

function goalLabel(g?: string) {
  const m: Record<string, string> = {
    fat_loss: "Fat loss", muscle_gain: "Muscle gain",
    endurance: "Endurance", general_health: "General health", recovery: "Recovery",
  };
  return m[g || ""] || "General health";
}

function actionLabel(a: string) {
  const m: Record<string, string> = {
    keep: "KEEP", simplify: "SIMPLIFY", protein_focus: "PROTEIN FOCUS",
    adjust_calories: "ADJUST", add_travel_strategy: "TRAVEL", flag_coach_review: "REVIEW",
  };
  return m[a] || a.toUpperCase();
}

function actionBadgeColor(a: string) {
  if (a === "keep") return { backgroundColor: theme.color.green };
  if (a === "flag_coach_review") return { backgroundColor: "#c94a4a" };
  if (a === "protein_focus" || a === "adjust_calories") return { backgroundColor: theme.color.brand };
  if (a === "simplify") return { backgroundColor: theme.color.amber };
  if (a === "add_travel_strategy") return { backgroundColor: "#3B82F6" };
  return { backgroundColor: theme.color.textDim };
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 14, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  headerT: { color: theme.color.text, fontSize: 14, letterSpacing: 3, fontWeight: "900", fontFamily: theme.font.display },

  headRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  dateT: { color: theme.color.text, fontSize: 18, fontWeight: "900", letterSpacing: 0.5, fontFamily: theme.font.display },
  goalT: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1.6, marginTop: 3, fontFamily: theme.font.textSemi },
  headBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand },
  headBtnT: { color: theme.color.brand, fontSize: 9, fontWeight: "900", letterSpacing: 1 },

  ringsRow: { flexDirection: "row", gap: 10 },
  metricCard: { flex: 1, padding: 14, borderRadius: 14, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, gap: 6 },
  metricRingBg: { height: 5, borderRadius: 3, backgroundColor: theme.color.surface3, overflow: "hidden", marginBottom: 8 },
  metricRingFill: { height: "100%" },
  metricLabel: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 2, fontWeight: "900", fontFamily: theme.font.textSemi },
  metricValue: { color: theme.color.text, fontSize: 22, fontWeight: "900", fontFamily: theme.font.display, letterSpacing: 0.3 },
  metricUnit: { color: theme.color.textDim, fontSize: 11, fontWeight: "700", letterSpacing: 0.5 },
  metricPct: { fontSize: 11, fontWeight: "900", letterSpacing: 1 },

  smallRow: { flexDirection: "row", gap: 8 },
  smallCard: { flex: 1, padding: 10, borderRadius: 10, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, alignItems: "center" },
  smallLabel: { color: theme.color.textMuted, fontSize: 9, fontWeight: "900", letterSpacing: 1.5, fontFamily: theme.font.textSemi },
  smallValue: { color: theme.color.text, fontSize: 15, fontWeight: "900", marginTop: 4, fontFamily: theme.font.display },
  smallTarget: { color: theme.color.textDim, fontSize: 9, marginTop: 2 },

  hydCard: { padding: 12, borderRadius: 12, backgroundColor: "#0A1420", borderWidth: 1, borderColor: "#183045" },
  hydCardHead: { flexDirection: "row", alignItems: "center", gap: 8 },
  hydCardT: { color: "#3B82F6", fontSize: 10, fontWeight: "900", letterSpacing: 2, flex: 1, fontFamily: theme.font.textSemi },
  hydCardV: { color: theme.color.text, fontSize: 12, fontWeight: "800" },
  hydBtnRow: { flexDirection: "row", gap: 6, marginTop: 10 },
  hydBtn: { flex: 1, paddingVertical: 10, alignItems: "center", borderRadius: 8, backgroundColor: "#183045", borderWidth: 1, borderColor: "#264C6D" },
  hydBtnT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 0.5 },
  hydBtnGhost: { flex: 0, width: 40, backgroundColor: theme.color.surface3, borderColor: theme.color.border },

  tipCard: { padding: 14, borderRadius: 12, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand },
  tipHead: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 6 },
  tipHeadT: { color: theme.color.brand, fontSize: 10, letterSpacing: 2, fontWeight: "900", fontFamily: theme.font.textSemi },
  tipT: { color: theme.color.text, fontSize: 13, lineHeight: 20, fontFamily: theme.font.text },

  weeklyCard: { padding: 14, borderRadius: 12, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.brand, gap: 8 },
  weeklyHead: { flexDirection: "row", alignItems: "center", gap: 8 },
  weeklyIcon: { width: 24, height: 24, borderRadius: 12, backgroundColor: theme.color.brandTint, alignItems: "center", justifyContent: "center" },
  weeklyHeadT: { color: theme.color.brand, fontSize: 10, letterSpacing: 2, fontWeight: "900", flex: 1, fontFamily: theme.font.textSemi },
  weeklyBadge: { paddingHorizontal: 6, paddingVertical: 3, borderRadius: 4 },
  weeklyBadgeT: { color: "#fff", fontSize: 8, letterSpacing: 0.8, fontWeight: "900" },
  weeklyT: { color: theme.color.text, fontSize: 13, lineHeight: 19, fontFamily: theme.font.text },
  weeklyFoot: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 4 },
  weeklyPending: { flexDirection: "row", alignItems: "center", gap: 3, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4, backgroundColor: "#1F1608", borderWidth: 1, borderColor: theme.color.amber },
  weeklyPendingT: { color: theme.color.amber, fontSize: 8, letterSpacing: 0.8, fontWeight: "900" },
  weeklyLink: { color: theme.color.brand, fontSize: 10, letterSpacing: 1, fontWeight: "900" },

  sect: { color: theme.color.brand, fontSize: 10, letterSpacing: 2, fontWeight: "900", marginTop: 8, fontFamily: theme.font.textSemi },
  actionsGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  action: { flexBasis: "48%", flexGrow: 1, paddingVertical: 14, paddingHorizontal: 12, borderRadius: 12, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, flexDirection: "row", alignItems: "center", gap: 8 },
  actionPri: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  actionT: { color: theme.color.text, fontSize: 11, fontWeight: "900", letterSpacing: 1, fontFamily: theme.font.textSemi, flex: 1 },
  soonPill: { paddingHorizontal: 5, paddingVertical: 2, borderRadius: 4, backgroundColor: theme.color.surface3 },
  soonT: { color: theme.color.textMuted, fontSize: 8, fontWeight: "900", letterSpacing: 0.8 },

  summaryCard: { padding: 14, borderRadius: 12, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, gap: 10 },
  summaryTop: { flexDirection: "row", gap: 8 },
  summaryK: { color: theme.color.textMuted, fontSize: 9, letterSpacing: 1.5, fontWeight: "900", fontFamily: theme.font.textSemi },
  summaryV: { color: theme.color.text, fontSize: 14, fontWeight: "900", marginTop: 2, fontFamily: theme.font.display },
  barsRow: { flexDirection: "row", justifyContent: "space-between", height: 60, alignItems: "flex-end" },
  barCol: { flex: 1, alignItems: "center", gap: 4 },
  barTrack: { width: 8, height: 40, borderRadius: 4, backgroundColor: theme.color.surface3, justifyContent: "flex-end", overflow: "hidden" },
  barFill: { width: "100%", backgroundColor: theme.color.brand, borderRadius: 4 },
  barT: { color: theme.color.textDim, fontSize: 9, fontWeight: "800" },

  disclaimer: { color: theme.color.textDim, fontSize: 10, textAlign: "center", lineHeight: 15, marginTop: 12, fontStyle: "italic" },
});
