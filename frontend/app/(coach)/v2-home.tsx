/**
 * Coach Dashboard V2 — Global Attention Home
 *
 * Route: /(coach)/v2-home
 *
 * Shows:
 *   - Today summary (24 active · 5 need attention · ...)
 *   - Needs Your Attention queue (cross-client)
 *   - Client list with V2 state chips + filters
 *
 * Requires the coach to have opted into `coach_dashboard_v2_enabled`.
 * If not enabled, offers a one-click enable and links back to V1 overview.
 */
import React, { useEffect, useMemo, useState, useCallback } from "react";
import { View, Text, Pressable, StyleSheet, ScrollView, ActivityIndicator } from "react-native";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { useAuth } from "@/src/lib/auth";

type AttentionRow = {
  client_id: string;
  client_name: string;
  kind: string;
  severity: "info" | "warning" | "blocker";
  reason: string;
  created_at?: string;
  scope_ref?: string;
  counts?: { ready?: number; review?: number; conflict?: number };
};

// Iter 128b — Client list widget removed from Home. Home is the operations
// dashboard; the canonical Clients directory now lives exclusively at
// /(coach)/clients (richer view with roster progress, filters, Preview,
// Review, Add client). All V1/V2 legacy visual references stripped.

const KIND_LABELS: Record<string, string> = {
  programme_ready: "Programme ready for approval",
  roster_changed: "Roster changed",
  pain_reported: "Pain reported",
  checkin_concern: "Check-in concern",
  missed_key_session: "Missed key session",
  event_at_risk: "Event requirement at risk",
  conflict: "Conflict",
  needs_review: "Needs review",
  generation_failure: "Generation failure",
  roster_parsing: "Roster parsing issue",
};

const SEVERITY_TINT: Record<string, string> = {
  blocker: "#ff5555",
  warning: "#f5b543",
  info: "#5aa9e6",
};

export default function CoachDashboardV2Home() {
  const router = useRouter();
  const { user } = useAuth();
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [summary, setSummary] = useState<any>(null);
  const [attention, setAttention] = useState<AttentionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const flag = await api<{ enabled: boolean }>("/v2/coach/me/dashboard-flag");
      setEnabled(flag.enabled);
      if (!flag.enabled) {
        setLoading(false);
        return;
      }
      const [sum, att] = await Promise.all([
        api("/v2/coach/dashboard/summary").catch(() => null),
        api("/v2/coach/dashboard/attention").catch(() => ({ attention: [] })),
      ]);
      setSummary(sum);
      setAttention((att as any).attention || []);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const enableV2 = useCallback(async () => {
    setBusy(true);
    try {
      await api("/v2/coach/me/dashboard-flag", { method: "PATCH", body: { coach_dashboard_v2_enabled: true } });
      await load();
    } finally { setBusy(false); }
  }, [load]);

  const attentionByClient = useMemo(() => {
    const map: Record<string, AttentionRow[]> = {};
    for (const r of attention) {
      (map[r.client_id] ||= []).push(r);
    }
    return map;
  }, [attention]);

  if (loading && enabled === null) {
    return <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>;
  }

  if (enabled === false) {
    return (
      <View style={[styles.root, styles.center]}>
        <View style={styles.optCard}>
          <Text style={styles.optTitle}>Coach Home</Text>
          <Text style={styles.optBody}>
            Enable the new Attention + Roster + Plan workspace to see everything
            that needs your review in one place.
          </Text>
          <Pressable style={styles.primaryBtn} onPress={enableV2} disabled={busy} testID="enable-v2-btn">
            <Text style={styles.primaryBtnText}>{busy ? "Enabling…" : "Enable"}</Text>
          </Pressable>
        </View>
      </View>
    );
  }

  return (
    <ScrollView style={styles.root} contentContainerStyle={{ paddingBottom: 80 }} testID="coach-dashboard-v2">
      <View style={styles.topRow}>
        <View style={{ flex: 1 }}>
          <Text style={styles.h1}>Coach Home</Text>
          <Text style={styles.h1sub}>Welcome back{user?.name ? `, ${user.name.split(" ")[0]}` : ""}. Here&apos;s who needs you.</Text>
        </View>
        <Pressable
          onPress={() => router.push("/(coach)/clients" as any)}
          style={styles.chip}
          testID="home-view-clients"
        >
          <Text style={styles.chipText}>View clients →</Text>
        </Pressable>
      </View>

      {/* Today summary */}
      {summary && (
        <View style={styles.summaryRow}>
          <SummaryCell label="Active clients"     value={summary.active_clients} />
          <SummaryCell label="Need attention"     value={summary.need_attention} tint={summary.need_attention ? "#f5b543" : undefined} />
          <SummaryCell label="Programmes ready"   value={summary.programmes_ready} />
          <SummaryCell label="Roster changes"     value={summary.roster_changes} />
          <SummaryCell label="Check-in concerns"  value={summary.checkin_concerns} tint={summary.checkin_concerns ? "#f5b543" : undefined} />
        </View>
      )}

      {/* Attention queue */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>NEEDS YOUR ATTENTION</Text>
        {attention.length === 0 ? (
          <View style={styles.emptyBox}>
            <Text style={styles.emptyTitle}>Nothing needs your attention</Text>
            <Text style={styles.emptyBody}>CrewFit is handling the current plan for every client. You&apos;ll be notified when review is needed.</Text>
          </View>
        ) : (
          Object.entries(attentionByClient).map(([cid, rows]) => (
            <View key={cid} style={styles.attnCard}>
              <View style={styles.attnHeader}>
                <Text style={styles.attnClient}>{rows[0].client_name}</Text>
                <Pressable
                  onPress={() => router.push(`/coach/client/${cid}/workspace` as any)}
                  style={styles.reviewBtn}
                  testID={`attn-review-${cid}`}
                >
                  <Text style={styles.reviewBtnText}>Review</Text>
                </Pressable>
              </View>
              {rows.map((r, i) => (
                <View key={i} style={styles.attnRow}>
                  <View style={[styles.sevDot, { backgroundColor: SEVERITY_TINT[r.severity] || "#999" }]} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.attnKind}>{KIND_LABELS[r.kind] || r.kind}</Text>
                    <Text style={styles.attnReason}>{r.reason}</Text>
                  </View>
                </View>
              ))}
            </View>
          ))
        )}
      </View>

      {/* Iter 128b — Client list intentionally removed from Home.
          Home is the operations dashboard. The canonical Clients directory
          lives at /(coach)/clients (richer profile, roster progress, filters,
          Preview/Review, Add client). Keeping duplication out of Home. */}

      {error && <Text style={styles.errorText}>{error}</Text>}
    </ScrollView>
  );
}

function SummaryCell({ label, value, tint }: { label: string; value: any; tint?: string }) {
  return (
    <View style={styles.sumCell}>
      <Text style={[styles.sumValue, tint ? { color: tint } : null]}>{value ?? "—"}</Text>
      <Text style={styles.sumLabel}>{label}</Text>
    </View>
  );
}

// StatusPill and ClientRow types removed with the client-list widget (iter 128b).

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.bg },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  optCard: {
    maxWidth: 480, backgroundColor: theme.color.surface2, borderRadius: 12,
    borderWidth: 1, borderColor: theme.color.border, padding: 24, alignItems: "center",
  },
  optTitle: { color: theme.color.textHi, fontSize: 20, fontWeight: "800", marginBottom: 12 },
  optBody: { color: theme.color.textDim, textAlign: "center", marginBottom: 20, lineHeight: 20 },
  primaryBtn: {
    backgroundColor: theme.color.brand, paddingHorizontal: 24, paddingVertical: 12,
    borderRadius: 8, minWidth: 200, alignItems: "center",
  },
  primaryBtnText: { color: "#000", fontWeight: "800", letterSpacing: 1 },
  secondaryLink: { color: theme.color.textDim, textDecorationLine: "underline" },

  topRow: { flexDirection: "row", alignItems: "flex-start", padding: 24, paddingBottom: 12 },
  h1: { color: theme.color.textHi, fontSize: 28, fontWeight: "800", letterSpacing: 0.5 },
  h1sub: { color: theme.color.textDim, fontSize: 13, marginTop: 4 },
  chip: {
    backgroundColor: theme.color.surface2, paddingHorizontal: 12, paddingVertical: 6,
    borderRadius: 16, borderWidth: 1, borderColor: theme.color.border,
  },
  chipText: { color: theme.color.textDim, fontSize: 11, letterSpacing: 1, fontWeight: "700" },

  summaryRow: {
    flexDirection: "row", flexWrap: "wrap", gap: 10, marginHorizontal: 24, marginBottom: 12,
  },
  sumCell: {
    minWidth: 140, flex: 1, backgroundColor: theme.color.surface2, borderRadius: 10,
    padding: 14, borderWidth: 1, borderColor: theme.color.border,
  },
  sumValue: { color: theme.color.textHi, fontSize: 28, fontWeight: "800" },
  sumLabel: { color: theme.color.textDim, fontSize: 11, letterSpacing: 1, fontWeight: "700", marginTop: 2 },

  section: { marginTop: 24, paddingHorizontal: 24 },
  sectionTitle: { color: theme.color.textDim, fontSize: 12, letterSpacing: 1.5, fontWeight: "800", marginBottom: 12 },

  emptyBox: {
    backgroundColor: theme.color.surface2, borderRadius: 10, borderWidth: 1,
    borderColor: theme.color.border, padding: 18,
  },
  emptyTitle: { color: theme.color.textHi, fontSize: 15, fontWeight: "700", marginBottom: 4 },
  emptyBody: { color: theme.color.textDim, fontSize: 13, lineHeight: 18 },

  attnCard: {
    backgroundColor: theme.color.surface2, borderRadius: 10, borderWidth: 1,
    borderColor: theme.color.border, padding: 14, marginBottom: 10,
  },
  attnHeader: { flexDirection: "row", alignItems: "center", marginBottom: 8 },
  attnClient: { color: theme.color.textHi, fontSize: 16, fontWeight: "700", flex: 1 },
  reviewBtn: {
    backgroundColor: theme.color.brand, paddingHorizontal: 14, paddingVertical: 6, borderRadius: 6,
  },
  reviewBtnText: { color: "#000", fontWeight: "800", fontSize: 11, letterSpacing: 1 },
  attnRow: { flexDirection: "row", alignItems: "flex-start", paddingVertical: 4 },
  sevDot: { width: 8, height: 8, borderRadius: 4, marginTop: 6, marginRight: 10 },
  attnKind: { color: theme.color.textHi, fontSize: 13, fontWeight: "600" },
  attnReason: { color: theme.color.textDim, fontSize: 12, marginTop: 1 },

  clientHeadRow: { flexDirection: "row", alignItems: "center", marginBottom: 8, gap: 8 },
  addClientBtn: {
    marginLeft: "auto", flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: theme.color.brand, borderRadius: 6,
    paddingHorizontal: 12, paddingVertical: 7,
  },
  addClientBtnText: { color: "#000", fontSize: 12, fontWeight: "800", letterSpacing: 0.3 },
  searchBox: {
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
    borderRadius: 6, paddingHorizontal: 10, paddingVertical: 6, color: theme.color.textHi, minWidth: 180,
  },
  filterRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 12 },
  filterBtn: {
    backgroundColor: theme.color.surface2, paddingHorizontal: 12, paddingVertical: 6, borderRadius: 6,
    borderWidth: 1, borderColor: theme.color.border,
  },
  filterBtnActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  filterBtnText: { color: theme.color.textDim, fontSize: 12, fontWeight: "700" },
  filterBtnTextActive: { color: "#000" },

  clientTable: { backgroundColor: theme.color.surface2, borderRadius: 10, borderWidth: 1, borderColor: theme.color.border, overflow: "hidden" },
  clientTableHead: {
    flexDirection: "row", paddingHorizontal: 14, paddingVertical: 10,
    borderBottomWidth: 1, borderBottomColor: theme.color.border, backgroundColor: "#00000030",
  },
  clientRow: {
    flexDirection: "row", alignItems: "center", paddingHorizontal: 14, paddingVertical: 12,
    flex: 1,
  },
  clientRowWrap: {
    flexDirection: "row", alignItems: "stretch",
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  rowDeleteBtn: {
    paddingHorizontal: 12, alignItems: "center", justifyContent: "center",
    borderLeftWidth: 1, borderLeftColor: theme.color.border,
    backgroundColor: "transparent",
  },
  rowV2Btn: {
    paddingHorizontal: 12, alignItems: "center", justifyContent: "center",
    borderLeftWidth: 1, borderLeftColor: theme.color.border,
    backgroundColor: "transparent",
  },
  clientCol: { color: theme.color.textDim, fontSize: 12, letterSpacing: 0.5 },
  clientName: { color: theme.color.textHi, fontWeight: "700", fontSize: 14 },
  colClient: { flex: 2 },
  colGoal:   { flex: 1.5 },
  colPhase:  { flex: 1.2 },
  colToday:  { flex: 1.4 },
  colStatus: { flex: 1.4 },

  statusPill: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 12, alignSelf: "flex-start" },
  statusPillText: { fontSize: 11, fontWeight: "800", letterSpacing: 0.5 },

  errorText: { color: "#ff6666", padding: 16 },

  // Delete confirmation modal
  modalBackdrop: {
    flex: 1, backgroundColor: "rgba(0,0,0,0.75)",
    alignItems: "center", justifyContent: "center", padding: 20,
  },
  modalCard: {
    width: "100%", maxWidth: 460, backgroundColor: theme.color.surface2,
    borderRadius: 14, borderWidth: 1, borderColor: theme.color.border, padding: 22,
  },
  modalTitle: {
    color: theme.color.textHi, fontSize: 20, fontWeight: "800", marginBottom: 10,
  },
  modalBody: { color: theme.color.textDim, fontSize: 13, lineHeight: 19, marginBottom: 16 },
  modalBodyStrong: { color: theme.color.textHi, fontWeight: "700" },
  modalLabel: {
    color: theme.color.textDim, fontSize: 11, letterSpacing: 1, fontWeight: "700",
    textTransform: "uppercase", marginBottom: 4,
  },
  modalEmailHint: {
    color: theme.color.textHi, fontSize: 13, fontWeight: "600",
    marginBottom: 8, fontFamily: "monospace",
  },
  modalInput: {
    backgroundColor: theme.color.bg, borderWidth: 1, borderColor: theme.color.border,
    borderRadius: 8, paddingHorizontal: 12, paddingVertical: 10,
    color: theme.color.textHi, fontSize: 14, marginBottom: 6,
  },
  modalError: { color: "#ff6b6b", fontSize: 12, marginTop: 2, marginBottom: 4 },
  modalRow: { flexDirection: "row", gap: 10, marginTop: 14, justifyContent: "flex-end" },
  modalBtn: { paddingHorizontal: 16, paddingVertical: 10, borderRadius: 8, minWidth: 100, alignItems: "center" },
  modalBtnGhost: { backgroundColor: "transparent", borderWidth: 1, borderColor: theme.color.border },
  modalBtnGhostText: { color: theme.color.textDim, fontWeight: "700" },
  modalBtnDanger: { backgroundColor: "#c53030" },
  modalBtnDangerText: { color: "#fff", fontWeight: "800", letterSpacing: 0.3 },
});
