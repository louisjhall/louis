/**
 * CrewFit V2 Engine V2 — Coach Draft Review + Publish
 * ======================================================
 *
 * Route: /(coach)/engine-v2-draft/[cid]
 *
 * Single-screen coach workflow:
 *   1. Draft header — goal, phase, planning window, config status badge
 *   2. Exceptions tray — resolvable list with per-exception actions
 *   3. Draft calendar — placements grouped by week (KEY/IMPORTANT badges)
 *   4. Draft vs Live diff (collapsible)
 *   5. Publish button — gated by validation + goal-config + exceptions
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

// ---------- Types ----------
type Placement = {
  exposure_id: string;
  objective_id: string;
  kind: string;
  date: string;
  priority: string;
  exposure_number: number;
  intensity_class: string;
  target_duration_min: number;
  intensity_target: string;
  key: boolean;
};

type ExceptionItem = {
  id: string;
  category: string;
  priority: string;
  kind?: string;
  reason_code?: string;
  human_reason?: string;
  candidate_hints?: string[];
  actions: string[];
  resolved: boolean;
  resolution?: {
    action: string;
    reason?: string;
    coach_id?: string;
    at?: string;
    details?: any;
  };
};

type GoalConfigStatus = {
  status: "COMPLETE" | "PARTIAL" | "MISSING";
  warnings: string[];
  notes?: string | null;
  goal_key?: string;
};

// ---------- Helpers ----------
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
function fmtDate(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  return `${WEEKDAYS[(d.getDay() + 6) % 7]} ${d.getDate()} ${d.toLocaleString("en-US", { month: "short" })}`;
}
function isoWeek(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  const first = new Date(d.getFullYear(), 0, 4);
  const diff = (d.getTime() - first.getTime()) / 86400000;
  const wk = Math.ceil((diff + first.getDay() + 1) / 7);
  return `${d.getFullYear()}-W${String(wk).padStart(2, "0")}`;
}
const PRIORITY_COLOURS: Record<string, string> = {
  KEY: "#F0A800",
  IMPORTANT: "#3B82F6",
  SUPPORTING: "#6B7280",
  OPTIONAL: "#9CA3AF",
  UNKNOWN: "#9CA3AF",
};

// ---------- Screen ----------
export default function EngineV2DraftScreen() {
  const { cid } = useLocalSearchParams<{ cid: string }>();
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<any>(null);
  const [exceptions, setExceptions] = useState<ExceptionItem[]>([]);
  const [configStatus, setConfigStatus] = useState<GoalConfigStatus | null>(null);
  const [compare, setCompare] = useState<any>(null);
  const [showCompare, setShowCompare] = useState(false);
  const [showPublishModal, setShowPublishModal] = useState(false);
  const [ackPartial, setAckPartial] = useState(false);
  const [overrideReason, setOverrideReason] = useState("");
  const [coachNote, setCoachNote] = useState("");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [resolveOpenFor, setResolveOpenFor] = useState<ExceptionItem | null>(null);
  const [resolveReason, setResolveReason] = useState("");

  const loadAll = useCallback(async () => {
    if (!cid) return;
    setLoading(true);
    setErrorMsg(null);
    try {
      // First check if there's an active draft — if not, we render an
      // empty state rather than trying to load exceptions/compare (both
      // would return 404).
      const state = await api(`/v2/coach/clients/${cid}/engine-v2/state`);
      if (!state.has_active_draft) {
        setDraft(null);
        setExceptions([]);
        setConfigStatus(null);
        setCompare({ has_live: state.has_active_live });
        setErrorMsg(null);
        (window as any).__v2State = state;
        return;
      }
      const [d, e, c] = await Promise.all([
        api(`/v2/coach/clients/${cid}/engine-v2/draft`),
        api(`/v2/coach/clients/${cid}/engine-v2/exceptions`),
        api(`/v2/coach/clients/${cid}/engine-v2/compare`),
      ]);
      setDraft(d);
      setExceptions(e.exceptions || []);
      setConfigStatus(e.goal_config_status);
      setCompare(c);
    } catch (err: any) {
      setErrorMsg(err?.message || String(err));
    } finally {
      setLoading(false);
    }
  }, [cid]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const placementsByWeek = useMemo(() => {
    if (!draft?.placements) return {} as Record<string, Placement[]>;
    const map: Record<string, Placement[]> = {};
    for (const p of draft.placements as Placement[]) {
      const wk = isoWeek(p.date);
      map[wk] = map[wk] || [];
      map[wk].push(p);
    }
    for (const wk of Object.keys(map)) {
      map[wk].sort((a, b) => a.date.localeCompare(b.date));
    }
    return map;
  }, [draft]);

  const validationOk = draft?.programme_validation?.ok === true;
  const unresolvedBlockers = exceptions.filter(
    (e) =>
      !e.resolved &&
      (e.priority === "KEY" || e.priority === "IMPORTANT") &&
      (e.category === "unfilled_objective" ||
        e.category === "validator_error" ||
        e.category === "dna_gap")
  );
  const canPublish =
    validationOk &&
    unresolvedBlockers.length === 0 &&
    configStatus?.status !== "MISSING" &&
    (configStatus?.status === "COMPLETE" || ackPartial);

  const resolveException = async (action: string) => {
    if (!resolveOpenFor) return;
    setBusy(true);
    try {
      await api(
        `/v2/coach/clients/${cid}/engine-v2/exceptions/${resolveOpenFor.id}/resolve`,
        { method: "POST", body: { action, reason: resolveReason || undefined } }
      );
      setResolveOpenFor(null);
      setResolveReason("");
      await loadAll();
    } catch (err: any) {
      setErrorMsg(err?.message || String(err));
    } finally {
      setBusy(false);
    }
  };

  const doPublish = async () => {
    if (!draft?.id) return;
    setBusy(true);
    setErrorMsg(null);
    try {
      const res = await api(`/v2/coach/clients/${cid}/engine-v2/publish`, {
        method: "POST",
        body: {
          draft_id: draft.id,
          ack_partial_config: ackPartial,
          override_reason: overrideReason || undefined,
          coach_note: coachNote || undefined,
        },
      });
      setShowPublishModal(false);
      setAckPartial(false);
      setOverrideReason("");
      setCoachNote("");
      alert(`Published. Live ID: ${res.live_id?.slice(0, 8)}`);
      await loadAll();
    } catch (err: any) {
      setErrorMsg(err?.detail?.message || err?.message || String(err));
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.container}>
        <ActivityIndicator style={{ marginTop: 60 }} color={theme.color.brand} />
      </SafeAreaView>
    );
  }

  if (!draft) {
    const state = (typeof window !== "undefined" && (window as any).__v2State) || {};
    return (
      <SafeAreaView style={styles.container} edges={["top"]}>
        <Stack.Screen options={{ title: "Engine V2 Draft" }} />
        <ScrollView contentContainerStyle={{ padding: 16 }}>
          <Text style={styles.title}>Engine V2 Draft</Text>
          <View style={styles.warningBox}>
            <Text style={styles.warningTitle}>No active Draft</Text>
            <Text style={styles.warningItem}>
              {state.has_roster
                ? "A roster is uploaded but no active Draft has been generated yet. Run Engine V2 kickoff to create one."
                : "No roster has been uploaded for this client. Upload the client's roster in Roster + Plan to create the next Draft."}
            </Text>
          </View>
          {state.has_active_live ? (
            <View style={[styles.warningBox, { backgroundColor: "#003A2A" }]}>
              <Text style={[styles.warningTitle, { color: "#A7F3D0" }]}>
                Current published Live plan is preserved
              </Text>
              <Text style={[styles.warningItem, { color: "#A7F3D0" }]}>
                Live ID: {String(state.active_live_id || "").slice(0, 8)} · activated{" "}
                {String(state.active_live_activated_at || "").slice(0, 10)}
              </Text>
              <Text style={[styles.warningItem, { color: "#A7F3D0" }]}>
                The client continues to receive this Live programme until you
                publish a replacement.
              </Text>
            </View>
          ) : null}
          {errorMsg ? <Text style={styles.err}>{errorMsg}</Text> : null}
          <Pressable
            style={[styles.toggleBtn, { marginTop: 20 }]}
            onPress={() => router.back()}
          >
            <Text style={styles.toggleBtnLabel}>← Back</Text>
          </Pressable>
        </ScrollView>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={["top"]}>
      <Stack.Screen options={{ title: "Engine V2 Draft" }} />
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 120 }}>
        {/* Header */}
        <Text style={styles.title}>Engine V2 Draft</Text>
        <View style={styles.row}>
          <ConfigBadge status={configStatus?.status || "PARTIAL"} />
          <StatusBadge draftStatus={draft.status} />
        </View>
        <Text style={styles.metaLine}>
          Goal: <Text style={styles.meta}>{draft.effective_context?.goal_key || "-"}</Text>
          {"   "}
          Phase: <Text style={styles.meta}>{draft.effective_context?.current_phase || "-"}</Text>
        </Text>
        <Text style={styles.metaLine}>
          Window: {draft.planning_window?.start} → {draft.planning_window?.end}
          {"   "}({draft.planning_window?.weeks} weeks)
        </Text>
        <Text style={styles.metaLine}>
          Placements: {draft.placements?.length || 0} / required{" "}
          {draft.demand?.required_exposures?.length || 0}
          {"   "}Unfilled: {draft.unfilled?.length || 0}
        </Text>

        {configStatus?.warnings?.length ? (
          <View style={styles.warningBox}>
            <Text style={styles.warningTitle}>Configuration notes</Text>
            {configStatus.warnings.map((w, i) => (
              <Text key={i} style={styles.warningItem}>• {w}</Text>
            ))}
          </View>
        ) : null}

        {/* Exceptions */}
        <SectionHeader
          title={`Exceptions (${unresolvedBlockers.length} blocking / ${exceptions.length} total)`}
        />
        {exceptions.length === 0 ? (
          <Text style={styles.muted}>No exceptions raised. Programme is ready.</Text>
        ) : (
          exceptions.map((e) => (
            <ExceptionCard
              key={e.id}
              e={e}
              onOpen={() => {
                setResolveOpenFor(e);
                setResolveReason("");
              }}
            />
          ))
        )}

        {/* Draft calendar */}
        <SectionHeader title="Draft Calendar" />
        {Object.keys(placementsByWeek)
          .sort()
          .map((wk) => (
            <View key={wk} style={styles.weekBlock}>
              <Text style={styles.weekLabel}>{wk}</Text>
              {placementsByWeek[wk].map((p) => (
                <PlacementRow key={`${p.exposure_id}-${p.date}`} p={p} />
              ))}
            </View>
          ))}

        {/* Compare Draft vs Live */}
        <SectionHeader
          title={`Draft vs Live${compare?.has_live ? "" : " (no Live yet)"}`}
        />
        <Pressable
          style={styles.toggleBtn}
          onPress={() => setShowCompare((v) => !v)}
        >
          <Text style={styles.toggleBtnLabel}>
            {showCompare ? "Hide diff" : "Show diff"}
          </Text>
        </Pressable>
        {showCompare && compare ? (
          <CompareBlock compare={compare} />
        ) : null}

        {/* Publish */}
        <SectionHeader title="Publish" />
        <View style={styles.publishBox}>
          <Text style={styles.publishRow}>
            Programme validation: {validationOk ? "✅ pass" : "❌ needs review"}
          </Text>
          <Text style={styles.publishRow}>
            Blocking exceptions: {unresolvedBlockers.length}
          </Text>
          <Text style={styles.publishRow}>
            Goal config: {configStatus?.status}
          </Text>
          {configStatus?.status === "PARTIAL" ? (
            <View style={styles.ackRow}>
              <Switch
                value={ackPartial}
                onValueChange={setAckPartial}
                testID="ack-partial-switch"
              />
              <Text style={styles.ackLabel}>
                I acknowledge that this goal's Engine V2 configuration is still
                being validated and I have reviewed this programme before publishing.
              </Text>
            </View>
          ) : null}
          <Pressable
            style={[styles.publishBtn, !canPublish && styles.publishBtnDisabled]}
            disabled={!canPublish || busy}
            onPress={() => setShowPublishModal(true)}
            testID="publish-btn"
          >
            <Text style={styles.publishBtnLabel}>
              {busy ? "Working…" : canPublish ? "Publish to Live" : "Cannot publish yet"}
            </Text>
          </Pressable>
        </View>

        {errorMsg ? <Text style={styles.err}>{errorMsg}</Text> : null}
      </ScrollView>

      {/* Resolve modal */}
      <Modal visible={!!resolveOpenFor} transparent animationType="fade">
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            {resolveOpenFor && (
              <>
                <Text style={styles.modalTitle}>
                  {resolveOpenFor.kind} — {resolveOpenFor.priority}
                </Text>
                <Text style={styles.modalBody}>{resolveOpenFor.human_reason}</Text>
                {resolveOpenFor.candidate_hints?.length ? (
                  <View style={{ marginTop: 8 }}>
                    <Text style={styles.hintTitle}>Rejected candidates:</Text>
                    {resolveOpenFor.candidate_hints.slice(0, 5).map((h, i) => (
                      <Text key={i} style={styles.hint}>• {h}</Text>
                    ))}
                  </View>
                ) : null}
                {["carry_forward", "modify_objective", "override_with_reason"].some(
                  (a) => resolveOpenFor.actions.includes(a)
                ) ? (
                  <TextInput
                    value={resolveReason}
                    onChangeText={setResolveReason}
                    placeholder="Reason (required for override)"
                    style={styles.input}
                    multiline
                  />
                ) : null}
                <View style={{ height: 8 }} />
                {resolveOpenFor.actions.map((a) => (
                  <Pressable
                    key={a}
                    style={styles.modalAction}
                    onPress={() => resolveException(a)}
                    disabled={busy}
                  >
                    <Text style={styles.modalActionLabel}>{a.replace(/_/g, " ")}</Text>
                  </Pressable>
                ))}
                <Pressable
                  style={styles.modalCancel}
                  onPress={() => setResolveOpenFor(null)}
                >
                  <Text style={styles.modalCancelLabel}>Cancel</Text>
                </Pressable>
              </>
            )}
          </View>
        </View>
      </Modal>

      {/* Publish modal */}
      <Modal visible={showPublishModal} transparent animationType="fade">
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Confirm Publish</Text>
            <Text style={styles.modalBody}>
              This will replace the client's current Live plan with this Draft.
              Previous Live remains in history.
            </Text>
            {configStatus?.status === "PARTIAL" ? (
              <Text style={styles.warningItem}>
                ⚠ Goal config: PARTIAL — extra acknowledgement required.
              </Text>
            ) : null}
            <TextInput
              value={coachNote}
              onChangeText={setCoachNote}
              placeholder="Optional coach note"
              style={styles.input}
              multiline
            />
            <Pressable
              style={styles.publishBtn}
              onPress={doPublish}
              disabled={busy}
              testID="confirm-publish-btn"
            >
              <Text style={styles.publishBtnLabel}>
                {busy ? "Publishing…" : "Confirm Publish"}
              </Text>
            </Pressable>
            <Pressable
              style={styles.modalCancel}
              onPress={() => setShowPublishModal(false)}
            >
              <Text style={styles.modalCancelLabel}>Cancel</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

// ---------- Subcomponents ----------
function SectionHeader({ title }: { title: string }) {
  return <Text style={styles.sectionHeader}>{title}</Text>;
}

function ConfigBadge({ status }: { status: string }) {
  const bg =
    status === "COMPLETE" ? "#10B981" : status === "PARTIAL" ? "#F59E0B" : "#EF4444";
  return (
    <View style={[styles.badge, { backgroundColor: bg }]}>
      <Text style={styles.badgeText}>Config: {status}</Text>
    </View>
  );
}
function StatusBadge({ draftStatus }: { draftStatus?: string }) {
  const bg = draftStatus === "ready_for_review" ? "#10B981" : draftStatus === "published" ? "#3B82F6" : "#F59E0B";
  return (
    <View style={[styles.badge, { backgroundColor: bg, marginLeft: 8 }]}>
      <Text style={styles.badgeText}>Status: {draftStatus || "-"}</Text>
    </View>
  );
}

function PlacementRow({ p }: { p: Placement }) {
  return (
    <View style={styles.placementRow}>
      <View
        style={[
          styles.priorityDot,
          { backgroundColor: PRIORITY_COLOURS[p.priority] || "#999" },
        ]}
      />
      <View style={{ flex: 1 }}>
        <Text style={styles.placementLine}>
          {fmtDate(p.date)}   {p.kind}   #{p.exposure_number}
          {p.key ? "  ★" : ""}
        </Text>
        <Text style={styles.placementSub}>
          {p.target_duration_min} min · {p.intensity_target}
        </Text>
      </View>
    </View>
  );
}

function ExceptionCard({
  e,
  onOpen,
}: {
  e: ExceptionItem;
  onOpen: () => void;
}) {
  return (
    <Pressable
      onPress={onOpen}
      style={[
        styles.excCard,
        e.resolved && { borderColor: "#10B981" },
      ]}
      testID={`exception-${e.id}`}
    >
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
        <Text style={[styles.excTitle, { color: PRIORITY_COLOURS[e.priority] || "#333" }]}>
          {e.priority} · {e.kind || e.category}
        </Text>
        <Text style={styles.excStatus}>{e.resolved ? "✓ resolved" : "unresolved"}</Text>
      </View>
      <Text style={styles.excBody} numberOfLines={3}>
        {e.human_reason}
      </Text>
      {e.resolved && e.resolution ? (
        <Text style={styles.excResolution}>
          Action: {e.resolution.action}{" · "}
          {e.resolution.at?.slice(0, 10)}
          {e.resolution.reason ? ` · ${e.resolution.reason}` : ""}
        </Text>
      ) : null}
    </Pressable>
  );
}

function CompareBlock({ compare }: { compare: any }) {
  if (!compare?.has_live) {
    return <Text style={styles.muted}>No published Live plan yet. All draft placements count as "added".</Text>;
  }
  const s = compare.summary || {};
  return (
    <View>
      <Text style={styles.metaLine}>
        Summary — added {s.added}, removed {s.removed}, moved {s.moved}, changed {s.changed}
      </Text>
      {["added", "removed", "moved", "changed"].map((k) => {
        const arr = compare[k] || [];
        if (!arr.length) return null;
        return (
          <View key={k} style={styles.compareGroup}>
            <Text style={styles.compareGroupTitle}>{k.toUpperCase()} ({arr.length})</Text>
            {arr.slice(0, 20).map((row: any, i: number) => (
              <Text key={i} style={styles.compareRow}>
                {row.date || `${row.from_date}→${row.to_date}`}   {row.kind}
                {row.changed_fields?.length ? `   (${row.changed_fields.join(", ")})` : ""}
              </Text>
            ))}
          </View>
        );
      })}
    </View>
  );
}

// ---------- Styles ----------
const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0B0B0F" },
  title: { color: "#fff", fontSize: 22, fontWeight: "700" },
  row: { flexDirection: "row", marginTop: 8, marginBottom: 8, flexWrap: "wrap" },
  meta: { color: "#fff", fontWeight: "600" },
  metaLine: { color: "#B6B6C0", marginTop: 4 },
  muted: { color: "#8A8A94", marginTop: 12 },
  err: { color: "#EF4444", marginTop: 12 },

  badge: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999 },
  badgeText: { color: "#fff", fontSize: 12, fontWeight: "700" },

  sectionHeader: { color: "#fff", fontSize: 16, fontWeight: "700", marginTop: 24, marginBottom: 8 },

  warningBox: { backgroundColor: "#3A2A00", borderRadius: 8, padding: 10, marginTop: 10 },
  warningTitle: { color: "#FDE68A", fontWeight: "700", marginBottom: 4 },
  warningItem: { color: "#FDE68A", fontSize: 12, marginTop: 2 },

  weekBlock: { marginBottom: 12 },
  weekLabel: { color: "#F0A800", fontWeight: "700", marginBottom: 6 },
  placementRow: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#1A1A24",
    borderRadius: 8,
    padding: 10,
    marginBottom: 4,
  },
  priorityDot: { width: 10, height: 10, borderRadius: 5, marginRight: 10 },
  placementLine: { color: "#fff", fontWeight: "600" },
  placementSub: { color: "#8A8A94", fontSize: 12, marginTop: 2 },

  excCard: {
    backgroundColor: "#1A1A24",
    borderRadius: 10,
    padding: 12,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: "#333",
  },
  excTitle: { fontWeight: "700", marginBottom: 4 },
  excStatus: { color: "#8A8A94", fontSize: 12 },
  excBody: { color: "#D1D1D9", fontSize: 13 },
  excResolution: { color: "#10B981", fontSize: 12, marginTop: 6 },

  toggleBtn: { alignSelf: "flex-start", paddingHorizontal: 12, paddingVertical: 6, borderRadius: 6, backgroundColor: "#26263A" },
  toggleBtnLabel: { color: "#fff" },
  compareGroup: { marginTop: 8 },
  compareGroupTitle: { color: "#F0A800", fontWeight: "700" },
  compareRow: { color: "#D1D1D9", fontSize: 12, marginLeft: 8, marginTop: 2 },

  publishBox: { backgroundColor: "#1A1A24", padding: 12, borderRadius: 10 },
  publishRow: { color: "#D1D1D9", marginBottom: 4 },
  ackRow: { flexDirection: "row", alignItems: "flex-start", marginTop: 12, gap: 10 },
  ackLabel: { color: "#FDE68A", flex: 1, fontSize: 13 },
  publishBtn: { backgroundColor: "#10B981", padding: 12, borderRadius: 8, marginTop: 12, alignItems: "center" },
  publishBtnDisabled: { backgroundColor: "#333" },
  publishBtnLabel: { color: "#fff", fontWeight: "700" },

  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.7)", justifyContent: "center", padding: 16 },
  modalCard: { backgroundColor: "#1A1A24", borderRadius: 12, padding: 16, maxHeight: "80%" },
  modalTitle: { color: "#fff", fontSize: 18, fontWeight: "700", marginBottom: 8 },
  modalBody: { color: "#D1D1D9", marginBottom: 8 },
  hintTitle: { color: "#F0A800", fontWeight: "700", fontSize: 12 },
  hint: { color: "#B6B6C0", fontSize: 12 },
  input: { backgroundColor: "#0B0B0F", color: "#fff", padding: 10, borderRadius: 6, minHeight: 48, marginTop: 8 },
  modalAction: { backgroundColor: "#3B82F6", padding: 10, borderRadius: 6, marginTop: 6, alignItems: "center" },
  modalActionLabel: { color: "#fff", fontWeight: "600" },
  modalCancel: { padding: 10, alignItems: "center", marginTop: 8 },
  modalCancelLabel: { color: "#8A8A94" },
});
