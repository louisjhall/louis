/**
 * Coach Calendar — cross-client operational view (Iter 128i)
 *
 * Answers: "What are all my clients doing over the next 7 / 14 / 28 days,
 * and does anything in their schedule need my attention?"
 *
 * NOT: the detailed per-client planning workspace. NOT: a debug feed. NOT:
 * a legacy V1 roster/workout dump.
 *
 * Backend: /api/v2/coach/calendar (current V2 Live data only; test/sandbox
 * accounts excluded unless `include_test=1`).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View,
} from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Roster = {
  classification: string;
  classification_label: string;
  duty_burden_band?: string | null;
};
type Training = {
  id: string;
  kind: string;
  label: string;
  duration_min?: number | null;
  key: boolean;
  intensity?: string | null;
};
type FlightItem = {
  id?: string;
  title: string;
  duration_min?: number | null;
  family?: string | null;
  is_bundle?: boolean;
};
type DayCell = {
  date: string;
  roster: Roster | null;
  trainings: Training[];
  flight_support: FlightItem[];
  is_rest: boolean;
};
type Row = {
  client_id: string;
  name: string;
  role_line?: string | null;
  avatar_url?: string | null;
  goal_label: string;
  phase_label?: string | null;
  plan_state: "live" | "draft_only" | "no_plan";
  has_roster: boolean;
  has_new_draft: boolean;
  days: DayCell[];
  content_present: boolean;
};
type CalendarResp = {
  start_date: string;
  end_date: string;
  days_count: number;
  dates: string[];
  clients: Row[];
  excluded_test_count: number;
};

const DEFAULT_RANGE = 7;

function fmtDay(iso: string): { dow: string; ddmm: string; isToday: boolean; isWeekend: boolean } {
  const d = new Date(iso + "T00:00:00");
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const isToday = d.getTime() === today.getTime();
  const isWeekend = d.getDay() === 0 || d.getDay() === 6;
  return {
    dow: d.toLocaleDateString("en-GB", { weekday: "short" }).toUpperCase(),
    ddmm: d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" }).toUpperCase(),
    isToday,
    isWeekend,
  };
}

function fmtRange(fromIso: string, toIso: string): string {
  const f = new Date(fromIso + "T00:00:00");
  const t = new Date(toIso + "T00:00:00");
  const fmt = (d: Date, y: boolean) => d.toLocaleDateString("en-GB", {
    day: "numeric", month: "short", ...(y ? { year: "numeric" } : {}),
  });
  const sameYear = f.getFullYear() === t.getFullYear();
  return `${fmt(f, false)} – ${fmt(t, !sameYear)}`;
}

export default function CoachCalendarScreen() {
  const router = useRouter();
  const [days, setDays] = useState<number>(DEFAULT_RANGE);
  const [start, setStart] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [dq, setDq] = useState("");
  const [needsAttentionOnly, setNAOnly] = useState(false);
  const [data, setData] = useState<CalendarResp | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => { const t = setTimeout(() => setDq(q.trim()), 200); return () => clearTimeout(t); }, [q]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("days", String(days));
      if (start) params.set("start", start);
      if (dq) params.set("q", dq);
      const res = await api<CalendarResp>(`/v2/coach/calendar?${params.toString()}`);
      setData(res);
    } catch (e: any) {
      console.warn("calendar load failed:", e?.message || e);
      setData(null);
    } finally { setLoading(false); }
  }, [days, start, dq]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const stepDays = useCallback((direction: -1 | 1) => {
    // Shift the window by one full range
    const anchor = start ? new Date(start + "T00:00:00") : new Date();
    anchor.setDate(anchor.getDate() + direction * days);
    const iso = anchor.toISOString().slice(0, 10);
    setStart(iso);
  }, [start, days]);

  const goToday = useCallback(() => setStart(null), []);

  // Optional narrow-by-attention filter (client-side; the row list is small).
  const rows = useMemo(() => {
    if (!data) return [];
    if (!needsAttentionOnly) return data.clients;
    return data.clients.filter(
      (c) => c.has_new_draft || c.plan_state === "no_plan" || !c.has_roster,
    );
  }, [data, needsAttentionOnly]);

  const dates = data?.dates || [];

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      {/* Header */}
      <View style={styles.header}>
        <View style={{ flex: 1 }}>
          <Text style={styles.h1}>Calendar</Text>
          <Text style={styles.h1sub}>
            {data ? fmtRange(data.start_date, data.end_date) : "…"}
            {data && data.excluded_test_count > 0
              ? ` · ${data.excluded_test_count} test client${data.excluded_test_count === 1 ? "" : "s"} hidden`
              : ""}
          </Text>
        </View>
        <View style={styles.rangeBox}>
          {[7, 14, 28].map((n) => (
            <Pressable
              key={n}
              onPress={() => setDays(n)}
              style={[styles.rangeBtn, days === n && styles.rangeBtnActive]}
              testID={`range-${n}d`}
            >
              <Text style={[styles.rangeBtnText, days === n && styles.rangeBtnTextActive]}>{n}D</Text>
            </Pressable>
          ))}
        </View>
      </View>

      {/* Toolbar */}
      <View style={styles.toolbar}>
        <Pressable style={styles.iconBtn} onPress={() => stepDays(-1)} testID="cal-prev">
          <Ionicons name="chevron-back" size={16} color={theme.color.textHi} />
        </Pressable>
        <Pressable style={styles.todayBtn} onPress={goToday} testID="cal-today">
          <Text style={styles.todayBtnText}>Today</Text>
        </Pressable>
        <Pressable style={styles.iconBtn} onPress={() => stepDays(1)} testID="cal-next">
          <Ionicons name="chevron-forward" size={16} color={theme.color.textHi} />
        </Pressable>
        <Pressable
          style={[styles.attnBtn, needsAttentionOnly && styles.attnBtnActive]}
          onPress={() => setNAOnly((v) => !v)}
          testID="cal-attn-only"
        >
          <Ionicons name="alert-circle-outline" size={13} color={needsAttentionOnly ? "#000" : theme.color.textHi} />
          <Text style={[styles.attnBtnText, needsAttentionOnly && styles.attnBtnTextActive]}>Needs attention</Text>
        </Pressable>
        <View style={styles.searchBox}>
          <Ionicons name="search" size={13} color={theme.color.textDim} />
          <TextInput
            value={q}
            onChangeText={setQ}
            placeholder="Search clients…"
            placeholderTextColor={theme.color.textDim}
            style={styles.searchInput}
            testID="cal-search"
          />
        </View>
      </View>

      {/* Grid — vertical scroll wraps a horizontal ScrollView for the days */}
      {loading && !data ? (
        <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>
      ) : !data || rows.length === 0 ? (
        <View style={styles.center}>
          <Ionicons name="calendar-outline" size={28} color={theme.color.textDim} />
          <Text style={styles.emptyTitle}>No clients to show</Text>
          <Text style={styles.emptyBody}>
            {q ? `No matches for "${q}".` :
             needsAttentionOnly ? "No client's calendar needs attention right now." :
             "Add an active client to see their schedule here."}
          </Text>
        </View>
      ) : (
        <ScrollView
          style={{ flex: 1 }}
          contentContainerStyle={{ paddingBottom: 40 }}
          testID="calendar-scroll"
        >
          {/* Sticky header row: client-column label + date columns */}
          <View style={styles.headerRow} testID="calendar-header">
            <View style={[styles.clientCol, styles.clientColHeader]}>
              <Text style={styles.clientHead}>CLIENT</Text>
            </View>
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              style={styles.dateScroll}
              testID="calendar-date-scroll-header"
            >
              {dates.map((d) => {
                const f = fmtDay(d);
                return (
                  <View key={d} style={[
                    styles.dateHead,
                    f.isToday && styles.dateHeadToday,
                    f.isWeekend && styles.dateHeadWeekend,
                    { width: cellWidthFor(days) },
                  ]}>
                    <Text style={[styles.dateDow, f.isToday && styles.dateDowToday]}>{f.dow}</Text>
                    <Text style={[styles.dateDdmm, f.isToday && styles.dateDdmmToday]}>{f.ddmm}</Text>
                  </View>
                );
              })}
            </ScrollView>
          </View>

          {rows.map((r) => (
            <ClientCalendarRow
              key={r.client_id}
              row={r}
              days={days}
              onOpenClient={() => router.push(`/coach/client/${r.client_id}/workspace` as any)}
              onOpenDate={(d) => router.push(`/coach/client/${r.client_id}/workspace` as any)}
              onOpenDraft={() => router.push(`/coach/client/${r.client_id}/workspace` as any)}
            />
          ))}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

function cellWidthFor(days: number): number {
  if (days <= 7)  return 150;
  if (days <= 14) return 118;
  return 82;
}

/* -------------------------------------------------------------------------- */
/*  Client row                                                                */
/* -------------------------------------------------------------------------- */
function ClientCalendarRow({
  row, days, onOpenClient, onOpenDate, onOpenDraft,
}: {
  row: Row;
  days: number;
  onOpenClient: () => void;
  onOpenDate: (dateIso: string) => void;
  onOpenDraft: () => void;
}) {
  const cellW = cellWidthFor(days);
  return (
    <View style={styles.rowRoot}>
      {/* Client column (frozen) */}
      <Pressable
        style={[styles.clientCol, styles.clientCell]}
        onPress={onOpenClient}
        testID={`cal-client-${row.client_id}`}
      >
        <Text style={styles.cName} numberOfLines={1}>{row.name}</Text>
        {row.role_line ? (
          <Text style={styles.cRole} numberOfLines={1}>{row.role_line}</Text>
        ) : null}
        <Text style={styles.cGoal} numberOfLines={1}>
          {row.goal_label}
          {row.phase_label ? ` · ${row.phase_label}` : ""}
        </Text>
        <View style={styles.pillRow}>
          {row.plan_state === "live" ? (
            <View style={styles.pillLive}>
              <View style={styles.pillDot} />
              <Text style={styles.pillLiveText}>LIVE</Text>
            </View>
          ) : row.plan_state === "no_plan" ? (
            <View style={styles.pillNoPlan}>
              <Text style={styles.pillNoPlanText}>NO PLAN</Text>
            </View>
          ) : (
            <View style={styles.pillDraft}>
              <Text style={styles.pillDraftText}>DRAFT</Text>
            </View>
          )}
          {row.has_new_draft && (
            <Pressable
              style={styles.newDraftBadge}
              onPress={(e) => { e.stopPropagation?.(); onOpenDraft(); }}
              testID={`cal-newdraft-${row.client_id}`}
            >
              <Text style={styles.newDraftText}>New Draft</Text>
            </Pressable>
          )}
        </View>
      </Pressable>

      {/* Day cells */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={styles.dateScroll}
        testID={`cal-days-${row.client_id}`}
      >
        {row.days.map((cell) => (
          <DayCellView
            key={cell.date}
            cell={cell}
            width={cellW}
            hasRoster={row.has_roster}
            onPress={() => onOpenDate(cell.date)}
            testID={`cal-cell-${row.client_id}-${cell.date}`}
          />
        ))}
      </ScrollView>
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/*  Day cell                                                                  */
/* -------------------------------------------------------------------------- */
function DayCellView({
  cell, width, hasRoster, onPress, testID,
}: {
  cell: DayCell; width: number; hasRoster: boolean;
  onPress: () => void; testID?: string;
}) {
  const f = fmtDay(cell.date);
  const hasContent = cell.trainings.length > 0 || cell.flight_support.length > 0 || !!cell.roster;
  return (
    <Pressable
      style={[
        styles.cell,
        { width },
        f.isToday && styles.cellToday,
        f.isWeekend && styles.cellWeekend,
      ]}
      onPress={onPress}
      testID={testID}
    >
      {/* Roster tag */}
      {cell.roster ? (
        <View style={styles.rosterTagWrap}>
          <Text style={[styles.rosterTag, burdenStyle(cell.roster.duty_burden_band)]} numberOfLines={1}>
            {cell.roster.classification_label || "—"}
          </Text>
        </View>
      ) : hasRoster ? null : (
        <Text style={styles.noRoster} numberOfLines={1}>—</Text>
      )}

      {/* Training(s) — visually dominant */}
      {cell.trainings.length > 0 ? (
        <View style={styles.trainings}>
          {cell.trainings.slice(0, 2).map((t) => (
            <View
              key={t.id}
              style={[styles.trainingCard, t.key && styles.trainingCardKey]}
            >
              <Text style={[styles.trainLabel, t.key && styles.trainLabelKey]} numberOfLines={1}>{t.label}</Text>
              <Text style={styles.trainMeta} numberOfLines={1}>
                {t.duration_min ? `${t.duration_min}m` : ""}
                {t.key ? "  · KEY" : ""}
              </Text>
            </View>
          ))}
          {cell.trainings.length > 2 && (
            <Text style={styles.moreLine}>+{cell.trainings.length - 2} more</Text>
          )}
        </View>
      ) : cell.roster ? (
        <Text style={styles.rest}>Rest</Text>
      ) : null}

      {/* Flight Support — tertiary */}
      {cell.flight_support.length > 0 ? (
        <View style={styles.fsWrap}>
          <View style={styles.fsHeadRow}>
            <Ionicons name="airplane-outline" size={10} color={theme.color.textDim} />
            <Text style={styles.fsHead}>Flight Support</Text>
          </View>
          {cell.flight_support.slice(0, 2).map((f, i) => (
            <Text key={f.id || i} style={styles.fsItem} numberOfLines={1}>
              {f.title}{f.duration_min ? ` · ${f.duration_min}m` : ""}
            </Text>
          ))}
          {cell.flight_support.length > 2 && (
            <Text style={styles.moreLine}>+{cell.flight_support.length - 2} more</Text>
          )}
        </View>
      ) : null}

      {!hasContent ? <View style={{ flex: 1 }} /> : null}
    </Pressable>
  );
}

function burdenStyle(band?: string | null): any {
  switch ((band || "").toLowerCase()) {
    case "heavy":    return { color: "#ff7b6b", borderColor: "rgba(255,123,107,0.45)" };
    case "moderate": return { color: "#f5b543", borderColor: "rgba(245,181,67,0.45)" };
    case "light":    return { color: "#61c982", borderColor: "rgba(97,201,130,0.45)" };
    default:         return { color: theme.color.textDim, borderColor: theme.color.border };
  }
}

/* -------------------------------------------------------------------------- */
/*  Styles                                                                    */
/* -------------------------------------------------------------------------- */
const CLIENT_COL_WIDTH = 220;

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.bg },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 40, gap: 6 },
  emptyTitle: { color: theme.color.textHi, fontSize: 15, fontWeight: "800", marginTop: 8 },
  emptyBody: { color: theme.color.textDim, fontSize: 12, textAlign: "center", maxWidth: 360 },

  /* Header */
  header: {
    flexDirection: "row", alignItems: "flex-start",
    paddingHorizontal: 20, paddingTop: 16, paddingBottom: 8, gap: 12,
  },
  h1: { color: theme.color.textHi, fontSize: 22, fontWeight: "800", letterSpacing: 0.3 },
  h1sub: { color: theme.color.textDim, fontSize: 11, marginTop: 3 },
  rangeBox: { flexDirection: "row", backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border, borderRadius: 8, overflow: "hidden" },
  rangeBtn: { paddingHorizontal: 12, paddingVertical: 7 },
  rangeBtnActive: { backgroundColor: theme.color.brand },
  rangeBtnText: { color: theme.color.textHi, fontSize: 11, fontWeight: "800", letterSpacing: 0.5 },
  rangeBtnTextActive: { color: "#fff" },

  /* Toolbar */
  toolbar: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: 20, paddingBottom: 8, flexWrap: "wrap",
  },
  iconBtn: {
    padding: 6, borderRadius: 6,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
  },
  todayBtn: {
    paddingHorizontal: 12, paddingVertical: 6, borderRadius: 6,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
  },
  todayBtnText: { color: theme.color.textHi, fontSize: 12, fontWeight: "700" },
  attnBtn: {
    flexDirection: "row", alignItems: "center", gap: 5,
    paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  attnBtnActive: { backgroundColor: "#f5b543", borderColor: "#f5b543" },
  attnBtnText: { color: theme.color.textHi, fontSize: 11, fontWeight: "700" },
  attnBtnTextActive: { color: "#000" },
  searchBox: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: theme.color.surface2, borderRadius: 6,
    borderWidth: 1, borderColor: theme.color.border,
    paddingHorizontal: 10, paddingVertical: 6, minWidth: 200, flex: 1, maxWidth: 320,
  },
  searchInput: { flex: 1, color: theme.color.textHi, fontSize: 12, padding: 0, outlineStyle: "none" as any },

  /* Sticky header row */
  headerRow: {
    flexDirection: "row", alignItems: "stretch",
    backgroundColor: theme.color.bg,
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
    position: "sticky" as any, top: 0, zIndex: 10,
  },
  clientCol: { width: CLIENT_COL_WIDTH, paddingHorizontal: 12, paddingVertical: 8, backgroundColor: theme.color.bg },
  clientColHeader: { justifyContent: "flex-end" },
  clientHead: { color: theme.color.textDim, fontSize: 10, letterSpacing: 1.5, fontWeight: "800" },
  dateScroll: { flex: 1 },
  dateHead: {
    borderLeftWidth: 1, borderLeftColor: theme.color.border,
    paddingHorizontal: 10, paddingVertical: 6, alignItems: "flex-start", justifyContent: "center",
  },
  dateHeadToday: { backgroundColor: "rgba(219,58,74,0.10)" },
  dateHeadWeekend: { backgroundColor: "rgba(255,255,255,0.02)" },
  dateDow: { color: theme.color.textDim, fontSize: 10, letterSpacing: 1.2, fontWeight: "700" },
  dateDowToday: { color: theme.color.brand },
  dateDdmm: { color: theme.color.textHi, fontSize: 12, fontWeight: "800", marginTop: 1 },
  dateDdmmToday: { color: theme.color.brand },

  /* Row */
  rowRoot: {
    flexDirection: "row", alignItems: "stretch",
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
    minHeight: 80,
  },
  clientCell: { backgroundColor: theme.color.surface, justifyContent: "center", gap: 2 },
  cName: { color: theme.color.textHi, fontSize: 13, fontWeight: "800" },
  cRole: { color: theme.color.textDim, fontSize: 11 },
  cGoal: { color: theme.color.textDim, fontSize: 11, marginTop: 1 },
  pillRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 4, flexWrap: "wrap" },
  pillLive: {
    flexDirection: "row", alignItems: "center", gap: 4,
    borderWidth: 1, borderColor: "rgba(97,201,130,0.45)",
    backgroundColor: "rgba(97,201,130,0.15)", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
  },
  pillDot: { width: 5, height: 5, borderRadius: 3, backgroundColor: "#61c982" },
  pillLiveText: { color: "#61c982", fontSize: 9, fontWeight: "800", letterSpacing: 0.8 },
  pillNoPlan: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4, borderWidth: 1, borderColor: theme.color.border },
  pillNoPlanText: { color: theme.color.textDim, fontSize: 9, fontWeight: "800", letterSpacing: 0.8 },
  pillDraft: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4, borderWidth: 1, borderColor: "rgba(245,181,67,0.55)", backgroundColor: "rgba(245,181,67,0.15)" },
  pillDraftText: { color: "#f5b543", fontSize: 9, fontWeight: "800", letterSpacing: 0.8 },
  newDraftBadge: {
    paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
    borderWidth: 1, borderColor: "rgba(245,181,67,0.55)",
    backgroundColor: "rgba(245,181,67,0.14)",
  },
  newDraftText: { color: "#f5b543", fontSize: 9, fontWeight: "800", letterSpacing: 0.8 },

  /* Day cell */
  cell: {
    padding: 6, gap: 4,
    borderLeftWidth: 1, borderLeftColor: theme.color.border,
    backgroundColor: theme.color.surface2,
    justifyContent: "flex-start",
  },
  cellToday:   { backgroundColor: "rgba(219,58,74,0.06)" },
  cellWeekend: { backgroundColor: theme.color.bg },
  rosterTagWrap: {},
  rosterTag: {
    fontSize: 9, fontWeight: "800", letterSpacing: 0.8,
    paddingHorizontal: 5, paddingVertical: 1, borderRadius: 3,
    borderWidth: 1, alignSelf: "flex-start",
  },
  noRoster: { color: theme.color.textDim, fontSize: 10 },
  trainings: { gap: 3 },
  trainingCard: {
    paddingHorizontal: 6, paddingVertical: 4, borderRadius: 4,
    backgroundColor: theme.color.surface,
    borderWidth: 1, borderColor: theme.color.border,
  },
  trainingCardKey: { backgroundColor: "rgba(219,58,74,0.10)", borderColor: theme.color.brand },
  trainLabel: { color: theme.color.textHi, fontSize: 11, fontWeight: "800" },
  trainLabelKey: { color: theme.color.brand },
  trainMeta: { color: theme.color.textDim, fontSize: 10, marginTop: 1 },
  moreLine: { color: theme.color.textDim, fontSize: 9, fontStyle: "italic" },
  rest: { color: theme.color.textDim, fontSize: 10, fontStyle: "italic" },
  fsWrap: {
    marginTop: 3, paddingTop: 3,
    borderTopWidth: 1, borderTopColor: theme.color.border,
  },
  fsHeadRow: { flexDirection: "row", alignItems: "center", gap: 3 },
  fsHead: { color: theme.color.textDim, fontSize: 8.5, fontWeight: "700", letterSpacing: 1 },
  fsItem: { color: theme.color.textDim, fontSize: 10, marginTop: 1 },
});
