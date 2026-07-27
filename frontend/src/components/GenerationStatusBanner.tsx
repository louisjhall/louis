/**
 * GenerationStatusBanner — progressive pipeline stages for Roster→Plan build.
 *
 * §24-25 of the build brief. Polls /generation/status while the pipeline
 * is running; auto-hides when idle and no recent errors.
 */
import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Stage = {
  stage: string;
  state: "pending" | "in_progress" | "done" | "error";
  at?: string;
  detail?: string | number;
};

const LABELS: Record<string, string> = {
  roster_uploaded:    "Roster uploaded",
  roster_parsed:      "Roster parsed",
  schedule_created:   "Schedule created",
  planning_programme: "Planning programme",
  generating_workouts:"Generating workouts",
  validating:         "Validating",
  ready_for_review:   "Ready for review",
  published:          "Published",
};

export function GenerationStatusBanner({
  clientId, month,
}: {
  clientId: string;
  month?: string;
}) {
  const [data, setData] = useState<{ overall: string; stages: Stage[] } | null>(null);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    let mounted = true;
    let interval: any;
    const tick = async () => {
      try {
        const res = await api<{ overall: string; stages: Stage[] }>(
          `/v2/coach/clients/${clientId}/generation/status${month ? `?month=${month}` : ""}`
        );
        if (!mounted) return;
        setData(res);
      } catch {
        /* silently ignore */
      }
    };
    tick();
    interval = setInterval(tick, 3500);
    return () => { mounted = false; clearInterval(interval); };
  }, [clientId, month]);

  if (!data) return null;
  const hasActivity = data.stages.some((s) => s.state === "in_progress" || s.state === "error");
  const showPublished = data.stages.find((s) => s.stage === "published" && s.state === "done");
  if (!hasActivity && !data.stages.some((s) => s.state === "pending" && s.stage !== "published")) {
    // Nothing pending & nothing running — show only if there's an error to surface.
    if (!data.stages.some((s) => s.state === "error")) return null;
  }
  if (collapsed) {
    return (
      <Pressable style={styles.collapsed} onPress={() => setCollapsed(false)} testID="genstatus-open">
        <Ionicons name="git-branch-outline" size={14} color={theme.color.textDim} />
        <Text style={styles.collapsedText}>Pipeline status</Text>
        <Ionicons name="chevron-down" size={14} color={theme.color.textDim} />
      </Pressable>
    );
  }

  return (
    <View style={styles.wrap} testID="genstatus-banner">
      <View style={styles.head}>
        <Text style={styles.title}>PIPELINE STATUS</Text>
        <Pressable onPress={() => setCollapsed(true)} testID="genstatus-close">
          <Ionicons name="chevron-up" size={16} color={theme.color.textDim} />
        </Pressable>
      </View>
      <View style={styles.stagesRow}>
        {data.stages.map((s, i) => (
          <View key={s.stage} style={styles.stageCol}>
            <View style={styles.stageDotRow}>
              {i > 0 && <View style={[styles.rail, { backgroundColor: railColor(data.stages[i - 1]) }]} />}
              <View style={[styles.dot, { backgroundColor: dotColor(s) }]}>
                {s.state === "in_progress" ? (
                  <ActivityIndicator size="small" color="#000" />
                ) : s.state === "done" ? (
                  <Ionicons name="checkmark" size={12} color="#000" />
                ) : s.state === "error" ? (
                  <Ionicons name="alert" size={12} color="#000" />
                ) : null}
              </View>
              {i < data.stages.length - 1 && (
                <View style={[styles.rail, { backgroundColor: railColor(s) }]} />
              )}
            </View>
            <Text style={styles.stageLabel} numberOfLines={2}>{LABELS[s.stage] || s.stage}</Text>
            {s.detail !== undefined && s.detail !== null && (
              <Text style={styles.stageDetail} numberOfLines={2}>{String(s.detail)}</Text>
            )}
          </View>
        ))}
      </View>
    </View>
  );
}

function dotColor(s: Stage): string {
  switch (s.state) {
    case "done":         return "#61c982";
    case "in_progress":  return "#f5b543";
    case "error":        return "#ff6b6b";
    default:             return "#3a3a45";
  }
}
function railColor(s: Stage): string {
  switch (s.state) {
    case "done":  return "#61c98255";
    case "error": return "#ff6b6b55";
    default:      return "#3a3a4555";
  }
}

const styles = StyleSheet.create({
  collapsed: {
    marginHorizontal: 12, marginTop: 8, marginBottom: 4,
    backgroundColor: theme.color.surface2, borderRadius: 6, borderWidth: 1, borderColor: theme.color.border,
    flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 10, paddingVertical: 6,
  },
  collapsedText: { flex: 1, color: theme.color.textDim, fontSize: 11 },
  wrap: {
    marginHorizontal: 12, marginTop: 8, marginBottom: 4,
    backgroundColor: theme.color.surface2, borderRadius: 8,
    borderWidth: 1, borderColor: theme.color.border, padding: 10,
  },
  head: { flexDirection: "row", alignItems: "center", marginBottom: 10 },
  title: { flex: 1, color: theme.color.textDim, fontSize: 10, letterSpacing: 1.5, fontWeight: "800" },
  stagesRow: { flexDirection: "row", justifyContent: "space-between", gap: 4 },
  stageCol: { flex: 1, alignItems: "center" },
  stageDotRow: { flexDirection: "row", alignItems: "center", width: "100%", height: 24 },
  rail: { flex: 1, height: 2 },
  dot: { width: 20, height: 20, borderRadius: 10, alignItems: "center", justifyContent: "center" },
  stageLabel: {
    color: theme.color.textHi, fontSize: 10, letterSpacing: 0.5, fontWeight: "700",
    textAlign: "center", marginTop: 6,
  },
  stageDetail: { color: theme.color.textDim, fontSize: 10, textAlign: "center", marginTop: 2 },
});
