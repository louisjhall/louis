/**
 * DualSessionCard — Iter 95a
 *
 * Optional home-screen card for short-haul crew on days that have a
 * genuine airport gap between duties. Nudges the client toward a short
 * "Airport Activation" without ever replacing their planned session.
 *
 * All copy is Louis-voiced. If today is not eligible, this component
 * renders nothing (returns null) so it never adds visual noise.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Exercise = { name: string; sets?: number; reps?: string; duration_sec?: number; rest_sec?: number; rpe?: number; notes?: string };
type Payload = {
  enabled: boolean;
  eligible: boolean;
  date?: string;
  reason?: string;
  session?: {
    title: string;
    duration_min: number;
    location: string;
    focus?: string;
    intensity?: string;
    warmup?: Exercise[];
    exercises?: Exercise[];
    cooldown?: Exercise[];
    rationale?: string;
  };
  coach?: { name?: string };
};

export function DualSessionCard({ refreshKey = 0 }: { refreshKey?: number }) {
  const [data, setData] = useState<Payload | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<Payload>("/dual-session/today");
      setData(r || null);
    } catch { /* silent — feature is optional */ } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load, refreshKey]);

  // Never render on loading or ineligibility — keeps home calm.
  if (loading) return null;
  if (!data || !data.enabled || !data.eligible || !data.session) return null;

  const s = data.session;
  const coachName = data.coach?.name || "Louis";

  return (
    <View style={styles.card} testID="dual-session-card">
      <View style={styles.headerRow}>
        <View style={styles.iconWrap}>
          <Ionicons name="airplane" size={18} color="#fff" />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.eyebrow}>OPTIONAL — TODAY</Text>
          <Text style={styles.title}>{s.title}</Text>
        </View>
        <View style={styles.durationChip}>
          <Ionicons name="time-outline" size={12} color={theme.color.text} />
          <Text style={styles.durationText}>{s.duration_min} min</Text>
        </View>
      </View>

      {data.reason ? (
        <Text style={styles.reason}>{data.reason}</Text>
      ) : null}

      <View style={styles.metaRow}>
        <View style={styles.metaChip}>
          <Ionicons name="location-outline" size={12} color={theme.color.textMuted} />
          <Text style={styles.metaText}>{s.location}</Text>
        </View>
        {s.intensity ? (
          <View style={styles.metaChip}>
            <Ionicons name="pulse-outline" size={12} color={theme.color.textMuted} />
            <Text style={styles.metaText}>{s.intensity}</Text>
          </View>
        ) : null}
      </View>

      <Pressable
        style={styles.ctaBtn}
        onPress={() => setExpanded((v) => !v)}
        testID="dual-session-expand-btn"
      >
        <Text style={styles.ctaText}>{expanded ? "Hide details" : "See what to do"}</Text>
        <Ionicons name={expanded ? "chevron-up" : "chevron-down"} size={16} color={theme.color.text} />
      </Pressable>

      {expanded ? (
        <View style={styles.detailBlock}>
          {s.warmup && s.warmup.length ? (
            <>
              <Text style={styles.sectionLabel}>Warm-up</Text>
              {s.warmup.map((e, i) => <ExerciseRow key={"w" + i} e={e} />)}
            </>
          ) : null}
          {s.exercises && s.exercises.length ? (
            <>
              <Text style={styles.sectionLabel}>Session</Text>
              {s.exercises.map((e, i) => <ExerciseRow key={"e" + i} e={e} />)}
            </>
          ) : null}
          {s.cooldown && s.cooldown.length ? (
            <>
              <Text style={styles.sectionLabel}>Cool-down</Text>
              {s.cooldown.map((e, i) => <ExerciseRow key={"c" + i} e={e} />)}
            </>
          ) : null}
          {s.rationale ? (
            <View style={styles.rationaleBox}>
              <Text style={styles.rationaleLabel}>Why this helps</Text>
              <Text style={styles.rationaleText}>{s.rationale}</Text>
            </View>
          ) : null}
          <Text style={styles.footNote}>
            This is an optional bonus from {coachName}. Your main session for tonight is unchanged.
          </Text>
        </View>
      ) : null}
    </View>
  );
}

function ExerciseRow({ e }: { e: Exercise }) {
  const bits: string[] = [];
  if (e.sets) bits.push(`${e.sets}×`);
  if (e.reps) bits.push(String(e.reps));
  else if (e.duration_sec) bits.push(`${Math.round(e.duration_sec)}s`);
  if (e.rpe) bits.push(`RPE ${e.rpe}`);
  return (
    <View style={styles.exRow}>
      <View style={styles.exBullet} />
      <View style={{ flex: 1 }}>
        <Text style={styles.exName}>{e.name}</Text>
        {bits.length ? <Text style={styles.exMeta}>{bits.join("  •  ")}</Text> : null}
        {e.notes ? <Text style={styles.exNote}>{e.notes}</Text> : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: theme.color.surface,
    borderRadius: theme.radius.lg,
    padding: theme.space.md,
    marginBottom: theme.space.md,
    borderWidth: 1,
    borderColor: theme.color.border,
  },
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    marginBottom: 8,
  },
  iconWrap: {
    width: 30,
    height: 30,
    borderRadius: 15,
    backgroundColor: "#3B82F6",
    alignItems: "center",
    justifyContent: "center",
  },
  eyebrow: {
    fontSize: 10,
    fontWeight: "700",
    color: "#3B82F6",
    letterSpacing: 0.8,
    marginBottom: 2,
  },
  title: {
    fontSize: 15,
    fontWeight: "700",
    color: theme.color.text,
  },
  durationChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: theme.color.bg,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 12,
  },
  durationText: {
    fontSize: 11,
    fontWeight: "600",
    color: theme.color.text,
  },
  reason: {
    fontSize: 13,
    color: theme.color.textMuted,
    lineHeight: 18,
    marginBottom: 10,
  },
  metaRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 10 },
  metaChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: theme.color.bg,
    borderRadius: 10,
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  metaText: { fontSize: 11, color: theme.color.textMuted, fontWeight: "500" },
  ctaBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    backgroundColor: theme.color.bg,
    borderWidth: 1,
    borderColor: theme.color.border,
    borderRadius: 10,
    paddingVertical: 10,
  },
  ctaText: { fontSize: 13, fontWeight: "600", color: theme.color.text },
  detailBlock: { marginTop: 12, gap: 8 },
  sectionLabel: {
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.8,
    color: theme.color.textMuted,
    marginTop: 8,
    marginBottom: 4,
  },
  exRow: {
    flexDirection: "row",
    gap: 8,
    paddingVertical: 4,
    alignItems: "flex-start",
  },
  exBullet: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: "#3B82F6",
    marginTop: 6,
  },
  exName: { fontSize: 13, color: theme.color.text, fontWeight: "600" },
  exMeta: { fontSize: 11, color: theme.color.textMuted, marginTop: 1 },
  exNote: { fontSize: 11, color: theme.color.textMuted, marginTop: 2, fontStyle: "italic" },
  rationaleBox: {
    backgroundColor: theme.color.bg,
    borderRadius: 10,
    padding: 10,
    marginTop: 8,
  },
  rationaleLabel: {
    fontSize: 10,
    fontWeight: "700",
    color: "#3B82F6",
    letterSpacing: 0.8,
    marginBottom: 4,
  },
  rationaleText: { fontSize: 12, color: theme.color.text, lineHeight: 17 },
  footNote: {
    fontSize: 11,
    color: theme.color.textMuted,
    fontStyle: "italic",
    marginTop: 10,
    textAlign: "center",
  },
});
