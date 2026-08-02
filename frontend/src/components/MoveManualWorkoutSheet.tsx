/**
 * MoveManualWorkoutSheet — Phase 1.5.
 *
 * Move a manual workout to a different roster date. Shows target-date roster
 * context (day type / available minutes / equipment / burden / existing
 * sessions) and any warnings before the coach confirms.
 *
 * Manual-only. Generated V2 or legacy generated sessions are NOT moved by
 * this flow (Phase 1: use replace_day / suppress_day for generated dates).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, Pressable, StyleSheet, ScrollView, Modal,
  ActivityIndicator, Alert, TextInput, useWindowDimensions,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Props = {
  visible: boolean;
  onClose: () => void;
  onMoved: (result: { workout: any; moved_from: string; moved_to: string; undo_token: any }) => void;
  clientId: string;
  workout: any;                 // the manual workout being moved
  days: any[];                  // Workspace.days[] for the visible month (roster context)
};

function _formatDow(iso: string) {
  const dt = new Date(iso + "T00:00:00");
  return dt.toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short" });
}

export default function MoveManualWorkoutSheet({ visible, onClose, onMoved, clientId, workout, days }: Props) {
  const { width } = useWindowDimensions();
  const isDesktop = width >= 900;
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (visible) {
      setReason("");
      setSelected(null);
    }
  }, [visible]);

  // Only roster dates that are NOT the current workout's date.
  const rosterDates = useMemo(() => (days || []).filter(d => d?.date && d.date !== workout?.date), [days, workout]);

  const target = useMemo(() => (days || []).find(d => d?.date === selected), [days, selected]);
  const originRow = useMemo(() => (days || []).find(d => d?.date === workout?.date), [days, workout]);

  const warnings = useMemo(() => {
    const list: { severity: "warn" | "block"; text: string }[] = [];
    if (!target) return list;
    // Available time
    const avail = target?.schedule?.available_time_min;
    if (typeof avail === "number" && workout?.duration_min && workout.duration_min > avail) {
      list.push({ severity: "warn", text: `Workout is ${workout.duration_min} min but only ${avail} min available on this date.` });
    }
    // Heavy duty
    const burden = target?.schedule?.duty_burden_band;
    if (burden === "heavy" || burden === "extreme") {
      list.push({ severity: "warn", text: `Target date has ${burden} flight-duty burden.` });
    }
    // Existing sessions
    const nGen = (target?.assignments?.length || 0) + ((target?.v1_workouts || []).filter((w: any) => w?.source !== "coach_manual").length || 0);
    const nManual = (target?.v1_workouts || []).filter((w: any) => w?.source === "coach_manual").length || 0;
    if (nGen > 0) list.push({ severity: "warn", text: `Target date already has ${nGen} generated session(s).` });
    if (nManual > 0) list.push({ severity: "block", text: `Target date already has ${nManual} manual workout — a safe swap will be required.` });
    // Flight support isolation note
    const fs = (target?.flight_support || []).length || 0;
    if (fs > 0) list.push({ severity: "warn", text: `Target date has ${fs} Flight Support item(s) — they will remain unchanged.` });
    return list;
  }, [target, workout]);

  const swapRequired = warnings.some(w => w.severity === "block");

  const confirm = useCallback(async () => {
    if (!selected || !workout?.id) return;
    setBusy(true);
    try {
      const body: any = { to_date: selected, reason: reason.trim() || undefined };
      if (swapRequired) body.allow_swap = true;
      if (warnings.length > 0) body.warning_override = warnings.map(w => w.text).join(" · ");
      const res = await api<any>(`/coach/workouts/${workout.id}/manual/move`, {
        method: "POST", body,
      });
      onMoved(res);
      onClose();
    } catch (e: any) {
      Alert.alert("Could not move workout", e?.message || "Please try again.");
    } finally {
      setBusy(false);
    }
  }, [selected, workout, reason, swapRequired, warnings, onMoved, onClose]);

  if (!workout) return null;

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.overlay}>
        <Pressable style={{ flex: 1 }} onPress={onClose} />
        <View style={[styles.sheet, isDesktop ? styles.sheetDesktop : styles.sheetMobile]}>
          <View style={styles.head}>
            <Text style={styles.headTitle} numberOfLines={1}>
              Move: {workout.title || "manual workout"}
            </Text>
            <Pressable onPress={onClose} testID="move-close">
              <Ionicons name="close" size={22} color={theme.color.textHi} />
            </Pressable>
          </View>

          <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: 16, paddingBottom: 100 }}>
            <View style={styles.card}>
              <Text style={styles.cardLabel}>ORIGINAL DATE</Text>
              <Text style={styles.cardValue}>{_formatDow(workout.date)}</Text>
              {originRow?.schedule && (
                <Text style={styles.cardMeta}>
                  {originRow.schedule.classification_label || "—"}
                </Text>
              )}
            </View>

            <Text style={styles.pickLabel}>Choose target date</Text>
            <View style={styles.dateGrid}>
              {rosterDates.map((d: any) => {
                const on = d.date === selected;
                const isRest = !!d.schedule && ["Rest", "Off"].includes(d.schedule.classification_label || "");
                return (
                  <Pressable
                    key={d.date}
                    style={[styles.dateBtn, on && styles.dateBtnActive]}
                    onPress={() => setSelected(d.date)}
                    testID={`move-pick-${d.date}`}
                  >
                    <Text style={[styles.dateBtnText, on && styles.dateBtnTextActive]}>
                      {_formatDow(d.date)}
                    </Text>
                    {d.schedule?.duty_burden_band && (
                      <Text style={styles.dateBtnMeta}>
                        {d.schedule.duty_burden_band}
                      </Text>
                    )}
                    {isRest && <Text style={styles.dateBtnMeta}>rest/off</Text>}
                  </Pressable>
                );
              })}
            </View>

            {target && (
              <View style={styles.card}>
                <Text style={styles.cardLabel}>TARGET DATE CONTEXT</Text>
                <Text style={styles.cardValue}>{_formatDow(target.date)}</Text>
                <Text style={styles.cardMeta}>
                  {target.schedule?.classification_label || "No roster classification"}
                  {typeof target.schedule?.available_time_min === "number" ? ` · ${target.schedule.available_time_min} min available` : ""}
                  {target.schedule?.duty_burden_band ? ` · ${target.schedule.duty_burden_band} burden` : ""}
                </Text>
                {target.schedule?.overnight_location?.city && (
                  <Text style={styles.cardMeta}>Overnight: {target.schedule.overnight_location.city}</Text>
                )}
                <Text style={styles.cardMeta}>
                  Existing sessions on target: {(target.assignments?.length || 0)} generated ·
                  {(target.v1_workouts || []).filter((w: any) => w?.source === "coach_manual").length} manual ·
                  {(target.v1_workouts || []).filter((w: any) => w?.source !== "coach_manual").length} legacy
                  {(target.flight_support?.length || 0) > 0 ? ` · ${target.flight_support.length} Flight Support` : ""}
                </Text>
              </View>
            )}

            {warnings.length > 0 && (
              <View style={styles.warningBox}>
                <Text style={styles.warningTitle}>Warnings</Text>
                {warnings.map((w, i) => (
                  <View key={i} style={styles.warningRow}>
                    <Ionicons
                      name={w.severity === "block" ? "alert-circle" : "warning"}
                      size={14}
                      color={w.severity === "block" ? "#ff6b6b" : "#f5b543"}
                    />
                    <Text style={styles.warningText}>{w.text}</Text>
                  </View>
                ))}
              </View>
            )}

            <Text style={styles.pickLabel}>Reason (optional)</Text>
            <TextInput
              style={styles.reason}
              value={reason}
              onChangeText={setReason}
              placeholder="Why is this workout moving?"
              placeholderTextColor="#666"
              multiline
              testID="move-reason"
            />
            <Text style={styles.footNote}>
              Flight Support and generated sessions on the target date are not touched by this move.
              Manual lock is preserved. You can Undo the move immediately after it completes.
            </Text>
          </ScrollView>

          <View style={styles.footer}>
            <Pressable onPress={onClose} style={styles.cancelBtn} testID="move-cancel">
              <Text style={styles.cancelTxt}>Cancel</Text>
            </Pressable>
            <Pressable
              onPress={confirm}
              disabled={!selected || busy}
              style={[styles.confirmBtn, (!selected || busy) && { opacity: 0.5 }]}
              testID="move-confirm"
            >
              {busy ? <ActivityIndicator color="#000" /> :
                <Text style={styles.confirmTxt}>{swapRequired ? "Confirm & swap" : "Confirm move"}</Text>}
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.6)", flexDirection: "row" },
  sheet: { backgroundColor: theme.color.bg, borderLeftWidth: 1, borderColor: theme.color.border, flexDirection: "column" },
  sheetDesktop: { width: 560, height: "100%" },
  sheetMobile: { width: "100%", height: "92%", borderTopLeftRadius: 16, borderTopRightRadius: 16, alignSelf: "flex-end" },
  head: { flexDirection: "row", alignItems: "center", padding: 16, borderBottomWidth: 1, borderBottomColor: theme.color.border, justifyContent: "space-between" },
  headTitle: { color: theme.color.textHi, fontSize: 16, fontWeight: "700", flex: 1, marginRight: 12 },
  card: { backgroundColor: theme.color.card, padding: 12, borderRadius: 10, borderWidth: 1, borderColor: theme.color.border, marginBottom: 12 },
  cardLabel: { color: theme.color.textDim, fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 4 },
  cardValue: { color: theme.color.textHi, fontSize: 14, fontWeight: "700" },
  cardMeta: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  pickLabel: { color: theme.color.textHi, fontSize: 13, fontWeight: "700", marginBottom: 8, marginTop: 4 },
  dateGrid: { flexDirection: "row", flexWrap: "wrap", marginBottom: 12, gap: 6 },
  dateBtn: { paddingHorizontal: 10, paddingVertical: 8, borderRadius: 8, borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.card, minWidth: 96 },
  dateBtnActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  dateBtnText: { color: theme.color.textHi, fontSize: 12, fontWeight: "600" },
  dateBtnTextActive: { color: "#000" },
  dateBtnMeta: { color: theme.color.textDim, fontSize: 10, marginTop: 2 },
  warningBox: { borderLeftWidth: 3, borderLeftColor: "#f5b543", backgroundColor: "rgba(245,181,67,0.08)", padding: 10, borderRadius: 6, marginBottom: 12 },
  warningTitle: { color: theme.color.textHi, fontWeight: "700", marginBottom: 6, fontSize: 12 },
  warningRow: { flexDirection: "row", alignItems: "flex-start", gap: 6, marginBottom: 4 },
  warningText: { color: theme.color.textHi, fontSize: 12, flex: 1 },
  reason: { minHeight: 56, backgroundColor: theme.color.card, color: theme.color.textHi, borderRadius: 8, padding: 10, borderWidth: 1, borderColor: theme.color.border, marginBottom: 12, textAlignVertical: "top" },
  footNote: { color: theme.color.textDim, fontSize: 11, fontStyle: "italic" },
  footer: { flexDirection: "row", padding: 12, borderTopWidth: 1, borderTopColor: theme.color.border, gap: 8 },
  cancelBtn: { flex: 1, paddingVertical: 12, alignItems: "center", borderWidth: 1, borderColor: theme.color.border, borderRadius: 8 },
  cancelTxt: { color: theme.color.textHi, fontWeight: "600" },
  confirmBtn: { flex: 2, paddingVertical: 12, alignItems: "center", backgroundColor: theme.color.brand, borderRadius: 8 },
  confirmTxt: { color: "#000", fontWeight: "700" },
});
