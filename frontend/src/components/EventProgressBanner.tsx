/**
 * EventProgressBanner — Iter 162 · Premium V2
 *
 * Motivational progress-style banner for the client's primary registered
 * event (5K, marathon, tri, HYROX, etc.). Replaces the legacy row-only
 * event card with a two-column layout:
 *
 *   ┌─────────────────────────────────────────────────────┐
 *   │  MARATHON · BUILD              ╭─────╮              │
 *   │  Athens Marathon               │ 12  │  weeks       │
 *   │  10 Nov 2026 · target 3:45     │     │  remaining   │
 *   │  Next milestone: Peak          ╰─────╯              │
 *   │  ────────────────────────────────────────────────── │
 *   │  This week's long run · 24 km                       │
 *   └─────────────────────────────────────────────────────┘
 *
 * Progress ring math — the ring FILLS as the race approaches:
 *   progress = 1 - clamp(weeks_to_race / RING_MAX_WEEKS, 0, 1)
 * where RING_MAX_WEEKS defaults to 16 (a typical build cycle). A short-cycle
 * event (e.g. 4-week 5K prep) starts with the ring already ~75% filled,
 * which is intentional — the visual weight tracks urgency, not phase.
 *
 * All React Native primitives + react-native-svg (already used by
 * RestTimer). NO react-dom / window / DOM APIs — safe for iOS + Android.
 */
import React from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import Svg, { Circle } from "react-native-svg";
import { theme } from "@/src/lib/theme";

const RING_SIZE = 92;
const RING_STROKE = 8;
const RING_MAX_WEEKS = 16;

type PhaseInfo = {
  phase?: string | null;
  weeks_to_race?: number | null;
  days_to_race?: number | null;
};

type EventShape = {
  event_name?: string | null;
  event_date?: string | null;
  event_type?: string | null;
  category?: string | null;
  category_label?: string | null;
  target_time?: string | null;
  phase_info?: PhaseInfo | null;
  days_value?: number | null;
  days_label?: string | null;
};

/** Best-effort human-friendly formatting for phase codes. */
function _prettyPhase(raw?: string | null): string | null {
  if (!raw) return null;
  const s = String(raw).replace(/_/g, " ").trim();
  if (!s) return null;
  return s
    .split(" ")
    .map((w) => (w.length <= 2 ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1).toLowerCase()))
    .join(" ");
}

/** Compute the fraction of the ring to fill (0 → empty, 1 → full). */
function _progressFromWeeks(weeksToRace: number | null | undefined): number {
  if (weeksToRace == null || Number.isNaN(Number(weeksToRace))) return 0;
  const w = Math.max(0, Number(weeksToRace));
  const remainingFraction = Math.min(1, w / RING_MAX_WEEKS);
  return Number((1 - remainingFraction).toFixed(3));
}

export function EventProgressBanner({
  event,
  longRunKm,
  onPress,
  onLongPress,
  testID,
}: {
  event: EventShape;
  longRunKm?: number | null;
  onPress?: () => void;
  onLongPress?: () => void;
  testID?: string;
}) {
  const phase = _prettyPhase(event.phase_info?.phase || null);
  const weeksRemaining =
    event.phase_info?.weeks_to_race != null
      ? Number(event.phase_info.weeks_to_race)
      : null;
  const progress = _progressFromWeeks(weeksRemaining);

  const radius = (RING_SIZE - RING_STROKE) / 2;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference * (1 - progress);

  const catLabel = (event.category_label || String(event.event_type || "")).toUpperCase();
  const dateLine = [event.event_date, event.target_time ? `target ${event.target_time}` : null]
    .filter(Boolean)
    .join(" · ");

  const showLongRun = longRunKm != null && Number(longRunKm) > 0;

  return (
    <Pressable
      testID={testID || "event-progress-banner"}
      onPress={onPress}
      onLongPress={onLongPress}
      style={styles.wrap}
    >
      {/* Row 1 — event identity + progress ring */}
      <View style={styles.topRow}>
        <View style={styles.leftCol}>
          <Text style={styles.eyebrow} numberOfLines={1}>
            {phase ? `${catLabel} · ${phase.toUpperCase()}` : catLabel}
          </Text>
          <Text style={styles.name} numberOfLines={2}>
            {event.event_name || "Your event"}
          </Text>
          {dateLine ? (
            <Text style={styles.dateLine} numberOfLines={1}>
              {dateLine}
            </Text>
          ) : null}
        </View>

        <View style={styles.ringCol}>
          <Svg width={RING_SIZE} height={RING_SIZE}>
            {/* Track */}
            <Circle
              cx={RING_SIZE / 2}
              cy={RING_SIZE / 2}
              r={radius}
              stroke={theme.color.border}
              strokeWidth={RING_STROKE}
              fill="transparent"
            />
            {/* Progress arc — rotate -90° so it starts at 12 o'clock. */}
            <Circle
              cx={RING_SIZE / 2}
              cy={RING_SIZE / 2}
              r={radius}
              stroke={theme.color.brand}
              strokeWidth={RING_STROKE}
              fill="transparent"
              strokeLinecap="round"
              strokeDasharray={`${circumference} ${circumference}`}
              strokeDashoffset={dashOffset}
              transform={`rotate(-90 ${RING_SIZE / 2} ${RING_SIZE / 2})`}
            />
          </Svg>
          <View style={styles.ringCentre} pointerEvents="none">
            <Text style={styles.ringValue}>
              {weeksRemaining != null ? Math.max(0, Math.round(weeksRemaining)) : "—"}
            </Text>
            <Text style={styles.ringLabel}>
              {weeksRemaining === 1 ? "WEEK" : "WEEKS"}
            </Text>
          </View>
        </View>
      </View>

      {/* Row 2 — next milestone */}
      {phase ? (
        <View style={styles.milestoneRow}>
          <Ionicons name="flag-outline" size={13} color={theme.color.textMuted} />
          <Text style={styles.milestoneLabel}>NEXT MILESTONE</Text>
          <Text style={styles.milestoneValue}>{phase}</Text>
        </View>
      ) : null}

      {/* Row 3 — this week's long run */}
      {showLongRun ? (
        <>
          <View style={styles.divider} />
          <View style={styles.longRunRow}>
            <Ionicons name="walk-outline" size={13} color={theme.color.textMuted} />
            <Text style={styles.longRunLabel}>THIS WEEK&apos;S LONG RUN</Text>
            <Text style={styles.longRunValue}>{`${Number(longRunKm).toFixed(Number(longRunKm) % 1 === 0 ? 0 : 1)} km`}</Text>
          </View>
        </>
      ) : null}
    </Pressable>
  );
}

// Re-export the pure helpers for unit-testing without a component mount.
export const _internals = { _progressFromWeeks, _prettyPhase };

const styles = StyleSheet.create({
  wrap: {
    backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.card,
    borderWidth: 1,
    borderColor: theme.color.border,
    padding: theme.space.lg,
    gap: 10,
  },
  topRow: { flexDirection: "row", alignItems: "center", gap: 12 },
  leftCol: { flex: 1, minHeight: RING_SIZE, justifyContent: "center", gap: 4 },
  eyebrow: {
    color: theme.color.brand,
    fontSize: 11,
    fontWeight: "900",
    letterSpacing: 2,
  },
  name: {
    color: theme.color.text,
    fontSize: 20,
    fontWeight: "800",
    letterSpacing: -0.3,
  },
  dateLine: {
    color: theme.color.textSoft,
    fontSize: 13,
    fontWeight: "500",
    marginTop: 2,
  },
  ringCol: {
    width: RING_SIZE,
    height: RING_SIZE,
    alignItems: "center",
    justifyContent: "center",
  },
  ringCentre: {
    position: "absolute",
    top: 0, left: 0, right: 0, bottom: 0,
    alignItems: "center",
    justifyContent: "center",
  },
  ringValue: {
    color: theme.color.text,
    fontSize: 28,
    fontWeight: "900",
    fontVariant: ["tabular-nums"],
    lineHeight: 30,
  },
  ringLabel: {
    color: theme.color.textMuted,
    fontSize: 11,
    fontWeight: "800",
    letterSpacing: 1.5,
    marginTop: 2,
  },
  milestoneRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: 2,
  },
  milestoneLabel: {
    color: theme.color.textMuted,
    fontSize: 11,
    fontWeight: "800",
    letterSpacing: 1.5,
  },
  milestoneValue: {
    color: theme.color.text,
    fontSize: 13,
    fontWeight: "700",
    marginLeft: 4,
  },
  divider: {
    height: 1,
    backgroundColor: theme.color.divider,
    marginVertical: 4,
  },
  longRunRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  longRunLabel: {
    color: theme.color.textMuted,
    fontSize: 11,
    fontWeight: "800",
    letterSpacing: 1.5,
    flex: 1,
  },
  longRunValue: {
    color: theme.color.brand,
    fontSize: 14,
    fontWeight: "900",
    fontVariant: ["tabular-nums"],
  },
});
