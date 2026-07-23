/**
 * Coach · Exercise Demand Queue
 *
 * Draft exercise requests bubble up here when the workout generator identifies
 * a movement the client needs but the V2 Library doesn't yet contain. Louis can:
 *   - Approve (accept as-is → status=Approved, client_visible=true, safe_for_programming=true)
 *   - Approve & Edit (approve + jump into the full editor)
 *   - Reject (with reason)
 *   - Merge (into an existing approved exercise; usage history is carried over)
 *   - Generate media (JIT image generation via Nano Banana)
 *
 * Sections:
 *   - Needed Soon: referenced by a workout in the next 7 days
 *   - Awaiting Review: everything else with status=draft_requested
 *   - History: rejected + merged
 */
import { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl, Alert,
  Modal, TextInput, KeyboardAvoidingView, Platform,
} from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Request = {
  id: string;
  exercise_name: string;
  requested_name?: string;
  suggested_name?: string;
  category?: string;
  movement_pattern?: string;
  body_area?: string;
  equipment_type?: string[];
  difficulty_level?: string;
  status: string;
  request_count?: number;
  reason_needed?: string;
  safe_approved_substitute_used?: { id?: string; name?: string } | null;
  clients_affected?: number;
  programmes_affected?: number;
  updated_at?: string;
  approved_image_status?: string;
  primary_image_id?: string | null;
};

type Grouped = {
  needed_soon: Request[];
  awaiting_review: Request[];
  history: Request[];
  counts: { needed_soon: number; awaiting_review: number; history: number; total_pending: number };
};

type SectionKey = "needed_soon" | "awaiting_review" | "history";

const SECTIONS: { key: SectionKey; title: string; sub: string; icon: keyof typeof Ionicons.glyphMap; color: string }[] = [
  { key: "needed_soon",     title: "NEEDED SOON",     sub: "Recently requested, or referenced by a workout in the next 7 days", icon: "flame",       color: "#e5a337" },
  { key: "awaiting_review", title: "AWAITING REVIEW", sub: "Older draft exercise requests still pending",                       icon: "hourglass",   color: theme.color.brand },
  { key: "history",         title: "HISTORY",         sub: "Rejected or merged into existing exercises",                        icon: "archive",     color: theme.color.textDim },
];

export default function DemandQueue() {
  const router = useRouter();
  const [data, setData] = useState<Grouped | null>(null);
  const [loading, setLoading] = useState(true);
  const [section, setSection] = useState<SectionKey>("needed_soon");
  const [autoSectionApplied, setAutoSectionApplied] = useState(false);
  const [selected, setSelected] = useState<Request | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const g = await api<Grouped>(`/exercise-requests/grouped`);
      setData(g);
    } catch (e: any) {
      Alert.alert("Load failed", e?.message || "Could not load the demand queue.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Iter 95j — on first successful load, if "Needed Soon" is empty but there
  // ARE items awaiting review, jump the client straight to that tab so newly
  // generated exercises are actually visible. Only fires once per mount so
  // manual tab switches aren't overridden.
  useEffect(() => {
    if (!data || autoSectionApplied) return;
    const ns = data.counts.needed_soon ?? 0;
    const ar = data.counts.awaiting_review ?? 0;
    if (section === "needed_soon" && ns === 0 && ar > 0) {
      setSection("awaiting_review");
    }
    setAutoSectionApplied(true);
  }, [data, autoSectionApplied, section]);

  const rows = data ? data[section] : [];

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.top}>
        <Pressable onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="chevron-back" size={24} color={theme.color.text} />
        </Pressable>
        <Text style={styles.topT}>DEMAND QUEUE</Text>
        <Pressable onPress={load} hitSlop={12}>
          <Ionicons name="refresh" size={20} color={theme.color.brand} />
        </Pressable>
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.tabsRow}>
        {SECTIONS.map((s) => {
          const active = section === s.key;
          const count = data?.counts[s.key] ?? 0;
          return (
            <Pressable
              key={s.key}
              testID={`dq-tab-${s.key}`}
              onPress={() => setSection(s.key)}
              style={[styles.tab, active && { borderColor: s.color, backgroundColor: s.color }]}
            >
              <Ionicons name={s.icon} size={14} color={active ? "#fff" : s.color} />
              <Text style={[styles.tabText, active && { color: "#fff" }]}>{s.title}</Text>
              {count > 0 ? (
                <View style={[styles.badge, active && { backgroundColor: "rgba(255,255,255,0.25)" }]}>
                  <Text style={[styles.badgeText, active && { color: "#fff" }]}>{count}</Text>
                </View>
              ) : null}
            </Pressable>
          );
        })}
      </ScrollView>

      <View style={styles.subCopyRow}>
        <Text style={styles.subCopy}>{SECTIONS.find((s) => s.key === section)?.sub}</Text>
      </View>

      <ScrollView
        contentContainerStyle={{ padding: 12, paddingBottom: 32 }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}
      >
        {loading && !data ? (
          <View style={{ paddingVertical: 40, alignItems: "center" }}>
            <ActivityIndicator color={theme.color.brand} />
          </View>
        ) : null}

        {!loading && rows.length === 0 ? (
          <View style={styles.empty}>
            <Ionicons name="checkmark-circle" size={40} color={theme.color.textDim} />
            <Text style={styles.emptyTitle}>No requests here</Text>
            <Text style={styles.emptySub}>
              {section === "needed_soon"
                ? "Nothing is blocking upcoming workouts."
                : section === "awaiting_review"
                ? "You've reviewed every pending exercise. Nice."
                : "No rejected or merged history yet."}
            </Text>
          </View>
        ) : null}

        {rows.map((r) => (
          <Pressable
            key={r.id}
            testID={`dq-row-${r.id}`}
            onPress={() => setSelected(r)}
            style={styles.card}
          >
            <View style={styles.cardTop}>
              <Text style={styles.cardName} numberOfLines={1}>{r.suggested_name || r.exercise_name}</Text>
              {typeof r.request_count === "number" && r.request_count > 1 ? (
                <View style={styles.reqPill}>
                  <Text style={styles.reqPillText}>×{r.request_count}</Text>
                </View>
              ) : null}
            </View>
            <View style={styles.metaRow}>
              {r.movement_pattern ? <Text style={styles.metaChip}>{r.movement_pattern.toUpperCase()}</Text> : null}
              {r.body_area ? <Text style={styles.metaChip}>{r.body_area.toUpperCase()}</Text> : null}
              {r.difficulty_level ? <Text style={styles.metaChip}>{r.difficulty_level.toUpperCase()}</Text> : null}
            </View>
            {r.reason_needed ? (
              <Text style={styles.reason} numberOfLines={2}>{r.reason_needed}</Text>
            ) : null}
            <View style={styles.footerRow}>
              {r.safe_approved_substitute_used?.name ? (
                <Text style={styles.subOn}>SUBSTITUTE: {r.safe_approved_substitute_used.name}</Text>
              ) : (
                <Text style={styles.subOnMuted}>NO SAFE SUBSTITUTE</Text>
              )}
              <Text style={styles.impact}>
                {r.clients_affected || 0} client{(r.clients_affected || 0) === 1 ? "" : "s"} · {r.programmes_affected || 0} prog
              </Text>
            </View>
          </Pressable>
        ))}
      </ScrollView>

      <ReviewModal
        request={selected}
        busyId={busyId}
        onClose={() => setSelected(null)}
        onAction={(action, payload) => handleAction(action, selected!, payload, {
          setBusyId, setSelected, reload: load, router,
        })}
      />
    </SafeAreaView>
  );
}

// ---------------------------------------------------------------------------
// Action handler
// ---------------------------------------------------------------------------

type ReviewAction = "approve" | "approve_edit" | "reject" | "merge" | "generate_media";

async function handleAction(
  action: ReviewAction,
  req: Request,
  payload: any,
  ctx: { setBusyId: (v: string | null) => void; setSelected: (v: Request | null) => void; reload: () => void; router: any },
) {
  ctx.setBusyId(req.id);
  try {
    if (action === "approve" || action === "approve_edit") {
      const body: any = { trigger_media: true, ...(payload?.edits || {}) };
      await api(`/exercise-requests/${req.id}/approve-quick`, { method: "POST", body });
      if (action === "approve_edit") {
        ctx.setSelected(null);
        // Route to the existing exercise editor for deeper edits.
        ctx.router.push({ pathname: "/coach/exercise-content" as any, params: { openId: req.id } } as any);
      } else {
        Alert.alert("Approved", `${req.exercise_name} is now available for programming. Media generation queued.`);
      }
    } else if (action === "reject") {
      await api(`/exercise-content/${req.id}/reject`, { method: "POST", body: { reason: payload?.reason || "" } });
      Alert.alert("Rejected", "Request will not be requested again.");
    } else if (action === "merge") {
      if (!payload?.target_id) return;
      await api(`/exercise-content/${req.id}/merge`, { method: "POST", body: { target_id: payload.target_id } });
      Alert.alert("Merged", "Request usage transferred to the canonical exercise.");
    } else if (action === "generate_media") {
      await api(`/exercise-requests/${req.id}/generate-media`, { method: "POST" });
      Alert.alert("Media queued", "Generation running in the background. Refresh in ~30s.");
    }
    ctx.setSelected(null);
    ctx.reload();
  } catch (e: any) {
    Alert.alert("Action failed", e?.message || "Please try again.");
  } finally {
    ctx.setBusyId(null);
  }
}

// ---------------------------------------------------------------------------
// Review Modal (streamlined MVP)
// ---------------------------------------------------------------------------

function ReviewModal({ request, busyId, onClose, onAction }: {
  request: Request | null;
  busyId: string | null;
  onClose: () => void;
  onAction: (action: ReviewAction, payload?: any) => void;
}) {
  const [name, setName] = useState<string>("");
  const [category, setCategory] = useState<string>("");
  const [movement, setMovement] = useState<string>("");
  const [equipment, setEquipment] = useState<string>("");
  const [difficulty, setDifficulty] = useState<string>("");
  const [rejectReason, setRejectReason] = useState<string>("");
  const [mergeSearch, setMergeSearch] = useState<string>("");
  const [mergeResults, setMergeResults] = useState<any[]>([]);
  const [mode, setMode] = useState<"review" | "merge" | "reject">("review");

  useEffect(() => {
    if (!request) return;
    setName(request.suggested_name || request.exercise_name || "");
    setCategory(request.category || "");
    setMovement(request.movement_pattern || "");
    setEquipment((request.equipment_type || []).join(", "));
    setDifficulty(request.difficulty_level || "");
    setRejectReason("");
    setMergeSearch("");
    setMergeResults([]);
    setMode("review");
  }, [request?.id]);

  useEffect(() => {
    if (mode !== "merge") return;
    let cancelled = false;
    (async () => {
      try {
        const q = new URLSearchParams({ q: mergeSearch, approved_only: "true" }).toString();
        const res = await api<any>(`/exercise-content?${q}`);
        // /exercise-content returns { exercises: [...], count } — normalise defensively.
        const arr = Array.isArray(res?.exercises) ? res.exercises
                  : Array.isArray(res?.items)     ? res.items
                  : Array.isArray(res)            ? res
                  : [];
        if (!cancelled) setMergeResults(arr);
      } catch {}
    })();
    return () => { cancelled = true; };
  }, [mergeSearch, mode]);

  const busy = busyId === request?.id;
  if (!request) return null;

  const runApprove = () => onAction("approve", {
    edits: {
      name,
      category: category || undefined,
      movement_pattern: movement || undefined,
      equipment_type: equipment ? equipment.split(",").map((s) => s.trim()).filter(Boolean) : undefined,
      difficulty_level: difficulty || undefined,
    },
  });
  const runApproveEdit = () => onAction("approve_edit", {
    edits: {
      name,
      category: category || undefined,
      movement_pattern: movement || undefined,
      equipment_type: equipment ? equipment.split(",").map((s) => s.trim()).filter(Boolean) : undefined,
      difficulty_level: difficulty || undefined,
    },
  });

  return (
    <Modal visible={!!request} transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={styles.modalScrim}>
        <View style={styles.modalSheet}>
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>{mode === "merge" ? "MERGE INTO EXISTING" : mode === "reject" ? "REJECT REQUEST" : "REVIEW REQUEST"}</Text>
            <Pressable onPress={onClose} testID="dq-review-close" hitSlop={10}>
              <Ionicons name="close" size={22} color={theme.color.text} />
            </Pressable>
          </View>

          <ScrollView contentContainerStyle={{ paddingBottom: 8 }} keyboardShouldPersistTaps="handled" style={{ maxHeight: 520 }}>
            {mode === "review" ? (
              <>
                {request.reason_needed ? (
                  <View style={styles.contextBlock}>
                    <Text style={styles.contextLabel}>WHY IT WAS REQUESTED</Text>
                    <Text style={styles.contextText}>{request.reason_needed}</Text>
                  </View>
                ) : null}
                {request.safe_approved_substitute_used?.name ? (
                  <View style={styles.contextBlock}>
                    <Text style={styles.contextLabel}>SUBSTITUTE IN USE</Text>
                    <Text style={styles.contextText}>{request.safe_approved_substitute_used.name}</Text>
                  </View>
                ) : null}

                <Text style={styles.field}>NAME</Text>
                <TextInput testID="dq-name" value={name} onChangeText={setName} style={styles.input} placeholderTextColor={theme.color.textDim} />

                <View style={styles.row2}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.field}>CATEGORY</Text>
                    <TextInput testID="dq-category" value={category} onChangeText={setCategory} placeholder="strength / mobility …" style={styles.input} placeholderTextColor={theme.color.textDim} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.field}>DIFFICULTY</Text>
                    <TextInput testID="dq-difficulty" value={difficulty} onChangeText={setDifficulty} placeholder="beginner / intermediate / advanced" style={styles.input} placeholderTextColor={theme.color.textDim} />
                  </View>
                </View>

                <Text style={styles.field}>MOVEMENT PATTERN</Text>
                <TextInput testID="dq-movement" value={movement} onChangeText={setMovement} placeholder="hinge / squat / push / pull …" style={styles.input} placeholderTextColor={theme.color.textDim} />

                <Text style={styles.field}>EQUIPMENT (COMMA-SEPARATED)</Text>
                <TextInput testID="dq-equipment" value={equipment} onChangeText={setEquipment} placeholder="dumbbell, bench" style={styles.input} placeholderTextColor={theme.color.textDim} />

                <View style={styles.actionsRow}>
                  <Pressable testID="dq-approve" onPress={runApprove} disabled={busy} style={[styles.actionPrimary, busy && { opacity: 0.6 }]}>
                    {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.actionPrimaryText}>APPROVE</Text>}
                  </Pressable>
                  <Pressable testID="dq-approve-edit" onPress={runApproveEdit} disabled={busy} style={[styles.actionSecondary, busy && { opacity: 0.6 }]}>
                    <Text style={styles.actionSecondaryText}>APPROVE & EDIT</Text>
                  </Pressable>
                </View>

                <View style={styles.actionsRow}>
                  <Pressable testID="dq-reject" onPress={() => setMode("reject")} disabled={busy} style={styles.actionGhost}>
                    <Ionicons name="close-circle" size={14} color="#c85450" />
                    <Text style={[styles.actionGhostText, { color: "#c85450" }]}>REJECT</Text>
                  </Pressable>
                  <Pressable testID="dq-merge" onPress={() => setMode("merge")} disabled={busy} style={styles.actionGhost}>
                    <Ionicons name="git-merge" size={14} color={theme.color.text} />
                    <Text style={styles.actionGhostText}>MERGE</Text>
                  </Pressable>
                  <Pressable testID="dq-gen-media" onPress={() => onAction("generate_media")} disabled={busy} style={styles.actionGhost}>
                    <Ionicons name="image" size={14} color={theme.color.text} />
                    <Text style={styles.actionGhostText}>GEN MEDIA</Text>
                  </Pressable>
                </View>
              </>
            ) : mode === "reject" ? (
              <>
                <Text style={styles.field}>REASON</Text>
                <TextInput
                  testID="dq-reject-reason"
                  value={rejectReason}
                  onChangeText={setRejectReason}
                  placeholder="e.g. Redundant with existing hinge options"
                  placeholderTextColor={theme.color.textDim}
                  multiline
                  style={[styles.input, { minHeight: 90 }]}
                />
                <View style={styles.actionsRow}>
                  <Pressable testID="dq-reject-cancel" onPress={() => setMode("review")} style={styles.actionSecondary}>
                    <Text style={styles.actionSecondaryText}>BACK</Text>
                  </Pressable>
                  <Pressable
                    testID="dq-reject-confirm"
                    onPress={() => onAction("reject", { reason: rejectReason })}
                    disabled={busy}
                    style={[styles.actionPrimary, { backgroundColor: "#c85450" }, busy && { opacity: 0.6 }]}
                  >
                    {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.actionPrimaryText}>REJECT</Text>}
                  </Pressable>
                </View>
              </>
            ) : (
              <>
                <Text style={styles.field}>SEARCH EXISTING APPROVED EXERCISES</Text>
                <TextInput
                  testID="dq-merge-search"
                  value={mergeSearch}
                  onChangeText={setMergeSearch}
                  placeholder="Type to search…"
                  placeholderTextColor={theme.color.textDim}
                  style={styles.input}
                />
                <View style={{ marginTop: 8, maxHeight: 260 }}>
                  {(Array.isArray(mergeResults) ? mergeResults : []).slice(0, 15).map((r: any) => (
                    <Pressable
                      key={r.id}
                      testID={`dq-merge-target-${r.id}`}
                      onPress={() => onAction("merge", { target_id: r.id })}
                      style={styles.mergeRow}
                    >
                      <Text style={styles.mergeName} numberOfLines={1}>{r.exercise_name}</Text>
                      <Text style={styles.mergeMeta}>{r.movement_pattern || ""} · {r.status}</Text>
                    </Pressable>
                  ))}
                  {mergeSearch && mergeResults.length === 0 ? (
                    <Text style={styles.mergeEmpty}>No approved exercises match &quot;{mergeSearch}&quot;.</Text>
                  ) : null}
                </View>
                <Pressable testID="dq-merge-cancel" onPress={() => setMode("review")} style={styles.actionSecondary}>
                  <Text style={styles.actionSecondaryText}>BACK</Text>
                </Pressable>
              </>
            )}
          </ScrollView>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  top: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 14, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: theme.color.border },
  topT: { color: theme.color.text, fontSize: 14, letterSpacing: 2, fontWeight: "800" },
  tabsRow: { paddingHorizontal: 12, paddingVertical: 10, gap: 6 },
  tab: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 8, borderRadius: theme.radius.pill, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  tabText: { color: theme.color.text, fontSize: 11, letterSpacing: 1.2, fontWeight: "800" },
  badge: { backgroundColor: theme.color.brand, paddingHorizontal: 6, paddingVertical: 1, borderRadius: 8, minWidth: 18, alignItems: "center" },
  badgeText: { color: "#fff", fontSize: 10, fontWeight: "800" },
  subCopyRow: { paddingHorizontal: 14, paddingBottom: 6 },
  subCopy: { color: theme.color.textDim, fontSize: 11, letterSpacing: 0.8 },
  empty: { alignItems: "center", paddingVertical: 60, gap: 8 },
  emptyTitle: { color: theme.color.text, fontSize: 15, fontWeight: "800" },
  emptySub: { color: theme.color.textDim, fontSize: 12, textAlign: "center", paddingHorizontal: 20 },
  card: { padding: 14, borderRadius: theme.radius.md, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, marginBottom: 8 },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 8 },
  cardName: { color: theme.color.text, fontSize: 15, fontWeight: "800", flex: 1 },
  reqPill: { backgroundColor: "#e5a337", paddingHorizontal: 8, paddingVertical: 3, borderRadius: 8 },
  reqPillText: { color: "#fff", fontSize: 10, fontWeight: "800" },
  metaRow: { flexDirection: "row", gap: 6, marginTop: 6, flexWrap: "wrap" },
  metaChip: { color: theme.color.textMuted, fontSize: 9, fontWeight: "800", letterSpacing: 1, borderWidth: 1, borderColor: theme.color.border, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  reason: { color: theme.color.textMuted, fontSize: 12, marginTop: 8, lineHeight: 16 },
  footerRow: { flexDirection: "row", justifyContent: "space-between", marginTop: 8, alignItems: "center" },
  subOn: { color: theme.color.textMuted, fontSize: 10, fontWeight: "700", letterSpacing: 1 },
  subOnMuted: { color: "#c85450", fontSize: 10, fontWeight: "700", letterSpacing: 1 },
  impact: { color: theme.color.textDim, fontSize: 10 },
  modalScrim: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  modalSheet: { backgroundColor: theme.color.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: 16, paddingBottom: 24 },
  modalHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 12 },
  modalTitle: { color: theme.color.text, fontSize: 14, fontWeight: "900", letterSpacing: 2 },
  contextBlock: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, padding: 12, marginBottom: 10, borderWidth: 1, borderColor: theme.color.border },
  contextLabel: { color: theme.color.brand, fontSize: 9, letterSpacing: 1.5, fontWeight: "800" },
  contextText: { color: theme.color.text, fontSize: 13, marginTop: 4, lineHeight: 18 },
  field: { color: theme.color.textDim, fontSize: 9, letterSpacing: 1.5, fontWeight: "800", marginTop: 8, marginBottom: 4 },
  input: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, color: theme.color.text, padding: 12, borderWidth: 1, borderColor: theme.color.border, fontSize: 14 },
  row2: { flexDirection: "row", gap: 10 },
  actionsRow: { flexDirection: "row", gap: 8, marginTop: 12 },
  actionPrimary: { flex: 1, backgroundColor: theme.color.brand, paddingVertical: 12, borderRadius: theme.radius.md, alignItems: "center" },
  actionPrimaryText: { color: "#fff", fontWeight: "800", letterSpacing: 1.5, fontSize: 12 },
  actionSecondary: { flex: 1, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, paddingVertical: 12, borderRadius: theme.radius.md, alignItems: "center" },
  actionSecondaryText: { color: theme.color.text, fontWeight: "800", letterSpacing: 1.5, fontSize: 12 },
  actionGhost: { flex: 1, flexDirection: "row", justifyContent: "center", alignItems: "center", gap: 6, paddingVertical: 10, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, backgroundColor: "transparent" },
  actionGhostText: { color: theme.color.text, fontWeight: "800", letterSpacing: 1.2, fontSize: 11 },
  mergeRow: { paddingVertical: 10, paddingHorizontal: 12, borderBottomWidth: 1, borderBottomColor: theme.color.border },
  mergeName: { color: theme.color.text, fontSize: 13, fontWeight: "700" },
  mergeMeta: { color: theme.color.textDim, fontSize: 10, marginTop: 2 },
  mergeEmpty: { color: theme.color.textDim, fontSize: 12, padding: 12, textAlign: "center" },
});
