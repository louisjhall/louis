/**
 * Coach Dashboard V2 — Roster + Plan workspace
 *
 * Route: /coach/client/[id]/workspace
 *
 * The primary client screen. Two columns on desktop, stacked cards on mobile:
 *   LEFT  = Roster / real life (schedule_days + duties + burden band)
 *   RIGHT = CrewFit plan (workout assignments + status + duration)
 *
 * Loads ONE aggregate for the whole month: /v2/coach/clients/{id}/workspace/{yyyy-mm}
 *
 * Tapping a workout opens a right-side drawer without leaving the workspace.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, Pressable, StyleSheet, ScrollView, ActivityIndicator,
  Platform, useWindowDimensions, Modal,
} from "react-native";
import { useRouter, useLocalSearchParams } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { CommandBar } from "@/src/components/CommandBar";
import { DirectiveEditor } from "@/src/components/DirectiveEditor";
import { GenerationStatusBanner } from "@/src/components/GenerationStatusBanner";
import { ProgrammeSummaryPanel } from "@/src/components/ProgrammeSummaryPanel";

type DayRow = {
  date: string;
  schedule: null | {
    classification: string;
    classification_label: string;
    duty_burden_band?: string | null;
    duty_burden_score?: number | null;
    training_opportunity?: number | null;
    recommended_intensity_ceiling?: string | null;
    available_time_min?: number | null;
    overnight_location?: any;
    v1_source?: boolean;
  };
  assignments: {
    id: string;
    kind?: string;
    kind_label: string;
    importance?: string;
    duration_min?: number;
    equipment?: string[];
    focus?: string;
    exposure_sequence?: number;
    objective_id?: string;
    status?: string;
    status_label: string;
    status_kind: "ready" | "review" | "conflict" | "approved" | "coach_edited" | "live" | "locked";
    needs_coach_review?: boolean;
    locked?: boolean;
    live_implementation_id?: string;
    draft_implementation_id?: string;
    key_session?: boolean;
    variant_type?: string;
  }[];
  v1_workouts?: any[];
};

type Workspace = {
  client: { id: string; name: string; kind: "v1" | "v2" };
  month: string;
  days: DayRow[];
  counts: Record<string, number>;
  programme: any;
  exceptions: any[];
  generated_at: string;
};

const STATUS_TINT: Record<string, string> = {
  ready: "#61c982",
  review: "#f5b543",
  conflict: "#ff6b6b",
  approved: "#5aa9e6",
  coach_edited: "#5aa9e6",
  live: "#61c982",
  locked: "#8e8e93",
};

const BURDEN_TINT: Record<string, string> = {
  light: "#61c982",
  moderate: "#f5b543",
  heavy: "#f57c43",
  extreme: "#ff6b6b",
};

function fmtDate(iso: string): { dow: string; d: string; mon: string } {
  const dt = new Date(iso + "T00:00:00");
  const dow = dt.toLocaleDateString("en-GB", { weekday: "short" }).toUpperCase();
  const d = String(dt.getDate()).padStart(2, "0");
  const mon = dt.toLocaleDateString("en-GB", { month: "short" }).toUpperCase();
  return { dow, d, mon };
}

export default function CoachWorkspaceScreen() {
  const router = useRouter();
  const { id: clientId } = useLocalSearchParams<{ id: string }>();
  const { width } = useWindowDimensions();
  const isDesktop = width >= 900;

  const [months, setMonths] = useState<string[]>([]);
  const [month, setMonth] = useState<string>("");
  const [data, setData] = useState<Workspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drawerAssignmentId, setDrawerAssignmentId] = useState<string | null>(null);
  const [directiveOpen, setDirectiveOpen] = useState(false);

  const loadMonths = useCallback(async () => {
    if (!clientId) return;
    try {
      const res = await api<{ months: string[]; current: string }>(`/v2/coach/clients/${clientId}/workspace/months`);
      setMonths(res.months || []);
      if (!month) setMonth(res.current || (res.months && res.months[0]) || "");
    } catch (e) {
      const now = new Date();
      const cur = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
      setMonths([cur]); setMonth(cur);
    }
  }, [clientId, month]);

  const loadMonth = useCallback(async () => {
    if (!clientId || !month) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api<Workspace>(`/v2/coach/clients/${clientId}/workspace/${month}`);
      setData(res);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally { setLoading(false); }
  }, [clientId, month]);

  useEffect(() => { loadMonths(); }, [loadMonths]);
  useEffect(() => { if (month) loadMonth(); }, [month, loadMonth]);

  const approveReady = useCallback(async () => {
    if (!data) return;
    const ready = data.counts?.ready || 0;
    if (!ready) return;
    setBusy(true);
    try {
      await api(`/v2/coach/clients/${clientId}/plan/approve-ready`, {
        method: "POST", body: { month },
      });
      await loadMonth();
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally { setBusy(false); }
  }, [clientId, month, data, loadMonth]);

  const stepMonth = useCallback((delta: number) => {
    if (!month) return;
    const [y, m] = month.split("-").map((s) => parseInt(s, 10));
    const dt = new Date(y, m - 1 + delta, 1);
    const next = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}`;
    setMonth(next);
  }, [month]);

  if (!clientId) {
    return <View style={styles.center}><Text style={styles.err}>No client id</Text></View>;
  }

  return (
    <View style={styles.root} testID="coach-workspace">
      {/* Header */}
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} style={styles.backBtn} testID="workspace-back">
          <Ionicons name="chevron-back" size={20} color={theme.color.textHi} />
          <Text style={styles.backTxt}>Back</Text>
        </Pressable>
        <View style={{ flex: 1, marginLeft: 8 }}>
          <Text style={styles.clientName} numberOfLines={1}>{data?.client?.name || "…"}</Text>
          <View style={styles.subRow}>
            {data?.client?.kind === "v1" && (
              <View style={styles.kindPill}><Text style={styles.kindPillText}>Training Intelligence V1</Text></View>
            )}
            {data?.client?.kind === "v2" && (
              <View style={[styles.kindPill, { backgroundColor: "#183020" }]}>
                <Text style={[styles.kindPillText, { color: "#61c982" }]}>Training Intelligence V2</Text>
              </View>
            )}
            {data?.programme?.present && (
              <Text style={styles.subMeta}>
                {data.programme.timeline_class ? `${data.programme.timeline_class} · ` : ""}
                v{data.programme.live_version_number || 0} live
                {data.programme.draft_id ? " · draft available" : ""}
              </Text>
            )}
          </View>
        </View>
      </View>

      {/* Month selector + status ribbon */}
      <View style={styles.ribbon}>
        <View style={styles.monthRow}>
          <Pressable onPress={() => stepMonth(-1)} style={styles.monthBtn} testID="month-prev">
            <Ionicons name="chevron-back" size={18} color={theme.color.textHi} />
          </Pressable>
          <Text style={styles.monthTitle}>{formatMonth(month)}</Text>
          <Pressable onPress={() => stepMonth(1)} style={styles.monthBtn} testID="month-next">
            <Ionicons name="chevron-forward" size={18} color={theme.color.textHi} />
          </Pressable>
          {months.length > 1 && (
            <View style={styles.monthChipsWrap}>
              {months.slice(0, 6).map((m) => (
                <Pressable key={m} onPress={() => setMonth(m)} style={[styles.monthChip, m === month && styles.monthChipActive]}>
                  <Text style={[styles.monthChipText, m === month && styles.monthChipTextActive]}>{formatMonth(m, true)}</Text>
                </Pressable>
              ))}
            </View>
          )}
        </View>
        {data && (
          <View style={styles.countRow}>
            <CountPill label="Ready"        n={data.counts.ready}        kind="ready" />
            <CountPill label="Review"       n={data.counts.review}       kind="review" />
            <CountPill label="Conflict"     n={data.counts.conflict}     kind="conflict" />
            <CountPill label="Approved"     n={data.counts.approved}     kind="approved" />
            <CountPill label="Live"         n={data.counts.live}         kind="live" />
            <CountPill label="Locked"       n={data.counts.locked}       kind="locked" />
            {data.counts.ready > 0 && (
              <Pressable style={styles.approveBtn} onPress={approveReady} disabled={busy} testID="approve-ready-btn">
                <Text style={styles.approveBtnText}>{busy ? "Approving…" : `Approve ${data.counts.ready} Ready`}</Text>
              </Pressable>
            )}
            <Pressable
              style={styles.directiveBtn}
              onPress={() => setDirectiveOpen(true)}
              testID="add-directive-btn"
            >
              <Ionicons name="flag-outline" size={14} color={theme.color.textHi} />
              <Text style={styles.directiveBtnText}>Add directive</Text>
            </Pressable>
          </View>
        )}
      </View>

      {/* Programme summary panel — expandable header with goal + phase strip */}
      {data && <ProgrammeSummaryPanel clientId={String(clientId)} />}

      {/* Pipeline / async generation status */}
      {data && <GenerationStatusBanner clientId={String(clientId)} month={month} />}

      {/* Command bar — works for both V1 and V2 clients (directives + notes) */}
      {data && (
        <CommandBar
          clientId={String(clientId)}
          month={month}
          draftId={data?.programme?.draft_id}
          onApplied={loadMonth}
        />
      )}

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>
      ) : error ? (
        <View style={styles.center}><Text style={styles.err}>{error}</Text></View>
      ) : !data || data.days.length === 0 ? (
        <View style={styles.center}>
          <Text style={styles.emptyTitle}>No roster or plan for {formatMonth(month)}</Text>
          <Text style={styles.emptyBody}>Upload a roster from the client's profile, or ask them to upload one from their app.</Text>
        </View>
      ) : (
        <ScrollView style={{ flex: 1 }} contentContainerStyle={{ paddingBottom: 80 }} testID="workspace-scroll">
          {isDesktop && (
            <View style={styles.colHead}>
              <Text style={[styles.colHeadText, { flex: 1 }]}>ROSTER / REAL LIFE</Text>
              <Text style={[styles.colHeadText, { flex: 1 }]}>CREWFIT PLAN</Text>
            </View>
          )}
          {data.days.map((d) => (
            <DayRowView key={d.date} row={d} desktop={isDesktop}
              onOpenWorkout={(aid) => setDrawerAssignmentId(aid)} />
          ))}

          {/* Exceptions block */}
          {data.exceptions && data.exceptions.length > 0 && (
            <View style={{ padding: 16 }}>
              <Text style={styles.sectionTitle}>NEEDS ATTENTION</Text>
              {data.exceptions.map((e) => (
                <View key={e.id} style={styles.excCard}>
                  <View style={[styles.sevDot, { backgroundColor: e.severity === "blocker" ? "#ff6b6b" : "#f5b543" }]} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.excKind}>{humanise(e.kind)}</Text>
                    <Text style={styles.excReason}>{e.human_readable_reason || ""}</Text>
                  </View>
                </View>
              ))}
            </View>
          )}
        </ScrollView>
      )}

      {/* Workout drawer */}
      <WorkoutDrawer
        assignmentId={drawerAssignmentId}
        clientId={String(clientId)}
        onClose={() => setDrawerAssignmentId(null)}
        onEditRequested={(implId) => {
          setDrawerAssignmentId(null);
          if (implId) router.push(`/coach/workout/edit/${implId}` as any);
        }}
      />

      {/* Directive editor */}
      <DirectiveEditor
        clientId={String(clientId)}
        visible={directiveOpen}
        onClose={() => setDirectiveOpen(false)}
        onSaved={loadMonth}
      />
    </View>
  );
}

function CountPill({ label, n, kind }: { label: string; n: number; kind: string }) {
  if (!n) return null;
  return (
    <View style={[styles.countPill, { borderColor: STATUS_TINT[kind] || theme.color.border }]}>
      <Text style={[styles.countPillN, { color: STATUS_TINT[kind] || theme.color.textHi }]}>{n}</Text>
      <Text style={styles.countPillLabel}>{label}</Text>
    </View>
  );
}

function DayRowView({ row, desktop, onOpenWorkout }: {
  row: DayRow; desktop: boolean; onOpenWorkout: (aid: string) => void;
}) {
  const dt = fmtDate(row.date);
  const burden = row.schedule?.duty_burden_band;
  return (
    <View style={[styles.dayRow, desktop ? styles.dayRowDesktop : styles.dayRowMobile]}>
      {/* Date column */}
      <View style={styles.dateCol}>
        <Text style={styles.dateDow}>{dt.dow}</Text>
        <Text style={styles.dateD}>{dt.d}</Text>
        <Text style={styles.dateMon}>{dt.mon}</Text>
      </View>
      {/* Roster / real life */}
      <View style={[styles.rosterCol, desktop ? { flex: 1 } : {}]}>
        {row.schedule ? (
          <>
            <Text style={styles.rosterClassification}>{row.schedule.classification_label}</Text>
            {burden && (
              <View style={styles.burdenRow}>
                <View style={[styles.burdenDot, { backgroundColor: BURDEN_TINT[burden] || "#888" }]} />
                <Text style={styles.burdenTxt}>{humanise(burden)} burden</Text>
                {typeof row.schedule.training_opportunity === "number" && (
                  <Text style={styles.oppTxt}> · opportunity {row.schedule.training_opportunity}</Text>
                )}
              </View>
            )}
            {row.schedule.overnight_location?.city && (
              <Text style={styles.rosterMeta}>Overnight: {row.schedule.overnight_location.city}</Text>
            )}
            {row.schedule.v1_source && (
              <Text style={styles.v1Hint}>V1 roster · read-only</Text>
            )}
          </>
        ) : (
          <Text style={styles.rosterMeta}>—</Text>
        )}
      </View>
      {/* Plan */}
      <View style={[styles.planCol, desktop ? { flex: 1 } : {}]}>
        {row.assignments.length === 0 && (row.v1_workouts || []).length === 0 ? (
          <Text style={styles.planEmpty}>Rest</Text>
        ) : null}
        {row.assignments.map((a) => (
          <Pressable
            key={a.id}
            style={styles.planCard}
            onPress={() => onOpenWorkout(a.id)}
            testID={`open-workout-${a.id}`}
          >
            <View style={{ flex: 1 }}>
              <View style={styles.planCardTop}>
                {a.key_session && (
                  <Ionicons name="star" size={12} color="#f5b543" style={{ marginRight: 4 }} />
                )}
                <Text style={styles.planTitle} numberOfLines={1}>{humanise(a.kind || a.kind_label)}</Text>
                {a.exposure_sequence ? (
                  <Text style={styles.exposureTxt}> · #{a.exposure_sequence}</Text>
                ) : null}
              </View>
              <Text style={styles.planMeta} numberOfLines={1}>
                {a.duration_min ? `${a.duration_min} min` : ""}
                {a.equipment && a.equipment.length > 0 ? ` · ${a.equipment.slice(0, 3).join(", ")}` : ""}
              </Text>
            </View>
            <View style={styles.planRight}>
              <StatusChip kind={a.status_kind} label={a.status_label} />
            </View>
          </Pressable>
        ))}
        {(row.v1_workouts || []).map((w: any) => (
          <View key={w.id} style={[styles.planCard, { opacity: 0.85 }]}>
            <View style={{ flex: 1 }}>
              <Text style={styles.planTitle} numberOfLines={1}>{w.title || w.focus}</Text>
              <Text style={styles.planMeta}>{w.duration_min ? `${w.duration_min} min` : ""} · V1</Text>
            </View>
            <View style={styles.planRight}>
              {w.completed && <StatusChip kind="approved" label="Done" />}
              {!w.completed && w.approved && <StatusChip kind="live" label="Live" />}
              {!w.completed && !w.approved && <StatusChip kind="review" label="Review" />}
            </View>
          </View>
        ))}
      </View>
    </View>
  );
}

function StatusChip({ kind, label }: { kind: string; label: string }) {
  const tint = STATUS_TINT[kind] || theme.color.textDim;
  const bg = kind === "review" ? "#3b2d0d"
    : kind === "conflict" ? "#3a1414"
      : kind === "live" || kind === "ready" ? "#183020"
        : kind === "locked" ? "#22222c"
          : "#0d2c3b";
  return (
    <View style={[styles.statusChip, { backgroundColor: bg }]}>
      <Text style={[styles.statusChipText, { color: tint }]}>{label}</Text>
    </View>
  );
}

/* ---- Workout drawer ---- */

function WorkoutDrawer({
  assignmentId, clientId, onClose, onEditRequested,
}: {
  assignmentId: string | null;
  clientId: string;
  onClose: () => void;
  onEditRequested: (implId?: string | null) => void;
}) {
  const [detail, setDetail] = useState<any>(null);
  const [decisions, setDecisions] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!assignmentId) { setDetail(null); return; }
    setLoading(true);
    (async () => {
      try {
        const impl = await api<any>(`/v2/coach/clients/${clientId}/plan/implementations/${assignmentId}`).catch(() => null);
        setDetail(impl);
        const dr = await api<any>(`/v2/coach/clients/${clientId}/decisions?scope_id=${assignmentId}`).catch(() => ({ decisions: [] }));
        setDecisions(dr?.decisions || []);
      } finally { setLoading(false); }
    })();
  }, [assignmentId, clientId]);

  if (!assignmentId) return null;
  return (
    <Modal transparent animationType="fade" visible onRequestClose={onClose}>
      <View style={styles.drawerBackdrop}>
        <Pressable style={{ flex: 1 }} onPress={onClose} />
        <View style={styles.drawer}>
          <View style={styles.drawerHead}>
            <Text style={styles.drawerTitle} numberOfLines={2}>
              {detail?.title || "Session"}
            </Text>
            <Pressable onPress={onClose} testID="drawer-close">
              <Ionicons name="close" size={22} color={theme.color.textHi} />
            </Pressable>
          </View>
          {loading ? (
            <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>
          ) : !detail ? (
            <View style={{ padding: 16 }}>
              <Text style={styles.drawerBody}>No implementation available yet. Open the plan builder to generate one.</Text>
            </View>
          ) : (
            <ScrollView contentContainerStyle={{ padding: 16 }}>
              <Text style={styles.drawerMeta}>
                {detail.duration_min ? `${detail.duration_min} min` : ""} · {humanise(detail.focus || "")}
              </Text>
              {detail.equipment_context?.equipment?.length ? (
                <Text style={styles.drawerMeta}>Equipment: {detail.equipment_context.equipment.join(", ")}</Text>
              ) : null}
              {detail.rationale && <Text style={styles.rationale}>{detail.rationale}</Text>}
              <View style={{ height: 12 }} />
              {(detail.exercises || []).map((ex: any, i: number) => (
                <View key={i} style={styles.exRow}>
                  <Text style={styles.exName}>{ex.exercise_name_display || "Exercise"}</Text>
                  <Text style={styles.exMeta}>
                    {ex.sets ? `${ex.sets} × ${ex.reps || "—"}` : ""}
                    {ex.rpe ? ` · RPE ${ex.rpe}` : ""}
                    {ex.rest_sec ? ` · rest ${ex.rest_sec}s` : ""}
                  </Text>
                </View>
              ))}
              <View style={{ height: 20 }} />
              <Text style={styles.sectionTitle}>WHY THIS?</Text>
              {decisions.length === 0 ? (
                <Text style={styles.drawerBody}>No decision records for this assignment yet.</Text>
              ) : (
                decisions.slice(0, 6).map((d, i) => (
                  <View key={i} style={styles.decisionRow}>
                    <Text style={styles.decisionLayer}>{d.layer}</Text>
                    <Text style={styles.decisionReason}>{d.human_readable_reason}</Text>
                  </View>
                ))
              )}
              <View style={{ height: 20 }} />
              <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
                <Pressable style={styles.primaryBtn} onPress={() => onEditRequested(detail?.id)} testID="drawer-edit">
                  <Text style={styles.primaryBtnText}>Edit</Text>
                </Pressable>
              </View>
            </ScrollView>
          )}
        </View>
      </View>
    </Modal>
  );
}

/* ---- helpers ---- */

function humanise(s?: string): string {
  if (!s) return "";
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatMonth(m: string, short = false): string {
  if (!m) return "";
  const [y, mo] = m.split("-").map((s) => parseInt(s, 10));
  const dt = new Date(y, (mo || 1) - 1, 1);
  const name = dt.toLocaleDateString("en-GB", { month: short ? "short" : "long", year: "numeric" });
  return name;
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.bg },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  err: { color: "#ff6666" },
  emptyTitle: { color: theme.color.textHi, fontWeight: "700", fontSize: 16, marginBottom: 6 },
  emptyBody: { color: theme.color.textDim, textAlign: "center", maxWidth: 400 },

  header: {
    flexDirection: "row", alignItems: "center", padding: 16, paddingBottom: 4,
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  backBtn: { flexDirection: "row", alignItems: "center", padding: 4 },
  backTxt: { color: theme.color.textHi, marginLeft: 2 },
  clientName: { color: theme.color.textHi, fontSize: 22, fontWeight: "800" },
  subRow: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", marginTop: 2, gap: 8 },
  subMeta: { color: theme.color.textDim, fontSize: 12 },
  kindPill: { backgroundColor: "#22222c", paddingHorizontal: 8, paddingVertical: 3, borderRadius: 10 },
  kindPillText: { color: theme.color.textDim, fontSize: 10, fontWeight: "700", letterSpacing: 0.5 },

  ribbon: {
    padding: 12, backgroundColor: theme.color.surface2,
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  monthRow: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 6 },
  monthBtn: { padding: 6, borderRadius: 6, backgroundColor: "#00000030" },
  monthTitle: { color: theme.color.textHi, fontSize: 16, fontWeight: "700", marginHorizontal: 8, minWidth: 150 },
  monthChipsWrap: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginLeft: 8 },
  monthChip: {
    backgroundColor: "#00000030", paddingHorizontal: 10, paddingVertical: 4, borderRadius: 12,
    borderWidth: 1, borderColor: theme.color.border,
  },
  monthChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  monthChipText: { color: theme.color.textDim, fontSize: 11, fontWeight: "700" },
  monthChipTextActive: { color: "#000" },

  countRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 8, alignItems: "center" },
  countPill: {
    paddingHorizontal: 10, paddingVertical: 4, borderRadius: 12, borderWidth: 1,
    flexDirection: "row", alignItems: "center", gap: 6,
  },
  countPillN: { fontWeight: "800", fontSize: 13 },
  countPillLabel: { color: theme.color.textDim, fontSize: 10, letterSpacing: 0.5, fontWeight: "700", textTransform: "uppercase" },

  approveBtn: {
    marginLeft: "auto", backgroundColor: theme.color.brand, paddingHorizontal: 14, paddingVertical: 8,
    borderRadius: 6,
  },
  approveBtnText: { color: "#000", fontWeight: "800", letterSpacing: 0.5 },
  directiveBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    borderWidth: 1, borderColor: theme.color.border, borderRadius: 6,
    paddingHorizontal: 10, paddingVertical: 7, backgroundColor: "#00000030",
  },
  directiveBtnText: { color: theme.color.textHi, fontWeight: "700", fontSize: 12 },

  colHead: { flexDirection: "row", paddingHorizontal: 88, paddingTop: 12, paddingBottom: 6 },
  colHeadText: { color: theme.color.textDim, fontSize: 10, letterSpacing: 1.5, fontWeight: "800" },

  dayRow: {
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
    paddingVertical: 10, paddingHorizontal: 12,
  },
  dayRowDesktop: { flexDirection: "row", alignItems: "flex-start", gap: 12 },
  dayRowMobile: { flexDirection: "column", gap: 8 },

  dateCol: {
    width: 62, alignItems: "center", paddingTop: 2,
  },
  dateDow: { color: theme.color.textDim, fontSize: 10, letterSpacing: 0.5, fontWeight: "700" },
  dateD: { color: theme.color.textHi, fontSize: 22, fontWeight: "800", lineHeight: 24 },
  dateMon: { color: theme.color.textDim, fontSize: 10, letterSpacing: 0.5, fontWeight: "700" },

  rosterCol: { paddingLeft: 4, paddingRight: 4 },
  planCol: { paddingLeft: 4, paddingRight: 4, gap: 6 },

  rosterClassification: { color: theme.color.textHi, fontSize: 14, fontWeight: "700" },
  burdenRow: { flexDirection: "row", alignItems: "center", marginTop: 2 },
  burdenDot: { width: 6, height: 6, borderRadius: 3, marginRight: 6 },
  burdenTxt: { color: theme.color.textDim, fontSize: 11 },
  oppTxt: { color: theme.color.textDim, fontSize: 11 },
  rosterMeta: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  v1Hint: { color: "#f5b543", fontSize: 10, marginTop: 2, fontStyle: "italic" },

  planEmpty: { color: theme.color.textDim, fontStyle: "italic", fontSize: 12 },
  planCard: {
    backgroundColor: "#00000030", borderRadius: 6, borderWidth: 1, borderColor: theme.color.border,
    padding: 10, flexDirection: "row", alignItems: "center",
  },
  planCardTop: { flexDirection: "row", alignItems: "center" },
  planTitle: { color: theme.color.textHi, fontSize: 13, fontWeight: "700" },
  exposureTxt: { color: theme.color.textDim, fontSize: 11, marginLeft: 4 },
  planMeta: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },
  planRight: { marginLeft: 8 },

  statusChip: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 10 },
  statusChipText: { fontSize: 10, fontWeight: "800", letterSpacing: 0.3 },

  sectionTitle: { color: theme.color.textDim, fontSize: 11, letterSpacing: 1.5, fontWeight: "800", marginBottom: 8 },
  excCard: {
    backgroundColor: theme.color.surface2, borderRadius: 8, borderWidth: 1, borderColor: theme.color.border,
    padding: 12, marginBottom: 6, flexDirection: "row", gap: 10,
  },
  sevDot: { width: 8, height: 8, borderRadius: 4, marginTop: 6 },
  excKind: { color: theme.color.textHi, fontWeight: "700" },
  excReason: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },

  /* Drawer */
  drawerBackdrop: { flex: 1, flexDirection: "row", backgroundColor: "rgba(0,0,0,0.5)" },
  drawer: {
    width: Platform.OS === "web" ? 480 : "88%",
    backgroundColor: theme.color.bg,
    borderLeftWidth: 1, borderLeftColor: theme.color.border,
    height: "100%",
  },
  drawerHead: {
    flexDirection: "row", alignItems: "center", padding: 14,
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  drawerTitle: { flex: 1, color: theme.color.textHi, fontSize: 17, fontWeight: "800" },
  drawerBody: { color: theme.color.textDim },
  drawerMeta: { color: theme.color.textDim, marginBottom: 4 },
  rationale: {
    color: theme.color.textHi, marginTop: 8, fontStyle: "italic",
    backgroundColor: "#00000030", padding: 10, borderRadius: 6, borderLeftWidth: 3, borderLeftColor: theme.color.brand,
  },
  exRow: {
    paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  exName: { color: theme.color.textHi, fontWeight: "700" },
  exMeta: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  decisionRow: {
    paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: theme.color.border, flexDirection: "row", gap: 8,
  },
  decisionLayer: { color: theme.color.brand, fontSize: 10, fontWeight: "800", width: 70 },
  decisionReason: { color: theme.color.textDim, flex: 1, fontSize: 12 },

  primaryBtn: {
    backgroundColor: theme.color.brand, paddingHorizontal: 16, paddingVertical: 8, borderRadius: 6,
  },
  primaryBtnText: { color: "#000", fontWeight: "800" },
});
