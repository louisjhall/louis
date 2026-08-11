/**
 * /coach/admin/live-controls — Iter 94v (Phase 4)
 *
 * Server-driven Live App Controls console for Louis.
 *
 * Louis can toggle feature flags on/off without a new app build, and see the
 * audit trail of who changed what. Content-key items (support numbers, beta
 * banner copy) are editable inline. Everything is guarded server-side by
 * the coach role check in feature_app_config.py.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, Switch, TextInput,
  ActivityIndicator, RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast } from "@/src/lib/ux";

type ConfigItem = {
  id: string;
  key: string;
  value: any;
  kind: string;              // "flag" | "content" | "threshold"
  enabled: boolean;
  safe_to_change_live: boolean;
  description?: string;
  updated_by_name?: string;
  updated_at?: string;
};

type AuditEntry = {
  id: string;
  key: string;
  action: string;
  actor_name?: string;
  created_at?: string;
  new_value?: any;
  previous?: { value?: any } | null;
};

export default function LiveControls() {
  const router = useRouter();
  const [items, setItems] = useState<ConfigItem[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [showAudit, setShowAudit] = useState(false);
  const [contentDraft, setContentDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [cfg, aud] = await Promise.all([
        api<{ items: ConfigItem[] }>("/admin/app-config"),
        api<{ audit: AuditEntry[] }>("/admin/app-config/audit"),
      ]);
      setItems(cfg?.items || []);
      setAudit(aud?.audit || []);
      const draft: Record<string, string> = {};
      for (const c of (cfg?.items || [])) {
        if (c.kind === "content" && typeof c.value === "string") {
          draft[c.key] = c.value;
        }
      }
      setContentDraft(draft);
    } catch (e: any) {
      toast(e?.message || "Couldn't load Live Controls.", "error");
    } finally { setLoading(false); setRefreshing(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const toggleFlag = async (item: ConfigItem, next: boolean) => {
    setSaving(item.key);
    // Optimistic
    setItems((prev) => prev.map((x) => x.key === item.key ? { ...x, value: next } : x));
    try {
      await api("/admin/app-config", {
        method: "POST",
        body: {
          key: item.key,
          value: next,
          kind: "flag",
          enabled: true,
          safe_to_change_live: true,
          description: item.description,
        },
      });
      toast(`${item.key} → ${next ? "ON" : "OFF"}`, "success");
      load();
    } catch (e: any) {
      // Revert on failure
      setItems((prev) => prev.map((x) => x.key === item.key ? { ...x, value: !next } : x));
      toast(e?.message || "Couldn't save.", "error");
    } finally { setSaving(null); }
  };

  const saveContent = async (key: string) => {
    const val = (contentDraft[key] || "").trim();
    setSaving(key);
    try {
      await api("/admin/app-config", {
        method: "POST",
        body: { key, value: val, kind: "content", enabled: true, safe_to_change_live: true },
      });
      toast(`Updated ${key}`, "success");
      load();
    } catch (e: any) {
      toast(e?.message || "Couldn't save.", "error");
    } finally { setSaving(null); }
  };

  const flags = items.filter((x) => x.kind === "flag");
  const contents = items.filter((x) => x.kind === "content");

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={10}><Ionicons name="chevron-back" size={24} color={theme.color.text} /></Pressable>
        <Text style={styles.headerTitle}>LIVE APP CONTROLS</Text>
        <Pressable onPress={() => setShowAudit((v) => !v)} hitSlop={10}>
          <Ionicons name="time" size={22} color={theme.color.brand} />
        </Pressable>
      </View>

      {loading ? (
        <ActivityIndicator color={theme.color.brand} style={{ marginTop: 40 }} />
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: 16, paddingBottom: 60 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={theme.color.brand} />}
        >
          {showAudit ? (
            <View style={styles.card}>
              <Text style={styles.sectionT}>AUDIT LOG · LAST 20</Text>
              {audit.length === 0 ? (
                <Text style={styles.emptyT}>No changes recorded yet.</Text>
              ) : audit.slice(0, 20).map((a) => (
                <View key={a.id} style={styles.auditRow}>
                  <Text style={styles.auditKey}>{a.key}</Text>
                  <Text style={styles.auditMeta}>
                    {a.action} · {a.actor_name || "system"}{a.created_at ? ` · ${a.created_at.slice(0, 16).replace("T", " ")}` : ""}
                  </Text>
                  <Text style={styles.auditVal}>
                    {String(a.previous?.value ?? "—")} → {String(a.new_value ?? "—")}
                  </Text>
                </View>
              ))}
            </View>
          ) : null}

          <View style={styles.card}>
            <Text style={styles.sectionT}>FEATURE FLAGS</Text>
            <Text style={styles.sectionHint}>
              Toggle features on/off without an app build. Changes take effect on the next client refresh.
            </Text>
            {flags.map((f) => (
              <View key={f.key} style={styles.row} testID={`flag-${f.key}`}>
                <View style={{ flex: 1, marginRight: 12 }}>
                  <Text style={styles.rowTitle}>{f.key}</Text>
                  {f.description ? <Text style={styles.rowDesc} numberOfLines={2}>{f.description}</Text> : null}
                  {f.updated_by_name ? (
                    <Text style={styles.rowMeta}>Last: {f.updated_by_name}{f.updated_at ? ` · ${f.updated_at.slice(0, 16).replace("T", " ")}` : ""}</Text>
                  ) : null}
                </View>
                {saving === f.key ? (
                  <ActivityIndicator color={theme.color.brand} />
                ) : (
                  <Switch
                    value={!!f.value}
                    onValueChange={(next) => toggleFlag(f, next)}
                    trackColor={{ true: theme.color.brand, false: theme.color.border }}
                    thumbColor="#fff"
                  />
                )}
              </View>
            ))}
          </View>

          <View style={styles.card}>
            <Text style={styles.sectionT}>EDITABLE CONTENT</Text>
            <Text style={styles.sectionHint}>
              Copy that can be updated live (support numbers, banners). All items are on the safe allowlist.
            </Text>
            {contents.length === 0 ? (
              <Text style={styles.emptyT}>No content items yet. Use POST /admin/app-config with kind={"\"content\""} to add.</Text>
            ) : contents.map((c) => (
              <View key={c.key} style={styles.contentBlock}>
                <Text style={styles.rowTitle}>{c.key}</Text>
                <TextInput
                  value={contentDraft[c.key] ?? ""}
                  onChangeText={(t) => setContentDraft((d) => ({ ...d, [c.key]: t }))}
                  multiline
                  style={styles.textArea}
                  placeholderTextColor={theme.color.textDim}
                  testID={`content-${c.key}`}
                />
                <Pressable
                  onPress={() => saveContent(c.key)}
                  disabled={saving === c.key}
                  style={styles.saveBtn}
                  testID={`save-${c.key}`}
                >
                  {saving === c.key ? (
                    <ActivityIndicator color="#fff" />
                  ) : (
                    <Text style={styles.saveBtnT}>SAVE</Text>
                  )}
                </Pressable>
              </View>
            ))}
          </View>

          <Text style={styles.footNote}>
            Live-editable only — no code, permissions, or native functionality can be changed from here. Any change is logged.
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

  row: {
    flexDirection: "row", alignItems: "center",
    paddingVertical: 10, borderTopWidth: 1, borderTopColor: theme.color.border,
  },
  rowTitle: { color: theme.color.text, fontSize: 12, fontWeight: "900", letterSpacing: 0.6 },
  rowDesc: { color: theme.color.textMuted, fontSize: 11, lineHeight: 15, marginTop: 3 },
  rowMeta: { color: theme.color.textDim, fontSize: 11, marginTop: 3 },

  contentBlock: {
    paddingVertical: 10, borderTopWidth: 1, borderTopColor: theme.color.border,
  },
  textArea: {
    color: theme.color.text, backgroundColor: theme.color.surface3, borderRadius: 8,
    padding: 10, marginTop: 8, minHeight: 60, borderWidth: 1, borderColor: theme.color.border,
  },
  saveBtn: {
    alignSelf: "flex-end", marginTop: 8,
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: 8, backgroundColor: theme.color.brand,
  },
  saveBtnT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },

  emptyT: { color: theme.color.textMuted, fontSize: 12 },
  footNote: { color: theme.color.textDim, fontSize: 11, textAlign: "center", marginTop: 8, marginBottom: 30, lineHeight: 14 },

  auditRow: { paddingVertical: 8, borderTopWidth: 1, borderTopColor: theme.color.border },
  auditKey: { color: theme.color.text, fontSize: 12, fontWeight: "900" },
  auditMeta: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },
  auditVal: { color: theme.color.textDim, fontSize: 11, marginTop: 3, fontStyle: "italic" },
});
