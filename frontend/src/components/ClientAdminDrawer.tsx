/**
 * ClientAdminDrawer — narrow bottom sheet for true administration.
 *
 * Iter 128e — replaces navigating to the legacy /coach/client/{id}.tsx page
 * with a compact drawer opened from the canonical workspace ADMIN button.
 *
 * Contents (nothing more):
 *  - Account: Reset password
 *  - Coach: Assigned coach (with Change) + Manage Coaches shortcut
 *  - Client status: Archive / Restore
 *  - Danger zone: Delete client (soft) / Permanent delete
 *
 * All handlers use existing backend endpoints. No new APIs.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, Modal, Pressable, TextInput, Alert, ActivityIndicator, ScrollView } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type ClientAdminData = {
  id: string;
  name: string;
  email: string;
  status?: string;
  archived?: boolean;
  assigned_coach?: { id: string; name: string } | null;
};

export function ClientAdminDrawer({
  visible, onClose, clientId,
}: {
  visible: boolean;
  onClose: () => void;
  clientId: string;
}) {
  const router = useRouter();
  const [data, setData] = useState<ClientAdminData | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmPerm, setConfirmPerm] = useState(false);
  const [confirmEmail, setConfirmEmail] = useState("");
  const [permText, setPermText] = useState("");
  // Iter 130a — inline password reset (Android + iOS + Web parity;
  // Alert.prompt is iOS-only and left Android coaches stuck).
  const [confirmReset, setConfirmReset] = useState(false);
  const [resetPw, setResetPw] = useState("");
  const [resetPwShow, setResetPwShow] = useState(false);

  const load = useCallback(async () => {
    if (!clientId) return;
    setLoading(true);
    try {
      const r = await api<ClientAdminData>(`/admin/clients/${clientId}`);
      setData(r);
    } catch (e: any) {
      Alert.alert("Load failed", e?.message || "Try again.");
    } finally { setLoading(false); }
  }, [clientId]);

  useEffect(() => { if (visible) load(); }, [visible, load]);

  const doResetPassword = useCallback(() => {
    // Cross-platform inline flow. Alert.prompt is iOS-only, so on Android
    // the previous branch just told coaches "not supported here" — this
    // opens an in-drawer modal with a TextInput that works everywhere.
    setResetPw("");
    setResetPwShow(false);
    setConfirmReset(true);
  }, []);

  const runResetPassword = useCallback(async (newPassword: string) => {
    setBusy("reset-password");
    try {
      const res: any = await api(`/coach/clients/${clientId}/reset-password`, { method: "POST", body: { new_password: newPassword } });
      setConfirmReset(false); setResetPw(""); setResetPwShow(false);
      const matched = Number(res?.matched_rows || 1);
      const dupNote = matched > 1
        ? `\n\n(We also synced ${matched - 1} duplicate account row${matched - 1 === 1 ? "" : "s"} sharing this email so login works reliably.)`
        : "";
      Alert.alert(
        "Password reset",
        `New password is active for ${data?.email}. Ask them to sign in again.${dupNote}`
      );
    } catch (e: any) {
      Alert.alert("Reset failed", e?.message || "Try again.");
    } finally { setBusy(null); }
  }, [clientId, data]);

  const doArchive = useCallback(async () => {
    setBusy("archive");
    try {
      await api(`/admin/clients/${clientId}/archive`, { method: "POST", body: {} });
      Alert.alert("Archived", `${data?.name} has been archived.`);
      await load();
    } catch (e: any) { Alert.alert("Archive failed", e?.message || ""); }
    finally { setBusy(null); }
  }, [clientId, data, load]);

  const doRestore = useCallback(async () => {
    setBusy("restore");
    try {
      await api(`/admin/clients/${clientId}/restore`, { method: "POST", body: {} });
      Alert.alert("Restored", `${data?.name} is active again.`);
      await load();
    } catch (e: any) { Alert.alert("Restore failed", e?.message || ""); }
    finally { setBusy(null); }
  }, [clientId, data, load]);

  const doSoftDelete = useCallback(async () => {
    if ((confirmEmail || "").trim().toLowerCase() !== (data?.email || "").toLowerCase()) {
      Alert.alert("Email doesn't match", "Type the client's exact email to confirm.");
      return;
    }
    setBusy("delete");
    try {
      await api(`/admin/clients/${clientId}/soft-delete`, { method: "POST", body: {} });
      Alert.alert("Deleted", `${data?.name} has been deleted. This can be restored.`);
      setConfirmDelete(false); setConfirmEmail("");
      onClose();
    } catch (e: any) { Alert.alert("Delete failed", e?.message || ""); }
    finally { setBusy(null); }
  }, [clientId, data, confirmEmail, onClose]);

  const doPermanentDelete = useCallback(async () => {
    if ((permText || "").trim() !== "DELETE") {
      Alert.alert("Confirmation required", 'Type "DELETE" exactly to confirm permanent deletion.');
      return;
    }
    setBusy("perm-delete");
    try {
      await api(`/admin/clients/${clientId}/permanent-delete`, { method: "POST", body: {} });
      Alert.alert("Permanently deleted", `${data?.name} and all their data have been permanently deleted.`);
      setConfirmPerm(false); setPermText("");
      onClose();
    } catch (e: any) { Alert.alert("Delete failed", e?.message || ""); }
    finally { setBusy(null); }
  }, [clientId, data, permText, onClose]);

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <Pressable style={styles.backdropDim} onPress={onClose} />
        <View style={styles.sheet}>
          <View style={styles.grabber} />
          <View style={styles.header}>
            <View style={{ flex: 1 }}>
              <Text style={styles.eyebrow}>CLIENT ADMINISTRATION</Text>
              <Text style={styles.name} numberOfLines={1}>{data?.name || "…"}</Text>
              <Text style={styles.email} numberOfLines={1}>{data?.email || " "}</Text>
            </View>
            <Pressable onPress={onClose} hitSlop={12} testID="admin-drawer-close">
              <Ionicons name="close" size={22} color={theme.color.textMuted} />
            </Pressable>
          </View>

          {loading ? (
            <View style={styles.loading}><ActivityIndicator color={theme.color.brand} /></View>
          ) : (
            <ScrollView contentContainerStyle={styles.body} showsVerticalScrollIndicator={false}>
              {/* ACCOUNT */}
              <Text style={styles.section}>ACCOUNT</Text>
              <Row
                icon="key-outline"
                label="Reset password"
                sub="Set a new password on this client's account."
                busy={busy === "reset-password"}
                onPress={doResetPassword}
                testID="admin-drawer-reset-password"
              />

              {/* COACH */}
              <Text style={[styles.section, { marginTop: 20 }]}>COACH</Text>
              <View style={styles.assignRow}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.assignLabel}>Assigned coach</Text>
                  <Text style={styles.assignValue}>{data?.assigned_coach?.name || "— unassigned —"}</Text>
                </View>
                <Pressable
                  onPress={() => { onClose(); router.push("/coach/admin/coaches" as any); }}
                  style={styles.smallBtn}
                  testID="admin-drawer-manage-coaches"
                >
                  <Text style={styles.smallBtnText}>Manage</Text>
                </Pressable>
              </View>

              {/* CLIENT STATUS */}
              <Text style={[styles.section, { marginTop: 20 }]}>CLIENT STATUS</Text>
              {data?.archived || data?.status === "archived" ? (
                <Row icon="refresh" label="Restore client" sub="Bring this client back into active coaching." busy={busy === "restore"} onPress={doRestore} testID="admin-drawer-restore" />
              ) : (
                <Row icon="archive-outline" label="Archive client" sub="Pause programme, hide from active lists. Reversible." busy={busy === "archive"} onPress={doArchive} testID="admin-drawer-archive" />
              )}

              {/* DANGER */}
              <Text style={[styles.section, { marginTop: 20, color: "#ff6b6b" }]}>DANGER ZONE</Text>
              <Row icon="trash-outline" label="Delete client" sub="Deletes the client and their data. Can be restored by an admin." danger onPress={() => setConfirmDelete(true)} testID="admin-drawer-delete" />
              <Row icon="alert-circle-outline" label="Permanent delete" sub="Irreversible removal of the client and every record they own." danger onPress={() => setConfirmPerm(true)} testID="admin-drawer-perm-delete" />

              <View style={{ height: 40 }} />
            </ScrollView>
          )}

          {/* Confirm modals */}
          {confirmDelete && (
            <View style={styles.confirmBackdrop}>
              <View style={styles.confirmCard}>
                <Text style={styles.confirmTitle}>Delete client</Text>
                <Text style={styles.confirmBody}>Type the client&apos;s email to confirm:</Text>
                <Text style={styles.confirmHint}>{data?.email}</Text>
                <TextInput value={confirmEmail} onChangeText={setConfirmEmail} autoCapitalize="none" keyboardType="email-address" style={styles.confirmInput} placeholder="client@example.com" placeholderTextColor="#666" testID="admin-drawer-delete-email" />
                <View style={styles.confirmRow}>
                  <Pressable onPress={() => { setConfirmDelete(false); setConfirmEmail(""); }} style={styles.ghostBtn}><Text style={styles.ghostBtnText}>Cancel</Text></Pressable>
                  <Pressable onPress={doSoftDelete} disabled={busy === "delete"} style={styles.dangerBtn} testID="admin-drawer-delete-confirm"><Text style={styles.dangerBtnText}>{busy === "delete" ? "Deleting…" : "Delete"}</Text></Pressable>
                </View>
              </View>
            </View>
          )}
          {confirmPerm && (
            <View style={styles.confirmBackdrop}>
              <View style={styles.confirmCard}>
                <Text style={styles.confirmTitle}>Permanently delete</Text>
                <Text style={styles.confirmBody}>This CANNOT be undone. Type DELETE to confirm:</Text>
                <TextInput value={permText} onChangeText={setPermText} autoCapitalize="characters" style={styles.confirmInput} placeholder="DELETE" placeholderTextColor="#666" testID="admin-drawer-perm-input" />
                <View style={styles.confirmRow}>
                  <Pressable onPress={() => { setConfirmPerm(false); setPermText(""); }} style={styles.ghostBtn}><Text style={styles.ghostBtnText}>Cancel</Text></Pressable>
                  <Pressable onPress={doPermanentDelete} disabled={busy === "perm-delete"} style={styles.dangerBtn} testID="admin-drawer-perm-confirm"><Text style={styles.dangerBtnText}>{busy === "perm-delete" ? "Deleting…" : "PERMANENT DELETE"}</Text></Pressable>
                </View>
              </View>
            </View>
          )}
          {confirmReset && (
            <View style={styles.confirmBackdrop}>
              <View style={styles.confirmCard}>
                <Text style={styles.confirmTitle}>Reset password</Text>
                <Text style={styles.confirmBody}>
                  Set a new password for {data?.email}. They&apos;ll use this to sign in.
                  Minimum 6 characters.
                </Text>
                <View style={styles.pwRow}>
                  <TextInput
                    value={resetPw}
                    onChangeText={setResetPw}
                    autoCapitalize="none"
                    autoCorrect={false}
                    secureTextEntry={!resetPwShow}
                    style={[styles.confirmInput, { flex: 1, marginTop: 0 }]}
                    placeholder="New password"
                    placeholderTextColor="#666"
                    testID="admin-drawer-reset-input"
                  />
                  <Pressable onPress={() => setResetPwShow(v => !v)} style={styles.eyeBtn} hitSlop={8} testID="admin-drawer-reset-toggle-visibility">
                    <Ionicons name={resetPwShow ? "eye-off" : "eye"} size={18} color={theme.color.textDim} />
                  </Pressable>
                </View>
                {resetPw.length > 0 && resetPw.length < 6 ? (
                  <Text style={styles.pwHint}>Password must be at least 6 characters.</Text>
                ) : null}
                <View style={styles.confirmRow}>
                  <Pressable onPress={() => { setConfirmReset(false); setResetPw(""); setResetPwShow(false); }} style={styles.ghostBtn}><Text style={styles.ghostBtnText}>Cancel</Text></Pressable>
                  <Pressable
                    onPress={() => { if (resetPw.length >= 6) runResetPassword(resetPw); }}
                    disabled={busy === "reset-password" || resetPw.length < 6}
                    style={[styles.primaryBtn, (busy === "reset-password" || resetPw.length < 6) && { opacity: 0.5 }]}
                    testID="admin-drawer-reset-confirm"
                  >
                    <Text style={styles.primaryBtnText}>{busy === "reset-password" ? "Resetting…" : "Reset"}</Text>
                  </Pressable>
                </View>
              </View>
            </View>
          )}
        </View>
      </View>
    </Modal>
  );
}

function Row({ icon, label, sub, onPress, busy, danger, testID }: {
  icon: any; label: string; sub: string; onPress: () => void; busy?: boolean; danger?: boolean; testID?: string;
}) {
  return (
    <Pressable onPress={onPress} disabled={busy} style={[styles.row, danger && styles.rowDanger, busy && { opacity: 0.5 }]} testID={testID}>
      <Ionicons name={icon} size={18} color={danger ? "#ff6b6b" : theme.color.textHi} />
      <View style={{ flex: 1 }}>
        <Text style={[styles.rowLabel, danger && { color: "#ff6b6b" }]}>{label}</Text>
        <Text style={styles.rowSub}>{sub}</Text>
      </View>
      {busy ? <ActivityIndicator size="small" color={theme.color.brand} /> : <Ionicons name="chevron-forward" size={16} color={theme.color.textDim} />}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, justifyContent: "flex-end" },
  backdropDim: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.6)" },
  sheet: { backgroundColor: theme.color.surface, borderTopLeftRadius: 18, borderTopRightRadius: 18, maxHeight: "88%", paddingBottom: 24, borderTopWidth: 1, borderColor: theme.color.border },
  grabber: { alignSelf: "center", width: 36, height: 4, borderRadius: 2, backgroundColor: theme.color.border, marginTop: 8, marginBottom: 12 },
  header: { flexDirection: "row", alignItems: "center", paddingHorizontal: 20, paddingBottom: 12, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  eyebrow: { color: theme.color.textDim, fontSize: 10, letterSpacing: 1.4, fontWeight: "800" },
  name: { color: theme.color.text, fontSize: 18, fontWeight: "800", marginTop: 2 },
  email: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  body: { paddingHorizontal: 20, paddingTop: 16 },
  section: { color: theme.color.textDim, fontSize: 10, letterSpacing: 1.6, fontWeight: "800", marginBottom: 8 },
  row: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: theme.color.surface2, padding: 14, borderRadius: 10, borderWidth: 1, borderColor: theme.color.border, marginBottom: 8 },
  rowDanger: { borderColor: "rgba(255,107,107,0.25)" },
  rowLabel: { color: theme.color.text, fontSize: 14, fontWeight: "700" },
  rowSub: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },
  assignRow: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: theme.color.surface2, padding: 14, borderRadius: 10, borderWidth: 1, borderColor: theme.color.border, marginBottom: 8 },
  assignLabel: { color: theme.color.textDim, fontSize: 10, letterSpacing: 1.3, fontWeight: "800" },
  assignValue: { color: theme.color.text, fontSize: 14, fontWeight: "700", marginTop: 2 },
  smallBtn: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 6, backgroundColor: theme.color.brand },
  smallBtnText: { color: "#000", fontSize: 11, fontWeight: "800", letterSpacing: 1 },
  loading: { padding: 40, alignItems: "center" },
  confirmBackdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.75)", justifyContent: "center", padding: 20 },
  confirmCard: { backgroundColor: theme.color.surface2, borderRadius: 14, padding: 20, borderWidth: 1, borderColor: theme.color.border },
  confirmTitle: { color: theme.color.text, fontSize: 16, fontWeight: "800" },
  confirmBody: { color: theme.color.textDim, marginTop: 8, fontSize: 12 },
  confirmHint: { color: theme.color.text, marginTop: 4, fontFamily: "monospace" },
  confirmInput: { marginTop: 10, borderWidth: 1, borderColor: theme.color.border, borderRadius: 8, padding: 10, color: theme.color.text, backgroundColor: theme.color.surface },
  confirmRow: { flexDirection: "row", gap: 8, marginTop: 14, justifyContent: "flex-end" },
  ghostBtn: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 6, borderWidth: 1, borderColor: theme.color.border },
  ghostBtnText: { color: theme.color.text, fontSize: 12, fontWeight: "700" },
  dangerBtn: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 6, backgroundColor: "#c44" },
  dangerBtnText: { color: "#fff", fontSize: 12, fontWeight: "800", letterSpacing: 0.8 },
  primaryBtn: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 6, backgroundColor: theme.color.brand },
  primaryBtnText: { color: "#000", fontSize: 12, fontWeight: "800", letterSpacing: 0.8 },
  pwRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 10 },
  eyeBtn: { padding: 8, borderRadius: 6, borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface },
  pwHint: { color: "#ff6b6b", fontSize: 11, marginTop: 6 },
});
