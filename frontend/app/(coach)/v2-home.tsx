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
import { View, Text, Pressable, StyleSheet, ScrollView, ActivityIndicator, TextInput } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { useAuth } from "@/src/lib/auth";
import { AddClientSheet } from "@/src/components/AddClientSheet";

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

type ClientRow = {
  client_id: string;
  name: string;
  email?: string;
  avatar_url?: string;
  kind: "v1" | "v2";
  goal?: string;
  phase?: string;
  today_label?: string;
  attention_count: number;
  status_chip: "ready" | "review" | "conflict" | "roster_changed" | "checkin";
  chip_detail: string;
};

const FILTERS: { id: string; label: string }[] = [
  { id: "all", label: "All" },
  { id: "attention", label: "Needs Attention" },
  { id: "programme_ready", label: "Programme Ready" },
  { id: "roster_changed", label: "Roster Changed" },
  { id: "quiet", label: "No Action" },
];

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
  const [clients, setClients] = useState<ClientRow[]>([]);
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [addClientOpen, setAddClientOpen] = useState(false);

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
      const [sum, att, cli] = await Promise.all([
        api("/v2/coach/dashboard/summary").catch(() => null),
        api("/v2/coach/dashboard/attention").catch(() => ({ attention: [] })),
        api(`/v2/coach/dashboard/clients?filter=${filter}${search ? `&q=${encodeURIComponent(search)}` : ""}`)
          .catch(() => ({ clients: [] })),
      ]);
      setSummary(sum);
      setAttention((att as any).attention || []);
      setClients((cli as any).clients || []);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [filter, search]);

  useEffect(() => { load(); }, [load]);

  const enableV2 = useCallback(async () => {
    setBusy(true);
    try {
      await api("/v2/coach/me/dashboard-flag", { method: "PATCH", body: { coach_dashboard_v2_enabled: true } });
      await load();
    } finally { setBusy(false); }
  }, [load]);

  const disableV2 = useCallback(async () => {
    setBusy(true);
    try {
      await api("/v2/coach/me/dashboard-flag", { method: "PATCH", body: { coach_dashboard_v2_enabled: false } });
      setEnabled(false);
    } finally { setBusy(false); }
  }, []);

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
          <Text style={styles.optTitle}>Coach Dashboard V2</Text>
          <Text style={styles.optBody}>
            Preview the new Attention + Roster + Plan workspace. Your existing V1 dashboard
            stays fully available; you can switch back any time.
          </Text>
          <Pressable style={styles.primaryBtn} onPress={enableV2} disabled={busy} testID="enable-v2-btn">
            <Text style={styles.primaryBtnText}>{busy ? "Enabling…" : "Enable V2 preview"}</Text>
          </Pressable>
          <Pressable onPress={() => router.replace("/(coach)/overview")} style={{ marginTop: 12 }}>
            <Text style={styles.secondaryLink}>Back to V1 Overview</Text>
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
          <Text style={styles.h1sub}>Welcome back{user?.name ? `, ${user.name.split(" ")[0]}` : ""}. Here's who needs you.</Text>
        </View>
        <Pressable onPress={disableV2} style={styles.chip} testID="disable-v2-btn">
          <Text style={styles.chipText}>Switch to V1</Text>
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
            <Text style={styles.emptyBody}>CrewFit is handling the current plan for every client. You'll be notified when review is needed.</Text>
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

      {/* Client list */}
      <View style={styles.section}>
        <View style={styles.clientHeadRow}>
          <Text style={styles.sectionTitle}>CLIENTS</Text>
          <Pressable
            onPress={() => setAddClientOpen(true)}
            style={styles.addClientBtn}
            testID="add-client-btn"
          >
            <Ionicons name="person-add" size={14} color="#000" />
            <Text style={styles.addClientBtnText}>Add client</Text>
          </Pressable>
          <TextInput
            placeholder="Search…"
            placeholderTextColor={theme.color.textDim}
            value={search}
            onChangeText={setSearch}
            style={styles.searchBox}
            testID="client-search"
          />
        </View>
        <View style={styles.filterRow}>
          {FILTERS.map((f) => (
            <Pressable
              key={f.id}
              onPress={() => setFilter(f.id)}
              style={[styles.filterBtn, filter === f.id && styles.filterBtnActive]}
              testID={`filter-${f.id}`}
            >
              <Text style={[styles.filterBtnText, filter === f.id && styles.filterBtnTextActive]}>{f.label}</Text>
            </Pressable>
          ))}
        </View>

        {clients.length === 0 ? (
          <Text style={styles.emptyBody}>No clients match this filter.</Text>
        ) : (
          <View style={styles.clientTable}>
            <View style={styles.clientTableHead}>
              <Text style={[styles.clientCol, styles.colClient]}>CLIENT</Text>
              <Text style={[styles.clientCol, styles.colGoal]}>GOAL</Text>
              <Text style={[styles.clientCol, styles.colPhase]}>PHASE</Text>
              <Text style={[styles.clientCol, styles.colToday]}>TODAY</Text>
              <Text style={[styles.clientCol, styles.colStatus]}>STATUS</Text>
            </View>
            {clients.map((c) => (
              <Pressable
                key={c.client_id}
                style={styles.clientRow}
                onPress={() => router.push(`/coach/client/${c.client_id}/workspace` as any)}
                testID={`client-row-${c.client_id}`}
              >
                <Text style={[styles.clientCol, styles.colClient, styles.clientName]} numberOfLines={1}>{c.name}</Text>
                <Text style={[styles.clientCol, styles.colGoal]} numberOfLines={1}>{c.goal || "—"}</Text>
                <Text style={[styles.clientCol, styles.colPhase]} numberOfLines={1}>{c.phase || "—"}</Text>
                <Text style={[styles.clientCol, styles.colToday]} numberOfLines={1}>{c.today_label || "—"}</Text>
                <View style={[styles.colStatus, { flexDirection: "row", alignItems: "center", gap: 6 }]}>
                  <StatusPill kind={c.status_chip} count={c.attention_count} />
                </View>
              </Pressable>
            ))}
          </View>
        )}
      </View>

      {error && <Text style={styles.errorText}>{error}</Text>}
      <AddClientSheet
        visible={addClientOpen}
        onClose={() => setAddClientOpen(false)}
        onCreated={() => { setAddClientOpen(false); load(); }}
      />
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

function StatusPill({ kind, count }: { kind: ClientRow["status_chip"]; count: number }) {
  const config: Record<string, { label: string; bg: string; fg: string }> = {
    ready:          { label: count > 0 ? `${count} ready` : "Ready",       bg: "#183020", fg: "#61c982" },
    review:         { label: count > 0 ? `${count} review`  : "Review",    bg: "#3b2d0d", fg: "#f5b543" },
    conflict:       { label: "Conflict",                                    bg: "#3a1414", fg: "#ff6b6b" },
    roster_changed: { label: "Roster changed",                              bg: "#0d2c3b", fg: "#5aa9e6" },
    checkin:        { label: "Check-in",                                    bg: "#3a1a2d", fg: "#e07eaa" },
  };
  const c = config[kind] || config.ready;
  return (
    <View style={[styles.statusPill, { backgroundColor: c.bg }]}>
      <Text style={[styles.statusPillText, { color: c.fg }]}>{c.label}</Text>
    </View>
  );
}

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
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
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
});
