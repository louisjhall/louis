import React from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";

export type WorkoutStatus =
  | "coach_reviewing" | "ready" | "in_progress" | "completed"
  | "missed" | "updating" | "locked";

// Derive a status from a workout record's various fields (backward-compat).
export function deriveStatus(w: any, today?: string): WorkoutStatus {
  if (!w) return "coach_reviewing";
  if (w.coach_locked) return "locked";
  if (w.completed) return "completed";
  if (w.status === "updating" || w.override_applied) return "updating";
  if (w.status === "in_progress") return "in_progress";
  if (w.approved === false || w.status === "coach_reviewing" || w.status === "pending") return "coach_reviewing";
  const dt = w.date;
  const t = today || new Date().toISOString().slice(0, 10);
  if (dt && dt < t && !w.completed) return "missed";
  return "ready";
}

const META: Record<WorkoutStatus, { label: string; desc: string; color: string; icon: any }> = {
  coach_reviewing: { label: "LOUIS REVIEWING", desc: "Louis is reviewing this workout before it becomes available.", color: "#F59E0B", icon: "eye" },
  ready:           { label: "READY",           desc: "Approved and ready to complete.",                                  color: theme.color.green, icon: "checkmark-circle" },
  in_progress:     { label: "IN PROGRESS",     desc: "Workout currently being completed.",                                color: "#3B82F6",         icon: "play-circle" },
  completed:       { label: "COMPLETED",       desc: "Workout completed.",                                                color: theme.color.green, icon: "checkmark-done" },
  missed:          { label: "MISSED",          desc: "Workout was not completed.",                                        color: theme.color.red,   icon: "close-circle" },
  updating:        { label: "UPDATING",        desc: "CrewFit Intelligence is updating this workout following changes to your roster.", color: "#A855F7", icon: "sync-circle" },
          locked:          { label: "LOCKED",          desc: "This workout has been locked by Louis.",                       color: "#6B7280",         icon: "lock-closed" },
};

export function StatusBadge({ status, onPress }: { status: WorkoutStatus; onPress?: () => void }) {
  const m = META[status];
  const inner = (
    <View style={[styles.badge, { borderColor: m.color, backgroundColor: `${m.color}22` }]}>
      <Ionicons name={m.icon} size={11} color={m.color} />
      <Text style={[styles.label, { color: m.color }]}>{m.label}</Text>
    </View>
  );
  if (onPress) return <Pressable testID={`status-${status}`} onPress={onPress}>{inner}</Pressable>;
  return inner;
}

export function statusMeta(status: WorkoutStatus) { return META[status]; }

const styles = StyleSheet.create({
  badge: {
    flexDirection: "row", alignItems: "center", gap: 5,
    paddingHorizontal: 8, paddingVertical: 3, borderRadius: 4,
    borderWidth: 1, alignSelf: "flex-start",
  },
  label: { fontSize: 9, fontWeight: "800", letterSpacing: 1.2 },
});
