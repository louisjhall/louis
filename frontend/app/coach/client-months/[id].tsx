/**
 * Coach — Client Roster/Programme Control Centre (Phase 1).
 *
 * Route: /coach/client/[id]/months
 *
 * A dedicated screen that groups a client's uploaded rosters by MONTH and
 * shows, for each month, a day-by-day calendar of duties with the attached
 * workout inline. Tapping the workout opens the existing coach workout
 * editor.
 *
 * Backed by GET /api/coach/clients/{cid}/roster/months
 *      and GET /api/coach/clients/{cid}/roster/months/{yyyy_mm}
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable,
  ActivityIndicator, RefreshControl, Modal,
} from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { WorkoutQuickActions, type WorkoutQuickActionTarget } from "@/src/components/WorkoutQuickActions";
import { ScheduleRow } from "@/src/components/ScheduleRow";

// -------------------- Types --------------------

type MonthSummary = {
  month_key: string;
  month_label: string;
  primary_roster_id: string;
  airline: string;
  day_count: number;
  confidence_avg?: number;
  status: string;
  confirmed: boolean;
  is_active: boolean;
  needs_review: boolean;
  colour_counts: { green: number; amber: number; red: number; black: number };
  version_count: number;
  parser_source?: string;
  source_filename?: string;
  start_date?: string;
  end_date?: string;
  other_versions?: Array<{ id: string; confirmed: boolean; is_active: boolean; status: string; created_at?: string; source_filename?: string; day_count?: number }>;
};

type DayCard = {
  date: string;
  weekday?: string;
  day_type: string;
  client_label: string;
  training_colour: "green" | "amber" | "red" | "black";
  label: string;
  blocked: string[];
  equipment_assumption: string;
  layover_city?: string | null;
  report_time?: string | null;
  release_time?: string | null;
  hotel_name?: string | null;
  flights?: Array<{ from?: string; to?: string; flight_number?: string }>;
  needs_review: boolean;
  reason?: string;
  source?: string | null;
  workout?: {
    id: string;
    title?: string;
    focus?: string;
    duration_min?: number;
    day_load?: string;
    location?: string;
    exercise_count?: number;
    missing_media_count?: number;
    approved?: boolean;
    coach_locked?: boolean;
    completed?: boolean;
    rationale?: string;
    parser_enforced?: boolean;
    client_hidden?: boolean;
    client_visible_in_min?: number;
    client_hidden_reason?: string;
  } | null;
};

type MonthDetail = {
  client: { id: string; name?: string; email?: string; photo_url?: string };
  month_key: string;
  month_label: string;
  primary_roster: {
    id: string;
    airline: string;
    status: string;
    confirmed: boolean;
    is_active: boolean;
    needs_review: boolean;
    confidence_avg?: number;
    source_filename?: string;
    parser_source?: string;
    start_date?: string;
    end_date?: string;
    created_at?: string;
  } | null;
  days: DayCard[];
  versions: Array<{ id: string; confirmed: boolean; status: string; created_at?: string; source_filename?: string; day_count?: number }>;
};

const TL_COLOURS: Record<string, string> = {
  green: "#3DBE6E",
  amber: "#E5A048",
  red: "#E15A5A",
  black: "#5A5A5A",
};

const STATUS_LABELS: Record<string, string> = {
  uploaded: "Uploaded",
  parsing: "Parsing",
  needs_client_review: "Needs client review",
  needs_coach_review: "Needs coach review",
  confirmed: "Confirmed",
  programme_generated: "Programme generated",
  superseded: "Superseded",
};

const fmtDate = (d?: string): string => {
  if (!d || d.length < 10) return d || "";
  try {
    const dt = new Date(d + "T00:00:00");
    return dt.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  } catch {
    return d;
  }
};

// -------------------- Screen --------------------

export default function CoachClientMonths() {
  const params = useLocalSearchParams<{ id: string }>();
  const id = params.id;
  const router = useRouter();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [months, setMonths] = useState<MonthSummary[]>([]);
  const [clientName, setClientName] = useState<string>("");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [detail, setDetail] = useState<MonthDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Phase 3 — version history modal state
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [versionsData, setVersionsData] = useState<any | null>(null);
  const [versionsLoading, setVersionsLoading] = useState(false);
  // Phase 4 — quick action sheet target
  const [qaTarget, setQaTarget] = useState<WorkoutQuickActionTarget | null>(null);

  const loadMonths = useCallback(async () => {
    try {
      setError(null);
      const r = await api<any>(`/coach/clients/${id}/roster/months`);
      setMonths(r?.months || []);
      setClientName(r?.client?.name || "Client");
      const def = r?.default_month_key || (r?.months?.[0]?.month_key ?? null);
      setSelectedKey((prev) => prev || def);
    } catch (e: any) {
      setError(e?.message || "Couldn't load rosters");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [id]);

  const loadDetail = useCallback(async (key: string) => {
    try {
      setDetailLoading(true);
      const r = await api<MonthDetail>(`/coach/clients/${id}/roster/months/${key}`);
      setDetail(r);
    } catch (e: any) {
      setError(e?.message || "Couldn't load month");
    } finally {
      setDetailLoading(false);
    }
  }, [id]);

  useEffect(() => { loadMonths(); }, [loadMonths]);
  useEffect(() => { if (selectedKey) loadDetail(selectedKey); }, [selectedKey, loadDetail]);

  // Phase 3 — Load versions on modal open
  useEffect(() => {
    if (!versionsOpen || !selectedKey) return;
    (async () => {
      setVersionsLoading(true);
      try {
        const r = await api<any>(`/coach/clients/${id}/roster/versions/${selectedKey}`);
        setVersionsData(r);
      } catch (e: any) {
        setError(e?.message || "Couldn't load versions");
      } finally {
        setVersionsLoading(false);
      }
    })();
  }, [versionsOpen, selectedKey, id]);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    loadMonths();
    if (selectedKey) loadDetail(selectedKey);
  }, [loadMonths, loadDetail, selectedKey]);

  const activeMonth = useMemo(
    () => months.find((m) => m.month_key === selectedKey),
    [months, selectedKey],
  );

  if (loading) {
    return (
      <SafeAreaView style={styles.root} edges={["top"]}>
        <View style={styles.center}>
          <ActivityIndicator color={theme.color.brand} />
          <Text style={styles.subtle}>Loading rosters…</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      {/* Header */}
      <View style={styles.header}>
        <Pressable testID="cm-back" onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={26} color={theme.color.text} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.headerTitle} numberOfLines={1}>SCHEDULE · {clientName.toUpperCase()}</Text>
          <Text style={styles.headerSub}>Schedule · roster + assigned plan by month</Text>
        </View>
        <Pressable testID="cm-refresh" onPress={onRefresh} hitSlop={10}>
          <Ionicons name="refresh" size={20} color={theme.color.textMuted} />
        </Pressable>
      </View>

      {error ? (
        <View style={styles.errBanner}>
          <Ionicons name="alert-circle" size={14} color="#fff" />
          <Text style={styles.errText}>{error}</Text>
        </View>
      ) : null}

      {/* Month tabs */}
      {months.length === 0 ? (
        <View style={styles.emptyWrap}>
          <Ionicons name="calendar-outline" size={40} color={theme.color.textMuted} />
          <Text style={styles.emptyT}>No rosters uploaded yet</Text>
          <Text style={styles.emptyS}>Once {clientName || "the client"} uploads a roster, months will appear here.</Text>
        </View>
      ) : (
        <>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.tabsRow}
            testID="cm-months-tabs"
          >
            {months.map((m) => {
              const active = selectedKey === m.month_key;
              return (
                <Pressable
                  key={m.month_key}
                  testID={`cm-tab-${m.month_key}`}
                  onPress={() => setSelectedKey(m.month_key)}
                  style={[styles.tab, active && styles.tabActive, m.needs_review && !active && styles.tabWarn]}
                >
                  <Text style={[styles.tabT, active && styles.tabTActive]}>
                    {m.month_label.toUpperCase()}
                  </Text>
                  {m.needs_review ? (
                    <View style={styles.tabWarnDot}>
                      <Ionicons name="alert" size={10} color="#fff" />
                    </View>
                  ) : null}
                  {m.version_count > 1 ? (
                    <View style={styles.tabVBadge}>
                      <Text style={styles.tabVBadgeT}>v{m.version_count}</Text>
                    </View>
                  ) : null}
                </Pressable>
              );
            })}
          </ScrollView>

          {/* Month header summary */}
          {activeMonth ? (
            <View style={styles.monthHead}>
              <View style={styles.monthHeadTop}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.monthTitle}>{activeMonth.month_label}</Text>
                  <Text style={styles.monthSub}>
                    {activeMonth.airline} · {activeMonth.day_count} days
                    {activeMonth.source_filename ? ` · ${activeMonth.source_filename}` : ""}
                  </Text>
                </View>
                <View style={[styles.statusPill, statusPillStyle(activeMonth.status)]}>
                  <Text style={styles.statusPillT}>{(STATUS_LABELS[activeMonth.status] || activeMonth.status).toUpperCase()}</Text>
                </View>
              </View>
              <View style={styles.tlRow}>
                {(["green", "amber", "red", "black"] as const).map((c) => {
                  const n = activeMonth.colour_counts?.[c] || 0;
                  if (n === 0) return null;
                  return (
                    <View key={c} style={styles.tlChip}>
                      <View style={[styles.tlDot, { backgroundColor: TL_COLOURS[c] }]} />
                      <Text style={styles.tlChipT}>{n}</Text>
                    </View>
                  );
                })}
                {activeMonth.version_count > 1 ? (
                  <Pressable
                    testID="cm-open-versions"
                    onPress={() => setVersionsOpen(true)}
                    style={[styles.tlChip, { borderColor: theme.color.brand }]}
                  >
                    <Ionicons name="git-branch-outline" size={11} color={theme.color.brand} />
                    <Text style={[styles.tlChipT, { color: theme.color.brand }]}>
                      {activeMonth.version_count} versions
                    </Text>
                  </Pressable>
                ) : null}
              </View>
            </View>
          ) : null}

          {/* Days list */}
          <ScrollView
            contentContainerStyle={styles.scrollBody}
            refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.color.brand} />}
          >
            {detailLoading ? (
              <View style={styles.center}>
                <ActivityIndicator color={theme.color.brand} />
              </View>
            ) : detail && detail.days.length > 0 ? (
              detail.days.map((d) => (
                <ScheduleRow
                  key={d.date}
                  day={d as any}
                  onOpenWorkout={(wid) => router.push(`/coach/workout/edit/${wid}` as any)}
                  onWorkoutMenu={() => d.workout?.id && setQaTarget({
                    id: d.workout.id,
                    title: d.workout.title,
                    date: d.date,
                    approved: d.workout.approved,
                    coach_locked: d.workout.coach_locked,
                    missing_media_count: d.workout.missing_media_count,
                  })}
                />
              ))
            ) : (
              <View style={styles.emptyWrap}>
                <Ionicons name="cloud-offline-outline" size={30} color={theme.color.textMuted} />
                <Text style={styles.emptyT}>No duties in this month</Text>
              </View>
            )}
          </ScrollView>
        </>
      )}

      {/* Phase 3 — Version history modal */}
      <Modal
        visible={versionsOpen}
        transparent
        animationType="slide"
        onRequestClose={() => setVersionsOpen(false)}
      >
        <View style={styles.modalScrim}>
          <View style={styles.modalSheet}>
            <View style={styles.modalHeader}>
              <View>
                <Text style={styles.modalTitle}>
                  {versionsData?.month_label || activeMonth?.month_label} · Versions
                </Text>
                <Text style={styles.modalSub}>
                  {versionsData?.versions?.length || 0} roster{(versionsData?.versions?.length || 0) === 1 ? "" : "s"} uploaded for this month
                </Text>
              </View>
              <Pressable testID="cm-versions-close" onPress={() => setVersionsOpen(false)} hitSlop={10}>
                <Ionicons name="close" size={26} color={theme.color.text} />
              </Pressable>
            </View>
            <ScrollView contentContainerStyle={{ padding: theme.space.md, paddingBottom: 40 }}>
              {versionsLoading ? (
                <ActivityIndicator color={theme.color.brand} />
              ) : (
                (versionsData?.versions || []).map((v: any) => (
                  <View
                    key={v.id}
                    style={[styles.versionCard, v.is_primary && styles.versionCardPrimary]}
                    testID={`cm-version-${v.id}`}
                  >
                    <View style={styles.versionTopRow}>
                      <View style={{ flex: 1 }}>
                        <Text style={styles.versionTitle} numberOfLines={1}>
                          {v.source_filename || "Roster upload"}
                        </Text>
                        <Text style={styles.versionMeta} numberOfLines={1}>
                          {v.created_at ? new Date(v.created_at).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : ""}
                          {v.day_count ? ` · ${v.day_count} days` : ""}
                          {v.parser_source ? ` · ${v.parser_source.replace("_parser_v1", "").toUpperCase()}` : ""}
                        </Text>
                      </View>
                      {v.is_primary ? (
                        <View style={[styles.versionBadge, { backgroundColor: theme.color.brand }]}>
                          <Text style={styles.versionBadgeT}>PRIMARY</Text>
                        </View>
                      ) : v.status === "pending_confirmation" ? (
                        <View style={[styles.versionBadge, { backgroundColor: "#a1611c" }]}>
                          <Text style={styles.versionBadgeT}>PENDING</Text>
                        </View>
                      ) : v.confirmed ? (
                        <View style={[styles.versionBadge, { backgroundColor: "#1f7c3a" }]}>
                          <Text style={styles.versionBadgeT}>CONFIRMED</Text>
                        </View>
                      ) : v.status === "superseded" ? (
                        <View style={[styles.versionBadge, { backgroundColor: "#5a5a5a" }]}>
                          <Text style={styles.versionBadgeT}>SUPERSEDED</Text>
                        </View>
                      ) : null}
                    </View>

                    {v.diff_vs_primary ? (
                      <View style={styles.diffRow}>
                        {v.diff_vs_primary.added?.length > 0 && (
                          <View style={[styles.diffPill, { backgroundColor: "#1f7c3a" }]}>
                            <Text style={styles.diffPillT}>+{v.diff_vs_primary.added.length} added</Text>
                          </View>
                        )}
                        {v.diff_vs_primary.removed?.length > 0 && (
                          <View style={[styles.diffPill, { backgroundColor: "#c85450" }]}>
                            <Text style={styles.diffPillT}>−{v.diff_vs_primary.removed.length} removed</Text>
                          </View>
                        )}
                        {v.diff_vs_primary.changed?.length > 0 && (
                          <View style={[styles.diffPill, { backgroundColor: "#a1611c" }]}>
                            <Text style={styles.diffPillT}>~{v.diff_vs_primary.changed.length} changed</Text>
                          </View>
                        )}
                        {v.diff_vs_primary.unchanged_count > 0 && (
                          <View style={[styles.diffPill, { backgroundColor: theme.color.surface }]}>
                            <Text style={[styles.diffPillT, { color: theme.color.textMuted }]}>
                              ={v.diff_vs_primary.unchanged_count} unchanged
                            </Text>
                          </View>
                        )}
                      </View>
                    ) : null}

                    {v.diff_vs_primary?.changed?.length > 0 && (
                      <View style={styles.diffList}>
                        {v.diff_vs_primary.changed.slice(0, 6).map((c: any) => (
                          <Text key={c.date} style={styles.diffChangeLine} numberOfLines={1}>
                            {c.date}: {c.prev?.day_type || "—"} → {c.new?.day_type || "—"}
                          </Text>
                        ))}
                        {v.diff_vs_primary.changed.length > 6 && (
                          <Text style={styles.diffChangeMore}>
                            +{v.diff_vs_primary.changed.length - 6} more…
                          </Text>
                        )}
                      </View>
                    )}
                  </View>
                ))
              )}
              {!versionsLoading && (versionsData?.versions || []).length === 0 ? (
                <Text style={{ color: theme.color.textMuted, textAlign: "center", padding: 24 }}>
                  No version history for this month.
                </Text>
              ) : null}
            </ScrollView>
          </View>
        </View>
      </Modal>

      {/* Phase 4 — Workout quick action sheet */}
      <WorkoutQuickActions
        visible={!!qaTarget}
        target={qaTarget}
        onClose={() => setQaTarget(null)}
        onChanged={() => selectedKey && loadDetail(selectedKey)}
      />
    </SafeAreaView>
  );
}

// -------------------- Day card --------------------

function DayCardView({ d, onWorkoutPress, onWorkoutMenu }: {
  d: DayCard;
  onWorkoutPress: () => void;
  onWorkoutMenu: () => void;
}) {
  const colour = TL_COLOURS[d.training_colour] || TL_COLOURS.green;
  const hasWorkout = !!d.workout && !!d.workout.id;
  const routeStr = (d.flights || []).map((f) => `${f.from || "?"}→${f.to || "?"}`).join(" · ");

  return (
    <View style={styles.dayCard} testID={`cm-day-${d.date}`}>
      {/* Left colour bar */}
      <View style={[styles.dayBar, { backgroundColor: colour }]} />

      <View style={{ flex: 1 }}>
        {/* Date + label */}
        <View style={styles.dayTopRow}>
          <Text style={styles.dayDate}>{fmtDate(d.date)}</Text>
          {d.needs_review ? (
            <View style={styles.reviewChip}>
              <Ionicons name="alert-circle" size={11} color="#fff" />
              <Text style={styles.reviewChipT}>REVIEW</Text>
            </View>
          ) : null}
        </View>

        <Text style={styles.dayType} numberOfLines={1}>
          {d.client_label || d.day_type || "Duty"}
        </Text>

        {routeStr ? (
          <Text style={styles.dayRoute} numberOfLines={1}>{routeStr}</Text>
        ) : null}

        {(d.report_time || d.release_time) ? (
          <Text style={styles.dayMeta} numberOfLines={1}>
            {d.report_time ? `Report ${d.report_time}` : ""}
            {d.report_time && d.release_time ? " · " : ""}
            {d.release_time ? `Off ${d.release_time}` : ""}
          </Text>
        ) : null}

        {d.hotel_name ? (
          <Text style={styles.dayMeta} numberOfLines={1}>🏨 {d.hotel_name}</Text>
        ) : d.layover_city ? (
          <Text style={styles.dayMeta} numberOfLines={1}>{d.layover_city}</Text>
        ) : null}

        {d.reason ? (
          <Text style={styles.dayReason} numberOfLines={2}>{d.reason}</Text>
        ) : null}

        {/* Workout attached */}
        <Pressable
          testID={hasWorkout ? `cm-workout-open-${d.workout!.id}` : `cm-workout-empty-${d.date}`}
          onPress={hasWorkout ? onWorkoutPress : undefined}
          disabled={!hasWorkout}
          style={[styles.workoutBox, !hasWorkout && styles.workoutBoxEmpty]}
        >
          {hasWorkout ? (
            <>
              <View style={styles.workoutTop}>
                <Text style={styles.workoutTitle} numberOfLines={1}>
                  {d.workout!.title || "Workout"}
                  {d.workout!.coach_locked ? "  🔒" : ""}
                </Text>
                <Pressable
                  testID={`cm-workout-menu-${d.workout!.id}`}
                  onPress={(e) => { e.stopPropagation(); onWorkoutMenu(); }}
                  hitSlop={10}
                  style={styles.kebabBtn}
                >
                  <Ionicons name="ellipsis-horizontal" size={18} color={theme.color.text} />
                </Pressable>
              </View>
              <Text style={styles.workoutMeta} numberOfLines={1}>
                {(d.workout!.focus || "").toUpperCase()}
                {d.workout!.duration_min ? ` · ${d.workout!.duration_min}m` : ""}
                {d.workout!.exercise_count ? ` · ${d.workout!.exercise_count} ex` : ""}
              </Text>
              <View style={styles.workoutChips}>
                {d.workout!.completed ? (
                  <View style={styles.wChipDone}>
                    <Ionicons name="checkmark" size={11} color="#fff" />
                    <Text style={styles.wChipDoneT}>DONE</Text>
                  </View>
                ) : d.workout!.approved ? (
                  <View style={styles.wChipApproved}>
                    <Text style={styles.wChipApprovedT}>APPROVED</Text>
                  </View>
                ) : (
                  <View style={styles.wChipPlanned}>
                    <Text style={styles.wChipPlannedT}>PLANNED</Text>
                  </View>
                )}
                {d.workout!.parser_enforced ? (
                  <View style={styles.wChipEnforced}>
                    <Text style={styles.wChipEnforcedT}>ROSTER-AWARE</Text>
                  </View>
                ) : null}
                {d.workout!.client_hidden ? (
                  <View style={styles.wChipHidden}>
                    <Ionicons name="eye-off-outline" size={10} color="#fff" />
                    <Text style={styles.wChipHiddenT}>
                      HIDDEN FROM CLIENT · {d.workout!.client_visible_in_min || "?"}m
                    </Text>
                  </View>
                ) : null}
                {(d.workout!.missing_media_count || 0) > 0 ? (
                  <View style={styles.wChipMedia}>
                    <Ionicons name="image-outline" size={10} color="#fff" />
                    <Text style={styles.wChipMediaT}>
                      {d.workout!.missing_media_count} missing media
                    </Text>
                  </View>
                ) : null}
              </View>
            </>
          ) : (
            <View style={styles.workoutEmptyRow}>
              <Ionicons name="ellipse-outline" size={14} color={theme.color.textMuted} />
              <Text style={styles.workoutEmptyT}>No workout scheduled</Text>
            </View>
          )}
        </Pressable>
      </View>
    </View>
  );
}

// -------------------- Helpers --------------------

function statusPillStyle(status: string): any {
  switch (status) {
    case "programme_generated":
    case "confirmed":
      return { backgroundColor: "#1f7c3a", borderColor: "#1f7c3a" };
    case "needs_client_review":
    case "needs_coach_review":
      return { backgroundColor: "#a1611c", borderColor: "#a1611c" };
    case "superseded":
      return { backgroundColor: "#5a5a5a", borderColor: "#5a5a5a" };
    default:
      return { backgroundColor: theme.color.surface2, borderColor: theme.color.border };
  }
}

// -------------------- Styles --------------------

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.bg },
  header: {
    flexDirection: "row", alignItems: "center", gap: theme.space.md,
    paddingHorizontal: theme.space.lg, paddingVertical: theme.space.md,
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  headerTitle: { color: theme.color.text, fontSize: 14, fontWeight: "900", letterSpacing: 1.5 },
  headerSub: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },
  center: { padding: theme.space.xl, alignItems: "center", gap: theme.space.md },
  subtle: { color: theme.color.textMuted, fontSize: 12 },
  errBanner: {
    flexDirection: "row", gap: 8, alignItems: "center",
    backgroundColor: "#c85450", padding: 10,
  },
  errText: { color: "#fff", fontSize: 12, flex: 1 },
  emptyWrap: { padding: theme.space.xl, alignItems: "center", gap: 8 },
  emptyT: { color: theme.color.text, fontSize: 14, fontWeight: "700", marginTop: 8 },
  emptyS: { color: theme.color.textMuted, fontSize: 12, textAlign: "center", maxWidth: 260 },
  tabsRow: {
    paddingHorizontal: theme.space.lg,
    paddingVertical: 10,
    gap: 6,
    alignItems: "center",
  },
  tab: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 12, paddingVertical: 8,
    borderRadius: theme.radius.pill,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
  },
  tabActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  tabWarn: { borderColor: "#E5A048" },
  tabT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "800", letterSpacing: 1 },
  tabTActive: { color: "#fff" },
  tabWarnDot: {
    backgroundColor: "#E5A048",
    borderRadius: 8, width: 14, height: 14,
    alignItems: "center", justifyContent: "center",
  },
  tabVBadge: {
    backgroundColor: theme.color.surface, borderRadius: 8,
    paddingHorizontal: 5, paddingVertical: 1,
  },
  tabVBadgeT: { color: theme.color.text, fontSize: 9, fontWeight: "800" },
  monthHead: {
    paddingHorizontal: theme.space.lg, paddingVertical: theme.space.md,
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
    backgroundColor: theme.color.surface2,
  },
  monthHeadTop: { flexDirection: "row", alignItems: "center", gap: theme.space.md },
  monthTitle: { color: theme.color.text, fontSize: 18, fontWeight: "900" },
  monthSub: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },
  statusPill: {
    paddingHorizontal: 10, paddingVertical: 5, borderRadius: theme.radius.pill,
    borderWidth: 1,
  },
  statusPillT: { color: "#fff", fontSize: 9, fontWeight: "900", letterSpacing: 1 },
  tlRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 10 },
  tlChip: {
    flexDirection: "row", alignItems: "center", gap: 5,
    paddingHorizontal: 8, paddingVertical: 4,
    borderRadius: theme.radius.pill,
    backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border,
  },
  tlChipT: { color: theme.color.text, fontSize: 10, fontWeight: "700" },
  tlDot: { width: 8, height: 8, borderRadius: 4 },
  scrollBody: { padding: theme.space.lg, paddingBottom: 60, gap: theme.space.sm },
  dayCard: {
    flexDirection: "row",
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
    borderRadius: theme.radius.md,
    padding: theme.space.md,
    gap: theme.space.md,
    marginBottom: theme.space.sm,
    minHeight: 88,
  },
  dayBar: { width: 4, borderRadius: 2 },
  dayTopRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 4 },
  dayDate: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1.5, fontWeight: "700" },
  dayType: { color: theme.color.text, fontSize: 14, fontWeight: "800" },
  dayRoute: { color: theme.color.textMuted, fontSize: 12, marginTop: 2 },
  dayMeta: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },
  dayReason: { color: theme.color.textMuted, fontSize: 11, marginTop: 4, fontStyle: "italic" },
  reviewChip: {
    flexDirection: "row", alignItems: "center", gap: 3,
    backgroundColor: "#E5A048",
    paddingHorizontal: 7, paddingVertical: 2,
    borderRadius: theme.radius.pill,
  },
  reviewChipT: { color: "#fff", fontSize: 9, fontWeight: "800", letterSpacing: 1 },
  workoutBox: {
    marginTop: 10,
    padding: 10,
    borderRadius: theme.radius.sm,
    backgroundColor: theme.color.surface,
    borderWidth: 1, borderColor: theme.color.border,
  },
  workoutBoxEmpty: {
    backgroundColor: "transparent",
    borderStyle: "dashed",
  },
  workoutTop: {
    flexDirection: "row", alignItems: "center", gap: 8,
  },
  workoutTitle: { flex: 1, color: theme.color.text, fontSize: 13, fontWeight: "800" },
  workoutMeta: { color: theme.color.textMuted, fontSize: 11, marginTop: 3, letterSpacing: 0.5 },
  workoutChips: { flexDirection: "row", flexWrap: "wrap", gap: 5, marginTop: 8 },
  workoutEmptyRow: { flexDirection: "row", gap: 6, alignItems: "center" },
  workoutEmptyT: { color: theme.color.textMuted, fontSize: 12, fontStyle: "italic" },
  wChipPlanned: {
    paddingHorizontal: 7, paddingVertical: 3, borderRadius: theme.radius.pill,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  wChipPlannedT: { color: theme.color.textMuted, fontSize: 9, fontWeight: "800", letterSpacing: 0.8 },
  wChipApproved: {
    paddingHorizontal: 7, paddingVertical: 3, borderRadius: theme.radius.pill,
    backgroundColor: "#1f7c3a",
  },
  wChipApprovedT: { color: "#fff", fontSize: 9, fontWeight: "800", letterSpacing: 0.8 },
  wChipDone: {
    flexDirection: "row", alignItems: "center", gap: 3,
    paddingHorizontal: 7, paddingVertical: 3, borderRadius: theme.radius.pill,
    backgroundColor: "#3DBE6E",
  },
  wChipDoneT: { color: "#fff", fontSize: 9, fontWeight: "800", letterSpacing: 0.8 },
  wChipEnforced: {
    paddingHorizontal: 7, paddingVertical: 3, borderRadius: theme.radius.pill,
    backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand,
  },
  wChipEnforcedT: { color: theme.color.brand, fontSize: 9, fontWeight: "800", letterSpacing: 0.8 },
  wChipMedia: {
    flexDirection: "row", alignItems: "center", gap: 3,
    paddingHorizontal: 7, paddingVertical: 3, borderRadius: theme.radius.pill,
    backgroundColor: "#c85450",
  },
  wChipMediaT: { color: "#fff", fontSize: 9, fontWeight: "800", letterSpacing: 0.8 },
  wChipHidden: {
    flexDirection: "row", alignItems: "center", gap: 3,
    paddingHorizontal: 7, paddingVertical: 3, borderRadius: theme.radius.pill,
    backgroundColor: "#7a4a2b",
  },
  wChipHiddenT: { color: "#fff", fontSize: 9, fontWeight: "800", letterSpacing: 0.5 },
  kebabBtn: {
    padding: 4,
    borderRadius: theme.radius.sm,
  },
  // Phase 3 — Version history modal
  modalScrim: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  modalSheet: {
    backgroundColor: theme.color.surface,
    borderTopLeftRadius: 18, borderTopRightRadius: 18,
    maxHeight: "88%",
  },
  modalHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    padding: theme.space.lg,
    borderBottomWidth: 1,
    borderBottomColor: theme.color.border,
  },
  modalTitle: { color: theme.color.text, fontSize: 16, fontWeight: "900" },
  modalSub: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },
  versionCard: {
    padding: theme.space.md,
    borderRadius: theme.radius.md,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
    marginBottom: theme.space.sm,
  },
  versionCardPrimary: {
    borderColor: theme.color.brand, borderLeftWidth: 4, borderLeftColor: theme.color.brand,
  },
  versionTopRow: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 8 },
  versionTitle: { color: theme.color.text, fontSize: 13, fontWeight: "800" },
  versionMeta: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },
  versionBadge: {
    paddingHorizontal: 8, paddingVertical: 3,
    borderRadius: theme.radius.pill,
  },
  versionBadgeT: { color: "#fff", fontSize: 9, fontWeight: "900", letterSpacing: 1 },
  diffRow: { flexDirection: "row", flexWrap: "wrap", gap: 5 },
  diffPill: {
    paddingHorizontal: 8, paddingVertical: 3,
    borderRadius: theme.radius.pill,
  },
  diffPillT: { color: "#fff", fontSize: 10, fontWeight: "800", letterSpacing: 0.5 },
  diffList: {
    marginTop: 8,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: theme.color.border,
    gap: 3,
  },
  diffChangeLine: {
    color: theme.color.textMuted, fontSize: 11, fontFamily: undefined,
  },
  diffChangeMore: {
    color: theme.color.textDim, fontSize: 11, marginTop: 2, fontStyle: "italic",
  },
});
