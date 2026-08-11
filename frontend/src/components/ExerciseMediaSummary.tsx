/**
 * ExerciseMediaSummary — dashboard tile that summarises how many exercises
 * scheduled for real clients still need artwork / video / coaching points /
 * approval. Tapping the card opens the Exercise Library with a filter
 * pre-applied.
 *
 * Only rendered when there is at least one item to act on — invisible on
 * a clean dashboard, glanceable when something needs attention.
 */
import React, { useEffect, useState } from "react";
import { View, Text, Pressable, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { useAuth } from "@/src/lib/auth";

type Summary = {
  needed_this_week: number;
  needed_tomorrow: number;
  missing_videos: number;
  ready_for_review: number;
};

export function ExerciseMediaSummary() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [data, setData] = useState<Summary | null>(null);

  useEffect(() => {
    // Wait for auth to hydrate — the api() call is 401 without a token.
    if (authLoading || !user) return;
    let cancel = false;
    (async () => {
      try {
        const r = await api<Summary>("/coach/exercise-media-summary");
        if (!cancel) setData(r);
      } catch {
        // silent — non-admins get 403; unauth gets 401. Card just stays hidden.
      }
    })();
    return () => { cancel = true; };
  }, [authLoading, user]);

  if (!data) return null;
  const total = data.needed_this_week + data.missing_videos + data.ready_for_review;
  if (total === 0) return null;

  const openLibrary = (filter?: string) => {
    const q = filter ? `?filter=${filter}` : "";
    router.push(`/coach/exercise-content${q}` as any);
  };

  return (
    <Pressable style={styles.card} onPress={() => openLibrary("needed_week")} testID="exercise-media-summary">
      <View style={styles.headerRow}>
        <View style={styles.iconBox}>
          <Ionicons name="images" size={18} color={theme.color.brand} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>EXERCISE MEDIA</Text>
          <Text style={styles.subtitle}>Just-in-time approvals for real client workouts</Text>
        </View>
        <Ionicons name="chevron-forward" size={18} color={theme.color.textDim} />
      </View>
      <View style={styles.metricsRow}>
        <Metric
          testID="ems-tomorrow"
          count={data.needed_tomorrow}
          label={`Needed ${data.needed_tomorrow === 1 ? "tomorrow" : "tomorrow"}`}
          tone={data.needed_tomorrow > 0 ? "danger" : "muted"}
          onPress={() => openLibrary("needed_tomorrow")}
        />
        <Metric
          testID="ems-week"
          count={data.needed_this_week}
          label={`Needed this week`}
          tone={data.needed_this_week > 0 ? "warn" : "muted"}
          onPress={() => openLibrary("needed_week")}
        />
        <Metric
          testID="ems-videos"
          count={data.missing_videos}
          label={`Missing video`}
          tone="muted"
          onPress={() => openLibrary("no_video")}
        />
        <Metric
          testID="ems-review"
          count={data.ready_for_review}
          label={`Ready for review`}
          tone={data.ready_for_review > 0 ? "ok" : "muted"}
          onPress={() => openLibrary("ready_review")}
        />
      </View>
      <Text style={styles.cta}>REVIEW EXERCISE MEDIA →</Text>
    </Pressable>
  );
}

function Metric({
  count, label, tone, onPress, testID,
}: {
  count: number; label: string; tone: "danger" | "warn" | "ok" | "muted";
  onPress: () => void; testID?: string;
}) {
  const color =
    tone === "danger" ? theme.color.red || "#DC2626" :
    tone === "warn" ? theme.color.amber || "#F59E0B" :
    tone === "ok" ? theme.color.green || "#22c55e" :
    theme.color.textMuted;
  return (
    <Pressable onPress={onPress} style={styles.metric} testID={testID}>
      <Text style={[styles.metricCount, { color }]}>{count}</Text>
      <Text style={styles.metricLabel} numberOfLines={2}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    marginTop: 16, padding: 14,
    backgroundColor: theme.color.surface2, borderRadius: 14,
    borderWidth: 1, borderColor: theme.color.border,
  },
  headerRow: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 12 },
  iconBox: {
    width: 38, height: 38, borderRadius: 10, backgroundColor: theme.color.brandTint,
    alignItems: "center", justifyContent: "center",
  },
  title: { color: theme.color.text, fontWeight: "900", letterSpacing: 1.2, fontSize: 12 },
  subtitle: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },
  metricsRow: { flexDirection: "row", gap: 8 },
  metric: {
    flex: 1, backgroundColor: theme.color.surface, borderRadius: 10, padding: 10,
    borderWidth: 1, borderColor: theme.color.border, alignItems: "center", gap: 4,
    minHeight: 76,
  },
  metricCount: { fontSize: 20, fontWeight: "900" },
  metricLabel: { color: theme.color.textMuted, fontSize: 11, textAlign: "center", fontWeight: "700" },
  cta: { color: theme.color.brand, fontWeight: "900", fontSize: 11, letterSpacing: 1.5, marginTop: 12, textAlign: "right" },
});
