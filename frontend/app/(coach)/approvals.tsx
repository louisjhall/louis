/**
 * Approvals — items that need an explicit coach decision.
 *
 * Iter 128d — retired V1 workout-approval union. All approval work now
 * flows through Engine V2:
 *   - Drafts ready for review     → programme_ready
 *   - Blocking exceptions         → conflict
 *   - Change-sets awaiting review → needs_review
 * Sources: /v2/coach/dashboard/attention (already the source of truth
 * for the Home attention queue). We filter that stream to only the
 * kinds that represent an actual review-gate.
 */
import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, RefreshControl, ActivityIndicator } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type AttentionRow = {
  client_id: string;
  client_name: string;
  kind: string;
  severity: "info" | "warning" | "blocker";
  reason: string;
};

// Approval-gate kinds only. Everything else (missed sessions, roster changes,
// check-in noise) stays on Home under "Needs your attention".
const APPROVAL_KINDS = new Set([
  "programme_ready",
  "conflict",
  "needs_review",
  "generation_failure",
]);

const KIND_LABELS: Record<string, string> = {
  programme_ready: "Programme ready for approval",
  conflict: "Blocking exception",
  needs_review: "Needs review",
  generation_failure: "Generation failure — coach intervention",
};

const SEVERITY_TINT: Record<string, string> = {
  blocker: "#ff5555",
  warning: "#f5b543",
  info: "#5aa9e6",
};

export default function Approvals() {
  const router = useRouter();
  const [items, setItems] = useState<AttentionRow[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<{ attention: AttentionRow[] }>("/v2/coach/dashboard/attention")
        .catch(() => ({ attention: [] }));
      const filtered = (r.attention || []).filter((it) => APPROVAL_KINDS.has(it.kind));
      setItems(filtered);
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Text style={styles.title}>APPROVALS</Text>
        <Text style={styles.sub}>Items that need an explicit coach decision.</Text>
        <Text style={styles.count}>{items.length} awaiting your review</Text>
      </View>
      <ScrollView
        contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 60 }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}
      >
        {loading && items.length === 0 ? (
          <ActivityIndicator color={theme.color.brand} />
        ) : items.length === 0 ? (
          <View style={styles.emptyBox}>
            <Ionicons name="checkmark-done-circle" size={40} color={theme.color.textDim} />
            <Text style={styles.emptyTitle}>Nothing to approve</Text>
            <Text style={styles.emptyBody}>Every current plan is either Live or in the client&apos;s hands.</Text>
          </View>
        ) : items.map((it, i) => (
          <Pressable
            key={`${it.client_id}-${it.kind}-${i}`}
            testID={`approval-${it.client_id}-${i}`}
            onPress={() => router.push(`/coach/client/${it.client_id}/workspace` as any)}
            style={styles.card}
          >
            <View style={[styles.loadBar, { backgroundColor: SEVERITY_TINT[it.severity] || "#999" }]} />
            <View style={{ flex: 1, padding: theme.space.md }}>
              <Text style={styles.client}>{it.client_name}</Text>
              <Text style={styles.title2}>{KIND_LABELS[it.kind] || it.kind}</Text>
              <Text style={styles.meta}>{it.reason}</Text>
            </View>
            <Text style={styles.review}>REVIEW →</Text>
          </Pressable>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  title: { color: theme.color.text, fontSize: 16, letterSpacing: 2, fontWeight: "900" },
  sub: { color: theme.color.brand, marginTop: 4, fontSize: 10, fontWeight: "800", letterSpacing: 1.5 },
  count: { color: theme.color.textMuted, marginTop: 4, fontSize: 12 },
  card: { flexDirection: "row", alignItems: "center", backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, marginBottom: theme.space.sm, overflow: "hidden" },
  loadBar: { width: 4, alignSelf: "stretch" },
  client: { color: theme.color.brand, fontSize: 11, letterSpacing: 1.5, fontWeight: "800" },
  title2: { color: theme.color.text, fontSize: 15, fontWeight: "700", marginTop: 2 },
  meta: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  review: { color: theme.color.brand, letterSpacing: 2, fontWeight: "800", fontSize: 11, marginRight: theme.space.md },
  emptyBox: { alignItems: "center", padding: theme.space.xxl, gap: theme.space.sm },
  emptyTitle: { color: theme.color.text, fontSize: 15, fontWeight: "700", marginTop: theme.space.sm },
  emptyBody: { color: theme.color.textDim, fontSize: 12, textAlign: "center" },
});
