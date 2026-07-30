/**
 * ScheduleRow — Iter 107
 *
 * Unified DATE | ROSTER | ASSIGNED PLAN row used across the Coach Dashboard
 * for showing a client's daily schedule. Replaces the older DayCardView.
 *
 * Layout on desktop / wider screens:
 *   ┌─────────┬────────────────────┬───────────────────────────────┐
 *   │  DATE   │  ROSTER DAY        │  ASSIGNED PLAN                │
 *   │  06 AUG │  ✈ Layover Arrival │  Arrival Recovery · Mob · 12m │
 *   └─────────┴────────────────────┴───────────────────────────────┘
 *
 * On mobile the same three regions stack into a compact card but keep the
 * same DATE / ROSTER / PLAN reading order, so the coach's eye trains once
 * and reads the same shape everywhere it appears.
 *
 * Colour language (subtle left-border only):
 *   Home        → blue
 *   Standby     → amber
 *   Flight      → red
 *   Layover     → purple
 *   Turnaround  → orange
 *   Rest / Off  → neutral grey
 *   Sick/Medical→ amber
 *   Unknown     → neutral
 *
 * Icon + text is always shown — colour is a hint, never the only signal.
 * Backend labels (LAYOVER_ARRIVAL, HOME_DAY, etc.) are humanised via
 * `humaniseDutyLabel` — the coach UI never shows raw database tokens.
 */
import React from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";

export type ScheduleDay = {
  date: string;
  weekday?: string;
  day_type?: string | null;
  client_label?: string | null;
  label?: string | null;
  training_colour?: "green" | "amber" | "red" | "black" | string;
  layover_city?: string | null;
  layover_nights?: number | null;
  report_time?: string | null;
  release_time?: string | null;
  hotel_name?: string | null;
  needs_review?: boolean;
  flights?: { number?: string; from?: string; to?: string }[];
  reason?: string;
  workout?: {
    id: string;
    title?: string | null;
    focus?: string | null;
    duration_min?: number | null;
    exercise_count?: number;
    approved?: boolean;
    completed?: boolean;
    coach_locked?: boolean;
    missing_media_count?: number;
    client_hidden?: boolean;
    client_visible_in_min?: number;
    parser_enforced?: boolean;
  } | null;
};

/* ------------------------------ helpers --------------------------------- */

export function humaniseDutyLabel(raw?: string | null): string {
  if (!raw) return "Unassigned";
  const s = String(raw).replace(/[_-]+/g, " ").trim().toLowerCase();
  if (!s) return "Unassigned";
  return s.replace(/\b\w/g, (c) => c.toUpperCase());
}

type Kind = "home" | "standby" | "flight" | "layover" | "turnaround" | "rest" | "sick" | "training" | "other";

function classify(day: ScheduleDay): Kind {
  const t = String(day.day_type || "").toLowerCase();
  if (!t) {
    // Fall back to workout title inference (mirrors ClientCalendarPanel).
    const wt = String(day.workout?.title || "").toLowerCase();
    if (wt.includes("layover")) return "layover";
    if (wt.includes("turnaround")) return "turnaround";
    if (wt.includes("flight")) return "flight";
    return "other";
  }
  if (t.includes("layover")) return "layover";
  if (t.includes("turnaround") || t === "t/r") return "turnaround";
  if (t.includes("standby") || t === "sby") return "standby";
  if (t.includes("flight") || t.includes("flying") || t.includes("long_haul") || t.includes("short_haul") || t.includes("night_flight")) return "flight";
  if (t.includes("home")) return "home";
  if (t === "off" || t === "rest" || t.includes("day_off") || t.includes("annual") || t === "recovery") return "rest";
  if (t.includes("sick") || t.includes("medical")) return "sick";
  if (t.includes("sim") || t.includes("training") || t.includes("ground_school")) return "training";
  return "other";
}

const KIND_COLOURS: Record<Kind, { border: string; tint: string; icon: keyof typeof Ionicons.glyphMap; label: string }> = {
  home:       { border: "#3b82f6", tint: "rgba(59,130,246,0.10)",  icon: "home",        label: "Home" },
  standby:    { border: "#f59e0b", tint: "rgba(245,158,11,0.10)",  icon: "hourglass",   label: "Standby" },
  flight:     { border: "#ef4444", tint: "rgba(239,68,68,0.10)",   icon: "airplane",    label: "Flying" },
  layover:    { border: "#a855f7", tint: "rgba(168,85,247,0.10)",  icon: "bed",         label: "Layover" },
  turnaround: { border: "#f97316", tint: "rgba(249,115,22,0.10)",  icon: "repeat",      label: "Turnaround" },
  rest:       { border: "#6b7280", tint: "rgba(107,114,128,0.10)", icon: "leaf",        label: "Rest" },
  sick:       { border: "#f59e0b", tint: "rgba(245,158,11,0.10)",  icon: "medkit",      label: "Sick" },
  training:   { border: "#3b82f6", tint: "rgba(59,130,246,0.10)",  icon: "school",      label: "Training" },
  other:      { border: "#4b5563", tint: "rgba(75,85,99,0.10)",    icon: "briefcase",   label: "Duty" },
};

function fmtDate(iso: string): { day: string; num: string; short: string } {
  try {
    const dt = new Date(iso + "T00:00:00");
    return {
      day: dt.toLocaleDateString(undefined, { weekday: "short" }).toUpperCase(),
      num: String(dt.getDate()),
      short: dt.toLocaleDateString(undefined, { day: "numeric", month: "short" }),
    };
  } catch {
    return { day: "", num: "", short: iso };
  }
}

/* ------------------------------ component ------------------------------- */

export function ScheduleRow({
  day,
  onOpenWorkout,
  onWorkoutMenu,
  onEditRoster,
}: {
  day: ScheduleDay;
  onOpenWorkout?: (workoutId: string) => void;
  onWorkoutMenu?: () => void;
  onEditRoster?: () => void;
}) {
  const kind = classify(day);
  const c = KIND_COLOURS[kind];
  const rawLabel = day.client_label || day.label || day.day_type;
  const dutyLabel = humaniseDutyLabel(rawLabel);
  const d = fmtDate(day.date);
  const route = (day.flights || [])
    .map((f: any) => {
      const org = f.origin || f.from || "";
      const dst = f.destination || f.to || "";
      if (!org && !dst) return "";
      return `${org || "?"}→${dst || "?"}`;
    })
    .filter(Boolean)
    .join(" · ");
  const w = day.workout;
  const hasWorkout = !!w?.id;

  return (
    <View style={[styles.row, { borderLeftColor: c.border }]} testID={`sched-${day.date}`}>
      {/* Date column */}
      <View style={styles.dateCol}>
        <Text style={styles.dow}>{d.day}</Text>
        <Text style={styles.dnum}>{d.num}</Text>
      </View>

      {/* Roster column */}
      <Pressable
        testID={`sched-roster-${day.date}`}
        onPress={onEditRoster}
        style={[styles.rosterCol, { backgroundColor: c.tint }]}
      >
        <View style={styles.rosterHead}>
          <Ionicons name={c.icon} size={13} color={c.border} />
          <Text style={[styles.rosterLabel, { color: c.border }]} numberOfLines={1}>
            {dutyLabel !== "Unassigned" ? dutyLabel : c.label}
          </Text>
          {day.needs_review ? (
            <View style={styles.reviewPill}>
              <Ionicons name="alert-circle" size={9} color="#fff" />
              <Text style={styles.reviewPillT}>REVIEW</Text>
            </View>
          ) : null}
        </View>
        {route ? <Text style={styles.rosterMeta} numberOfLines={1}>{route}</Text> : null}
        {day.layover_city && kind === "layover" ? (
          <Text style={styles.rosterMeta} numberOfLines={1}>
            {day.layover_city}{day.layover_nights ? ` · ${day.layover_nights}n` : ""}
          </Text>
        ) : null}
        {day.hotel_name ? <Text style={styles.rosterMeta} numberOfLines={1}>{day.hotel_name}</Text> : null}
        {(day.report_time || day.release_time) ? (
          <Text style={styles.rosterMeta} numberOfLines={1}>
            {day.report_time ? `Report ${day.report_time}` : ""}
            {day.report_time && day.release_time ? " · " : ""}
            {day.release_time ? `Off ${day.release_time}` : ""}
          </Text>
        ) : null}
      </Pressable>

      {/* Assigned Plan column */}
      <Pressable
        testID={hasWorkout ? `sched-plan-${w!.id}` : `sched-plan-empty-${day.date}`}
        onPress={() => { if (hasWorkout && onOpenWorkout) onOpenWorkout(w!.id); }}
        disabled={!hasWorkout}
        style={styles.planCol}
      >
        {hasWorkout ? (
          <>
            <View style={styles.planHead}>
              <Text style={styles.planTitle} numberOfLines={1}>
                {w!.title || "Workout"}{w!.coach_locked ? "  🔒" : ""}
              </Text>
              {onWorkoutMenu ? (
                <Pressable
                  testID={`sched-plan-menu-${w!.id}`}
                  onPress={(e) => { e.stopPropagation(); onWorkoutMenu(); }}
                  hitSlop={10}
                >
                  <Ionicons name="ellipsis-horizontal" size={16} color={theme.color.textMuted} />
                </Pressable>
              ) : null}
            </View>
            <Text style={styles.planMeta} numberOfLines={1}>
              {(w!.focus || "").replace(/^./, (s) => s.toUpperCase())}
              {w!.duration_min ? ` · ${w!.duration_min} min` : ""}
              {w!.exercise_count ? ` · ${w!.exercise_count} ex` : ""}
            </Text>
            <View style={styles.planChips}>
              {w!.completed ? (
                <View style={[styles.chip, { backgroundColor: theme.color.green }]}><Text style={styles.chipT}>DONE</Text></View>
              ) : w!.approved ? (
                <View style={[styles.chip, { backgroundColor: theme.color.brand }]}><Text style={styles.chipT}>APPROVED</Text></View>
              ) : (
                <View style={[styles.chip, { backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border }]}>
                  <Text style={[styles.chipT, { color: theme.color.textMuted }]}>PLANNED</Text>
                </View>
              )}
              {w!.client_hidden ? (
                <View style={[styles.chip, { backgroundColor: theme.color.amber }]}>
                  <Text style={styles.chipT}>HIDDEN {w!.client_visible_in_min ? `· ${w!.client_visible_in_min}m` : ""}</Text>
                </View>
              ) : null}
              {(w!.missing_media_count || 0) > 0 ? (
                <View style={[styles.chip, { backgroundColor: "#dc2626" }]}>
                  <Text style={styles.chipT}>{w!.missing_media_count} MEDIA</Text>
                </View>
              ) : null}
            </View>
          </>
        ) : (
          <View style={styles.planEmpty}>
            <Text style={styles.planEmptyTitle}>Louis to plan</Text>
            <Text style={styles.planEmptySub}>Tap to build a session for this day</Text>
          </View>
        )}
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    gap: 10,
    padding: 10,
    marginBottom: 8,
    borderRadius: 10,
    backgroundColor: theme.color.surface,
    borderLeftWidth: 4,
  },
  dateCol: {
    width: 42, alignItems: "center", justifyContent: "center",
  },
  dow: { color: theme.color.textMuted, fontSize: 9, fontWeight: "800", letterSpacing: 1.2 },
  dnum: { color: theme.color.text, fontSize: 20, fontWeight: "900", marginTop: 1 },

  rosterCol: {
    flex: 1.1,
    padding: 8,
    borderRadius: 8,
    justifyContent: "center",
  },
  rosterHead: { flexDirection: "row", alignItems: "center", gap: 5, marginBottom: 2 },
  rosterLabel: { fontSize: 11, fontWeight: "800", letterSpacing: 0.4, flex: 1 },
  rosterMeta: { color: theme.color.textMuted, fontSize: 10, marginTop: 2, lineHeight: 13 },
  reviewPill: {
    flexDirection: "row", alignItems: "center", gap: 2,
    paddingHorizontal: 4, paddingVertical: 2, borderRadius: 3,
    backgroundColor: "#dc2626",
  },
  reviewPillT: { color: "#fff", fontSize: 7, fontWeight: "900", letterSpacing: 0.5 },

  planCol: { flex: 1.5, padding: 8, borderRadius: 8, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, justifyContent: "center" },
  planHead: { flexDirection: "row", alignItems: "center", gap: 6 },
  planTitle: { color: theme.color.text, fontSize: 12, fontWeight: "800", flex: 1 },
  planMeta: { color: theme.color.textMuted, fontSize: 10, marginTop: 3 },
  planChips: { flexDirection: "row", flexWrap: "wrap", gap: 4, marginTop: 6 },
  chip: { paddingHorizontal: 5, paddingVertical: 2, borderRadius: 3 },
  chipT: { color: "#fff", fontSize: 8, fontWeight: "900", letterSpacing: 0.6 },
  planEmpty: { paddingVertical: 4 },
  planEmptyTitle: { color: theme.color.textMuted, fontSize: 12, fontWeight: "800", fontStyle: "italic" },
  planEmptySub: { color: theme.color.textMuted, fontSize: 10, marginTop: 3 },
});

export default ScheduleRow;
