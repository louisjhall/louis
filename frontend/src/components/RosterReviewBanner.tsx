/**
 * Iter 95n — Home dashboard placeholder that surfaces while a freshly
 * uploaded roster is inside its ~12-20 min "Louis is looking over your week"
 * review window. Polls GET /roster/status every 30s (and on focus). When
 * status flips to "ready" the banner quietly disappears — no toast, no
 * animation, so it feels like the app just got on with things.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { View, Text, StyleSheet, ActivityIndicator } from "react-native";
import { useFocusEffect } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type RosterStatus = {
  status: "reviewing" | "ready" | "none";
  unlocks_at?: string;
  eta_minutes?: number;
  promise_minutes?: number;
};

export function RosterReviewBanner({ onReadyChanged }: { onReadyChanged?: () => void }) {
  const [state, setState] = useState<RosterStatus | null>(null);
  const wasReviewing = useRef(false);

  const load = useCallback(async () => {
    try {
      const r = await api<RosterStatus>("/roster/status");
      setState(r);
      // If we were showing the banner and the roster just unlocked, ping
      // the host so it can re-fetch the calendar/messages one time.
      if (wasReviewing.current && r.status !== "reviewing") {
        onReadyChanged?.();
      }
      wasReviewing.current = r.status === "reviewing";
    } catch {
      // Silently swallow — a missing endpoint / offline network must never
      // block the home screen from rendering.
      setState({ status: "none" });
    }
  }, [onReadyChanged]);

  // Poll every 30s while banner is mounted, plus one immediate read.
  useEffect(() => {
    load();
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
  }, [load]);

  // Re-check on tab focus so the client sees the reveal the instant they
  // come back to the app after the window elapses.
  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (!state || state.status !== "reviewing") return null;

  const promise = state.promise_minutes ?? 20;
  const eta = Math.min(state.eta_minutes ?? promise, promise);

  return (
    <View style={styles.card}>
      <View style={styles.iconWrap}>
        <ActivityIndicator size="small" color={theme.color.brand} />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.eyebrow}>ROSTER REVIEW UNDER WAY</Text>
        <Text style={styles.title}>Louis is looking over your week.</Text>
        <Text style={styles.sub}>
          You&apos;ll see your programme within the next {promise} minutes
          {eta > 0 && eta < promise ? ` — currently around ${eta} min` : ""}.
          He&apos;ll drop you a message when it&apos;s ready.
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 14,
    backgroundColor: theme.color.surface,
    borderColor: theme.color.brand,
    borderWidth: 1,
    borderRadius: 14,
    padding: 16,
    marginHorizontal: 16,
    marginTop: 14,
    marginBottom: 4,
  },
  iconWrap: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: theme.color.brandTint,
    borderColor: theme.color.brand,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  eyebrow: {
    color: theme.color.brand,
    fontSize: 11,
    fontWeight: "900",
    letterSpacing: 2,
    marginBottom: 4,
  },
  title: {
    color: theme.color.text,
    fontSize: 15,
    fontWeight: "800",
    letterSpacing: -0.2,
    marginBottom: 6,
  },
  sub: {
    color: theme.color.textMuted,
    fontSize: 12,
    lineHeight: 17,
  },
});
