/**
 * TodayFlightSupport — client-facing Aviation Support block on Home.
 *
 * Iter 126 · UX rebuild.
 * Renders interventions returned by /api/client/today as a separate section
 * from Training. NEVER treats these as programme workouts.
 *
 * Compact summary card only. Full protocol / guided execution lives in
 * FlightSupportProtocolModal. Completion is recorded as Flight Support
 * completion, never as workout completion.
 */
import React, { useState } from "react";
import { View, Text, StyleSheet, Pressable, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";
import { api } from "@/src/lib/api";
import { FlightSupportProtocolModal } from "@/src/components/FlightSupportProtocolModal";

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
  const [openIntervention, setOpenIntervention] = useState<Intervention | null>(null);
  const [skipBusy, setSkipBusy] = useState<string | null>(null);

  if (!snapshot) return null;
  const enabled = snapshot.auto_flight_support_enabled !== false;
  const items: Intervention[] = snapshot.flight_support || [];
  const role: string = snapshot.role || "role_unknown";

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

  const skip = async (it: Intervention) => {
    setSkipBusy(it.id);
    try {
      await api("/client/flight-support/complete", {
        method: "POST",
        body: {
          intervention_id: it.id,
          status: "skipped",
          protocol_key: it.protocol_key,
          duration_min: it.duration_min,
          date: it.date,
        },
      });
      if (onRefresh) await onRefresh();
    } catch (e: any) {
      Alert.alert("Couldn't save", String(e?.message || e));
    } finally {
      setSkipBusy(null);
    }
  };

  const handleCompleted = async () => {
    if (onRefresh) await onRefresh();
  };

  return (
    <View style={s.wrap} testID="flight-support-today">
      <View style={s.headerRow}>
        <Ionicons name="airplane-outline" size={12} color={theme.color.textMuted} />
        <Text style={s.header}>FLIGHT SUPPORT</Text>
        <Text style={s.headerHint}>Not counted as training</Text>
      </View>
      {items.map((it) => (
        <FlightSupportSummary
          key={it.id}
          it={it}
          skipBusy={skipBusy === it.id}
          onOpen={() => setOpenIntervention(it)}
          onSkip={() => skip(it)}
        />
      ))}

      <FlightSupportProtocolModal
        visible={!!openIntervention}
        intervention={openIntervention}
        onClose={() => setOpenIntervention(null)}
        onCompleted={handleCompleted}
      />
    </View>
  );
}

/* ---------------------------- summary card ------------------------------- */
function FlightSupportSummary({
  it, skipBusy, onOpen, onSkip,
}: {
  it: Intervention;
  skipBusy: boolean;
  onOpen: () => void;
  onSkip: () => void;
}) {
  const iconName = familyIcon(it.family);
  const tone = familyTone(it.family);
  const done = it.completion_status === "completed";
  const skipped = it.completion_status === "skipped";
  const movements = (it.blocks || []).length;

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
        onPress={done || skipped ? undefined : onOpen}
        style={s.cardHeader}
        testID={`fs-open-${it.id}`}
        disabled={done || skipped}
      >
        <View style={[s.iconChip, { backgroundColor: tone + "22", borderColor: tone }]}>
          <Ionicons name={iconName as any} size={14} color={tone} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={s.title} numberOfLines={1}>{it.title}</Text>
          <Text style={s.metaLine} numberOfLines={1}>
            {familyLabel(it.family)}
            {" · "}
            {it.duration_min} min
            {movements > 0 ? ` · ${movements} movement${movements === 1 ? "" : "s"}` : ""}
          </Text>
          {it.trigger_reason && !done && !skipped ? (
            <Text style={s.reason} numberOfLines={2}>{it.trigger_reason}</Text>
          ) : null}
        </View>
        {!done && !skipped ? (
          <Ionicons name="chevron-forward" size={18} color={theme.color.textMuted} />
        ) : null}
      </Pressable>

      {/* Status pill OR the two action rows (Start / Skip) */}
      {done ? (
        <View style={[s.statusPill, { backgroundColor: theme.color.brand + "22", borderColor: theme.color.brand }]}>
          <Ionicons name="checkmark-circle" size={13} color={theme.color.brand} />
          <Text style={[s.statusText, { color: theme.color.brand }]}>COMPLETED</Text>
        </View>
      ) : skipped ? (
        <View style={[s.statusPill, { backgroundColor: theme.color.textMuted + "22", borderColor: theme.color.textMuted }]}>
          <Ionicons name="close" size={13} color={theme.color.textMuted} />
          <Text style={[s.statusText, { color: theme.color.textMuted }]}>SKIPPED</Text>
        </View>
      ) : (
        <View style={s.actionsRow}>
          <Pressable
            testID={`fs-start-${it.protocol_key}`}
            onPress={onOpen}
            style={[s.primaryBtn]}
          >
            <Ionicons name="play" size={13} color="#fff" />
            <Text style={s.primaryBtnText}>START FLIGHT SUPPORT</Text>
          </Pressable>
          <Pressable
            testID={`fs-skip-${it.protocol_key}`}
            disabled={skipBusy}
            onPress={onSkip}
            style={s.skipBtn}
          >
            <Text style={s.skipText}>SKIP</Text>
          </Pressable>
        </View>
      )}
    </View>
  );
}

function familyLabel(family: string): string {
  switch ((family || "").toLowerCase()) {
    case "mobility":       return "Mobility";
    case "activation":     return "Activation";
    case "recovery":       return "Recovery";
    case "reset":          return "Reset";
    case "walk":           return "Walk";
    case "movement_break": return "Movement break";
    default:               return "Flight Support";
  }
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
    padding: 12, gap: 10,
  },
  cardDone: { opacity: 0.7 },
  cardSkipped: { opacity: 0.55 },
  cardHeader: {
    flexDirection: "row", alignItems: "center", gap: 10,
  },
  iconChip: {
    width: 32, height: 32, borderRadius: 16, borderWidth: 1,
    alignItems: "center", justifyContent: "center",
  },
  title: {
    color: theme.color.text, fontSize: 15, fontWeight: "800",
  },
  metaLine: {
    color: theme.color.brand, fontSize: 11, fontWeight: "700",
    letterSpacing: 0.5, marginTop: 2, textTransform: "uppercase",
  },
  reason: {
    color: theme.color.textMuted, fontSize: 12, marginTop: 4, lineHeight: 16,
  },

  statusPill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    alignSelf: "flex-start",
    paddingHorizontal: 10, paddingVertical: 4,
    borderRadius: 12, borderWidth: 1,
  },
  statusText: { fontSize: 10, fontWeight: "800", letterSpacing: 1 },

  actionsRow: {
    flexDirection: "row", gap: 8, marginTop: 2,
  },
  primaryBtn: {
    flex: 1,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    paddingVertical: 12, borderRadius: 10,
    backgroundColor: theme.color.brand,
  },
  primaryBtnText: {
    color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.2,
  },
  skipBtn: {
    paddingHorizontal: 14, paddingVertical: 12, borderRadius: 10,
    backgroundColor: "transparent",
    borderWidth: 1, borderColor: theme.color.border,
    alignItems: "center", justifyContent: "center",
  },
  skipText: {
    color: theme.color.textMuted, fontSize: 11, fontWeight: "800", letterSpacing: 1,
  },
});
