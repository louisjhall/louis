/**
 * EngineV2DraftPanel — compact V2 status + actions embedded in the client
 * workspace. Reuses `feature_v2_engine_v2_publish` endpoints; no engine
 * changes.
 *
 * Renders inside the workspace Plan tab for engine_v2-flagged clients.
 * Opens exceptions and publish as bottom-sheet-style modals so the coach
 * never leaves the client workspace.
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
      await api(`/v2/coach/clients/${clientId}/engine-v2/kickoff`,
        { method: "POST", body: { planning_window_weeks: 4 } });
      await load();
    } catch (e: any) { setErr(e?.message || String(e)); }
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
      <View style={styles.panel}>
        <ActivityIndicator color={theme.color.brand} />
      </View>
    );
  }
  if (!state) return null;

  // Empty states
  if (!state.has_roster) {
    return (
      <View style={styles.panel}>
        <Text style={styles.title}>Engine V2 · Roster required</Text>
        <Text style={styles.sub}>Upload a roster to enable programme generation.</Text>
      </View>
    );
  }
  if (!state.has_active_draft) {
    return (
      <View style={styles.panel}>
        <Text style={styles.title}>Engine V2 · No Draft</Text>
        {state.has_active_live ? (
          <Text style={styles.sub}>
            Live plan {String(state.active_live_id || "").slice(0, 8)} is active. Build a new Draft to propose changes.
          </Text>
        ) : (
          <Text style={styles.sub}>Ready to build a Draft against this roster.</Text>
        )}
        <Pressable style={styles.btnPrimary} onPress={kickoff} disabled={busy}
                   testID="v2-build-plan">
          <Text style={styles.btnPrimaryLabel}>{busy ? "Building…" : "Build plan"}</Text>
        </Pressable>
        {err ? <Text style={styles.err}>{err}</Text> : null}
      </View>
    );
  }

  // Draft exists
  const cs = exc?.goal_config_status;
  const ok = exc?.programme_validation_ok;
  const totalPlaced = (exc?.counts?.total || 0);
  return (
    <View style={styles.panel}>
      <View style={styles.headerRow}>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>Engine V2 Draft</Text>
          <Text style={styles.sub}>
            {cs?.status === "COMPLETE" ? "✅ Config Complete" : cs?.status === "PARTIAL" ? "⚠ Config Partial" : "❌ Config Missing"}
            {"  ·  "}
            {unresolvedBlockers === 0
              ? "✅ Ready to publish"
              : `❌ ${unresolvedBlockers} to review`}
          </Text>
        </View>
      </View>
      <View style={styles.chipRow}>
        <Pressable style={styles.chip} onPress={() => setShowExceptions(true)}
                   testID="v2-review-issues">
          <Text style={styles.chipLabel}>
            {unresolvedBlockers > 0 ? `${unresolvedBlockers} Needs Review` : `Exceptions (${totalPlaced})`}
          </Text>
        </Pressable>
        <Pressable style={styles.chip} onPress={() => setShowCompare(true)}
                   testID="v2-compare">
          <Text style={styles.chipLabel}>
            Compare Live · {(cmp?.summary?.added || 0)}+ {(cmp?.summary?.removed || 0)}− {(cmp?.summary?.moved || 0)}↔ {(cmp?.summary?.changed || 0)}~
          </Text>
        </Pressable>
        <Pressable
          style={[styles.chip, canPublish ? styles.chipOk : styles.chipDisabled]}
          disabled={!canPublish || busy}
          onPress={() => setShowPublish(true)}
          testID="v2-publish"
        >
          <Text style={styles.chipLabel}>{canPublish ? "Publish" : "Cannot publish"}</Text>
        </Pressable>
      </View>
      <Pressable style={styles.rebuild} onPress={kickoff} disabled={busy}
                 testID="v2-rebuild">
        <Text style={styles.rebuildLabel}>{busy ? "Working…" : "↻ Rebuild draft"}</Text>
      </Pressable>
      {err ? <Text style={styles.err}>{err}</Text> : null}

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
                  {"I acknowledge this goal's Engine V2 configuration is still being validated and I have reviewed this programme."}
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

const styles = StyleSheet.create({
  panel: {
    backgroundColor: theme.color.surface2, borderRadius: 12, padding: 14,
    marginHorizontal: 16, marginTop: 12, marginBottom: 4,
    borderWidth: 1, borderColor: theme.color.border,
  },
  headerRow: { flexDirection: "row", alignItems: "center" },
  title: { color: theme.color.textHi, fontWeight: "700", fontSize: 15 },
  sub: { color: theme.color.textMuted, fontSize: 12, marginTop: 4 },
  subHi: { color: theme.color.amber, fontWeight: "700", fontSize: 12, marginBottom: 2 },
  err: { color: theme.color.red, fontSize: 12, marginTop: 6 },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 10 },
  chip: { backgroundColor: theme.color.surface3, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6 },
  chipOk: { backgroundColor: theme.color.green },
  chipDisabled: { backgroundColor: theme.color.surface3, opacity: 0.5 },
  chipLabel: { color: theme.color.textHi, fontSize: 12, fontWeight: "600" },
  rebuild: { marginTop: 10, alignSelf: "flex-start" },
  rebuildLabel: { color: theme.color.textMuted, fontSize: 12 },
  btnPrimary: { backgroundColor: theme.color.brand, paddingVertical: 10, paddingHorizontal: 16,
                borderRadius: 8, marginTop: 12, alignSelf: "flex-start" },
  btnPrimaryLabel: { color: "#fff", fontWeight: "700" },

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
