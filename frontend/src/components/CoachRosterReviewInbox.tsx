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
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type PendingRow = {
  id: string;                 // roster id
  user_id: string;            // client id
  client_first_name?: string;
  client_last_name?: string;
  awaiting_review_since?: string;
  start_date?: string;
  end_date?: string;
};

export function CoachRosterReviewInbox() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [rows, setRows] = useState<PendingRow[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await api<{ count: number; clients: PendingRow[] }>(
        "/coach/rosters-awaiting-review"
      );
      setRows(r?.clients || []);
    } catch {
      setRows([]);
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
      // Optimistically drop the row so the queue count drops immediately.
      setRows((prev) => prev.filter((r) => r.id !== rid));
    } catch {
      // On failure, reload so state matches server truth.
      await load();
    } finally {
      setBusyId(null);
    }
  };

  if (loading) return null;
  if (rows.length === 0) return null;

  return (
    <View style={styles.wrap} testID="coach-roster-review-inbox">
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
});
