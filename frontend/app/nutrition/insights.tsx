/**
 * Nutrition · Adaptive Weekly Insights (Phase 5).
 *
 * Latest insight card + history list. If none exists for this week, offer a
 * "Generate now" CTA that pings /nutrition/insights/generate.
 */
import React, { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useFocusEffect } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast } from "@/src/lib/ux";

type Insight = {
  id: string; week_start: string; week_end: string;
  action: string; atlas_summary: string; main_issue: string;
  suggested_action: string;
  target_change_suggestion?: { calories: number | null; protein_g: number | null; notes: string };
  coach_review_required: boolean;
  confidence: string;
  status: string;
  created_at: string;
  analytics?: { days_logged: number; days_total: number; avg_calories: number; avg_protein_g: number; low_protein_days: number };
};

const ACTION_LABEL: Record<string, string> = {
  keep: "KEEP THE PLAN", simplify: "SIMPLIFY TRACKING",
  protein_focus: "PROTEIN FOCUS", adjust_calories: "ADJUST CALORIES",
  add_travel_strategy: "TRAVEL STRATEGY", flag_coach_review: "FLAGGED FOR REVIEW",
};

const ACTION_ICON: Record<string, any> = {
  keep: "checkmark-circle", simplify: "flash",
  protein_focus: "barbell", adjust_calories: "options",
  add_travel_strategy: "airplane", flag_coach_review: "flag",
};

export default function InsightsScreen() {
  const router = useRouter();
  const [latest, setLatest] = useState<Insight | null>(null);
  const [history, setHistory] = useState<Insight[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [generating, setGenerating] = useState(false);

  const load = useCallback(async () => {
    try {
      const [l, h] = await Promise.all([
        api<{ insight: Insight | null }>("/nutrition/insights/latest"),
        api<{ insights: Insight[] }>("/nutrition/insights/mine?limit=12"),
      ]);
      setLatest(l.insight); setHistory(h.insights || []);
    } catch (e: any) { toast(e?.message || "Failed", "error"); }
  }, []);

  useFocusEffect(useCallback(() => { setLoading(true); load().finally(() => setLoading(false)); }, [load]));

  const generateNow = async () => {
    setGenerating(true);
    try {
      const r = await api<{ insight: Insight; cached: boolean }>("/nutrition/insights/generate", {
        method: "POST", body: { force: true },
      });
      setLatest(r.insight);
      toast(r.cached ? "Insight refreshed" : "New insight ready", "success");
      await load();
    } catch (e: any) { toast(e?.message || "Failed", "error"); }
    finally { setGenerating(false); }
  };

  const previous = history.filter((h) => h.id !== latest?.id);

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="chevron-back" size={24} color={theme.color.text} />
        </Pressable>
        <Text style={styles.headerT}>ATLAS INSIGHTS</Text>
        <Pressable onPress={generateNow} hitSlop={12} disabled={generating} testID="insight-refresh">
          {generating ? <ActivityIndicator size="small" color={theme.color.brand} />
            : <Ionicons name="refresh" size={18} color={theme.color.brand} />}
        </Pressable>
      </View>

      {loading && !latest ? (
        <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: 16, gap: 14, paddingBottom: 40 }}
          refreshControl={<RefreshControl refreshing={refreshing}
            onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }}
            tintColor={theme.color.brand} />}>
          {latest ? <BigCard insight={latest} /> : (
            <View style={styles.emptyCard}>
              <Ionicons name="sparkles" size={30} color={theme.color.brand} />
              <Text style={styles.emptyT}>No insight yet this week.</Text>
              <Text style={styles.emptySub}>Atlas needs a bit of nutrition data to give you a meaningful weekly analysis.</Text>
              <Pressable onPress={generateNow} disabled={generating}
                style={[styles.genBtn, generating && { opacity: 0.5 }]} testID="insight-generate">
                {generating ? <ActivityIndicator color="#fff" /> : (
                  <>
                    <Ionicons name="sparkles" size={13} color="#fff" />
                    <Text style={styles.genBtnT}>GENERATE ANYWAY</Text>
                  </>
                )}
              </Pressable>
            </View>
          )}

          {previous.length ? (
            <>
              <Text style={styles.sect}>PREVIOUS INSIGHTS</Text>
              {previous.map((it) => (
                <View key={it.id} style={styles.historyCard}>
                  <View style={styles.historyHead}>
                    <View style={[styles.actionBadge, actionColor(it.action)]}>
                      <Ionicons name={ACTION_ICON[it.action] || "sparkles"} size={10} color="#fff" />
                      <Text style={styles.actionBadgeT}>{ACTION_LABEL[it.action] || it.action.toUpperCase()}</Text>
                    </View>
                    <Text style={styles.historyDate}>{formatWeek(it.week_start, it.week_end)}</Text>
                  </View>
                  <Text style={styles.historyMain}>{it.main_issue}</Text>
                  {it.status && it.status !== "info" && it.status !== "pending" ? (
                    <View style={styles.statusPill}>
                      <Text style={styles.statusPillT}>{it.status.toUpperCase()}</Text>
                    </View>
                  ) : null}
                </View>
              ))}
            </>
          ) : null}

          <Text style={styles.disclaimer}>
            Weekly Atlas insights are coaching guidance, not medical advice. Louis reviews anything flagged.
          </Text>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

function BigCard({ insight }: { insight: Insight }) {
  const label = ACTION_LABEL[insight.action] || insight.action.toUpperCase();
  const icon = ACTION_ICON[insight.action] || "sparkles";
  const tcs = insight.target_change_suggestion;
  return (
    <View style={styles.bigCard}>
      <View style={styles.bigHead}>
        <View style={[styles.actionBadge, actionColor(insight.action)]}>
          <Ionicons name={icon} size={11} color="#fff" />
          <Text style={styles.actionBadgeT}>{label}</Text>
        </View>
        <Text style={styles.weekT}>{formatWeek(insight.week_start, insight.week_end)}</Text>
      </View>
      <Text style={styles.summary}>{insight.atlas_summary}</Text>
      <View style={styles.divider} />
      <View style={styles.blockRow}>
        <Ionicons name="alert-circle" size={13} color={theme.color.amber} />
        <View style={{ flex: 1 }}>
          <Text style={styles.blockLabel}>MAIN ISSUE</Text>
          <Text style={styles.blockText}>{insight.main_issue}</Text>
        </View>
      </View>
      {insight.suggested_action ? (
        <View style={styles.blockRow}>
          <Ionicons name="compass" size={13} color={theme.color.brand} />
          <View style={{ flex: 1 }}>
            <Text style={styles.blockLabel}>SUGGESTED ACTION</Text>
            <Text style={styles.blockText}>{insight.suggested_action}</Text>
          </View>
        </View>
      ) : null}
      {tcs && (tcs.calories || tcs.protein_g) ? (
        <View style={styles.tcs}>
          <Ionicons name="options" size={13} color={theme.color.brand} />
          <View style={{ flex: 1 }}>
            <Text style={styles.blockLabel}>ATLAS TARGET SUGGESTION</Text>
            <Text style={styles.blockText}>
              {tcs.calories ? `Calories → ${tcs.calories} kcal` : ""}
              {tcs.calories && tcs.protein_g ? " · " : ""}
              {tcs.protein_g ? `Protein → ${tcs.protein_g}g` : ""}
            </Text>
            <Text style={styles.tcsPending}>
              {insight.coach_review_required ? "Awaiting Louis's approval" : "Optional — coach will review"}
            </Text>
          </View>
        </View>
      ) : null}
      {insight.analytics ? (
        <>
          <View style={styles.divider} />
          <View style={styles.stats}>
            <Stat label="LOGGED" value={`${insight.analytics.days_logged}/${insight.analytics.days_total}`} />
            <Stat label="AVG KCAL" value={String(insight.analytics.avg_calories)} />
            <Stat label="AVG P" value={`${insight.analytics.avg_protein_g}g`} />
            <Stat label="LOW-P DAYS" value={String(insight.analytics.low_protein_days)} />
          </View>
        </>
      ) : null}
    </View>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.statCol}>
      <Text style={styles.statLabel}>{label}</Text>
      <Text style={styles.statVal}>{value}</Text>
    </View>
  );
}

function actionColor(action: string) {
  if (action === "keep") return { backgroundColor: theme.color.green };
  if (action === "flag_coach_review") return { backgroundColor: "#c94a4a" };
  if (action === "protein_focus" || action === "adjust_calories") return { backgroundColor: theme.color.brand };
  if (action === "simplify") return { backgroundColor: theme.color.amber };
  if (action === "add_travel_strategy") return { backgroundColor: "#3B82F6" };
  return { backgroundColor: theme.color.textDim };
}

function formatWeek(ws: string, we: string) {
  try {
    const s = new Date(ws), e = new Date(we);
    return `${s.toLocaleDateString(undefined, { month: "short", day: "numeric" })} – ${e.toLocaleDateString(undefined, { month: "short", day: "numeric" })}`.toUpperCase();
  } catch { return ws; }
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 14, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  headerT: { color: theme.color.text, fontSize: 14, letterSpacing: 3, fontWeight: "900", fontFamily: theme.font.display },

  bigCard: { padding: 18, borderRadius: 14, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand, gap: 10 },
  bigHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  actionBadge: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6 },
  actionBadgeT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1 },
  weekT: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1.5, fontWeight: "800" },
  summary: { color: theme.color.text, fontSize: 15, lineHeight: 22, fontFamily: theme.font.text },
  divider: { height: 1, backgroundColor: theme.color.divider, marginVertical: 4 },
  blockRow: { flexDirection: "row", gap: 10, alignItems: "flex-start" },
  blockLabel: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1.5, fontWeight: "900" },
  blockText: { color: theme.color.text, fontSize: 13, lineHeight: 18, marginTop: 2, fontFamily: theme.font.text },
  tcs: { flexDirection: "row", gap: 10, padding: 12, borderRadius: 10, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.brand },
  tcsPending: { color: theme.color.brand, fontSize: 11, marginTop: 4, letterSpacing: 0.5, fontWeight: "800" },
  stats: { flexDirection: "row", gap: 8 },
  statCol: { flex: 1, padding: 8, borderRadius: 8, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, alignItems: "center" },
  statLabel: { color: theme.color.textDim, fontSize: 11, letterSpacing: 1, fontWeight: "900" },
  statVal: { color: theme.color.text, fontSize: 13, fontWeight: "900", marginTop: 3, fontFamily: theme.font.display },

  emptyCard: { padding: 30, borderRadius: 14, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, alignItems: "center", gap: 8 },
  emptyT: { color: theme.color.text, fontSize: 15, fontWeight: "900", fontFamily: theme.font.display },
  emptySub: { color: theme.color.textMuted, fontSize: 12, textAlign: "center", lineHeight: 18, fontFamily: theme.font.text },
  genBtn: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 16, paddingVertical: 10, borderRadius: 8, backgroundColor: theme.color.brand, marginTop: 8 },
  genBtnT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },

  sect: { color: theme.color.brand, fontSize: 11, letterSpacing: 2, fontWeight: "900", marginTop: 8, fontFamily: theme.font.textSemi },
  historyCard: { padding: 12, borderRadius: 10, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, gap: 6 },
  historyHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  historyDate: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1, fontWeight: "800" },
  historyMain: { color: theme.color.text, fontSize: 12, lineHeight: 18, fontFamily: theme.font.text },
  statusPill: { alignSelf: "flex-start", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4, backgroundColor: theme.color.surface3 },
  statusPillT: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 0.8, fontWeight: "900" },

  disclaimer: { color: theme.color.textDim, fontSize: 11, textAlign: "center", fontStyle: "italic", lineHeight: 15, paddingHorizontal: 6, marginTop: 6 },
});
