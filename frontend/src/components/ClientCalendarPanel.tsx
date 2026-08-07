/**
 * ClientCalendarPanel — Iter 94s
 *
 * Scrollable ±30-day (extendable to ±60) calendar rendered inline inside the
 * home dashboard's ScrollView (no nested scroll). Each day card shows:
 *   - Date + Today badge
 *   - Workout title + duration
 *   - Duty (roster) summary + layover
 *   - Personal activity chip(s)
 *   - Primary badge: Completed / Planned / Missed / Recovered / Moved /
 *                    Optional / Skipped / Key / Awaiting Review / Roster-adj.
 *   - Missed → Recover inline action
 *
 * Load-more buttons at top/bottom extend the range in 30-day chunks (max ±60).
 * The parent is responsible for scrolling; this component just reports the
 * y-position of today's row via `onTodayLayoutY` so the parent can jump.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useFocusEffect } from "expo-router";
import { api } from "@/src/lib/api";
import { theme, loadColor } from "@/src/lib/theme";
import { RecoverySheet } from "./RecoverySheet";
import { MoveWorkoutSheet } from "./MoveWorkoutSheet";

type DayCard = {
  date: string;
  is_today: boolean;
  is_past: boolean;
  badge: string;
  priority?: string | null;
  workout?: {
    id: string;
    title?: string;
    focus?: string;
    session_type?: string;
    day_load?: string;
    completed?: boolean;
    skipped?: boolean;
    key_session?: boolean;
    coach_locked?: boolean;
    location?: string;
    estimated_minutes?: number;
    recovered_from_date?: string;
    recovered_to_date?: string;
    hard?: boolean;
    // Iter 112 — Engine V2 rationale / intensity / priority surfacing.
    source?: string;                // "engine_v2" | undefined
    rationale?: string | null;
    priority?: string | null;       // "KEY" | "IMPORTANT" | "SUPPORT"
    intensity_target?: string | null;
    exposure_number?: number | null;
  } | null;
  roster_day?: {
    day_type?: string;
    layover_city?: string;
    flights?: {
      // Backend v2 shape
      flight_number?: string;
      origin?: string;
      destination?: string;
      dep_time?: string;
      arr_time?: string;
      aircraft?: string;
      // Legacy shape (kept for compat)
      number?: string;
      from?: string;
      to?: string;
    }[];
    load?: string;
  } | null;
  activities?: any[];
  client_copy?: { title?: string; body?: string; recommendation?: string } | null;
  // Iter 116 — Aviation Support Layer (Phase A).
  // A separate, non-training list of short operational interventions. NEVER
  // affects Engine V2 quotas or adherence. Empty for non-pilot roles or
  // non-duty days.
  flight_support?: {
    id: string;
    date: string;
    protocol_key: string;
    role: string;
    title: string;
    family: string;               // walk | mobility | activation | recovery | reset | movement_break | custom
    intensity: string;
    duration_min: number;
    cues: string[];
    equipment: string[];
    blocks: any[];
    bundle_key?: string | null;
    bundle_title?: string | null;
    trigger_reason?: string;
  }[];
};

type RangePayload = {
  from: string;
  to: string;
  today: string;
  days: DayCard[];
  counts: Record<string, number>;
};

const PAGE_DAYS = 6;        // 7 visible days = today + 6 (initial), or a 7-day page
const MAX_BACK = 60;
const MAX_FWD  = 60;

function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}
function localToday(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${dd}`;
}
function niceDate(iso: string): string {
  try {
    const d = new Date(`${iso}T00:00:00`);
    return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
  } catch { return iso; }
}

// Iter 116 — Flight Support family → icon + colour helpers.
// Kept local so the palette can drift without leaking into other components.
function fsFamilyIcon(family: string): string {
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
function fsFamilyColor(family: string): string {
  switch ((family || "").toLowerCase()) {
    case "walk":            return theme.color.brand;
    case "mobility":        return theme.color.green;
    case "activation":      return theme.color.amber;
    case "recovery":        return "#8b5cf6";  // violet
    case "reset":           return "#0ea5e9";  // sky
    case "movement_break":  return theme.color.textMuted;
    default:                return theme.color.textMuted;
  }
}
function daysBetween(a: string, b: string): number {
  const da = new Date(`${a}T00:00:00`).getTime();
  const db = new Date(`${b}T00:00:00`).getTime();
  return Math.round((db - da) / 86400000);
}

type BadgeStyle = { label: string; bg: string; fg: string };
function badgeStyle(b: string): BadgeStyle {
  switch (b) {
    case "completed":              return { label: "COMPLETED",   bg: theme.color.green,     fg: "#fff" };
    case "planned":                return { label: "PLANNED",     bg: theme.color.surface3,  fg: theme.color.textMuted };
    case "missed":                 return { label: "MISSED",      bg: theme.color.red,       fg: "#fff" };
    case "recovered":              return { label: "RECOVERED",   bg: theme.color.brand,     fg: "#fff" };
    case "moved":                  return { label: "MOVED",       bg: theme.color.amber,     fg: "#fff" };
    case "optional":               return { label: "OPTIONAL",    bg: theme.color.textDim,   fg: "#fff" };
    case "skipped":                return { label: "SKIPPED",     bg: theme.color.textDim,   fg: "#fff" };
    case "awaiting_coach_review":  return { label: "AWAITING REVIEW", bg: theme.color.red,   fg: "#fff" };
    case "key_session":            return { label: "KEY SESSION", bg: theme.color.brand,     fg: "#fff" };
    case "roster_adjusted":        return { label: "ROSTER-ADJUSTED", bg: theme.color.amber, fg: "#fff" };
    case "rest":                   return { label: "REST",        bg: theme.color.surface3,  fg: theme.color.textMuted };
    default:                       return { label: b.toUpperCase(), bg: theme.color.surface3, fg: theme.color.textMuted };
  }
}


// Iter 95f — pretty labels + icon per duty type. Every day gets a chip.
type DutyChip = {
  label: string;
  icon: React.ComponentProps<typeof Ionicons>["name"];
  tone: "brand" | "amber" | "muted" | "green";
};

function buildDutyChip(
  rd: DayCard["roster_day"] | null,
  workout?: DayCard["workout"] | null,
): DutyChip {
  const raw = String(rd?.day_type || "").toLowerCase();
  const map: Record<string, DutyChip> = {
    long_haul:      { label: "Long-Haul Flight", icon: "airplane", tone: "brand" },
    "long-haul":    { label: "Long-Haul Flight", icon: "airplane", tone: "brand" },
    short_haul:     { label: "Short-Haul",       icon: "airplane", tone: "brand" },
    flight_day:     { label: "Flying",           icon: "airplane", tone: "brand" },
    flying:         { label: "Flying",           icon: "airplane", tone: "brand" },
    layover_full:   { label: "Layover",          icon: "bed",      tone: "amber" },
    layover:        { label: "Layover",          icon: "bed",      tone: "amber" },
    layover_departure: { label: "Layover",       icon: "bed",      tone: "amber" },
    layover_arrival:{ label: "Layover",          icon: "bed",      tone: "amber" },
    deadhead:       { label: "Deadhead",         icon: "airplane", tone: "brand" },
    positioning:    { label: "Positioning",      icon: "airplane", tone: "brand" },
    night_flight:   { label: "Night Flight",     icon: "moon",     tone: "brand" },
    early_start:    { label: "Early Start",      icon: "alarm",    tone: "amber" },
    standby:        { label: "Standby",          icon: "hourglass",tone: "amber" },
    airport_standby:{ label: "Airport Standby",  icon: "hourglass",tone: "amber" },
    sim:            { label: "Simulator",        icon: "desktop",  tone: "brand" },
    training:       { label: "Training Day",     icon: "school",   tone: "brand" },
    ground_school:  { label: "Ground School",    icon: "school",   tone: "brand" },
    medical:        { label: "Medical",          icon: "medkit",   tone: "amber" },
    home_day:       { label: "Home",             icon: "home",     tone: "muted" },
    home:           { label: "Home",             icon: "home",     tone: "muted" },
    turnaround:     { label: "Turnaround",       icon: "repeat",   tone: "brand" },
    "t/r":          { label: "Turnaround",       icon: "repeat",   tone: "brand" },
    rest:           { label: "Rest",             icon: "leaf",     tone: "green" },
    off:            { label: "Off",              icon: "leaf",     tone: "green" },
    day_off:        { label: "Day Off",          icon: "leaf",     tone: "green" },
    annual_leave:   { label: "Annual Leave",     icon: "sunny",    tone: "green" },
    sick:           { label: "Sick",             icon: "medkit",   tone: "amber" },
    recovery:       { label: "Recovery",         icon: "heart",    tone: "green" },
  };
  if (raw && map[raw]) return map[raw];
  if (raw) {
    // Sensible fallback — Title Case the raw string.
    return {
      label: raw.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
      icon: "briefcase",
      tone: "muted",
    };
  }
  // Iter 106 — when the roster day has no explicit day_type, derive context
  // from the workout itself. Layover-branded workouts (Iter 102 renamer)
  // must not render as HOME just because rd.day_type is empty.
  const wt = String(workout?.title || "").toLowerCase();
  const wf = String(workout?.focus || "").toLowerCase();
  if (wt.includes("layover") || wf.includes("layover")) {
    return { label: "Layover", icon: "bed", tone: "amber" };
  }
  if (wt.includes("turnaround") || wt.includes("t/r")) {
    return { label: "Turnaround", icon: "repeat", tone: "brand" };
  }
  if (wt.includes("flight") || wt.includes("flying")) {
    return { label: "Flying", icon: "airplane", tone: "brand" };
  }
  // No roster loaded for this date — treat as Home so the row isn't blank.
  return { label: "Home", icon: "home", tone: "muted" };
}

function dutyChipColors(tone: DutyChip["tone"]) {
  switch (tone) {
    case "brand": return { bg: theme.color.brandTint, fg: theme.color.brand, border: theme.color.brand };
    case "amber": return { bg: "rgba(245,158,11,0.14)", fg: theme.color.amber, border: theme.color.amber };
    case "green": return { bg: "rgba(34,197,94,0.14)",  fg: theme.color.green, border: theme.color.green };
    default:      return { bg: theme.color.surface3,    fg: theme.color.textMuted, border: theme.color.border };
  }
}

function _isRestish(rd: NonNullable<DayCard["roster_day"]>): boolean {
  const t = String(rd.day_type || "").toLowerCase();
  return t === "rest" || t === "off" || t === "day_off" || t === "annual_leave" || t === "home" || t === "home_day";
}

// Iter 113 — DutyChipView retained (currently unused after we replaced the
// small chip row with a proper duty info block, but still exported-shape for
// possible future compact renderings, e.g. week/month summaries).
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function DutyChipView({ chip, small }: { chip: DutyChip; small?: boolean }) {
  const c = dutyChipColors(chip.tone);
  return (
    <View style={[
      styles.chip,
      { backgroundColor: c.bg, borderColor: c.border },
      small && styles.chipSmall,
    ]}>
      <Ionicons name={chip.icon} size={small ? 10 : 11} color={c.fg} />
      <Text style={[styles.chipT, { color: c.fg }, small && styles.chipTSmall]}>{chip.label}</Text>
    </View>
  );
}

/**
 * Iter 95h — compact icon-only status dot for the top-right of a day card.
 * Communicates duty context at a glance without cluttering the row body.
 * Long-press / tap-through opens the workout; we don't add own handler.
 */
function DutyIconDot({ chip }: { chip: DutyChip }) {
  const c = dutyChipColors(chip.tone);
  return (
    <View
      accessibilityLabel={chip.label}
      style={[styles.dutyDot, { backgroundColor: c.bg, borderColor: c.border }]}
    >
      <Ionicons name={chip.icon} size={12} color={c.fg} />
    </View>
  );
}

export function ClientCalendarPanel({
  refreshKey = 0,
  onLongPressDay,
  onTodayLayoutY,
  onJumpToToday,
}: {
  refreshKey?: number;
  onLongPressDay?: (date: string) => void;
  /** Called when today's card mounts; parent uses the y position to scroll. */
  onTodayLayoutY?: (y: number) => void;
  /** Optional: called when the internal "Today" button is tapped. */
  onJumpToToday?: () => void;
}) {
  const router = useRouter();
  const today = useMemo(localToday, []);
  // Iter 95e — REGRESSION FIX
  // Default view = today + next 6 days = a strict 7-day WINDOW.
  // Prev/Next 7 Days buttons *page* by 7 (jump), they do not append.
  // "Today" button resets to today + 6.
  const [fromDate, setFromDate] = useState<string>(() => today);
  const [toDate, setToDate] = useState<string>(() => addDays(today, PAGE_DAYS));
  const [days, setDays] = useState<DayCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [paging, setPaging] = useState<"none" | "back" | "fwd" | "today">("none");
  const [activeRecovery, setActiveRecovery] = useState<DayCard | null>(null);
  const [moveSource, setMoveSource] = useState<DayCard | null>(null);

  const load = useCallback(async (from: string, to: string) => {
    try {
      const r = await api<RangePayload>(`/calendar/range?from=${from}&to=${to}`);
      setDays(r?.days || []);
    } catch { /* ignore */ }
  }, []);

  const initRef = useRef(false);
  useEffect(() => {
    (async () => {
      setLoading(true);
      await load(fromDate, toDate);
      setLoading(false);
      initRef.current = true;
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  // Iter 152 — Refresh on focus so the "Completed" status badge appears
  // as soon as the user returns from a workout / rating flow. The initial
  // mount already loads via the effect above (initRef guard skips the
  // duplicate first-fetch). Range navigation (paging / today) is handled
  // separately by its own `load()` calls.
  useFocusEffect(
    useCallback(() => {
      if (!initRef.current) return;
      load(fromDate, toDate);
    }, [fromDate, toDate, load]),
  );

  const goPrev7 = useCallback(async () => {
    if (paging !== "none") return;
    const newFrom = addDays(fromDate, -7);
    // Cap at MAX_BACK days before today.
    const cappedFrom = daysBetween(newFrom, today) > MAX_BACK ? addDays(today, -MAX_BACK) : newFrom;
    const newTo = addDays(cappedFrom, PAGE_DAYS);
    setPaging("back");
    await load(cappedFrom, newTo);
    setFromDate(cappedFrom);
    setToDate(newTo);
    setPaging("none");
  }, [fromDate, today, load, paging]);

  const goNext7 = useCallback(async () => {
    if (paging !== "none") return;
    const newFrom = addDays(fromDate, 7);
    // Cap at MAX_FWD days ahead of today.
    const cappedFrom = daysBetween(today, newFrom) > MAX_FWD - PAGE_DAYS
      ? addDays(today, MAX_FWD - PAGE_DAYS)
      : newFrom;
    const newTo = addDays(cappedFrom, PAGE_DAYS);
    setPaging("fwd");
    await load(cappedFrom, newTo);
    setFromDate(cappedFrom);
    setToDate(newTo);
    setPaging("none");
  }, [fromDate, today, load, paging]);

  const goToday = useCallback(async () => {
    if (paging !== "none") return;
    setPaging("today");
    await load(today, addDays(today, PAGE_DAYS));
    setFromDate(today);
    setToDate(addDays(today, PAGE_DAYS));
    setPaging("none");
    onJumpToToday?.();
  }, [today, load, paging, onJumpToToday]);

  const goDetail = useCallback((c: DayCard) => {
    if (c.workout?.id) router.push(`/workout/${c.workout.id}` as any);
  }, [router]);

  const isViewingToday = fromDate === today;
  const canGoBack = daysBetween(addDays(fromDate, -7), today) <= MAX_BACK;
  const canGoFwd  = daysBetween(today, fromDate) < MAX_FWD - PAGE_DAYS;

  return (
    <View>
      <View style={styles.headerRow}>
        <Text style={styles.headerTitle}>YOUR CALENDAR</Text>
        <Text style={styles.rangeT}>{niceDate(fromDate)}  →  {niceDate(toDate)}</Text>
      </View>

      {loading && days.length === 0 ? (
        <ActivityIndicator color={theme.color.brand} style={{ marginTop: 20 }} />
      ) : (
        <>
          {/* Iter 95e — paged navigation (Prev 7 / Today / Next 7) */}
          <View style={styles.pagerRow}>
            <Pressable
              onPress={goPrev7}
              disabled={paging !== "none" || !canGoBack}
              style={[styles.pagerBtn, (!canGoBack || paging !== "none") && styles.pagerBtnDisabled]}
              testID="cal-prev-7"
            >
              {paging === "back" ? (
                <ActivityIndicator color={theme.color.text} size="small" />
              ) : (
                <>
                  <Ionicons name="chevron-back" size={14} color={theme.color.text} />
                  <Text style={styles.pagerT}>PREV 7</Text>
                </>
              )}
            </Pressable>

            <Pressable
              onPress={goToday}
              disabled={paging !== "none" || isViewingToday}
              style={[
                styles.pagerBtn,
                styles.pagerBtnToday,
                (isViewingToday || paging !== "none") && styles.pagerBtnDisabled,
              ]}
              testID="cal-today"
            >
              {paging === "today" ? (
                <ActivityIndicator color={theme.color.brand} size="small" />
              ) : (
                <>
                  <Ionicons name="today" size={14} color={theme.color.brand} />
                  <Text style={[styles.pagerT, { color: theme.color.brand }]}>TODAY</Text>
                </>
              )}
            </Pressable>

            <Pressable
              onPress={goNext7}
              disabled={paging !== "none" || !canGoFwd}
              style={[styles.pagerBtn, (!canGoFwd || paging !== "none") && styles.pagerBtnDisabled]}
              testID="cal-next-7"
            >
              {paging === "fwd" ? (
                <ActivityIndicator color={theme.color.text} size="small" />
              ) : (
                <>
                  <Text style={styles.pagerT}>NEXT 7</Text>
                  <Ionicons name="chevron-forward" size={14} color={theme.color.text} />
                </>
              )}
            </Pressable>
          </View>

          {days.map((c) => (
            <View
              key={c.date}
              onLayout={(e) => {
                if (c.is_today) onTodayLayoutY?.(e.nativeEvent.layout.y);
              }}
            >
              <DayRow
                card={c}
                onOpenWorkout={() => goDetail(c)}
                onLongPress={() => onLongPressDay?.(c.date)}
                onRecover={() => setActiveRecovery(c)}
                onMove={() => setMoveSource(c)}
              />
            </View>
          ))}
        </>
      )}

      <RecoverySheet
        visible={!!activeRecovery && activeRecovery.badge === "missed" && !!activeRecovery.workout?.id}
        workout={
          activeRecovery?.workout
            ? {
                id: activeRecovery.workout.id,
                title: activeRecovery.workout.title,
                date: activeRecovery.date,
                days_ago: daysBetween(activeRecovery.date, today),
                key_session: activeRecovery.workout.key_session,
                priority: activeRecovery.priority || undefined,
              }
            : null
        }
        onClose={() => setActiveRecovery(null)}
        onDone={() => {
          setActiveRecovery(null);
          load(fromDate, toDate);
        }}
      />

      <MoveWorkoutSheet
        visible={!!moveSource && !!moveSource.workout?.id}
        source={
          moveSource?.workout
            ? {
                workoutId: moveSource.workout.id,
                fromDate: moveSource.date,
                title: moveSource.workout.title || null,
                key_session: moveSource.workout.key_session || null,
              }
            : null
        }
        onClose={() => setMoveSource(null)}
        onMoved={() => {
          setMoveSource(null);
          load(fromDate, toDate);
        }}
      />
    </View>
  );
}

function DayRow({
  card,
  onOpenWorkout,
  onLongPress,
  onRecover,
  onMove,
}: {
  card: DayCard;
  onOpenWorkout: () => void;
  onLongPress?: () => void;
  onRecover: () => void;
  onMove?: () => void;
}) {
  const bs = badgeStyle(card.badge);
  const rd = card.roster_day || null;
  const dl = niceDate(card.date);
  const acts = card.activities || [];

  // Iter 95f — proper duty-context chip.
  // Every day gets at least one chip so clients see where/what they are.
  // Iter 106 — pass the workout so we can infer LAYOVER / TURNAROUND from
  // the workout title when the roster day has no explicit day_type set
  // (which was causing layover cards to display a wrong HOME icon).
  const dutyChip = buildDutyChip(rd, card.workout);

  // Iter 113 — proper duty info block. Previously the flight number,
  // layover city and turnaround details were compressed into a tiny top-
  // right icon dot which clients missed entirely. Now every roster day
  // that has any real context shows a dedicated info row under the
  // workout/rest title:
  //   • flight legs: "EK770  NBO → AUH  07:05–13:15"
  //   • layover city: "Layover · Nairobi (NBO)"
  //   • standby / sim / training / early / night flags
  const _flights = (rd?.flights || []).map((f) => {
    const num = f.flight_number || f.number || "";
    const org = f.origin || f.from || "";
    const dst = f.destination || f.to || "";
    const dep = f.dep_time || "";
    const arr = f.arr_time || "";
    const aircraft = f.aircraft || "";
    const route = org && dst ? `${org} → ${dst}` : (org || dst);
    const times = dep && arr ? `${dep}–${arr}` : (dep || arr);
    // Compose "EK770  NBO → AUH  07:05–13:15"
    const parts = [num, route, times].filter(Boolean).join("  ");
    return { key: `${num}-${dep}-${org}`, text: parts, aircraft };
  }).filter((x) => !!x.text);

  const _rawDuty = String(rd?.day_type || "").toLowerCase();
  const _hasLayover = !!rd?.layover_city;
  const _hasDutyContext =
    _flights.length > 0
    || _hasLayover
    || (!!_rawDuty && !_isRestish(rd || { day_type: _rawDuty }));

  const isMissed = card.badge === "missed";
  const canRecover = isMissed
    && !!card.workout?.id
    && !card.workout?.coach_locked
    && card.priority !== "optional_recovery";

  // A session can be moved if it's a real planned/upcoming workout the client
  // hasn't already done or missed. Missed → use RECOVER instead.
  const canMove = !!card.workout?.id
    && !card.workout?.completed
    && !card.workout?.skipped
    && !card.workout?.coach_locked
    && !isMissed
    && !card.is_past
    && card.badge !== "rest";

  const barColor = card.workout
    ? loadColor(card.workout.day_load || rd?.load)
    : (rd ? loadColor(rd.load) : theme.color.textDim);

  return (
    <Pressable
      onPress={card.workout ? onOpenWorkout : undefined}
      onLongPress={onLongPress}
      delayLongPress={350}
      style={[
        styles.row,
        card.is_today && styles.rowToday,
        isMissed && styles.rowMissed,
      ]}
      testID={`cal-day-${card.date}`}
    >
      <View style={[styles.loadBar, { backgroundColor: barColor }]} />
      <View style={{ flex: 1, minWidth: 0 }}>
        <View style={styles.rowHead}>
          <View style={{ flex: 1 }}>
            <Text style={[styles.date, card.is_today && { color: theme.color.brand }]}>
              {card.is_today ? "TODAY" : dl.toUpperCase()}
            </Text>
            {card.is_today ? <Text style={styles.dateSub}>{dl}</Text> : null}
          </View>
          {/* Iter 95h — duty status now lives as a small icon dot in the
              top-right, next to the workout status badge. Cleaner than the
              old bottom chip row. */}
          <View style={styles.rowHeadRight}>
            <DutyIconDot chip={dutyChip} />
            <View style={[styles.badge, { backgroundColor: bs.bg }]}>
              <Text style={[styles.badgeT, { color: bs.fg }]}>{bs.label}</Text>
            </View>
          </View>
        </View>

        {card.workout ? (
          <>
            <Text style={styles.title} numberOfLines={1}>{card.workout.title || "Session"}</Text>
            <Text style={styles.meta} numberOfLines={1}>
              {card.workout.location || dutyChip.label}
              {card.workout.estimated_minutes ? ` · ${card.workout.estimated_minutes}min` : ""}
              {card.workout.intensity_target ? `  ·  ${String(card.workout.intensity_target).toUpperCase()}` : ""}
              {card.workout.key_session ? "  ·  KEY" : ""}
            </Text>
            {/* Iter 112 — Engine V2 "why this?" rationale + priority pill.
                Only rendered when the workout came from Engine V2 (source
                marker). Legacy V1 workouts keep their existing quiet layout. */}
            {card.workout.source === "engine_v2" && card.workout.rationale ? (
              <View style={styles.v2Reason}>
                <Ionicons name="sparkles-outline" size={11} color={theme.color.brand} />
                <Text style={styles.v2ReasonText} numberOfLines={2}>
                  {card.workout.rationale}
                </Text>
              </View>
            ) : null}
            {card.workout.source === "engine_v2" && card.workout.priority ? (
              <View style={styles.v2PillRow}>
                <View
                  style={[
                    styles.v2Pill,
                    (String(card.workout.priority).toUpperCase() === "KEY") && { borderColor: theme.color.brand },
                  ]}
                >
                  <Text style={styles.v2PillText}>
                    {String(card.workout.priority).toUpperCase()}
                    {card.workout.exposure_number ? ` · #${card.workout.exposure_number}` : ""}
                  </Text>
                </View>
              </View>
            ) : null}
          </>
        ) : rd && !_isRestish(rd) ? (
          <Text style={styles.titleRest}>REST FROM TRAINING</Text>
        ) : (
          <Text style={styles.titleRest}>REST</Text>
        )}

        {/* Iter 113 — proper duty context surface. Shows the full duty row
            (label + flights + city + load) below the workout/rest title so
            clients can see WHY a rest day exists, or the flight legs on a
            flying day. Non-rest days always render this block. */}
        {_hasDutyContext ? (
          <View style={styles.dutyBox}>
            <View style={styles.dutyHeaderRow}>
              <Ionicons name={dutyChip.icon} size={13} color={dutyChipColors(dutyChip.tone).fg} />
              <Text style={[styles.dutyHeader, { color: dutyChipColors(dutyChip.tone).fg }]}>
                {dutyChip.label.toUpperCase()}
              </Text>
              {_hasLayover ? (
                <Text style={styles.dutyCity} numberOfLines={1}>
                  {"  ·  "}{rd?.layover_city}
                </Text>
              ) : null}
              {rd?.load ? (
                <View style={[styles.dutyLoadPill, { backgroundColor: loadColor(rd.load) }]}>
                  <Text style={styles.dutyLoadPillT}>{String(rd.load).toUpperCase()}</Text>
                </View>
              ) : null}
            </View>
            {_flights.map((f) => (
              <View key={f.key} style={styles.dutyFlightRow}>
                <Ionicons name="airplane" size={11} color={theme.color.brand} />
                <Text style={styles.dutyFlightT} numberOfLines={1}>
                  {f.text}
                </Text>
                {f.aircraft ? (
                  <Text style={styles.dutyFlightAircraft}>{f.aircraft}</Text>
                ) : null}
              </View>
            ))}
          </View>
        ) : null}

        {/* Iter 116 — Aviation Support Layer (Phase A). Rendered as a
            separate labelled section so clients understand these are NOT
            programme training. Cards are compact (icon + title + minutes).
            Coach can override / disable individual interventions via
            db.flight_support_overrides (Phase B). */}
        {(card.flight_support && card.flight_support.length > 0) ? (
          <View style={styles.fsBox}>
            <View style={styles.fsHeader}>
              <Ionicons name="airplane-outline" size={11} color={theme.color.textMuted} />
              <Text style={styles.fsHeaderT}>FLIGHT SUPPORT</Text>
              <Text style={styles.fsHeaderHint}>Not counted as training</Text>
            </View>
            {card.flight_support.map((it) => (
              <View key={it.id} style={styles.fsRow}>
                <View style={[styles.fsIconWrap, {
                  backgroundColor: fsFamilyColor(it.family) + "22",
                  borderColor: fsFamilyColor(it.family),
                }]}>
                  <Ionicons
                    name={fsFamilyIcon(it.family) as any}
                    size={12}
                    color={fsFamilyColor(it.family)}
                  />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.fsTitle} numberOfLines={1}>
                    {it.title}
                    {it.bundle_title ? (
                      <Text style={styles.fsBundleHint}>  ·  {it.bundle_title}</Text>
                    ) : null}
                  </Text>
                  {it.trigger_reason ? (
                    <Text style={styles.fsReason} numberOfLines={1}>
                      {it.trigger_reason}
                    </Text>
                  ) : null}
                </View>
                <Text style={styles.fsDuration}>{it.duration_min}m</Text>
              </View>
            ))}
          </View>
        ) : null}

        {acts.map((a) => (
          <View key={a.id} style={styles.actChip}>
            <Ionicons name="tennisball" size={11} color={theme.color.brand} />
            <Text style={styles.actChipT} numberOfLines={1}>
              {a.activity_name}{a.duration_minutes ? ` · ${a.duration_minutes}m` : ""}
            </Text>
          </View>
        ))}

        {card.client_copy?.body ? (
          <Text style={styles.missedCopy} numberOfLines={3}>{card.client_copy.body}</Text>
        ) : null}

        {isMissed && canRecover ? (
          <View style={styles.missedActions}>
            <Pressable
              onPress={(e) => { e.stopPropagation?.(); onRecover(); }}
              style={[styles.mBtn, styles.mBtnPrimary]}
              testID={`cal-recover-${card.date}`}
            >
              <Text style={styles.mBtnPrimaryT}>RECOVER</Text>
            </Pressable>
          </View>
        ) : canMove ? (
          <View style={styles.missedActions}>
            <Pressable
              onPress={(e) => { e.stopPropagation?.(); onMove?.(); }}
              style={[styles.mBtn, styles.mBtnGhost]}
              testID={`cal-move-${card.date}`}
              hitSlop={6}
            >
              <Ionicons name="swap-horizontal" size={13} color={theme.color.brand} />
              <Text style={styles.mBtnGhostT}>MOVE TO ANOTHER DAY</Text>
            </Pressable>
          </View>
        ) : null}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  headerRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    marginBottom: 12,
  },
  headerTitle: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  rangeT: {
    color: theme.color.textMuted,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.5,
  },
  // Iter 95e — paged 7-day navigation
  pagerRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
    marginBottom: 12,
  },
  pagerBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 4,
    paddingVertical: 10,
    paddingHorizontal: 10,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: theme.color.border,
    backgroundColor: theme.color.surface2,
  },
  pagerBtnToday: {
    borderColor: theme.color.brand,
    backgroundColor: theme.color.brandTint,
  },
  pagerBtnDisabled: {
    opacity: 0.4,
  },
  pagerT: {
    color: theme.color.text,
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 1.5,
  },
  todayBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8,
    borderWidth: 1, borderColor: theme.color.border,
  },
  todayBtnT: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },

  loadMoreBtn: {
    padding: 12, borderRadius: 10, borderWidth: 1, borderColor: theme.color.border,
    alignItems: "center", marginBottom: 8, backgroundColor: theme.color.surface2,
    flexDirection: "row", justifyContent: "center", gap: 6,
  },
  pastBtn: { backgroundColor: theme.color.surface },
  loadMoreT: { color: theme.color.textMuted, fontSize: 10, fontWeight: "900", letterSpacing: 2 },

  row: {
    flexDirection: "row", alignItems: "stretch",
    backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.md,
    borderWidth: 1, borderColor: theme.color.border,
    marginBottom: 8, overflow: "hidden",
  },
  rowToday: { borderColor: theme.color.brand, backgroundColor: theme.color.brandTint },
  rowMissed: { borderColor: theme.color.red, backgroundColor: "rgba(239,68,68,0.06)" },
  loadBar: { width: 4, backgroundColor: theme.color.border },
  rowHead: { flexDirection: "row", alignItems: "flex-start", padding: 12, paddingBottom: 4 },

  date: { color: theme.color.text, fontSize: 12, fontWeight: "900", letterSpacing: 1.5 },
  dateSub: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },

  badge: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 10 },
  badgeT: { fontSize: 9, fontWeight: "900", letterSpacing: 1.5 },

  title: { color: theme.color.text, fontSize: 14, fontWeight: "800", paddingHorizontal: 12, marginTop: 2 },
  titleRest: { color: theme.color.textMuted, fontSize: 12, fontWeight: "800", paddingHorizontal: 12, marginTop: 2, letterSpacing: 1 },
  meta: { color: theme.color.textMuted, fontSize: 11, paddingHorizontal: 12, marginTop: 3 },
  // Iter 113 — duty info block (flights + layover city + load)
  dutyBox: {
    marginHorizontal: 12, marginTop: 8, paddingHorizontal: 10, paddingVertical: 8,
    backgroundColor: theme.color.surface2, borderRadius: theme.radius.sm,
    borderWidth: 1, borderColor: theme.color.border,
    gap: 4,
  },
  dutyHeaderRow: {
    flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 4,
  },
  dutyHeader: {
    fontSize: 11, fontWeight: "800", letterSpacing: 1.2,
  },
  dutyCity: {
    color: theme.color.textMuted, fontSize: 11, fontWeight: "600", flex: 1, minWidth: 0,
  },
  dutyLoadPill: {
    paddingHorizontal: 6, paddingVertical: 2, borderRadius: 6, marginLeft: "auto",
  },
  dutyLoadPillT: {
    color: "#fff", fontSize: 9, fontWeight: "800", letterSpacing: 1,
  },
  dutyFlightRow: {
    flexDirection: "row", alignItems: "center", gap: 6, paddingTop: 2,
  },
  dutyFlightT: {
    color: theme.color.text, fontSize: 11, fontWeight: "600", flex: 1, minWidth: 0,
  },
  dutyFlightAircraft: {
    color: theme.color.textMuted, fontSize: 10, fontWeight: "700",
  },
  // Iter 116 — Aviation Support (Phase A) rendering
  fsBox: {
    marginHorizontal: 12, marginTop: 8, paddingHorizontal: 10, paddingVertical: 8,
    backgroundColor: theme.color.surface2, borderRadius: theme.radius.sm,
    borderWidth: 1, borderColor: theme.color.border,
    borderLeftWidth: 3, borderLeftColor: theme.color.brand,
    gap: 6,
  },
  fsHeader: {
    flexDirection: "row", alignItems: "center", gap: 6,
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
    paddingBottom: 6,
  },
  fsHeaderT: {
    color: theme.color.text, fontSize: 10, fontWeight: "800", letterSpacing: 1.2,
  },
  fsHeaderHint: {
    color: theme.color.textMuted, fontSize: 9, fontWeight: "600",
    fontStyle: "italic", marginLeft: "auto",
  },
  fsRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
  },
  fsIconWrap: {
    width: 22, height: 22, borderRadius: 11,
    alignItems: "center", justifyContent: "center",
    borderWidth: 1,
  },
  fsTitle: {
    color: theme.color.text, fontSize: 12, fontWeight: "700",
  },
  fsBundleHint: {
    color: theme.color.textMuted, fontSize: 10, fontWeight: "600",
    fontStyle: "italic",
  },
  fsReason: {
    color: theme.color.textMuted, fontSize: 10, marginTop: 1,
  },
  fsDuration: {
    color: theme.color.brand, fontSize: 12, fontWeight: "700",
    minWidth: 32, textAlign: "right",
  },
  // Iter 112 — V2 rationale + priority pill styles
  v2Reason: {
    flexDirection: "row", alignItems: "flex-start", gap: 6,
    paddingHorizontal: 12, marginTop: 6, paddingRight: 12,
  },
  v2ReasonText: {
    color: theme.color.text, fontSize: 11, lineHeight: 15, flex: 1,
    fontStyle: "italic", opacity: 0.9,
  },
  v2PillRow: {
    flexDirection: "row", flexWrap: "wrap", gap: 6,
    paddingHorizontal: 12, marginTop: 6,
  },
  v2Pill: {
    borderWidth: 1, borderColor: theme.color.border,
    borderRadius: 8, paddingHorizontal: 8, paddingVertical: 3,
    backgroundColor: theme.color.surface2,
  },
  v2PillText: {
    color: theme.color.textMuted, fontSize: 10, fontWeight: "700",
    letterSpacing: 0.8,
  },
  duty: { color: theme.color.textMuted, fontSize: 11, paddingHorizontal: 12, marginTop: 3, fontStyle: "italic" },

  actChip: {
    flexDirection: "row", alignItems: "center", gap: 4,
    alignSelf: "flex-start", marginHorizontal: 12, marginTop: 6,
    paddingHorizontal: 8, paddingVertical: 3,
    borderRadius: 12, backgroundColor: theme.color.brandTint,
  },
  actChipT: { color: theme.color.brand, fontSize: 10, fontWeight: "800" },

  // Iter 95h — duty context lives inline in the top-right of every day
  // card as a small round icon dot. If there is extra roster context
  // (flight number, layover city) it appears as a compact pill below.
  rowHeadRight: { flexDirection: "row", alignItems: "center", gap: 8 },
  dutyDot: {
    width: 24, height: 24, borderRadius: 12,
    alignItems: "center", justifyContent: "center",
    borderWidth: 1,
  },
  chipRow: {
    flexDirection: "row", flexWrap: "wrap", gap: 6,
    paddingHorizontal: 12, marginTop: 8,
  },
  chip: {
    flexDirection: "row", alignItems: "center", gap: 5,
    paddingHorizontal: 8, paddingVertical: 3,
    borderRadius: 10, borderWidth: 1,
  },
  chipSmall: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 8 },
  chipT: { fontSize: 10, fontWeight: "800", letterSpacing: 0.4 },
  chipTSmall: { fontSize: 9, letterSpacing: 0.3 },

  missedCopy: { color: theme.color.textMuted, fontSize: 12, paddingHorizontal: 12, marginTop: 6, lineHeight: 17 },
  missedActions: { flexDirection: "row", gap: 8, padding: 12, paddingTop: 8 },
  mBtn: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8, flexDirection: "row", alignItems: "center", gap: 6 },
  mBtnPrimary: { backgroundColor: theme.color.brand },
  mBtnPrimaryT: { color: "#fff", fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },
  mBtnGhost: { backgroundColor: "transparent", borderWidth: 1, borderColor: theme.color.brand },
  mBtnGhostT: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },
});
