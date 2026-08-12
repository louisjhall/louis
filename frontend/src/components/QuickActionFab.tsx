/**
 * QuickActionFab — Iter172
 *
 * A red floating action button (+) pinned to the bottom-right of the
 * client Today screen. Tapping expands two shortcut chips:
 *   · Log a Meal  → /nutrition/log
 *   · Start Workout → today's workout list (or the workouts calendar
 *     if no workout is scheduled today)
 *
 * The button sits ABOVE the bottom tab bar (which contains the chat
 * icon on the messages tab) via `bottom: 96` so it never collides
 * with tab targets.
 */
import React, { useState, useCallback } from "react";
import { View, Text, StyleSheet, Pressable, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { theme } from "@/src/lib/theme";

export function QuickActionFab({
  todayWorkoutId,
}: {
  /** ID of today's workout, if any. Used to jump straight into the logger. */
  todayWorkoutId?: string | null;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);

  const toggle = useCallback(() => setOpen((v) => !v), []);
  const close = useCallback(() => setOpen(false), []);

  const goMeal = useCallback(() => {
    close();
    router.push("/nutrition/log" as any);
  }, [router, close]);

  const goWorkout = useCallback(() => {
    close();
    if (todayWorkoutId) {
      router.push(`/workout/${todayWorkoutId}/list` as any);
    } else {
      router.push("/(client)/calendar" as any);
    }
  }, [router, close, todayWorkoutId]);

  return (
    <View pointerEvents="box-none" style={styles.container} testID="quick-action-fab-wrap">
      {open ? (
        <View style={styles.actionsCol} pointerEvents="box-none">
          <Pressable style={styles.actionRow} onPress={goMeal} testID="quick-action-meal">
            <View style={styles.actionLabel}>
              <Text style={styles.actionLabelT}>LOG A MEAL</Text>
            </View>
            <View style={[styles.miniFab, styles.miniFabAlt]}>
              <Ionicons name="restaurant" size={18} color="#fff" />
            </View>
          </Pressable>
          <Pressable style={styles.actionRow} onPress={goWorkout} testID="quick-action-workout">
            <View style={styles.actionLabel}>
              <Text style={styles.actionLabelT}>START WORKOUT</Text>
            </View>
            <View style={[styles.miniFab, styles.miniFabAlt]}>
              <Ionicons name="barbell" size={18} color="#fff" />
            </View>
          </Pressable>
        </View>
      ) : null}
      <Pressable
        onPress={toggle}
        style={[styles.fab, open && styles.fabOpen]}
        accessibilityLabel="Quick actions"
        testID="quick-action-fab"
      >
        <Ionicons
          name={open ? "close" : "add"}
          size={30}
          color="#fff"
        />
      </Pressable>
    </View>
  );
}

const shadow = Platform.select({
  ios: {
    shadowColor: "#000",
    shadowOpacity: 0.35,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
  },
  android: { elevation: 8 },
  default: {},
});

const styles = StyleSheet.create({
  container: {
    position: "absolute",
    right: 18,
    // Sits above the bottom tab bar which contains the chat/messages tab.
    // Tab bar height on Expo Router defaults to ~80–90; we add breathing room.
    bottom: 96,
    alignItems: "flex-end",
    gap: 12,
    zIndex: 60,
  },
  fab: {
    width: 60,
    height: 60,
    borderRadius: 30,
    backgroundColor: theme.color.brand,
    alignItems: "center",
    justifyContent: "center",
    ...(shadow as object),
  },
  fabOpen: {
    backgroundColor: "#1E1E1E",
  },
  actionsCol: {
    gap: 12,
    alignItems: "flex-end",
    marginBottom: 12,
  },
  actionRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
  },
  actionLabel: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 8,
    backgroundColor: "#1E1E1E",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: "rgba(255,255,255,0.15)",
    ...(shadow as object),
  },
  actionLabelT: {
    color: "#FFFFFF",
    fontSize: 12,
    fontWeight: "900",
    letterSpacing: 1.4,
  },
  miniFab: {
    width: 46,
    height: 46,
    borderRadius: 23,
    alignItems: "center",
    justifyContent: "center",
    ...(shadow as object),
  },
  miniFabAlt: {
    backgroundColor: theme.color.brand,
  },
});
