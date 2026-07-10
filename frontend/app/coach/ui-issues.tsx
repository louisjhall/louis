import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, RefreshControl, ActivityIndicator, Alert } from "react-native";
import { Stack, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Issue = {
  id: string;
  screen: string;
  note: string;
  issue_type: string;
  priority: "low" | "medium" | "high";
  status: "open" | "resolved" | "ignored";
  reporter_email: string | null;
  viewed_as_email: string | null;
  is_preview: boolean;
  has_screenshot: boolean;
  ts: string;
};

export default function UIIssuesScreen() {
  const [issues, setIssues] = useState<Issue[]>([]);
  const [counts, setCounts] = useState<any>({});
  const [status, setStatus] = useState<"open" | "resolved" | "ignored" | "all">("open");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<{ issues: Issue[]; counts: any }>(`/admin/ui-issues?status_filter=${status}`);
      setIssues(r.issues);
      setCounts(r.counts);
    } catch (e: any) {
      Alert.alert("Load failed", e?.message || "Try again.");
    } finally { setLoading(false); }
  }, [status]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const setIssueStatus = async (id: string, s: "open" | "resolved" | "ignored") => {
    try {
      await api(`/admin/ui-issues/${id}`, { method: "PATCH", body: { status: s } });
      load();
    } catch (e: any) {
      Alert.alert("Update failed", e?.message || "Try again.");
    }
  };

  const priorityColor = (p: string) =>
    p === "high" ? theme.color.red : p === "medium" ? theme.color.amber : theme.color.textMuted;

  return (
    <SafeAreaView style={styles.wrap} edges={["top", "left", "right"]}>
      <Stack.Screen options={{ title: "UI Issues" }} />
      <ScrollView contentContainerStyle={{ padding: 16 }} refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}>
        <Text style={styles.h1}>UI ISSUES</Text>
        <Text style={styles.sub}>Reported from Coach Preview Mode.</Text>

        <View style={styles.filters}>
          {(["open", "resolved", "ignored", "all"] as const).map((f) => (
            <Pressable key={f} onPress={() => setStatus(f)} style={[styles.chip, status === f && styles.chipActive]} testID={`ui-issues-filter-${f}`}>
              <Text style={[styles.chipT, status === f && styles.chipTActive]}>
                {f.toUpperCase()} {f !== "all" ? `(${counts[f] || 0})` : ""}
              </Text>
            </Pressable>
          ))}
        </View>

        {loading ? (
          <ActivityIndicator color={theme.color.brand} style={{ marginTop: 40 }} />
        ) : issues.length === 0 ? (
          <Text style={styles.emptyT}>No {status} issues.</Text>
        ) : (
          issues.map((issue) => (
            <View key={issue.id} style={styles.card} testID={`ui-issue-${issue.id}`}>
              <View style={styles.rowTop}>
                <View style={[styles.priorityDot, { backgroundColor: priorityColor(issue.priority) }]} />
                <Text style={styles.screen} numberOfLines={1}>{issue.screen}</Text>
                <Text style={styles.date}>{new Date(issue.ts).toLocaleDateString()}</Text>
              </View>
              <Text style={styles.note}>{issue.note}</Text>
              <View style={styles.metaRow}>
                <Text style={styles.meta}>{issue.issue_type.toUpperCase()} · {issue.priority.toUpperCase()}</Text>
                {issue.is_preview ? (
                  <Text style={styles.meta}>viewed as {issue.viewed_as_email || "unknown"}</Text>
                ) : null}
                {issue.has_screenshot ? (
                  <Text style={styles.meta}>📷</Text>
                ) : null}
              </View>
              {issue.status === "open" ? (
                <View style={styles.actions}>
                  <Pressable onPress={() => setIssueStatus(issue.id, "resolved")} style={[styles.actBtn, styles.actResolve]} testID={`ui-issue-resolve-${issue.id}`}>
                    <Text style={styles.actT}>RESOLVE</Text>
                  </Pressable>
                  <Pressable onPress={() => setIssueStatus(issue.id, "ignored")} style={[styles.actBtn, styles.actIgnore]} testID={`ui-issue-ignore-${issue.id}`}>
                    <Text style={styles.actT}>IGNORE</Text>
                  </Pressable>
                </View>
              ) : (
                <Pressable onPress={() => setIssueStatus(issue.id, "open")} style={[styles.actBtn, styles.actReopen]} testID={`ui-issue-reopen-${issue.id}`}>
                  <Text style={styles.actT}>RE-OPEN</Text>
                </Pressable>
              )}
            </View>
          ))
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: theme.color.surface },
  h1: { color: theme.color.text, fontSize: 24, fontWeight: "800", letterSpacing: 1 },
  sub: { color: theme.color.textMuted, fontSize: 13, marginBottom: 16 },
  filters: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 16 },
  chip: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  chipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "800", letterSpacing: 0.6 },
  chipTActive: { color: "#fff" },
  emptyT: { color: theme.color.textDim, textAlign: "center", padding: 40 },
  card: { backgroundColor: theme.color.surface2, borderRadius: 10, padding: 14, marginBottom: 10, borderWidth: 1, borderColor: theme.color.border },
  rowTop: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 6 },
  priorityDot: { width: 8, height: 8, borderRadius: 4 },
  screen: { flex: 1, color: theme.color.text, fontSize: 12, fontWeight: "700" },
  date: { color: theme.color.textDim, fontSize: 11 },
  note: { color: theme.color.text, fontSize: 14, lineHeight: 20, marginBottom: 8 },
  metaRow: { flexDirection: "row", flexWrap: "wrap", gap: 12, marginBottom: 10 },
  meta: { color: theme.color.textMuted, fontSize: 11 },
  actions: { flexDirection: "row", gap: 8 },
  actBtn: { flex: 1, paddingVertical: 8, borderRadius: 6, alignItems: "center" },
  actResolve: { backgroundColor: theme.color.green },
  actIgnore: { backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border },
  actReopen: { backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border, alignSelf: "flex-start", paddingHorizontal: 16 },
  actT: { color: "#fff", fontSize: 11, fontWeight: "800", letterSpacing: 0.8 },
});
