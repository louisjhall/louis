/**
 * PublishPanel — Draft vs Live diff + selective publishing modal.
 *
 * Priority 4 of the Coach Dashboard V2 PRD:
 *   - Coach sees a side-by-side comparison of LIVE vs DRAFT for every
 *     workout_assignment in the current month.
 *   - Per-item toggle to include/exclude from publish.
 *   - Change-set list with individual Accept / Reject / Skip.
 *   - PUBLISH promotes the selected set to a new immutable plan_version.
 *
 * Guardrails:
 *   - No "AI/bot/generated" wording. Diff is labelled "Refined details" if
 *     opaque, else concrete field deltas.
 *   - Locked assignments are shown but cannot be published.
 *   - Client-facing plan only changes AFTER the coach hits Publish.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, Pressable, StyleSheet, Modal, ScrollView,
  ActivityIndicator, Platform, useWindowDimensions, TextInput,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type ImplSig = {
  present: boolean;
  id?: string;
  title?: string;
  focus?: string;
  duration_min?: number;
  key_session?: boolean;
  variant_type?: string;
  equipment?: string[];
  exercise_count?: number;
  exercise_names?: string[];
  needs_coach_review?: boolean;
};

type AssignmentDiff = {
  id: string;
  date: string;
  kind: string;
  kind_label: string;
  status: string;
  locked: boolean;
  live: ImplSig;
  draft: ImplSig;
  delta_kind: "unchanged" | "modified" | "added" | "removed" | "live_only";
  delta_bullets: string[];
  needs_coach_review: boolean;
};

type ChangeSet = {
  id: string;
  kind: string;
  human_readable_summary: string;
  status: string;
  triggered_by: string;
  proposed_by: string;
  created_at: string;
  scope_assignment_ids: string[];
  before_snapshot?: any;
  after_snapshot?: any;
};

type DiffResp = {
  client_id: string;
  month: string;
  programme?: { id?: string };
  live_version?: { id?: string; version?: number; published_at?: string } | null;
  draft?: { id?: string; status?: string; notes?: string } | null;
  summary: {
    total_assignments: number;
    changed: number;
    added: number;
    unchanged: number;
    change_sets_pending: number;
    change_sets_proposed: number;
  };
  assignments: AssignmentDiff[];
  change_sets: ChangeSet[];
};

const DELTA_TINT: Record<string, string> = {
  modified: "#f5b543",
  added: "#61c982",
  removed: "#ff6b6b",
  unchanged: "#5a5a66",
  live_only: "#5aa9e6",
};

function fmtDate(iso: string): string {
  const dt = new Date(iso + "T00:00:00");
  return dt.toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short" });
}

export function PublishPanel({
  clientId, month, draftId, visible, onClose, onPublished,
}: {
  clientId: string;
  month: string;
  draftId?: string | null;
  visible: boolean;
  onClose: () => void;
  onPublished?: () => void;
}) {
  const { width } = useWindowDimensions();
  const wide = width >= 900;

  const [loading, setLoading] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [data, setData] = useState<DiffResp | null>(null);
  const [error, setError] = useState<string | null>(null);

  // selection state
  const [selectedAssignments, setSelectedAssignments] = useState<Record<string, boolean>>({});
  const [changeSetDecision, setChangeSetDecision] = useState<Record<string, "accept" | "reject" | "skip">>({});
  const [notes, setNotes] = useState("");
  const [publishedNotice, setPublishedNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!clientId || !month) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api<DiffResp>(`/v2/coach/clients/${clientId}/plan/diff?month=${month}`);
      setData(res);
      // Default selections: publishable changes ticked, unchanged/locked/live_only OFF
      const asel: Record<string, boolean> = {};
      (res.assignments || []).forEach((a) => {
        const publishable =
          !a.locked && (a.delta_kind === "modified" || a.delta_kind === "added");
        asel[a.id] = publishable;
      });
      setSelectedAssignments(asel);
      const csel: Record<string, "accept" | "reject" | "skip"> = {};
      (res.change_sets || []).forEach((cs) => {
        if (cs.status === "proposed") csel[cs.id] = "accept";
      });
      setChangeSetDecision(csel);
      setPublishedNotice(null);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [clientId, month]);

  useEffect(() => { if (visible) load(); }, [visible, load]);

  const selectedAssignmentIds = useMemo(
    () => Object.keys(selectedAssignments).filter((k) => selectedAssignments[k]),
    [selectedAssignments]
  );
  const acceptIds = useMemo(
    () => Object.keys(changeSetDecision).filter((k) => changeSetDecision[k] === "accept"),
    [changeSetDecision]
  );
  const rejectIds = useMemo(
    () => Object.keys(changeSetDecision).filter((k) => changeSetDecision[k] === "reject"),
    [changeSetDecision]
  );

  const canPublish = !!(data?.draft?.id) && !publishing && (
    selectedAssignmentIds.length > 0 ||
    acceptIds.length > 0 ||
    rejectIds.length > 0
  );

  const doPublish = useCallback(async () => {
    if (!data?.draft?.id) {
      setError("No active draft to publish. Ask the plan builder to generate one.");
      return;
    }
    setPublishing(true);
    setError(null);
    try {
      const res = await api<{
        published_count: number;
        accepted_change_sets: number;
        rejected_count: number;
        version?: number;
      }>(`/v2/coach/clients/${clientId}/plan/publish`, {
        method: "POST",
        body: {
          draft_id: data.draft.id,
          assignment_ids: selectedAssignmentIds,
          accept_change_set_ids: acceptIds,
          reject_change_set_ids: rejectIds,
          notes: notes || undefined,
          scope: "selected",
        },
      });
      const bits: string[] = [];
      if (res.published_count) bits.push(`${res.published_count} session${res.published_count === 1 ? "" : "s"} live`);
      if (res.accepted_change_sets) bits.push(`${res.accepted_change_sets} change${res.accepted_change_sets === 1 ? "" : "s"} accepted`);
      if (res.rejected_count) bits.push(`${res.rejected_count} rejected`);
      const versionTag = res.version ? ` · v${res.version}` : "";
      setPublishedNotice((bits.join(" · ") || "Nothing changed") + versionTag);
      // Refresh diff view — most items should now be unchanged
      await load();
      if (onPublished) onPublished();
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setPublishing(false);
    }
  }, [clientId, data, selectedAssignmentIds, acceptIds, rejectIds, notes, load, onPublished]);

  // Group assignments by date for display
  const groupedByDate = useMemo(() => {
    const g: Record<string, AssignmentDiff[]> = {};
    (data?.assignments || []).forEach((a) => {
      (g[a.date] = g[a.date] || []).push(a);
    });
    return Object.keys(g).sort().map((d) => ({ date: d, items: g[d] }));
  }, [data]);

  const publishableGroups = useMemo(
    () => groupedByDate.map((g) => ({
      ...g,
      items: g.items.filter((a) => a.delta_kind !== "unchanged" && a.delta_kind !== "live_only"),
    })).filter((g) => g.items.length > 0),
    [groupedByDate]
  );

  return (
    <Modal transparent animationType="fade" visible={visible} onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <Pressable style={{ flex: 1 }} onPress={onClose} />
        <View style={[styles.panel, wide ? styles.panelWide : styles.panelPhone]}>
          {/* Header */}
          <View style={styles.head}>
            <View style={{ flex: 1 }}>
              <Text style={styles.title}>Publish plan changes</Text>
              <Text style={styles.subtitle}>
                Draft vs Live · {month}
                {data?.live_version?.version ? ` · currently on v${data.live_version.version}` : ""}
              </Text>
            </View>
            <Pressable onPress={onClose} testID="publish-close" hitSlop={12}>
              <Ionicons name="close" size={22} color={theme.color.textHi} />
            </Pressable>
          </View>

          {loading ? (
            <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>
          ) : error ? (
            <View style={styles.center}><Text style={styles.err}>{error}</Text></View>
          ) : !data ? (
            <View style={styles.center}><Text style={styles.err}>Nothing loaded.</Text></View>
          ) : !data.draft ? (
            <View style={styles.center}>
              <Text style={styles.emptyTitle}>No active draft</Text>
              <Text style={styles.emptyBody}>
                The plan is fully live. Roster changes, directives, or command-bar edits will open a new draft you can publish here.
              </Text>
            </View>
          ) : (
            <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: 16, paddingBottom: 24 }}
              testID="publish-scroll">
              {/* Summary strip */}
              <View style={styles.sumRow}>
                <SumChip label="Changed"      n={data.summary.changed}      tint="#f5b543" />
                <SumChip label="New"          n={data.summary.added}        tint="#61c982" />
                <SumChip label="Unchanged"    n={data.summary.unchanged}    tint="#5a5a66" />
                <SumChip label="Changes to review" n={data.summary.change_sets_proposed} tint="#5aa9e6" />
              </View>

              {publishedNotice && (
                <View style={styles.publishedBanner}>
                  <Ionicons name="checkmark-circle" size={16} color="#61c982" />
                  <Text style={styles.publishedText}>Published · {publishedNotice}</Text>
                </View>
              )}

              {/* Change sets first — they're the deltas the engine already staged */}
              {data.change_sets && data.change_sets.filter((c) => c.status === "proposed").length > 0 && (
                <View style={styles.section}>
                  <Text style={styles.sectionTitle}>PROPOSED CHANGES</Text>
                  {data.change_sets.filter((c) => c.status === "proposed").map((cs) => (
                    <ChangeSetRow
                      key={cs.id}
                      cs={cs}
                      decision={changeSetDecision[cs.id] || "skip"}
                      onDecision={(d) => setChangeSetDecision((prev) => ({ ...prev, [cs.id]: d }))}
                    />
                  ))}
                </View>
              )}

              {/* Assignment diffs */}
              <View style={styles.section}>
                <Text style={styles.sectionTitle}>SESSIONS TO PUBLISH</Text>
                {publishableGroups.length === 0 ? (
                  <Text style={styles.emptyBody}>No pending session changes for this month.</Text>
                ) : publishableGroups.map((grp) => (
                  <View key={grp.date} style={styles.dateBlock}>
                    <Text style={styles.dateHead}>{fmtDate(grp.date)}</Text>
                    {grp.items.map((a) => (
                      <AssignmentDiffRow
                        key={a.id}
                        a={a}
                        selected={!!selectedAssignments[a.id]}
                        onToggle={() => setSelectedAssignments((prev) => ({ ...prev, [a.id]: !prev[a.id] }))}
                      />
                    ))}
                  </View>
                ))}
              </View>

              {/* Notes footer */}
              <Text style={styles.notesLabel}>Publish note (optional)</Text>
              <TextInput
                style={styles.notesInput}
                value={notes}
                onChangeText={setNotes}
                placeholder="e.g. Reduced volume across next 7 days after roster change."
                placeholderTextColor={theme.color.textDim}
                multiline
                numberOfLines={2}
                testID="publish-notes-input"
              />
            </ScrollView>
          )}

          {/* Sticky footer */}
          {data?.draft && (
            <View style={styles.footer}>
              <View style={{ flex: 1 }}>
                <Text style={styles.footerCount}>
                  {selectedAssignmentIds.length} session{selectedAssignmentIds.length === 1 ? "" : "s"}
                  {" · "}
                  {acceptIds.length} accept · {rejectIds.length} reject
                </Text>
              </View>
              <Pressable
                style={[styles.publishBtn, !canPublish && styles.publishBtnDisabled]}
                onPress={doPublish}
                disabled={!canPublish}
                testID="publish-btn"
              >
                <Ionicons name="rocket-outline" size={16} color={canPublish ? "#000" : "#666"} />
                <Text style={[styles.publishBtnText, !canPublish && { color: "#666" }]}>
                  {publishing ? "Publishing…" : "Publish to Live"}
                </Text>
              </Pressable>
            </View>
          )}
        </View>
      </View>
    </Modal>
  );
}

function SumChip({ label, n, tint }: { label: string; n: number; tint: string }) {
  return (
    <View style={[styles.sumChip, { borderColor: tint }]}>
      <Text style={[styles.sumN, { color: tint }]}>{n}</Text>
      <Text style={styles.sumL}>{label}</Text>
    </View>
  );
}

function ChangeSetRow({ cs, decision, onDecision }: {
  cs: ChangeSet;
  decision: "accept" | "reject" | "skip";
  onDecision: (d: "accept" | "reject" | "skip") => void;
}) {
  return (
    <View style={styles.csRow}>
      <View style={{ flex: 1 }}>
        <Text style={styles.csKind}>{humanise(cs.kind)}</Text>
        <Text style={styles.csSummary}>{cs.human_readable_summary || "(no summary)"}</Text>
        <Text style={styles.csMeta}>
          {cs.triggered_by ? `Triggered by ${humanise(cs.triggered_by)}` : ""}
          {cs.scope_assignment_ids?.length ? ` · affects ${cs.scope_assignment_ids.length} session${cs.scope_assignment_ids.length === 1 ? "" : "s"}` : ""}
        </Text>
      </View>
      <View style={styles.csActions}>
        <Pressable
          style={[styles.csBtn, decision === "accept" && styles.csBtnAccept]}
          onPress={() => onDecision("accept")}
        >
          <Text style={[styles.csBtnText, decision === "accept" && { color: "#000" }]}>ACCEPT</Text>
        </Pressable>
        <Pressable
          style={[styles.csBtn, decision === "reject" && styles.csBtnReject]}
          onPress={() => onDecision("reject")}
        >
          <Text style={[styles.csBtnText, decision === "reject" && { color: "#fff" }]}>REJECT</Text>
        </Pressable>
        <Pressable
          style={[styles.csBtn, decision === "skip" && styles.csBtnSkip]}
          onPress={() => onDecision("skip")}
        >
          <Text style={[styles.csBtnText, decision === "skip" && { color: "#fff" }]}>SKIP</Text>
        </Pressable>
      </View>
    </View>
  );
}

function AssignmentDiffRow({ a, selected, onToggle }: {
  a: AssignmentDiff;
  selected: boolean;
  onToggle: () => void;
}) {
  const tint = DELTA_TINT[a.delta_kind] || "#5a5a66";
  const canPublish = !a.locked && (a.delta_kind === "modified" || a.delta_kind === "added");
  return (
    <View style={styles.adRow}>
      <Pressable onPress={canPublish ? onToggle : undefined} style={styles.adCheck} disabled={!canPublish}>
        <View style={[
          styles.checkbox,
          selected && styles.checkboxOn,
          !canPublish && styles.checkboxDisabled,
        ]}>
          {selected && <Ionicons name="checkmark" size={14} color="#000" />}
        </View>
      </Pressable>
      <View style={{ flex: 1 }}>
        <View style={styles.adTop}>
          <View style={[styles.deltaPill, { backgroundColor: tint + "30", borderColor: tint }]}>
            <Text style={[styles.deltaPillText, { color: tint }]}>{deltaLabel(a.delta_kind)}</Text>
          </View>
          <Text style={styles.adKind} numberOfLines={1}>{a.kind_label}</Text>
          {a.locked && (
            <View style={styles.lockedTag}>
              <Ionicons name="lock-closed" size={10} color="#8e8e93" />
              <Text style={styles.lockedText}>Locked</Text>
            </View>
          )}
          {a.needs_coach_review && (
            <View style={styles.reviewTag}>
              <Text style={styles.reviewText}>Needs review</Text>
            </View>
          )}
        </View>

        {/* Two-column mini diff */}
        <View style={styles.miniDiff}>
          <View style={[styles.miniCol, styles.miniColLive]}>
            <Text style={styles.miniColHead}>LIVE</Text>
            <MiniImpl impl={a.live} />
          </View>
          <View style={[styles.miniCol, styles.miniColDraft, { borderColor: tint }]}>
            <Text style={[styles.miniColHead, { color: tint }]}>DRAFT</Text>
            <MiniImpl impl={a.draft} />
          </View>
        </View>

        {a.delta_bullets?.length > 0 && (
          <View style={styles.bulletsWrap}>
            {a.delta_bullets.map((b, i) => (
              <Text key={i} style={styles.bullet}>• {b}</Text>
            ))}
          </View>
        )}
      </View>
    </View>
  );
}

function MiniImpl({ impl }: { impl: ImplSig }) {
  if (!impl?.present) {
    return <Text style={styles.miniEmpty}>—</Text>;
  }
  return (
    <View>
      <Text style={styles.miniTitle} numberOfLines={2}>{impl.title || impl.focus || "Session"}</Text>
      <Text style={styles.miniMeta}>
        {impl.duration_min ? `${impl.duration_min} min` : ""}
        {typeof impl.exercise_count === "number" ? ` · ${impl.exercise_count} ex.` : ""}
        {impl.key_session ? " · KEY" : ""}
      </Text>
      {impl.equipment && impl.equipment.length > 0 && (
        <Text style={styles.miniMeta} numberOfLines={1}>{impl.equipment.slice(0, 3).join(", ")}</Text>
      )}
    </View>
  );
}

function deltaLabel(k: string): string {
  switch (k) {
    case "modified": return "CHANGED";
    case "added": return "NEW";
    case "removed": return "REMOVED";
    case "live_only": return "LIVE";
    default: return "SAME";
  }
}

function humanise(s?: string): string {
  if (!s) return "";
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, flexDirection: "row", backgroundColor: "rgba(0,0,0,0.55)" },
  panel: {
    backgroundColor: theme.color.bg,
    borderLeftWidth: 1, borderLeftColor: theme.color.border,
    height: "100%",
    ...(Platform.OS === "web" ? { boxShadow: "-8px 0 24px rgba(0,0,0,0.3)" } : {}),
  },
  panelWide: { width: 720 },
  panelPhone: { width: "92%" },

  head: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: 16, paddingVertical: 14,
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  title: { color: theme.color.textHi, fontSize: 18, fontWeight: "800" },
  subtitle: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },

  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  err: { color: "#ff6666" },
  emptyTitle: { color: theme.color.textHi, fontWeight: "700", fontSize: 15, marginBottom: 6 },
  emptyBody: { color: theme.color.textDim, textAlign: "center", maxWidth: 380 },

  sumRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 12 },
  sumChip: {
    paddingHorizontal: 10, paddingVertical: 5, borderRadius: 12, borderWidth: 1,
    flexDirection: "row", alignItems: "center", gap: 6,
  },
  sumN: { fontWeight: "800", fontSize: 14 },
  sumL: { color: theme.color.textDim, fontSize: 10, letterSpacing: 0.5, fontWeight: "700", textTransform: "uppercase" },

  publishedBanner: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: "#0d2c1a", borderColor: "#61c982", borderWidth: 1,
    padding: 10, borderRadius: 6, marginBottom: 12,
  },
  publishedText: { color: "#61c982", fontWeight: "700", fontSize: 12, flex: 1 },

  section: { marginBottom: 18 },
  sectionTitle: {
    color: theme.color.textDim, fontSize: 10, letterSpacing: 1.5,
    fontWeight: "800", marginBottom: 8,
  },

  csRow: {
    backgroundColor: theme.color.surface2, borderRadius: 8,
    borderWidth: 1, borderColor: theme.color.border,
    padding: 12, marginBottom: 8, flexDirection: "row", gap: 12,
  },
  csKind: { color: theme.color.textHi, fontSize: 13, fontWeight: "800" },
  csSummary: { color: theme.color.textHi, fontSize: 13, marginTop: 4 },
  csMeta: { color: theme.color.textDim, fontSize: 11, marginTop: 4 },
  csActions: { flexDirection: "row", gap: 4, alignItems: "flex-start" },
  csBtn: {
    paddingHorizontal: 8, paddingVertical: 5, borderRadius: 4,
    borderWidth: 1, borderColor: theme.color.border,
  },
  csBtnAccept: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  csBtnReject: { backgroundColor: "#5a1f1f", borderColor: "#ff6b6b" },
  csBtnSkip:   { backgroundColor: "#2a2a34", borderColor: "#5a5a66" },
  csBtnText: { color: theme.color.textDim, fontSize: 10, fontWeight: "800", letterSpacing: 0.5 },

  dateBlock: { marginBottom: 12 },
  dateHead: {
    color: theme.color.textDim, fontSize: 11, letterSpacing: 0.5,
    fontWeight: "700", marginBottom: 6,
  },

  adRow: {
    backgroundColor: "#00000030", borderRadius: 8,
    borderWidth: 1, borderColor: theme.color.border,
    padding: 10, marginBottom: 8, flexDirection: "row", gap: 10,
  },
  adCheck: { paddingTop: 2 },
  checkbox: {
    width: 20, height: 20, borderRadius: 4, borderWidth: 1,
    borderColor: theme.color.border, alignItems: "center", justifyContent: "center",
  },
  checkboxOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  checkboxDisabled: { opacity: 0.4 },
  adTop: { flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" },
  deltaPill: {
    paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4, borderWidth: 1,
  },
  deltaPillText: { fontSize: 9, fontWeight: "800", letterSpacing: 0.5 },
  adKind: { color: theme.color.textHi, fontSize: 12, fontWeight: "700", flex: 1 },
  lockedTag: { flexDirection: "row", alignItems: "center", gap: 3 },
  lockedText: { color: "#8e8e93", fontSize: 9, letterSpacing: 0.5 },
  reviewTag: {
    backgroundColor: "#3b2d0d", paddingHorizontal: 5, paddingVertical: 2, borderRadius: 3,
    borderWidth: 1, borderColor: "#f5b543",
  },
  reviewText: { color: "#f5b543", fontSize: 9, fontWeight: "800", letterSpacing: 0.5 },

  miniDiff: { flexDirection: "row", gap: 6, marginTop: 8 },
  miniCol: {
    flex: 1, borderRadius: 6, borderWidth: 1, padding: 8,
  },
  miniColLive: { borderColor: theme.color.border, backgroundColor: "#0e0e14" },
  miniColDraft: { backgroundColor: "#00000030" },
  miniColHead: {
    color: theme.color.textDim, fontSize: 9, letterSpacing: 1,
    fontWeight: "800", marginBottom: 4,
  },
  miniTitle: { color: theme.color.textHi, fontSize: 12, fontWeight: "700" },
  miniMeta: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },
  miniEmpty: { color: theme.color.textDim, fontStyle: "italic", fontSize: 11 },

  bulletsWrap: {
    marginTop: 8, paddingTop: 6, borderTopWidth: 1, borderTopColor: theme.color.border,
  },
  bullet: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },

  notesLabel: {
    color: theme.color.textDim, fontSize: 10, letterSpacing: 1,
    fontWeight: "800", marginTop: 8, marginBottom: 4,
  },
  notesInput: {
    backgroundColor: theme.color.surface2, borderRadius: 6,
    borderWidth: 1, borderColor: theme.color.border,
    padding: 10, minHeight: 44, color: theme.color.textHi, fontSize: 12,
    textAlignVertical: "top",
  },

  footer: {
    flexDirection: "row", alignItems: "center", gap: 12,
    padding: 12, borderTopWidth: 1, borderTopColor: theme.color.border,
    backgroundColor: theme.color.surface2,
  },
  footerCount: { color: theme.color.textDim, fontSize: 11 },
  publishBtn: {
    backgroundColor: theme.color.brand, paddingHorizontal: 16, paddingVertical: 10,
    borderRadius: 6, flexDirection: "row", alignItems: "center", gap: 6,
  },
  publishBtnDisabled: { backgroundColor: "#2a2a34" },
  publishBtnText: { color: "#000", fontWeight: "800", letterSpacing: 0.5, fontSize: 13 },
});
