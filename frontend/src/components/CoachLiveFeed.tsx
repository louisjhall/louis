/**
 * CoachLiveFeed — Phase 2.
 *
 * Live feed rendered on the main coach dashboard showing upcoming workouts
 * across all of the coach's clients. Includes:
 *   - Summary cards (today / tomorrow / needs review / needs media / heavy
 *     duty / layover / missed) that toggle the active filter.
 *   - Filter chips (all/needs_review/needs_media/heavy/layover/today/missed).
 *   - Priority-sorted list of workout cards. Each card shows the client,
 *     the roster context, the training colour, the workout summary, and
 *     inline flag badges. Tapping the workout deeplinks to the existing
 *     coach workout editor.
 *
 * Backed by GET /api/coach/live-feed.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable,
  ActivityIndicator,
} from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { WorkoutQuickActions, type WorkoutQuickActionTarget } from "@/src/components/WorkoutQuickActions";


type Filter =
  | "all" | "today" | "needs_review" | "needs_media"
  | "heavy_duty" | "layover" | "post_night" | "missed";

type FeedItem = {
  workout_id: string;
  client: { id: string; name?: string; photo_url?: string; email?: string; airline?: string; role?: string };
  date: string;
  day_offset: number;
  day_offset_label: string;
  roster_day: {
    day_type?: string;
    client_label?: string;
    training_colour?: "green" | "amber" | "red" | "black";
    label?: string;
    blocked?: string[];
    equipment_assumption?: string;
    reason?: string;
    layover_city?: string | null;
    hotel_name?: string | null;
    flights?: { from?: string; to?: string; flight_number?: string }[];
    report_time?: string | null;
    release_time?: string | null;
    needs_review?: boolean;
    source?: string | null;
  };
  workout: {
    id?: string;
    title?: string;
    focus?: string;
    duration_min?: number;
    day_load?: string;
    exercise_count?: number;
    missing_media_count?: number;
    approved?: boolean;
    coach_locked?: boolean;
    completed?: boolean;
    rationale?: string;
    parser_enforced?: boolean;
  };
  flags: string[];
  priority: number;
};

type FeedResponse = {
  generated_at: string;
  range: { start: string; end: string; days: number; include_missed: boolean };
  summary: {
    total: number; today: number; tomorrow: number;
    needs_review: number; needs_media: number;
    heavy_duty: number; layover_sessions: number;
    post_night_recovery: number; missed: number;
    roster_uncertain: number;
    by_client: Record<string, number>;
    by_airline: Record<string, number>;
    by_colour: Record<string, number>;
  };
  items: FeedItem[];
};

const TL: Record<string, string> = {
  green: "#3DBE6E", amber: "#E5A048", red: "#E15A5A", black: "#5A5A5A",
};

// Filter → API filter string
const FILTER_LABELS: Record<Filter, string> = {
  all: "All",
  today: "Today",
  needs_review: "Needs review",
  needs_media: "Needs media",
  heavy_duty: "Heavy duty",
  layover: "Layover",
  post_night: "Post-night",
  missed: "Missed",
};

const FLAG_BADGE_STYLE: Record<string, { bg: string; fg: string; label: string }> = {
  today: { bg: "#E15A5A", fg: "#fff", label: "TODAY" },
  tomorrow: { bg: "#a1611c", fg: "#fff", label: "TOMORROW" },
  missed: { bg: "#c85450", fg: "#fff", label: "MISSED" },
  needs_media: { bg: "#c85450", fg: "#fff", label: "NEEDS MEDIA" },
  needs_review: { bg: "#E5A048", fg: "#fff", label: "NEEDS REVIEW" },
  heavy_duty: { bg: "#7d3c2c", fg: "#fff", label: "HEAVY DUTY" },
  layover: { bg: "#3a4a6b", fg: "#fff", label: "LAYOVER" },
  layover_unknown_equip: { bg: "#3a4a6b", fg: "#fff", label: "EQUIP TBC" },
  post_night_recovery: { bg: "#4a3f6b", fg: "#fff", label: "POST-NIGHT" },
  hotel_gym_unknown: { bg: "transparent", fg: "#888", label: "HOTEL GYM ?" },
  roster_uncertain: { bg: "#7a5a2b", fg: "#fff", label: "ROSTER UNCLEAR" },
  edited_by_louis: { bg: "transparent", fg: "#3DBE6E", label: "EDITED BY LOUIS" },
  ready: { bg: "transparent", fg: "#3DBE6E", label: "READY" },
};

const fmtDate = (d: string): string => {
  try {
    const dt = new Date(d + "T00:00:00");
    return dt.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  } catch {
    return d;
  }
};


export function CoachLiveFeed() {
  const router = useRouter();
  const [feed, setFeed] = useState<FeedResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<Filter>("all");
  const [days, setDays] = useState<5 | 7>(5);
  const [error, setError] = useState<string | null>(null);
  // Phase 4 — quick action target
  const [qaTarget, setQaTarget] = useState<WorkoutQuickActionTarget | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const qs = new URLSearchParams({ days: String(days) });
      if (filter !== "all") qs.set("filter", filter);
      const r = await api<FeedResponse>(`/coach/live-feed?${qs.toString()}`);
      setFeed(r);
    } catch (e: any) {
      const msg = String(e?.message || "");
      if (!/missing token/i.test(msg)) setError(msg || "Couldn't load feed");
    } finally {
      setLoading(false);
    }
  }, [filter, days]);

  useEffect(() => { load(); }, [load]);

  const summary = feed?.summary;

  const summaryCards: {
    key: Filter; label: string; value: number; icon: any; tint: string;
  }[] = useMemo(() => ([
    { key: "today", label: "TODAY", value: summary?.today ?? 0, icon: "sunny", tint: "#E15A5A" },
    { key: "missed", label: "MISSED", value: summary?.missed ?? 0, icon: "close-circle", tint: "#c85450" },
    { key: "needs_review", label: "NEEDS REVIEW", value: summary?.needs_review ?? 0, icon: "alert-circle", tint: "#E5A048" },
    { key: "needs_media", label: "NEEDS MEDIA", value: summary?.needs_media ?? 0, icon: "images", tint: "#c85450" },
    { key: "heavy_duty", label: "HEAVY DUTY", value: summary?.heavy_duty ?? 0, icon: "flame", tint: "#7d3c2c" },
    { key: "layover", label: "LAYOVER", value: summary?.layover_sessions ?? 0, icon: "airplane", tint: "#3a4a6b" },
    { key: "post_night", label: "POST-NIGHT", value: summary?.post_night_recovery ?? 0, icon: "moon", tint: "#4a3f6b" },
  ]), [summary]);

  const items = feed?.items || [];

  return (
    <View style={styles.wrap}>
      <View style={styles.headerRow}>
        <View style={{ flex: 1 }}>
          <Text style={styles.h1}>LIVE FEED · NEXT {days} DAYS</Text>
          <Text style={styles.sub}>
            {items.length} workout{items.length === 1 ? "" : "s"} across your clients
            {feed?.range ? ` · ${fmtDate(feed.range.start)} → ${fmtDate(feed.range.end)}` : ""}
          </Text>
        </View>
        <View style={{ flexDirection: "row", gap: 6 }}>
          {([5, 7] as const).map((d) => (
            <Pressable
              key={d}
              testID={`lf-days-${d}`}
              onPress={() => setDays(d)}
              style={[styles.rangeBtn, days === d && styles.rangeBtnActive]}
            >
              <Text style={[styles.rangeBtnT, days === d && styles.rangeBtnTActive]}>{d}D</Text>
            </Pressable>
          ))}
          <Pressable testID="lf-refresh" onPress={load} style={styles.rangeBtn}>
            <Ionicons name="refresh" size={12} color={theme.color.textMuted} />
          </Pressable>
        </View>
      </View>

      {error ? (
        <View style={styles.err}>
          <Ionicons name="alert-circle" size={14} color="#fff" />
          <Text style={styles.errT}>{error}</Text>
        </View>
      ) : null}

      {/* Summary cards */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.summaryRow}
        testID="lf-summary-cards"
      >
        {summaryCards.map((c) => {
          const active = filter === c.key;
          return (
            <Pressable
              key={c.key}
              testID={`lf-sum-${c.key}`}
              onPress={() => setFilter(active ? "all" : c.key)}
              style={[
                styles.sumCard,
                active && { borderColor: c.tint, backgroundColor: c.tint + "22" },
                c.value === 0 && { opacity: 0.55 },
              ]}
            >
              <Ionicons name={c.icon} size={14} color={c.tint} />
              <Text style={[styles.sumV, { color: c.tint }]}>{c.value}</Text>
              <Text style={styles.sumL}>{c.label}</Text>
            </Pressable>
          );
        })}
      </ScrollView>

      {/* Filter chips (all / by day / by colour) */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.chipsRow}
        testID="lf-filter-chips"
      >
        {(["all", "today", "needs_review", "needs_media", "heavy_duty", "layover", "post_night", "missed"] as Filter[]).map((f) => {
          const active = filter === f;
          return (
            <Pressable
              key={f}
              testID={`lf-chip-${f}`}
              onPress={() => setFilter(f)}
              style={[styles.chip, active && styles.chipActive]}
            >
              <Text style={[styles.chipT, active && styles.chipTActive]}>
                {FILTER_LABELS[f].toUpperCase()}
              </Text>
            </Pressable>
          );
        })}
      </ScrollView>

      {/* Feed list */}
      {loading && !feed ? (
        <View style={styles.center}>
          <ActivityIndicator color={theme.color.brand} />
        </View>
      ) : items.length === 0 ? (
        <View style={styles.emptyWrap}>
          <Ionicons name="checkmark-done-circle-outline" size={38} color={theme.color.textMuted} />
          <Text style={styles.emptyT}>Nothing needs your attention</Text>
          <Text style={styles.emptyS}>
            {filter === "all"
              ? "No client workouts in the next window."
              : "No items match this filter. Tap ALL to see everything."}
          </Text>
        </View>
      ) : (
        <View style={{ gap: 10 }}>
          {items.map((it) => (
            <FeedCard
              key={it.workout_id}
              it={it}
              onOpenWorkout={() => router.push(`/coach/workout/edit/${it.workout_id}` as any)}
              onOpenClient={() => router.push(`/coach/client-months/${it.client.id}` as any)}
              onOpenMenu={() => setQaTarget({
                id: it.workout_id,
                title: it.workout.title,
                date: it.date,
                approved: it.workout.approved,
                coach_locked: it.workout.coach_locked,
                missing_media_count: it.workout.missing_media_count,
              })}
            />
          ))}
        </View>
      )}

      {/* Phase 4 — Workout quick action sheet */}
      <WorkoutQuickActions
        visible={!!qaTarget}
        target={qaTarget}
        onClose={() => setQaTarget(null)}
        onChanged={load}
      />
    </View>
  );
}


function FeedCard({
  it, onOpenWorkout, onOpenClient, onOpenMenu,
}: {
  it: FeedItem;
  onOpenWorkout: () => void;
  onOpenClient: () => void;
  onOpenMenu: () => void;
}) {
  const colour = TL[it.roster_day.training_colour || "green"];
  const flags = it.flags.filter((f) => FLAG_BADGE_STYLE[f]);
  const route = (it.roster_day.flights || [])
    .map((f: any) => {
      const org = f.origin || f.from || "";
      const dst = f.destination || f.to || "";
      if (!org && !dst) return "";
      return `${org || "?"}→${dst || "?"}`;
    })
    .filter(Boolean)
    .join(" · ");

  return (
    <View style={styles.card} testID={`lf-card-${it.workout_id}`}>
      <View style={[styles.cardBar, { backgroundColor: colour }]} />
      <View style={{ flex: 1 }}>
        <View style={styles.cardTop}>
          <Pressable
            testID={`lf-client-${it.client.id}`}
            onPress={onOpenClient}
            style={styles.clientRow}
          >
            <View style={styles.avatar}>
              <Text style={styles.avatarT}>
                {((it.client.name || "?")[0] || "?").toUpperCase()}
              </Text>
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.clientName} numberOfLines={1}>{it.client.name}</Text>
              <Text style={styles.clientMeta} numberOfLines={1}>
                {it.client.airline}{it.client.role ? ` · ${it.client.role}` : ""}
              </Text>
            </View>
          </Pressable>
          <View style={styles.dateBox}>
            <Text style={styles.dateT}>{it.day_offset_label.toUpperCase()}</Text>
            <Text style={styles.dateSub}>{fmtDate(it.date)}</Text>
          </View>
        </View>

        {/* Roster context */}
        <View style={styles.rosterRow}>
          <View style={[styles.tlDot, { backgroundColor: colour }]} />
          <Text style={styles.rosterLabel} numberOfLines={1}>
            {it.roster_day.client_label || it.roster_day.day_type || "Duty"}
          </Text>
        </View>
        {route ? (
          <Text style={styles.rosterMeta} numberOfLines={1}>{route}</Text>
        ) : null}
        {(it.roster_day.report_time || it.roster_day.release_time) ? (
          <Text style={styles.rosterMeta} numberOfLines={1}>
            {it.roster_day.report_time ? `Report ${it.roster_day.report_time}` : ""}
            {it.roster_day.report_time && it.roster_day.release_time ? " · " : ""}
            {it.roster_day.release_time ? `Off ${it.roster_day.release_time}` : ""}
          </Text>
        ) : null}

        {/* Workout */}
        <View style={styles.workoutRow}>
          <Pressable
            testID={`lf-open-workout-${it.workout_id}`}
            onPress={onOpenWorkout}
            style={styles.workoutBox}
          >
            <View style={styles.workoutTop}>
              <Text style={styles.workoutTitle} numberOfLines={1}>
                {it.workout.title || "Workout"}
                {it.workout.coach_locked ? "  🔒" : ""}
              </Text>
              <Ionicons name="chevron-forward" size={16} color={theme.color.textMuted} />
            </View>
            <Text style={styles.workoutMeta} numberOfLines={1}>
              {(it.workout.focus || "").toUpperCase()}
              {it.workout.duration_min ? ` · ${it.workout.duration_min}m` : ""}
              {it.workout.exercise_count ? ` · ${it.workout.exercise_count} ex` : ""}
            </Text>
            {it.workout.rationale ? (
              <Text style={styles.workoutRat} numberOfLines={2}>{it.workout.rationale}</Text>
            ) : null}
          </Pressable>
          <Pressable
            testID={`lf-menu-${it.workout_id}`}
            onPress={onOpenMenu}
            hitSlop={10}
            style={styles.feedKebab}
          >
            <Ionicons name="ellipsis-vertical" size={18} color={theme.color.text} />
          </Pressable>
        </View>

        {/* Badges */}
        {flags.length > 0 ? (
          <View style={styles.badgeRow}>
            {flags.map((f) => {
              const s = FLAG_BADGE_STYLE[f];
              return (
                <View
                  key={f}
                  style={[
                    styles.badge,
                    { backgroundColor: s.bg, borderColor: s.bg === "transparent" ? s.fg : s.bg },
                  ]}
                >
                  <Text style={[styles.badgeT, { color: s.fg }]}>{s.label}</Text>
                </View>
              );
            })}
          </View>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { paddingVertical: 4 },
  headerRow: {
    flexDirection: "row", alignItems: "flex-start", gap: 8,
    marginBottom: 10,
  },
  h1: { color: theme.color.text, fontSize: 12, fontWeight: "900", letterSpacing: 2 },
  sub: { color: theme.color.textMuted, fontSize: 11, marginTop: 3 },
  rangeBtn: {
    paddingHorizontal: 8, paddingVertical: 6,
    borderRadius: theme.radius.sm,
    borderWidth: 1, borderColor: theme.color.border,
    minWidth: 36, alignItems: "center", justifyContent: "center",
  },
  rangeBtnActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  rangeBtnT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1 },
  rangeBtnTActive: { color: "#fff" },
  err: {
    flexDirection: "row", gap: 6, alignItems: "center",
    backgroundColor: "#c85450", padding: 8, borderRadius: 8,
    marginBottom: 8,
  },
  errT: { color: "#fff", fontSize: 11, flex: 1 },
  summaryRow: {
    gap: 8, paddingRight: 8, paddingBottom: 8,
  },
  sumCard: {
    minWidth: 96,
    paddingHorizontal: 10, paddingVertical: 8,
    borderRadius: 10,
    borderWidth: 1, borderColor: theme.color.border,
    backgroundColor: theme.color.surface2,
    alignItems: "center", gap: 2,
  },
  sumV: { fontSize: 18, fontWeight: "900" },
  sumL: { color: theme.color.textMuted, fontSize: 11, fontWeight: "800", letterSpacing: 1 },
  chipsRow: { gap: 6, paddingRight: 8, paddingBottom: 12 },
  chip: {
    paddingHorizontal: 10, paddingVertical: 6,
    borderRadius: theme.radius.pill,
    borderWidth: 1, borderColor: theme.color.border,
    backgroundColor: theme.color.surface2,
  },
  chipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "800", letterSpacing: 1 },
  chipTActive: { color: "#fff" },
  center: { padding: 30, alignItems: "center" },
  emptyWrap: { padding: 30, alignItems: "center", gap: 8 },
  emptyT: { color: theme.color.text, fontSize: 13, fontWeight: "700", marginTop: 6 },
  emptyS: { color: theme.color.textMuted, fontSize: 11, textAlign: "center", maxWidth: 280 },
  card: {
    flexDirection: "row",
    padding: 12, gap: 10,
    borderRadius: theme.radius.md,
    borderWidth: 1, borderColor: theme.color.border,
    backgroundColor: theme.color.surface2,
  },
  cardBar: { width: 4, borderRadius: 2 },
  cardTop: {
    flexDirection: "row", alignItems: "flex-start", gap: 10, marginBottom: 6,
  },
  clientRow: {
    flexDirection: "row", alignItems: "center", gap: 8, flex: 1,
  },
  avatar: {
    width: 32, height: 32, borderRadius: 16,
    backgroundColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
  },
  avatarT: { color: "#fff", fontWeight: "900", fontSize: 12 },
  clientName: { color: theme.color.text, fontSize: 13, fontWeight: "800" },
  clientMeta: { color: theme.color.textMuted, fontSize: 11, marginTop: 1 },
  dateBox: { alignItems: "flex-end" },
  dateT: { color: theme.color.text, fontSize: 11, fontWeight: "900", letterSpacing: 1 },
  dateSub: { color: theme.color.textMuted, fontSize: 11, marginTop: 1 },
  rosterRow: {
    flexDirection: "row", alignItems: "center", gap: 6,
    marginTop: 4,
  },
  tlDot: { width: 8, height: 8, borderRadius: 4 },
  rosterLabel: { color: theme.color.text, fontSize: 12, fontWeight: "700", flex: 1 },
  rosterMeta: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },
  workoutRow: {
    flexDirection: "row",
    alignItems: "stretch",
    gap: 6,
    marginTop: 8,
  },
  workoutBox: {
    flex: 1,
    padding: 10,
    borderRadius: theme.radius.sm,
    backgroundColor: theme.color.surface,
    borderWidth: 1, borderColor: theme.color.border,
  },
  feedKebab: {
    paddingHorizontal: 10,
    justifyContent: "center",
    alignItems: "center",
    borderRadius: theme.radius.sm,
    backgroundColor: theme.color.surface,
    borderWidth: 1, borderColor: theme.color.border,
  },
  workoutTop: { flexDirection: "row", alignItems: "center", gap: 6 },
  workoutTitle: { flex: 1, color: theme.color.text, fontSize: 13, fontWeight: "800" },
  workoutMeta: { color: theme.color.textMuted, fontSize: 11, marginTop: 3, letterSpacing: 0.5 },
  workoutRat: { color: theme.color.textDim, fontSize: 11, marginTop: 5, fontStyle: "italic" },
  badgeRow: { flexDirection: "row", flexWrap: "wrap", gap: 5, marginTop: 8 },
  badge: {
    paddingHorizontal: 7, paddingVertical: 3,
    borderRadius: theme.radius.pill,
    borderWidth: 1,
  },
  badgeT: { fontSize: 11, fontWeight: "900", letterSpacing: 0.7 },
});
