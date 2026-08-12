/**
 * QuickActionFab — Iter174
 *
 * A red floating (+) button pinned to the bottom-right of every
 * client tab. Tapping expands exactly TWO shortcut chips:
 *   🍽️  Log a Meal    → /nutrition/pick  (existing nutrition menu
 *                        that already surfaces Photo Scan / Food
 *                        Search / Manual Log inline)
 *   🏋️  Start Workout → today's workout list (or the calendar if
 *                        no workout is scheduled today)
 *
 * Iter173 briefly expanded the menu to four items; Iter174 rolls
 * back to two, per PRD, since the nutrition sub-choices are already
 * one tap away on the /nutrition/pick screen.
 *
 * The button sits ABOVE the bottom tab bar (which contains the chat
 * icon on the messages tab) so it never collides with tab targets.
 *
 * Rendered at the (client) layout root so it stays visible when the
 * user hops between Today / Calendar / Nutrition / Base / Profile /
 * Messages, and disappears automatically when a non-tab screen
 * (e.g. the workout logger itself) pushes on top of the stack.
 */
import React, { useEffect, useMemo, useState, useCallback } from "react";
import { View, Text, StyleSheet, Pressable, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { theme } from "@/src/lib/theme";
import { api } from "@/src/lib/api";

// Iter173 · Local YYYY-MM-DD helper. Kept inline to avoid a new import
// dependency chain from the client-tab layout entry point.
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
  const [open, setOpen] = useState(false);
  const [todayWorkoutId, setTodayWorkoutId] = useState<string | null>(null);

  // Iter173 · Pull today's workout id lazily so "Start Workout" opens
  // the logger directly when there is one scheduled today.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const day = todayIso();
        const rows = await api<any[]>(`/workouts?date=${day}`);
        if (!cancelled) {
          const first = Array.isArray(rows) && rows.length ? rows[0] : null;
          setTodayWorkoutId(first?.id || null);
        }
      } catch {
        // best-effort — the shortcut falls back to the calendar
      }
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
      // Iter174 · Route to the nutrition-picker screen, which already
      // exposes Photo Scan / Food Search / Manual Log side-by-side.
      // Avoids duplicating those three choices inside the FAB.
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
                  <Ionicons name={s.icon} size={18} color={theme.color.onBrand} />
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
          color={theme.color.onBrand}
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
    // Iter174 · Raised from 96 → 180 so the FAB clears the floating
    // Coach Chat bubble on every client tab (the chat launcher
    // renders at bottom-right ~90–120px above the tab bar).
    bottom: 180,
    alignItems: "flex-end",
    zIndex: 60,
  },
  fab: {
    width: 60,
    height: 60,
    borderRadius: 30,
    // Iter173 · Brand red per PRD — pure white icon (theme.color.onBrand)
    // ensures the "+" is never lost against the button.
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
    // Iter173 · Dark chip in BOTH modes so the label reads clearly
    // when placed over a white tab background (Light Mode).
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
    // Iter173 · Uses brand red so the mini FABs read as siblings of
    // the primary + button.
    backgroundColor: theme.color.brand,
    alignItems: "center",
    justifyContent: "center",
    ...(shadow as object),
  },
});
