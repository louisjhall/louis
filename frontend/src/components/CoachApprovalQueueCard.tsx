/**
 * CoachApprovalQueueCard — Phase 7B coach dashboard section.
 *
 * Renders the queue of programme-approval-pending clients as a "one-tap
 * approve" task list. Backed by:
 *   - GET  /api/coach/tasks?filter_type=programme_approval_pending
 *   - GET  /api/coach/clients/{cid}/approval-preview
 *   - POST /api/coach/clients/{cid}/approve-programme
 *
 * The confirm sheet shows Louis a snapshot of what the client will see the
 * instant he approves (today's plan state + workouts hidden until now).
 * Approve → instantly unlocks all hidden workouts in the roster date range
 * and drops a Louis-branded message in the client's inbox.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ActivityIndicator,
  Modal,
} from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast } from "@/src/lib/ux";

type Task = {
  id: string;
  user_id: string;
  client_id?: string;
  client_name?: string;
  title?: string;
  summary?: string;
  roster_id?: string;
  created_at?: string;
  priority?: string;
};

type Preview = {
  client: { id: string; name?: string };
  roster: { id: string; airline: string; start_date?: string; end_date?: string; confidence_avg?: number | null };
  workouts_total: number;
  workouts_hidden: number;
  today_if_approved: { state: string; label?: string | null };
  will_publish_now: boolean;
};

const TODAY_LABEL: Record<string, string> = {
  session_planned: "Session planned",
  recovery_planned: "Recovery day",
  rest_day: "Rest day",
  travel_day: "Flying day",
  layover_day: "Layover day",
  nutrition_focus: "Nutrition focus",
  habit_focus: "Habit focus",
  no_session_planned: "No session planned",
};

function fmtDate(d?: string): string {
  if (!d) return "";
  try {
    const dt = new Date(d + "T00:00:00");
    return dt.toLocaleDateString(undefined, { day: "numeric", month: "short" });
  } catch {
    return d;
  }
}

export function CoachApprovalQueueCard() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [previewFor, setPreviewFor] = useState<string | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [approving, setApproving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // We pull ONLY programme_approval_pending here so the card is focused.
      const r = await api<{ tasks: Task[] }>(
        "/coach/tasks?filter_type=programme_approval_pending",
      ).catch(() => ({ tasks: [] as Task[] }));
      setTasks((r?.tasks || []).filter((t) => (t as any).status !== "done" && (t as any).status !== "dismissed"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const openPreview = useCallback(async (clientId: string) => {
    setPreviewFor(clientId);
    setPreview(null);
    setPreviewLoading(true);
    try {
      const p = await api<Preview>(`/coach/clients/${clientId}/approval-preview`);
      setPreview(p);
    } catch (e: any) {
      toast(e?.message || "Couldn't load approval preview", "error");
      setPreviewFor(null);
    } finally {
      setPreviewLoading(false);
    }
  }, []);

  const closePreview = useCallback(() => {
    setPreviewFor(null);
    setPreview(null);
  }, []);

  const approve = useCallback(async () => {
    if (!previewFor) return;
    setApproving(true);
    try {
      const r = await api<{ ok: boolean; unlocked_workouts: number }>(
        `/coach/clients/${previewFor}/approve-programme`,
        { method: "POST", body: {} },
      );
      toast(
        r.unlocked_workouts > 0
          ? `Programme live · ${r.unlocked_workouts} session${r.unlocked_workouts === 1 ? "" : "s"} unlocked`
          : "Programme approved",
        "success",
      );
      closePreview();
      load();
    } catch (e: any) {
      toast(e?.message || "Couldn't approve programme", "error");
    } finally {
      setApproving(false);
    }
  }, [previewFor, load, closePreview]);

  if (loading && tasks.length === 0) {
    return (
      <View style={styles.wrap}>
        <View style={styles.headRow}>
          <Text style={styles.head}>PROGRAMME APPROVALS</Text>
          <ActivityIndicator color={theme.color.brand} size="small" />
        </View>
      </View>
    );
  }

  if (tasks.length === 0) {
    // Card is intentionally hidden when there's nothing pending — Louis
    // shouldn't see a permanent "0" box on the dashboard.
    return null;
  }

  return (
    <View style={styles.wrap} testID="coach-approval-queue-card">
      <View style={styles.headRow}>
        <View style={{ flex: 1 }}>
          <Text style={styles.head}>PROGRAMME APPROVALS</Text>
          <Text style={styles.sub}>
            {tasks.length} client{tasks.length === 1 ? "" : "s"} waiting for you to push their programme live
          </Text>
        </View>
        <View style={styles.countPill}><Text style={styles.countPillT}>{tasks.length}</Text></View>
      </View>

      <View style={{ gap: 10 }}>
        {tasks.slice(0, 6).map((t) => {
          const clientId = t.client_id || t.user_id;
          return (
            <View key={t.id} style={styles.taskCard} testID={`caq-${t.id}`}>
              <View style={styles.avatar}>
                <Text style={styles.avatarT}>{((t.client_name || "?")[0] || "?").toUpperCase()}</Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.clientName} numberOfLines={1}>{t.client_name || "Client"}</Text>
                <Text style={styles.summary} numberOfLines={2}>
                  {t.summary || "Roster ready — approve to push the programme live."}
                </Text>
                <View style={styles.actionsRow}>
                  <Pressable
                    testID={`caq-approve-${t.id}`}
                    onPress={() => openPreview(clientId)}
                    style={styles.approveBtn}
                  >
                    <Ionicons name="checkmark-circle" size={13} color="#fff" />
                    <Text style={styles.approveT}>APPROVE PROGRAMME</Text>
                  </Pressable>
                  <Pressable
                    testID={`caq-review-${t.id}`}
                    onPress={() => router.push(`/coach/client-months/${clientId}` as any)}
                    style={styles.reviewBtn}
                  >
                    <Ionicons name="eye" size={13} color={theme.color.brand} />
                    <Text style={styles.reviewT}>REVIEW FIRST</Text>
                  </Pressable>
                </View>
              </View>
            </View>
          );
        })}
        {tasks.length > 6 ? (
          <Text style={styles.moreCount}>+{tasks.length - 6} more waiting</Text>
        ) : null}
      </View>

      {/* Approval preview modal — one-tap confirmation */}
      <Modal visible={!!previewFor} animationType="slide" transparent onRequestClose={closePreview}>
        <Pressable style={styles.modalBg} onPress={closePreview}>
          <Pressable style={styles.sheet} onPress={(e) => e.stopPropagation()}>
            <View style={styles.sheetHandle} />
            <Text style={styles.sheetTitle}>APPROVE PROGRAMME</Text>

            {previewLoading || !preview ? (
              <View style={{ paddingVertical: 30, alignItems: "center" }}>
                <ActivityIndicator color={theme.color.brand} />
              </View>
            ) : (
              <>
                <Text style={styles.sheetClient}>{preview.client.name || "Client"}</Text>
                <Text style={styles.sheetSub}>
                  {preview.roster.airline}
                  {preview.roster.start_date ? ` · ${fmtDate(preview.roster.start_date)} → ${fmtDate(preview.roster.end_date)}` : ""}
                </Text>

                <View style={styles.previewGrid}>
                  <View style={styles.previewBox}>
                    <Text style={styles.previewV}>{preview.workouts_total}</Text>
                    <Text style={styles.previewL}>SESSIONS PLANNED</Text>
                  </View>
                  <View style={styles.previewBox}>
                    <Text style={[styles.previewV, { color: preview.workouts_hidden > 0 ? theme.color.amber : theme.color.green }]}>
                      {preview.workouts_hidden}
                    </Text>
                    <Text style={styles.previewL}>CURRENTLY HIDDEN</Text>
                  </View>
                </View>

                <View style={styles.todayBlock}>
                  <Text style={styles.todayEyebrow}>WHAT THE CLIENT SEES TODAY IF YOU APPROVE NOW</Text>
                  <Text style={styles.todayValue}>
                    {preview.today_if_approved?.label || TODAY_LABEL[preview.today_if_approved?.state] || "Session planned"}
                  </Text>
                </View>

                {preview.will_publish_now ? (
                  <Text style={styles.publishNote}>
                    Approving will unlock {preview.workouts_hidden} hidden session
                    {preview.workouts_hidden === 1 ? "" : "s"} instantly and drop a Louis message in the client&apos;s inbox.
                  </Text>
                ) : (
                  <Text style={styles.publishNote}>
                    Nothing is currently hidden — approving will simply confirm the programme and message the client.
                  </Text>
                )}

                <View style={styles.sheetActions}>
                  <Pressable
                    testID="caq-preview-cancel"
                    onPress={closePreview}
                    disabled={approving}
                    style={[styles.sheetBtn, styles.sheetBtnGhost, approving && { opacity: 0.5 }]}
                  >
                    <Text style={styles.sheetBtnGhostT}>NOT YET</Text>
                  </Pressable>
                  <Pressable
                    testID="caq-preview-approve"
                    onPress={approve}
                    disabled={approving}
                    style={[styles.sheetBtn, styles.sheetBtnPrimary, approving && { opacity: 0.6 }]}
                  >
                    {approving ? (
                      <ActivityIndicator color="#fff" />
                    ) : (
                      <>
                        <Ionicons name="checkmark" size={16} color="#fff" />
                        <Text style={styles.sheetBtnPrimaryT}>APPROVE &amp; PUBLISH</Text>
                      </>
                    )}
                  </Pressable>
                </View>
              </>
            )}
          </Pressable>
        </Pressable>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    marginTop: 20,
    marginHorizontal: 0,
    padding: 16,
    borderRadius: 12,
    backgroundColor: theme.color.brandTint,
    borderWidth: 1,
    borderColor: theme.color.brand,
  },
  headRow: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 12 },
  head: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  sub: { color: theme.color.textMuted, fontSize: 11, marginTop: 3 },
  countPill: {
    paddingHorizontal: 10, paddingVertical: 3,
    borderRadius: 4,
    backgroundColor: theme.color.surface,
    borderWidth: 1, borderColor: theme.color.brand,
  },
  countPillT: { color: theme.color.brand, fontSize: 10, fontWeight: "900" },

  taskCard: {
    flexDirection: "row",
    gap: 12,
    padding: 12,
    borderRadius: 10,
    backgroundColor: theme.color.surface2,
    borderWidth: 1,
    borderColor: theme.color.border,
  },
  avatar: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
  },
  avatarT: { color: "#fff", fontWeight: "900", fontSize: 13 },
  clientName: { color: theme.color.text, fontSize: 13, fontWeight: "800" },
  summary: { color: theme.color.textMuted, fontSize: 11, lineHeight: 15, marginTop: 3 },

  actionsRow: { flexDirection: "row", gap: 8, marginTop: 10, flexWrap: "wrap" },
  approveBtn: {
    flexDirection: "row", alignItems: "center", gap: 5,
    paddingVertical: 8, paddingHorizontal: 12,
    borderRadius: 8,
    backgroundColor: theme.color.brand,
  },
  approveT: { color: "#fff", fontSize: 10, fontWeight: "900", letterSpacing: 1.2 },
  reviewBtn: {
    flexDirection: "row", alignItems: "center", gap: 5,
    paddingVertical: 8, paddingHorizontal: 12,
    borderRadius: 8,
    borderWidth: 1, borderColor: theme.color.brand,
    backgroundColor: theme.color.surface,
  },
  reviewT: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1.2 },
  moreCount: { color: theme.color.textMuted, fontSize: 11, textAlign: "center", marginTop: 4 },

  // Modal / preview sheet
  modalBg: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.55)",
    justifyContent: "flex-end",
  },
  sheet: {
    backgroundColor: theme.color.surface,
    borderTopLeftRadius: 20, borderTopRightRadius: 20,
    padding: 20, paddingBottom: 34,
    gap: 6,
  },
  sheetHandle: {
    alignSelf: "center",
    width: 40, height: 4, borderRadius: 2,
    backgroundColor: theme.color.border,
    marginBottom: 12,
  },
  sheetTitle: { color: theme.color.brand, fontSize: 11, letterSpacing: 2, fontWeight: "900" },
  sheetClient: { color: theme.color.text, fontSize: 18, fontWeight: "900", marginTop: 6 },
  sheetSub: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },

  previewGrid: {
    flexDirection: "row",
    gap: 8,
    marginTop: 14,
  },
  previewBox: {
    flex: 1,
    padding: 12,
    borderRadius: 10,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
    alignItems: "center",
  },
  previewV: { color: theme.color.text, fontSize: 24, fontWeight: "900" },
  previewL: { color: theme.color.textMuted, fontSize: 9, fontWeight: "800", letterSpacing: 1, marginTop: 3 },

  todayBlock: {
    marginTop: 14,
    padding: 12,
    borderRadius: 10,
    backgroundColor: theme.color.brandTint,
    borderLeftWidth: 3,
    borderLeftColor: theme.color.brand,
  },
  todayEyebrow: { color: theme.color.brand, fontSize: 9, fontWeight: "900", letterSpacing: 1.4 },
  todayValue: { color: theme.color.text, fontSize: 15, fontWeight: "800", marginTop: 4 },

  publishNote: {
    color: theme.color.textMuted,
    fontSize: 12,
    lineHeight: 17,
    marginTop: 12,
  },

  sheetActions: {
    flexDirection: "row",
    gap: 8,
    marginTop: 16,
  },
  sheetBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 14,
    borderRadius: 10,
  },
  sheetBtnPrimary: { backgroundColor: theme.color.brand },
  sheetBtnPrimaryT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 1.5 },
  sheetBtnGhost: { backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border },
  sheetBtnGhostT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "800", letterSpacing: 1.5 },
});

export default CoachApprovalQueueCard;
