import { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, RefreshControl, ActivityIndicator, Alert } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme, loadColor } from "@/src/lib/theme";
import { ProfileAvatar } from "@/src/components/ProfileAvatar";
import { PreviewClientButton } from "@/src/components/PreviewLauncher";
import { useAuth } from "@/src/lib/auth";
import { usePreview } from "@/src/lib/preview";
import { confirm as uxConfirm, toast as uxToast } from "@/src/lib/ux";

const FILTERS = [
  { key: "all", label: "ALL" },
  { key: "needs_review", label: "NEEDS REVIEW" },
  { key: "profile_incomplete", label: "PROFILE GAP" },
  { key: "expiring_soon", label: "EXPIRING" },
  { key: "expired", label: "EXPIRED" },
  { key: "no_roster", label: "NO ROSTER" },
  { key: "needs_confirmation", label: "NEEDS CONFIRM" },
  { key: "pending_approval", label: "PENDING" },
  { key: "red_days", label: "RED DAYS" },
  { key: "missed", label: "MISSED" },
];

export default function Clients() {
  const router = useRouter();
  const { user } = useAuth();
  const { enterSandbox, resetSandbox } = usePreview();
  const [filter, setFilter] = useState("all");
  const [showArchived, setShowArchived] = useState(false);
  const [data, setData] = useState<any>({ clients: [], counts: {}, total: 0, preview_sandbox: null });
  const [loading, setLoading] = useState(true);
  const [previewBusy, setPreviewBusy] = useState<null | "start" | "reset">(null);

  const isAdmin = !!(
    user?.is_admin ||
    user?.role === "admin" ||
    (user as any)?.coach_tier === "admin" ||
    (user as any)?.is_primary_coach ||
    (user?.email || "").toLowerCase().endsWith("@crewfit.net")
  );

  const quickArchive = async (client: any, e?: any) => {
    e?.stopPropagation?.();
    const ok = await uxConfirm({
      title: `Archive ${client.name}?`,
      message: "Removes from active list. Data preserved. Can be restored later.",
      confirmLabel: "Archive",
      cancelLabel: "Cancel",
    });
    if (!ok) return;
    try {
      await api(`/admin/clients/${client.id}/archive`, { method: "POST", body: { mode: "archive_only" } });
      uxToast(`${client.name} archived`, "success");
      await load();
    } catch (err: any) {
      uxToast(`Archive failed: ${err?.message || "try again"}`, "error");
    }
  };

  const quickRestore = async (client: any, e?: any) => {
    e?.stopPropagation?.();
    try {
      await api(`/admin/clients/${client.id}/restore`, { method: "POST", body: {} });
      uxToast(`${client.name} restored`, "success");
      await load();
    } catch (err: any) {
      uxToast(`Restore failed: ${err?.message || "try again"}`, "error");
    }
  };

  const quickDelete = async (client: any, e?: any) => {
    e?.stopPropagation?.();
    const ok = await uxConfirm({
      title: `Delete ${client.name}?`,
      message: "Disables login and removes from active dashboard. Data kept temporarily unless permanently deleted.",
      confirmLabel: "Delete",
      cancelLabel: "Cancel",
      destructive: true,
    });
    if (!ok) return;
    try {
      await api(`/admin/clients/${client.id}/soft-delete`, { method: "POST", body: {} });
      uxToast(`${client.name} deleted`, "success");
      await load();
    } catch (err: any) {
      uxToast(`Delete failed: ${err?.message || "try again"}`, "error");
    }
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const url = showArchived
        ? `/coach/dashboard?filter=${filter}&include_archived=true`
        : `/coach/dashboard?filter=${filter}`;
      const res = await api<any>(url);
      // When showing archived, keep only non-active statuses.
      if (showArchived && res?.clients) {
        res.clients = res.clients.filter((c: any) => c.status && c.status !== "active");
        res.total = res.clients.length;
      }
      setData(res);
    } catch (e: any) {
      const msg = String(e?.message || "");
      if (/missing token|not authenticated|invalid token/i.test(msg)) {
        router.replace("/(auth)/login" as any);
        return;
      }
      console.warn("clients load failed:", msg);
    } finally {
      setLoading(false);
    }
  }, [filter, showArchived, router]);
  useFocusEffect(useCallback(() => { load(); }, [load]));
  // Slice 3 fix: useFocusEffect only re-runs on screen focus, not when deps
  // change while focused. Trigger a reload whenever filter / showArchived
  // change so the chip clicks actually narrow the list.
  useEffect(() => { load(); }, [filter, showArchived]);

  const c = data.counts || {};

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>CLIENTS</Text>
          <Text style={styles.sub}>{data.total || 0} {showArchived ? "archived" : "active"}</Text>
        </View>
        <Pressable
          testID="toggle-archived"
          onPress={() => setShowArchived((v) => !v)}
          style={[styles.archivedToggle, showArchived && { backgroundColor: theme.color.brand, borderColor: theme.color.brand }]}
        >
          <Ionicons name="archive" size={12} color={showArchived ? "#fff" : theme.color.textMuted} />
          <Text style={[styles.archivedToggleText, showArchived && { color: "#fff" }]}>
            {showArchived ? "SHOWING ARCHIVED" : "ARCHIVED"}
          </Text>
        </Pressable>
      </View>

      <View style={styles.widgets}>
        <Widget dotColor={theme.color.green} label="Active" value={Math.max(0, (data.total || 0) - Math.max(c.expired || 0, c.no_roster || 0))} />
        <Widget dotColor={theme.color.amber} label="Expiring" value={c.expiring_soon || 0} tint={theme.color.amber} />
        <Widget dotColor={theme.color.red}   label="Expired"  value={c.expired || 0} tint={theme.color.red} />
        <Widget dotColor={theme.color.textDim} label="No Roster" value={c.no_roster || 0} />
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.filtersRow}>
        {FILTERS.map((f) => (
          <Pressable key={f.key} testID={`filter-${f.key}`} onPress={() => setFilter(f.key)} style={[styles.chip, filter === f.key && styles.chipActive]}>
            <Text style={[styles.chipText, filter === f.key && { color: "#fff" }]}>{f.label}</Text>
            {c[f.key] !== undefined && f.key !== "all" && <Text style={[styles.chipCount, filter === f.key && { color: "#fff" }]}> {c[f.key]}</Text>}
          </Pressable>
        ))}
      </ScrollView>

      <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 60 }} refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}>
        {/* Admin quick-actions: Manage Coaches + New Client Preview sandbox */}
        {isAdmin ? (
          <View style={styles.adminBar} testID="admin-quick-actions">
            <Pressable
              testID="cl-manage-coaches"
              onPress={() => router.push("/coach/admin/coaches" as any)}
              style={styles.adminBtn}
            >
              <Ionicons name="people" size={14} color={theme.color.brand} />
              <Text style={styles.adminBtnT}>MANAGE COACHES</Text>
            </Pressable>
            <Pressable
              testID="cl-audit-log"
              onPress={() => router.push("/(coach)/changelog" as any)}
              style={styles.adminBtn}
            >
              <Ionicons name="document-text" size={14} color={theme.color.brand} />
              <Text style={styles.adminBtnT}>AUDIT LOG</Text>
            </Pressable>
          </View>
        ) : null}

        {/* Persistent preview sandbox card — pinned above real clients */}
        {isAdmin ? (
          <View style={styles.previewCard} testID="preview-sandbox-card">
            <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
              <View style={styles.previewBadge}>
                <Ionicons name="flask" size={16} color="#fff" />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.previewName}>New Client Preview</Text>
                <Text style={styles.previewSub}>
                  Sandbox client · resettable · isolated from real client metrics
                </Text>
                {data.preview_sandbox ? (
                  <Text style={styles.previewMeta} numberOfLines={1}>
                    {data.preview_sandbox.programme_pill?.goal_label ? `${data.preview_sandbox.programme_pill.goal_label} · ` : ""}
                    {data.preview_sandbox.email || "preview@crewfit.test"}
                  </Text>
                ) : (
                  <Text style={styles.previewMeta}>Tap START PREVIEW to seed and enter.</Text>
                )}
              </View>
            </View>
            <View style={styles.previewActions}>
              <Pressable
                testID="preview-sandbox-start"
                disabled={previewBusy !== null}
                onPress={async () => {
                  setPreviewBusy("start");
                  try {
                    await enterSandbox();
                    router.replace("/" as any);
                  } catch (e: any) {
                    Alert.alert("Preview failed", e?.message || "Try again.");
                  } finally { setPreviewBusy(null); }
                }}
                style={[styles.previewBtn, previewBusy === "start" && { opacity: 0.6 }]}
              >
                {previewBusy === "start" ? <ActivityIndicator color="#fff" /> : (
                  <>
                    <Ionicons name="play" size={13} color="#fff" />
                    <Text style={styles.previewBtnT}>START PREVIEW</Text>
                  </>
                )}
              </Pressable>
              <Pressable
                testID="preview-sandbox-reset-start"
                disabled={previewBusy !== null}
                onPress={async () => {
                  setPreviewBusy("reset");
                  try {
                    await resetSandbox();
                    await enterSandbox();
                    router.replace("/" as any);
                  } catch (e: any) {
                    Alert.alert("Reset failed", e?.message || "Try again.");
                  } finally { setPreviewBusy(null); }
                }}
                style={[styles.previewBtnAlt, previewBusy === "reset" && { opacity: 0.6 }]}
              >
                {previewBusy === "reset" ? <ActivityIndicator color={theme.color.brand} /> : (
                  <>
                    <Ionicons name="refresh" size={13} color={theme.color.brand} />
                    <Text style={styles.previewBtnAltT}>RESET & START</Text>
                  </>
                )}
              </Pressable>
              {data.preview_sandbox?.id ? (
                <Pressable
                  testID="preview-sandbox-open-detail"
                  onPress={() => router.push(`/coach/client/${data.preview_sandbox.id}` as any)}
                  style={styles.previewBtnAlt}
                >
                  <Ionicons name="open-outline" size={13} color={theme.color.brand} />
                  <Text style={styles.previewBtnAltT}>DETAIL</Text>
                </Pressable>
              ) : null}
            </View>
          </View>
        ) : null}

        {loading && data.clients.length === 0 ? <ActivityIndicator color={theme.color.brand} /> :
          data.clients.length === 0 ? <Text style={{ color: theme.color.textMuted, textAlign: "center", marginTop: 40 }}>No clients in this bucket.</Text> :
          data.clients.map((cl: any) => {
            const days = cl.latest_roster?.days || [];
            const exp = cl.roster_expiry || {};
            return (
              <Pressable key={cl.id} testID={`client-card-${cl.id}`} onPress={() => router.push(`/coach/client/${cl.id}`)} style={styles.card}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
                  <ProfileAvatar userId={cl.id} name={cl.name} photoUrl={cl.profile_photo_url || null} size={44} ring={false} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.name}>{cl.name}</Text>
                    {cl.profile?.job_title || cl.profile?.airline ? (
                      <Text style={styles.roleLine} numberOfLines={1}>
                        {cl.profile?.job_title || "Crew"}
                        {cl.profile?.airline ? ` · ${cl.profile.airline}` : ""}
                      </Text>
                    ) : null}
                    {cl.profile?.home_base || cl.current_location_city ? (
                      <Text style={styles.locLine} numberOfLines={1}>
                        {cl.profile?.home_base ? String(cl.profile.home_base).toUpperCase() : ""}
                        {cl.profile?.route_focus ? `  ·  ${String(cl.profile.route_focus).replace("_", " ").toUpperCase()}` : ""}
                        {cl.current_location_city ? `  ·  in ${cl.current_location_city}` : ""}
                      </Text>
                    ) : (
                      <Text style={styles.email} numberOfLines={1}>{cl.email}</Text>
                    )}
                    {cl.assigned_coach_name && cl.assigned_coach_name !== "Louis Hall" ? (
                      <Text style={styles.locLine} numberOfLines={1}>Coach · {cl.assigned_coach_name}</Text>
                    ) : null}
                  </View>
                  <View style={{ alignItems: "flex-end", gap: 4 }}>
                    {cl.pending_approvals > 0 && (
                      <View style={styles.pendingPill}><Text style={styles.pendingText}>{cl.pending_approvals} PENDING</Text></View>
                    )}
                    {exp.expired && <View style={[styles.pendingPill, { backgroundColor: theme.color.red }]}><Text style={styles.pendingText}>EXPIRED</Text></View>}
                    {!exp.expired && exp.coverage === "critical" && <View style={[styles.pendingPill, { backgroundColor: theme.color.amber }]}><Text style={styles.pendingText}>{exp.days_remaining}D LEFT</Text></View>}
                  </View>
                </View>
                {cl.programme_pill ? (
                  <View style={styles.progPillRow}>
                    <View style={[styles.progPill, cl.programme_pill.validation_status === "needs_review" && !cl.programme_pill.coach_approved && styles.progPillReview]}>
                      <Text style={styles.progPillText} numberOfLines={1}>
                        {(cl.programme_pill.goal_label || "Programme").toUpperCase()}
                        {cl.programme_pill.phase_label ? ` · ${cl.programme_pill.phase_label}` : ""}
                        {cl.programme_pill.week_index ? ` · WK ${cl.programme_pill.week_index}` : ""}
                        {cl.programme_pill.target_sessions_per_week ? ` · ${cl.programme_pill.target_sessions_per_week}×/WK` : ""}
                      </Text>
                    </View>
                    {cl.programme_pill.validation_status === "needs_review" && !cl.programme_pill.coach_approved ? (
                      <Text style={styles.progFlag}>NEEDS REVIEW</Text>
                    ) : cl.programme_pill.coach_approved ? (
                      <Text style={styles.progOk}>APPROVED</Text>
                    ) : null}
                  </View>
                ) : null}
                {cl.profile_incomplete_pill ? (
                  <View style={styles.incompleteRow} testID={`profile-incomplete-${cl.id}`}>
                    <Ionicons name="warning" size={12} color="#a06400" />
                    <Text style={styles.incompleteText} numberOfLines={1}>
                      PROFILE INCOMPLETE · {cl.profile_incomplete_pill.missing_count} MISSING
                      {cl.profile_incomplete_pill.friendly_labels?.length
                        ? ` · ${cl.profile_incomplete_pill.friendly_labels.slice(0, 2).join(", ")}${cl.profile_incomplete_pill.missing_count > 2 ? "…" : ""}`
                        : ""}
                    </Text>
                  </View>
                ) : null}
                {days.length > 0 && (
                  <View style={styles.loadRow}>
                    {days.slice(0, 14).map((d: any, i: number) => (
                      <View key={i} style={[styles.loadBlock, { backgroundColor: loadColor(d.load) }]} />
                    ))}
                    <Text style={styles.rosterText}>{cl.latest_roster?.start_date} → {cl.latest_roster?.end_date}</Text>
                  </View>
                )}
                <View style={styles.actionRow}>
                  <Text style={styles.metaSmall}>{cl.missed_workouts > 0 ? `${cl.missed_workouts} missed` : ""}</Text>
                  <View style={{ flexDirection: "row", gap: 8, alignItems: "center" }}>
                    <PreviewClientButton clientId={cl.id} clientName={cl.name} />
                    {isAdmin ? (
                      <>
                        {showArchived || cl.status === "archived" || cl.status === "paused" || cl.status === "deletion_pending" ? (
                          <Pressable
                            testID={`quick-restore-${cl.id}`}
                            onPress={(e) => quickRestore(cl, e)}
                            style={styles.rowIconBtn}
                            hitSlop={8}
                          >
                            <Ionicons name="refresh" size={15} color={theme.color.brand} />
                          </Pressable>
                        ) : (
                          <Pressable
                            testID={`quick-archive-${cl.id}`}
                            onPress={(e) => quickArchive(cl, e)}
                            style={styles.rowIconBtn}
                            hitSlop={8}
                          >
                            <Ionicons name="archive" size={15} color={theme.color.textMuted} />
                          </Pressable>
                        )}
                        <Pressable
                          testID={`quick-delete-${cl.id}`}
                          onPress={(e) => quickDelete(cl, e)}
                          style={styles.rowIconBtn}
                          hitSlop={8}
                        >
                          <Ionicons name="trash" size={15} color="#c85450" />
                        </Pressable>
                      </>
                    ) : null}
                    <Text style={styles.action}>REVIEW →</Text>
                  </View>
                </View>
              </Pressable>
            );
          })
        }
      </ScrollView>
    </SafeAreaView>
  );
}

function Widget({ dotColor, label, value, tint }: any) {
  return (
    <View style={styles.widget}>
      <View style={[styles.wDot, { backgroundColor: dotColor || theme.color.textDim }]} />
      <View>
        <Text style={[styles.wVal, tint && { color: tint }]}>{value}</Text>
        <Text style={styles.wLabel}>{label}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.divider, flexDirection: "row", alignItems: "center", gap: 12 },
  title: { color: theme.color.text, fontSize: 22, fontWeight: "900", letterSpacing: 2 },
  archivedToggle: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 6, borderRadius: theme.radius.pill, borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface2 },
  archivedToggleText: { color: theme.color.textMuted, fontSize: 10, fontWeight: "800", letterSpacing: 1 },
  sub: { color: theme.color.textMuted, marginTop: 2 },
  widgets: { flexDirection: "row", padding: theme.space.md, gap: theme.space.sm },
  widget: { flex: 1, flexDirection: "row", alignItems: "center", gap: 8, padding: 10, borderRadius: theme.radius.md, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  wIcon: { fontSize: 16 },
  wDot: { width: 10, height: 10, borderRadius: 5 },
  wVal: { color: theme.color.text, fontSize: 20, fontWeight: "900", fontFamily: theme.font.display },
  wLabel: { color: theme.color.textDim, fontSize: 9, letterSpacing: 1, fontWeight: "700", fontFamily: theme.font.textSemi },
  roleLine: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700", letterSpacing: 0.5, marginTop: 1, fontFamily: theme.font.text },
  locLine: { color: theme.color.textDim, fontSize: 10, letterSpacing: 1, fontWeight: "800", marginTop: 2, fontFamily: theme.font.textSemi },
  filtersRow: { paddingHorizontal: theme.space.lg, paddingBottom: theme.space.sm, gap: 6 },
  chip: { flexDirection: "row", paddingHorizontal: 12, paddingVertical: 6, borderRadius: theme.radius.pill, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, flexShrink: 0 },
  chipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipText: { color: theme.color.textMuted, fontSize: 10, fontWeight: "800", letterSpacing: 1 },
  chipCount: { color: theme.color.brand, fontSize: 10, fontWeight: "800" },
  card: { padding: theme.space.md, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, marginBottom: theme.space.sm },
  name: { color: theme.color.text, fontSize: 16, fontWeight: "800" },
  email: { color: theme.color.textMuted, fontSize: 12, marginTop: 2 },
  pendingPill: { backgroundColor: theme.color.brand, paddingHorizontal: 8, paddingVertical: 3, borderRadius: theme.radius.sm },
  pendingText: { color: "#fff", fontSize: 9, letterSpacing: 1.5, fontWeight: "800" },
  loadRow: { flexDirection: "row", gap: 3, marginTop: 10, alignItems: "center" },
  loadBlock: { flex: 1, height: 6, borderRadius: 2 },
  rosterText: { color: theme.color.textDim, fontSize: 9, letterSpacing: 0.5, marginLeft: 6, fontWeight: "700" },
  actionRow: { marginTop: 8, borderTopWidth: 1, borderTopColor: theme.color.divider, paddingTop: 8, flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  metaSmall: { color: theme.color.amber, fontSize: 10, fontWeight: "700", letterSpacing: 1 },
  action: { color: theme.color.brand, letterSpacing: 2, fontWeight: "800", fontSize: 11 },
  progPillRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 8 },
  incompleteRow: {
    flexDirection: "row", alignItems: "center", gap: 6, marginTop: 6,
    paddingHorizontal: 8, paddingVertical: 5, borderRadius: theme.radius.sm,
    backgroundColor: "rgba(229,163,55,0.10)", borderWidth: 1, borderColor: "rgba(229,163,55,0.55)",
  },
  incompleteText: { color: "#a06400", fontSize: 10, fontWeight: "800", letterSpacing: 0.6, flex: 1 },
  progPill: {
    flex: 1, backgroundColor: theme.color.brandTint || "rgba(59,130,246,0.08)",
    borderWidth: 1, borderColor: theme.color.brand,
    paddingHorizontal: 8, paddingVertical: 4, borderRadius: theme.radius.sm,
  },
  progPillReview: { borderColor: theme.color.amber, backgroundColor: "rgba(229,163,55,0.08)" },
  progPillText: { color: theme.color.text, fontSize: 10, fontWeight: "800", letterSpacing: 0.8 },
  progFlag: { color: theme.color.amber, fontSize: 9, fontWeight: "800", letterSpacing: 1 },
  progOk: { color: theme.color.green, fontSize: 9, fontWeight: "800", letterSpacing: 1 },
  // Admin bar + preview sandbox card
  adminBar: { flexDirection: "row", gap: 8, marginBottom: 12, flexWrap: "wrap" },
  adminBtn: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 8, borderRadius: theme.radius.md, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.brand },
  adminBtnT: { color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 1.2 },
  previewCard: { padding: 14, backgroundColor: theme.color.brandTint || "rgba(59,130,246,0.08)", borderWidth: 1, borderColor: theme.color.brand, borderRadius: theme.radius.md, marginBottom: 14 },
  previewBadge: { width: 36, height: 36, borderRadius: 18, backgroundColor: theme.color.brand, alignItems: "center", justifyContent: "center" },
  previewName: { color: theme.color.text, fontSize: 15, fontWeight: "900" },
  previewSub: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },
  previewMeta: { color: theme.color.textDim, fontSize: 10, marginTop: 4, fontWeight: "700", letterSpacing: 0.5 },
  previewActions: { flexDirection: "row", gap: 8, marginTop: 12, flexWrap: "wrap" },
  previewBtn: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 10, borderRadius: theme.radius.md, backgroundColor: theme.color.brand },
  previewBtnT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.2 },
  previewBtnAlt: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 10, borderRadius: theme.radius.md, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.brand },
  previewBtnAltT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.2 },
  rowIconBtn: { padding: 6, borderRadius: 6, backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border },
});
