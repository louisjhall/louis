/**
 * StandbyStatusCard — shows only on standby days. Client can:
 *   - Report Still Waiting / Called Out / Not Called Out / Cancelled / Too Tired / Have Time
 *   - Pick an Atlas standby-friendly workout recommendation
 *   - Restore the original workout if not called out
 */
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, Pressable, Modal, ScrollView, ActivityIndicator, Alert, TextInput } from "react-native";
import { useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Rec = { id: string; kind: string; title: string; duration_min: number; why: string };
type StandbyToday = {
  date: string;
  is_standby: boolean;
  standby: null | {
    type: string;
    start_time?: string;
    end_time?: string;
    location?: string;
    status: string;
    called_out: boolean;
    confirmed_by_client: boolean;
    needs_confirmation: boolean;
    can_train?: string;
  };
  workout: any;
  recommendations: Rec[];
  reason?: string;
};

const TYPE_LABEL: Record<string, string> = {
  home_standby: "Home Standby",
  airport_standby: "Airport Standby",
  reserve: "Reserve",
  short_call: "Short-call Standby",
  long_call: "Long-call Standby",
  night_standby: "Night Standby",
  early_standby: "Early Standby",
  unknown_standby: "Standby",
};

export function StandbyStatusCard() {
  const [data, setData] = useState<StandbyToday | null>(null);
  const [busy, setBusy] = useState(false);
  const [picker, setPicker] = useState(false);
  const [called, setCalled] = useState(false);
  const [reportTime, setReportTime] = useState("");
  const [duty, setDuty] = useState("");
  const [dest, setDest] = useState("");
  const [canTrain, setCanTrain] = useState<"yes" | "no" | "unsure" | "">("");

  const load = useCallback(async () => {
    try {
      const r = await api<StandbyToday>("/standby/today");
      setData(r);
    } catch { /* silent — standby card is best-effort on the home screen */ }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (!data || !data.is_standby || !data.standby) return null;
  const sb = data.standby;

  const setStatus = async (status: string) => {
    setBusy(true);
    try {
      await api("/standby/status", { method: "POST", body: { status } });
      await load();
    } catch (e: any) {
      Alert.alert("Couldn't save", e?.message || "Try again");
    } finally { setBusy(false); }
  };

  const submitCalledOut = async () => {
    setBusy(true);
    try {
      await api("/standby/called-out", {
        method: "POST",
        body: {
          report_time: reportTime || null,
          expected_duty_length_hours: duty ? parseFloat(duty) : null,
          destination: dest || null,
          can_train: canTrain || null,
        },
      });
      setCalled(false);
      setReportTime(""); setDuty(""); setDest(""); setCanTrain("");
      await load();
    } catch (e: any) {
      Alert.alert("Couldn't save", e?.message || "Try again");
    } finally { setBusy(false); }
  };

  const applyRec = async (recId: string) => {
    setBusy(true);
    try {
      await api("/standby/apply-workout", { method: "POST", body: { recommendation_id: recId } });
      setPicker(false);
      await load();
      Alert.alert("Session updated", "Atlas has swapped in a standby-friendly session for today.");
    } catch (e: any) {
      if (e?.status === 409) {
        Alert.alert("Coach review needed", "This session is coach-locked. Louis has been notified.");
        setPicker(false);
      } else {
        Alert.alert("Couldn't apply", e?.message || "Try again");
      }
    } finally { setBusy(false); }
  };

  const restore = async () => {
    setBusy(true);
    try {
      await api("/standby/restore-original", { method: "POST", body: {} });
      await load();
    } catch (e: any) {
      Alert.alert("Couldn't restore", e?.message || "Try again");
    } finally { setBusy(false); }
  };

  return (
    <View style={styles.wrap}>
      <View style={styles.headRow}>
        <View>
          <Text style={styles.head}>STANDBY MODE</Text>
          <Text style={styles.sub}>{TYPE_LABEL[sb.type] || "Standby"}
            {sb.start_time ? ` · ${sb.start_time}` : ""}{sb.end_time ? `–${sb.end_time}` : ""}
            {sb.location ? ` · ${sb.location}` : ""}
          </Text>
        </View>
        <View style={[styles.statusPill, statusColor(sb.status)]}>
          <Text style={styles.statusPillT}>{(sb.status || "waiting").toUpperCase().replace(/_/g, " ")}</Text>
        </View>
      </View>

      {sb.needs_confirmation ? (
        <View style={styles.confirmCard}>
          <Ionicons name="information-circle" size={18} color={theme.color.amber} />
          <Text style={styles.confirmT}>Atlas isn&apos;t sure of your standby type — tap the badge to confirm.</Text>
        </View>
      ) : null}

      <Text style={styles.reason}>{data.reason}</Text>

      <View style={styles.actionGrid}>
        <SBBtn testID="sb-waiting" label="Still Waiting" icon="hourglass" onPress={() => setStatus("waiting")} active={sb.status === "waiting"} disabled={busy} />
        <SBBtn testID="sb-called" label="Called Out" icon="airplane" onPress={() => setCalled(true)} active={sb.status === "called_out"} disabled={busy} accent />
        <SBBtn testID="sb-not-called" label="Not Called Out" icon="checkmark-circle" onPress={() => setStatus("not_called_out")} active={sb.status === "not_called_out"} disabled={busy} />
        <SBBtn testID="sb-cancelled" label="Standby Cancelled" icon="close-circle" onPress={() => setStatus("cancelled")} active={sb.status === "cancelled"} disabled={busy} />
        <SBBtn testID="sb-tired" label="Too Tired To Train" icon="bed" onPress={() => setStatus("too_tired")} active={sb.status === "too_tired"} disabled={busy} />
        <SBBtn testID="sb-time" label="I Have Time To Train" icon="fitness" onPress={() => setStatus("have_time")} active={sb.status === "have_time"} disabled={busy} />
      </View>

      {data.workout && !data.workout.standby_adjusted && data.recommendations?.length > 0 ? (
        <Pressable testID="sb-pick-workout" onPress={() => setPicker(true)} style={styles.ctaBtn} disabled={busy}>
          <Ionicons name="sparkles" size={16} color="#fff" />
          <Text style={styles.ctaT}>PICK A STANDBY-FRIENDLY SESSION</Text>
        </Pressable>
      ) : null}
      {data.workout?.standby_adjusted ? (
        <View style={styles.appliedCard}>
          <View style={{ flex: 1 }}>
            <Text style={styles.appliedHead}>APPLIED · {data.workout.title}</Text>
            <Text style={styles.appliedReason}>{data.workout.standby_reason}</Text>
          </View>
          <Pressable testID="sb-restore" onPress={restore} style={styles.restoreBtn} disabled={busy}>
            <Text style={styles.restoreT}>RESTORE</Text>
          </Pressable>
        </View>
      ) : null}

      {/* Called-out details modal */}
      <Modal visible={called} transparent animationType="slide" onRequestClose={() => setCalled(false)}>
        <Pressable style={styles.modalBg} onPress={() => setCalled(false)}>
          <Pressable style={styles.sheet} onPress={(e) => e.stopPropagation()}>
            <View style={styles.sheetHandle} />
            <Text style={styles.sheetTitle}>Called out — a few quick details</Text>
            <Text style={styles.sheetSub}>Optional. Atlas will adjust today around your duty.</Text>
            <View style={{ gap: 10, marginTop: 12 }}>
              <TextInput testID="co-time" value={reportTime} onChangeText={setReportTime} placeholder="Report time HH:MM" placeholderTextColor={theme.color.textDim} style={styles.input} />
              <TextInput testID="co-duty" value={duty} onChangeText={setDuty} placeholder="Expected duty length (hours)" placeholderTextColor={theme.color.textDim} keyboardType="numeric" style={styles.input} />
              <TextInput testID="co-dest" value={dest} onChangeText={setDest} placeholder="Destination (optional)" placeholderTextColor={theme.color.textDim} style={styles.input} />
              <Text style={styles.subLabel}>Are you able to train today?</Text>
              <View style={{ flexDirection: "row", gap: 6 }}>
                {(["yes", "unsure", "no"] as const).map((v) => (
                  <Pressable key={v} testID={`co-can-${v}`} onPress={() => setCanTrain(v)} style={[styles.canChip, canTrain === v && styles.canChipActive]}>
                    <Text style={[styles.canChipT, canTrain === v && { color: "#fff" }]}>{v.toUpperCase()}</Text>
                  </Pressable>
                ))}
              </View>
            </View>
            <Pressable testID="co-submit" onPress={submitCalledOut} disabled={busy} style={[styles.submitBtn, busy && { opacity: 0.5 }]}>
              {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.submitT}>SAVE</Text>}
            </Pressable>
          </Pressable>
        </Pressable>
      </Modal>

      {/* Recommendation picker */}
      <Modal visible={picker} transparent animationType="slide" onRequestClose={() => setPicker(false)}>
        <Pressable style={styles.modalBg} onPress={() => setPicker(false)}>
          <Pressable style={styles.sheet} onPress={(e) => e.stopPropagation()}>
            <View style={styles.sheetHandle} />
            <Text style={styles.sheetTitle}>Standby-friendly options</Text>
            <Text style={styles.sheetSub}>Pick one — none of these will affect your duty readiness.</Text>
            <ScrollView contentContainerStyle={{ paddingBottom: 20, paddingTop: 12 }}>
              {data.recommendations.map((r) => (
                <Pressable key={r.id} testID={`rec-${r.id}`} onPress={() => applyRec(r.id)} style={styles.recCard} disabled={busy}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.recT}>{r.title}</Text>
                    <Text style={styles.recWhy}>{r.why}</Text>
                    <Text style={styles.recDur}>{r.duration_min > 0 ? `${r.duration_min} min` : "No training today"}</Text>
                  </View>
                  <Ionicons name="chevron-forward" size={18} color={theme.color.brand} />
                </Pressable>
              ))}
            </ScrollView>
          </Pressable>
        </Pressable>
      </Modal>
    </View>
  );
}

function SBBtn({ label, icon, onPress, active, disabled, accent, testID }: any) {
  return (
    <Pressable testID={testID} onPress={onPress} disabled={disabled} style={[styles.sbBtn, active && styles.sbBtnActive, accent && styles.sbBtnAccent, active && accent && styles.sbBtnAccentActive, disabled && { opacity: 0.5 }]}>
      <Ionicons name={icon} size={14} color={active ? "#fff" : (accent ? "#fff" : theme.color.text)} />
      <Text style={[styles.sbBtnT, active && { color: "#fff" }, accent && { color: "#fff" }]}>{label}</Text>
    </Pressable>
  );
}

function statusColor(status: string): any {
  if (status === "called_out") return { backgroundColor: "#c94a4a" };
  if (status === "not_called_out") return { backgroundColor: theme.color.green };
  if (status === "cancelled") return { backgroundColor: theme.color.textDim };
  if (status === "too_tired") return { backgroundColor: theme.color.amber };
  if (status === "have_time") return { backgroundColor: theme.color.brand };
  return { backgroundColor: theme.color.brand };  // waiting
}

const styles = StyleSheet.create({
  wrap: { marginTop: theme.space.md, marginBottom: theme.space.md, padding: 14, borderRadius: 14, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.brand },
  headRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 },
  head: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  sub: { color: theme.color.textMuted, fontSize: 11, marginTop: 3 },
  statusPill: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 4 },
  statusPillT: { color: "#fff", fontSize: 9, fontWeight: "900", letterSpacing: 1 },
  confirmCard: { flexDirection: "row", alignItems: "center", gap: 8, padding: 10, marginTop: 4, marginBottom: 4, borderRadius: 8, backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.amber },
  confirmT: { color: theme.color.textMuted, fontSize: 11, flex: 1 },
  reason: { color: theme.color.text, fontSize: 12, marginTop: 8, marginBottom: 10, lineHeight: 17, fontStyle: "italic" },
  actionGrid: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  sbBtn: { flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: 10, paddingVertical: 9, borderRadius: 8, backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border, minWidth: "31%" },
  sbBtnActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  sbBtnAccent: { backgroundColor: "#c94a4a", borderColor: "#c94a4a" },
  sbBtnAccentActive: { backgroundColor: "#8f3838" },
  sbBtnT: { color: theme.color.text, fontSize: 10, fontWeight: "800", letterSpacing: 0.5, flexShrink: 1 },
  ctaBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, marginTop: 12, paddingVertical: 12, borderRadius: 10, backgroundColor: theme.color.brand },
  ctaT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  appliedCard: { flexDirection: "row", alignItems: "center", gap: 10, marginTop: 12, padding: 12, borderRadius: 10, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand },
  appliedHead: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },
  appliedReason: { color: theme.color.text, fontSize: 11, marginTop: 3, lineHeight: 15 },
  restoreBtn: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 4, backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.brand },
  restoreT: { color: theme.color.brand, fontSize: 9, fontWeight: "900", letterSpacing: 1 },
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  sheet: { backgroundColor: theme.color.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: theme.space.lg, paddingBottom: theme.space.xl, maxHeight: "80%" },
  sheetHandle: { alignSelf: "center", width: 40, height: 4, backgroundColor: theme.color.borderStrong, borderRadius: 2, marginBottom: 12 },
  sheetTitle: { color: theme.color.text, fontSize: 16, fontWeight: "900" },
  sheetSub: { color: theme.color.textMuted, fontSize: 12, marginTop: 4 },
  input: { padding: 12, borderRadius: 8, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, color: theme.color.text, fontSize: 14 },
  subLabel: { color: theme.color.textMuted, fontSize: 12, marginTop: 8 },
  canChip: { flex: 1, alignItems: "center", paddingVertical: 10, borderRadius: 8, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  canChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  canChipT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "800", letterSpacing: 1 },
  submitBtn: { marginTop: 16, paddingVertical: 14, borderRadius: 10, alignItems: "center", backgroundColor: theme.color.brand },
  submitT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 1.5 },
  recCard: { flexDirection: "row", alignItems: "center", gap: 10, padding: 12, marginBottom: 8, borderRadius: 10, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  recT: { color: theme.color.text, fontSize: 14, fontWeight: "800" },
  recWhy: { color: theme.color.textMuted, fontSize: 11, marginTop: 3, lineHeight: 15 },
  recDur: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1, marginTop: 4 },
});
