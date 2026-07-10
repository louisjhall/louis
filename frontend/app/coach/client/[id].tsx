import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl, Alert } from "react-native";
import { useLocalSearchParams, useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
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
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [controls, setControls] = useState<Controls | null>(null);
  const [savingCtrl, setSavingCtrl] = useState(false);
  const [changeLog, setChangeLog] = useState<any[]>([]);
  const [habitsData, setHabitsData] = useState<any>(null);
  const [standbyData, setStandbyData] = useState<any>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [detail, ctrl, log, habits, standby] = await Promise.all([
        api<any>(`/coach/clients/${id}`),
        api<{ controls: Controls }>(`/coach/clients/${id}/controls`).catch(() => ({ controls: null as any })),
        api<{ entries: any[] }>(`/coach/clients/${id}/change-log`).catch(() => ({ entries: [] })),
        api<any>(`/coach/clients/${id}/habits`).catch(() => null),
        api<any>(`/coach/clients/${id}/standby`).catch(() => null),
      ]);
      setData(detail);
      if (ctrl?.controls) setControls(ctrl.controls);
      setChangeLog(log.entries || []);
      setHabitsData(habits);
      setStandbyData(standby);
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
                {w.approved && <Text style={styles.approved}>✓</Text>}
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
                      <Text style={styles.streakT}>🔥 {h.streak}d</Text>
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
  pausedHead: { color: theme.color.textDim, fontSize: 9, fontWeight: "800", letterSpacing: 1.5, marginTop: 14, marginBottom: 4 },
  latestReviewCard: { marginTop: 12, padding: 10, backgroundColor: theme.color.brandTint, borderRadius: 8, borderWidth: 1, borderColor: theme.color.brand },
  blockHead: { color: theme.color.brand, fontSize: 9, fontWeight: "900", letterSpacing: 1.5 },
  blockBody: { color: theme.color.text, fontSize: 12, marginTop: 4, lineHeight: 16 },
  blockMeta: { color: theme.color.textMuted, fontSize: 10, marginTop: 4 },
  sbBadge: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 4 },
  sbBadgeT: { color: "#fff", fontSize: 9, fontWeight: "900", letterSpacing: 1 },
});
