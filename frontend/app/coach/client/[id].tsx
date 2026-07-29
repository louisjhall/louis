import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl, Alert, Modal, TextInput, Platform } from "react-native";
import { useLocalSearchParams, useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { useAuth } from "@/src/lib/auth";
import { usePreview } from "@/src/lib/preview";
import { theme, loadColor } from "@/src/lib/theme";
import { StatusBadge, deriveStatus } from "@/src/components/StatusBadge";
import { CoachNotesTab } from "@/src/components/CoachNotesTab";
import { CoachRosterUploadButton } from "@/src/components/CoachRosterUploadButton";
import { confirm as uxConfirm, toast as uxToast } from "@/src/lib/ux";

const DAY_TYPES = [
  "Home Day", "Home Training Day", "Turnaround Duty", "Layover Arrival Day",
  "Layover Full Day", "Layover Departure Day", "Long-Haul Duty", "Short-Haul Duty",
  "Night Flight", "Early Report", "Late Finish", "Rest Day", "Recovery Day",
  "Standby", "Simulator/Training Day", "Annual Leave", "Unknown/Needs Confirmation",
];
const LOAD_OPTIONS: { key: string; label: string; color: string }[] = [
  { key: "green",  label: "GREEN",  color: "#4caf50" },
  { key: "amber",  label: "AMBER",  color: "#e5a337" },
  { key: "red",    label: "RED",    color: "#c85450" },
  { key: "blue",   label: "BLUE",   color: "#4a90e2" },
  { key: "purple", label: "PURPLE", color: "#8a5cf5" },
  { key: "grey",   label: "GREY",   color: "#666" },
];

type Controls = {
  programme_flexibility: string;
  progression_speed: string;
  injury_caution: string;
  video_frequency: string;
  auto_approval_risk_threshold: string;
};

const CONTROL_OPTIONS: Record<keyof Controls, { key: string; label: string }[]> = {
  programme_flexibility: [
    { key: "strict", label: "Strict" },
    { key: "flexible", label: "Flexible" },
  ],
  progression_speed: [
    { key: "cautious", label: "Cautious" },
    { key: "standard", label: "Standard" },
    { key: "aggressive", label: "Aggressive" },
  ],
  injury_caution: [
    { key: "low", label: "Low" },
    { key: "medium", label: "Medium" },
    { key: "high", label: "High" },
  ],
  video_frequency: [
    { key: "weekly", label: "Weekly" },
    { key: "biweekly", label: "Bi-weekly" },
    { key: "monthly", label: "Monthly" },
  ],
  auto_approval_risk_threshold: [
    { key: "none", label: "None (coach reviews all)" },
    { key: "low", label: "Low-risk only" },
    { key: "low_medium", label: "Low + Medium" },
  ],
};

const CONTROL_LABEL: Record<keyof Controls, string> = {
  programme_flexibility: "Programme flexibility",
  progression_speed: "Progression speed",
  injury_caution: "Injury caution level",
  video_frequency: "Video touchpoint",
  auto_approval_risk_threshold: "Auto-approval risk threshold",
};

export default function ClientDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { user: currentUser } = useAuth();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [controls, setControls] = useState<Controls | null>(null);
  const [savingCtrl, setSavingCtrl] = useState(false);
  const [changeLog, setChangeLog] = useState<any[]>([]);
  const [habitsData, setHabitsData] = useState<any>(null);
  const [standbyData, setStandbyData] = useState<any>(null);
  const [programme, setProgramme] = useState<any>(null);
  const [next7, setNext7] = useState<any[]>([]);
  const [history, setHistory] = useState<any[]>([]);
  const [regenOpen, setRegenOpen] = useState(false);
  const [regenNote, setRegenNote] = useState("");
  const [regenerating, setRegenerating] = useState(false);
  const [approving, setApproving] = useState(false);
  // Slice 1: admin lifecycle actions + audit log.
  const [auditLog, setAuditLog] = useState<any[]>([]);
  // Plan C3 — programme overview + timeline
  const [overview, setOverview] = useState<any>(null);
  const [timeline, setTimeline] = useState<any[]>([]);
  const [permDeleteOpen, setPermDeleteOpen] = useState(false);
  const [permDeleteText, setPermDeleteText] = useState("");
  const [adminBusy, setAdminBusy] = useState<string | null>(null);
  // Iter 92 (Phase 2, Task 2.6) — LIVE SIGNALS
  const [liveState, setLiveState] = useState<any | null>(null);
  const [liveReceipt, setLiveReceipt] = useState<any | null>(null);
  const [directiveText, setDirectiveText] = useState("");
  const [directiveBusy, setDirectiveBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [detail, ctrl, log, habits, standby, prog, hist, audit, overview, timeline, live] = await Promise.all([
        api<any>(`/coach/clients/${id}`),
        api<{ controls: Controls }>(`/coach/clients/${id}/controls`).catch(() => ({ controls: null as any })),
        api<{ entries: any[] }>(`/coach/clients/${id}/change-log`).catch(() => ({ entries: [] })),
        api<any>(`/coach/clients/${id}/habits`).catch(() => null),
        api<any>(`/coach/clients/${id}/standby`).catch(() => null),
        api<any>(`/coach/clients/${id}/programme`).catch(() => null),
        api<any>(`/coach/clients/${id}/programme/history`).catch(() => ({ programmes: [] })),
        api<{ entries: any[] }>(`/admin/clients/${id}/audit-log?limit=25`).catch(() => ({ entries: [] })),
        // Plan C3 — programme overview + timeline
        api<any>(`/coach/clients/${id}/programme-overview`).catch(() => null),
        api<any>(`/coach/clients/${id}/programme-timeline?limit=120`).catch(() => ({ timeline: [] })),
        // Iter 92 (Phase 2) — Live signals
        api<any>(`/coach/clients/${id}/live-state`).catch(() => null),
      ]);
      setData(detail);
      if (ctrl?.controls) setControls(ctrl.controls);
      setChangeLog(log.entries || []);
      setHabitsData(habits);
      setStandbyData(standby);
      setProgramme(prog?.programme || null);
      setNext7(prog?.next_7_days || []);
      setHistory(hist?.programmes || []);
      setAuditLog(audit?.entries || []);
      setOverview(overview || null);
      setTimeline(timeline?.timeline || []);
      setLiveState(live?.live_state || null);
      setLiveReceipt(live?.receipt || null);
    } finally { setLoading(false); }
  }, [id]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const updateControl = async (field: keyof Controls, value: string) => {
    if (!controls) return;
    const prev = controls;
    setControls({ ...controls, [field]: value });
    setSavingCtrl(true);
    try {
      const r = await api<{ controls: Controls }>(`/coach/clients/${id}/controls`, {
        method: "PUT", body: { [field]: value },
      });
      setControls(r.controls);
      // refresh change log
      const log = await api<{ entries: any[] }>(`/coach/clients/${id}/change-log`).catch(() => ({ entries: [] }));
      setChangeLog(log.entries || []);
    } catch (e: any) {
      setControls(prev);
      Alert.alert("Couldn't save", e?.message || "Try again");
    } finally { setSavingCtrl(false); }
  };

  const doRegenerate = async () => {
    setRegenerating(true);
    try {
      const res = await api<any>(`/coach/clients/${id}/programme/regenerate`, {
        method: "POST",
        body: { force_fresh_llm: true, note: regenNote || null },
      });
      setRegenOpen(false);
      setRegenNote("");
      Alert.alert(
        "Regeneration started",
        `We're rebuilding ${res.workouts_scheduled} days of workouts on the active roster. Refresh in ~30–60s.`,
      );
      setTimeout(load, 30000); // auto-refresh after ~30s
    } catch (e: any) {
      Alert.alert("Regenerate failed", e?.message || "Try again in a moment.");
    } finally {
      setRegenerating(false);
    }
  };

  const doApproveProgramme = async () => {
    if (!programme) return;
    setApproving(true);
    try {
      const res = await api<any>(`/coach/clients/${id}/programme/approve`, {
        method: "POST",
        body: { approve: true },
      });
      setProgramme(res.programme || programme);
      Alert.alert(
        "Programme approved",
        `${res.workouts_touched || 0} workouts cleared of the review flag.`,
      );
    } catch (e: any) {
      Alert.alert("Approval failed", e?.message || "Try again.");
    } finally {
      setApproving(false);
    }
  };

  // Plan C7 — Regenerate whole programme (preview → apply)
  const [regenPreview, setRegenPreview] = useState<any>(null);
  const [regenBusy, setRegenBusy] = useState(false);
  const openRegenProgramme = async () => {
    setRegenBusy(true);
    try {
      const r = await api<any>(`/coach/clients/${id}/programme/regenerate-preview`, { method: "POST" });
      setRegenPreview(r);
    } catch (e: any) {
      Alert.alert("Preview failed", e?.message || "Try again.");
    } finally {
      setRegenBusy(false);
    }
  };
  const applyRegenProgramme = async () => {
    setRegenBusy(true);
    try {
      const r = await api<any>(`/coach/clients/${id}/programme/regenerate-apply`, {
        method: "POST",
        body: { preserve_coach_locked: true, preserve_completed: true },
      });
      Alert.alert("Regeneration queued", r?.message || "The worker will process it shortly.");
      setRegenPreview(null);
      await load();
    } catch (e: any) {
      Alert.alert("Apply failed", e?.message || "Try again.");
    } finally {
      setRegenBusy(false);
    }
  };

  // ---- Admin lifecycle actions ----
  const runAdmin = async (label: string, path: string, body?: any) => {
    setAdminBusy(label);
    try {
      await api(`/admin/clients/${id}${path}`, { method: "POST", body: body || {} });
      uxToast(`${label} — done`, "success");
      await load();
    } catch (e: any) {
      uxToast(`${label} failed: ${e?.message || "try again"}`, "error");
    } finally {
      setAdminBusy(null);
    }
  };

  const askArchive = async () => {
    const mode = await new Promise<"cancel" | "archive_only" | "archive_pause">((resolve) => {
      // Two-step for the two options — web can't show 3-button Alerts either.
      uxConfirm({
        title: "Archive this client?",
        message: "This will move them out of the active client list. Their data will be kept and can be restored later.\n\nOK = Archive Only.  Cancel to skip.",
        confirmLabel: "Archive Only",
        cancelLabel: "Cancel",
      }).then(async (ok) => {
        if (!ok) return resolve("cancel");
        // Offer the harder option after they confirm archive
        const alsoPause = await uxConfirm({
          title: "Also disable client login?",
          message: "OK = Archive + Pause login (client can't sign in).\nCancel = Just archive (login still works).",
          confirmLabel: "Archive & Pause",
          cancelLabel: "Just Archive",
          destructive: true,
        });
        resolve(alsoPause ? "archive_pause" : "archive_only");
      });
    });
    if (mode === "cancel") return;
    await runAdmin(mode === "archive_pause" ? "Archive & Pause" : "Archive", "/archive", { mode });
  };

  const askRestore = () => runAdmin("Restore", "/restore");

  // Iter 128b — admin/coach force password reset. Uses the dedicated
  // `/coach/clients/{id}/reset-password` endpoint (server.py) which
  // hashes with the same bcrypt scheme the rest of auth uses.
  const askResetPassword = async () => {
    if (Platform.OS !== "web") {
      // Native: use Alert.prompt on iOS, fallback to text-input modal on
      // Android. For MVP we only support iOS Alert.prompt + web prompt().
      if (Platform.OS === "ios" && (Alert as any).prompt) {
        (Alert as any).prompt(
          "Reset client password",
          `Set a new password for ${data?.email || "this client"}.\nMinimum 6 characters.`,
          [
            { text: "Cancel", style: "cancel" },
            {
              text: "Reset",
              style: "destructive",
              onPress: async (pw?: string) => {
                if (!pw || pw.length < 6) {
                  Alert.alert("Too short", "Password must be at least 6 characters.");
                  return;
                }
                await doResetPassword(pw);
              },
            },
          ],
          "secure-text",
        );
        return;
      }
      // Android + any other: use the small in-page prompt fallback via
      // Alert with a follow-up TextInput isn't possible without a modal.
      // Coach flow lives on web/desktop primarily so this is acceptable.
      Alert.alert(
        "Not supported on this device",
        "Reset a client password from the desktop coach view (Louis on web).",
      );
      return;
    }
    // Web: window.prompt is fine — coach is on desktop.
    const pw = typeof window !== "undefined" ? window.prompt(
      `Set a new password for ${data?.email || "this client"}.\nMinimum 6 characters.`,
    ) : null;
    if (!pw) return;
    if (pw.length < 6) {
      Alert.alert("Too short", "Password must be at least 6 characters.");
      return;
    }
    const ok = typeof window !== "undefined" ? window.confirm(
      `Reset ${data?.email || "this client"}'s password to:\n\n${pw}\n\nThey will be signed out and must use this new password to log in.`,
    ) : true;
    if (!ok) return;
    await doResetPassword(pw);
  };

  const doResetPassword = async (newPassword: string) => {
    setAdminBusy("Reset Password");
    try {
      await api(`/coach/clients/${id}/reset-password`, {
        method: "POST",
        body: { new_password: newPassword },
      });
      Alert.alert(
        "Password reset",
        `New password is now active for ${data?.email || "this client"}. Ask them to sign in again with it.`,
      );
    } catch (e: any) {
      Alert.alert("Reset failed", e?.message || "Try again.");
    } finally {
      setAdminBusy(null);
    }
  };

  const askSoftDelete = async () => {
    const ok = await uxConfirm({
      title: "Delete this client?",
      message: "This will disable their access and remove them from your active dashboard. Their data will be kept temporarily unless you choose permanent deletion.",
      confirmLabel: "Delete Client",
      cancelLabel: "Cancel",
      destructive: true,
    });
    if (!ok) return;
    await runAdmin("Soft Delete", "/soft-delete");
  };

  const openPermDelete = () => {
    setPermDeleteText("");
    setPermDeleteOpen(true);
  };

  const doPermDelete = async () => {
    if (permDeleteText.trim().toUpperCase() !== "DELETE") {
      Alert.alert("Confirmation required", "Type DELETE in capital letters to confirm.");
      return;
    }
    setAdminBusy("Permanent Delete");
    try {
      await api(`/admin/clients/${id}/permanent-delete`, {
        method: "POST",
        body: { confirmation: "DELETE" },
      });
      setPermDeleteOpen(false);
      Alert.alert("Permanently deleted", "The client's identifying data has been erased.", [
        { text: "OK", onPress: () => router.back() },
      ]);
    } catch (e: any) {
      Alert.alert("Permanent delete failed", e?.message || "Try again.");
    } finally {
      setAdminBusy(null);
    }
  };

  const isAdmin = !!(
    currentUser?.is_admin ||
    currentUser?.role === "admin" ||
    (currentUser as any)?.coach_tier === "admin" ||
    (currentUser as any)?.is_primary_coach ||
    (currentUser?.email || "").toLowerCase().endsWith("@crewfit.net")
  );

  // Slice 2: assign/reassign coach
  const [coachPickerOpen, setCoachPickerOpen] = useState(false);
  const [availableCoaches, setAvailableCoaches] = useState<any[]>([]);
  // Slice 3: tabbed layout state.
  type Tab = "overview" | "notes" | "calendar" | "roster" | "programme" | "timeline" | "workouts" | "checkins" | "messages" | "profile" | "admin";
  const [tab, setTab] = useState<Tab>("overview");

  const openCoachPicker = async () => {
    try {
      const r = await api<any>(`/admin/coaches`);
      setAvailableCoaches((r.coaches || []).filter((c: any) => c.status === "active"));
      setCoachPickerOpen(true);
    } catch (e: any) {
      Alert.alert("Load failed", e?.message || "Could not load coaches.");
    }
  };

  const assignCoach = async (coach_id: string, coach_name: string) => {
    setAdminBusy("Assign Coach");
    try {
      await api(`/admin/clients/${id}/assign-coach`, {
        method: "POST",
        body: { coach_id },
      });
      setCoachPickerOpen(false);
      await load();
      Alert.alert("Coach assigned", `${data?.name || "This client"} is now assigned to ${coach_name}.`);
    } catch (e: any) {
      Alert.alert("Assignment failed", e?.message || "Try again.");
    } finally {
      setAdminBusy(null);
    }
  };

  // ---- Slice 3.5: deep-edit state ----
  const preview = usePreview();
  const [wActionOpen, setWActionOpen] = useState<any | null>(null); // workout for action sheet
  const [wMoveOpen, setWMoveOpen] = useState<any | null>(null);
  const [wMoveDate, setWMoveDate] = useState("");
  const [wRegenOpen, setWRegenOpen] = useState<any | null>(null);
  const [wRegenNote, setWRegenNote] = useState("");
  const [wBusy, setWBusy] = useState(false);
  const [rDayEditOpen, setRDayEditOpen] = useState<any | null>(null); // day being edited
  const [rDayDraft, setRDayDraft] = useState<{ day_type?: string; load?: string; notes?: string; layover_city?: string }>({});
  const [rDayBusy, setRDayBusy] = useState(false);
  const [previewBusy, setPreviewBusy] = useState(false);

  const startPreview = async () => {
    setPreviewBusy(true);
    try {
      await preview.enterReal(String(id));
      Alert.alert(
        "Preview mode active",
        "You're now seeing the app as this client. Writes are blocked. Tap 'Exit preview' in the banner to return.",
        [{ text: "OK", onPress: () => router.replace("/(tabs)/home" as any) }],
      );
    } catch (e: any) {
      Alert.alert("Preview failed", e?.message || "Try again.");
    } finally { setPreviewBusy(false); }
  };

  const doWorkoutApprove = async (w: any) => {
    setWBusy(true);
    try {
      await api(`/coach/workouts/${w.id}/approve`, { method: "POST", body: {} });
      setWActionOpen(null);
      await load();
    } catch (e: any) {
      Alert.alert("Approve failed", e?.message || "Try again.");
    } finally { setWBusy(false); }
  };

  const doWorkoutLockToggle = async (w: any) => {
    setWBusy(true);
    try {
      await api(`/coach/workouts/${w.id}/lock`, {
        method: "POST",
        body: { locked: !w.coach_locked },
      });
      setWActionOpen(null);
      await load();
    } catch (e: any) {
      Alert.alert("Lock failed", e?.message || "Try again.");
    } finally { setWBusy(false); }
  };

  const doWorkoutMove = async () => {
    if (!wMoveOpen) return;
    const d = wMoveDate.trim();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(d)) {
      Alert.alert("Invalid date", "Use format YYYY-MM-DD");
      return;
    }
    setWBusy(true);
    try {
      const r = await api<any>(`/coach/workouts/${wMoveOpen.id}/move`, {
        method: "POST",
        body: { to_date: d, swap_with_existing: true },
      });
      setWMoveOpen(null); setWActionOpen(null); setWMoveDate("");
      Alert.alert("Workout moved", r?.swapped ? `Swapped with the workout on ${d}` : `Moved to ${d}`);
      await load();
    } catch (e: any) {
      Alert.alert("Move failed", e?.message || "Try again.");
    } finally { setWBusy(false); }
  };

  const doWorkoutRegenSingle = async () => {
    if (!wRegenOpen) return;
    setWBusy(true);
    try {
      await api(`/coach/workouts/${wRegenOpen.id}/regenerate`, {
        method: "POST",
        body: { note: wRegenNote || null },
      });
      setWRegenOpen(null); setWActionOpen(null); setWRegenNote("");
      Alert.alert("Regenerated", "The workout has been rebuilt using the latest programme context.");
      await load();
    } catch (e: any) {
      // Iter 84 (Task 1.4) — profile_incomplete 409 → offer to nudge the client.
      const code = e?.detail?.code || e?.code;
      if (code === "profile_incomplete" || e?.status === 409) {
        const labels = (e?.detail?.friendly_labels || [])
          .map((l: string) => `• ${l}`).join("\n");
        const hint = e?.detail?.coach_hint || "";
        setWRegenOpen(null);
        Alert.alert(
          "Client hasn't finished training setup",
          `${hint}\n\nMissing:\n${labels}`,
          [
            { text: "OK", style: "cancel" },
            {
              text: "Nudge Client",
              onPress: () => nudgeClientForSetup(),
            },
          ],
        );
        return;
      }
      Alert.alert("Regenerate failed", e?.message || "Try again.");
    } finally { setWBusy(false); }
  };

  // Iter 84 (Task 1.4) — send a friendly message from Louis asking the client
  // to complete their setup. Fires a coach→client message.
  const nudgeClientForSetup = async () => {
    if (!client) return;
    const name = (client?.name || "").split(" ")[0] || "";
    try {
      await api(`/messages`, {
        method: "POST",
        body: {
          to_user_id: client.id,
          text: (
            `Hey${name ? " " + name : ""}, just noticed you haven't finished your training setup. ` +
            `It only takes 30 seconds and locks in your equipment, time and goals so I can build proper workouts for you. ` +
            `Open the app and you'll see the setup screen automatically — thanks!`
          ),
        },
      });
      Alert.alert("Nudge sent", "Message from Louis queued to this client.");
    } catch (e: any) {
      Alert.alert("Nudge failed", e?.message || "Try again.");
    }
  };

  const openRosterDayEdit = (day: any) => {
    setRDayDraft({
      day_type: day.day_type || "Home Day",
      load: day.load || "grey",
      notes: day.notes || "",
      layover_city: day.layover_city || "",
    });
    setRDayEditOpen(day);
  };

  const doSaveRosterDay = async () => {
    if (!rDayEditOpen || !data?.roster?.id) return;
    setRDayBusy(true);
    try {
      await api(`/coach/clients/${id}/roster/${data.roster.id}/day`, {
        method: "PATCH",
        body: {
          date: rDayEditOpen.date,
          day_type: rDayDraft.day_type,
          load: rDayDraft.load,
          notes: rDayDraft.notes,
          layover_city: rDayDraft.layover_city,
        },
      });
      setRDayEditOpen(null);
      await load();
    } catch (e: any) {
      Alert.alert("Save failed", e?.message || "Try again.");
    } finally { setRDayBusy(false); }
  };

  const doClearHotel = async () => {
    if (!rDayEditOpen || !data?.roster?.id) return;
    setRDayBusy(true);
    try {
      await api(`/coach/clients/${id}/roster/${data.roster.id}/day`, {
        method: "PATCH",
        body: { date: rDayEditOpen.date, clear_hotel: true },
      });
      setRDayEditOpen(null);
      await load();
    } catch (e: any) {
      Alert.alert("Clear failed", e?.message || "Try again.");
    } finally { setRDayBusy(false); }
  };


  if (loading || !data) {
    return <View style={{ flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: theme.color.surface }}><ActivityIndicator color={theme.color.brand} /></View>;
  }

  const { client, roster, workouts, checkins, overrides = [] } = data;
  const p = client.profile || {};

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()}><Ionicons name="chevron-back" size={26} color={theme.color.text} /></Pressable>
        <Text style={styles.headerT}>CLIENT</Text>
        <View style={{ width: 26 }} />
      </View>
      <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 60 }} refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}>
        <Text style={styles.name}>{client.name}</Text>
        <Text style={styles.email}>{client.email}</Text>

        {client.progression_pill?.status ? (
          <View style={styles.progRow} testID="cd-progression-pill">
            <View style={[
              styles.progPill,
              client.progression_pill.status === "progressing_well" && { backgroundColor: "rgba(34,197,94,0.15)" },
              client.progression_pill.status === "reduce_load"      && { backgroundColor: "rgba(245,158,11,0.18)" },
              client.progression_pill.status === "deload"           && { backgroundColor: "rgba(59,130,246,0.15)" },
              client.progression_pill.status === "maintain"         && { backgroundColor: "rgba(163,24,46,0.12)" },
            ]}>
              <Ionicons
                name={
                  client.progression_pill.status === "progressing_well" ? "trending-up" :
                  client.progression_pill.status === "reduce_load"      ? "trending-down" :
                  client.progression_pill.status === "deload"           ? "moon" : "remove"
                }
                size={11}
                color={
                  client.progression_pill.status === "progressing_well" ? "#16A34A" :
                  client.progression_pill.status === "reduce_load"      ? "#B45309" :
                  client.progression_pill.status === "deload"           ? "#1D4ED8" : theme.color.brand
                }
              />
              <Text style={[
                styles.progPillText,
                { color:
                  client.progression_pill.status === "progressing_well" ? "#16A34A" :
                  client.progression_pill.status === "reduce_load"      ? "#B45309" :
                  client.progression_pill.status === "deload"           ? "#1D4ED8" : theme.color.brand
                }
              ]}>
                {client.progression_pill.status_label} · WK {client.progression_pill.week_key}
              </Text>
            </View>
            {client.progression_pill.coach_note ? (
              <Text style={styles.progNote} numberOfLines={2}>{client.progression_pill.coach_note}</Text>
            ) : null}
          </View>
        ) : null}

        {/* Iter 92 (Phase 2, Task 2.6) — LIVE SIGNALS card */}
        {liveState ? (
          <View style={styles.liveCard} testID="cd-live-signals">
            <View style={styles.liveHead}>
              <Ionicons name="pulse" size={13} color={theme.color.brand} />
              <Text style={styles.liveTitle}>LIVE SIGNALS · LAST {liveState.window_days || 14}D</Text>
              {liveState.auto_deload_trigger ? (
                <View style={styles.liveDeloadPill} testID="cd-live-deload">
                  <Text style={styles.liveDeloadT}>AUTO-DELOAD</Text>
                </View>
              ) : null}
            </View>
            <View style={styles.liveGrid}>
              <View style={styles.liveCell}>
                <Text style={styles.liveVal}>{liveState.energy_avg ?? "—"}</Text>
                <Text style={styles.liveLabel}>ENERGY · {liveState.energy_trend || "—"}</Text>
              </View>
              <View style={styles.liveCell}>
                <Text style={styles.liveVal}>{liveState.avg_rpe_last_7d ?? "—"}</Text>
                <Text style={styles.liveLabel}>RPE 7D</Text>
              </View>
              <View style={styles.liveCell}>
                <Text style={styles.liveVal}>{liveState.adherence_pct != null ? Math.round(liveState.adherence_pct * 100) + "%" : "—"}</Text>
                <Text style={styles.liveLabel}>ADHERENCE</Text>
              </View>
              <View style={styles.liveCell}>
                <Text style={styles.liveVal}>{liveState.missed_sessions_14d ?? 0}</Text>
                <Text style={styles.liveLabel}>MISSED</Text>
              </View>
            </View>
            {liveState.pain_flags?.length ? (
              <View style={styles.liveChipRow}>
                {liveState.pain_flags.map((p: any, i: number) => (
                  <View key={i} style={styles.liveChipRed} testID={`cd-pain-flag-${p.key || i}`}>
                    <Ionicons name="warning" size={10} color="#c85450" />
                    <Text style={styles.liveChipRedT}>{(p.region || "pain").replace("_", " ").toUpperCase()}</Text>
                  </View>
                ))}
              </View>
            ) : null}
            {liveState.avoid_movement_patterns?.length ? (
              <Text style={styles.liveHint}>Avoiding next week: {liveState.avoid_movement_patterns.slice(0, 4).join(", ")}</Text>
            ) : null}
            {liveState.focus_shift_request?.target ? (
              <Text style={styles.liveHint}>Focus shift: {String(liveState.focus_shift_request.target).replace("_", " ")}</Text>
            ) : null}
            {liveState.coach_directives?.length ? (
              <View style={{ marginTop: 8 }}>
                <Text style={styles.liveSub}>COACH DIRECTIVES · PINNED</Text>
                {liveState.coach_directives.slice(0, 3).map((d: any) => (
                  <View key={d.id} style={styles.directiveRow} testID={`cd-directive-${d.id}`}>
                    <Text style={styles.directiveT} numberOfLines={3}>· {d.text}</Text>
                    <Pressable
                      testID={`cd-directive-del-${d.id}`}
                      hitSlop={8}
                      onPress={async () => {
                        try {
                          await api(`/coach/clients/${id}/directives/${d.id}`, { method: "DELETE" });
                          await load();
                        } catch (e: any) {
                          Alert.alert("Couldn't remove", e?.message || "Try again.");
                        }
                      }}
                    >
                      <Ionicons name="close-circle" size={16} color={theme.color.textMuted} />
                    </Pressable>
                  </View>
                ))}
              </View>
            ) : null}
            <View style={styles.directiveInputRow}>
              <TextInput
                testID="cd-directive-input"
                value={directiveText}
                onChangeText={setDirectiveText}
                placeholder="Add a coaching directive for next plan..."
                placeholderTextColor={theme.color.textDim}
                style={styles.directiveInput}
                multiline
              />
              <Pressable
                testID="cd-directive-add"
                disabled={directiveBusy || !directiveText.trim()}
                onPress={async () => {
                  setDirectiveBusy(true);
                  try {
                    await api(`/coach/clients/${id}/directives`, {
                      method: "POST",
                      body: { text: directiveText.trim(), ttl_days: 21 },
                    });
                    setDirectiveText("");
                    await load();
                  } catch (e: any) {
                    Alert.alert("Couldn't save", e?.message || "Try again.");
                  } finally { setDirectiveBusy(false); }
                }}
                style={[styles.directiveAddBtn, (!directiveText.trim() || directiveBusy) && { opacity: 0.4 }]}
              >
                <Ionicons name="add-circle" size={16} color={theme.color.brand} />
                <Text style={styles.directiveAddT}>PIN</Text>
              </Pressable>
            </View>
          </View>
        ) : null}

        <View style={styles.actionRow}>
          <Pressable
            testID="cd-months-btn"
            onPress={() => router.push(`/coach/client-months/${client.id}` as any)}
            style={[styles.actionBtn, { backgroundColor: theme.color.brand }]}
          >
            <Ionicons name="calendar" size={16} color="#fff" />
            <Text style={styles.actionText}>PROGRAMME BY MONTH</Text>
          </Pressable>
          {/* Iter 109 · Phase A · A2 — Coach uploads roster on behalf of client */}
          <CoachRosterUploadButton
            clientId={client.id}
            clientName={client.name || client.first_name || client.email}
            onComplete={load}
          />
          <Pressable testID="cd-script-btn" onPress={() => router.push(`/coach/scripts/${client.id}`)} style={[styles.actionBtn, { backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border }]}>
            <Ionicons name="videocam" size={16} color={theme.color.text} />
            <Text style={[styles.actionText, { color: theme.color.text }]}>WEEKLY SCRIPT</Text>
          </Pressable>
          <Pressable
            testID="cd-draft-btn"
            onPress={async () => {
              try {
                const r = await api<any>("/coach/messages/generate", { method: "POST", body: { client_id: client.id } });
                if (r?.draft?.id) router.push(`/coach/draft/${r.draft.id}` as any);
              } catch (e: any) {
                Alert.alert("Couldn't draft reply", e?.message || "Try again");
              }
            }}
            style={[styles.actionBtn, { backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.brand }]}
          >
            <Ionicons name="sparkles" size={16} color={theme.color.brand} />
            <Text style={[styles.actionText, { color: theme.color.brand }]}>DRAFT REPLY</Text>
          </Pressable>
          {isAdmin ? (
            <Pressable
              testID="cd-admin-shortcut"
              onPress={() => setTab("admin")}
              style={[styles.actionBtn, { backgroundColor: "transparent", borderWidth: 1, borderColor: "#c85450" }]}
            >
              <Ionicons name="shield" size={16} color="#c85450" />
              <Text style={[styles.actionText, { color: "#c85450" }]}>ADMIN</Text>
            </Pressable>
          ) : null}
        </View>

        {/* Slice 3: Tab bar. Sections below render according to the selected tab. */}
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingVertical: 8, paddingRight: 12, gap: 6 }}>
          {(isAdmin
            ? ["overview","admin","notes","calendar","roster","programme","timeline","workouts","checkins","messages","profile"]
            : ["overview","notes","calendar","roster","programme","timeline","workouts","checkins","messages","profile"]
          ).map((t) => {
            const active = tab === (t as Tab);
            const isAdminTab = t === "admin";
            return (
              <Pressable
                key={t}
                testID={`cd-tab-${t}`}
                onPress={() => setTab(t as Tab)}
                style={[
                  styles.cdTab,
                  active && styles.cdTabActive,
                  isAdminTab && !active && { borderColor: "#c85450", backgroundColor: "rgba(200,84,80,0.08)" },
                  isAdminTab && active && { backgroundColor: "#c85450", borderColor: "#c85450" },
                ]}
              >
                <Text style={[
                  styles.cdTabText,
                  active && { color: "#fff" },
                  isAdminTab && !active && { color: "#c85450" },
                ]}>{t.toUpperCase()}</Text>
              </Pressable>
            );
          })}
        </ScrollView>

        {/* Overview tab — high-level cards render below */}
        {tab === "overview" && (
          <View style={styles.card}>
            <Text style={styles.sect}>OVERVIEW</Text>
            <Text style={{ color: theme.color.textMuted, fontSize: 12, marginTop: 6, lineHeight: 18 }}>
              {data?.name} · {data?.email}
              {data?.assigned_coach_name ? `\nAssigned to ${data.assigned_coach_name}` : ""}
              {data?.profile?.airline ? `\n${data.profile.airline} · ${data.profile?.job_title || data.profile?.position || ""}` : ""}
              {data?.profile?.home_base ? ` · Base ${data.profile.home_base}` : ""}
              {data?.profile?.route_focus ? ` · ${data.profile.route_focus}` : ""}
              {"\n"}
              {programme?.goal_label ? `Goal: ${programme.goal_label} · ${programme?.phase?.label || ""} · Week ${programme?.display_week || programme?.week_index || "—"}` : "No programme yet."}
            </Text>
          </View>
        )}

        {tab === "notes" ? (
          <CoachNotesTab clientId={String(id)} />
        ) : null}

        {/* Plan C3 — Programme Overview enriched card */}
        {(tab === "overview" || tab === "programme") && overview ? (
          <View testID="programme-overview-card" style={[styles.card, overview.needs_coach_review && { borderColor: "#f59e0b" }]}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
              <Text style={styles.sect}>PROGRAMME OVERVIEW</Text>
              {overview.needs_coach_review ? (
                <Text style={{ color: "#f59e0b", fontSize: 10, fontWeight: "800", letterSpacing: 1 }}>NEEDS REVIEW</Text>
              ) : null}
            </View>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 12, marginTop: 8 }}>
              <View>
                <Text style={styles.ovLbl}>THIS WEEK</Text>
                <Text style={styles.ovVal}>{overview.week_counts?.completed || 0}/{overview.week_counts?.target || overview.week_counts?.planned || 0}</Text>
                <Text style={styles.ovSub}>completed / target</Text>
              </View>
              <View>
                <Text style={styles.ovLbl}>MISSED</Text>
                <Text style={styles.ovVal}>{overview.week_counts?.missed || 0}</Text>
                <Text style={styles.ovSub}>this week</Text>
              </View>
              <View>
                <Text style={styles.ovLbl}>REVIEW</Text>
                <Text style={styles.ovVal}>{overview.upcoming?.needs_coach_review || 0}</Text>
                <Text style={styles.ovSub}>next 14d</Text>
              </View>
              <View>
                <Text style={styles.ovLbl}>LOCKED</Text>
                <Text style={styles.ovVal}>{overview.upcoming?.coach_locked || 0}</Text>
                <Text style={styles.ovSub}>upcoming</Text>
              </View>
              <View>
                <Text style={styles.ovLbl}>TEMPLATE</Text>
                <Text style={styles.ovVal}>{overview.upcoming?.template_count || 0}</Text>
                <Text style={styles.ovSub}>of {overview.upcoming?.total_14d || 0}</Text>
              </View>
            </View>
            {overview.next_key_session ? (
              <View style={{ marginTop: 10, paddingTop: 10, borderTopWidth: 1, borderTopColor: theme.color.line }}>
                <Text style={styles.ovLbl}>NEXT KEY SESSION</Text>
                <Text style={{ color: theme.color.text, fontSize: 13, fontWeight: "700", marginTop: 4 }}>{overview.next_key_session.title}</Text>
                <Text style={{ color: theme.color.textMuted, fontSize: 11, marginTop: 2 }}>{overview.next_key_session.date} · {overview.next_key_session.focus}</Text>
              </View>
            ) : null}
            <View style={{ flexDirection: "row", gap: 8, marginTop: 10 }}>
              <View style={styles.sourcePill}>
                <Text style={styles.sourcePillT}>SOURCE: {(overview.source || "").replace("_", " ").toUpperCase()}</Text>
              </View>
              {overview.open_coach_tasks_for_client ? (
                <View style={styles.sourcePill}>
                  <Text style={styles.sourcePillT}>{overview.open_coach_tasks_for_client} OPEN TASK{overview.open_coach_tasks_for_client > 1 ? "S" : ""}</Text>
                </View>
              ) : null}
            </View>
          </View>
        ) : null}

        {/* Plan C3 — Timeline tab */}
        {tab === "timeline" && (
          <View style={styles.card}>
            <Text style={styles.sect}>PROGRAMME TIMELINE</Text>
            <Text style={{ color: theme.color.textMuted, fontSize: 11, marginTop: 4 }}>
              Onboarding · roster · programme · workouts · check-ins · coach changes.
            </Text>
            <View style={{ marginTop: 12 }}>
              {timeline.length === 0 ? (
                <Text style={{ color: theme.color.textMuted, fontSize: 12 }}>No timeline events yet.</Text>
              ) : (
                timeline.slice(0, 60).map((e: any, idx: number) => {
                  const at = (e.at || "").slice(0, 16).replace("T", " ");
                  const kind = String(e.kind || "");
                  const iconMap: Record<string, string> = {
                    "onboarding.started": "person-add",
                    "assessment.completed": "checkmark-circle",
                    "dna.version": "git-branch",
                    "roster.uploaded": "cloud-upload",
                    "roster.confirmed": "checkmark",
                    "roster.deleted": "trash",
                    "roster.deactivated": "close-circle",
                    "programme.generated": "sparkles",
                    "programme.validation_flag": "alert-circle",
                    "workout.completed": "barbell",
                    "checkin.completed": "chatbubbles",
                    "workout.edit": "create",
                    "programme.edit": "settings",
                  };
                  const icon = iconMap[kind] || "ellipse-outline";
                  const tone = kind.includes("deleted") || kind.includes("validation_flag") ? "#f59e0b"
                    : kind.includes("completed") ? "#22c55e" : theme.color.text;
                  return (
                    <View key={idx} style={styles.tlRow}>
                      <View style={styles.tlIconWrap}>
                        <Ionicons name={icon as any} size={14} color={tone} />
                      </View>
                      <View style={{ flex: 1 }}>
                        <Text style={styles.tlTitle}>{e.title}</Text>
                        {e.detail ? <Text style={styles.tlDetail}>{e.detail}</Text> : null}
                        <Text style={styles.tlMeta}>{at} · {e.actor || "system"} · {kind}</Text>
                      </View>
                    </View>
                  );
                })
              )}
            </View>
          </View>
        )}

        {/* Iter 128d — Legacy V1 Programme card REMOVED (regenerate/approve/
            preview/apply were all V1 generator entry points). All programme
            management now lives exclusively in the canonical client workspace
            (/coach/client/{id}/workspace) via the Engine V2 Draft panel. */}


        {/* Slice 1: Admin — status pill, archive/pause/restore/delete, audit log. */}
        {(tab === "admin" || tab === "overview") && isAdmin ? (
          <View testID="admin-card" style={[styles.card, styles.adminCard]}>
            <View style={styles.progHeader}>
              <Text style={styles.sect}>ADMIN</Text>
              <View style={[styles.progStatusPill, {
                backgroundColor:
                  data?.status === "archived" ? theme.color.textDim :
                  data?.status === "paused" ? "#e5a337" :
                  data?.status === "deletion_pending" ? "#c85450" :
                  data?.status === "deleted" ? "#666" :
                  theme.color.green,
              }]}>
                <Text style={styles.progStatusPillText}>{String(data?.status || "active").toUpperCase()}</Text>
              </View>
            </View>

            {/* Assigned coach */}
            <View style={styles.progRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.progLabel}>ASSIGNED COACH</Text>
                <Text style={styles.progValue}>{data?.assigned_coach_name || "Louis Hall"}</Text>
              </View>
              <Pressable testID="admin-change-coach" onPress={openCoachPicker} style={styles.adminBtnAlt}>
                <Ionicons name="swap-horizontal" size={13} color={theme.color.text} />
                <Text style={styles.adminBtnAltText}>CHANGE</Text>
              </Pressable>
            </View>

            <View style={styles.adminActions}>
              <Pressable testID="admin-reset-password" onPress={askResetPassword} disabled={!!adminBusy} style={styles.adminBtnAlt}>
                <Ionicons name="key" size={13} color={theme.color.text} />
                <Text style={styles.adminBtnAltText}>RESET PASSWORD</Text>
              </Pressable>
              {(!data?.status || data?.status === "active") ? (
                <>
                  <Pressable testID="admin-archive" onPress={askArchive} disabled={!!adminBusy} style={styles.adminBtnAlt}>
                    <Ionicons name="archive" size={13} color={theme.color.text} />
                    <Text style={styles.adminBtnAltText}>ARCHIVE</Text>
                  </Pressable>
                  <Pressable testID="admin-delete" onPress={askSoftDelete} disabled={!!adminBusy} style={styles.adminBtnDanger}>
                    <Ionicons name="trash" size={13} color="#c85450" />
                    <Text style={styles.adminBtnDangerText}>DELETE</Text>
                  </Pressable>
                </>
              ) : (data?.status === "archived" || data?.status === "paused") ? (
                <>
                  <Pressable testID="admin-restore" onPress={askRestore} disabled={!!adminBusy} style={styles.adminBtnPrimary}>
                    <Ionicons name="refresh" size={13} color="#fff" />
                    <Text style={styles.adminBtnPrimaryText}>RESTORE</Text>
                  </Pressable>
                  <Pressable testID="admin-delete" onPress={askSoftDelete} disabled={!!adminBusy} style={styles.adminBtnDanger}>
                    <Ionicons name="trash" size={13} color="#c85450" />
                    <Text style={styles.adminBtnDangerText}>DELETE</Text>
                  </Pressable>
                </>
              ) : (data?.status === "deletion_pending") ? (
                <>
                  <Pressable testID="admin-restore" onPress={askRestore} disabled={!!adminBusy} style={styles.adminBtnPrimary}>
                    <Ionicons name="refresh" size={13} color="#fff" />
                    <Text style={styles.adminBtnPrimaryText}>RESTORE</Text>
                  </Pressable>
                  <Pressable testID="admin-perm-delete" onPress={openPermDelete} disabled={!!adminBusy} style={[styles.adminBtnDanger, { borderColor: "#c85450", backgroundColor: "rgba(200,84,80,0.08)" }]}>
                    <Ionicons name="warning" size={13} color="#c85450" />
                    <Text style={styles.adminBtnDangerText}>PERMANENT DELETE</Text>
                  </Pressable>
                </>
              ) : null}
              {adminBusy ? (
                <View style={{ marginLeft: 8, justifyContent: "center" }}>
                  <ActivityIndicator color={theme.color.brand} />
                </View>
              ) : null}
            </View>

            {auditLog.length > 0 ? (
              <View style={{ marginTop: 14 }}>
                <Text style={styles.progLabel}>AUDIT LOG</Text>
                {auditLog.slice(0, 6).map((row: any) => (
                  <View key={row.id} style={styles.auditRow}>
                    <Text style={styles.auditAction}>{String(row.action || "").toUpperCase()}</Text>
                    <Text style={styles.auditMeta} numberOfLines={1}>
                      {row.actor_name || row.actor_email || "system"}
                      {row.reason ? ` · ${row.reason}` : ""}
                    </Text>
                    <Text style={styles.auditWhen}>{(row.timestamp || "").slice(0, 16).replace("T", " ")}</Text>
                  </View>
                ))}
              </View>
            ) : null}

            <Pressable
              testID="admin-manage-coaches"
              onPress={() => router.push("/coach/admin/coaches" as any)}
              style={[styles.adminBtnAlt, { marginTop: 12, alignSelf: "flex-start" }]}
            >
              <Ionicons name="people" size={13} color={theme.color.text} />
              <Text style={styles.adminBtnAltText}>MANAGE COACHES</Text>
            </Pressable>

            {/* Slice 3.5 — Preview as Client */}
            <Pressable
              testID="admin-preview-client"
              onPress={startPreview}
              disabled={previewBusy}
              style={[styles.adminBtnAlt, { marginTop: 8, alignSelf: "flex-start" }, previewBusy && { opacity: 0.55 }]}
            >
              <Ionicons name="eye" size={13} color={theme.color.brand} />
              <Text style={[styles.adminBtnAltText, { color: theme.color.brand }]}>
                {previewBusy ? "OPENING…" : "PREVIEW AS THIS CLIENT"}
              </Text>
            </Pressable>
          </View>
        ) : null}

        {(tab === "admin" || tab === "overview") && controls ? (
          <View style={styles.card}>
            <Text style={styles.sect}>COACH CONTROLS {savingCtrl ? " · SAVING…" : ""}</Text>
            {(Object.keys(CONTROL_OPTIONS) as (keyof Controls)[]).map((field) => (
              <View key={field} style={styles.ctrlBlock}>
                <Text style={styles.ctrlLabel}>{CONTROL_LABEL[field]}</Text>
                <View style={styles.ctrlRow}>
                  {CONTROL_OPTIONS[field].map((opt) => {
                    const active = controls[field] === opt.key;
                    return (
                      <Pressable
                        key={opt.key}
                        testID={`ctrl-${field}-${opt.key}`}
                        onPress={() => updateControl(field, opt.key)}
                        style={[styles.ctrlChip, active && styles.ctrlChipActive]}
                      >
                        <Text style={[styles.ctrlChipT, active && { color: "#fff" }]}>{opt.label}</Text>
                      </Pressable>
                    );
                  })}
                </View>
              </View>
            ))}
          </View>
        ) : null}

        {(tab === "profile" || tab === "overview") && (
        <View style={styles.card}>
          <Text style={styles.sect}>PROFILE</Text>
          <Row label="Airline" value={p.airline || "—"} />
          <Row label="Position" value={p.position || "—"} />
          <Row label="Level" value={p.experience_level || "—"} />
          <Row label="Days/week" value={String(p.training_days_per_week || "—")} />
          <Row label="Weight" value={p.weight_kg ? `${p.weight_kg}kg` : "—"} />
          <Row label="Calorie target" value={String(p.calorie_target || "—")} />
        </View>
        )}

        {(tab === "roster" || tab === "calendar" || tab === "overview") && roster ? (
          <View style={styles.card}>
            <Text style={styles.sect}>ROSTER · {roster.week_start}</Text>
            {roster.days?.map((d: any, i: number) => {
              const rowInner = (
                <View style={styles.dayRow}>
                  <View style={[styles.bar, { backgroundColor: loadColor(d.load) }]} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.dText}>
                      {d.date} · {d.type?.toUpperCase() || d.day_type?.toUpperCase()}
                    </Text>
                    {d.flights?.[0] ? (
                      <Text style={styles.fText}>  {d.flights[0].from}→{d.flights[0].to}</Text>
                    ) : null}
                    {d.hotel_name ? (
                      <Text style={styles.hText}>  🏨 {d.hotel_name}</Text>
                    ) : null}
                  </View>
                  {tab === "roster" ? <Ionicons name="create-outline" size={16} color={theme.color.textMuted} /> : null}
                </View>
              );
              return tab === "roster" ? (
                <Pressable
                  key={i}
                  testID={`cd-roster-day-${d.date}`}
                  onPress={() => openRosterDayEdit(d)}
                >
                  {rowInner}
                </Pressable>
              ) : (
                <View key={i}>{rowInner}</View>
              );
            })}
          </View>
        ) : (tab === "roster" || tab === "calendar" || tab === "overview") ? (
          <View style={styles.card}><Text style={{ color: theme.color.textMuted }}>No roster uploaded.</Text></View>
        ) : null}

        {(tab === "workouts" || tab === "calendar" || tab === "overview") && (
        <View style={styles.card}>
          <Text style={styles.sect}>WEEK PLAN · {workouts.length} WORKOUTS</Text>
          {workouts.length === 0 ? <Text style={{ color: theme.color.textMuted, marginTop: 6 }}>No workouts yet.</Text> :
            workouts.map((w: any) => (
              <View key={w.id} style={styles.wRow}>
                <View style={[styles.bar, { backgroundColor: loadColor(w.day_load) }]} />
                <Pressable
                  testID={`cd-workout-${w.id}`}
                  onPress={() => router.push(`/workout/${w.id}`)}
                  style={{ flex: 1 }}
                >
                  <Text style={styles.wTitle}>
                    {w.title}
                    {w.coach_locked ? " · 🔒" : ""}
                  </Text>
                  <Text style={styles.wMeta}>{w.date} · {w.exercises?.length || 0} ex</Text>
                </Pressable>
                {w.approved ? <Ionicons name="checkmark-circle" size={18} color={theme.color.green} /> : <StatusBadge status={deriveStatus(w)} />}
                {(tab === "workouts") && (
                  <Pressable
                    testID={`cd-workout-manage-${w.id}`}
                    onPress={() => setWActionOpen(w)}
                    style={styles.wManageBtn}
                  >
                    <Ionicons name="ellipsis-horizontal" size={16} color={theme.color.text} />
                  </Pressable>
                )}
              </View>
            ))
          }
        </View>
        )}

        {(tab === "roster" || tab === "overview") && overrides.length > 0 && (
          <View style={styles.card}>
            <Text style={styles.sect}>CLIENT DAY EDITS · {overrides.length}</Text>
            {overrides.slice(0, 12).map((o: any, idx: number) => {
              const tagsList: string[] = o.tags || [];
              const topTag = tagsList[0] || o.day_type || o.training_preference || "edit";
              return (
                <View key={o.id || `${o.date}-${idx}`} style={styles.ovRow}>
                  <View style={styles.ovLeft}>
                    <Ionicons name="create" size={14} color={theme.color.amber} />
                    <Text style={styles.ovDate}>{o.date}</Text>
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.ovTags} numberOfLines={1}>
                      {tagsList.length
                        ? tagsList.map((t: string) => t.replace(/_/g, " ").toUpperCase()).join(" · ")
                        : String(topTag).replace(/_/g, " ").toUpperCase()}
                    </Text>
                    {o.notes ? (
                      <Text style={styles.ovNotes} numberOfLines={2}>
                        {`"${o.notes}"`}
                      </Text>
                    ) : null}
                  </View>
                </View>
              );
            })}
            {overrides.length > 12 && (
              <Text style={styles.ovMore}>+{overrides.length - 12} more</Text>
            )}
          </View>
        )}

        {(tab === "checkins" || tab === "overview") && checkins.length > 0 && (
          <View style={styles.card}>
            <Text style={styles.sect}>LATEST CHECK-IN</Text>
            <Row label="Energy" value={String(checkins[0].energy)} />
            <Row label="Sleep" value={String(checkins[0].sleep)} />
            <Row label="Soreness" value={String(checkins[0].soreness)} />
            <Row label="Stress" value={String(checkins[0].stress)} />
            {checkins[0].weight_kg && <Row label="Weight" value={`${checkins[0].weight_kg}kg`} />}
            {checkins[0].notes && <Text style={{ color: theme.color.textMuted, marginTop: 8, fontStyle: "italic" }}>{`"${checkins[0].notes}"`}</Text>}
          </View>
        )}

        {(tab === "checkins" || tab === "overview") && habitsData ? (
          <View style={styles.card}>
            <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
              <Text style={styles.sect}>HABITS · {(habitsData.active || []).length} ACTIVE</Text>
              {habitsData.pending_review ? (
                <Pressable
                  testID="habits-review-open"
                  onPress={() => router.push(`/coach/habit-review/${habitsData.pending_review.id}` as any)}
                  style={{ paddingHorizontal: 10, paddingVertical: 4, borderRadius: 4, backgroundColor: theme.color.amber }}
                >
                  <Text style={{ color: "#000", fontSize: 9, fontWeight: "900", letterSpacing: 1.5 }}>REVIEW READY</Text>
                </Pressable>
              ) : null}
            </View>
            {(habitsData.active || []).length === 0 && (habitsData.paused || []).length === 0 ? (
              <Text style={{ color: theme.color.textMuted, fontSize: 12 }}>No habits yet — starter pack will be seeded after DNA finalises.</Text>
            ) : null}
            {(habitsData.active || []).map((h: any) => {
              const stat = habitsData.completion?.[h.id];
              return (
                <View key={h.id} style={styles.habitRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.habitTitle}>{h.title}</Text>
                    {h.reason ? <Text style={styles.habitReason} numberOfLines={2}>{h.reason}</Text> : null}
                    <Text style={styles.habitMeta}>
                      {String(h.habit_type).toUpperCase().replace(/-/g, " ")}
                      {h.linked_goal ? ` · ${String(h.linked_goal).toUpperCase().replace(/_/g, " ")}` : ""}
                    </Text>
                  </View>
                  <View style={{ alignItems: "flex-end" }}>
                    {stat ? (
                      <Text style={[styles.completionPct, { color: stat.rate >= 0.8 ? theme.color.green : (stat.rate >= 0.4 ? theme.color.amber : "#c94a4a") }]}>
                        {Math.round((stat.rate || 0) * 100)}%
                      </Text>
                    ) : null}
                    {typeof h.streak === "number" && h.streak > 0 ? (
                      <View style={styles.streakChip}>
                        <Ionicons name="flame" size={11} color={theme.color.brand} />
                        <Text style={styles.streakT}>{h.streak}d</Text>
                      </View>
                    ) : null}
                  </View>
                </View>
              );
            })}
            {(habitsData.paused || []).length > 0 ? (
              <Text style={styles.pausedHead}>PAUSED · {(habitsData.paused || []).length}</Text>
            ) : null}
            {(habitsData.paused || []).map((h: any) => (
              <View key={h.id} style={[styles.habitRow, { opacity: 0.55 }]}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.habitTitle}>{h.title}</Text>
                </View>
                <Text style={{ color: theme.color.textDim, fontSize: 10, fontWeight: "800", letterSpacing: 1 }}>PAUSED</Text>
              </View>
            ))}
            {habitsData.latest_review ? (
              <View style={styles.latestReviewCard}>
                <Text style={styles.blockHead}>LATEST ATLAS REVIEW</Text>
                <Text style={styles.blockBody}>{habitsData.latest_review.atlas_summary}</Text>
                <Text style={styles.blockMeta}>
                  {habitsData.latest_review.week_start} → {habitsData.latest_review.week_end} ·
                  {" "}{Math.round((habitsData.latest_review.completion_rate || 0) * 100)}% completion ·
                  {" "}{String(habitsData.latest_review.coach_review_status || "pending").toUpperCase()}
                </Text>
              </View>
            ) : null}
          </View>
        ) : null}

        {standbyData && standbyData.days?.length > 0 ? (
          <View style={styles.card}>
            <Text style={styles.sect}>STANDBY · {standbyData.days.length} DAYS</Text>
            {standbyData.days.slice(0, 8).map((d: any) => (
              <View key={d.date} style={styles.habitRow}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.habitTitle}>{d.date} · {(d.standby_type || "standby").toUpperCase().replace(/_/g, " ")}</Text>
                  <Text style={styles.habitMeta}>
                    {d.start_time || "?"}{d.end_time ? `–${d.end_time}` : ""} · {d.location || "unknown"}
                    {d.needs_confirmation ? " · NEEDS CONFIRMATION" : ""}
                  </Text>
                </View>
                <View style={[styles.sbBadge, sbStatusColor(d.standby_status)]}>
                  <Text style={styles.sbBadgeT}>{(d.standby_status || "waiting").toUpperCase().replace(/_/g, " ")}</Text>
                </View>
              </View>
            ))}
          </View>
        ) : null}

        {changeLog.length > 0 ? (
          <View style={styles.card}>
            <Text style={styles.sect}>CHANGE LOG · {changeLog.length}</Text>
            {changeLog.slice(0, 20).map((entry: any) => (
              <View key={entry.id} style={styles.logRow}>
                <View style={[styles.logDot, { backgroundColor: logColor(entry.category) }]} />
                <View style={{ flex: 1 }}>
                  <View style={{ flexDirection: "row", gap: 6, alignItems: "center" }}>
                    <Text style={[styles.logCat, { color: logColor(entry.category) }]}>{(entry.category || "other").toUpperCase()}</Text>
                    <Text style={styles.logDate}>{(entry.created_at || "").slice(0, 16).replace("T", " ")}</Text>
                  </View>
                  <Text style={styles.logTitle}>{entry.title}</Text>
                  {entry.description ? <Text style={styles.logDesc} numberOfLines={2}>{entry.description}</Text> : null}
                </View>
              </View>
            ))}
            {changeLog.length > 20 && (
              <Text style={styles.ovMore}>+{changeLog.length - 20} more</Text>
            )}
          </View>
        ) : null}
      </ScrollView>

      <Modal visible={regenOpen} transparent animationType="fade" onRequestClose={() => setRegenOpen(false)}>
        <View style={styles.modalScrim}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Regenerate this client&apos;s plan?</Text>
            <Text style={styles.modalBody}>
              We&apos;ll rebuild the workouts on the active roster using the latest
              programme context. Locked or completed sessions are preserved.
            </Text>
            <Text style={[styles.progLabel, { marginTop: 12 }]}>COACH NOTE (OPTIONAL)</Text>
            <TextInput
              testID="regen-note"
              style={styles.modalInput}
              value={regenNote}
              onChangeText={setRegenNote}
              placeholder="e.g. Adjust to new base after Dubai transfer"
              placeholderTextColor={theme.color.textDim}
              multiline
            />
            <View style={styles.modalRow}>
              <Pressable testID="regen-cancel" style={styles.modalBtnGhost} onPress={() => setRegenOpen(false)}>
                <Text style={styles.modalBtnGhostText}>CANCEL</Text>
              </Pressable>
              <Pressable
                testID="regen-confirm"
                style={[styles.modalBtn, regenerating && { opacity: 0.6 }]}
                onPress={doRegenerate}
                disabled={regenerating}
              >
                {regenerating ? <ActivityIndicator color="#fff" /> : (
                  <Text style={styles.modalBtnText}>REGENERATE</Text>
                )}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
      <Modal visible={coachPickerOpen} transparent animationType="slide" onRequestClose={() => setCoachPickerOpen(false)}>
        <View style={styles.modalScrim}>
          <View style={[styles.modalCard, { maxHeight: 500 }]}>
            <Text style={styles.modalTitle}>Assign to Coach</Text>
            <Text style={styles.modalBody}>Choose the coach who will look after {data?.name || "this client"}.</Text>
            <ScrollView style={{ marginTop: 12, maxHeight: 340 }}>
              {availableCoaches.map((c) => (
                <Pressable
                  key={c.id}
                  testID={`assign-coach-${c.id}`}
                  onPress={() => assignCoach(c.id, c.name)}
                  disabled={adminBusy === "Assign Coach"}
                  style={styles.auditRow}
                >
                  <Text style={styles.auditAction}>{(c.name || "Coach").toUpperCase()}</Text>
                  <Text style={styles.auditMeta}>
                    {(c.coach_tier || "full").toUpperCase()} · {c.assigned_clients || 0} clients
                  </Text>
                </Pressable>
              ))}
              {availableCoaches.length === 0 ? (
                <Text style={{ color: theme.color.textDim, padding: 12, textAlign: "center" }}>
                  No other active coaches. Invite one from Manage Coaches.
                </Text>
              ) : null}
            </ScrollView>
            <Pressable testID="assign-coach-cancel" onPress={() => setCoachPickerOpen(false)} style={[styles.modalBtnGhost, { marginTop: 12 }]}>
              <Text style={styles.modalBtnGhostText}>CANCEL</Text>
            </Pressable>
          </View>
        </View>
      </Modal>

      <Modal visible={permDeleteOpen} transparent animationType="fade" onRequestClose={() => setPermDeleteOpen(false)}>
        <View style={styles.modalScrim}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Permanently delete this client and their data?</Text>
            <Text style={styles.modalBody}>
              This cannot be undone. Their identifying data will be scrubbed and their
              messages redacted. Audit-log rows are preserved.
            </Text>
            <Text style={[styles.progLabel, { marginTop: 12 }]}>TYPE DELETE TO CONFIRM</Text>
            <TextInput
              testID="perm-delete-input"
              style={styles.modalInput}
              value={permDeleteText}
              onChangeText={setPermDeleteText}
              placeholder="DELETE"
              placeholderTextColor={theme.color.textDim}
              autoCapitalize="characters"
              autoCorrect={false}
            />
            <View style={styles.modalRow}>
              <Pressable testID="perm-delete-cancel" style={styles.modalBtnGhost} onPress={() => setPermDeleteOpen(false)}>
                <Text style={styles.modalBtnGhostText}>CANCEL</Text>
              </Pressable>
              <Pressable
                testID="perm-delete-confirm"
                style={[styles.modalBtn, { backgroundColor: "#c85450" }, adminBusy === "Permanent Delete" && { opacity: 0.6 }]}
                onPress={doPermDelete}
                disabled={adminBusy === "Permanent Delete"}
              >
                {adminBusy === "Permanent Delete"
                  ? <ActivityIndicator color="#fff" />
                  : <Text style={styles.modalBtnText}>PERMANENTLY DELETE</Text>}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Slice 3.5 — Workout action sheet */}
      <Modal visible={!!wActionOpen} transparent animationType="fade" onRequestClose={() => setWActionOpen(null)}>
        <Pressable style={styles.modalScrim} onPress={() => setWActionOpen(null)}>
          <Pressable style={styles.modalCard} onPress={(e) => e.stopPropagation?.()}>
            <Text style={styles.modalTitle}>Manage workout</Text>
            <Text style={styles.modalBody}>
              {wActionOpen?.title || "Session"} · {wActionOpen?.date}
              {wActionOpen?.coach_locked ? " · 🔒 LOCKED" : ""}
              {wActionOpen?.approved ? " · ✓ APPROVED" : ""}
            </Text>
            <View style={{ gap: 8, marginTop: 14 }}>
              {!wActionOpen?.approved ? (
                <Pressable
                  testID="w-approve"
                  disabled={wBusy}
                  onPress={() => doWorkoutApprove(wActionOpen)}
                  style={[styles.dEditBtn, { borderColor: theme.color.green }]}
                >
                  <Ionicons name="checkmark-circle" size={14} color={theme.color.green} />
                  <Text style={[styles.dEditBtnT, { color: theme.color.green }]}>APPROVE</Text>
                </Pressable>
              ) : null}
              <Pressable
                testID="w-lock"
                disabled={wBusy}
                onPress={() => doWorkoutLockToggle(wActionOpen)}
                style={styles.dEditBtn}
              >
                <Ionicons name={wActionOpen?.coach_locked ? "lock-open" : "lock-closed"} size={14} color={theme.color.text} />
                <Text style={styles.dEditBtnT}>{wActionOpen?.coach_locked ? "UNLOCK" : "LOCK"}</Text>
              </Pressable>
              <Pressable
                testID="w-move"
                disabled={wBusy}
                onPress={() => { setWMoveDate(""); setWMoveOpen(wActionOpen); }}
                style={styles.dEditBtn}
              >
                <Ionicons name="calendar" size={14} color={theme.color.text} />
                <Text style={styles.dEditBtnT}>MOVE / SWAP DATE</Text>
              </Pressable>
              <Pressable
                testID="w-regen"
                disabled={wBusy || wActionOpen?.coach_locked}
                onPress={() => { setWRegenNote(""); setWRegenOpen(wActionOpen); }}
                style={[styles.dEditBtn, wActionOpen?.coach_locked && { opacity: 0.4 }]}
              >
                <Ionicons name="refresh" size={14} color={theme.color.brand} />
                <Text style={[styles.dEditBtnT, { color: theme.color.brand }]}>REGENERATE</Text>
              </Pressable>
              <Pressable
                testID="w-deep-edit"
                disabled={wBusy || wActionOpen?.coach_locked}
                onPress={() => { const wid = wActionOpen.id; setWActionOpen(null); router.push(`/coach/workout/edit/${wid}`); }}
                style={[styles.dEditBtn, { borderColor: theme.color.brand }, wActionOpen?.coach_locked && { opacity: 0.4 }]}
              >
                <Ionicons name="construct" size={14} color={theme.color.brand} />
                <Text style={[styles.dEditBtnT, { color: theme.color.brand }]}>DEEP EDIT (SETS / EXERCISES)</Text>
              </Pressable>
              <Pressable
                testID="w-open"
                onPress={() => { setWActionOpen(null); router.push(`/workout/${wActionOpen.id}`); }}
                style={styles.dEditBtn}
              >
                <Ionicons name="open-outline" size={14} color={theme.color.text} />
                <Text style={styles.dEditBtnT}>OPEN WORKOUT (CLIENT VIEW)</Text>
              </Pressable>
            </View>
            <Pressable testID="w-cancel" onPress={() => setWActionOpen(null)} style={[styles.modalBtnGhost, { marginTop: 12 }]}>
              <Text style={styles.modalBtnGhostText}>CLOSE</Text>
            </Pressable>
          </Pressable>
        </Pressable>
      </Modal>

      {/* Slice 3.5 — Move workout modal */}
      <Modal visible={!!wMoveOpen} transparent animationType="fade" onRequestClose={() => setWMoveOpen(null)}>
        <View style={styles.modalScrim}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Move workout</Text>
            <Text style={styles.modalBody}>
              Currently on {wMoveOpen?.date}. Enter the new date (YYYY-MM-DD). If a workout already exists on the target day it will be swapped.
            </Text>
            <TextInput
              testID="w-move-input"
              style={styles.modalInput}
              value={wMoveDate}
              onChangeText={setWMoveDate}
              placeholder="YYYY-MM-DD"
              placeholderTextColor={theme.color.textDim}
              autoCorrect={false}
              autoCapitalize="none"
            />
            <View style={styles.modalRow}>
              <Pressable testID="w-move-cancel" style={styles.modalBtnGhost} onPress={() => setWMoveOpen(null)}>
                <Text style={styles.modalBtnGhostText}>CANCEL</Text>
              </Pressable>
              <Pressable
                testID="w-move-confirm"
                onPress={doWorkoutMove}
                disabled={wBusy}
                style={[styles.modalBtn, wBusy && { opacity: 0.55 }]}
              >
                {wBusy ? <ActivityIndicator color="#fff" /> : <Text style={styles.modalBtnText}>MOVE</Text>}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Slice 3.5 — Regenerate single workout modal */}
      <Modal visible={!!wRegenOpen} transparent animationType="fade" onRequestClose={() => setWRegenOpen(null)}>
        <View style={styles.modalScrim}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Regenerate this workout</Text>
            <Text style={styles.modalBody}>
              We&apos;ll rebuild just {wRegenOpen?.date} using the latest programme context. Client-set adaptations on this day are respected. Coach-locked sessions are refused.
            </Text>
            <Text style={[styles.progLabel, { marginTop: 12 }]}>NOTE (OPTIONAL)</Text>
            <TextInput
              testID="w-regen-note"
              style={styles.modalInput}
              value={wRegenNote}
              onChangeText={setWRegenNote}
              placeholder="e.g. tired from red-eye, dial back"
              placeholderTextColor={theme.color.textDim}
              multiline
            />
            <View style={styles.modalRow}>
              <Pressable testID="w-regen-cancel" style={styles.modalBtnGhost} onPress={() => setWRegenOpen(null)}>
                <Text style={styles.modalBtnGhostText}>CANCEL</Text>
              </Pressable>
              <Pressable
                testID="w-regen-confirm"
                onPress={doWorkoutRegenSingle}
                disabled={wBusy}
                style={[styles.modalBtn, wBusy && { opacity: 0.55 }]}
              >
                {wBusy ? <ActivityIndicator color="#fff" /> : <Text style={styles.modalBtnText}>REGENERATE</Text>}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Slice 3.5 — Roster day edit modal */}
      <Modal visible={!!rDayEditOpen} transparent animationType="slide" onRequestClose={() => setRDayEditOpen(null)}>
        <View style={styles.modalScrim}>
          <View style={[styles.modalCard, { maxHeight: 620 }]}>
            <Text style={styles.modalTitle}>Edit roster day</Text>
            <Text style={styles.modalBody}>{rDayEditOpen?.date}</Text>

            <ScrollView style={{ maxHeight: 440, marginTop: 8 }}>
              <Text style={[styles.progLabel, { marginTop: 10 }]}>DUTY TYPE</Text>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6, paddingVertical: 6 }}>
                {DAY_TYPES.map((dt) => {
                  const active = rDayDraft.day_type === dt;
                  return (
                    <Pressable
                      key={dt}
                      testID={`r-daytype-${dt}`}
                      onPress={() => setRDayDraft((d) => ({ ...d, day_type: dt }))}
                      style={[styles.ctrlChip, active && styles.ctrlChipActive]}
                    >
                      <Text style={[styles.ctrlChipT, active && { color: "#fff" }]}>{dt}</Text>
                    </Pressable>
                  );
                })}
              </ScrollView>

              <Text style={[styles.progLabel, { marginTop: 10 }]}>LOAD</Text>
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                {LOAD_OPTIONS.map((l) => {
                  const active = rDayDraft.load === l.key;
                  return (
                    <Pressable
                      key={l.key}
                      testID={`r-load-${l.key}`}
                      onPress={() => setRDayDraft((d) => ({ ...d, load: l.key }))}
                      style={[styles.ctrlChip, active && { backgroundColor: l.color, borderColor: l.color }]}
                    >
                      <Text style={[styles.ctrlChipT, active && { color: "#fff" }]}>{l.label}</Text>
                    </Pressable>
                  );
                })}
              </View>

              <Text style={[styles.progLabel, { marginTop: 12 }]}>LAYOVER CITY</Text>
              <TextInput
                testID="r-layover-city"
                style={styles.modalInput}
                value={rDayDraft.layover_city || ""}
                onChangeText={(v) => setRDayDraft((d) => ({ ...d, layover_city: v }))}
                placeholder="e.g. New York"
                placeholderTextColor={theme.color.textDim}
              />

              <Text style={[styles.progLabel, { marginTop: 12 }]}>COACH NOTES</Text>
              <TextInput
                testID="r-notes"
                style={[styles.modalInput, { minHeight: 70 }]}
                value={rDayDraft.notes || ""}
                onChangeText={(v) => setRDayDraft((d) => ({ ...d, notes: v }))}
                placeholder="Extra context for the client and the programme"
                placeholderTextColor={theme.color.textDim}
                multiline
              />

              {rDayEditOpen?.hotel_name ? (
                <>
                  <Text style={[styles.progLabel, { marginTop: 12 }]}>HOTEL</Text>
                  <Text style={{ color: theme.color.text, fontSize: 13, marginTop: 4 }}>{rDayEditOpen.hotel_name}</Text>
                  <Pressable
                    testID="r-clear-hotel"
                    onPress={doClearHotel}
                    disabled={rDayBusy}
                    style={[styles.dEditBtn, { marginTop: 6, alignSelf: "flex-start", borderColor: "#c85450" }]}
                  >
                    <Ionicons name="close" size={13} color="#c85450" />
                    <Text style={[styles.dEditBtnT, { color: "#c85450" }]}>CLEAR HOTEL</Text>
                  </Pressable>
                </>
              ) : null}
            </ScrollView>

            <View style={styles.modalRow}>
              <Pressable testID="r-day-cancel" style={styles.modalBtnGhost} onPress={() => setRDayEditOpen(null)}>
                <Text style={styles.modalBtnGhostText}>CANCEL</Text>
              </Pressable>
              <Pressable
                testID="r-day-save"
                onPress={doSaveRosterDay}
                disabled={rDayBusy}
                style={[styles.modalBtn, rDayBusy && { opacity: 0.55 }]}
              >
                {rDayBusy ? <ActivityIndicator color="#fff" /> : <Text style={styles.modalBtnText}>SAVE</Text>}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Plan C7 — Regenerate Programme preview modal */}
      <Modal visible={!!regenPreview} transparent animationType="slide" onRequestClose={() => setRegenPreview(null)}>
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Regeneration preview</Text>
              <Pressable onPress={() => setRegenPreview(null)} hitSlop={12}>
                <Ionicons name="close" size={22} color={theme.color.text} />
              </Pressable>
            </View>
            <ScrollView style={{ maxHeight: 460 }}>
              {regenPreview && (
                <>
                  <Text style={styles.tlDetail}>
                    Goal: {regenPreview.goal_key || "—"} · Target: {regenPreview.target_sessions_per_week || "—"}/wk · First new workout: {regenPreview.first_new_workout_date || "—"}
                  </Text>
                  <View style={{ flexDirection: "row", gap: 10, marginTop: 12 }}>
                    <View style={{ flex: 1, backgroundColor: theme.color.surface, padding: 10, borderRadius: 8 }}>
                      <Text style={styles.ovLbl}>OLD</Text>
                      <Text style={styles.ovVal}>{regenPreview.old_summary?.total_workouts || 0}</Text>
                      <Text style={styles.ovSub}>workouts</Text>
                      <Text style={styles.tlDetail}>keys: {regenPreview.old_summary?.key_sessions || 0}</Text>
                    </View>
                    <View style={{ flex: 1, backgroundColor: "#0d2018", padding: 10, borderRadius: 8, borderWidth: 1, borderColor: theme.color.green }}>
                      <Text style={styles.ovLbl}>NEW</Text>
                      <Text style={styles.ovVal}>{regenPreview.new_summary?.total_workouts || 0}</Text>
                      <Text style={styles.ovSub}>workouts</Text>
                      <Text style={styles.tlDetail}>keys: {regenPreview.new_summary?.key_sessions || 0}</Text>
                    </View>
                  </View>
                  <View style={{ flexDirection: "row", gap: 10, marginTop: 12 }}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.ovLbl}>WOULD CHANGE</Text>
                      <Text style={styles.ovVal}>{regenPreview.would_change || 0}</Text>
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.ovLbl}>WOULD KEEP</Text>
                      <Text style={styles.ovVal}>{regenPreview.would_keep || 0}</Text>
                    </View>
                  </View>
                  <View style={{ marginTop: 12 }}>
                    <Text style={styles.ovLbl}>PRESERVED</Text>
                    <Text style={styles.tlDetail}>Completed workouts: {regenPreview.preserved?.completed_workouts || 0} · Coach-locked: {regenPreview.preserved?.coach_locked_workouts || 0}</Text>
                  </View>
                </>
              )}
            </ScrollView>
            <View style={{ flexDirection: "row", gap: 10, marginTop: 12 }}>
              <Pressable onPress={() => setRegenPreview(null)} style={styles.progBtnAlt}>
                <Text style={styles.progBtnAltText}>CANCEL</Text>
              </Pressable>
              <Pressable onPress={applyRegenProgramme} disabled={regenBusy} style={[styles.progBtn, regenBusy && { opacity: 0.6 }]}>
                {regenBusy ? <ActivityIndicator color="#fff" /> : <Text style={styles.progBtnText}>APPLY REGENERATION</Text>}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const Row = ({ label, value }: any) => (
  <View style={styles.row}><Text style={styles.rowL}>{label}</Text><Text style={styles.rowV}>{value}</Text></View>
);

function logColor(category: string): string {
  switch (category) {
    case "message": return theme.color.brand;
    case "controls": return theme.color.amber;
    case "programme": return theme.color.brand;
    case "script": return theme.color.brand;
    case "workout": return theme.color.green;
    default: return theme.color.textDim;
  }
}

function sbStatusColor(status: string): any {
  if (status === "called_out") return { backgroundColor: "#c94a4a" };
  if (status === "not_called_out") return { backgroundColor: theme.color.green };
  if (status === "cancelled") return { backgroundColor: theme.color.textDim };
  if (status === "too_tired") return { backgroundColor: theme.color.amber };
  return { backgroundColor: theme.color.brand };
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  headerT: { color: theme.color.text, fontSize: 14, letterSpacing: 2, fontWeight: "900" },
  name: { color: theme.color.text, fontSize: 26, fontWeight: "900" },
  email: { color: theme.color.textMuted, marginTop: 2 },
  // Iter 81 Phase 4 — coach client progression pill + coach note
  progRow: { marginTop: theme.space.sm, marginBottom: theme.space.md, gap: 4 },
  progPill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    alignSelf: "flex-start",
    paddingHorizontal: 10, paddingVertical: 4,
    borderRadius: 999,
    backgroundColor: theme.color.brandTint,
  },
  progPillText: { fontSize: 10, fontWeight: "800", letterSpacing: 0.6, color: theme.color.brand },
  progNote: {
    fontSize: 12, color: theme.color.textMuted, lineHeight: 17, marginTop: 2,
  },
  actionRow: { flexDirection: "row", gap: 8, marginTop: theme.space.md },
  actionBtn: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: theme.color.brand, paddingVertical: 10, paddingHorizontal: 14, borderRadius: theme.radius.md },
  actionText: { color: "#fff", fontWeight: "800", letterSpacing: 1.5, fontSize: 11 },
  card: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, padding: theme.space.md, marginTop: theme.space.md },
  sect: { color: theme.color.textMuted, letterSpacing: 2, fontSize: 10, fontWeight: "800", marginBottom: theme.space.sm },
  row: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 6, borderTopWidth: 1, borderTopColor: theme.color.divider },
  rowL: { color: theme.color.textMuted, fontSize: 13 },
  rowV: { color: theme.color.text, fontWeight: "700", fontSize: 13 },
  dayRow: { flexDirection: "row", alignItems: "center", paddingVertical: 8, borderTopWidth: 1, borderTopColor: theme.color.divider },
  bar: { width: 4, height: 24, marginRight: 10, borderRadius: 2 },
  dText: { color: theme.color.text, fontSize: 13, letterSpacing: 1, fontWeight: "700" },
  fText: { color: theme.color.brand, fontSize: 12, fontWeight: "600" },
  wRow: { flexDirection: "row", alignItems: "center", paddingVertical: 10, borderTopWidth: 1, borderTopColor: theme.color.divider },
  wTitle: { color: theme.color.text, fontSize: 14, fontWeight: "700" },
  wMeta: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },
  approved: { color: theme.color.green, fontSize: 20, marginRight: 4 },
  pending: { color: theme.color.amber, fontSize: 10, fontWeight: "800", letterSpacing: 1.5 },
  ovRow: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 8, borderTopWidth: 1, borderTopColor: theme.color.divider },
  ovLeft: { flexDirection: "row", alignItems: "center", gap: 6, width: 118 },
  ovDate: { color: theme.color.text, fontSize: 11, fontWeight: "700", letterSpacing: 0.5 },
  ovTags: { color: theme.color.amber, fontSize: 10, fontWeight: "800", letterSpacing: 1 },
  ovNotes: { color: theme.color.textMuted, fontSize: 11, fontStyle: "italic", marginTop: 2 },
  ovMore: { color: theme.color.textDim, fontSize: 10, fontWeight: "700", letterSpacing: 1, marginTop: 6, textAlign: "center" },
  ctrlBlock: { paddingVertical: 10, borderTopWidth: 1, borderTopColor: theme.color.divider },
  ctrlLabel: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700", letterSpacing: 0.5, marginBottom: 6 },
  ctrlRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  ctrlChip: { paddingHorizontal: 10, paddingVertical: 7, borderRadius: theme.radius.pill, backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border },
  ctrlChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  ctrlChipT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700" },
  logRow: { flexDirection: "row", gap: 10, paddingVertical: 10, borderTopWidth: 1, borderTopColor: theme.color.divider },
  logDot: { width: 6, height: 6, borderRadius: 3, marginTop: 6 },
  logCat: { fontSize: 9, fontWeight: "800", letterSpacing: 1.5 },
  logDate: { color: theme.color.textDim, fontSize: 10 },
  logTitle: { color: theme.color.text, fontSize: 12, fontWeight: "700", marginTop: 2 },
  logDesc: { color: theme.color.textMuted, fontSize: 11, marginTop: 2, lineHeight: 15 },
  habitRow: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 10, borderTopWidth: 1, borderTopColor: theme.color.divider },
  habitTitle: { color: theme.color.text, fontSize: 13, fontWeight: "700" },
  habitReason: { color: theme.color.textMuted, fontSize: 11, marginTop: 2, lineHeight: 15 },
  habitMeta: { color: theme.color.textDim, fontSize: 9, fontWeight: "800", letterSpacing: 1, marginTop: 4 },
  completionPct: { fontSize: 14, fontWeight: "900" },
  streakT: { color: theme.color.brand, fontSize: 10, fontWeight: "800", letterSpacing: 1 },
  streakChip: { flexDirection: "row", alignItems: "center", gap: 3, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 10, borderWidth: 1, borderColor: theme.color.brand },
  pausedHead: { color: theme.color.textDim, fontSize: 9, fontWeight: "800", letterSpacing: 1.5, marginTop: 14, marginBottom: 4 },
  latestReviewCard: { marginTop: 12, padding: 10, backgroundColor: theme.color.brandTint, borderRadius: 8, borderWidth: 1, borderColor: theme.color.brand },
  blockHead: { color: theme.color.brand, fontSize: 9, fontWeight: "900", letterSpacing: 1.5 },
  blockBody: { color: theme.color.text, fontSize: 12, marginTop: 4, lineHeight: 16 },
  blockMeta: { color: theme.color.textMuted, fontSize: 10, marginTop: 4 },
  sbBadge: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 4 },
  sbBadgeT: { color: "#fff", fontSize: 9, fontWeight: "900", letterSpacing: 1 },
  // Phase 4: Programme card
  progCard: { borderColor: theme.color.brand, borderWidth: 1 },
  progCardReview: { borderColor: theme.color.amber, borderWidth: 2 },
  progHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  progStatusPill: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: theme.radius.sm },
  progStatusPillText: { color: "#fff", fontSize: 9, fontWeight: "800", letterSpacing: 1 },
  progRow: { flexDirection: "row", gap: 12, marginTop: 8 },
  progCell: { flex: 1 },
  progLabel: { color: theme.color.textDim, fontSize: 9, fontWeight: "800", letterSpacing: 1.5 },
  progValue: { color: theme.color.text, fontSize: 15, fontWeight: "800", marginTop: 2 },
  progFocus: { color: theme.color.textMuted, fontSize: 12, marginTop: 10, lineHeight: 16, fontStyle: "italic" },
  progContext: { marginTop: 10, padding: 10, backgroundColor: theme.color.surface, borderRadius: theme.radius.sm, borderWidth: 1, borderColor: theme.color.border },
  progContextText: { color: theme.color.text, fontSize: 12, marginTop: 4, lineHeight: 16 },
  progErrText: { color: theme.color.textMuted, fontSize: 12, marginTop: 2 },
  progActions: { flexDirection: "row", gap: 8, marginTop: 14 },
  progBtn: { flex: 1, flexDirection: "row", justifyContent: "center", alignItems: "center", gap: 6, backgroundColor: theme.color.brand, paddingVertical: 12, borderRadius: theme.radius.md },
  progBtnText: { color: "#fff", fontSize: 11, fontWeight: "800", letterSpacing: 1.5 },
  progBtnAlt: { flex: 1, flexDirection: "row", justifyContent: "center", alignItems: "center", gap: 6, backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.green, paddingVertical: 12, borderRadius: theme.radius.md },
  progBtnAltText: { color: theme.color.green, fontSize: 11, fontWeight: "800", letterSpacing: 1.5 },
  progEmpty: { color: theme.color.textMuted, fontSize: 13, lineHeight: 18 },
  histChip: { minWidth: 100, padding: 8, borderRadius: theme.radius.sm, borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface },
  histChipTop: { color: theme.color.textMuted, fontSize: 9, fontWeight: "800", letterSpacing: 1 },
  histChipMid: { color: theme.color.text, fontSize: 12, fontWeight: "800", marginTop: 3 },
  histChipSub: { color: theme.color.textDim, fontSize: 9, fontWeight: "700", letterSpacing: 1, marginTop: 3 },
  modalScrim: { flex: 1, backgroundColor: "rgba(0,0,0,0.6)", alignItems: "center", justifyContent: "center", padding: theme.space.lg },
  modalCard: { width: "100%", maxWidth: 420, backgroundColor: theme.color.surface, borderRadius: theme.radius.md, padding: theme.space.lg, borderWidth: 1, borderColor: theme.color.border },
  modalTitle: { color: theme.color.text, fontSize: 18, fontWeight: "900" },
  modalBody: { color: theme.color.textMuted, fontSize: 13, marginTop: 8, lineHeight: 18 },
  modalInput: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, color: theme.color.text, padding: 12, borderWidth: 1, borderColor: theme.color.border, fontSize: 13, marginTop: 6, minHeight: 60 },
  modalRow: { flexDirection: "row", gap: 8, marginTop: 16 },
  modalBtn: { flex: 1, backgroundColor: theme.color.brand, paddingVertical: 12, borderRadius: theme.radius.md, alignItems: "center" },
  modalBtnText: { color: "#fff", fontWeight: "800", letterSpacing: 1.5, fontSize: 12 },
  modalBtnGhost: { flex: 1, backgroundColor: "transparent", borderWidth: 1, borderColor: theme.color.border, paddingVertical: 12, borderRadius: theme.radius.md, alignItems: "center" },
  modalBtnGhostText: { color: theme.color.text, fontWeight: "800", letterSpacing: 1.5, fontSize: 12 },
  // Slice 1: Admin card
  adminCard: { borderColor: "#c85450", borderWidth: 1 },
  adminActions: { flexDirection: "row", gap: 8, marginTop: 12, flexWrap: "wrap" },
  adminBtnPrimary: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: theme.color.brand, paddingVertical: 10, paddingHorizontal: 14, borderRadius: theme.radius.md },
  adminBtnPrimaryText: { color: "#fff", fontSize: 11, fontWeight: "800", letterSpacing: 1.5 },
  adminBtnAlt: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, paddingVertical: 10, paddingHorizontal: 14, borderRadius: theme.radius.md },
  adminBtnAltText: { color: theme.color.text, fontSize: 11, fontWeight: "800", letterSpacing: 1.5 },
  adminBtnDanger: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: "transparent", borderWidth: 1, borderColor: "#c85450", paddingVertical: 10, paddingHorizontal: 14, borderRadius: theme.radius.md },
  adminBtnDangerText: { color: "#c85450", fontSize: 11, fontWeight: "800", letterSpacing: 1.5 },
  auditRow: { paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: theme.color.border },
  auditAction: { color: theme.color.text, fontSize: 11, fontWeight: "800", letterSpacing: 1.2 },
  auditMeta: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },
  auditWhen: { color: theme.color.textDim, fontSize: 10, marginTop: 2 },
  // Slice 3: tab bar
  cdTab: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: theme.radius.pill, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  cdTabActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  cdTabText: { color: theme.color.textMuted, fontSize: 10, fontWeight: "800", letterSpacing: 1.2 },
  // Slice 3.5: deep-edit affordances
  wManageBtn: { padding: 8, marginLeft: 4, borderRadius: theme.radius.sm, backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border },
  dEditBtn: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 12, paddingHorizontal: 14, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface2 },
  dEditBtnT: { color: theme.color.text, fontSize: 12, fontWeight: "800", letterSpacing: 1.2 },
  hText: { color: theme.color.textMuted, fontSize: 11, fontWeight: "600", marginTop: 2 },
  // Plan C3 — Programme Overview enrichment + Timeline styles
  ovLbl: { color: theme.color.textMuted, fontSize: 9, letterSpacing: 1.0, fontWeight: "800" },
  ovVal: { color: theme.color.text, fontSize: 18, fontWeight: "900", marginTop: 3 },
  ovSub: { color: theme.color.textMuted, fontSize: 10, marginTop: 2 },
  sourcePill: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 4, borderWidth: 1, borderColor: theme.color.line, backgroundColor: theme.color.surface },
  sourcePillT: { color: theme.color.textMuted, fontSize: 9, letterSpacing: 1, fontWeight: "800" },
  tlRow: { flexDirection: "row", gap: 10, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: theme.color.line },
  tlIconWrap: { width: 24, height: 24, borderRadius: 12, alignItems: "center", justifyContent: "center", backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.line, marginTop: 1 },
  tlTitle: { color: theme.color.text, fontSize: 13, fontWeight: "700" },
  tlDetail: { color: theme.color.textMuted, fontSize: 12, marginTop: 2, lineHeight: 16 },
  tlMeta: { color: theme.color.textMuted, fontSize: 10, marginTop: 3, letterSpacing: 0.6 },
  // Iter 92 (Phase 2, Task 2.6) — LIVE SIGNALS
  liveCard: { marginTop: 10, padding: 12, borderRadius: theme.radius.md, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  liveHead: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 10 },
  liveTitle: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.4, flex: 1 },
  liveDeloadPill: { backgroundColor: theme.color.amber || "#e5a337", paddingHorizontal: 8, paddingVertical: 3, borderRadius: theme.radius.pill },
  liveDeloadT: { color: "#111", fontSize: 9, fontWeight: "900", letterSpacing: 1.2 },
  liveGrid: { flexDirection: "row", gap: 8 },
  liveCell: { flex: 1, alignItems: "center", padding: 8, borderRadius: theme.radius.sm, backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.divider },
  liveVal: { color: theme.color.text, fontSize: 16, fontWeight: "900" },
  liveLabel: { color: theme.color.textMuted, fontSize: 9, letterSpacing: 0.8, fontWeight: "700", marginTop: 2, textAlign: "center" },
  liveChipRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 10 },
  liveChipRed: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 3, borderRadius: theme.radius.pill, backgroundColor: "rgba(200,84,80,0.14)", borderWidth: 1, borderColor: "rgba(200,84,80,0.45)" },
  liveChipRedT: { color: "#c85450", fontSize: 9, fontWeight: "900", letterSpacing: 1 },
  liveHint: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700", marginTop: 8, fontStyle: "italic" },
  liveSub: { color: theme.color.textMuted, fontSize: 9, fontWeight: "800", letterSpacing: 1.2, marginBottom: 4 },
  directiveRow: { flexDirection: "row", alignItems: "flex-start", gap: 8, paddingVertical: 4 },
  directiveT: { color: theme.color.text, fontSize: 12, flex: 1, lineHeight: 17 },
  directiveInputRow: { flexDirection: "row", alignItems: "flex-end", gap: 8, marginTop: 10 },
  directiveInput: { flex: 1, minHeight: 38, maxHeight: 100, backgroundColor: theme.color.surface, borderRadius: theme.radius.sm, borderWidth: 1, borderColor: theme.color.border, padding: 8, color: theme.color.text, fontSize: 12 },
  directiveAddBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 8, borderRadius: theme.radius.sm, backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.brand },
  directiveAddT: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1.2 },
});
