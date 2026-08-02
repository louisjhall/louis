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
  Platform, useWindowDimensions, Modal, StatusBar, Alert,
} from "react-native";
import { useRouter, useLocalSearchParams } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { CommandBar } from "@/src/components/CommandBar";
import { DirectiveEditor } from "@/src/components/DirectiveEditor";
import { ClientAdminDrawer } from "@/src/components/ClientAdminDrawer";
// Iter 128f — density pass. Programme state now lives inline in the compact
// EngineV2DraftPanel ribbon; the standalone GenerationStatusBanner and
// ProgrammeSummaryPanel are no longer rendered in the Plan tab to reclaim
// vertical space for the actual Roster/Plan grid.
import { PublishPanel } from "@/src/components/PublishPanel";
import { InlineWorkoutEditor } from "@/src/components/InlineWorkoutEditor";
import { CoachRosterUploadButton } from "@/src/components/CoachRosterUploadButton";
import { V2ClientTabs, V2Tab } from "@/src/components/V2ClientTabs";
import EngineV2DraftPanel from "@/src/components/EngineV2DraftPanel";
import ManualWorkoutBuilderSheet from "@/src/components/ManualWorkoutBuilderSheet";
import DayActionsMenu, { DayState } from "@/src/components/DayActionsMenu";
import DeleteManualConfirmSheet from "@/src/components/DeleteManualConfirmSheet";
import MoveManualWorkoutSheet from "@/src/components/MoveManualWorkoutSheet";

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
  // Iter 117 — Aviation Support (Phase B) surfaced inline in Roster + Plan.
  flight_support?: {
    id: string;
    title: string;
    protocol_key: string;
    family: string;
    duration_min: number;
    trigger_reason?: string;
    is_bundle?: boolean;
    completion_status?: string;
  }[];
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
  const insets = useSafeAreaInsets();
  // Iter 130d — bullet-proof Android status-bar clearance.
  // Some Android skins with translucent status bars report insets.top === 0
  // in Expo Go, which caused the header to sit under the system time / signal
  // icons and made the ADMIN button untappable in the corner. We combine the
  // safe-area inset with `StatusBar.currentHeight` (Android-only) and floor
  // everything to a minimum of 24dp on Android / the reported inset on iOS.
  const rawInset = insets.top || 0;
  const androidSbHeight = Platform.OS === "android" ? (StatusBar.currentHeight || 0) : 0;
  const safeTop = Math.max(rawInset, androidSbHeight, Platform.OS === "android" ? 24 : 0);

  const [months, setMonths] = useState<string[]>([]);
  const [month, setMonth] = useState<string>("");
  const [data, setData] = useState<Workspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drawerAssignmentId, setDrawerAssignmentId] = useState<string | null>(null);
  const [adminDrawerOpen, setAdminDrawerOpen] = useState(false);
  // Iter 117 — Coach flight-support override sheet target.
  const [fsSheet, setFsSheet] = useState<{ date: string; item: any } | null>(null);
  const [directiveOpen, setDirectiveOpen] = useState(false);
  const [publishOpen, setPublishOpen] = useState(false);
  const [commandBarOpen, setCommandBarOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<V2Tab>("plan");

  // Phase 1 Manual Workout Builder — state
  const [dayMenuDate, setDayMenuDate] = useState<string | null>(null);
  const [manualBuilder, setManualBuilder] = useState<null | {
    date: string; editing: any | null; replaceGenerated: boolean;
  }>(null);
  const [deleteTarget, setDeleteTarget] = useState<null | {
    workout: any; wasReplacingGeneratedDay: boolean;
  }>(null);
  const [moveTarget, setMoveTarget] = useState<null | { workout: any }>(null);
  const [undoBanner, setUndoBanner] = useState<null | {
    workout_id: string; undo_token: any; label: string;
  }>(null);
  // date -> { id, mode, replacement_workout_id }
  const [overrides, setOverrides] = useState<Record<string, any>>({});
  // date -> manual workout doc (source=coach_manual)
  const [manualByDate, setManualByDate] = useState<Record<string, any>>({});

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

  // Phase 1 Manual Workout Builder — load active overrides for the visible month.
  const loadManualAndOverrides = useCallback(async () => {
    if (!clientId || !month) return;
    try {
      const ovRes = await api<{ overrides: any[] }>(`/coach/clients/${clientId}/day-overrides?active_only=true`);
      const ovMap: Record<string, any> = {};
      (ovRes.overrides || []).forEach(o => { ovMap[o.date] = o; });
      setOverrides(ovMap);
    } catch {
      // silent — overrides overlay is best-effort; core calendar still loads
    }
  }, [clientId, month]);

  // Manual workouts come from data.days[].v1_workouts (source === "coach_manual").
  useEffect(() => {
    const map: Record<string, any> = {};
    (data?.days || []).forEach((d: any) => {
      const m = (d.v1_workouts || []).find((w: any) => w?.source === "coach_manual");
      if (m) map[d.date] = m;
    });
    setManualByDate(map);
  }, [data]);

  useEffect(() => { loadMonths(); }, [loadMonths]);
  useEffect(() => { if (month) { loadMonth(); loadManualAndOverrides(); } }, [month, loadMonth, loadManualAndOverrides]);

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

  const kickoffBuild = useCallback(async () => {
    setBusy(true); setError(null);
    try {
      const res = await api<{ assignments_created: number; implementations_created: number }>(
        `/v2/coach/clients/${clientId}/plan/kickoff`,
        { method: "POST", body: { weeks: 8 } }
      );
      await loadMonth();
      // Surface a summary error banner if 0 assignments were created
      if (!res.assignments_created) {
        setError("Plan built but no sessions could be scheduled. Check the schedule days.");
      }
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally { setBusy(false); }
  }, [clientId, loadMonth]);

  const stepMonth = useCallback((delta: number) => {
    if (!month) return;
    const [y, m] = month.split("-").map((s) => parseInt(s, 10));
    const dt = new Date(y, m - 1 + delta, 1);
    const next = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}`;
    setMonth(next);
  }, [month]);

  // Phase 1 Manual Workout Builder — helpers
  const computeDayState = useCallback((row: DayRow): DayState => {
    const override = overrides[row.date];
    if (override) {
      return override.mode === "replace_day" ? "replaced" : "suppressed";
    }
    const manual = manualByDate[row.date];
    if (manual) return "manual";
    const hasGenerated =
      (row.assignments?.length || 0) > 0 ||
      (row.v1_workouts || []).some((w: any) => w?.source !== "coach_manual");
    return hasGenerated ? "generated" : "empty";
  }, [overrides, manualByDate]);

  const openBuilderForCreate = useCallback((date: string, replaceGenerated: boolean) => {
    setManualBuilder({ date, editing: null, replaceGenerated });
  }, []);

  const openBuilderForEdit = useCallback(async (manualStub: any) => {
    if (!manualStub?.id) return;
    try {
      const full = await api<any>(`/workouts/${manualStub.id}`);
      setManualBuilder({ date: full.date, editing: full, replaceGenerated: false });
    } catch (e: any) {
      setError(e?.message || String(e));
    }
  }, []);

  const suppressDay = useCallback(async (date: string) => {
    setBusy(true);
    try {
      await api(`/coach/clients/${clientId}/day-overrides/${date}`, {
        method: "POST", body: { mode: "suppress_day", reason: "coach suppress_day" },
      });
      await loadManualAndOverrides();
      await loadMonth();
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally { setBusy(false); }
  }, [clientId, loadManualAndOverrides, loadMonth]);

  const restoreDay = useCallback(async (date: string) => {
    setBusy(true);
    try {
      await api(`/coach/clients/${clientId}/day-overrides/${date}`, { method: "DELETE" });
      await loadManualAndOverrides();
      await loadMonth();
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally { setBusy(false); }
  }, [clientId, loadManualAndOverrides, loadMonth]);

  const askDeleteManual = useCallback(async (manualStub: any, date: string) => {
    if (!manualStub?.id) return;
    try {
      const full = await api<any>(`/workouts/${manualStub.id}`);
      const wasReplacing = !!overrides[date] && overrides[date].mode === "replace_day";
      setDeleteTarget({ workout: full, wasReplacingGeneratedDay: wasReplacing });
    } catch (e: any) {
      setError(e?.message || String(e));
    }
  }, [overrides]);

  const askMoveManual = useCallback(async (manualStub: any) => {
    if (!manualStub?.id) return;
    try {
      const full = await api<any>(`/workouts/${manualStub.id}`);
      setMoveTarget({ workout: full });
    } catch (e: any) {
      setError(e?.message || String(e));
    }
  }, []);

  const undoMove = useCallback(async () => {
    if (!undoBanner) return;
    setBusy(true);
    try {
      await api(`/coach/workouts/${undoBanner.workout_id}/manual/undo-move`, {
        method: "POST", body: { undo_token: undoBanner.undo_token },
      });
      setUndoBanner(null);
      await loadManualAndOverrides();
      await loadMonth();
    } catch (e: any) {
      Alert.alert("Could not undo move", e?.message || "Please try again.");
    } finally { setBusy(false); }
  }, [undoBanner, loadManualAndOverrides, loadMonth]);

  if (!clientId) {
    return <View style={styles.center}><Text style={styles.err}>No client id</Text></View>;
  }

  return (
    <View style={[styles.root, { paddingTop: safeTop }]} testID="coach-workspace">
      {/* Iter 128f — Compact client header (one row, ~44px).
          State (LIVE / DRAFT / NO PLAN) lives in the EngineV2DraftPanel
          ribbon below the tabs so it isn't duplicated up here. */}
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} style={styles.backBtn} testID="workspace-back">
          <Ionicons name="chevron-back" size={18} color={theme.color.textHi} />
          <Text style={styles.backTxt}>Back</Text>
        </Pressable>
        <Text style={styles.clientName} numberOfLines={1}>{data?.client?.name || "…"}</Text>
        <View style={{ flex: 1 }} />
        <Pressable
          onPress={() => setAdminDrawerOpen(true)}
          style={styles.adminBtn}
          testID="workspace-admin-btn"
          accessibilityLabel="Client admin"
          hitSlop={{ top: 12, bottom: 12, left: 8, right: 12 }}
        >
          <Ionicons name="settings-outline" size={14} color={theme.color.textHi} />
          <Text style={styles.adminBtnText}>ADMIN</Text>
        </Pressable>
      </View>

      {/* V2 client tabs — Plan (default) + Check-ins / Messages / Progress / History / Goals */}
      <TabBar active={activeTab} onChange={setActiveTab} />

      {activeTab !== "plan" ? (
        <V2ClientTabs
          clientId={String(clientId)}
          tab={activeTab}
        />
      ) : (
      <>
      {/* Iter 128f — One compact Plan toolbar (~44px) merges month
          navigation with Directive / Ask CrewFit / Upload Roster and a
          Ready-approval mini-pill when appropriate. Build/Publish live
          in the EngineV2DraftPanel ribbon (below) so they aren't duplicated. */}
      {data && (
        <View style={styles.toolbar}>
          <Pressable onPress={() => stepMonth(-1)} style={styles.monthBtn} testID="month-prev">
            <Ionicons name="chevron-back" size={16} color={theme.color.textHi} />
          </Pressable>
          <Text style={styles.monthTitle}>{formatMonth(month)}</Text>
          <Pressable onPress={() => stepMonth(1)} style={styles.monthBtn} testID="month-next">
            <Ionicons name="chevron-forward" size={16} color={theme.color.textHi} />
          </Pressable>
          <View style={styles.toolbarDivider} />
          <Pressable
            style={styles.tbBtn}
            onPress={() => setDirectiveOpen(true)}
            testID="add-directive-btn"
          >
            <Ionicons name="flag-outline" size={13} color={theme.color.textHi} />
            <Text style={styles.tbBtnText}>Directive</Text>
          </Pressable>
          <Pressable
            style={[styles.tbBtn, commandBarOpen && styles.tbBtnActive]}
            onPress={() => setCommandBarOpen((v) => !v)}
            testID="ask-crewfit-btn"
          >
            <Ionicons name="sparkles-outline" size={13} color={theme.color.brand} />
            <Text style={[styles.tbBtnText, { color: theme.color.brand }]}>Ask CrewFit</Text>
          </Pressable>
          <CoachRosterUploadButton
            clientId={String(clientId)}
            clientName={data.client?.name}
            onComplete={loadMonth}
            compact
          />
          {data.counts?.ready > 0 && (
            <Pressable
              style={styles.approveMini}
              onPress={approveReady}
              disabled={busy}
              testID="approve-ready-btn"
            >
              <Ionicons name="checkmark" size={13} color="#000" />
              <Text style={styles.approveMiniText}>
                {busy ? "…" : `Approve ${data.counts.ready} Ready`}
              </Text>
            </Pressable>
          )}
        </View>
      )}

      {/* Iter 128f — Compact Engine V2 state ribbon (single row, collapsible).
          Handles LIVE / DRAFT / NO PLAN / BUILDING states + quick actions
          (Compare / Review / Publish / Rebuild) without a big permanent card. */}
      {data && <EngineV2DraftPanel clientId={String(clientId)} onPublished={loadMonth} />}

      {/* Iter 128f — Ask CrewFit command bar. Hidden by default; opens on
          toolbar button click and collapses back to its trigger on close. */}
      {data && commandBarOpen && (
        <CommandBar
          clientId={String(clientId)}
          month={month}
          draftId={data?.programme?.draft_id}
          onApplied={loadMonth}
          defaultExpanded
          onClose={() => setCommandBarOpen(false)}
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
        <ScrollView
          style={{ flex: 1 }}
          contentContainerStyle={{ paddingBottom: 60 }}
          testID="workspace-scroll"
          stickyHeaderIndices={isDesktop ? [0] : undefined}
        >
          {isDesktop && (
            <View style={styles.colHead}>
              <Text style={[styles.colHeadText, { flex: 1 }]}>ROSTER / REAL LIFE</Text>
              <Text style={[styles.colHeadText, { flex: 1 }]}>CREWFIT PLAN</Text>
            </View>
          )}
          {data.days.map((d) => (
            <DayRowView key={d.date} row={d} desktop={isDesktop}
              dayState={computeDayState(d)}
              manualStub={manualByDate[d.date]}
              onOpenWorkout={(aid) => setDrawerAssignmentId(aid)}
              onOpenFlightSupport={(date, fs) => setFsSheet({ date, item: fs })}
              onPressDate={() => setDayMenuDate(d.date)} />
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
      </>
      )}

      {/* Workout drawer */}
      <WorkoutDrawer
        assignmentId={drawerAssignmentId}
        clientId={String(clientId)}
        onClose={() => setDrawerAssignmentId(null)}
        onEdited={loadMonth}
      />

      {/* Iter 117 — Flight Support override sheet */}
      <FlightSupportOverrideSheet
        target={fsSheet}
        clientId={String(clientId)}
        onClose={() => setFsSheet(null)}
        onDone={() => { setFsSheet(null); loadMonth(); }}
      />

      {/* Directive editor */}
      <DirectiveEditor
        clientId={String(clientId)}
        visible={directiveOpen}
        onClose={() => setDirectiveOpen(false)}
        onSaved={loadMonth}
      />

      {/* Publish panel */}
      <PublishPanel
        clientId={String(clientId)}
        month={month}
        draftId={data?.programme?.draft_id}
        visible={publishOpen}
        onClose={() => setPublishOpen(false)}
        onPublished={loadMonth}
      />
      <ClientAdminDrawer
        visible={adminDrawerOpen}
        onClose={() => setAdminDrawerOpen(false)}
        clientId={String(clientId)}
      />

      {/* Phase 1 Manual Workout Builder — Day actions menu */}
      {dayMenuDate && (() => {
        const row = data?.days?.find(d => d.date === dayMenuDate);
        if (!row) return null;
        const state = computeDayState(row);
        const manualStub = manualByDate[dayMenuDate];
        return (
          <DayActionsMenu
            visible={!!dayMenuDate}
            date={dayMenuDate}
            state={state}
            onClose={() => setDayMenuDate(null)}
            onCreateManual={() => openBuilderForCreate(dayMenuDate, false)}
            onReplaceGenerated={() => openBuilderForCreate(dayMenuDate, true)}
            onSuppressDay={() => suppressDay(dayMenuDate)}
            onRestoreDay={() => restoreDay(dayMenuDate)}
            onOpenManual={() => openBuilderForEdit(manualStub)}
            onEditManual={() => openBuilderForEdit(manualStub)}
            onDeleteManual={() => askDeleteManual(manualStub, dayMenuDate)}
            onMoveManual={() => askMoveManual(manualStub)}
          />
        );
      })()}

      {/* Phase 1 Manual Workout Builder — Builder sheet */}
      {manualBuilder && (
        <ManualWorkoutBuilderSheet
          visible={!!manualBuilder}
          onClose={() => setManualBuilder(null)}
          onSaved={async (result) => {
            setManualBuilder(null);
            await loadManualAndOverrides();
            await loadMonth();
            const n = (result?.missing_media || []).length;
            if (n > 0) {
              try {
                const { Alert } = require("react-native");
                Alert.alert("Media queued",
                  `${n} exercise${n === 1 ? " has" : "s have"} been added to the media queue.`);
              } catch {}
            }
          }}
          clientId={String(clientId)}
          date={manualBuilder.date}
          editing={manualBuilder.editing}
          replaceGenerated={manualBuilder.replaceGenerated}
        />
      )}

      {/* Phase 1 Manual Workout Builder — Delete confirmation */}
      {deleteTarget && (
        <DeleteManualConfirmSheet
          visible={!!deleteTarget}
          onClose={() => setDeleteTarget(null)}
          onDeleted={async () => {
            setDeleteTarget(null);
            await loadManualAndOverrides();
            await loadMonth();
          }}
          workout={deleteTarget.workout}
          wasReplacingGeneratedDay={deleteTarget.wasReplacingGeneratedDay}
        />
      )}

      {/* Phase 1.5 — Move manual workout */}
      {moveTarget && (
        <MoveManualWorkoutSheet
          visible={!!moveTarget}
          onClose={() => setMoveTarget(null)}
          workout={moveTarget.workout}
          days={data?.days || []}
          clientId={String(clientId)}
          onMoved={async (res) => {
            setMoveTarget(null);
            setUndoBanner({
              workout_id: res.workout.id,
              undo_token: res.undo_token,
              label: `Moved ${res.moved_from} → ${res.moved_to}`,
            });
            await loadManualAndOverrides();
            await loadMonth();
          }}
        />
      )}

      {/* Phase 1.5 — Undo banner after a successful move */}
      {undoBanner && (
        <View style={styles.undoBanner} pointerEvents="box-none">
          <View style={styles.undoInner}>
            <Ionicons name="checkmark-circle" size={18} color="#61c982" />
            <Text style={styles.undoText}>{undoBanner.label}</Text>
            <Pressable
              onPress={undoMove}
              style={styles.undoBtn}
              testID="undo-move-btn"
            >
              <Text style={styles.undoBtnText}>Undo</Text>
            </Pressable>
            <Pressable onPress={() => setUndoBanner(null)} testID="undo-close-btn" style={{ paddingHorizontal: 6 }}>
              <Ionicons name="close" size={16} color={theme.color.textHi} />
            </Pressable>
          </View>
        </View>
      )}
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

/* ---- V2 client tab bar ---- */
const TABS: { key: V2Tab; label: string; icon: any }[] = [
  { key: "plan",      label: "Plan",      icon: "calendar-outline" },
  { key: "checkins",  label: "Check-ins", icon: "heart-outline" },
  { key: "messages",  label: "Messages",  icon: "chatbubble-outline" },
  { key: "progress",  label: "Progress",  icon: "trending-up-outline" },
  { key: "history",   label: "History",   icon: "time-outline" },
  { key: "goals",     label: "Goals",     icon: "flag-outline" },
];

function TabBar({ active, onChange }: { active: V2Tab; onChange: (t: V2Tab) => void }) {
  return (
    <View style={styles.tabBar} testID="v2-tabbar">
      {TABS.map((t) => {
        const on = t.key === active;
        return (
          <Pressable
            key={t.key}
            onPress={() => onChange(t.key)}
            style={[styles.tabBtn, on && styles.tabBtnActive]}
            testID={`v2-tab-${t.key}`}
          >
            <Ionicons name={t.icon} size={14} color={on ? theme.color.brand : theme.color.textDim} />
            <Text style={[styles.tabBtnText, on && styles.tabBtnTextActive]}>{t.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

function DayRowView({ row, desktop, dayState, manualStub, onOpenWorkout, onOpenFlightSupport, onPressDate }: {
  row: DayRow; desktop: boolean;
  dayState: DayState;
  manualStub: any | undefined;
  onOpenWorkout: (aid: string) => void;
  onOpenFlightSupport: (date: string, item: any) => void;
  onPressDate: () => void;
}) {
  const dt = fmtDate(row.date);
  const burden = row.schedule?.duty_burden_band;
  const badge = dayState === "manual" ? { label: "MANUAL", color: "#5aa9e6" }
              : dayState === "replaced" ? { label: "REPLACED", color: "#f5b543" }
              : dayState === "suppressed" ? { label: "HIDDEN", color: "#8e8e93" }
              : null;
  return (
    <View style={[styles.dayRow, desktop ? styles.dayRowDesktop : styles.dayRowMobile]}>
      {/* Date column — Phase 1: clickable → DayActionsMenu */}
      <Pressable
        style={styles.dateCol}
        onPress={onPressDate}
        testID={`day-press-${row.date}`}
        accessibilityLabel={`Open day actions for ${row.date}`}
        hitSlop={4}
      >
        <Text style={styles.dateDow}>{dt.dow}</Text>
        <Text style={styles.dateD}>{dt.d}</Text>
        <Text style={styles.dateMon}>{dt.mon}</Text>
        {badge && (
          <View style={{ marginTop: 4, backgroundColor: badge.color, paddingHorizontal: 4, paddingVertical: 1, borderRadius: 4 }}>
            <Text style={{ color: "#000", fontWeight: "700", fontSize: 8 }}>{badge.label}</Text>
          </View>
        )}
      </Pressable>
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
        {/* Iter 117 — Aviation Support inline. Visually secondary (border
            + smaller card) so it can't be mistaken for programme training.
            Coach can tap to open the FlightSupportOverrideSheet. */}
        {row.flight_support && row.flight_support.length > 0 ? (
          <View style={styles.fsWrap}>
            <Text style={styles.fsLabel}>FLIGHT SUPPORT</Text>
            {row.flight_support.map((fs) => (
              <Pressable
                key={fs.id}
                onPress={() => onOpenFlightSupport(row.date, fs)}
                style={styles.fsCard}
                testID={`fs-open-${row.date}-${fs.protocol_key}`}
              >
                <Ionicons name="airplane-outline" size={11} color="#8e8e93" style={{ marginRight: 6 }} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.fsTitleTxt} numberOfLines={1}>
                    {fs.title}
                    {fs.is_bundle ? " · bundle" : ""}
                  </Text>
                  {fs.trigger_reason ? (
                    <Text style={styles.fsReasonTxt} numberOfLines={1}>{fs.trigger_reason}</Text>
                  ) : null}
                </View>
                <Text style={styles.fsDurTxt}>{fs.duration_min}m</Text>
                {fs.completion_status === "completed" ? (
                  <Ionicons name="checkmark-circle" size={12} color="#61c982" style={{ marginLeft: 4 }} />
                ) : fs.completion_status === "skipped" ? (
                  <Ionicons name="close-circle" size={12} color="#8e8e93" style={{ marginLeft: 4 }} />
                ) : null}
              </Pressable>
            ))}
          </View>
        ) : null}
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
  assignmentId, clientId, onClose, onEdited,
}: {
  assignmentId: string | null;
  clientId: string;
  onClose: () => void;
  onEdited: () => void;
}) {
  const [detail, setDetail] = useState<any>(null);
  const [decisions, setDecisions] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<"view" | "edit">("view");
  const [editErr, setEditErr] = useState<string | null>(null);

  useEffect(() => {
    if (!assignmentId) { setDetail(null); setMode("view"); return; }
    setLoading(true);
    (async () => {
      try {
        if (assignmentId.startsWith("v2p:")) {
          // Engine V2 placement: id shape → "v2p:<source_id>:<exposure_id>"
          const parts = assignmentId.split(":");
          const sourceId = parts[1];
          const exposureId = parts.slice(2).join(":");
          // Try live first, then fall back to draft (matches workspace_month
          // preference order — safe if the coach's calendar is showing a
          // draft preview because plan_live_v2 hasn't been created yet).
          let raw: any = null;
          try {
            raw = await api<any>(
              `/v2/coach/clients/${clientId}/engine-v2/placement-detail?source=live&source_id=${encodeURIComponent(sourceId)}&exposure_id=${encodeURIComponent(exposureId)}`
            );
          } catch {
            raw = await api<any>(
              `/v2/coach/clients/${clientId}/engine-v2/placement-detail?source=draft&source_id=${encodeURIComponent(sourceId)}&exposure_id=${encodeURIComponent(exposureId)}`
            ).catch(() => null);
          }
          setDetail(raw ? adaptV2PlacementToDrawer(raw) : null);
          setDecisions([]);
        } else {
          const impl = await api<any>(`/v2/coach/clients/${clientId}/plan/implementations/${assignmentId}`).catch(() => null);
          setDetail(impl);
          // P1-2: use assignment_id so scope expands to include objective + programme + phase decisions
          const dr = await api<any>(`/v2/coach/clients/${clientId}/decisions?assignment_id=${assignmentId}&limit=20`).catch(() => ({ decisions: [] }));
          setDecisions(dr?.decisions || []);
        }
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
          ) : mode === "edit" ? (
            <>
              {editErr && (
                <View style={styles.editErrorBanner}>
                  <Ionicons name="alert-circle" size={14} color="#ff6666" />
                  <Text style={styles.editErrorText}>{editErr}</Text>
                </View>
              )}
              <InlineWorkoutEditor
                clientId={clientId}
                impl={detail}
                onExit={() => { setMode("view"); onEdited(); }}
                onSaved={(fresh) => { setDetail(fresh); onEdited(); }}
                onError={(msg) => setEditErr(msg)}
              />
            </>
          ) : (
            <ScrollView contentContainerStyle={{ padding: 16 }}>
              <Text style={styles.drawerMeta}>
                {detail.duration_min ? `${detail.duration_min} min` : ""} · {humanise(detail.focus || "")}
              </Text>
              {detail.equipment_context?.equipment?.length ? (
                <Text style={styles.drawerMeta}>Equipment: {detail.equipment_context.equipment.join(", ")}</Text>
              ) : null}
              {detail.rationale && <Text style={styles.rationale}>{detail.rationale}</Text>}
              {detail.coach_notes ? (
                <View style={styles.coachNote}>
                  <Text style={styles.coachNoteLabel}>COACH NOTE</Text>
                  <Text style={styles.coachNoteText}>{detail.coach_notes}</Text>
                </View>
              ) : null}
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
              {/* P1-3: render endurance blocks */}
              {(detail.blocks || []).map((bl: any, i: number) => (
                <View key={`bl-${i}`} style={styles.exRow}>
                  <Text style={styles.exName}>
                    {String(bl.type || "block").toUpperCase()}
                    {bl.duration_min ? ` · ${bl.duration_min} min` : ""}
                  </Text>
                  <Text style={styles.exMeta}>
                    {bl.hr_zone ? `${String(bl.hr_zone).toUpperCase()}` : ""}
                    {bl.pace_target ? ` · ${bl.pace_target}` : ""}
                    {bl.effort_rpe ? ` · RPE ${bl.effort_rpe}` : ""}
                    {bl.sets ? ` · ${bl.sets} × ${bl.work_sec}s / ${bl.rest_sec}s` : ""}
                  </Text>
                  {bl.cue ? <Text style={styles.exMeta}>{bl.cue}</Text> : null}
                </View>
              ))}
              {(!detail.exercises?.length && !detail.blocks?.length) ? (
                <View style={styles.exRow}>
                  <Text style={styles.exName}>Needs coach review</Text>
                  <Text style={styles.exMeta}>
                    Auto-build didn&apos;t match a template. Edit inline to add content.
                  </Text>
                </View>
              ) : null}
              <View style={{ height: 20 }} />
              <Text style={styles.sectionTitle}>WHY THIS?</Text>
              {detail._v2_placement ? (
                <View style={styles.decisionRow}>
                  <Text style={styles.decisionLayer}>ENGINE V2</Text>
                  <Text style={styles.decisionReason}>
                    {detail.rationale || "Scheduled by Engine V2 (WHAT→WHEN→HOW)."}
                    {detail._v2_intensity ? `  ·  intensity: ${detail._v2_intensity}` : ""}
                    {detail._v2_key ? "  ·  KEY session" : ""}
                  </Text>
                </View>
              ) : decisions.length === 0 ? (
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
              {!detail._v2_placement && (
                <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
                  <Pressable style={styles.primaryBtn} onPress={() => { setEditErr(null); setMode("edit"); }} testID="drawer-edit">
                    <Ionicons name="create-outline" size={14} color="#000" />
                    <Text style={styles.primaryBtnText}>Edit inline</Text>
                  </Pressable>
                </View>
              )}
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

/**
 * Convert an Engine V2 placement-detail response into the shape the workout
 * drawer expects (title, duration_min, focus, equipment_context, rationale,
 * blocks/exercises). Non-destructive: pure mapping.
 *
 * Session spec payloads shipped by feature_v2_construction_v2:
 *   running/cycling/swim/brick:  { warmup, main, cooldown }
 *   strength:                    { exercises: [...] }
 *   mobility/recovery/activation/travel_recovery: { flow_blocks | ... }
 */
function adaptV2PlacementToDrawer(r: any): any {
  const p = r?.placement || {};
  const s = r?.session_spec || {};
  const kind: string = p.kind || s.kind || "session";
  const payload: any = s.payload || {};
  const blocks: any[] = [];

  const push = (b: any) => { if (b && b.duration_min) blocks.push(b); };
  const _wu = payload.warmup;
  const _main = payload.main;
  const _cd = payload.cooldown;

  if (s.spec_kind === "running" || s.spec_kind === "cycling"
      || s.spec_kind === "swimming" || s.spec_kind === "brick") {
    if (_wu) push({ type: "warmup", duration_min: _wu.duration_min,
                     hr_zone: _wu.hr_zone, cue: _wu.cue });
    if (_main) push({ type: _main.type || "main", duration_min: _main.duration_min,
                       hr_zone: _main.hr_zone, pace_target: _main.pace_target,
                       power_target: _main.power_target,
                       cadence: _main.cadence,
                       sets: _main.reps, work_sec: _main.work_sec, rest_sec: _main.rest_sec,
                       cue: _main.cue || _main.fuel_cue });
    if (_cd) push({ type: "cooldown", duration_min: _cd.duration_min,
                     hr_zone: _cd.hr_zone, cue: _cd.cue });
    // Brick shape → payload.segments[]
    (payload.segments || []).forEach((seg: any) => {
      push({ type: seg.type || seg.modality || "segment",
             duration_min: seg.duration_min, hr_zone: seg.hr_zone,
             pace_target: seg.pace_target, cue: seg.cue });
    });
  } else if (s.spec_kind === "mobility" || s.spec_kind === "recovery"
             || s.spec_kind === "activation" || s.spec_kind === "travel_recovery") {
    (payload.flow_blocks || payload.blocks || []).forEach((b: any) => {
      push({ type: b.name || b.type || "block",
             duration_min: b.duration_min || (b.duration_sec ? Math.max(1, Math.round(b.duration_sec / 60)) : 0),
             cue: b.cue });
    });
  }

  const exercises: any[] = (s.spec_kind === "strength")
    ? (payload.exercises || []).map((ex: any) => ({
        exercise_name_display: ex.name || ex.exercise || "Exercise",
        sets: ex.sets, reps: ex.reps,
        rpe: ex.rpe || ex.load_target,
        rest_sec: ex.rest_sec,
      }))
    : [];

  return {
    title: humanise(kind) + (p.exposure_number ? ` · #${p.exposure_number}` : ""),
    duration_min: s.duration_min || p.target_duration_min,
    focus: s.spec_kind || kind,
    equipment_context: {
      equipment: (s.equipment_used || []).slice(0, 6),
      environment: s.environment,
    },
    rationale: s.rationale || "",
    coach_notes: r.coach_note || "",
    exercises,
    blocks,
    _v2_placement: true,
    _v2_intensity: p.intensity_target || s.intensity_target,
    _v2_key: !!p.key,
  };
}

function formatMonth(m: string, short = false): string {
  if (!m) return "";
  const [y, mo] = m.split("-").map((s) => parseInt(s, 10));
  const dt = new Date(y, (mo || 1) - 1, 1);
  const name = dt.toLocaleDateString("en-GB", { month: short ? "short" : "long", year: "numeric" });
  return name;
}

const styles = StyleSheet.create({
  undoBanner: { position: "absolute", left: 16, right: 16, bottom: 24, alignItems: "center", zIndex: 1000 },
  undoInner: { flexDirection: "row", alignItems: "center", backgroundColor: theme.color.card, borderWidth: 1, borderColor: theme.color.border, borderRadius: 12, paddingVertical: 10, paddingHorizontal: 14, gap: 10, maxWidth: 480 },
  undoText: { color: theme.color.textHi, fontSize: 13, flex: 1 },
  undoBtn: { backgroundColor: theme.color.brand, paddingHorizontal: 12, paddingVertical: 6, borderRadius: 6 },
  undoBtnText: { color: "#000", fontWeight: "700", fontSize: 12 },
  root: { flex: 1, backgroundColor: theme.color.bg },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  err: { color: "#ff6666" },
  emptyTitle: { color: theme.color.textHi, fontWeight: "700", fontSize: 16, marginBottom: 6 },
  emptyBody: { color: theme.color.textDim, textAlign: "center", maxWidth: 400 },

  header: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: 14, paddingVertical: 10, gap: 6,
    minHeight: 48,
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  backBtn: { flexDirection: "row", alignItems: "center", padding: 8, marginRight: 4, minWidth: 48, minHeight: 44 },
  backTxt: { color: theme.color.textHi, marginLeft: 1, fontSize: 13 },
  adminBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    paddingHorizontal: 12,
    paddingVertical: 10,
    minHeight: 44,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: theme.color.border,
    backgroundColor: theme.color.surface2,
  },
  adminBtnText: {
    color: theme.color.textHi,
    fontSize: 10,
    letterSpacing: 1.2,
    fontWeight: "800",
  },
  clientName: { color: theme.color.textHi, fontSize: 17, fontWeight: "800" },
  subRow: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", marginTop: 2, gap: 8 },
  subMeta: { color: theme.color.textDim, fontSize: 12 },
  kindPill: { backgroundColor: "#22222c", paddingHorizontal: 8, paddingVertical: 3, borderRadius: 10 },
  kindPillText: { color: theme.color.textDim, fontSize: 10, fontWeight: "700", letterSpacing: 0.5 },

  /* Iter 128f — compact plan toolbar (single row, ~44px). */
  toolbar: {
    flexDirection: "row", alignItems: "center", flexWrap: "wrap",
    paddingHorizontal: 12, paddingVertical: 6, gap: 6,
    backgroundColor: theme.color.surface2,
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  monthBtn: { padding: 4, borderRadius: 5, backgroundColor: "#00000030" },
  monthTitle: {
    color: theme.color.textHi, fontSize: 13, fontWeight: "700",
    marginHorizontal: 4, minWidth: 100, textAlign: "center",
  },
  toolbarDivider: {
    width: 1, height: 18, backgroundColor: theme.color.border,
    marginHorizontal: 4,
  },
  tbBtn: {
    flexDirection: "row", alignItems: "center", gap: 5,
    paddingHorizontal: 9, paddingVertical: 5, borderRadius: 6,
    borderWidth: 1, borderColor: theme.color.border,
    backgroundColor: "#00000030",
  },
  tbBtnActive: {
    borderColor: theme.color.brand, backgroundColor: "rgba(219,58,74,0.10)",
  },
  tbBtnText: { color: theme.color.textHi, fontSize: 12, fontWeight: "700" },
  approveMini: {
    marginLeft: "auto", flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: theme.color.brand, paddingHorizontal: 10, paddingVertical: 5,
    borderRadius: 6,
  },
  approveMiniText: { color: "#000", fontWeight: "800", fontSize: 11, letterSpacing: 0.3 },

  /* Legacy (kept for callers we don't render now) */
  ribbon: {
    padding: 12, backgroundColor: theme.color.surface2,
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  monthRow: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 6 },
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
  publishBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    borderRadius: 6, paddingHorizontal: 12, paddingVertical: 8,
    backgroundColor: theme.color.brand,
  },
  publishBtnText: { color: "#000", fontWeight: "800", fontSize: 12, letterSpacing: 0.3 },
  tabBar: {
    flexDirection: "row", gap: 3, paddingHorizontal: 12, paddingVertical: 5,
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
    backgroundColor: theme.color.surface2, flexWrap: "wrap",
  },
  tabBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 10, paddingVertical: 5, borderRadius: 5,
    borderWidth: 1, borderColor: "transparent",
  },
  tabBtnActive: {
    borderColor: theme.color.brand, backgroundColor: "#00000030",
  },
  tabBtnText: {
    color: theme.color.textDim, fontSize: 11.5, fontWeight: "700",
  },
  tabBtnTextActive: { color: theme.color.brand },

  colHead: {
    flexDirection: "row", paddingHorizontal: 88, paddingTop: 8, paddingBottom: 6,
    backgroundColor: theme.color.bg,
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  colHeadText: { color: theme.color.textDim, fontSize: 10, letterSpacing: 1.5, fontWeight: "800" },

  dayRow: {
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
    paddingVertical: 6, paddingHorizontal: 12,
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
  // Iter 117 — Aviation Support inline row in Roster + Plan
  fsWrap: {
    marginTop: 10, paddingTop: 8,
    borderTopWidth: 1, borderTopColor: theme.color.border,
    gap: 4,
  },
  fsLabel: {
    color: theme.color.textDim, fontSize: 9, fontWeight: "800",
    letterSpacing: 1.4,
  },
  fsCard: {
    flexDirection: "row", alignItems: "center",
    paddingVertical: 6, paddingHorizontal: 8,
    borderRadius: 6, backgroundColor: "#00000022",
    borderLeftWidth: 2, borderLeftColor: theme.color.brand,
  },
  fsTitleTxt: { color: theme.color.textHi, fontSize: 11, fontWeight: "600" },
  fsReasonTxt: { color: theme.color.textDim, fontSize: 10, marginTop: 1 },
  fsDurTxt: {
    color: theme.color.brand, fontSize: 11, fontWeight: "700", marginLeft: 6,
    minWidth: 30, textAlign: "right",
  },
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
    flexDirection: "row", alignItems: "center", gap: 6,
  },
  primaryBtnText: { color: "#000", fontWeight: "800" },
  coachNote: {
    backgroundColor: "#00000030", borderRadius: 6, padding: 10,
    borderLeftWidth: 3, borderLeftColor: "#f5b543", marginTop: 8,
  },
  coachNoteLabel: {
    color: "#f5b543", fontSize: 9, letterSpacing: 1, fontWeight: "800",
  },
  coachNoteText: { color: theme.color.textHi, fontSize: 12, marginTop: 3 },
  editErrorBanner: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "#3a1414", borderColor: "#ff6666", borderWidth: 1,
    padding: 8, margin: 12, marginBottom: 0, borderRadius: 6,
  },
  editErrorText: { color: "#ff6666", fontSize: 11, flex: 1 },
});


/* ---- Iter 117 — Flight Support Override Sheet -------------------------- */

function FlightSupportOverrideSheet({
  target, clientId, onClose, onDone,
}: {
  target: { date: string; item: any } | null;
  clientId: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const [protocols, setProtocols] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  React.useEffect(() => {
    if (!target) return;
    api<any>(`/v2/coach/protocols/flight-support?role=pilot`)
      .then((r) => setProtocols(r?.protocols || []))
      .catch(() => setProtocols([]));
  }, [target]);

  if (!target) return null;

  const call = async (payload: any) => {
    setBusy(true); setErr(null);
    try {
      await api(`/v2/coach/clients/${clientId}/flight-support/override`, {
        method: "POST", body: payload,
      });
      onDone();
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const removeOverride = async () => {
    setBusy(true); setErr(null);
    try {
      await api(`/v2/coach/clients/${clientId}/flight-support/override/remove`, {
        method: "POST",
        body: { date: target.date, protocol_key: target.item.protocol_key },
      });
      onDone();
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const currentKey = target.item.protocol_key;

  return (
    <Modal transparent visible onRequestClose={onClose} animationType="fade">
      <Pressable style={styles.drawerBackdrop} onPress={onClose}>
        <Pressable style={styles.drawer} onPress={(e) => e.stopPropagation()}>
          <View style={styles.drawerHeader}>
            <Text style={styles.drawerTitle}>Flight Support · {target.date}</Text>
            <Pressable onPress={onClose} testID="fs-sheet-close">
              <Ionicons name="close" size={24} color={theme.color.textDim} />
            </Pressable>
          </View>
          <ScrollView style={{ padding: 16 }}>
            <Text style={styles.sectionTitle}>CURRENT</Text>
            <View style={styles.planCard}>
              <View style={{ flex: 1 }}>
                <Text style={styles.planTitle}>{target.item.title}</Text>
                <Text style={styles.planMeta}>{target.item.duration_min}m · {target.item.family}</Text>
              </View>
            </View>
            {err ? (
              <View style={styles.editErrorBanner}>
                <Text style={styles.editErrorText}>{err}</Text>
              </View>
            ) : null}

            <Text style={[styles.sectionTitle, { marginTop: 18 }]}>REPLACE WITH</Text>
            {protocols.filter((p) => p.key !== currentKey).map((p) => (
              <Pressable
                key={p.key}
                disabled={busy || target.item.is_bundle}
                style={[styles.planCard, { opacity: busy ? 0.4 : 1 }]}
                onPress={() => call({
                  date: target.date, action: "replace",
                  protocol_key: currentKey, replace_key: p.key,
                })}
                testID={`fs-replace-${p.key}`}
              >
                <View style={{ flex: 1 }}>
                  <Text style={styles.planTitle}>{p.title}</Text>
                  <Text style={styles.planMeta}>{p.duration_min}m · {p.family}</Text>
                </View>
                <Ionicons name="chevron-forward" size={14} color={theme.color.textDim} />
              </Pressable>
            ))}

            <Text style={[styles.sectionTitle, { marginTop: 18 }]}>ACTIONS</Text>
            <Pressable
              disabled={busy}
              style={[styles.primaryBtn, { backgroundColor: "#f57c43", alignSelf: "stretch", justifyContent: "center", marginTop: 8 }]}
              onPress={() => call({
                date: target.date, action: "disable",
                protocol_key: currentKey,
                reason: "Coach disabled",
              })}
              testID="fs-disable-one"
            >
              <Ionicons name="ban" size={14} color="#000" />
              <Text style={styles.primaryBtnText}>DISABLE THIS INTERVENTION</Text>
            </Pressable>
            <Pressable
              disabled={busy}
              style={[styles.primaryBtn, { backgroundColor: "#ff6b6b", alignSelf: "stretch", justifyContent: "center", marginTop: 8 }]}
              onPress={() => call({ date: target.date, action: "disable_day" })}
              testID="fs-disable-day"
            >
              <Ionicons name="calendar-outline" size={14} color="#000" />
              <Text style={styles.primaryBtnText}>DISABLE ALL SUPPORT FOR THIS DAY</Text>
            </Pressable>
            <Pressable
              disabled={busy}
              style={[styles.primaryBtn, { backgroundColor: "#3a3a3a", alignSelf: "stretch", justifyContent: "center", marginTop: 8 }]}
              onPress={removeOverride}
              testID="fs-remove-override"
            >
              <Ionicons name="refresh" size={14} color="#fff" />
              <Text style={[styles.primaryBtnText, { color: "#fff" }]}>RESTORE ORIGINAL</Text>
            </Pressable>
          </ScrollView>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
