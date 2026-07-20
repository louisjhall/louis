import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl, Alert, Modal, TextInput } from "react-native";
import { useLocalSearchParams, useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { useAuth } from "@/src/lib/auth";
import { theme, loadColor } from "@/src/lib/theme";
import { StatusBadge, deriveStatus } from "@/src/components/StatusBadge";

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
  const [permDeleteOpen, setPermDeleteOpen] = useState(false);
  const [permDeleteText, setPermDeleteText] = useState("");
  const [adminBusy, setAdminBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [detail, ctrl, log, habits, standby, prog, hist, audit] = await Promise.all([
        api<any>(`/coach/clients/${id}`),
        api<{ controls: Controls }>(`/coach/clients/${id}/controls`).catch(() => ({ controls: null as any })),
        api<{ entries: any[] }>(`/coach/clients/${id}/change-log`).catch(() => ({ entries: [] })),
        api<any>(`/coach/clients/${id}/habits`).catch(() => null),
        api<any>(`/coach/clients/${id}/standby`).catch(() => null),
        api<any>(`/coach/clients/${id}/programme`).catch(() => null),
        api<any>(`/coach/clients/${id}/programme/history`).catch(() => ({ programmes: [] })),
        api<{ entries: any[] }>(`/admin/clients/${id}/audit-log?limit=25`).catch(() => ({ entries: [] })),
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

  // ---- Admin lifecycle actions ----
  const runAdmin = async (label: string, path: string, body?: any) => {
    setAdminBusy(label);
    try {
      await api(`/admin/clients/${id}${path}`, { method: "POST", body: body || {} });
      await load();
    } catch (e: any) {
      Alert.alert(`${label} failed`, e?.message || "Try again.");
    } finally {
      setAdminBusy(null);
    }
  };

  const askArchive = () => {
    Alert.alert(
      "Archive this client?",
      "This will move them out of the active client list. Their data will be kept and can be restored later.",
      [
        { text: "Cancel", style: "cancel" },
        { text: "Archive Only",         onPress: () => runAdmin("Archive",  "/archive", { mode: "archive_only" }) },
        { text: "Archive & Pause",      style: "destructive",
          onPress: () => runAdmin("Archive & Pause", "/archive", { mode: "archive_pause" }) },
      ],
    );
  };

  const askRestore = () => runAdmin("Restore", "/restore");

  const askSoftDelete = () => {
    Alert.alert(
      "Delete this client?",
      "This will disable their access and remove them from your active dashboard. Their data will be kept temporarily unless you choose permanent deletion.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete Client",
          style: "destructive",
          onPress: () => runAdmin("Soft Delete", "/soft-delete"),
        },
      ],
    );
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

  const isAdmin = !!(currentUser?.is_admin || currentUser?.role === "admin");

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

        <View style={styles.actionRow}>
          <Pressable testID="cd-script-btn" onPress={() => router.push(`/coach/scripts/${client.id}`)} style={styles.actionBtn}>
            <Ionicons name="videocam" size={16} color="#fff" />
            <Text style={styles.actionText}>WEEKLY SCRIPT</Text>
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
        </View>

        {/* Phase 4: Programme summary + Regenerate + Approve */}
        <View testID="programme-card" style={[styles.card, styles.progCard, programme?.validation_status === "needs_review" && !programme?.coach_approved && styles.progCardReview]}>
          <View style={styles.progHeader}>
            <Text style={styles.sect}>PROGRAMME</Text>
            {programme?.validation_status === "needs_review" && !programme?.coach_approved ? (
              <View style={[styles.progStatusPill, { backgroundColor: theme.color.amber }]}>
                <Text style={styles.progStatusPillText}>NEEDS REVIEW</Text>
              </View>
            ) : programme?.coach_approved ? (
              <View style={[styles.progStatusPill, { backgroundColor: theme.color.green }]}>
                <Text style={styles.progStatusPillText}>APPROVED</Text>
              </View>
            ) : programme ? (
              <View style={[styles.progStatusPill, { backgroundColor: theme.color.green }]}>
                <Text style={styles.progStatusPillText}>OK</Text>
              </View>
            ) : null}
          </View>

          {programme ? (
            <>
              <View style={styles.progRow}>
                <View style={styles.progCell}>
                  <Text style={styles.progLabel}>GOAL</Text>
                  <Text style={styles.progValue}>{programme.goal_label || programme.goal_key || "—"}</Text>
                </View>
                <View style={styles.progCell}>
                  <Text style={styles.progLabel}>PHASE</Text>
                  <Text style={styles.progValue}>{programme.phase?.label || "—"}</Text>
                </View>
              </View>
              <View style={styles.progRow}>
                <View style={styles.progCell}>
                  <Text style={styles.progLabel}>WEEK</Text>
                  <Text style={styles.progValue}>{programme.week_index || "—"}</Text>
                </View>
                <View style={styles.progCell}>
                  <Text style={styles.progLabel}>TARGET</Text>
                  <Text style={styles.progValue}>
                    {programme.target_sessions_per_week ? `${programme.target_sessions_per_week}×/week` : "—"}
                  </Text>
                </View>
              </View>
              {programme.focus_copy ? (
                <Text style={styles.progFocus}>{programme.focus_copy}</Text>
              ) : null}
              {programme.roster_context_summary ? (
                <View style={styles.progContext}>
                  <Text style={styles.progLabel}>ROSTER CONTEXT</Text>
                  <Text style={styles.progContextText}>
                    {typeof programme.roster_context_summary === "string"
                      ? programme.roster_context_summary
                      : JSON.stringify(programme.roster_context_summary)}
                  </Text>
                </View>
              ) : null}
              {programme.validation_errors?.length > 0 ? (
                <View style={styles.progContext}>
                  <Text style={[styles.progLabel, { color: theme.color.amber }]}>VALIDATION FLAGS</Text>
                  {programme.validation_errors.map((err: string, i: number) => (
                    <Text key={i} style={styles.progErrText}>· {err}</Text>
                  ))}
                </View>
              ) : null}

              {history.length > 1 ? (
                <View style={{ marginTop: 12 }}>
                  <Text style={styles.progLabel}>HISTORY</Text>
                  <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6, paddingTop: 6 }}>
                    {history.map((h: any) => (
                      <View
                        key={h.id}
                        style={[
                          styles.histChip,
                          h.id === programme.id && { borderColor: theme.color.brand, backgroundColor: theme.color.brandTint },
                        ]}
                      >
                        <Text style={styles.histChipTop}>V{h.version_number} · WK {h.week_index || "—"}</Text>
                        <Text style={styles.histChipMid}>{h.phase?.label || "—"}</Text>
                        <Text style={styles.histChipSub}>
                          {h.validation_status === "needs_review" ? "REVIEW" : h.coach_approved ? "APPROVED" : "OK"}
                        </Text>
                      </View>
                    ))}
                  </ScrollView>
                </View>
              ) : null}

              <View style={styles.progActions}>
                {programme.validation_status === "needs_review" && !programme.coach_approved ? (
                  <Pressable
                    testID="programme-approve"
                    onPress={doApproveProgramme}
                    disabled={approving}
                    style={[styles.progBtnAlt, approving && { opacity: 0.55 }]}
                  >
                    {approving ? <ActivityIndicator color={theme.color.brand} /> : (
                      <>
                        <Ionicons name="checkmark-circle" size={14} color={theme.color.green} />
                        <Text style={styles.progBtnAltText}>APPROVE ANYWAY</Text>
                      </>
                    )}
                  </Pressable>
                ) : null}
                <Pressable
                  testID="programme-regenerate"
                  onPress={() => setRegenOpen(true)}
                  style={styles.progBtn}
                >
                  <Ionicons name="refresh" size={14} color="#fff" />
                  <Text style={styles.progBtnText}>REGENERATE PLAN</Text>
                </Pressable>
              </View>
            </>
          ) : (
            <View style={{ paddingVertical: 12 }}>
              <Text style={styles.progEmpty}>No programme record yet. It's created automatically when the client uploads or confirms a roster.</Text>
              <Pressable
                testID="programme-regenerate-empty"
                onPress={() => setRegenOpen(true)}
                style={[styles.progBtn, { marginTop: 12, alignSelf: "flex-start" }]}
              >
                <Ionicons name="refresh" size={14} color="#fff" />
                <Text style={styles.progBtnText}>GENERATE PLAN</Text>
              </Pressable>
            </View>
          )}
        </View>

        {/* Slice 1: Admin — status pill, archive/pause/restore/delete, audit log. */}
        {isAdmin ? (
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

            <View style={styles.adminActions}>
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
          </View>
        ) : null}

        {controls ? (
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

        <View style={styles.card}>
          <Text style={styles.sect}>PROFILE</Text>
          <Row label="Airline" value={p.airline || "—"} />
          <Row label="Position" value={p.position || "—"} />
          <Row label="Level" value={p.experience_level || "—"} />
          <Row label="Days/week" value={String(p.training_days_per_week || "—")} />
          <Row label="Weight" value={p.weight_kg ? `${p.weight_kg}kg` : "—"} />
          <Row label="Calorie target" value={String(p.calorie_target || "—")} />
        </View>

        {roster ? (
          <View style={styles.card}>
            <Text style={styles.sect}>ROSTER · {roster.week_start}</Text>
            {roster.days?.map((d: any, i: number) => (
              <View key={i} style={styles.dayRow}>
                <View style={[styles.bar, { backgroundColor: loadColor(d.load) }]} />
                <Text style={styles.dText}>{d.date} · {d.type?.toUpperCase()}</Text>
                {d.flights?.[0] && <Text style={styles.fText}>  {d.flights[0].from}→{d.flights[0].to}</Text>}
              </View>
            ))}
          </View>
        ) : (
          <View style={styles.card}><Text style={{ color: theme.color.textMuted }}>No roster uploaded.</Text></View>
        )}

        <View style={styles.card}>
          <Text style={styles.sect}>WEEK PLAN · {workouts.length} WORKOUTS</Text>
          {workouts.length === 0 ? <Text style={{ color: theme.color.textMuted, marginTop: 6 }}>No workouts yet.</Text> :
            workouts.map((w: any) => (
              <Pressable key={w.id} testID={`cd-workout-${w.id}`} onPress={() => router.push(`/workout/${w.id}`)} style={styles.wRow}>
                <View style={[styles.bar, { backgroundColor: loadColor(w.day_load) }]} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.wTitle}>{w.title}</Text>
                  <Text style={styles.wMeta}>{w.date} · {w.exercises?.length || 0} ex</Text>
                </View>
                {w.approved && <Ionicons name="checkmark-circle" size={20} color={theme.color.green} />}
                {!w.approved && <StatusBadge status={deriveStatus(w)} />}
              </Pressable>
            ))
          }
        </View>

        {overrides.length > 0 && (
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

        {checkins.length > 0 && (
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

        {habitsData ? (
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
});
