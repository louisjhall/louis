/**
 * /coach/admin/auto-media — Per-kind Auto-Media-Gen toggles.
 *
 * Louis flips which content kinds get auto-generated when a new
 * exercise lands in the library. Coach still has to approve.
 *
 * Backed by:
 *   GET  /api/coach/auto-media-gen/settings
 *   PATCH /api/coach/auto-media-gen/settings
 *
 * Env kill-switches (AUTO_MEDIA_GEN_<KIND>=false) always win over the
 * DB toggle — the screen shows them as locked with a badge.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, Switch,
  ActivityIndicator, RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast } from "@/src/lib/ux";

type SettingsPayload = {
  toggles: Record<string, boolean>;
  labels: Record<string, string>;
  env_kill_switches?: Record<string, boolean>;
};

type StatusPayload = {
  enabled?: boolean;
  budget_paused?: boolean;
  budget_paused_at?: string | null;
  budget_paused_reason?: string | null;
  budget_paused_by_kind?: string | null;
  budget_paused_by_exercise_id?: string | null;
  budget_resumed_at?: string | null;
};

// Cost hint per kind so Louis can see credit impact at a glance.
const COST_HINT: Record<string, string> = {
  image_primary:   "1 Nano-Banana image gen (single frame)",
  image_start:     "1 Nano-Banana image gen (extra frame)",
  image_end:       "1 Nano-Banana image gen (extra frame)",
  coaching_points: "1 Claude call (~500 tokens)",
  common_mistakes: "1 Claude call (~500 tokens)",
  alternatives:    "1 Claude call + auto-creates library drafts",
  instructions:    "1 Claude call (~500 tokens)",
};

// Split the toggles into two groups so images sit under their own section.
const IMAGE_KINDS = ["image_primary", "image_start", "image_end"];
const CONTENT_KINDS = ["coaching_points", "common_mistakes", "alternatives", "instructions"];

export default function AutoMediaSettingsScreen() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [saving, setSaving] = useState<string | null>(null);
  const [data, setData] = useState<SettingsPayload | null>(null);
  const [genStatus, setGenStatus] = useState<StatusPayload | null>(null);
  const [resuming, setResuming] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, st] = await Promise.all([
        api<SettingsPayload>("/coach/auto-media-gen/settings"),
        api<StatusPayload>("/coach/auto-media-gen/status").catch(() => null),
      ]);
      setData(s);
      setGenStatus(st);
    } catch (e: any) {
      toast(e?.message || "Couldn't load auto-media settings.", "error");
    } finally { setLoading(false); setRefreshing(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const resumeBudget = useCallback(async () => {
    setResuming(true);
    try {
      await api<any>("/coach/auto-media-gen/budget/resume", { method: "POST" });
      toast("Generation resumed — new tasks will fire on next exercise.", "success");
      await load();
    } catch (e: any) {
      toast(e?.message || "Couldn't resume generation.", "error");
    } finally { setResuming(false); }
  }, [load]);

  // Bundle helper — flip start + end frames together as "Multi-frame Images".
  const flipMultiFrame = useCallback(async (next: boolean) => {
    if (!data) return;
    setSaving("__multi_frame__");
    const patch: Record<string, boolean> = {};
    if (!(data.env_kill_switches || {})["image_start"]) patch.image_start = next;
    if (!(data.env_kill_switches || {})["image_end"])   patch.image_end   = next;
    try {
      const r = await api<any>("/coach/auto-media-gen/settings", {
        method: "PATCH", body: { toggles: patch },
      });
      if (r?.toggles) setData((d) => d ? { ...d, toggles: r.toggles } : d);
      toast(`Multi-frame Images → ${next ? "ON" : "OFF"}`, "success");
    } catch (e: any) {
      toast(e?.message || "Couldn't save.", "error");
    } finally { setSaving(null); }
  }, [data]);

  const flip = async (kind: string, next: boolean) => {
    if (!data) return;
    setSaving(kind);
    // Optimistic
    const prev = data.toggles[kind];
    setData({ ...data, toggles: { ...data.toggles, [kind]: next } });
    try {
      const r = await api<any>("/coach/auto-media-gen/settings", {
        method: "PATCH",
        body: { toggles: { [kind]: next } },
      });
      if (r?.ok && r?.toggles) {
        setData((d) => d ? { ...d, toggles: r.toggles } : d);
      }
      toast(`${data.labels[kind] || kind} → ${next ? "ON" : "OFF"}`, "success");
    } catch (e: any) {
      // Revert
      setData((d) => d ? { ...d, toggles: { ...d.toggles, [kind]: prev } } : d);
      toast(e?.message || "Couldn't save.", "error");
    } finally { setSaving(null); }
  };

  const bulk = async (value: boolean) => {
    if (!data) return;
    setSaving("__bulk__");
    const patch: Record<string, boolean> = {};
    for (const k of Object.keys(data.labels)) {
      if (!(data.env_kill_switches || {})[k]) patch[k] = value;
    }
    try {
      const r = await api<any>("/coach/auto-media-gen/settings", {
        method: "PATCH", body: { toggles: patch },
      });
      if (r?.toggles) setData((d) => d ? { ...d, toggles: r.toggles } : d);
      toast(value ? "All kinds ON" : "All kinds OFF", "success");
    } catch (e: any) {
      toast(e?.message || "Couldn't save.", "error");
    } finally { setSaving(null); }
  };

  const imageKinds = useMemo(() => {
    if (!data) return [] as string[];
    return IMAGE_KINDS.filter((k) => k in data.labels);
  }, [data]);
  const contentKinds = useMemo(() => {
    if (!data) return [] as string[];
    const known = Object.keys(data.labels);
    const inGroup = new Set([...IMAGE_KINDS, ...CONTENT_KINDS]);
    return [
      ...CONTENT_KINDS.filter((k) => known.includes(k)),
      ...known.filter((k) => !inGroup.has(k)),
    ];
  }, [data]);

  const totalOn = useMemo(() => {
    if (!data) return 0;
    return Object.values(data.toggles).filter(Boolean).length;
  }, [data]);

  const renderRow = (k: string) => {
    if (!data) return null;
    const label = data.labels[k] || k;
    const isOn = !!data.toggles[k];
    const envLocked = !!(data.env_kill_switches || {})[k];
    return (
      <View key={k} style={styles.row} testID={`toggle-${k}`}>
        <View style={{ flex: 1, marginRight: 12 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <Text style={styles.rowTitle}>{label}</Text>
            {envLocked && (
              <View style={styles.envBadge}>
                <Text style={styles.envBadgeT}>ENV LOCK</Text>
              </View>
            )}
          </View>
          {COST_HINT[k] ? <Text style={styles.rowDesc}>{COST_HINT[k]}</Text> : null}
        </View>
        {saving === k ? (
          <ActivityIndicator color={theme.color.brand} />
        ) : (
          <Switch
            value={isOn}
            onValueChange={(next) => flip(k, next)}
            disabled={envLocked}
            trackColor={{ true: theme.color.brand, false: "#3a3a3a" }}
            thumbColor="#fff"
          />
        )}
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={10}>
          <Ionicons name="chevron-back" size={24} color={theme.color.text} />
        </Pressable>
        <Text style={styles.headerTitle}>GENERATION CONTROL</Text>
        <View style={{ width: 24 }} />
      </View>

      {loading ? (
        <ActivityIndicator color={theme.color.brand} style={{ marginTop: 40 }} />
      ) : !data ? (
        <View style={styles.card}><Text style={styles.emptyT}>Could not load settings.</Text></View>
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: 16, paddingBottom: 60 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={theme.color.brand} />}
        >
          {/* Budget-paused banner — visible only when the LLM key ran out */}
          {genStatus?.budget_paused && (
            <View style={styles.budgetBanner} testID="budget-paused-banner">
              <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <Ionicons name="pause-circle" size={20} color="#ff6b6b" />
                <Text style={styles.budgetTitle}>GENERATION PAUSED · BUDGET EXCEEDED</Text>
              </View>
              <Text style={styles.budgetBody}>
                {genStatus.budget_paused_reason
                  ? String(genStatus.budget_paused_reason).slice(0, 220)
                  : "The Universal LLM Key is out of credits."}
              </Text>
              <Text style={styles.budgetHint}>
                {genStatus.budget_paused_by_kind ? `Tripped on ${genStatus.budget_paused_by_kind}` : ""}
                {"  ·  "}
                Top up via Profile → Manage plan → Universal Key → Add Balance, then hit Resume below.
              </Text>
              <View style={{ flexDirection: "row", gap: 8, marginTop: 10 }}>
                <Pressable
                  style={styles.resumeBtn}
                  onPress={resumeBudget}
                  disabled={resuming}
                  testID="resume-generation-btn"
                >
                  {resuming ? (
                    <ActivityIndicator color="#fff" />
                  ) : (
                    <Ionicons name="play" size={14} color="#fff" />
                  )}
                  <Text style={styles.resumeBtnT}>{resuming ? "RESUMING…" : "RESUME GENERATION"}</Text>
                </Pressable>
              </View>
            </View>
          )}

          <View style={styles.card}>
            <Text style={styles.sectionT}>SUMMARY</Text>
            <Text style={styles.sectionHint}>
              When any new exercise is added anywhere in the app, the enabled
              kinds below are queued in the background. Coach still has to
              approve — nothing is published automatically.
            </Text>
            <View style={styles.statRow}>
              <View style={styles.stat}>
                <Text style={styles.statN}>{totalOn}</Text>
                <Text style={styles.statL}>ON</Text>
              </View>
              <View style={styles.stat}>
                <Text style={styles.statN}>{Object.keys(data.labels).length - totalOn}</Text>
                <Text style={styles.statL}>OFF</Text>
              </View>
              <View style={styles.stat}>
                <Text style={styles.statN}>{Object.keys(data.env_kill_switches || {}).length}</Text>
                <Text style={styles.statL}>ENV LOCK</Text>
              </View>
              <View style={styles.stat}>
                <Text style={[styles.statN, { color: genStatus?.enabled === false ? "#ff6b6b" : "#4ade80" }]}>
                  {genStatus?.enabled === false ? "OFF" : "ON"}
                </Text>
                <Text style={styles.statL}>FEATURE</Text>
              </View>
            </View>
            <View style={{ flexDirection: "row", gap: 8, marginTop: 12 }}>
              <Pressable style={styles.bulkBtn} onPress={() => bulk(true)} disabled={saving === "__bulk__"}>
                <Text style={styles.bulkBtnT}>ALL ON</Text>
              </Pressable>
              <Pressable style={[styles.bulkBtn, styles.bulkBtnDark]} onPress={() => bulk(false)} disabled={saving === "__bulk__"}>
                <Text style={styles.bulkBtnT}>ALL OFF</Text>
              </Pressable>
              {saving === "__bulk__" && <ActivityIndicator color={theme.color.brand} />}
            </View>
          </View>

          <View style={styles.card}>
            <Text style={styles.sectionT}>IMAGE FRAMES</Text>
            <Text style={styles.sectionHint}>
              Which Nano-Banana frames get generated automatically. Coach
              can still manually generate any frame per-exercise from the
              library.
            </Text>
            {imageKinds.map((k) => renderRow(k))}
            {/* Bundle toggle — flips start + end together as "Multi-frame" */}
            {(imageKinds.includes("image_start") || imageKinds.includes("image_end")) && (() => {
              const multiOn = !!(data && data.toggles.image_start && data.toggles.image_end);
              const envLocked = !!(data && ((data.env_kill_switches || {}).image_start || (data.env_kill_switches || {}).image_end));
              return (
                <View style={styles.row} testID="toggle-multi_frame">
                  <View style={{ flex: 1, marginRight: 12 }}>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                      <Text style={styles.rowTitle}>Multi-frame Images (start + end)</Text>
                      {envLocked && (
                        <View style={styles.envBadge}>
                          <Text style={styles.envBadgeT}>ENV LOCK</Text>
                        </View>
                      )}
                    </View>
                    <Text style={styles.rowDesc}>
                      One-click bundle — flips both extra frames together. +2 Nano-Banana image gens per exercise.
                    </Text>
                  </View>
                  {saving === "__multi_frame__" ? (
                    <ActivityIndicator color={theme.color.brand} />
                  ) : (
                    <Switch
                      value={multiOn}
                      onValueChange={(next) => flipMultiFrame(next)}
                      disabled={envLocked}
                      trackColor={{ true: theme.color.brand, false: "#3a3a3a" }}
                      thumbColor="#fff"
                    />
                  )}
                </View>
              );
            })()}
          </View>

          <View style={styles.card}>
            <Text style={styles.sectionT}>WRITTEN CONTENT</Text>
            <Text style={styles.sectionHint}>
              Text fields drafted by Claude in Louis’s voice. Every field
              lands as a draft — coach approves before it reaches clients.
            </Text>
            {contentKinds.map((k) => renderRow(k))}
          </View>

          {Object.keys(data.env_kill_switches || {}).length > 0 && (
            <View style={styles.card}>
              <Text style={styles.sectionT}>ENV-LOCKED KINDS</Text>
              <Text style={styles.sectionHint}>
                These kinds are forced OFF by an environment variable
                (AUTO_MEDIA_GEN_&lt;KIND&gt;=false) and cannot be flipped
                from this panel. Update the env in your Emergent
                deployment settings to unlock.
              </Text>
              {Object.keys(data.env_kill_switches || {}).map((k) => (
                <Text key={k} style={styles.envLockedItem}>· {data.labels[k] || k}</Text>
              ))}
            </View>
          )}

          <Text style={styles.footNote}>
            All auto-generation goes to “Needs Review” — you still approve
            everything before it lands in a client workout.
          </Text>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    padding: 16, borderBottomWidth: 1, borderBottomColor: theme.color.divider,
  },
  headerTitle: { color: theme.color.text, fontSize: 14, letterSpacing: 2, fontWeight: "900" },

  card: {
    backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.md,
    borderWidth: 1, borderColor: theme.color.border,
    padding: 14, marginBottom: 12,
  },
  sectionT: { color: theme.color.brand, fontSize: 11, letterSpacing: 2, fontWeight: "900", marginBottom: 6 },
  sectionHint: { color: theme.color.textMuted, fontSize: 11, lineHeight: 16, marginBottom: 10 },

  statRow: { flexDirection: "row", gap: 12, marginTop: 6 },
  stat: { flex: 1, alignItems: "center", padding: 8, backgroundColor: theme.color.surface3, borderRadius: 8 },
  statN: { color: theme.color.text, fontSize: 20, fontWeight: "900" },
  statL: { color: theme.color.textMuted, fontSize: 9, letterSpacing: 1.2, fontWeight: "800", marginTop: 2 },

  row: {
    flexDirection: "row", alignItems: "center",
    paddingVertical: 12, borderTopWidth: 1, borderTopColor: theme.color.border,
  },
  rowTitle: { color: theme.color.text, fontSize: 13, fontWeight: "800", letterSpacing: 0.3 },
  rowDesc: { color: theme.color.textMuted, fontSize: 11, lineHeight: 15, marginTop: 3 },

  envBadge: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 3, backgroundColor: "#f5b54322", borderWidth: 1, borderColor: "#f5b543" },
  envBadgeT: { color: "#f5b543", fontSize: 8, fontWeight: "900", letterSpacing: 0.5 },

  bulkBtn: {
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: 8,
    backgroundColor: theme.color.brand,
  },
  bulkBtnDark: { backgroundColor: "#3a3a3a" },
  bulkBtnT: { color: "#fff", fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },

  envLockedItem: { color: theme.color.textDim, fontSize: 12, paddingVertical: 3 },

  emptyT: { color: theme.color.textMuted, fontSize: 12 },
  footNote: { color: theme.color.textDim, fontSize: 10, textAlign: "center", marginTop: 8, marginBottom: 30, lineHeight: 14 },

  // Budget-paused banner
  budgetBanner: {
    backgroundColor: "#3B0B12",
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "#7A1122",
    padding: 14,
    marginBottom: 12,
  },
  budgetTitle: { color: "#ff6b6b", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  budgetBody: { color: theme.color.text, fontSize: 12, lineHeight: 17 },
  budgetHint: { color: theme.color.textMuted, fontSize: 11, lineHeight: 15, marginTop: 6 },
  resumeBtn: {
    backgroundColor: "#065f46",
    paddingHorizontal: 14, paddingVertical: 8,
    borderRadius: 8,
    flexDirection: "row", alignItems: "center", gap: 6,
  },
  resumeBtnT: { color: "#fff", fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },
});
