/**
 * DeleteManualConfirmSheet — Phase 1.
 *
 * Deleting a manual workout is a permanent action. If the workout was
 * replacing a generated day, ask the coach what to do next.
 */
import React, { useState } from "react";
import { View, Text, Pressable, StyleSheet, Modal, ActivityIndicator, Alert, TextInput } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Props = {
  visible: boolean;
  onClose: () => void;
  onDeleted: () => void;
  workout: any | null;               // manual workout doc
  wasReplacingGeneratedDay: boolean; // true if there's a linked replace_day override
};

type ThenAction = "restore_day" | "suppress_day" | "leave_rest";

export default function DeleteManualConfirmSheet({ visible, onClose, onDeleted, workout, wasReplacingGeneratedDay }: Props) {
  const [reason, setReason] = useState("");
  const [thenAction, setThenAction] = useState<ThenAction>("restore_day");
  const [busy, setBusy] = useState(false);

  const doDelete = async () => {
    if (!workout) return;
    setBusy(true);
    try {
      await api(`/coach/workouts/${workout.id}/manual`, {
        method: "DELETE",
        body: {
          confirm: true,
          reason: reason.trim() || undefined,
          then_action: wasReplacingGeneratedDay ? thenAction : undefined,
        },
      });
      onDeleted();
      onClose();
      setReason("");
    } catch (e: any) {
      Alert.alert("Could not delete", e?.message || "Please try again.");
    } finally {
      setBusy(false);
    }
  };

  if (!workout) return null;

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.overlay}>
        <View style={styles.card}>
          <Text style={styles.title}>Delete manual workout?</Text>
          <Text style={styles.body}>
            "{workout.title}" on {workout.date}. This cannot be undone. A permanent audit record will remain.
          </Text>
          <TextInput
            style={styles.input}
            value={reason}
            onChangeText={setReason}
            placeholder="Reason (optional)"
            placeholderTextColor="#666"
            testID="delete-manual-reason"
          />
          {wasReplacingGeneratedDay && (
            <View style={{ marginTop: 12 }}>
              <Text style={styles.subLabel}>This workout was replacing the generated day. After delete:</Text>
              <Row selected={thenAction === "restore_day"} onPress={() => setThenAction("restore_day")}
                label="Restore the generated day" testID="then-restore" />
              <Row selected={thenAction === "suppress_day"} onPress={() => setThenAction("suppress_day")}
                label="Keep the date hidden as rest" testID="then-suppress" />
              <Row selected={thenAction === "leave_rest"} onPress={() => setThenAction("leave_rest")}
                label="Leave the date as rest (no generated, no manual)" testID="then-leave-rest" />
            </View>
          )}
          <View style={styles.actions}>
            <Pressable style={styles.cancel} onPress={onClose} testID="delete-manual-cancel">
              <Text style={styles.cancelText}>Cancel</Text>
            </Pressable>
            <Pressable
              style={[styles.confirm, busy && { opacity: 0.6 }]}
              onPress={doDelete} disabled={busy}
              testID="delete-manual-confirm"
            >
              {busy ? <ActivityIndicator color="#fff" /> :
                <>
                  <Ionicons name="trash" size={16} color="#fff" />
                  <Text style={styles.confirmText}>Delete workout</Text>
                </>}
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

function Row({ selected, onPress, label, testID }: { selected: boolean; onPress: () => void; label: string; testID?: string }) {
  return (
    <Pressable style={styles.row} onPress={onPress} testID={testID}>
      <Ionicons name={selected ? "radio-button-on" : "radio-button-off"}
        size={18} color={selected ? theme.color.brand : theme.color.textDim} />
      <Text style={styles.rowText}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.7)", alignItems: "center", justifyContent: "center", padding: 20 },
  card: { backgroundColor: theme.color.bg, borderRadius: 14, width: "100%", maxWidth: 460, padding: 18, borderWidth: 1, borderColor: theme.color.border },
  title: { color: theme.color.textHi, fontSize: 16, fontWeight: "700", marginBottom: 8 },
  body: { color: theme.color.textDim, fontSize: 13, marginBottom: 12 },
  input: { backgroundColor: theme.color.card, color: theme.color.onRed, borderRadius: 8, padding: 10, borderWidth: 1, borderColor: theme.color.border },
  subLabel: { color: theme.color.textDim, fontSize: 12, marginBottom: 8 },
  row: { flexDirection: "row", alignItems: "center", paddingVertical: 8, gap: 8 },
  rowText: { color: theme.color.textHi, fontSize: 13, flex: 1 },
  actions: { flexDirection: "row", marginTop: 16, gap: 8 },
  cancel: { flex: 1, paddingVertical: 12, borderRadius: 8, alignItems: "center", borderWidth: 1, borderColor: theme.color.border },
  cancelText: { color: theme.color.textHi, fontWeight: "600" },
  confirm: { flex: 2, flexDirection: "row", justifyContent: "center", alignItems: "center", gap: 6, paddingVertical: 12, borderRadius: 8, backgroundColor: "#ff6b6b" },
  confirmText: { color: "#fff", fontWeight: "700" },
});
