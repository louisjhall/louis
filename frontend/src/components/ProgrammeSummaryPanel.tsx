/**
 * ProgrammeSummaryPanel — collapsible header panel for the workspace.
 *
 * §20 of the build brief. Shows goal + phase strip + event countdown +
 * adherence + planning-objective quotas.
 */
import React, { useEffect, useState } from "react";
import { View, Text, Pressable, StyleSheet, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Summary = {
  present: boolean;
  programme?: any;
  goal?: any;
  active_phase?: any;
  phase_strip?: any[];
  event_countdown?: any;
  adherence_pct?: number | null;
  adherence_window_days?: number;
  objective_quotas?: { discipline: string; target: number; scheduled: number; completed: number }[];
};

export function ProgrammeSummaryPanel({ clientId }: { clientId: string }) {
  const [data, setData] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    let mounted = true;
    (async () => {
      setLoading(true);
      try {
        const res = await api<Summary>(`/v2/coach/clients/${clientId}/programme/summary`);
        if (mounted) setData(res);
      } catch {
        if (mounted) setData({ present: false });
      } finally { if (mounted) setLoading(false); }
    })();
    return () => { mounted = false; };
  }, [clientId]);

  if (loading) return null;
  if (!data?.present) return null;

  return (
    <View style={styles.wrap} testID="programme-summary">
      <Pressable style={styles.head} onPress={() => setExpanded((v) => !v)}>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>{data.goal?.label || "Programme"}</Text>
          <View style={styles.subRow}>
            {data.active_phase?.label && (
              <Text style={styles.sub}>{data.active_phase.label}
                {data.active_phase.weeks ? ` · ${data.active_phase.weeks}w` : ""}</Text>
            )}
            {data.event_countdown?.days_to_event != null && (
              <Text style={[styles.sub, styles.subDot]}>
                · {data.event_countdown.days_to_event >= 0
                    ? `${data.event_countdown.weeks_to_event}w to ${humanise(data.event_countdown.event_type)}`
                    : `${Math.abs(data.event_countdown.days_to_event)}d after ${humanise(data.event_countdown.event_type)}`}
              </Text>
            )}
            {typeof data.adherence_pct === "number" && (
              <Text style={[styles.sub, styles.subDot]}> · adherence {data.adherence_pct}%</Text>
            )}
          </View>
        </View>
        <Ionicons name={expanded ? "chevron-up" : "chevron-down"} size={16} color={theme.color.textDim} />
      </Pressable>

      {/* Phase strip (always visible) */}
      {(data.phase_strip || []).length > 0 && (
        <View style={styles.phaseStripWrap}>
          {(data.phase_strip || []).map((p, i) => (
            <View key={p.id || i}
              style={[styles.phaseChip, p.current && styles.phaseChipActive,
                       p.status === "completed" && styles.phaseChipDone]}
            >
              <Text style={[styles.phaseChipText,
                              p.current && { color: "#000" }]} numberOfLines={1}>
                {p.label}{p.weeks ? ` · ${p.weeks}w` : ""}
              </Text>
            </View>
          ))}
        </View>
      )}

      {expanded && (
        <View style={styles.body}>
          {data.event_countdown && (
            <View style={styles.eventCard}>
              <Ionicons name="flag-outline" size={16} color={theme.color.brand} />
              <View style={{ flex: 1, marginLeft: 8 }}>
                <Text style={styles.eventKind}>{humanise(data.event_countdown.event_type)}</Text>
                <Text style={styles.eventMeta}>
                  {data.event_countdown.location ? `${JSON.stringify(data.event_countdown.location)} · ` : ""}
                  {data.event_countdown.date} · {data.event_countdown.days_to_event}d away
                </Text>
              </View>
            </View>
          )}

          {(data.objective_quotas || []).length > 0 && (
            <>
              <Text style={styles.section}>CURRENT PLANNING OBJECTIVES (7d)</Text>
              {(data.objective_quotas || []).map((q, i) => (
                <View key={i} style={styles.quotaRow}>
                  <Text style={styles.quotaDisc}>{q.discipline}</Text>
                  <View style={{ flex: 1 }} />
                  <Text style={styles.quotaTxt}>
                    {q.scheduled}/{q.target} scheduled
                    {q.completed > 0 ? ` · ${q.completed} done` : ""}
                  </Text>
                </View>
              ))}
            </>
          )}

          <Text style={styles.metaRow}>
            Timeline: {data.programme?.timeline_class || "—"} · Live v{data.programme?.live_plan_version || 0}
          </Text>
        </View>
      )}
    </View>
  );
}

function humanise(s?: string): string {
  if (!s) return "";
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

const styles = StyleSheet.create({
  wrap: {
    marginHorizontal: 12, marginTop: 8, marginBottom: 4,
    backgroundColor: theme.color.surface2, borderRadius: 8,
    borderWidth: 1, borderColor: theme.color.border, padding: 10,
  },
  head: { flexDirection: "row", alignItems: "center", gap: 8 },
  title: { color: theme.color.textHi, fontSize: 15, fontWeight: "800" },
  subRow: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", marginTop: 2 },
  sub: { color: theme.color.textDim, fontSize: 11 },
  subDot: { marginLeft: 3 },

  phaseStripWrap: { flexDirection: "row", flexWrap: "wrap", gap: 4, marginTop: 8 },
  phaseChip: {
    paddingHorizontal: 8, paddingVertical: 4, borderRadius: 12,
    backgroundColor: "#00000030", borderWidth: 1, borderColor: theme.color.border,
  },
  phaseChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  phaseChipDone: { backgroundColor: "#183020", borderColor: "#183020" },
  phaseChipText: { color: theme.color.textDim, fontSize: 11, fontWeight: "700" },

  body: { marginTop: 10 },
  section: { color: theme.color.textDim, fontSize: 11, letterSpacing: 1.5, fontWeight: "800", marginTop: 10, marginBottom: 6 },
  eventCard: {
    flexDirection: "row", alignItems: "center", padding: 8, borderRadius: 6,
    backgroundColor: "#00000030", borderWidth: 1, borderColor: theme.color.border,
  },
  eventKind: { color: theme.color.textHi, fontWeight: "700", fontSize: 12 },
  eventMeta: { color: theme.color.textDim, fontSize: 11, marginTop: 1 },
  quotaRow: { flexDirection: "row", alignItems: "center", paddingVertical: 4 },
  quotaDisc: { color: theme.color.textHi, fontSize: 12, fontWeight: "700" },
  quotaTxt: { color: theme.color.textDim, fontSize: 11 },
  metaRow: { color: theme.color.textDim, fontSize: 11, marginTop: 10, fontStyle: "italic" },
});
