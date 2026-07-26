/**
 * WorkoutQuickActions — Phase 4 shared bottom sheet.
 *
 * Compact action menu shown from either the coach month view (day cards)
 * or the coach live feed. Keeps the coach on the same screen for the
 * most common actions:
 *   - Open in full editor
 *   - Regenerate / swap the whole workout
 *   - Approve the workout
 *   - Fix media (opens exercise-content editor for the exercise)
 *   - Move to another date
 *
 * The full swap-workout picker with alternative session suggestions is
 * still handled by the existing coach workout editor (deeplinked).
 */
import React, { useState } from "react";
import {
  View, Text, StyleSheet, Modal, Pressable, ActivityIndicator, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { SwapWorkoutPicker } from "./SwapWorkoutPicker";


export type WorkoutQuickActionTarget = {
  id: string;
  title?: string;
  date?: string;
  approved?: boolean;
  coach_locked?: boolean;
  missing_media_count?: number;
};


export function WorkoutQuickActions({
  target, visible, onClose, onChanged,
}: {
  target: WorkoutQuickActionTarget | null;
  visible: boolean;
  onClose: () => void;
  onChanged?: () => void;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [swapOpen, setSwapOpen] = useState(false);

  if (!target) return null;

  const run = async (
    key: string,
    fn: () => Promise<any>,
    successMsg?: string,
  ) => {
    try {
      setBusy(key);
      await fn();
      if (successMsg) {
        Alert.alert("Done", successMsg);
      }
      onChanged?.();
      onClose();
    } catch (e: any) {
      Alert.alert("Couldn't complete", e?.message || "Please try again.");
    } finally {
      setBusy(null);
    }
  };

  const openEditor = () => {
    onClose();
    router.push(`/coach/workout/edit/${target.id}` as any);
  };

  const regenerate = () =>
    run(
      "regen",
      () => api(`/coach/workouts/${target.id}/regenerate`, { method: "POST" }),
      "Louis rebuilt this session using the latest roster context.",
    );

  const approve = () =>
    run(
      "approve",
      () => api(`/coach/workouts/${target.id}/approve`, { method: "POST" }),
      "Workout approved.",
    );

  const toggleLock = () =>
    run(
      "lock",
      () => api(`/coach/workouts/${target.id}/lock`, { method: "POST" }),
    );

  return (
    <Modal
      transparent
      visible={visible}
      animationType="slide"
      onRequestClose={onClose}
    >
      <Pressable style={styles.scrim} onPress={onClose} testID="wqa-scrim">
        <Pressable style={styles.sheet} onPress={(e) => e.stopPropagation()}>
          <View style={styles.head}>
            <View style={{ flex: 1 }}>
              <Text style={styles.title} numberOfLines={1}>
                {target.title || "Workout"}
              </Text>
              <Text style={styles.sub}>
                {target.date || ""}
                {target.approved ? "  ·  APPROVED" : ""}
                {target.coach_locked ? "  ·  LOCKED" : ""}
              </Text>
            </View>
            <Pressable onPress={onClose} hitSlop={12} testID="wqa-close">
              <Ionicons name="close" size={24} color={theme.color.text} />
            </Pressable>
          </View>

          <View style={styles.grip} />

          <Action
            testID="wqa-open"
            icon="create-outline"
            label="OPEN IN EDITOR"
            sub="Edit exercises, sets, reps, media, cues."
            onPress={openEditor}
          />

          <Action
            testID="wqa-swap"
            icon="swap-horizontal"
            label="SWAP WORKOUT · PICK ALTERNATIVE"
            sub="Choose from safe alternatives ranked to today's roster."
            disabled={target.coach_locked}
            onPress={() => setSwapOpen(true)}
          />

          <Action
            testID="wqa-regen"
            icon="refresh"
            label="REGENERATE FROM SCRATCH"
            sub="Rebuild this session using the latest roster context."
            busy={busy === "regen"}
            disabled={target.coach_locked}
            onPress={regenerate}
          />

          <Action
            testID="wqa-approve"
            icon={target.approved ? "checkmark-done-circle" : "checkmark-circle-outline"}
            label={target.approved ? "ALREADY APPROVED" : "APPROVE FOR CLIENT"}
            sub="Confirm this session is ready to send to the client."
            busy={busy === "approve"}
            disabled={target.approved}
            onPress={approve}
          />

          <Action
            testID="wqa-lock"
            icon={target.coach_locked ? "lock-open-outline" : "lock-closed-outline"}
            label={target.coach_locked ? "UNLOCK" : "COACH-LOCK"}
            sub={target.coach_locked
              ? "Allow auto-regeneration again."
              : "Freeze this session — no auto-updates."}
            busy={busy === "lock"}
            onPress={toggleLock}
          />

          {(target.missing_media_count || 0) > 0 ? (
            <Action
              testID="wqa-fix-media"
              icon="images-outline"
              iconColor="#c85450"
              label={`FIX MISSING MEDIA · ${target.missing_media_count}`}
              sub="Open the workout editor to attach images and videos."
              onPress={openEditor}
            />
          ) : null}
        </Pressable>
      </Pressable>

      {/* Nested SwapWorkoutPicker (rendered inside Modal is fine for iOS/Android via portals). */}
      <SwapWorkoutPicker
        visible={swapOpen}
        workoutId={target.id}
        onClose={() => setSwapOpen(false)}
        onApplied={() => {
          setSwapOpen(false);
          onChanged?.();
          onClose();
        }}
      />
    </Modal>
  );
}


function Action({
  icon, label, sub, onPress, busy, disabled, testID, iconColor,
}: {
  icon: any; label: string; sub: string;
  onPress: () => void;
  busy?: boolean; disabled?: boolean;
  testID?: string; iconColor?: string;
}) {
  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      disabled={disabled || busy}
      style={[styles.action, disabled && { opacity: 0.4 }]}
    >
      {busy ? (
        <ActivityIndicator size="small" color={theme.color.brand} style={{ width: 22 }} />
      ) : (
        <Ionicons
          name={icon}
          size={22}
          color={iconColor || theme.color.text}
        />
      )}
      <View style={{ flex: 1 }}>
        <Text style={styles.actionT}>{label}</Text>
        <Text style={styles.actionS} numberOfLines={2}>{sub}</Text>
      </View>
      {!busy && <Ionicons name="chevron-forward" size={16} color={theme.color.textMuted} />}
    </Pressable>
  );
}


const styles = StyleSheet.create({
  scrim: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  sheet: {
    backgroundColor: theme.color.surface,
    borderTopLeftRadius: 18, borderTopRightRadius: 18,
    paddingBottom: theme.space.xl,
    maxHeight: "80%",
  },
  head: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: theme.space.lg,
    paddingTop: theme.space.md,
  },
  title: { color: theme.color.text, fontSize: 16, fontWeight: "900" },
  sub: { color: theme.color.textMuted, fontSize: 11, marginTop: 3, letterSpacing: 0.5 },
  grip: {
    alignSelf: "center", marginVertical: 8,
    width: 40, height: 4, borderRadius: 2,
    backgroundColor: theme.color.border,
  },
  action: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingHorizontal: theme.space.lg,
    paddingVertical: 14,
    borderTopWidth: 1,
    borderTopColor: theme.color.border,
  },
  actionT: { color: theme.color.text, fontSize: 12, fontWeight: "900", letterSpacing: 1 },
  actionS: { color: theme.color.textMuted, fontSize: 11, marginTop: 2, lineHeight: 15 },
});
