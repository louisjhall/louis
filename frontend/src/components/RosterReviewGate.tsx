/**
 * RosterReviewGate — Iter187
 *
 * Full-screen, non-dismissible overlay that renders on top of the entire
 * (client) tab layout the moment a client's roster is in the
 * `awaiting_coach_review` state.
 *
 * Product requirement (2026-06):
 *   "When a client successfully uploads their roster, immediately show a
 *   full-screen confirmation message that cannot be dismissed or
 *   navigated away from. It should say: 'Roster Received. Your coach is
 *   reviewing your programme — this can take up to 24 hours. You'll be
 *   notified when it's ready.' The client should see this every time
 *   they open the app until the coach has approved it. No upload
 *   buttons. No way back to the upload screen. Just that message."
 *
 * Design notes
 * ------------
 * - Covers 100% of the client tab UI (including the tab bar / FAB / chat
 *   bubble). Rendered as a sibling of the Tabs INSIDE the client layout
 *   so it inherits SafeArea and does not require a route push.
 * - No back button, no close, no primary CTA, no ghost buttons. The
 *   only interactive affordance is a subtle "Refresh" pill that re-
 *   fetches the state — required because a client keeping the app open
 *   past the 24-h auto-approve mark otherwise has no way to unblock.
 * - Re-polls the state every 30 seconds so the moment the coach
 *   approves the roster on the desktop, the gate quietly dismisses
 *   itself. Also revalidates on app foreground.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, ActivityIndicator, AppState, Pressable,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

const POLL_INTERVAL_MS = 30_000;

type SubmissionState = {
  state: string;
  submitted_at?: string;
  awaiting_review_since?: string;
};

export function RosterReviewGate({ children }: { children: React.ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [sub, setSub] = useState<SubmissionState | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);

  const reload = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const s = await api<SubmissionState>("/roster/submission-state");
      if (mountedRef.current) setSub(s);
    } catch {
      // Silent — network hiccups shouldn't accidentally show the gate.
      // If we've never loaded successfully, treat as `none`.
      if (mountedRef.current && !sub) setSub({ state: "none" });
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [sub]);

  useEffect(() => {
    mountedRef.current = true;
    reload(false);
    // Poll every 30 s so an approval fires the gate down without a
    // manual refresh — matches product copy: "you'll be notified when
    // it's ready".
    pollRef.current = setInterval(() => { reload(true); }, POLL_INTERVAL_MS);

    // Also revalidate whenever the app comes back to the foreground —
    // most users open the app expecting fresh state, not a 30-s stale
    // poll window.
    const appStateSub = AppState.addEventListener("change", (next) => {
      if (next === "active") reload(true);
    });

    return () => {
      mountedRef.current = false;
      if (pollRef.current) clearInterval(pollRef.current);
      appStateSub.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const showGate = !!sub && sub.state === "awaiting_coach_review";

  return (
    <View style={{ flex: 1 }}>
      {children}
      {showGate ? (
        <RosterReviewLockOverlay
          submittedAt={sub?.submitted_at}
          loading={loading}
          onRefresh={() => reload(false)}
        />
      ) : null}
    </View>
  );
}

/* --------------------------------------------------------------------- */
/*  Full-screen overlay                                                  */
/* --------------------------------------------------------------------- */
function RosterReviewLockOverlay({
  submittedAt,
  loading,
  onRefresh,
}: {
  submittedAt?: string;
  loading: boolean;
  onRefresh: () => void;
}) {
  const submittedLabel = submittedAt
    ? new Date(submittedAt).toLocaleString(undefined, {
        weekday: "short", day: "numeric", month: "short",
        hour: "2-digit", minute: "2-digit",
      })
    : null;

  return (
    <SafeAreaView
      style={styles.overlay}
      edges={["top", "bottom", "left", "right"]}
      testID="roster-review-gate"
      pointerEvents="auto"
    >
      <View style={styles.content}>
        <View style={styles.iconWrap}>
          <Ionicons name="checkmark-done" size={40} color="#fff" />
        </View>

        <Text style={styles.eyebrow}>ROSTER RECEIVED</Text>

        <Text style={styles.title}>Your coach is reviewing your programme</Text>

        <Text style={styles.body}>
          This can take up to 24 hours. You&apos;ll be notified when it&apos;s ready.
        </Text>

        {submittedLabel ? (
          <View style={styles.metaRow}>
            <Ionicons name="time-outline" size={12} color={theme.color.textMuted} />
            <Text style={styles.metaT}>Submitted {submittedLabel}</Text>
          </View>
        ) : null}

        <View style={styles.spinnerRow}>
          <ActivityIndicator size="small" color={theme.color.brand} />
          <Text style={styles.spinnerT}>Louis is on it</Text>
        </View>
      </View>

      <View style={styles.footer}>
        <Pressable
          onPress={onRefresh}
          disabled={loading}
          hitSlop={16}
          style={({ pressed }) => [styles.refreshPill, pressed && { opacity: 0.7 }]}
          testID="roster-review-gate-refresh"
          accessibilityRole="button"
          accessibilityLabel="Refresh status"
        >
          <Ionicons
            name="refresh"
            size={13}
            color={theme.color.textMuted}
            style={loading ? { opacity: 0.4 } : undefined}
          />
          <Text style={styles.refreshT}>{loading ? "CHECKING…" : "REFRESH STATUS"}</Text>
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  overlay: {
    position: "absolute",
    top: 0, left: 0, right: 0, bottom: 0,
    backgroundColor: theme.color.bg,
    // Iter187 · Sits above the tab bar (elevation:8 on Android),
    // FAB (zIndex:100 on iOS), and the chat bubble (zIndex:99).
    zIndex: 9999,
    ...Platform.select({
      android: { elevation: 32 },
      default: {},
    }),
  },
  content: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 32,
    gap: 14,
  },
  iconWrap: {
    width: 80, height: 80, borderRadius: 40,
    backgroundColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
    marginBottom: 12,
    shadowColor: theme.color.brand,
    shadowOpacity: 0.35, shadowRadius: 16, shadowOffset: { width: 0, height: 8 },
  },
  eyebrow: {
    color: theme.color.brand,
    fontSize: 12, fontWeight: "900", letterSpacing: 2.4,
    marginTop: 4,
  },
  title: {
    color: theme.color.text,
    fontSize: 22, fontWeight: "900",
    textAlign: "center", lineHeight: 28,
    marginTop: 4,
    paddingHorizontal: 8,
  },
  body: {
    color: theme.color.textMuted,
    fontSize: 15, lineHeight: 22,
    textAlign: "center",
    marginTop: 6,
  },
  metaRow: {
    flexDirection: "row", alignItems: "center", gap: 6,
    marginTop: 14,
  },
  metaT: {
    color: theme.color.textMuted,
    fontSize: 11, fontStyle: "italic",
  },
  spinnerRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    marginTop: 24,
    paddingHorizontal: 16, paddingVertical: 10,
    borderRadius: 20,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
  },
  spinnerT: {
    color: theme.color.text,
    fontSize: 12, fontWeight: "700", letterSpacing: 1,
  },
  footer: {
    alignItems: "center",
    paddingBottom: 24,
  },
  refreshPill: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: 18, paddingVertical: 10,
    borderRadius: 24,
    backgroundColor: "transparent",
  },
  refreshT: {
    color: theme.color.textMuted,
    fontSize: 11, fontWeight: "800", letterSpacing: 1.4,
  },
});
