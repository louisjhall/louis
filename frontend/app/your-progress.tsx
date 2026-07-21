/**
 * /your-progress — Full-screen weekly progression history.
 *
 * Shows the client's last 8 weeks of progression snapshots as a timeline with:
 *   * status badge (PROGRESSING / STEADY / PULL BACK / DELOAD)
 *   * reason string (client-facing)
 *   * metrics (sessions completed, adherence, avg RPE, key sessions missed)
 * The header shows the current week + a "Recompute" button (calls POST /api/progress/recompute).
 */
import { useCallback, useEffect, useState } from "react";
import {
  View, Text, ScrollView, Pressable, StyleSheet, ActivityIndicator, RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast } from "@/src/lib/ux";

type Snapshot = {
  status: "progressing_well" | "maintain" | "reduce_load" | "deload";
  status_label: string;
  reason: string;
  coach_note?: string;
  metrics: {
    sessions_planned: number;
    sessions_completed: number;
    adherence_pct: number;
    avg_rpe: number | null;
    high_rpe_count: number;
    very_high_rpe_count: number;
    key_missed: number;
  };
  week_start: string;
  week_end: string;
  week_key: string;
  computed_at?: string;
};

const STATUS_COLOR: Record<Snapshot["status"], { bg: string; fg: string; icon: keyof typeof import("@expo/vector-icons").Ionicons.glyphMap }> = {
  progressing_well: { bg: "rgba(34,197,94,0.12)",  fg: "#16A34A", icon: "trending-up" },
  maintain:         { bg: "rgba(163,24,46,0.10)",  fg: theme.color.brand, icon: "remove" },
  reduce_load:      { bg: "rgba(245,158,11,0.15)", fg: "#B45309", icon: "trending-down" },
  deload:           { bg: "rgba(59,130,246,0.15)", fg: "#1D4ED8", icon: "moon" },
};

const fmtWeek = (s: string, e: string) => {
  const opt: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
  try {
    return `${new Date(s).toLocaleDateString("en-GB", opt)} → ${new Date(e).toLocaleDateString("en-GB", opt)}`;
  } catch {
    return `${s} → ${e}`;
  }
};

export default function YourProgress() {
  const router = useRouter();
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [recomputing, setRecomputing] = useState(false);

  const load = useCallback(async () => {
    try {
      const rows = await api<Snapshot[]>("/progress/history?weeks=8").catch(() => []);
      setSnapshots(Array.isArray(rows) ? rows : []);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const recompute = async () => {
    setRecomputing(true);
    try {
      await api("/progress/recompute", { method: "POST" });
      toast("Progress recomputed", "success");
      await load();
    } catch (e: any) {
      toast(e?.message || "Couldn't recompute", "error");
    } finally {
      setRecomputing(false);
    }
  };

  const onRefresh = () => { setRefreshing(true); load(); };

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} style={styles.backBtn} testID="your-progress-back">
            <Ionicons name="chevron-back" size={22} color={theme.color.text} />
          </Pressable>
          <View style={{ flex: 1 }}>
            <Text style={styles.hTitle}>YOUR PROGRESS</Text>
            <Text style={styles.hSub}>Last 8 weeks · reactive to your sessions</Text>
          </View>
          <Pressable
            testID="progress-recompute-btn"
            onPress={recompute}
            disabled={recomputing}
            style={[styles.recomputeBtn, recomputing && { opacity: 0.5 }]}
          >
            {recomputing ? (
              <ActivityIndicator size="small" color={theme.color.brand} />
            ) : (
              <Ionicons name="refresh" size={14} color={theme.color.brand} />
            )}
          </Pressable>
        </View>
      </SafeAreaView>

      {loading ? (
        <View style={{ padding: theme.space.xl, alignItems: "center" }}>
          <ActivityIndicator color={theme.color.brand} />
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 60 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.color.brand} />}
        >
          {snapshots.length === 0 ? (
            <View style={styles.empty} testID="your-progress-empty">
              <Ionicons name="analytics-outline" size={32} color={theme.color.textMuted} />
              <Text style={styles.emptyTitle}>No snapshots yet</Text>
              <Text style={styles.emptyBody}>
                Complete a full training week and CrewFit will calculate how you&apos;re progressing.
                {"\n"}Louis will review the snapshot and adjust next week&apos;s load.
              </Text>
            </View>
          ) : (
            snapshots.map((snap) => {
              const color = STATUS_COLOR[snap.status] || STATUS_COLOR.maintain;
              const adherence = Math.round(snap.metrics.adherence_pct);
              return (
                <View
                  key={snap.week_key || `${snap.week_start}-${snap.week_end}`}
                  style={[styles.snapshot, { borderLeftColor: color.fg }]}
                  testID={`snap-${snap.week_key || snap.week_start}`}
                >
                  <View style={styles.snapHead}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.snapDates}>{fmtWeek(snap.week_start, snap.week_end)}</Text>
                      <View style={[styles.pill, { backgroundColor: color.bg, marginTop: 4 }]}>
                        <Ionicons name={color.icon} size={12} color={color.fg} />
                        <Text style={[styles.pillText, { color: color.fg }]}>{snap.status_label}</Text>
                      </View>
                    </View>
                  </View>
                  <Text style={styles.reason}>{snap.reason}</Text>

                  <View style={styles.metrics}>
                    <View style={styles.metric}>
                      <Text style={styles.mVal}>
                        {snap.metrics.sessions_completed}<Text style={styles.mSlash}>/{snap.metrics.sessions_planned}</Text>
                      </Text>
                      <Text style={styles.mLabel}>SESSIONS</Text>
                    </View>
                    <View style={styles.divider} />
                    <View style={styles.metric}>
                      <Text style={styles.mVal}>{adherence}%</Text>
                      <Text style={styles.mLabel}>ADHERENCE</Text>
                    </View>
                    <View style={styles.divider} />
                    <View style={styles.metric}>
                      <Text style={styles.mVal}>{snap.metrics.avg_rpe != null ? snap.metrics.avg_rpe.toFixed(1) : "—"}</Text>
                      <Text style={styles.mLabel}>AVG RPE</Text>
                    </View>
                    {snap.metrics.key_missed > 0 ? (
                      <>
                        <View style={styles.divider} />
                        <View style={styles.metric}>
                          <Text style={[styles.mVal, { color: "#B45309" }]}>{snap.metrics.key_missed}</Text>
                          <Text style={styles.mLabel}>KEY MISSED</Text>
                        </View>
                      </>
                    ) : null}
                  </View>
                </View>
              );
            })
          )}

          <Text style={styles.footNote}>
            CrewFit reviews your session data at the end of each week. Adherence, effort (RPE), and missed key sessions all feed into next week&apos;s plan. Louis has full visibility on every snapshot.
          </Text>
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: {
    flexDirection: "row", alignItems: "center", padding: theme.space.lg, gap: 12,
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  backBtn: {
    width: 36, height: 36, borderRadius: 18,
    alignItems: "center", justifyContent: "center",
    backgroundColor: theme.color.surface2,
  },
  hTitle: { fontSize: 14, fontWeight: "700", color: theme.color.text, letterSpacing: 0.5 },
  hSub: { fontSize: 12, color: theme.color.textMuted, marginTop: 2 },
  recomputeBtn: {
    width: 36, height: 36, borderRadius: 18,
    alignItems: "center", justifyContent: "center",
    backgroundColor: theme.color.brandTint,
    borderWidth: 1, borderColor: theme.color.brand,
  },

  empty: {
    alignItems: "center",
    padding: theme.space.xxl,
    gap: theme.space.md,
  },
  emptyTitle: { fontSize: 14, fontWeight: "700", color: theme.color.text, letterSpacing: 0.5 },
  emptyBody: { fontSize: 13, color: theme.color.textMuted, textAlign: "center", lineHeight: 19 },

  snapshot: {
    backgroundColor: theme.color.surface2,
    borderRadius: 12,
    padding: 14,
    borderLeftWidth: 4,
    marginBottom: 12,
  },
  snapHead: { flexDirection: "row", alignItems: "flex-start", marginBottom: 8 },
  snapDates: { fontSize: 12, fontWeight: "700", color: theme.color.textMuted, letterSpacing: 0.5 },
  pill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    alignSelf: "flex-start",
    paddingHorizontal: 8, paddingVertical: 3,
    borderRadius: 999,
  },
  pillText: { fontSize: 10, fontWeight: "800", letterSpacing: 0.8 },
  reason: { fontSize: 13, color: theme.color.text, lineHeight: 19, marginBottom: 12 },
  metrics: {
    flexDirection: "row", alignItems: "center",
    backgroundColor: theme.color.surface,
    borderRadius: 8,
    paddingVertical: 10,
  },
  metric: { flex: 1, alignItems: "center" },
  divider: { width: 1, height: 30, backgroundColor: theme.color.border },
  mVal: { fontSize: 18, fontWeight: "800", color: theme.color.text },
  mSlash: { fontSize: 12, color: theme.color.textMuted, fontWeight: "600" },
  mLabel: { fontSize: 10, fontWeight: "700", color: theme.color.textMuted, letterSpacing: 0.5, marginTop: 2 },

  footNote: {
    marginTop: theme.space.lg,
    fontSize: 11,
    color: theme.color.textDim,
    textAlign: "center",
    lineHeight: 16,
  },
});
