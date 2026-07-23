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
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { theme, loadColor } from "@/src/lib/theme";
import { RecoverySheet } from "./RecoverySheet";

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
  } | null;
  roster_day?: {
    day_type?: string;
    layover_city?: string;
    flights?: { number?: string; from?: string; to?: string }[];
    load?: string;
  } | null;
  activities?: any[];
  client_copy?: { title?: string; body?: string; recommendation?: string } | null;
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

function buildDutyChip(rd: DayCard["roster_day"] | null): DutyChip {
  const raw = String(rd?.day_type || "").toLowerCase();
  const map: Record<string, DutyChip> = {
    long_haul:      { label: "Long-Haul Flight", icon: "airplane", tone: "brand" },
    "long-haul":    { label: "Long-Haul Flight", icon: "airplane", tone: "brand" },
    short_haul:     { label: "Short-Haul",       icon: "airplane", tone: "brand" },
    flight_day:     { label: "Flying",           icon: "airplane", tone: "brand" },
    flying:         { label: "Flying",           icon: "airplane", tone: "brand" },
    layover_full:   { label: "Layover",          icon: "bed",      tone: "amber" },
    layover:        { label: "Layover",          icon: "bed",      tone: "amber" },
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
    </View>
  );
}

function DayRow({
  card,
  onOpenWorkout,
  onLongPress,
  onRecover,
}: {
  card: DayCard;
  onOpenWorkout: () => void;
  onLongPress?: () => void;
  onRecover: () => void;
}) {
  const bs = badgeStyle(card.badge);
  const rd = card.roster_day || null;
  const flightNo = rd?.flights?.[0]?.number;
  const dl = niceDate(card.date);
  const acts = card.activities || [];

  // Iter 95f — proper duty-context chip.
  // Every day gets at least one chip so clients see where/what they are.
  const dutyChip = buildDutyChip(rd);
  const flightChip = flightNo ? { label: `Flight ${flightNo}`, icon: "airplane" as const, tone: "brand" as const } : null;
  const layoverChip = rd?.layover_city
    ? { label: rd.layover_city, icon: "location" as const, tone: "muted" as const }
    : null;

  const isMissed = card.badge === "missed";
  const canRecover = isMissed
    && !!card.workout?.id
    && !card.workout?.coach_locked
    && card.priority !== "optional_recovery";

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
              {card.workout.key_session ? "  ·  KEY" : ""}
            </Text>
          </>
        ) : rd && !_isRestish(rd) ? (
          <Text style={styles.titleRest}>REST FROM TRAINING</Text>
        ) : (
          <Text style={styles.titleRest}>REST</Text>
        )}

        {/* Iter 95h — only surface a chip row when there's genuine extra
            context beyond the top-right duty dot (i.e. a flight number or
            layover city). Keeps the base card visually clean. */}
        {(flightChip || layoverChip) ? (
          <View style={styles.chipRow}>
            {flightChip ? <DutyChipView chip={flightChip} small /> : null}
            {layoverChip ? <DutyChipView chip={layoverChip} small /> : null}
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
  mBtn: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8 },
  mBtnPrimary: { backgroundColor: theme.color.brand },
  mBtnPrimaryT: { color: "#fff", fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },
});
