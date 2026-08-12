/**
 * QuickActionFab — Iter177
 *
 * A red floating (+) button pinned to the bottom-right of every
 * client tab. Tapping expands exactly TWO shortcut chips:
 *   🍽️  Log a Meal    → /nutrition/pick  (nutrition menu that already
 *                        surfaces Photo Scan / Food Search / Manual Log)
 *   🏋️  Start Workout → today's workout list (or the calendar if no
 *                        workout is scheduled today)
 *
 * PIXEL-PERFECT ALIGNMENT (Iter177):
 *   QuickActionFab      right: 14   width: 60   → centre-x = 14 + 30 = 44
 *   CoachChatBubble     right: 16   width: 56   → centre-x = 16 + 28 = 44
 * Both icons share the same vertical axis 44px in from the right edge.
 *
 * VERTICAL STACKING: the FAB sits 16px above the CoachChatBubble
 * (which itself sits `max(insets.bottom, 10) + TAB_BAR (62) + 10`
 * above the screen bottom), so:
 *   fab.bottom = max(insets.bottom, 10) + 62 + 10 + BUBBLE (56) + 16
 *              = max(insets.bottom, 10) + 144
 */
import React, { useEffect, useMemo, useState, useCallback } from "react";
import { View, Text, StyleSheet, Pressable, Platform } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { theme } from "@/src/lib/theme";
import { useThemeMode } from "@/src/hooks/use-theme-mode";
import { api } from "@/src/lib/api";
import type { ThemeMode } from "@/src/lib/theme";

// Local YYYY-MM-DD helper — inline to avoid an extra import chain.
function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

type Shortcut = {
  key: string;
  label: string;
  emoji: string;
  icon: React.ComponentProps<typeof Ionicons>["name"];
  onPress: () => void;
};

export function QuickActionFab() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  // Iter177 · Subscribe to the reactive theme mode. `styles` is rebuilt
  // via `makeStyles(mode)` whose colour reads happen AT RENDER TIME so
  // the FAB repaints instantly on Light ↔ Dark toggle without needing
  // a full app reload.
  const { mode } = useThemeMode();
  const styles = useMemo(() => makeStyles(mode, insets.bottom), [mode, insets.bottom]);

  const [open, setOpen] = useState(false);
  const [todayWorkoutId, setTodayWorkoutId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const rows = await api<any[]>(`/workouts?date=${todayIso()}`);
        if (!cancelled) {
          const first = Array.isArray(rows) && rows.length ? rows[0] : null;
          setTodayWorkoutId(first?.id || null);
        }
      } catch { /* best-effort */ }
    })();
    return () => { cancelled = true; };
  }, []);

  const close = useCallback(() => setOpen(false), []);
  const toggle = useCallback(() => setOpen((v) => !v), []);

  const shortcuts = useMemo<Shortcut[]>(() => [
    {
      key: "meal",
      label: "LOG A MEAL",
      emoji: "🍽️",
      icon: "restaurant",
      onPress: () => { close(); router.push("/nutrition/pick" as any); },
    },
    {
      key: "workout",
      label: "START WORKOUT",
      emoji: "🏋️",
      icon: "barbell",
      onPress: () => {
        close();
        if (todayWorkoutId) {
          router.push(`/workout/${todayWorkoutId}/list` as any);
        } else {
          router.push("/(client)/calendar" as any);
        }
      },
    },
  ], [router, todayWorkoutId, close]);

  return (
    <View pointerEvents="box-none" style={styles.container} testID="quick-action-fab-wrap">
      {open ? (
        <>
          {/* Tap-outside catcher — closes the menu when the user taps
              anywhere else on the tab (below/behind the shortcuts). */}
          <Pressable
            style={StyleSheet.absoluteFillObject}
            onPress={close}
            testID="quick-action-scrim"
          />
          <View style={styles.actionsCol} pointerEvents="box-none">
            {shortcuts.map((s) => (
              <Pressable
                key={s.key}
                style={styles.actionRow}
                onPress={s.onPress}
                testID={`quick-action-${s.key}`}
              >
                <View style={styles.actionLabel}>
                  <Text style={styles.actionLabelT}>
                    {s.emoji}  {s.label}
                  </Text>
                </View>
                <View style={styles.miniFab}>
                  <Ionicons name={s.icon} size={18} color="#FFFFFF" />
                </View>
              </Pressable>
            ))}
          </View>
        </>
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
          color="#FFFFFF"
        />
      </Pressable>
    </View>
  );
}

/* --------------------------------------------------------------------------
 * Iter177 · makeStyles factory. Called from inside <QuickActionFab/> via
 * `useMemo(..., [mode])` so all `theme.color.xxx` reads happen at render
 * time and the button repaints instantly on Light ↔ Dark toggle.
 *
 * Contrast rule enforced here: the FAB is ALWAYS brand red with a
 * pure-white icon in both modes (red on white bg reads; red on dark
 * bg reads). Never rely on `theme.color.text` for the icon colour —
 * pass literal "#FFFFFF" so it can never accidentally become black in
 * Light Mode.
 * ------------------------------------------------------------------------ */
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

function makeStyles(_mode: ThemeMode, safeBottomPx: number) {
  // FAB bottom math: sit 16px above the CoachChatBubble.
  //   coach.bottom = max(insets.bottom, 10) + 62 (tab bar) + 10 padding
  //   fab.bottom   = coach.bottom + 56 (bubble) + 16 (gap)
  //                = max(insets.bottom, 10) + 144
  const safeBottom = Math.max(safeBottomPx || 0, 10);
  const fabBottom = safeBottom + 144;

  return StyleSheet.create({
    container: {
      position: "absolute",
      // Iter177 · right:14, width:60 → centre-x = 14 + 30 = 44px in from the
      // right edge. Matches CoachChatBubble (right:16, width:56 → 16+28=44).
      right: 14,
      bottom: fabBottom,
      alignItems: "flex-end",
      zIndex: 60,
    },
    fab: {
      width: 60,
      height: 60,
      borderRadius: 30,
      // Iter177 · Brand red in BOTH modes so the (+) always reads as
      // primary action. Icon is a literal "#FFFFFF" — never `theme.color.text`.
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
      // Dark chip in BOTH modes so the label reads clearly on a white
      // (Light Mode) OR dark (Dark Mode) tab background.
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
      backgroundColor: theme.color.brand,
      alignItems: "center",
      justifyContent: "center",
      ...(shadow as object),
    },
  });
}
