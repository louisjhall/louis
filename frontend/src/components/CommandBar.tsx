/**
 * CommandBar — Coach Dashboard V2
 *
 * Free-text input at the top of the Roster + Plan workspace. Coach types
 * an instruction; backend returns structured proposals; coach reviews and
 * applies the ones they want. Nothing mutates LIVE until the resulting
 * change_sets go through the normal approval flow.
 */
import React, { useState, useCallback } from "react";
import {
  View, Text, TextInput, Pressable, StyleSheet, ActivityIndicator, ScrollView,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Proposal = {
  proposal_id: string;
  kind: string;
  assignment_id?: string;
  target_date?: string;
  new_date?: string;
  target_kind_or_pattern?: string;
  duration_min_new?: number;
  duration_min_delta_pct?: number;
  directive_kind?: string;
  directive_scope?: string;
  reason?: string;
  summary?: string;
};

type Preview = {
  preview_id: string;
  proposals: Proposal[];
  input_text: string;
};

const EXAMPLES = [
  "Move his long run to Saturday and keep Friday recovery.",
  "No running until Sunday because his knee is sore.",
  "Reduce his training volume by 20% this week.",
  "Make Tuesday bodyweight only.",
  "Add another strength session on one of his next home days.",
];

const KIND_ICON: Record<string, any> = {
  move_assignment: "swap-horizontal",
  edit_duration: "time",
  convert_to_mobility: "leaf",
  convert_to_recovery: "bed",
  swap_exercise: "sync",
  add_directive: "flag",
  reduce_volume: "trending-down",
  skip_session: "close-circle",
  lock_session: "lock-closed",
  note_only: "chatbox-ellipses",
};

export function CommandBar({
  clientId,
  month,
  draftId,
  onApplied,
  defaultExpanded,
  onClose,
}: {
  clientId: string;
  month: string;
  draftId?: string;
  onApplied?: () => void;
  /** Iter 128f — density pass. When true (toolbar-triggered mode), the
   *  component opens expanded and the close button calls onClose instead
   *  of collapsing to a permanent full-width row. */
  defaultExpanded?: boolean;
  onClose?: () => void;
}) {
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(!defaultExpanded);

  const parse = useCallback(async () => {
    if (!text.trim()) return;
    setBusy(true); setError(null); setPreview(null);
    try {
      const res = await api<Preview>(`/v2/coach/clients/${clientId}/command-bar/parse`, {
        method: "POST",
        body: { month, text: text.trim(), draft_id: draftId },
      });
      setPreview(res);
      const sel: Record<string, boolean> = {};
      for (const p of res.proposals || []) sel[p.proposal_id] = true;
      setSelected(sel);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally { setBusy(false); }
  }, [text, month, clientId, draftId]);

  const apply = useCallback(async () => {
    if (!preview) return;
    const accepted = Object.entries(selected).filter(([, v]) => v).map(([k]) => k);
    if (!accepted.length) { setError("Select at least one proposal"); return; }
    setBusy(true); setError(null);
    try {
      await api(`/v2/coach/clients/${clientId}/command-bar/apply`, {
        method: "POST",
        body: { preview_id: preview.preview_id, accept_proposal_ids: accepted, draft_id: draftId },
      });
      setPreview(null);
      setText("");
      if (defaultExpanded) { onClose?.(); }
      else { setCollapsed(true); }
      onApplied?.();
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally { setBusy(false); }
  }, [preview, selected, clientId, draftId, onApplied, defaultExpanded, onClose]);

  const clear = useCallback(() => {
    setPreview(null); setSelected({}); setError(null);
  }, []);

  return (
    <View style={styles.wrap} testID="command-bar">
      {collapsed ? (
        <Pressable style={styles.collapsedRow} onPress={() => setCollapsed(false)} testID="command-bar-open">
          <Ionicons name="chatbubble-ellipses-outline" size={16} color={theme.color.textDim} />
          <Text style={styles.collapsedText}>Ask CrewFit to adjust this plan…</Text>
          <Ionicons name="chevron-down" size={14} color={theme.color.textDim} />
        </Pressable>
      ) : (
        <View style={styles.expanded}>
          <View style={styles.inputRow}>
            <Ionicons name="chatbubble-ellipses" size={16} color={theme.color.brand} style={{ marginTop: 6 }} />
            <TextInput
              value={text}
              onChangeText={setText}
              placeholder={"e.g. Move Tuesday's long run to Sunday and reduce Thursday to 30 min"}
              placeholderTextColor={theme.color.textDim}
              style={styles.input}
              multiline
              editable={!busy}
              testID="command-bar-input"
            />
            <Pressable
              style={[styles.sendBtn, (!text.trim() || busy) && { opacity: 0.5 }]}
              onPress={parse}
              disabled={!text.trim() || busy}
              testID="command-bar-send"
            >
              {busy && !preview ? <ActivityIndicator color="#000" /> :
                <Text style={styles.sendBtnText}>Propose</Text>}
            </Pressable>
            <Pressable onPress={() => {
              if (defaultExpanded) { clear(); setText(""); onClose?.(); }
              else { setCollapsed(true); clear(); setText(""); }
            }} style={styles.iconBtn}>
              <Ionicons name="close" size={18} color={theme.color.textDim} />
            </Pressable>
          </View>

          {!preview && !busy && (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6, paddingTop: 6 }}>
              {EXAMPLES.map((e, i) => (
                <Pressable key={i} onPress={() => setText(e)} style={styles.exampleChip}>
                  <Text style={styles.exampleChipText}>{e}</Text>
                </Pressable>
              ))}
            </ScrollView>
          )}

          {error && <Text style={styles.errorText}>{error}</Text>}

          {preview && (
            <View style={styles.previewBox}>
              <Text style={styles.previewTitle}>PROPOSED CHANGES · {preview.proposals.length}</Text>
              {preview.proposals.length === 0 ? (
                <Text style={styles.emptyProp}>No proposals returned.</Text>
              ) : (
                preview.proposals.map((p) => (
                  <Pressable
                    key={p.proposal_id}
                    style={[styles.propRow, selected[p.proposal_id] && styles.propRowSelected]}
                    onPress={() => setSelected((s) => ({ ...s, [p.proposal_id]: !s[p.proposal_id] }))}
                    testID={`command-proposal-${p.proposal_id}`}
                  >
                    <Ionicons
                      name={selected[p.proposal_id] ? "checkbox" : "square-outline"}
                      size={18}
                      color={selected[p.proposal_id] ? theme.color.brand : theme.color.textDim}
                    />
                    <Ionicons
                      name={KIND_ICON[p.kind] || "ellipsis-horizontal"}
                      size={14}
                      color={theme.color.textDim}
                      style={{ marginLeft: 6 }}
                    />
                    <View style={{ flex: 1, marginLeft: 8 }}>
                      <Text style={styles.propSummary}>{p.summary || p.kind}</Text>
                      {p.reason && <Text style={styles.propReason}>{p.reason}</Text>}
                    </View>
                  </Pressable>
                ))
              )}
              <View style={styles.previewActions}>
                <Pressable style={styles.applyBtn} onPress={apply} disabled={busy} testID="command-apply">
                  <Text style={styles.applyBtnText}>{busy ? "Applying…" : "Apply to Draft"}</Text>
                </Pressable>
                <Pressable style={styles.cancelBtn} onPress={clear} disabled={busy}>
                  <Text style={styles.cancelBtnText}>Cancel</Text>
                </Pressable>
              </View>
            </View>
          )}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    marginHorizontal: 12, marginTop: 8, marginBottom: 4,
    backgroundColor: theme.color.surface2, borderRadius: 8,
    borderWidth: 1, borderColor: theme.color.border,
  },
  collapsedRow: {
    flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 12, paddingVertical: 10,
  },
  collapsedText: { flex: 1, color: theme.color.textDim, fontSize: 13 },

  expanded: { padding: 10 },
  inputRow: { flexDirection: "row", alignItems: "flex-start", gap: 8 },
  input: {
    flex: 1, minHeight: 36, maxHeight: 100, color: theme.color.textHi, fontSize: 13,
    backgroundColor: "#00000030", borderRadius: 6, paddingHorizontal: 10, paddingVertical: 8,
    borderWidth: 1, borderColor: theme.color.border,
  },
  sendBtn: {
    backgroundColor: theme.color.brand, paddingHorizontal: 14, paddingVertical: 8,
    borderRadius: 6, alignItems: "center", justifyContent: "center", minHeight: 36,
  },
  sendBtnText: { color: "#000", fontWeight: "800", fontSize: 12, letterSpacing: 0.5 },
  iconBtn: { padding: 6 },

  exampleChip: {
    backgroundColor: "#00000030", borderRadius: 12, paddingHorizontal: 10, paddingVertical: 5,
    borderWidth: 1, borderColor: theme.color.border,
  },
  exampleChipText: { color: theme.color.textDim, fontSize: 11 },

  errorText: { color: "#ff6666", fontSize: 12, marginTop: 6 },

  previewBox: { marginTop: 10, backgroundColor: "#00000030", borderRadius: 6, padding: 10 },
  previewTitle: { color: theme.color.textDim, fontSize: 10, letterSpacing: 1.5, fontWeight: "800", marginBottom: 6 },
  emptyProp: { color: theme.color.textDim, fontStyle: "italic", fontSize: 12 },
  propRow: {
    flexDirection: "row", alignItems: "flex-start", paddingVertical: 6, gap: 4,
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  propRowSelected: { backgroundColor: "#00000020" },
  propSummary: { color: theme.color.textHi, fontSize: 13, fontWeight: "600" },
  propReason: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },
  previewActions: { flexDirection: "row", gap: 8, marginTop: 10 },
  applyBtn: {
    backgroundColor: theme.color.brand, paddingHorizontal: 14, paddingVertical: 8, borderRadius: 6,
  },
  applyBtnText: { color: "#000", fontWeight: "800", fontSize: 12, letterSpacing: 0.5 },
  cancelBtn: {
    borderWidth: 1, borderColor: theme.color.border,
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: 6,
  },
  cancelBtnText: { color: theme.color.textDim, fontWeight: "700", fontSize: 12 },
});
