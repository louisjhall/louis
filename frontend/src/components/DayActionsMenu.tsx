/**
 * DayActionsMenu — Phase 1.
 * Opens when the coach taps a date row in the Plan calendar.
 * Shows different actions depending on whether the date already has sessions
 * and whether a coach override is active for the date.
 */
import React from "react";
import { View, Text, Pressable, StyleSheet, Modal } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";

export type DayState =
  | "empty"                 // no generated + no manual
  | "generated"             // has generated V2 or legacy sessions, no override
  | "manual"                // has manual (source=coach_manual), no override
  | "replaced"              // active replace_day override → manual visible, generated hidden
  | "suppressed";           // active suppress_day override → rest, generated hidden

type Props = {
  visible: boolean;
  onClose: () => void;
  date: string;
  state: DayState;
  onCreateManual: () => void;
  onReplaceGenerated: () => void;
  onSuppressDay: () => void;
  onRestoreDay: () => void;
  onEditManual: () => void;
  onDeleteManual: () => void;
  onOpenManual: () => void;
};

export default function DayActionsMenu(props: Props) {
  const { visible, onClose, date, state } = props;
  const items: { key: string; label: string; icon: any; onPress: () => void; danger?: boolean; testID: string }[] = [];

  if (state === "empty") {
    items.push({ key: "create", label: "Create manual workout", icon: "add-circle", onPress: props.onCreateManual, testID: "day-menu-create" });
  } else if (state === "generated") {
    items.push({ key: "replace", label: "Replace day with manual workout", icon: "swap-horizontal", onPress: props.onReplaceGenerated, testID: "day-menu-replace" });
    items.push({ key: "suppress", label: "Hide all sessions (mark as rest)", icon: "eye-off", onPress: props.onSuppressDay, testID: "day-menu-suppress" });
  } else if (state === "manual") {
    items.push({ key: "open", label: "Open manual workout", icon: "open-outline", onPress: props.onOpenManual, testID: "day-menu-open" });
    items.push({ key: "edit", label: "Edit manual workout", icon: "create", onPress: props.onEditManual, testID: "day-menu-edit" });
    items.push({ key: "delete", label: "Delete manual workout", icon: "trash", onPress: props.onDeleteManual, danger: true, testID: "day-menu-delete" });
  } else if (state === "replaced") {
    items.push({ key: "open", label: "Open manual workout", icon: "open-outline", onPress: props.onOpenManual, testID: "day-menu-open" });
    items.push({ key: "edit", label: "Edit manual workout", icon: "create", onPress: props.onEditManual, testID: "day-menu-edit" });
    items.push({ key: "delete", label: "Delete manual & restore generated day", icon: "trash", onPress: props.onDeleteManual, danger: true, testID: "day-menu-delete" });
    items.push({ key: "restore", label: "Restore generated day", icon: "refresh", onPress: props.onRestoreDay, testID: "day-menu-restore" });
  } else if (state === "suppressed") {
    items.push({ key: "restore", label: "Restore generated day", icon: "refresh", onPress: props.onRestoreDay, testID: "day-menu-restore" });
    items.push({ key: "create", label: "Add manual workout for this date", icon: "add-circle", onPress: props.onReplaceGenerated, testID: "day-menu-create-under-suppress" });
  }

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.overlay} onPress={onClose}>
        <View style={styles.card} onStartShouldSetResponder={() => true}>
          <Text style={styles.title}>{date}</Text>
          <Text style={styles.subtitle}>{stateLabel(state)}</Text>
          {items.map(it => (
            <Pressable
              key={it.key}
              style={[styles.item, it.danger && styles.itemDanger]}
              onPress={() => { it.onPress(); onClose(); }}
              testID={it.testID}
            >
              <Ionicons name={it.icon} size={18} color={it.danger ? "#ff6b6b" : theme.color.brand} />
              <Text style={[styles.itemText, it.danger && { color: "#ff6b6b" }]}>{it.label}</Text>
            </Pressable>
          ))}
          <Pressable style={styles.cancel} onPress={onClose} testID="day-menu-cancel">
            <Text style={styles.cancelText}>Cancel</Text>
          </Pressable>
        </View>
      </Pressable>
    </Modal>
  );
}

function stateLabel(s: DayState) {
  switch (s) {
    case "empty": return "Empty date";
    case "generated": return "Generated sessions on this date";
    case "manual": return "Manual workout on this date";
    case "replaced": return "Generated day replaced with a manual workout";
    case "suppressed": return "Date hidden by coach — client sees rest";
  }
}

const styles = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.6)", alignItems: "center", justifyContent: "center", padding: 20 },
  card: { backgroundColor: theme.color.bg, borderRadius: 14, width: "100%", maxWidth: 420, padding: 16, borderWidth: 1, borderColor: theme.color.border },
  title: { color: theme.color.textHi, fontSize: 16, fontWeight: "700" },
  subtitle: { color: theme.color.textDim, fontSize: 12, marginBottom: 12, marginTop: 2 },
  item: { flexDirection: "row", alignItems: "center", paddingVertical: 12, paddingHorizontal: 10, borderTopWidth: 1, borderTopColor: theme.color.border, gap: 10 },
  itemDanger: {},
  itemText: { color: theme.color.textHi, fontSize: 14, flex: 1 },
  cancel: { marginTop: 12, paddingVertical: 12, alignItems: "center", borderRadius: 8, borderWidth: 1, borderColor: theme.color.border },
  cancelText: { color: theme.color.textHi, fontWeight: "600" },
});
