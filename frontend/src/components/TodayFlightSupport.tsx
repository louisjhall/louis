/**
 * TodayFlightSupport — client-facing Aviation Support block on Home.
 *
 * Iter 117 · Phase B.
 * Renders interventions returned by /api/client/today as a separate section
 * from Training. NEVER treats these as programme workouts.
 */
import React, { useState } from "react";
import { View, Text, StyleSheet, Pressable, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";
import { api } from "@/src/lib/api";

type Intervention = {
  id: string;
  date: string;
  protocol_key: string;
  title: string;
  family: string;
  intensity: string;
  duration_min: number;
  cues?: string[];
  equipment?: string[];
  blocks?: any[];
  bundle_title?: string | null;
  bundle_key?: string | null;
  is_bundle?: boolean;
  sub_interventions?: Intervention[];
  trigger_reason?: string;
  completion_status?: "not_started" | "completed" | "skipped" | "partial";
};

export function TodayFlightSupport({
  snapshot, onRefresh,
}: {
  snapshot: any | null;
  onRefresh?: () => Promise<void> | void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  if (!snapshot) return null;
  const enabled = snapshot.auto_flight_support_enabled !== false;
  const items: Intervention[] = snapshot.flight_support || [];
  const role: string = snapshot.role || "role_unknown";

  // Role-unknown → show a subtle prompt for the coach to set it (client
  // can't self-serve but should at least understand why it's absent).
  if (role === "role_unknown") {
    return (
      <View style={s.wrap} testID="flight-support-role-unknown">
        <Text style={s.header}>FLIGHT SUPPORT</Text>
        <Text style={s.body}>
          Ask your coach to set your aviation role so CrewFit can prescribe
          the right operational support (e.g. pre/post-flight movement).
        </Text>
      </View>
    );
  }

  if (!enabled) return null;
  if (items.length === 0) return null;

  const complete = async (it: Intervention, status: "completed" | "skipped") => {
    setBusy(it.id);
    try {
      await api("/client/flight-support/complete", {
        method: "POST",
        body: {
          intervention_id: it.id,
          status,
          protocol_key: it.protocol_key,
          duration_min: it.duration_min,
          date: it.date,
        },
      });
      if (onRefresh) await onRefresh();
    } catch (e: any) {
      Alert.alert("Couldn't save", String(e?.message || e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <View style={s.wrap} testID="flight-support-today">
      <View style={s.headerRow}>
        <Ionicons name="airplane-outline" size={12} color={theme.color.textMuted} />
        <Text style={s.header}>FLIGHT SUPPORT</Text>
        <Text style={s.headerHint}>Not counted as training</Text>
      </View>
      {items.map((it) => (
        <FlightSupportCard
          key={it.id} it={it} busy={busy === it.id}
          onComplete={() => complete(it, "completed")}
          onSkip={() => complete(it, "skipped")}
        />
      ))}
    </View>
  );
}

function FlightSupportCard({
  it, busy, onComplete, onSkip,
}: {
  it: Intervention; busy: boolean;
  onComplete: () => void; onSkip: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const iconName = familyIcon(it.family);
  const tone = familyTone(it.family);
  const done = it.completion_status === "completed";
  const skipped = it.completion_status === "skipped";
  const partial = it.completion_status === "partial";
  return (
    <View
      style={[
        s.card,
        done ? s.cardDone : skipped ? s.cardSkipped : null,
        { borderLeftColor: tone },
      ]}
      testID={`fs-card-${it.protocol_key}`}
    >
      <Pressable
        onPress={() => setExpanded((v) => !v)}
        style={s.cardHeader}
        testID={`fs-toggle-${it.id}`}
      >
        <View style={[s.iconChip, { backgroundColor: tone + "22", borderColor: tone }]}>
          <Ionicons name={iconName as any} size={14} color={tone} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={s.title} numberOfLines={1}>
            {it.title}
            {it.is_bundle ? (
              <Text style={s.bundleHint}>  ·  {(it.sub_interventions || []).length} steps</Text>
            ) : null}
          </Text>
          {it.trigger_reason ? (
            <Text style={s.reason} numberOfLines={2}>{it.trigger_reason}</Text>
          ) : null}
        </View>
        <View style={{ alignItems: "flex-end" }}>
          <Text style={s.duration}>{it.duration_min}m</Text>
          <Text style={s.intensity}>{intensityLabel(it.intensity)}</Text>
        </View>
      </Pressable>

      {expanded && it.blocks && it.blocks.length > 0 ? (
        <View style={s.blocksWrap}>
          {it.blocks.map((b: any, i: number) => (
            <View key={i} style={s.blockRow}>
              <Text style={s.blockName}>{b.name || b.type || `Step ${i + 1}`}</Text>
              <View style={s.blockRight}>
                {b.cue ? <Text style={s.blockCue} numberOfLines={1}>{b.cue}</Text> : null}
                <Text style={s.blockDur}>
                  {b.duration_min ? `${b.duration_min}m` : b.duration_sec ? `${b.duration_sec}s` : ""}
                </Text>
              </View>
            </View>
          ))}
          {it.cues && it.cues.length > 0 ? (
            <Text style={s.cues}>{it.cues.join("  ·  ")}</Text>
          ) : null}
        </View>
      ) : null}

      <View style={s.actionsRow}>
        <Pressable
          testID={`fs-complete-${it.protocol_key}`}
          disabled={busy}
          onPress={onComplete}
          style={[s.actionBtn, done ? s.actionBtnDone : null]}
        >
          <Ionicons name={done ? "checkmark-circle" : "checkmark"} size={13} color={done ? "#fff" : theme.color.brand} />
          <Text style={[s.actionT, done ? s.actionTDone : { color: theme.color.brand }]}>
            {done ? "COMPLETED" : partial ? "MARK DONE" : "DONE"}
          </Text>
        </Pressable>
        <Pressable
          testID={`fs-skip-${it.protocol_key}`}
          disabled={busy}
          onPress={onSkip}
          style={[s.actionBtn, s.actionBtnSkip, skipped ? s.actionBtnSkipped : null]}
        >
          <Ionicons name="close" size={13} color={skipped ? "#fff" : theme.color.textMuted} />
          <Text style={[s.actionT, { color: skipped ? "#fff" : theme.color.textMuted }]}>
            {skipped ? "SKIPPED" : "SKIP"}
          </Text>
        </Pressable>
      </View>
    </View>
  );
}

function intensityLabel(i?: string): string {
  const v = (i || "").toLowerCase();
  if (v === "very_low") return "RPE 1-2";
  if (v === "low") return "RPE 2-3";
  return "easy";
}

function familyIcon(family: string): string {
  switch ((family || "").toLowerCase()) {
    case "walk":            return "walk-outline";
    case "mobility":        return "body-outline";
    case "activation":      return "flash-outline";
    case "recovery":        return "moon-outline";
    case "reset":           return "refresh-outline";
    case "movement_break":  return "pause-circle-outline";
    default:                return "airplane-outline";
  }
}
function familyTone(family: string): string {
  switch ((family || "").toLowerCase()) {
    case "walk":            return theme.color.brand;
    case "mobility":        return theme.color.green;
    case "activation":      return theme.color.amber;
    case "recovery":        return "#8b5cf6";
    case "reset":           return "#0ea5e9";
    case "movement_break":  return theme.color.textMuted;
    default:                return theme.color.textMuted;
  }
}

const s = StyleSheet.create({
  wrap: {
    marginTop: 12, marginHorizontal: 12, padding: 12,
    backgroundColor: theme.color.surface, borderRadius: theme.radius.md,
    borderWidth: 1, borderColor: theme.color.border,
    gap: 10,
  },
  headerRow: {
    flexDirection: "row", alignItems: "center", gap: 6,
  },
  header: {
    color: theme.color.text, fontSize: 11, fontWeight: "800",
    letterSpacing: 1.4,
  },
  headerHint: {
    color: theme.color.textMuted, fontSize: 9, fontWeight: "600",
    fontStyle: "italic", marginLeft: "auto",
  },
  body: {
    color: theme.color.textMuted, fontSize: 12, lineHeight: 17,
  },
  card: {
    backgroundColor: theme.color.surface2, borderRadius: theme.radius.sm,
    borderWidth: 1, borderColor: theme.color.border,
    borderLeftWidth: 3,
    padding: 10, gap: 8,
  },
  cardDone: { opacity: 0.7 },
  cardSkipped: { opacity: 0.55 },
  cardHeader: {
    flexDirection: "row", alignItems: "center", gap: 8,
  },
  iconChip: {
    width: 26, height: 26, borderRadius: 13, borderWidth: 1,
    alignItems: "center", justifyContent: "center",
  },
  title: { color: theme.color.text, fontSize: 13, fontWeight: "700" },
  bundleHint: {
    color: theme.color.textMuted, fontSize: 10, fontWeight: "600",
    fontStyle: "italic",
  },
  reason: {
    color: theme.color.textMuted, fontSize: 11, marginTop: 1,
  },
  duration: { color: theme.color.brand, fontSize: 13, fontWeight: "800" },
  intensity: { color: theme.color.textMuted, fontSize: 9, fontWeight: "700",
                 letterSpacing: 1, marginTop: 1 },
  blocksWrap: {
    paddingTop: 6, borderTopWidth: 1, borderTopColor: theme.color.border,
    gap: 4,
  },
  blockRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingVertical: 2,
  },
  blockName: {
    color: theme.color.text, fontSize: 12, fontWeight: "600", flex: 1,
  },
  blockRight: {
    flexDirection: "row", alignItems: "center", gap: 6,
  },
  blockCue: {
    color: theme.color.textMuted, fontSize: 11, fontStyle: "italic",
    maxWidth: 140,
  },
  blockDur: {
    color: theme.color.brand, fontSize: 11, fontWeight: "700", minWidth: 34,
    textAlign: "right",
  },
  cues: {
    color: theme.color.textMuted, fontSize: 11, marginTop: 4,
    fontStyle: "italic",
  },
  actionsRow: {
    flexDirection: "row", gap: 6, marginTop: 2,
  },
  actionBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 12, paddingVertical: 6,
    borderRadius: 8, borderWidth: 1,
    borderColor: theme.color.brand + "55",
    flex: 1, justifyContent: "center",
  },
  actionBtnSkip: { borderColor: theme.color.border },
  actionBtnDone: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  actionBtnSkipped: { backgroundColor: theme.color.textMuted, borderColor: theme.color.textMuted },
  actionT: { fontSize: 10, fontWeight: "800", letterSpacing: 1 },
  actionTDone: { color: "#fff" },
});
