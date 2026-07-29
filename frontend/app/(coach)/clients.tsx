/**
 * Clients — canonical directory (Iter 128h)
 *
 * One responsibility: "Who do I coach and what is their current coaching
 * state?"
 *
 * Home already answers "what needs my attention?" — this page complements
 * it by showing every client in a compact row with:
 *
 *     IDENTITY · GOAL · PLAN STATE · ROSTER STATE · NEXT ACTION
 *
 * Backend source: /api/v2/coach/clients/directory (deterministic aggregator
 * that reuses the same next-action logic as the Home Action Queue).
 *
 * NOT a dashboard. NOT admin. NOT a preview sandbox. NOT the legacy
 * multi-filter view.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, TextInput,
} from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { ProfileAvatar } from "@/src/components/ProfileAvatar";
import { AddClientSheet } from "@/src/components/AddClientSheet";
import { PreviewClientButton } from "@/src/components/PreviewLauncher";
import { useAuth } from "@/src/lib/auth";

type FilterKind = "active" | "needs_attention" | "archived";

type PlanState = {
  kind: string;
  label: string;
  tint: "green" | "amber" | "dim" | "red";
  sub?: string | null;
  sub_tint?: string | null;
};
type RosterState = {
  kind: string;
  label: string;
  tint: "green" | "amber" | "dim" | "red";
  sub?: string | null;
};
type NextAction = {
  label: string;
  deep_link: string;
  priority: "urgent" | "attention" | "upcoming" | "normal" | "waiting";
  task_type?: string | null;
};
type Row = {
  id: string;
  name: string;
  email?: string | null;
  avatar_url?: string | null;
  role_line?: string | null;
  goal: { label: string; phase?: string | null };
  plan: PlanState;
  roster: RosterState;
  next_action: NextAction;
  attention_count: number;
  status: string;
};
type Directory = {
  clients: Row[];
  counts: { active: number; needs_attention: number; archived: number };
  filter: FilterKind;
  q: string;
};

const TINT_MAP: Record<string, string> = {
  green: "#61c982",
  amber: "#f5b543",
  dim:   theme.color.textDim,
  red:   "#ff5b5b",
};

const PRIORITY_ACCENT: Record<string, string> = {
  urgent:    "#ff5b5b",
  attention: "#f5b543",
  upcoming:  "#5aa9e6",
  waiting:   theme.color.textDim,
  normal:    theme.color.textHi,
};

export default function ClientsScreen() {
  const router = useRouter();
  useAuth();  // ensure re-render on login change
  const [filter, setFilter] = useState<FilterKind>("active");
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [data, setData] = useState<Directory | null>(null);
  const [loading, setLoading] = useState(true);
  const [addOpen, setAddOpen] = useState(false);

  // debounce search input
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 200);
    return () => clearTimeout(t);
  }, [q]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("filter", filter);
      if (debouncedQ) params.set("q", debouncedQ);
      const res = await api<Directory>(`/v2/coach/clients/directory?${params.toString()}`);
      setData(res);
    } catch (e: any) {
      // fail silently — surface via UI empty state
      console.warn("clients directory load failed:", e?.message || e);
      setData({ clients: [], counts: { active: 0, needs_attention: 0, archived: 0 }, filter, q: "" });
    } finally {
      setLoading(false);
    }
  }, [filter, debouncedQ]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={{ paddingBottom: 60 }}
        testID="clients-page"
      >
        {/* Header */}
        <View style={styles.header}>
          <View style={{ flex: 1 }}>
            <Text style={styles.h1}>Clients</Text>
            <Text style={styles.h1sub}>
              {data
                ? filter === "archived"
                  ? `${data.counts.archived} archived`
                  : `${data.counts.active} active client${data.counts.active === 1 ? "" : "s"}`
                : "…"}
            </Text>
          </View>
          <Pressable
            style={styles.addBtn}
            onPress={() => setAddOpen(true)}
            testID="clients-add"
          >
            <Ionicons name="add" size={16} color="#fff" />
            <Text style={styles.addBtnText}>Add Client</Text>
          </Pressable>
        </View>

        {/* Filter tabs + search */}
        <View style={styles.toolbar}>
          <View style={styles.tabs}>
            <FilterTab
              label="Active"      count={data?.counts.active}
              active={filter === "active"}
              onPress={() => setFilter("active")}
              testID="filter-active"
            />
            <FilterTab
              label="Needs Attention" count={data?.counts.needs_attention}
              active={filter === "needs_attention"} amber
              onPress={() => setFilter("needs_attention")}
              testID="filter-needs-attention"
            />
            <FilterTab
              label="Archived"    count={data?.counts.archived}
              active={filter === "archived"} muted
              onPress={() => setFilter("archived")}
              testID="filter-archived"
            />
          </View>
          <View style={styles.searchBox}>
            <Ionicons name="search" size={14} color={theme.color.textDim} />
            <TextInput
              value={q}
              onChangeText={setQ}
              placeholder="Search clients…"
              placeholderTextColor={theme.color.textDim}
              style={styles.searchInput}
              testID="clients-search"
            />
            {q ? (
              <Pressable onPress={() => setQ("")} testID="clients-search-clear">
                <Ionicons name="close-circle" size={14} color={theme.color.textDim} />
              </Pressable>
            ) : null}
          </View>
        </View>

        {/* Column headers */}
        <View style={styles.colHead}>
          <Text style={[styles.colHeadText, styles.colClient]}>CLIENT</Text>
          <Text style={[styles.colHeadText, styles.colGoal]}>GOAL</Text>
          <Text style={[styles.colHeadText, styles.colPlan]}>PLAN</Text>
          <Text style={[styles.colHeadText, styles.colRoster]}>ROSTER</Text>
          <Text style={[styles.colHeadText, styles.colAction]}>NEXT ACTION</Text>
        </View>

        {/* Body */}
        {loading && !data ? (
          <View style={styles.centered}><ActivityIndicator color={theme.color.brand} /></View>
        ) : !data || data.clients.length === 0 ? (
          <EmptyState filter={filter} q={debouncedQ} />
        ) : (
          data.clients.map((r) => (
            <ClientRow key={r.id} row={r} onOpen={(link) => router.push(link as any)} />
          ))
        )}
      </ScrollView>

      <AddClientSheet
        visible={addOpen}
        onClose={() => setAddOpen(false)}
        onCreated={async () => { setAddOpen(false); await load(); }}
      />
    </SafeAreaView>
  );
}

/* -------------------------------------------------------------------------- */
/*  Filter tab                                                                */
/* -------------------------------------------------------------------------- */
function FilterTab({
  label, count, active, amber, muted, onPress, testID,
}: {
  label: string; count?: number; active: boolean; amber?: boolean; muted?: boolean;
  onPress: () => void; testID?: string;
}) {
  const showCount = typeof count === "number";
  const showAmberDot = !!amber && !active && (count || 0) > 0;
  return (
    <Pressable
      onPress={onPress}
      style={[
        styles.tab,
        active && styles.tabActive,
        active && amber && styles.tabActiveAmber,
        active && muted && styles.tabActiveMuted,
      ]}
      testID={testID}
    >
      <Text style={[styles.tabText, active && styles.tabTextActive]}>{label}</Text>
      {showCount ? (
        <Text style={[styles.tabCount, active && styles.tabCountActive]}>{count}</Text>
      ) : null}
      {showAmberDot ? <View style={styles.amberDot} /> : null}
    </Pressable>
  );
}

/* -------------------------------------------------------------------------- */
/*  Client row                                                                */
/* -------------------------------------------------------------------------- */
function ClientRow({ row, onOpen }: { row: Row; onOpen: (link: string) => void }) {
  const primaryTint = PRIORITY_ACCENT[row.next_action.priority] || theme.color.textHi;
  const isUrgent = row.next_action.priority === "urgent";
  return (
    <Pressable
      style={styles.row}
      onPress={() => onOpen(`/coach/client/${row.id}/workspace`)}
      testID={`client-row-${row.id}`}
    >
      {/* CLIENT */}
      <View style={[styles.cell, styles.colClient]}>
        <ProfileAvatar userId={row.id} name={row.name} photoUrl={row.avatar_url || null} size={38} ring={false} />
        <View style={{ flex: 1, marginLeft: 10, minWidth: 0 }}>
          <Text style={styles.cName} numberOfLines={1}>{row.name}</Text>
          {row.role_line ? (
            <Text style={styles.cSub} numberOfLines={1}>{row.role_line}</Text>
          ) : (
            <Text style={styles.cSub} numberOfLines={1}>{row.email || ""}</Text>
          )}
        </View>
      </View>

      {/* GOAL */}
      <View style={[styles.cell, styles.colGoal]}>
        <Text style={styles.goalLabel} numberOfLines={1}>{row.goal.label}</Text>
        {row.goal.phase ? (
          <Text style={styles.goalPhase} numberOfLines={1}>{row.goal.phase}</Text>
        ) : null}
      </View>

      {/* PLAN */}
      <View style={[styles.cell, styles.colPlan]}>
        <View style={styles.stateLine}>
          <View style={[styles.stateDot, { backgroundColor: TINT_MAP[row.plan.tint] || theme.color.textDim }]} />
          <Text style={[styles.stateLabel, { color: TINT_MAP[row.plan.tint] || theme.color.textHi }]}>
            {row.plan.label}
          </Text>
        </View>
        {row.plan.sub ? (
          <Text style={[styles.stateSub, { color: TINT_MAP[row.plan.sub_tint || "dim"] || theme.color.textDim }]}
                numberOfLines={2}>
            {row.plan.sub}
          </Text>
        ) : null}
      </View>

      {/* ROSTER */}
      <View style={[styles.cell, styles.colRoster]}>
        <View style={styles.stateLine}>
          <Ionicons
            name={row.roster.kind === "required" ? "cloud-upload-outline" : "calendar-outline"}
            size={12}
            color={TINT_MAP[row.roster.tint] || theme.color.textDim}
            style={{ marginRight: 6 }}
          />
          <Text style={[styles.stateLabel, { color: TINT_MAP[row.roster.tint] || theme.color.textHi }]}
                numberOfLines={1}>
            {row.roster.label}
          </Text>
        </View>
        {row.roster.sub ? (
          <Text style={styles.stateSub} numberOfLines={1}>{row.roster.sub}</Text>
        ) : null}
      </View>

      {/* NEXT ACTION */}
      <View style={[styles.cell, styles.colAction, { alignItems: "flex-end" }]}>
        <Pressable
          onPress={(e) => { e.stopPropagation?.(); onOpen(row.next_action.deep_link); }}
          style={[
            styles.actionBtn,
            isUrgent && styles.actionBtnUrgent,
          ]}
          testID={`client-action-${row.id}`}
        >
          <Text style={[styles.actionBtnText, isUrgent && styles.actionBtnTextUrgent]}>
            {row.next_action.label}
          </Text>
          <Ionicons
            name="arrow-forward"
            size={12}
            color={isUrgent ? "#fff" : primaryTint}
          />
        </Pressable>
        {/* Secondary Preview link — small, non-competing (brief §15) */}
        <View style={{ marginTop: 6 }} onStartShouldSetResponder={() => true}>
          <PreviewClientButton clientId={row.id} clientName={row.name} />
        </View>
      </View>
    </Pressable>
  );
}

/* -------------------------------------------------------------------------- */
/*  Empty state                                                               */
/* -------------------------------------------------------------------------- */
function EmptyState({ filter, q }: { filter: FilterKind; q: string }) {
  let title = "No clients yet";
  let body  = "Tap Add Client to onboard your first client.";
  if (q) {
    title = "No matches";
    body  = `Nothing matches “${q}”. Try a different name, airline, or email.`;
  } else if (filter === "needs_attention") {
    title = "You're all caught up";
    body  = "No client in the roster needs your attention right now.";
  } else if (filter === "archived") {
    title = "No archived clients";
    body  = "Archived clients will appear here.";
  }
  return (
    <View style={styles.emptyBox} testID="clients-empty">
      <Ionicons name="people-outline" size={30} color={theme.color.textDim} />
      <Text style={styles.emptyTitle}>{title}</Text>
      <Text style={styles.emptyBody}>{body}</Text>
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/*  Styles                                                                    */
/* -------------------------------------------------------------------------- */
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.bg },
  centered: { padding: 40, alignItems: "center", justifyContent: "center" },

  /* Header */
  header: {
    flexDirection: "row", alignItems: "flex-start",
    paddingHorizontal: 24, paddingTop: 20, paddingBottom: 12, gap: 12,
  },
  h1: { color: theme.color.textHi, fontSize: 26, fontWeight: "800", letterSpacing: 0.3 },
  h1sub: { color: theme.color.textDim, fontSize: 12, marginTop: 4 },
  addBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: theme.color.brand,
    paddingHorizontal: 14, paddingVertical: 9, borderRadius: 8,
  },
  addBtnText: { color: "#fff", fontWeight: "800", fontSize: 13 },

  /* Toolbar */
  toolbar: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 24, paddingBottom: 12, gap: 12, flexWrap: "wrap",
  },
  tabs: { flexDirection: "row", gap: 8, flexWrap: "wrap" },
  tab: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: 8,
    borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface2,
  },
  tabActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  tabActiveAmber: { backgroundColor: "#f5b543", borderColor: "#f5b543" },
  tabActiveMuted: { backgroundColor: theme.color.surface, borderColor: theme.color.border },
  tabText: { color: theme.color.textHi, fontSize: 12, fontWeight: "700" },
  tabTextActive: { color: "#fff" },
  tabCount: {
    color: theme.color.textDim, fontSize: 12, fontWeight: "800",
    minWidth: 16, textAlign: "center",
  },
  tabCountActive: { color: "#fff" },
  amberDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: "#f5b543" },
  searchBox: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: theme.color.surface2, borderRadius: 8,
    borderWidth: 1, borderColor: theme.color.border,
    paddingHorizontal: 10, paddingVertical: 8, minWidth: 240, flex: 1, maxWidth: 360,
  },
  searchInput: {
    flex: 1, color: theme.color.textHi, fontSize: 13, padding: 0,
    outlineStyle: "none" as any,
  },

  /* Column headers */
  colHead: {
    flexDirection: "row", alignItems: "center", paddingHorizontal: 24,
    paddingVertical: 8, gap: 16,
  },
  colHeadText: {
    color: theme.color.textDim, fontSize: 10, letterSpacing: 1.5, fontWeight: "800",
  },
  colClient: { flex: 2.4, flexDirection: "row", alignItems: "center", minWidth: 200 },
  colGoal:   { flex: 1.2, minWidth: 130 },
  colPlan:   { flex: 1.6, minWidth: 170 },
  colRoster: { flex: 1.4, minWidth: 150 },
  colAction: { flex: 1.4, minWidth: 170 },

  /* Rows */
  row: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: 24, paddingVertical: 12, gap: 16,
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
    backgroundColor: theme.color.surface2, marginHorizontal: 12, marginTop: 6,
    borderRadius: 10, borderWidth: 1,
  },
  cell: { justifyContent: "center" },

  cName: { color: theme.color.textHi, fontSize: 14, fontWeight: "800" },
  cSub: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },

  goalLabel: { color: theme.color.textHi, fontSize: 13, fontWeight: "700" },
  goalPhase: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },

  stateLine: { flexDirection: "row", alignItems: "center" },
  stateDot: { width: 8, height: 8, borderRadius: 4, marginRight: 6 },
  stateLabel: { fontSize: 12, fontWeight: "800", letterSpacing: 0.3 },
  stateSub: { color: theme.color.textDim, fontSize: 11, marginTop: 3 },

  actionBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border,
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: 6,
  },
  actionBtnUrgent: { backgroundColor: "#f5b543", borderColor: "#f5b543" },
  actionBtnText: { color: theme.color.textHi, fontSize: 12, fontWeight: "700" },
  actionBtnTextUrgent: { color: "#000" },

  /* Empty */
  emptyBox: {
    marginHorizontal: 24, marginTop: 24, padding: 30,
    alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: theme.color.surface2, borderRadius: 12,
    borderWidth: 1, borderColor: theme.color.border,
  },
  emptyTitle: { color: theme.color.textHi, fontSize: 16, fontWeight: "800", marginTop: 4 },
  emptyBody: { color: theme.color.textDim, fontSize: 13, textAlign: "center", maxWidth: 360, lineHeight: 18 },
});
