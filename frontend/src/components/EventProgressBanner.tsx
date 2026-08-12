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
import React, { useMemo } from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import Svg, { Circle } from "react-native-svg";
import { theme } from "@/src/lib/theme";
import type { ThemeMode } from "@/src/lib/theme";
import { useThemeMode } from "@/src/hooks/use-theme-mode";

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
  // Iter180 · Dynamic theme wiring — the Target Marathon card sits on
  // `surface2` which is red in Light Mode. User spec: all card content
  // (eyebrow, event name, date, milestone label/value, long-run label,
  // circular countdown value + label + ring, and both flag / walk icons)
  // must be WHITE in Light. Dark Mode keeps its existing charcoal-card
  // look — `onRed = #FFFFFF` in both palettes so no visual regression.
  const { mode } = useThemeMode();
  const styles = useMemo(() => makeStyles(mode), [mode]);
  const isLight = mode === "light";
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
            {/* Track — Iter180: subtle white wash on the red card so the
                unfilled portion of the ring is visible in Light Mode. */}
            <Circle
              cx={RING_SIZE / 2}
              cy={RING_SIZE / 2}
              r={radius}
              stroke={isLight ? "rgba(255,255,255,0.3)" : theme.color.border}
              strokeWidth={RING_STROKE}
              fill="transparent"
            />
            {/* Progress arc — rotate -90° so it starts at 12 o'clock.
                Iter180: WHITE progress arc in Light (on red card) so the
                remaining-weeks indicator is unmistakable. */}
            <Circle
              cx={RING_SIZE / 2}
              cy={RING_SIZE / 2}
              r={radius}
              stroke={isLight ? "#FFFFFF" : theme.color.brand}
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
          <Ionicons name="flag-outline" size={13} color={theme.color.onRed} />
          <Text style={styles.milestoneLabel}>NEXT MILESTONE</Text>
          <Text style={styles.milestoneValue}>{phase}</Text>
        </View>
      ) : null}

      {/* Row 3 — this week's long run */}
      {showLongRun ? (
        <>
          <View style={styles.divider} />
          <View style={styles.longRunRow}>
            <Ionicons name="walk-outline" size={13} color={theme.color.onRed} />
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

// Iter180 · Style factory — all text/icons inside the red Target Marathon
// card must render WHITE per user spec. `theme.color.onRed = #FFFFFF` in
// both palettes, so Dark Mode's charcoal card (which already expected
// white text) is visually unchanged.
function makeStyles(mode: ThemeMode) {
  const isLight = mode === "light";
  return StyleSheet.create({
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
    color: theme.color.onRed,
    fontSize: 11,
    fontWeight: "900",
    letterSpacing: 2,
  },
  name: {
    color: theme.color.onRed,
    fontSize: 20,
    fontWeight: "800",
    letterSpacing: -0.3,
  },
  dateLine: {
    color: theme.color.onRed,
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
    color: theme.color.onRed,
    fontSize: 28,
    fontWeight: "900",
    fontVariant: ["tabular-nums"],
    lineHeight: 30,
  },
  ringLabel: {
    color: theme.color.onRed,
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
    color: theme.color.onRed,
    fontSize: 11,
    fontWeight: "800",
    letterSpacing: 1.5,
  },
  milestoneValue: {
    color: theme.color.onRed,
    fontSize: 13,
    fontWeight: "700",
    marginLeft: 4,
  },
  divider: {
    height: 1,
    backgroundColor: isLight ? "rgba(255,255,255,0.28)" : theme.color.divider,
    marginVertical: 4,
  },
  longRunRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  longRunLabel: {
    color: theme.color.onRed,
    fontSize: 11,
    fontWeight: "800",
    letterSpacing: 1.5,
    flex: 1,
  },
  longRunValue: {
    color: theme.color.onRed,
    fontSize: 14,
    fontWeight: "900",
    fontVariant: ["tabular-nums"],
  },
});
}
