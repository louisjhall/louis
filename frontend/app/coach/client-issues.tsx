/**
 * Coach Client-Issues Inbox — central place for all client reported issues.
 * Reuses:
 *   • existing api() helper, theme, ux toast() & confirm()
 *   • existing coach-tab screen layout patterns
 *   • ScrollView + refresh pattern from other coach screens
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  RefreshControl, Modal, Image, TextInput,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast } from "@/src/lib/ux";

type Issue = {
  id: string;
  user_id: string; user_name: string; user_email: string;
  category: string; description: string;
  what_should_happen?: string;
  urgency: "normal" | "blocking";
  status: string;
  route?: string; platform?: string;
  app_version?: string; app_build?: string;
  workout_id?: string; exercise_id?: string; exercise_name?: string;
  error_code?: string;
  screenshot_base64?: string;
  coach_reply?: string; coach_reply_at?: string;
  internal_notes?: { text: string; by: string; at: string }[];
  assigned_area?: string;
  created_at: string; updated_at: string;
  group_summary?: {
    group_id: string; report_count: number; clients: number;
    platforms: string[]; builds: string[];
    first_reported_at: string; last_reported_at: string;
  };
};

const STATUS_ORDER = ["new", "reviewing", "fix_in_progress", "waiting_for_client", "resolved", "closed"];
const STATUS_LABEL: Record<string, string> = {
  new: "New", reviewing: "Reviewing", fix_in_progress: "Fix in progress",
  waiting_for_client: "Waiting for client", resolved: "Resolved", closed: "Closed",
};
const CATEGORY_LABEL: Record<string, string> = {
  workout_not_working: "Workout", exercise_or_media: "Exercise / media",
  roster: "Roster", flight_support: "Flight Support",
  todays_reality: "Today's Reality", app_button_or_screen: "App button",
  login_or_account: "Login", progress_or_habit: "Progress",
  other: "Other",
};

export default function ClientIssuesScreen() {
  const router = useRouter();
  const [issues, setIssues] = useState<Issue[]>([]);
  const [counts, setCounts] = useState<any>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [openIssue, setOpenIssue] = useState<Issue | null>(null);
  const [reply, setReply] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q = statusFilter === "all" ? "" : `?status=${statusFilter}`;
      const r = await api<any>(`/coach/client-issues${q}`);
      setIssues(r.issues || []);
      setCounts(r.counts || {});
    } catch (e: any) {
      toast(`Couldn't load — ${e?.message || "please retry"}`, "error");
    } finally {
      setLoading(false); setRefreshing(false);
    }
  }, [statusFilter]);
  useEffect(() => { load(); }, [load]);

  const openDetail = async (i: Issue) => {
    try {
      const r = await api<any>(`/coach/client-issues/${i.id}`);
      setOpenIssue(r.issue);
      setReply(r.issue.coach_reply || "");
      setNote("");
    } catch (e: any) {
      toast(`Couldn't open — ${e?.message || "please retry"}`, "error");
    }
  };

  const setStatus = async (i: Issue, status: string) => {
    setSaving(true);
    try {
      await api(`/coach/client-issues/${i.id}`, { method: "PATCH", body: { status } });
      toast(`Status → ${STATUS_LABEL[status]}`, "success");
      await load();
      if (openIssue?.id === i.id) setOpenIssue({ ...openIssue, status });
    } catch (e: any) {
      toast(`Couldn't update — ${e?.message || ""}`, "error");
    } finally { setSaving(false); }
  };

  const saveReply = async () => {
    if (!openIssue) return;
    setSaving(true);
    try {
      await api(`/coach/client-issues/${openIssue.id}`, { method: "PATCH",
        body: { coach_reply: reply || null } });
      toast("Reply saved.", "success");
      await load();
    } catch (e: any) { toast(`Couldn't save — ${e?.message || ""}`, "error"); }
    finally { setSaving(false); }
  };

  const addNote = async () => {
    if (!openIssue || !note.trim()) return;
    setSaving(true);
    try {
      const r = await api<any>(`/coach/client-issues/${openIssue.id}`, {
        method: "PATCH", body: { internal_note: note.trim() },
      });
      setOpenIssue(r.issue);
      setNote("");
      toast("Note added.", "success");
    } catch (e: any) { toast(`Couldn't add — ${e?.message || ""}`, "error"); }
    finally { setSaving(false); }
  };

  return (
    <SafeAreaView edges={["top"]} style={{ flex: 1, backgroundColor: theme.color.bg }}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} style={styles.backBtn}>
          <Ionicons name="chevron-back" size={22} color={theme.color.textHi} />
        </Pressable>
        <Text style={styles.title}>CLIENT ISSUES</Text>
        <View style={{ width: 22 }} />
      </View>

      <ScrollView
        contentContainerStyle={styles.body}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={theme.color.brand} />}
      >
        {/* Counters */}
        <View style={styles.counterRow}>
          <View style={styles.counter}>
            <Text style={styles.counterN}>{counts?.new ?? 0}</Text>
            <Text style={styles.counterL}>NEW</Text>
          </View>
          <View style={[styles.counter, { borderColor: "#ff6b6b" }]}>
            <Text style={[styles.counterN, { color: "#ff6b6b" }]}>{counts?.blocking ?? 0}</Text>
            <Text style={[styles.counterL, { color: "#ff6b6b" }]}>BLOCKING</Text>
          </View>
        </View>

        {/* Status filter chips */}
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.filterRow}>
          {["all", ...STATUS_ORDER].map((s) => (
            <Pressable
              key={s} onPress={() => setStatusFilter(s)}
              style={[styles.filterChip, statusFilter === s && styles.filterChipOn]}
              testID={`ci-filter-${s}`}
            >
              <Text style={[styles.filterChipT, statusFilter === s && { color: theme.color.brand }]}>
                {s === "all" ? "All" : STATUS_LABEL[s]}
              </Text>
            </Pressable>
          ))}
        </ScrollView>

        {/* List */}
        {loading ? (
          <ActivityIndicator color={theme.color.brand} style={{ marginTop: 30 }} />
        ) : issues.length === 0 ? (
          <View style={styles.empty}>
            <Ionicons name="checkmark-circle-outline" size={30} color={theme.color.textDim} />
            <Text style={styles.emptyT}>No issues.</Text>
          </View>
        ) : (
          issues.map((i) => (
            <Pressable
              key={i.id} onPress={() => openDetail(i)}
              style={[styles.card, i.urgency === "blocking" && { borderColor: "#ff6b6b" }]}
              testID={`ci-row-${i.id}`}
            >
              <View style={styles.cardHead}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.cardTitle} numberOfLines={1}>
                    {i.user_name} · {CATEGORY_LABEL[i.category] || i.category}
                  </Text>
                  <Text style={styles.cardMeta} numberOfLines={2}>{i.description}</Text>
                </View>
                {i.urgency === "blocking" && (
                  <View style={styles.blockingChip}>
                    <Ionicons name="alert" size={10} color="#ff6b6b" />
                    <Text style={styles.blockingT}>BLOCKING</Text>
                  </View>
                )}
              </View>
              <View style={styles.cardFoot}>
                <Text style={styles.foot}>{STATUS_LABEL[i.status] || i.status}</Text>
                <Text style={styles.foot}>· {i.platform || "?"}</Text>
                {i.app_version && <Text style={styles.foot}>· v{i.app_version}</Text>}
                {i.screenshot_base64 && <Ionicons name="image" size={10} color={theme.color.textDim} />}
                {i.group_summary && i.group_summary.report_count > 1 && (
                  <View style={styles.groupChip}>
                    <Text style={styles.groupT}>x{i.group_summary.report_count} · {i.group_summary.clients} clients</Text>
                  </View>
                )}
              </View>
            </Pressable>
          ))
        )}
      </ScrollView>

      {/* Detail modal */}
      <Modal transparent visible={!!openIssue} animationType="slide" onRequestClose={() => setOpenIssue(null)}>
        <View style={styles.backdrop}>
          <View style={styles.sheet}>
            <View style={styles.header}>
              <Text style={styles.title}>ISSUE DETAILS</Text>
              <Pressable onPress={() => setOpenIssue(null)} style={styles.backBtn}>
                <Ionicons name="close" size={22} color={theme.color.textHi} />
              </Pressable>
            </View>
            {openIssue && (
              <ScrollView contentContainerStyle={{ padding: 16 }}>
                <Text style={styles.detailLabel}>Client</Text>
                <Text style={styles.detailVal}>{openIssue.user_name} · {openIssue.user_email}</Text>

                <Text style={styles.detailLabel}>Category</Text>
                <Text style={styles.detailVal}>{CATEGORY_LABEL[openIssue.category] || openIssue.category}</Text>

                <Text style={styles.detailLabel}>What happened</Text>
                <Text style={styles.detailVal}>{openIssue.description}</Text>

                {openIssue.what_should_happen && (
                  <>
                    <Text style={styles.detailLabel}>Expected</Text>
                    <Text style={styles.detailVal}>{openIssue.what_should_happen}</Text>
                  </>
                )}

                {openIssue.screenshot_base64 && (
                  <>
                    <Text style={styles.detailLabel}>Screenshot</Text>
                    <Image source={{ uri: openIssue.screenshot_base64 }} style={styles.shot} />
                  </>
                )}

                <Text style={styles.detailLabel}>Context</Text>
                <View style={styles.ctxBox}>
                  {openIssue.platform && <Text style={styles.ctxRow}>Platform: {openIssue.platform}</Text>}
                  {openIssue.app_version && <Text style={styles.ctxRow}>Version: {openIssue.app_version} ({openIssue.app_build || "-"})</Text>}
                  {openIssue.route && <Text style={styles.ctxRow}>Route: {openIssue.route}</Text>}
                  {openIssue.workout_id && <Text style={styles.ctxRow}>Workout: {openIssue.workout_id}</Text>}
                  {openIssue.exercise_name && <Text style={styles.ctxRow}>Exercise: {openIssue.exercise_name} ({openIssue.exercise_id})</Text>}
                  {openIssue.error_code && <Text style={styles.ctxRow}>Error code: {openIssue.error_code}</Text>}
                </View>

                <Text style={styles.detailLabel}>Change status</Text>
                <View style={styles.statusRow}>
                  {STATUS_ORDER.map((s) => (
                    <Pressable
                      key={s} onPress={() => setStatus(openIssue, s)}
                      style={[styles.statusBtn, openIssue.status === s && styles.statusBtnOn]}
                      disabled={saving}
                    >
                      <Text style={[styles.statusBtnT, openIssue.status === s && { color: theme.color.brand }]}>{STATUS_LABEL[s]}</Text>
                    </Pressable>
                  ))}
                </View>

                <Text style={styles.detailLabel}>Reply to client</Text>
                <TextInput
                  value={reply} onChangeText={setReply} multiline
                  style={styles.input} placeholder="Type your reply…"
                  placeholderTextColor={theme.color.textDim}
                />
                <Pressable onPress={saveReply} disabled={saving} style={styles.primaryBtn}>
                  <Text style={styles.primaryT}>SAVE REPLY</Text>
                </Pressable>

                <Text style={styles.detailLabel}>Internal notes</Text>
                {(openIssue.internal_notes || []).map((n, i) => (
                  <View key={i} style={styles.noteBox}>
                    <Text style={styles.noteText}>{n.text}</Text>
                    <Text style={styles.noteMeta}>{n.at}</Text>
                  </View>
                ))}
                <TextInput
                  value={note} onChangeText={setNote} multiline
                  style={styles.input} placeholder="Add an internal note…"
                  placeholderTextColor={theme.color.textDim}
                />
                <Pressable onPress={addNote} disabled={saving || !note.trim()} style={styles.primaryBtn}>
                  <Text style={styles.primaryT}>ADD NOTE</Text>
                </Pressable>

                {openIssue.group_summary && openIssue.group_summary.report_count > 1 && (
                  <>
                    <Text style={styles.detailLabel}>Grouped with</Text>
                    <Text style={styles.detailVal}>
                      {openIssue.group_summary.report_count} reports · {openIssue.group_summary.clients} clients ·
                      platforms: {(openIssue.group_summary.platforms || []).join(", ")}
                    </Text>
                  </>
                )}

                <View style={{ height: 60 }} />
              </ScrollView>
            )}
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 12, paddingVertical: 12,
    borderBottomWidth: 1, borderColor: theme.color.border,
  },
  backBtn: { padding: 4 },
  title: { color: theme.color.brand, fontWeight: "900", letterSpacing: 2, fontSize: 12 },
  body: { padding: 12 },
  counterRow: { flexDirection: "row", gap: 8, marginBottom: 12 },
  counter: {
    flex: 1, padding: 12, borderRadius: 8,
    borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface,
  },
  counterN: { color: theme.color.brand, fontSize: 22, fontWeight: "900" },
  counterL: { color: theme.color.textDim, fontSize: 11, fontWeight: "800", letterSpacing: 1.3 },
  filterRow: { flexDirection: "row", gap: 6, marginBottom: 12 },
  filterChip: {
    paddingHorizontal: 10, paddingVertical: 6, borderRadius: 5,
    borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.bg,
  },
  filterChipOn: { borderColor: theme.color.brand, backgroundColor: `${theme.color.brand}12` },
  filterChipT: { color: theme.color.textDim, fontSize: 11, fontWeight: "700" },
  empty: { alignItems: "center", padding: 30, gap: 6 },
  emptyT: { color: theme.color.textDim, fontSize: 12 },
  card: {
    backgroundColor: theme.color.surface, borderRadius: 8, padding: 12,
    marginBottom: 8, borderWidth: 1, borderColor: theme.color.border,
  },
  cardHead: { flexDirection: "row", alignItems: "flex-start", gap: 8 },
  cardTitle: { color: theme.color.textHi, fontSize: 13, fontWeight: "800" },
  cardMeta: { color: theme.color.textDim, fontSize: 12, marginTop: 3 },
  cardFoot: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 8, flexWrap: "wrap" },
  foot: { color: theme.color.textDim, fontSize: 11, fontWeight: "600" },
  blockingChip: {
    flexDirection: "row", alignItems: "center", gap: 3,
    paddingHorizontal: 6, paddingVertical: 3, borderRadius: 4,
    borderWidth: 1, borderColor: "#ff6b6b", backgroundColor: "#3a1414",
  },
  blockingT: { color: "#ff6b6b", fontSize: 11, fontWeight: "900", letterSpacing: 0.8 },
  groupChip: {
    paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
    borderWidth: 1, borderColor: theme.color.brand,
  },
  groupT: { color: theme.color.brand, fontSize: 11, fontWeight: "800" },
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.7)", justifyContent: "flex-end" },
  sheet: {
    backgroundColor: theme.color.bg,
    borderTopLeftRadius: 20, borderTopRightRadius: 20, maxHeight: "94%",
  },
  detailLabel: {
    color: theme.color.textDim, fontSize: 11, fontWeight: "800",
    letterSpacing: 1.3, marginTop: 14, marginBottom: 4,
  },
  detailVal: { color: theme.color.textHi, fontSize: 13 },
  shot: { width: "100%", height: 220, borderRadius: 8, marginTop: 4 },
  ctxBox: {
    backgroundColor: theme.color.surface, borderRadius: 6, padding: 10,
    borderWidth: 1, borderColor: theme.color.border,
  },
  ctxRow: { color: theme.color.textHi, fontSize: 11, marginBottom: 3 },
  statusRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  statusBtn: {
    paddingVertical: 6, paddingHorizontal: 10, borderRadius: 5,
    borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface,
  },
  statusBtnOn: { borderColor: theme.color.brand, backgroundColor: `${theme.color.brand}12` },
  statusBtnT: { color: theme.color.textHi, fontSize: 11, fontWeight: "700" },
  input: {
    backgroundColor: theme.color.surface, borderWidth: 1,
    borderColor: theme.color.border, borderRadius: 6,
    padding: 10, color: theme.color.textHi, fontSize: 13, minHeight: 60,
  },
  primaryBtn: {
    marginTop: 8, paddingVertical: 10, borderRadius: 6,
    backgroundColor: theme.color.brand, alignItems: "center",
  },
  primaryT: { color: "#000", fontWeight: "900", letterSpacing: 1.3, fontSize: 11 },
  noteBox: {
    backgroundColor: theme.color.surface, borderRadius: 5, padding: 8,
    marginBottom: 6, borderLeftWidth: 3, borderLeftColor: theme.color.brand,
  },
  noteText: { color: theme.color.textHi, fontSize: 12 },
  noteMeta: { color: theme.color.textDim, fontSize: 11, marginTop: 3 },
});
