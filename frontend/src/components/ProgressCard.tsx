/**
 * ProgressCard — client home summary of the latest weekly progression snapshot.
 * Tapping opens /your-progress full-screen with history + reasons.
 * Hidden entirely if the client has no snapshot yet.
 */
import { useEffect, useState, useCallback } from "react";
import { View, Text, Pressable, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Snapshot = {
  status: "progressing_well" | "maintain" | "reduce_load" | "deload";
  status_label: string;
  reason: string;
  metrics: {
    sessions_planned: number;
    sessions_completed: number;
    adherence_pct: number;
    avg_rpe: number | null;
    key_missed: number;
  };
  week_start: string;
  week_end: string;
};

const STATUS_COLOR: Record<Snapshot["status"], { bg: string; fg: string; icon: keyof typeof Ionicons.glyphMap }> = {
  progressing_well: { bg: "rgba(34,197,94,0.12)",  fg: "#16A34A", icon: "trending-up" },
  maintain:         { bg: "rgba(163,24,46,0.10)",  fg: theme.color.brand, icon: "remove" },
  reduce_load:      { bg: "rgba(245,158,11,0.15)", fg: "#B45309", icon: "trending-down" },
  deload:           { bg: "rgba(59,130,246,0.15)", fg: "#1D4ED8", icon: "moon" },
};

export function ProgressCard({ refreshKey }: { refreshKey?: number }) {
  const router = useRouter();
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const s = await api<Snapshot | Record<string, never>>("/progress/current").catch(() => ({} as any));
      if (s && (s as any).status) setSnap(s as Snapshot);
      else setSnap(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load, refreshKey]);

  if (loading) return null;
  if (!snap) return null;

  const color = STATUS_COLOR[snap.status] || STATUS_COLOR.maintain;
  const adherence = Math.round(snap.metrics.adherence_pct);
  const rpe = snap.metrics.avg_rpe;

  return (
    <Pressable
      testID="progress-card"
      onPress={() => router.push("/your-progress")}
      style={[styles.card, { borderLeftColor: color.fg }]}
    >
      <View style={styles.top}>
        <View style={styles.left}>
          <View style={[styles.pill, { backgroundColor: color.bg }]}>
            <Ionicons name={color.icon} size={12} color={color.fg} />
            <Text style={[styles.pillText, { color: color.fg }]}>{snap.status_label}</Text>
          </View>
          <Text style={styles.title}>YOUR PROGRESS · LAST WEEK</Text>
        </View>
        <Ionicons name="chevron-forward" size={16} color={theme.color.textMuted} />
      </View>

      <Text style={styles.reason} numberOfLines={2}>{snap.reason}</Text>

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
          <Text style={styles.mVal}>{rpe != null ? rpe.toFixed(1) : "—"}</Text>
          <Text style={styles.mLabel}>AVG RPE</Text>
        </View>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: theme.color.surface2,
    borderRadius: 12,
    padding: 14,
    borderLeftWidth: 4,
    marginBottom: 12,
  },
  top: { flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between" },
  left: { flex: 1 },
  pill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    alignSelf: "flex-start",
    paddingHorizontal: 8, paddingVertical: 3,
    borderRadius: 999,
    marginBottom: 6,
  },
  pillText: { fontSize: 10, fontWeight: "800", letterSpacing: 0.8 },
  title: {
    fontSize: 11, fontWeight: "700", color: theme.color.textMuted, letterSpacing: 0.5, marginBottom: 6,
  },
  reason: {
    fontSize: 13, color: theme.color.text, lineHeight: 18, marginBottom: 12,
  },
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
});
