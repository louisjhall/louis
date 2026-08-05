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

type DuplicateRow = {
  id: string;
  name?: string | null;
  email?: string | null;
  created_at?: string | null;
  password_changed_at?: string | null;
  coach_id?: string | null;
  status?: string | null;
  has_v2_plan: boolean;
  has_v2_draft: boolean;
  has_roster: boolean;
  roster_days: number;
  plan_implementations: number;
  workouts_v2_active: number;
  recommend_keep: boolean;
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

  // Iter 130d — duplicate account cleanup. Coach can view every users row
  // sharing this client's email and hard-delete the wrong ones. Guarded on
  // the backend: cannot delete the row that owns the active V2 plan.
  const [dupes, setDupes] = useState<DuplicateRow[]>([]);
  const [dupeTarget, setDupeTarget] = useState<DuplicateRow | null>(null);
  const [dupeConfirmEmail, setDupeConfirmEmail] = useState("");

  // Iter 130j — Training Availability quick-edit form (lifts per-client
  // caps so the engine can honour the intended weekly structure).
  const [avEdit, setAvEdit] = useState(false);
  const [avTrainingDays, setAvTrainingDays] = useState("");
  const [avSessionsMax, setAvSessionsMax] = useState("");
  const [avSessionLen, setAvSessionLen] = useState("");
  const [avHomeCap, setAvHomeCap] = useState("");
  const [avLayoverCap, setAvLayoverCap] = useState("");
  const [avCardioPref, setAvCardioPref] = useState("");
  const [avVariety, setAvVariety] = useState("");
  const [avExperience, setAvExperience] = useState("");
  const [avDislikesRunning, setAvDislikesRunning] = useState<"yes" | "no" | "">("");
  const [avLayoversOk, setAvLayoversOk] = useState<"yes" | "no" | "">("");

  const load = useCallback(async () => {
    if (!clientId) return;
    setLoading(true);
    try {
      const r = await api<ClientAdminData>(`/admin/clients/${clientId}`);
      setData(r);
      // Fire-and-forget: fetch duplicate account rows in parallel.
      try {
        const d = await api<{ rows: DuplicateRow[] }>(`/coach/clients/${clientId}/duplicates`);
        setDupes(Array.isArray(d?.rows) ? d.rows : []);
      } catch {
        setDupes([]);
      }
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

  // Iter 140b — Manual Draft Override + Bulk Delete Workouts.
  const [mdoState, setMdoState] = useState<{ enabled: boolean; updated_by?: string | null; updated_at?: string | null; reason?: string | null } | null>(null);
  const [mdoConfirm, setMdoConfirm] = useState<null | "enable" | "disable">(null);
  const [mdoReason, setMdoReason] = useState("");
  const [bulkConfirm, setBulkConfirm] = useState(false);
  const [bulkStart, setBulkStart] = useState("");
  const [bulkEnd, setBulkEnd] = useState("");
  const [bulkSource, setBulkSource] = useState<"all" | "coach_manual" | "imported">("all");
  const [bulkReason, setBulkReason] = useState("");

  const loadMdo = useCallback(async () => {
    try {
      const r = await api<any>(`/v2/coach/clients/${clientId}/manual-draft-override`);
      setMdoState({
        enabled: !!r?.enabled,
        updated_by: r?.updated_by,
        updated_at: r?.updated_at,
        reason: r?.reason,
      });
    } catch {
      setMdoState({ enabled: false });
    }
  }, [clientId]);

  useEffect(() => { if (visible && clientId) loadMdo(); }, [visible, clientId, loadMdo]);

  const submitMdoToggle = useCallback(async () => {
    if (!mdoConfirm) return;
    const target = mdoConfirm === "enable";
    if (target && !mdoReason.trim()) {
      Alert.alert("Reason required", "Please enter a reason for enabling the override.");
      return;
    }
    setBusy("mdo");
    try {
      await api(`/v2/coach/clients/${clientId}/manual-draft-override`, {
        method: "PATCH",
        body: { enabled: target, reason: mdoReason.trim() || undefined },
      });
      setMdoConfirm(null);
      setMdoReason("");
      await loadMdo();
      Alert.alert(
        target ? "Override enabled" : "Override disabled",
        target
          ? "V2 kickoff / publish / regenerate now work for this client even while Manual Mode is active globally."
          : "This client is back under the global Manual Mode gate."
      );
    } catch (e: any) {
      Alert.alert("Failed", e?.message || "Try again.");
    } finally { setBusy(null); }
  }, [clientId, mdoConfirm, mdoReason, loadMdo]);

  const submitBulkDelete = useCallback(async () => {
    // Basic validation
    const iso = /^\d{4}-\d{2}-\d{2}$/;
    if (!iso.test(bulkStart) || !iso.test(bulkEnd)) {
      Alert.alert("Bad dates", "Both dates must be in YYYY-MM-DD format.");
      return;
    }
    if (bulkEnd < bulkStart) {
      Alert.alert("Bad range", "End date must be on or after start date.");
      return;
    }
    if (!bulkReason.trim() || bulkReason.trim().length < 3) {
      Alert.alert("Reason required", "Please give a short reason (audit trail).");
      return;
    }
    setBusy("bulk-delete");
    try {
      const body: any = {
        start_date: bulkStart,
        end_date: bulkEnd,
        reason: bulkReason.trim(),
        confirm: true,
      };
      if (bulkSource === "coach_manual") body.sources = ["coach_manual"];
      if (bulkSource === "imported") body.import_ref_prefix = "";  // any non-null import_ref via the regex ^
      // For "imported", we want workouts that have import_ref set — use a prefix
      // regex that matches everything. Backend does `^${prefix}` so `""` matches all.
      const res: any = await api(`/coach/clients/${clientId}/workouts/bulk-delete`, {
        method: "POST", body,
      });
      setBulkConfirm(false);
      setBulkStart(""); setBulkEnd(""); setBulkReason(""); setBulkSource("all");
      Alert.alert(
        "Workouts deleted",
        `Deleted ${res?.deleted_count ?? 0} workout${(res?.deleted_count ?? 0) === 1 ? "" : "s"}.`
      );
    } catch (e: any) {
      Alert.alert("Delete failed", e?.message || "Try again.");
    } finally { setBusy(null); }
  }, [clientId, bulkStart, bulkEnd, bulkReason, bulkSource]);

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
      // Backend requires `confirmation: "DELETE"` in the body — was missing.
      await api(`/admin/clients/${clientId}/permanent-delete`, {
        method: "POST",
        body: { confirmation: "DELETE" },
      });
      Alert.alert("Permanently deleted", `${data?.name} and all their data have been permanently deleted.`);
      setConfirmPerm(false); setPermText("");
      onClose();
    } catch (e: any) { Alert.alert("Delete failed", e?.message || ""); }
    finally { setBusy(null); }
  }, [clientId, data, permText, onClose]);

  const doDeleteDuplicate = useCallback(async () => {
    if (!dupeTarget) return;
    const expected = (dupeTarget.email || "").trim().toLowerCase();
    if ((dupeConfirmEmail || "").trim().toLowerCase() !== expected) {
      Alert.alert("Email doesn't match", "Type the client's exact email to confirm the deletion.");
      return;
    }
    setBusy("dup-delete");
    try {
      await api(`/coach/clients/${clientId}/duplicates/delete`, {
        method: "POST",
        body: { target_id: dupeTarget.id, confirm_email: expected },
      });
      Alert.alert("Duplicate deleted", `Removed the duplicate account row for ${dupeTarget.email}. The client can now log in and land on the correct profile.`);
      setDupeTarget(null);
      setDupeConfirmEmail("");
      // Refresh duplicates list.
      try {
        const d = await api<{ rows: DuplicateRow[] }>(`/coach/clients/${clientId}/duplicates`);
        setDupes(Array.isArray(d?.rows) ? d.rows : []);
      } catch { /* no-op */ }
    } catch (e: any) {
      Alert.alert("Delete failed", e?.message || "Try again.");
    } finally { setBusy(null); }
  }, [clientId, dupeTarget, dupeConfirmEmail]);

  // Iter 130j — Save Training Availability. Only fields the coach filled
  // in are sent. Backend endpoint whitelists + logs the diff.
  const openAvEdit = useCallback(() => {
    // Prefill from anything we can find on the client doc, else blank.
    const p: any = (data as any)?.profile || {};
    setAvTrainingDays(p.training_days_per_week ? String(p.training_days_per_week) : "");
    setAvSessionsMax(p.sessions_per_week_max ? String(p.sessions_per_week_max) : "");
    setAvSessionLen(p.preferred_session_length ? String(p.preferred_session_length) : "");
    setAvHomeCap(p.max_home_minutes || p.time_home_min
      ? String(p.max_home_minutes || p.time_home_min) : "");
    setAvLayoverCap(p.time_layover_min ? String(p.time_layover_min) : "");
    setAvCardioPref(p.cardio_preference || "");
    setAvVariety(p.variety_preference || "");
    setAvExperience(p.training_experience || "");
    setAvDislikesRunning(p.dislikes_running === true ? "yes"
                          : p.dislikes_running === false ? "no" : "");
    setAvLayoversOk(p.willing_to_train_layovers === true ? "yes"
                     : p.willing_to_train_layovers === false ? "no" : "");
    setAvEdit(true);
  }, [data]);

  const doSaveAvailability = useCallback(async () => {
    const body: Record<string, any> = {};
    const num = (s: string) => (s.trim() && !isNaN(Number(s)) ? Number(s) : undefined);
    if (num(avTrainingDays) !== undefined) body.training_days_per_week = num(avTrainingDays);
    if (num(avSessionsMax) !== undefined) {
      body.sessions_per_week_max = num(avSessionsMax);
      body.sessions_per_week_min = num(avTrainingDays) ?? num(avSessionsMax);
    }
    if (num(avSessionLen) !== undefined) body.preferred_session_length = num(avSessionLen);
    if (num(avHomeCap) !== undefined) {
      body.max_home_minutes = num(avHomeCap);
      body.time_home_min = num(avHomeCap);
    }
    if (num(avLayoverCap) !== undefined) body.time_layover_min = num(avLayoverCap);
    if (avCardioPref.trim()) body.cardio_preference = avCardioPref.trim().toLowerCase();
    if (avVariety.trim()) body.variety_preference = avVariety.trim().toLowerCase();
    if (avExperience.trim()) body.training_experience = avExperience.trim().toLowerCase();
    if (avDislikesRunning) body.dislikes_running = avDislikesRunning === "yes";
    if (avLayoversOk) body.willing_to_train_layovers = avLayoversOk === "yes";
    if (Object.keys(body).length === 0) {
      Alert.alert("Nothing to save", "Fill at least one field.");
      return;
    }
    setBusy("training-availability");
    try {
      const res: any = await api(`/v2/coach/clients/${clientId}/training-availability`, {
        method: "PATCH", body,
      });
      setAvEdit(false);
      const changedKeys = Object.keys(res?.diff || {});
      Alert.alert(
        "Availability saved",
        (changedKeys.length
          ? `Updated: ${changedKeys.join(", ")}.\n\n`
          : "No changes were needed.\n\n") +
        "Now press \"Rebuild draft\" on the workspace to regenerate the programme.",
      );
    } catch (e: any) {
      Alert.alert("Save failed", e?.detail?.message || e?.message || String(e));
    } finally { setBusy(null); }
  }, [clientId, avTrainingDays, avSessionsMax, avSessionLen, avHomeCap,
      avLayoverCap, avCardioPref, avVariety, avExperience,
      avDislikesRunning, avLayoversOk]);

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

              {/* TRAINING AVAILABILITY (Iter 130j) */}
              <Text style={[styles.section, { marginTop: 20 }]}>TRAINING AVAILABILITY</Text>
              <Row
                icon="time-outline"
                label="Edit training days & time caps"
                sub="How many days, how long, cardio preference. Lifts the caps that block programme generation."
                busy={busy === "training-availability"}
                onPress={openAvEdit}
                testID="admin-drawer-training-availability"
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

              {/* PROGRAMME OVERRIDES (Iter 140b) */}
              <Text style={[styles.section, { marginTop: 20 }]}>PROGRAMME OVERRIDES</Text>
              <View style={[styles.row, mdoState?.enabled && { borderColor: theme.color.brand }]} testID="admin-drawer-mdo-row">
                <Ionicons
                  name={mdoState?.enabled ? "flash" : "flash-outline"}
                  size={18}
                  color={mdoState?.enabled ? theme.color.brand : theme.color.textHi}
                />
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowLabel}>
                    Allow V2 draft/publish during Manual Mode
                  </Text>
                  <Text style={styles.rowSub}>
                    {mdoState?.enabled
                      ? `ON · unlocks Build plan + Publish for this client only. Set by ${mdoState.updated_by || "coach"}.`
                      : "OFF · this client is blocked by the global MANUAL_MODE gate."}
                  </Text>
                </View>
                <Pressable
                  onPress={() => {
                    setMdoReason("");
                    setMdoConfirm(mdoState?.enabled ? "disable" : "enable");
                  }}
                  disabled={busy === "mdo"}
                  style={[styles.smallBtn, mdoState?.enabled && { backgroundColor: "#c44" }]}
                  testID="admin-drawer-mdo-toggle"
                >
                  <Text style={[styles.smallBtnText, mdoState?.enabled && { color: "#fff" }]}>
                    {busy === "mdo" ? "…" : (mdoState?.enabled ? "TURN OFF" : "TURN ON")}
                  </Text>
                </Pressable>
              </View>

              {/* BULK ACTIONS (Iter 140b) */}
              <Text style={[styles.section, { marginTop: 20 }]}>BULK ACTIONS</Text>
              <Row
                icon="trash-bin-outline"
                label="Delete workouts in a date range"
                sub="Wipe imported or manual workouts across a window. Completed sessions are protected."
                busy={busy === "bulk-delete"}
                onPress={() => {
                  setBulkStart(""); setBulkEnd(""); setBulkReason(""); setBulkSource("all");
                  setBulkConfirm(true);
                }}
                testID="admin-drawer-bulk-delete"
              />

              {/* CLIENT STATUS */}
              <Text style={[styles.section, { marginTop: 20 }]}>CLIENT STATUS</Text>
              {data?.archived || data?.status === "archived" ? (
                <Row icon="refresh" label="Restore client" sub="Bring this client back into active coaching." busy={busy === "restore"} onPress={doRestore} testID="admin-drawer-restore" />
              ) : (
                <Row icon="archive-outline" label="Archive client" sub="Pause programme, hide from active lists. Reversible." busy={busy === "archive"} onPress={doArchive} testID="admin-drawer-archive" />
              )}

              {/* DUPLICATE ACCOUNTS (only shown when > 1 row exists) */}
              {dupes.length > 1 ? (
                <>
                  <Text style={[styles.section, { marginTop: 20, color: "#ffb84d" }]}>DUPLICATE ACCOUNTS</Text>
                  <Text style={styles.rowSub}>
                    {dupes.length} rows exist for {dupes[0]?.email}. Keep the one with the active V2 plan — delete the others.
                  </Text>
                  {dupes.map((row) => {
                    const canDelete = !row.has_v2_plan;
                    const created = row.created_at ? new Date(row.created_at).toLocaleDateString() : "—";
                    return (
                      <View key={row.id} style={[styles.dupeCard, row.recommend_keep && styles.dupeCardKeep]} testID={`admin-drawer-dupe-${row.id}`}>
                        <View style={styles.dupeHeader}>
                          <Text style={styles.dupeTitle} numberOfLines={1}>
                            {row.recommend_keep ? "KEEP · " : ""}{row.name || row.id}
                          </Text>
                          {row.recommend_keep ? (
                            <View style={styles.pillKeep}><Text style={styles.pillKeepText}>ACTIVE V2</Text></View>
                          ) : null}
                        </View>
                        <Text style={styles.dupeMeta}>
                          Created {created} · {row.roster_days} roster day{row.roster_days === 1 ? "" : "s"} · {row.plan_implementations} plan impl · {row.workouts_v2_active} live V2
                        </Text>
                        <Text style={styles.dupeIdMono}>{row.id}</Text>
                        <View style={{ flexDirection: "row", gap: 8, marginTop: 10 }}>
                          <Pressable
                            onPress={() => { setDupeTarget(row); setDupeConfirmEmail(""); }}
                            disabled={!canDelete || busy === "dup-delete"}
                            style={[styles.dangerBtn, (!canDelete || busy === "dup-delete") && { opacity: 0.4 }]}
                            testID={`admin-drawer-dupe-delete-${row.id}`}
                          >
                            <Text style={styles.dangerBtnText}>{canDelete ? "Delete this row" : "Protected · has V2 plan"}</Text>
                          </Pressable>
                        </View>
                      </View>
                    );
                  })}
                </>
              ) : null}

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
          {/* Iter 140b — Manual Draft Override toggle confirm */}
          {mdoConfirm && (
            <View style={styles.confirmBackdrop}>
              <View style={styles.confirmCard}>
                <Text style={styles.confirmTitle}>
                  {mdoConfirm === "enable" ? "Enable V2 override" : "Disable V2 override"}
                </Text>
                <Text style={styles.confirmBody}>
                  {mdoConfirm === "enable"
                    ? "This lets Build plan / Publish / Regenerate run for this client only while Manual Mode is active globally. Every use is audit-logged."
                    : "This client will go back under the global MANUAL_MODE gate — Build plan will refuse until you re-enable the override."}
                </Text>
                {mdoConfirm === "enable" && (
                  <>
                    <Text style={styles.fieldLabel}>Reason (required)</Text>
                    <TextInput
                      value={mdoReason} onChangeText={setMdoReason}
                      placeholder="e.g. Onboarding new client during manual mode"
                      placeholderTextColor="#666"
                      style={[styles.confirmInput, { minHeight: 60 }]}
                      multiline
                      testID="admin-drawer-mdo-reason"
                    />
                  </>
                )}
                <View style={styles.confirmRow}>
                  <Pressable
                    onPress={() => { setMdoConfirm(null); setMdoReason(""); }}
                    style={styles.ghostBtn}
                  >
                    <Text style={styles.ghostBtnText}>Cancel</Text>
                  </Pressable>
                  <Pressable
                    onPress={submitMdoToggle}
                    disabled={busy === "mdo"}
                    style={mdoConfirm === "enable" ? styles.primaryBtn : styles.dangerBtn}
                    testID="admin-drawer-mdo-submit"
                  >
                    <Text style={mdoConfirm === "enable" ? styles.primaryBtnText : styles.dangerBtnText}>
                      {busy === "mdo" ? "Working…" : (mdoConfirm === "enable" ? "ENABLE" : "DISABLE")}
                    </Text>
                  </Pressable>
                </View>
              </View>
            </View>
          )}

          {/* Iter 140b — Bulk delete workouts confirm */}
          {bulkConfirm && (
            <View style={styles.confirmBackdrop}>
              <View style={[styles.confirmCard, { maxHeight: "85%" }]}>
                <ScrollView>
                  <Text style={styles.confirmTitle}>Delete workouts in range</Text>
                  <Text style={styles.confirmBody}>
                    Removes workouts on this client between the two dates (inclusive). Completed sessions are refused with a 409. Every deletion is audit-logged.
                  </Text>

                  <Text style={styles.fieldLabel}>Start date (YYYY-MM-DD)</Text>
                  <TextInput
                    value={bulkStart} onChangeText={setBulkStart}
                    placeholder="2026-08-01" placeholderTextColor="#666"
                    autoCapitalize="none"
                    style={styles.confirmInput}
                    testID="admin-drawer-bulk-start"
                  />

                  <Text style={styles.fieldLabel}>End date (YYYY-MM-DD)</Text>
                  <TextInput
                    value={bulkEnd} onChangeText={setBulkEnd}
                    placeholder="2026-08-31" placeholderTextColor="#666"
                    autoCapitalize="none"
                    style={styles.confirmInput}
                    testID="admin-drawer-bulk-end"
                  />

                  <Text style={styles.fieldLabel}>Which workouts?</Text>
                  <View style={styles.pillRow}>
                    {(["all", "coach_manual", "imported"] as const).map((s) => (
                      <Pressable
                        key={s}
                        onPress={() => setBulkSource(s)}
                        style={[styles.pillChoice, bulkSource === s && styles.pillChoiceActive]}
                        testID={`admin-drawer-bulk-src-${s}`}
                      >
                        <Text style={[styles.pillChoiceText, bulkSource === s && styles.pillChoiceTextActive]}>
                          {s === "all" ? "All" : s === "coach_manual" ? "Manual only" : "Imported only"}
                        </Text>
                      </Pressable>
                    ))}
                  </View>
                  <Text style={styles.fieldHint}>
                    Imported only targets workouts that came from the JSON importer (have import_ref). Manual only targets everything with source=coach_manual including hand-built and imported. All wipes every non-completed row in the window.
                  </Text>

                  <Text style={styles.fieldLabel}>Reason (required, min 3 chars)</Text>
                  <TextInput
                    value={bulkReason} onChangeText={setBulkReason}
                    placeholder="e.g. Old restored programme — wiping to import new August JSON"
                    placeholderTextColor="#666"
                    style={[styles.confirmInput, { minHeight: 60 }]}
                    multiline
                    testID="admin-drawer-bulk-reason"
                  />

                  <View style={styles.confirmRow}>
                    <Pressable
                      onPress={() => setBulkConfirm(false)}
                      style={styles.ghostBtn}
                    >
                      <Text style={styles.ghostBtnText}>Cancel</Text>
                    </Pressable>
                    <Pressable
                      onPress={submitBulkDelete}
                      disabled={busy === "bulk-delete"}
                      style={styles.dangerBtn}
                      testID="admin-drawer-bulk-submit"
                    >
                      <Text style={styles.dangerBtnText}>
                        {busy === "bulk-delete" ? "Deleting…" : "DELETE"}
                      </Text>
                    </Pressable>
                  </View>
                </ScrollView>
              </View>
            </View>
          )}
          {/* Iter 130j — Training Availability edit modal */}
          {avEdit && (
            <View style={styles.confirmBackdrop}>
              <View style={[styles.confirmCard, { maxHeight: "85%" }]}>
                <ScrollView>
                  <Text style={styles.confirmTitle}>Training availability</Text>
                  <Text style={styles.confirmBody}>
                    Leave a field blank to keep its current value. Values in
                    minutes for the time caps.
                  </Text>

                  <Text style={styles.fieldLabel}>Training days per week (1–7)</Text>
                  <TextInput
                    value={avTrainingDays} onChangeText={setAvTrainingDays}
                    keyboardType="number-pad" placeholder="e.g. 5"
                    placeholderTextColor="#666" style={styles.confirmInput}
                    testID="admin-av-training-days"
                  />

                  <Text style={styles.fieldLabel}>Max sessions per week</Text>
                  <TextInput
                    value={avSessionsMax} onChangeText={setAvSessionsMax}
                    keyboardType="number-pad" placeholder="e.g. 6"
                    placeholderTextColor="#666" style={styles.confirmInput}
                    testID="admin-av-sessions-max"
                  />

                  <Text style={styles.fieldLabel}>Preferred session length (min)</Text>
                  <TextInput
                    value={avSessionLen} onChangeText={setAvSessionLen}
                    keyboardType="number-pad" placeholder="e.g. 75"
                    placeholderTextColor="#666" style={styles.confirmInput}
                    testID="admin-av-session-len"
                  />

                  <Text style={styles.fieldLabel}>Home / office daily cap (min)</Text>
                  <TextInput
                    value={avHomeCap} onChangeText={setAvHomeCap}
                    keyboardType="number-pad" placeholder="e.g. 120"
                    placeholderTextColor="#666" style={styles.confirmInput}
                    testID="admin-av-home-cap"
                  />

                  <Text style={styles.fieldLabel}>Layover daily cap (min)</Text>
                  <TextInput
                    value={avLayoverCap} onChangeText={setAvLayoverCap}
                    keyboardType="number-pad" placeholder="e.g. 60"
                    placeholderTextColor="#666" style={styles.confirmInput}
                    testID="admin-av-layover-cap"
                  />

                  <Text style={styles.fieldLabel}>Cardio preference</Text>
                  <Text style={styles.fieldHint}>
                    run · walk · bike · elliptical · rower · recumbent_bike · incline_walk
                  </Text>
                  <TextInput
                    value={avCardioPref} onChangeText={setAvCardioPref}
                    autoCapitalize="none" placeholder="e.g. elliptical"
                    placeholderTextColor="#666" style={styles.confirmInput}
                    testID="admin-av-cardio-pref"
                  />

                  <Text style={styles.fieldLabel}>Variety preference</Text>
                  <Text style={styles.fieldHint}>low · moderate · high</Text>
                  <TextInput
                    value={avVariety} onChangeText={setAvVariety}
                    autoCapitalize="none" placeholder="e.g. high"
                    placeholderTextColor="#666" style={styles.confirmInput}
                    testID="admin-av-variety"
                  />

                  <Text style={styles.fieldLabel}>Training experience</Text>
                  <Text style={styles.fieldHint}>beginner · intermediate · advanced</Text>
                  <TextInput
                    value={avExperience} onChangeText={setAvExperience}
                    autoCapitalize="none" placeholder="e.g. intermediate"
                    placeholderTextColor="#666" style={styles.confirmInput}
                    testID="admin-av-experience"
                  />

                  <Text style={styles.fieldLabel}>Dislikes running?</Text>
                  <View style={styles.pillRow}>
                    <Pressable onPress={() => setAvDislikesRunning("yes")}
                      style={[styles.pillChoice, avDislikesRunning === "yes" && styles.pillChoiceActive]}
                      testID="admin-av-dislikes-yes">
                      <Text style={[styles.pillChoiceText, avDislikesRunning === "yes" && styles.pillChoiceTextActive]}>Yes</Text>
                    </Pressable>
                    <Pressable onPress={() => setAvDislikesRunning("no")}
                      style={[styles.pillChoice, avDislikesRunning === "no" && styles.pillChoiceActive]}
                      testID="admin-av-dislikes-no">
                      <Text style={[styles.pillChoiceText, avDislikesRunning === "no" && styles.pillChoiceTextActive]}>No</Text>
                    </Pressable>
                  </View>

                  <Text style={styles.fieldLabel}>Willing to train on layovers?</Text>
                  <View style={styles.pillRow}>
                    <Pressable onPress={() => setAvLayoversOk("yes")}
                      style={[styles.pillChoice, avLayoversOk === "yes" && styles.pillChoiceActive]}
                      testID="admin-av-layovers-yes">
                      <Text style={[styles.pillChoiceText, avLayoversOk === "yes" && styles.pillChoiceTextActive]}>Yes</Text>
                    </Pressable>
                    <Pressable onPress={() => setAvLayoversOk("no")}
                      style={[styles.pillChoice, avLayoversOk === "no" && styles.pillChoiceActive]}
                      testID="admin-av-layovers-no">
                      <Text style={[styles.pillChoiceText, avLayoversOk === "no" && styles.pillChoiceTextActive]}>No</Text>
                    </Pressable>
                  </View>

                  <View style={[styles.confirmRow, { marginTop: 20 }]}>
                    <Pressable onPress={() => setAvEdit(false)} style={styles.ghostBtn}>
                      <Text style={styles.ghostBtnText}>Cancel</Text>
                    </Pressable>
                    <Pressable
                      onPress={doSaveAvailability}
                      disabled={busy === "training-availability"}
                      style={[styles.primaryBtn, busy === "training-availability" && { opacity: 0.5 }]}
                      testID="admin-av-save"
                    >
                      <Text style={styles.primaryBtnText}>
                        {busy === "training-availability" ? "Saving…" : "Save"}
                      </Text>
                    </Pressable>
                  </View>
                </ScrollView>
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
          {dupeTarget && (
            <View style={styles.confirmBackdrop}>
              <View style={styles.confirmCard}>
                <Text style={styles.confirmTitle}>Delete duplicate row</Text>
                <Text style={styles.confirmBody}>
                  This hard-deletes the duplicate account row (id below) sharing this email. The other row(s) are untouched.
                </Text>
                <Text style={styles.confirmHint}>{dupeTarget.id}</Text>
                <Text style={[styles.confirmBody, { marginTop: 10 }]}>Type the client&apos;s email to confirm:</Text>
                <Text style={styles.confirmHint}>{dupeTarget.email}</Text>
                <TextInput
                  value={dupeConfirmEmail}
                  onChangeText={setDupeConfirmEmail}
                  autoCapitalize="none"
                  keyboardType="email-address"
                  style={styles.confirmInput}
                  placeholder="client@example.com"
                  placeholderTextColor="#666"
                  testID="admin-drawer-dupe-confirm-email"
                />
                <View style={styles.confirmRow}>
                  <Pressable onPress={() => { setDupeTarget(null); setDupeConfirmEmail(""); }} style={styles.ghostBtn}><Text style={styles.ghostBtnText}>Cancel</Text></Pressable>
                  <Pressable onPress={doDeleteDuplicate} disabled={busy === "dup-delete"} style={styles.dangerBtn} testID="admin-drawer-dupe-confirm">
                    <Text style={styles.dangerBtnText}>{busy === "dup-delete" ? "Deleting…" : "Delete row"}</Text>
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
  fieldLabel: { color: theme.color.text, fontSize: 13, fontWeight: "600", marginTop: 12 },
  fieldHint: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },
  pillRow: { flexDirection: "row", gap: 8, marginTop: 8 },
  pillChoice: { paddingVertical: 8, paddingHorizontal: 16, borderRadius: 999, borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface },
  pillChoiceActive: { borderColor: theme.color.brand, backgroundColor: theme.color.brand },
  pillChoiceText: { color: theme.color.text, fontSize: 13, fontWeight: "600" },
  pillChoiceTextActive: { color: "#fff" },
  dupeCard: { backgroundColor: theme.color.surface2, padding: 12, borderRadius: 10, borderWidth: 1, borderColor: theme.color.border, marginTop: 8 },
  dupeCardKeep: { borderColor: "rgba(80, 200, 120, 0.5)", backgroundColor: "rgba(80, 200, 120, 0.06)" },
  dupeHeader: { flexDirection: "row", alignItems: "center", gap: 8, justifyContent: "space-between" },
  dupeTitle: { color: theme.color.text, fontSize: 13, fontWeight: "800", flex: 1 },
  dupeMeta: { color: theme.color.textDim, fontSize: 11, marginTop: 4 },
  dupeIdMono: { color: theme.color.textDim, fontSize: 10, fontFamily: "monospace", marginTop: 2 },
  pillKeep: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4, backgroundColor: "rgba(80, 200, 120, 0.2)" },
  pillKeepText: { color: "#50c878", fontSize: 9, fontWeight: "800", letterSpacing: 1 },
});
