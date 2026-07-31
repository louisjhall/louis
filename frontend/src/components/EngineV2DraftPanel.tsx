/**
 * EngineV2DraftPanel — compact V2 status + actions embedded in the client
 * workspace. Reuses `feature_v2_engine_v2_publish` endpoints; no engine
 * changes.
 *
 * Iter 128f — density pass. Renders as a single-line collapsible ribbon
 * that summarises Live + Draft state and blocking-exception count. Details
 * (config status, compare, exceptions, publish gate, rebuild) live in the
 * expanded body so they don't permanently consume vertical space.
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
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Props = { clientId: string; onPublished?: () => void };

export default function EngineV2DraftPanel({ clientId, onPublished }: Props) {
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [state, setState] = useState<any>(null);
  const [exc, setExc] = useState<any | null>(null);
  const [cmp, setCmp] = useState<any | null>(null);
  const [showExceptions, setShowExceptions] = useState(false);
  const [showCompare, setShowCompare] = useState(false);
  const [showPublish, setShowPublish] = useState(false);
  const [resolveOpen, setResolveOpen] = useState<any>(null);
  const [resolveReason, setResolveReason] = useState("");
  const [ackPartial, setAckPartial] = useState(false);
  const [coachNote, setCoachNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const load = useCallback(async () => {
    if (!clientId) return;
    setLoading(true); setErr(null);
    try {
      const s = await api(`/v2/coach/clients/${clientId}/engine-v2/state`);
      setState(s);
      if (s.has_active_draft) {
        const [e, c] = await Promise.all([
          api(`/v2/coach/clients/${clientId}/engine-v2/exceptions`).catch(() => null),
          api(`/v2/coach/clients/${clientId}/engine-v2/compare`).catch(() => null),
        ]);
        setExc(e); setCmp(c);
      } else {
        setExc(null); setCmp(null);
      }
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  const unresolvedBlockers = useMemo(() => {
    if (!exc?.exceptions) return 0;
    return (exc.exceptions as any[]).filter(
      (e) => !e.resolved &&
        (e.priority === "KEY" || e.priority === "IMPORTANT") &&
        (e.category === "unfilled_objective" || e.category === "validator_error" || e.category === "dna_gap")
    ).length;
  }, [exc]);

  // Publish is allowed when goal-config permits AND no KEY/IMPORTANT exception
  // is still unresolved. programme_validation.ok being false is fine as long
  // as every blocking exception has been resolved (matches backend semantics).
  const canPublish =
    unresolvedBlockers === 0 &&
    exc?.goal_config_status?.status !== "MISSING" &&
    (exc?.goal_config_status?.status === "COMPLETE" || ackPartial);

  const kickoff = async () => {
    setBusy(true); setErr(null);
    try {
      const res = await api(`/v2/coach/clients/${clientId}/engine-v2/kickoff`,
        { method: "POST", body: { planning_window_weeks: 4 } });
      // Iter 130i — kickoff can return 200 with {ok:false, code:'...'} when
      // DNA is missing / roster empty / engine flag off. Previously the UI
      // silently swallowed those responses and refreshed — user saw
      // "nothing happened". Surface the code + message so the coach can act.
      if (res && res.ok === false) {
        const codeLine = res.code ? `[${res.code}] ` : "";
        const msg = res.message || "Engine V2 kickoff returned ok:false";
        setErr(codeLine + msg);
        // Refresh state anyway so any partial changes propagate.
        await load();
        return;
      }
      await load();
    } catch (e: any) {
      setErr(e?.detail?.message || e?.message || String(e));
    }
    finally { setBusy(false); }
  };

  const resolveException = async (action: string) => {
    if (!resolveOpen) return;
    setBusy(true);
    try {
      await api(`/v2/coach/clients/${clientId}/engine-v2/exceptions/${resolveOpen.id}/resolve`,
        { method: "POST", body: { action, reason: resolveReason || undefined } });
      setResolveOpen(null); setResolveReason(""); await load();
    } catch (e: any) { setErr(e?.message || String(e)); }
    finally { setBusy(false); }
  };

  const doPublish = async () => {
    if (!exc?.draft_id) return;
    setBusy(true); setErr(null);
    try {
      const res = await api(`/v2/coach/clients/${clientId}/engine-v2/publish`, {
        method: "POST",
        body: { draft_id: exc.draft_id,
                ack_partial_config: ackPartial,
                coach_note: coachNote || undefined },
      });
      setShowPublish(false); setAckPartial(false); setCoachNote("");
      alert(`Published. Live ID: ${res.live_id?.slice(0, 8)}`);
      await load();
      onPublished?.();
    } catch (e: any) { setErr(e?.detail?.message || e?.message || String(e)); }
    finally { setBusy(false); }
  };

  if (loading) {
    return (
      <View style={styles.ribbonLoading}>
        <ActivityIndicator size="small" color={theme.color.brand} />
      </View>
    );
  }
  if (!state) return null;

  const cs = exc?.goal_config_status;

  // ---- Ribbon summary line (always compact) --------------------------------
  const hasLive = !!state.has_active_live;
  const hasDraft = !!state.has_active_draft;
  const hasRoster = !!state.has_roster;
  const totalPlaced = (exc?.counts?.total || 0);

  // Draft header pieces
  const liveMonth = fmtMonth(state?.active_live?.planning_window?.start || state?.roster_range?.start);

  return (
    <View style={styles.ribbonWrap} testID="engine-v2-ribbon">
      {/* Compact single-line ribbon */}
      <Pressable
        style={styles.ribbon}
        onPress={() => setExpanded((v) => !v)}
        testID="engine-v2-ribbon-toggle"
      >
        {/* Left: state summary */}
        <View style={styles.ribbonLeft}>
          {!hasRoster ? (
            <>
              <Ionicons name="cloud-upload-outline" size={13} color={theme.color.textDim} />
              <Text style={styles.stateDim}>NO ROSTER</Text>
              <Text style={styles.stateHint}>Upload a roster to enable programme generation.</Text>
            </>
          ) : hasLive && hasDraft ? (
            <>
              <Ionicons name="checkmark-circle" size={13} color="#61c982" />
              <Text style={styles.stateGreen}>LIVE</Text>
              {liveMonth ? <Text style={styles.stateHint}>· {liveMonth}</Text> : null}
              <Text style={styles.divider}>·</Text>
              <Ionicons name="alert-circle" size={13} color="#f5b543" />
              <Text style={styles.stateAmber}>NEW DRAFT</Text>
              {unresolvedBlockers > 0 ? (
                <Text style={styles.stateAmberSub}>· {unresolvedBlockers} NEED REVIEW</Text>
              ) : (
                <Text style={styles.stateGreenSub}>· READY TO PUBLISH</Text>
              )}
            </>
          ) : hasDraft ? (
            <>
              <Ionicons name="alert-circle" size={13} color="#f5b543" />
              <Text style={styles.stateAmber}>DRAFT</Text>
              {unresolvedBlockers > 0 ? (
                <Text style={styles.stateAmberSub}>· {unresolvedBlockers} NEED REVIEW</Text>
              ) : (
                <Text style={styles.stateGreenSub}>· READY TO PUBLISH</Text>
              )}
            </>
          ) : hasLive ? (
            <>
              <Ionicons name="checkmark-circle" size={13} color="#61c982" />
              <Text style={styles.stateGreen}>LIVE</Text>
              {liveMonth ? <Text style={styles.stateHint}>· {liveMonth}</Text> : null}
            </>
          ) : (
            <>
              <Ionicons name="calendar-outline" size={13} color={theme.color.textDim} />
              <Text style={styles.stateDim}>NO PLAN</Text>
              <Text style={styles.stateHint}>Ready to build a Draft against this roster.</Text>
            </>
          )}
        </View>

        {/* Right: compact quick-actions + chevron */}
        <View style={styles.ribbonRight}>
          {hasDraft && (
            <Pressable
              style={styles.miniBtn}
              onPress={(e) => { e.stopPropagation?.(); setShowCompare(true); }}
              testID="v2-compare"
            >
              <Text style={styles.miniBtnText}>Compare</Text>
            </Pressable>
          )}
          {hasDraft && unresolvedBlockers > 0 && (
            <Pressable
              style={[styles.miniBtn, styles.miniBtnAmber]}
              onPress={(e) => { e.stopPropagation?.(); setShowExceptions(true); }}
              testID="v2-review-issues"
            >
              <Text style={styles.miniBtnAmberText}>Review ({unresolvedBlockers})</Text>
            </Pressable>
          )}
          {hasDraft && unresolvedBlockers === 0 && cs?.status !== "MISSING" && (
            <Pressable
              style={[styles.miniBtn, canPublish ? styles.miniBtnGreen : styles.miniBtn]}
              onPress={(e) => { e.stopPropagation?.(); setShowPublish(true); }}
              testID="v2-publish"
            >
              <Text style={canPublish ? styles.miniBtnGreenText : styles.miniBtnText}>Publish</Text>
            </Pressable>
          )}
          {!hasDraft && hasRoster && (
            <Pressable
              style={[styles.miniBtn, styles.miniBtnBrand]}
              onPress={(e) => { e.stopPropagation?.(); kickoff(); }}
              disabled={busy}
              testID="v2-build-plan"
            >
              <Text style={styles.miniBtnBrandText}>{busy ? "…" : "Build plan"}</Text>
            </Pressable>
          )}
          <Ionicons name={expanded ? "chevron-up" : "chevron-down"} size={14} color={theme.color.textDim} />
        </View>
      </Pressable>

      {/* Expanded body */}
      {expanded && (
        <View style={styles.expandedBody}>
          {hasDraft ? (
            <>
              <View style={styles.detailRow}>
                <Text style={styles.detailLabel}>Config</Text>
                <Text style={styles.detailVal}>
                  {cs?.status === "COMPLETE" ? "✅ Complete"
                    : cs?.status === "PARTIAL" ? "⚠ Partial"
                    : "❌ Missing"}
                </Text>
              </View>
              <View style={styles.detailRow}>
                <Text style={styles.detailLabel}>Exceptions</Text>
                <Text style={styles.detailVal}>
                  {unresolvedBlockers > 0
                    ? `❌ ${unresolvedBlockers} blocking · ${totalPlaced} total`
                    : `✅ 0 blocking · ${totalPlaced} total`}
                </Text>
              </View>
              <View style={styles.detailRow}>
                <Text style={styles.detailLabel}>Compare vs Live</Text>
                <Text style={styles.detailVal}>
                  {(cmp?.summary?.added || 0)}+  {(cmp?.summary?.removed || 0)}−  {(cmp?.summary?.moved || 0)}↔  {(cmp?.summary?.changed || 0)}~
                </Text>
              </View>
              <View style={styles.expandActions}>
                <Pressable style={styles.actionBtn} onPress={() => setShowExceptions(true)}>
                  <Text style={styles.actionBtnText}>Review issues</Text>
                </Pressable>
                <Pressable style={styles.actionBtn} onPress={kickoff} disabled={busy} testID="v2-rebuild">
                  <Text style={styles.actionBtnText}>{busy ? "…" : "Rebuild draft"}</Text>
                </Pressable>
              </View>
              {err ? <Text style={styles.err}>{err}</Text> : null}
            </>
          ) : hasRoster ? (
            <>
              <Text style={styles.expandBody}>
                {hasLive
                  ? `Live plan ${String(state.active_live_id || "").slice(0, 8)} is active. Build a new Draft to propose changes.`
                  : "Ready to build a Draft against this roster."}
              </Text>
              <Pressable style={styles.actionBtn} onPress={kickoff} disabled={busy}>
                <Text style={styles.actionBtnText}>{busy ? "Building…" : "Build plan"}</Text>
              </Pressable>
              {err ? <Text style={styles.err}>{err}</Text> : null}
            </>
          ) : (
            <Text style={styles.expandBody}>Upload a roster to enable programme generation.</Text>
          )}
        </View>
      )}

      {/* Exceptions modal */}
      <Modal visible={showExceptions} transparent animationType="fade">
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Exceptions</Text>
            <ScrollView style={{ maxHeight: 380 }}>
              {(exc?.exceptions || []).map((e: any) => (
                <Pressable key={e.id} onPress={() => setResolveOpen(e)}
                           style={[styles.excRow, e.resolved && styles.excRowResolved]}>
                  <Text style={styles.excTitle}>{e.priority} · {e.kind || e.category}</Text>
                  <Text style={styles.excBody} numberOfLines={2}>{e.human_reason}</Text>
                  {e.resolved ? <Text style={styles.excResolved}>✓ resolved · {e.resolution?.action}</Text> : null}
                </Pressable>
              ))}
              {(exc?.exceptions || []).length === 0 ? (
                <Text style={styles.sub}>No exceptions.</Text>
              ) : null}
            </ScrollView>
            <Pressable style={styles.btnCancel} onPress={() => setShowExceptions(false)}>
              <Text style={styles.btnCancelLabel}>Close</Text>
            </Pressable>
          </View>
        </View>
      </Modal>

      {/* Resolve one exception */}
      <Modal visible={!!resolveOpen} transparent animationType="fade">
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            {resolveOpen && (
              <>
                <Text style={styles.modalTitle}>{resolveOpen.kind} · {resolveOpen.priority}</Text>
                <Text style={styles.modalBody}>{resolveOpen.human_reason}</Text>
                {resolveOpen.candidate_hints?.length ? (
                  <View style={{ marginTop: 8 }}>
                    <Text style={styles.subHi}>Rejected candidates</Text>
                    {resolveOpen.candidate_hints.slice(0, 5).map((h: string, i: number) => (
                      <Text key={i} style={styles.sub}>• {h}</Text>
                    ))}
                  </View>
                ) : null}
                {["carry_forward", "modify_objective", "override_with_reason"].some((a) =>
                  resolveOpen.actions.includes(a)) ? (
                  <TextInput value={resolveReason} onChangeText={setResolveReason}
                             placeholder="Reason (required for override)"
                             placeholderTextColor={theme.color.textMuted}
                             style={styles.input} multiline />
                ) : null}
                {(resolveOpen.actions || []).map((a: string) => (
                  <Pressable key={a} style={styles.btnAction} onPress={() => resolveException(a)}
                             disabled={busy}>
                    <Text style={styles.btnActionLabel}>{a.replace(/_/g, " ")}</Text>
                  </Pressable>
                ))}
                <Pressable style={styles.btnCancel} onPress={() => setResolveOpen(null)}>
                  <Text style={styles.btnCancelLabel}>Cancel</Text>
                </Pressable>
              </>
            )}
          </View>
        </View>
      </Modal>

      {/* Compare modal */}
      <Modal visible={showCompare} transparent animationType="fade">
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Draft vs Live</Text>
            {cmp?.has_live === false ? (
              <Text style={styles.sub}>No published Live yet — every placement is new.</Text>
            ) : cmp ? (
              <ScrollView style={{ maxHeight: 380 }}>
                {(["added", "removed", "moved", "changed"] as const).map((k) => {
                  const arr = (cmp as any)[k] || [];
                  if (!arr.length) return null;
                  return (
                    <View key={k} style={{ marginTop: 8 }}>
                      <Text style={styles.subHi}>{k.toUpperCase()} ({arr.length})</Text>
                      {arr.slice(0, 20).map((row: any, i: number) => (
                        <Text key={i} style={styles.sub}>
                          {row.date || `${row.from_date}→${row.to_date}`}   {row.kind}
                          {row.changed_fields?.length ? `  (${row.changed_fields.join(", ")})` : ""}
                        </Text>
                      ))}
                    </View>
                  );
                })}
              </ScrollView>
            ) : null}
            <Pressable style={styles.btnCancel} onPress={() => setShowCompare(false)}>
              <Text style={styles.btnCancelLabel}>Close</Text>
            </Pressable>
          </View>
        </View>
      </Modal>

      {/* Publish modal */}
      <Modal visible={showPublish} transparent animationType="fade">
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Confirm Publish</Text>
            <Text style={styles.modalBody}>
              This will replace the current Live plan for the client. Previous Live is preserved in history.
            </Text>
            {cs?.status === "PARTIAL" ? (
              <View style={styles.ackRow}>
                <Switch value={ackPartial} onValueChange={setAckPartial} />
                <Text style={styles.ackLabel}>
                  {"I acknowledge this goal's programme configuration is still being validated and I have reviewed this programme."}
                </Text>
              </View>
            ) : null}
            <TextInput value={coachNote} onChangeText={setCoachNote}
                       placeholder="Optional coach note"
                       placeholderTextColor={theme.color.textMuted}
                       style={styles.input} multiline />
            <Pressable style={styles.btnAction} disabled={busy} onPress={doPublish}
                       testID="v2-confirm-publish">
              <Text style={styles.btnActionLabel}>{busy ? "Publishing…" : "Confirm Publish"}</Text>
            </Pressable>
            <Pressable style={styles.btnCancel} onPress={() => setShowPublish(false)}>
              <Text style={styles.btnCancelLabel}>Cancel</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </View>
  );
}

function fmtMonth(iso?: string): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleString("default", { month: "short", year: "numeric" });
  } catch { return ""; }
}

const styles = StyleSheet.create({
  ribbonWrap: {
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
    backgroundColor: theme.color.surface2,
  },
  ribbonLoading: {
    paddingVertical: 6, paddingHorizontal: 12,
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
    backgroundColor: theme.color.surface2, alignItems: "flex-start",
  },
  ribbon: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: 12, paddingVertical: 7, gap: 8,
  },
  ribbonLeft: {
    flex: 1, flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap",
  },
  ribbonRight: {
    flexDirection: "row", alignItems: "center", gap: 6,
  },
  stateDim:    { color: theme.color.textDim, fontSize: 10.5, fontWeight: "800", letterSpacing: 1.3 },
  stateGreen:  { color: "#61c982",          fontSize: 10.5, fontWeight: "800", letterSpacing: 1.3 },
  stateAmber:  { color: "#f5b543",          fontSize: 10.5, fontWeight: "800", letterSpacing: 1.3 },
  stateHint:   { color: theme.color.textDim, fontSize: 11 },
  stateAmberSub: { color: "#f5b543", fontSize: 10.5, fontWeight: "700", letterSpacing: 1 },
  stateGreenSub: { color: "#61c982", fontSize: 10.5, fontWeight: "700", letterSpacing: 1 },
  divider:     { color: theme.color.border, fontSize: 12, marginHorizontal: 2 },

  miniBtn: {
    paddingHorizontal: 10, paddingVertical: 4, borderRadius: 6,
    borderWidth: 1, borderColor: theme.color.border, backgroundColor: "#00000030",
  },
  miniBtnText: { color: theme.color.textHi, fontSize: 11, fontWeight: "700" },
  miniBtnAmber: { borderColor: "rgba(245,181,67,0.55)", backgroundColor: "rgba(245,181,67,0.14)" },
  miniBtnAmberText: { color: "#f5b543", fontSize: 11, fontWeight: "800" },
  miniBtnGreen: { borderColor: "rgba(97,201,130,0.55)", backgroundColor: "rgba(97,201,130,0.14)" },
  miniBtnGreenText: { color: "#61c982", fontSize: 11, fontWeight: "800" },
  miniBtnBrand: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  miniBtnBrandText: { color: "#000", fontSize: 11, fontWeight: "800" },

  expandedBody: {
    paddingHorizontal: 12, paddingBottom: 10, paddingTop: 2,
    gap: 6, backgroundColor: theme.color.surface2,
  },
  detailRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingVertical: 3,
  },
  detailLabel: { color: theme.color.textDim, fontSize: 11, letterSpacing: 0.5, fontWeight: "700", width: 130 },
  detailVal:   { color: theme.color.textHi, fontSize: 12, flex: 1 },
  expandActions: {
    flexDirection: "row", gap: 8, marginTop: 6, flexWrap: "wrap",
  },
  actionBtn: {
    paddingHorizontal: 12, paddingVertical: 6, borderRadius: 6,
    borderWidth: 1, borderColor: theme.color.border, backgroundColor: "#00000030",
  },
  actionBtnText: { color: theme.color.textHi, fontSize: 12, fontWeight: "700" },
  expandBody: { color: theme.color.textDim, fontSize: 12, marginBottom: 4 },
  err: { color: theme.color.red, fontSize: 12, marginTop: 6 },

  /* Modal shared */
  sub: { color: theme.color.textMuted, fontSize: 12, marginTop: 4 },
  subHi: { color: theme.color.amber, fontWeight: "700", fontSize: 12, marginBottom: 2 },
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.7)", justifyContent: "center", padding: 16 },
  modalCard: { backgroundColor: theme.color.surface2, borderRadius: 12, padding: 16, maxHeight: "82%" },
  modalTitle: { color: theme.color.textHi, fontSize: 17, fontWeight: "700", marginBottom: 8 },
  modalBody: { color: theme.color.textMuted, marginBottom: 8 },
  input: { backgroundColor: theme.color.surface, color: theme.color.textHi, padding: 10, borderRadius: 6, minHeight: 44, marginTop: 8 },
  ackRow: { flexDirection: "row", gap: 10, alignItems: "flex-start", marginTop: 10 },
  ackLabel: { color: theme.color.amber, fontSize: 12, flex: 1 },
  btnAction: { backgroundColor: theme.color.brand, paddingVertical: 10, borderRadius: 6, marginTop: 8, alignItems: "center" },
  btnActionLabel: { color: "#fff", fontWeight: "600" },
  btnCancel: { padding: 10, alignItems: "center", marginTop: 6 },
  btnCancelLabel: { color: theme.color.textMuted },
  excRow: { padding: 10, borderRadius: 8, backgroundColor: theme.color.surface3, marginBottom: 6, borderWidth: 1, borderColor: theme.color.border },
  excRowResolved: { borderColor: theme.color.green },
  excTitle: { color: theme.color.textHi, fontWeight: "600", fontSize: 13 },
  excBody: { color: theme.color.textMuted, fontSize: 12, marginTop: 2 },
  excResolved: { color: theme.color.green, fontSize: 11, marginTop: 4 },
});
