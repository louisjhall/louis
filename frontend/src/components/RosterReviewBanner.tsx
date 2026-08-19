/**
 * RosterReviewBanner — home-screen only.
 *
 * Renders one of TWO states, whichever is currently active:
 *
 * 1. `reviewing` (fast) — the 12-20 min programme-release window right
 *    after roster confirmation. Keyed off GET /roster/status.
 *
 * 2. `awaiting_coach_review` (slow) — coach is manually approving the
 *    programme, up to 24 h. Keyed off GET /roster/submission-state.
 *    (Iter187 · product requirement 2026-06 — persistent home banner
 *    replaces the earlier full-screen overlay so the client can navigate
 *    the rest of the app freely.)
 *
 * Both states dismiss themselves automatically the moment the underlying
 * server-side condition clears. `onReadyChanged` fires so the host can
 * re-fetch the calendar / messages one time.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { View, Text, StyleSheet, ActivityIndicator } from "react-native";
import { useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type RosterStatus = {
  status: "reviewing" | "ready" | "none";
  unlocks_at?: string;
  eta_minutes?: number;
  promise_minutes?: number;
};

type SubmissionState = {
  state: string;
  submitted_at?: string;
  awaiting_review_since?: string;
};

// Sentinel active-mode enum — computed AFTER both endpoints resolve so
// we don't briefly flash the fast copy over a coach-review submission.
type Mode = "none" | "reviewing" | "coach_review";

export function RosterReviewBanner({ onReadyChanged }: { onReadyChanged?: () => void }) {
  const [mode, setMode] = useState<Mode>("none");
  const [status, setStatus] = useState<RosterStatus | null>(null);
  const wasActive = useRef(false);

  const load = useCallback(async () => {
    try {
      const [rRaw, sRaw] = await Promise.all([
        api<RosterStatus>("/roster/status").catch(() => ({ status: "none" }) as RosterStatus),
        api<SubmissionState>("/roster/submission-state").catch(() => ({ state: "none" }) as SubmissionState),
      ]);

      // Iter170 · Defence-in-depth on the fast banner — if `/roster/status`
      // mistakenly returns "reviewing" but the active roster is already
      // CONFIRMED, treat it as ready.
      let effectiveStatus: RosterStatus = rRaw;
      if (rRaw.status === "reviewing") {
        try {
          const cur = await api<any>("/roster/current");
          if (String(cur?.status || "").toLowerCase() === "confirmed") {
            effectiveStatus = { ...rRaw, status: "ready" };
          }
        } catch { /* fall back */ }
      }
      setStatus(effectiveStatus);

      // Priority: coach_review > reviewing > none.
      // Coach review outranks the fast 20-min window because it is the
      // more truthful signal once we've entered the manual approval flow.
      let next: Mode = "none";
      if (sRaw.state === "awaiting_coach_review") next = "coach_review";
      else if (effectiveStatus.status === "reviewing") next = "reviewing";
      setMode(next);

      // Ping host on any active → inactive transition so the calendar
      // and message list re-fetch once.
      if (wasActive.current && next === "none") onReadyChanged?.();
      wasActive.current = next !== "none";
    } catch {
      // Silently swallow — a missing endpoint / offline network must
      // never block the home screen from rendering.
      setMode("none");
    }
  }, [onReadyChanged]);

  useEffect(() => {
    load();
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
  }, [load]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (mode === "none") return null;

  // -------------------------------------------------------------------
  // Slow copy — Coach Review (Iter187, up to 24 h)
  // -------------------------------------------------------------------
  if (mode === "coach_review") {
    return (
      <View style={styles.card} testID="coach-review-banner">
        <View style={styles.iconWrap}>
          <Ionicons name="hourglass-outline" size={16} color={theme.color.brand} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.eyebrow}>ROSTER RECEIVED</Text>
          <Text style={styles.title}>
            Your coach is working on your programme — up to 24 hours.
          </Text>
          <Text style={styles.sub}>
            You&apos;ll be notified the moment it&apos;s ready.
          </Text>
        </View>
      </View>
    );
  }

  // -------------------------------------------------------------------
  // Fast copy — Programme Release (~20 min)
  // -------------------------------------------------------------------
  const promise = status?.promise_minutes ?? 20;
  const eta = Math.min(status?.eta_minutes ?? promise, promise);

  return (
    <View style={styles.card} testID="roster-review-banner">
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
