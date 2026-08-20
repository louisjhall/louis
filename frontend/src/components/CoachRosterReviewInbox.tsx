/**
 * CoachRosterReviewInbox — Iter186
 *
 * Sits at the top of the coach's Clients screen. Lists any client rosters
 * that are currently in `awaiting_coach_review` state (client has confirmed
 * their duty pattern but the coach hasn't yet approved / requested a new
 * upload).
 *
 * Each row exposes inline **APPROVE** and **REQUEST NEW UPLOAD** buttons
 * so the coach can clear the queue without navigating into every client's
 * workspace one by one.
 *
 * Visibility contract:
 *   - Renders `null` when the queue is empty (no visual noise).
 *   - Auto-refreshes on tab focus so approving in one place removes the
 *     row here without a hard reload.
 */
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator, Alert, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

/**
 * Iter188 · Cross-platform confirm dialog.
 * `Alert.alert` on RN Web silently no-ops the button callbacks (well-known
 * limitation), which meant tapping UNAPPROVE on the coach's web dashboard
 * did literally nothing. Fall back to `window.confirm` on web where the
 * native browser dialog gives us a synchronous yes/no.
 */
async function confirmDialog(title: string, message: string, confirmLabel = "Confirm"): Promise<boolean> {
  if (Platform.OS === "web") {
    return typeof window !== "undefined" && window.confirm(`${title}\n\n${message}`);
  }
  return new Promise((resolve) => {
    Alert.alert(title, message, [
      { text: "Cancel", style: "cancel", onPress: () => resolve(false) },
      { text: confirmLabel, style: "destructive", onPress: () => resolve(true) },
    ]);
  });
}

type PendingRow = {
  id: string;                 // roster id
  user_id: string;            // client id
  client_first_name?: string;
  client_last_name?: string;
  awaiting_review_since?: string;
  start_date?: string;
  end_date?: string;
};

type ApprovedRow = {
  id: string;
  user_id: string;
  client_first_name?: string;
  client_last_name?: string;
  coach_review_at?: string;
  coach_review_actor?: string;
  start_date?: string;
  end_date?: string;
};

export function CoachRosterReviewInbox() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [rows, setRows] = useState<PendingRow[]>([]);
  const [approved, setApproved] = useState<ApprovedRow[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [showApproved, setShowApproved] = useState(false);

  const load = useCallback(async () => {
    try {
      const [awaiting, recentlyApproved] = await Promise.all([
        api<{ count: number; clients: PendingRow[] }>(
          "/coach/rosters-awaiting-review",
        ).catch(() => ({ count: 0, clients: [] } as any)),
        api<{ count: number; clients: ApprovedRow[] }>(
          "/coach/rosters-recently-approved",
        ).catch(() => ({ count: 0, clients: [] } as any)),
      ]);
      setRows(awaiting?.clients || []);
      setApproved(recentlyApproved?.clients || []);
    } catch {
      setRows([]);
      setApproved([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const submit = async (rid: string, outcome: "approved" | "rejected") => {
    if (busyId) return;
    setBusyId(rid);
    try {
      await api(`/coach/rosters/${rid}/review`, {
        method: "POST",
        body: { outcome },
      });
      setRows((prev) => prev.filter((r) => r.id !== rid));
      // A freshly-approved roster should also show up in the approved
      // list — refresh in background so it's there next expand.
      load();
    } catch {
      await load();
    } finally {
      setBusyId(null);
    }
  };

  const unapprove = async (rid: string, name: string) => {
    if (busyId) return;
    // Iter188 · Cross-platform confirm — Alert.alert on RN Web no-ops.
    const proceed = await confirmDialog(
      `Unapprove ${name}'s roster?`,
      "The client will be prompted to upload a fresh roster and receive a notification.",
      "Unapprove",
    );
    if (!proceed) return;
    setBusyId(rid);
    try {
      await api(`/coach/rosters/${rid}/unapprove`, {
        method: "POST",
        body: {},
      });
      setApproved((prev) => prev.filter((r) => r.id !== rid));
    } catch (e: any) {
      if (Platform.OS === "web" && typeof window !== "undefined") {
        window.alert(`Couldn't unapprove: ${e?.message || "Please try again."}`);
      } else {
        Alert.alert("Couldn't unapprove", e?.message || "Please try again.");
      }
      await load();
    } finally {
      setBusyId(null);
    }
  };

  if (loading) return null;
  if (rows.length === 0 && approved.length === 0) return null;

  return (
    <View style={styles.wrap} testID="coach-roster-review-inbox">
      {rows.length > 0 ? (
        <>
          <View style={styles.header}>
            <View style={styles.badge}>
              <Text style={styles.badgeT}>{rows.length}</Text>
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.title}>ROSTERS AWAITING YOUR REVIEW</Text>
              <Text style={styles.sub}>
                {rows.length === 1
                  ? "1 client is waiting for you to approve their submitted roster."
                  : `${rows.length} clients are waiting for you to approve their submitted rosters.`}
                {"  "}They can&apos;t re-upload until you act.
              </Text>
            </View>
          </View>

          {rows.map((row) => {
            const fullName = [row.client_first_name, row.client_last_name].filter(Boolean).join(" ") || "Client";
            const range = row.start_date && row.end_date
              ? `${row.start_date} → ${row.end_date}`
              : row.awaiting_review_since
                ? `submitted ${new Date(row.awaiting_review_since).toLocaleDateString()}`
                : "";
            const isBusy = busyId === row.id;
            return (
              <View key={row.id} style={styles.row} testID={`coach-roster-review-row-${row.id}`}>
                <Pressable
                  style={{ flex: 1 }}
                  onPress={() => router.push(`/coach/client/${row.user_id}/workspace` as any)}
                >
                  <Text style={styles.rowName}>{fullName}</Text>
                  {range ? <Text style={styles.rowMeta}>{range}</Text> : null}
                </Pressable>
                <View style={styles.actions}>
                  <Pressable
                    testID={`coach-roster-review-reject-${row.id}`}
                    onPress={() => submit(row.id, "rejected")}
                    disabled={isBusy}
                    style={[styles.rejectBtn, isBusy && { opacity: 0.5 }]}
                  >
                    <Ionicons name="refresh" size={12} color={theme.color.brand} />
                    <Text style={styles.rejectBtnT}>REQUEST NEW</Text>
                  </Pressable>
                  <Pressable
                    testID={`coach-roster-review-approve-${row.id}`}
                    onPress={() => submit(row.id, "approved")}
                    disabled={isBusy}
                    style={[styles.approveBtn, isBusy && { opacity: 0.5 }]}
                  >
                    {isBusy ? (
                      <ActivityIndicator color="#fff" size="small" />
                    ) : (
                      <>
                        <Ionicons name="checkmark" size={13} color="#fff" />
                        <Text style={styles.approveBtnT}>APPROVE</Text>
                      </>
                    )}
                  </Pressable>
                </View>
              </View>
            );
          })}

          <Text style={styles.autoHint}>
            Rosters auto-approve after 24 h if you don&apos;t act — the client won&apos;t be left waiting.
          </Text>
        </>
      ) : null}

      {/* Iter188 · Recently-approved rosters — collapsed by default. Coach
          can unapprove any of these to reopen the client's upload slot. */}
      {approved.length > 0 ? (
        <View style={styles.approvedSection} testID="coach-roster-recently-approved">
          <Pressable
            onPress={() => setShowApproved((s) => !s)}
            style={styles.approvedHeader}
            testID="coach-roster-approved-toggle"
          >
            <Ionicons
              name={showApproved ? "chevron-down" : "chevron-forward"}
              size={14}
              color={theme.color.textMuted}
            />
            <Text style={styles.approvedTitle}>
              RECENTLY APPROVED · {approved.length}
            </Text>
            <Text style={styles.approvedSubtle}>
              tap to {showApproved ? "hide" : "unapprove"}
            </Text>
          </Pressable>

          {showApproved ? approved.map((row) => {
            const fullName = [row.client_first_name, row.client_last_name].filter(Boolean).join(" ") || "Client";
            const when = row.coach_review_at
              ? new Date(row.coach_review_at).toLocaleDateString()
              : "";
            const actor = row.coach_review_actor === "auto_24h"
              ? "auto-approved"
              : "approved";
            const isBusy = busyId === row.id;
            return (
              <View key={row.id} style={styles.row} testID={`coach-roster-approved-row-${row.id}`}>
                <Pressable
                  style={{ flex: 1 }}
                  onPress={() => router.push(`/coach/client/${row.user_id}/workspace` as any)}
                >
                  <Text style={styles.rowName}>{fullName}</Text>
                  <Text style={styles.rowMeta}>{actor}{when ? ` · ${when}` : ""}</Text>
                </Pressable>
                <Pressable
                  testID={`coach-roster-unapprove-${row.id}`}
                  onPress={() => unapprove(row.id, fullName)}
                  disabled={isBusy}
                  style={[styles.unapproveBtn, isBusy && { opacity: 0.5 }]}
                >
                  {isBusy ? (
                    <ActivityIndicator color={theme.color.brand} size="small" />
                  ) : (
                    <>
                      <Ionicons name="close" size={12} color={theme.color.brand} />
                      <Text style={styles.unapproveBtnT}>UNAPPROVE</Text>
                    </>
                  )}
                </Pressable>
              </View>
            );
          }) : null}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    marginHorizontal: 16,
    marginBottom: 12,
    padding: 14,
    borderRadius: 14,
    backgroundColor: theme.color.brandTint,
    borderWidth: 1,
    borderColor: theme.color.brand,
    gap: 12,
  },
  header: { flexDirection: "row", gap: 12, alignItems: "flex-start" },
  badge: {
    minWidth: 34, height: 34, borderRadius: 17,
    paddingHorizontal: 8,
    alignItems: "center", justifyContent: "center",
    backgroundColor: theme.color.brand,
  },
  badgeT: { color: "#fff", fontSize: 15, fontWeight: "900" },
  title: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  sub: { color: theme.color.text, fontSize: 12, lineHeight: 17, marginTop: 3 },

  row: {
    flexDirection: "row", alignItems: "center", gap: 10,
    padding: 12, borderRadius: 10,
    backgroundColor: theme.color.surface,
    borderWidth: 1, borderColor: theme.color.border,
  },
  rowName: { color: theme.color.text, fontSize: 13, fontWeight: "800" },
  rowMeta: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },

  actions: { flexDirection: "row", gap: 6 },
  rejectBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 10, paddingVertical: 8, borderRadius: 8,
    borderWidth: 1, borderColor: theme.color.brand,
    backgroundColor: "transparent",
  },
  rejectBtnT: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1 },
  approveBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8,
    backgroundColor: theme.color.brand,
  },
  approveBtnT: { color: "#fff", fontSize: 10, fontWeight: "900", letterSpacing: 1 },

  autoHint: {
    color: theme.color.textMuted, fontSize: 11, fontStyle: "italic", textAlign: "center",
  },

  // Iter188 · Recently-approved unapprove section
  approvedSection: {
    marginTop: 4,
    borderTopWidth: 1,
    borderTopColor: theme.color.divider,
    paddingTop: 12,
    gap: 8,
  },
  approvedHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingVertical: 4,
  },
  approvedTitle: {
    color: theme.color.textMuted,
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 1.6,
  },
  approvedSubtle: {
    color: theme.color.textMuted,
    fontSize: 10,
    fontStyle: "italic",
    marginLeft: "auto",
  },
  unapproveBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: theme.color.brand,
    backgroundColor: "transparent",
  },
  unapproveBtnT: {
    color: theme.color.brand,
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 1,
  },
});
