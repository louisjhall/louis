/**
 * Social Studio — admin-only route. Shows today's daily post at the top,
 * list of drafts + scheduled + posted below, and the regenerate/approve/schedule flow.
 */
import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, TextInput, Alert, RefreshControl } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { useAuth } from "@/src/lib/auth";

type Post = {
  id: string; title: string; platform?: string; post_type?: string; content_pillar?: string;
  hook?: string; script?: string; caption?: string; hashtags?: string[]; cta?: string;
  status: string; scheduled_local_datetime?: string;
};

const TONE_ACTIONS: { key: string; label: string }[] = [
  { key: "shorter", label: "SHORTER" },
  { key: "punchier", label: "PUNCHIER" },
  { key: "professional", label: "PROFESSIONAL" },
  { key: "direct", label: "MORE DIRECT" },
  { key: "linkedin", label: "MORE LINKEDIN" },
  { key: "tiktok", label: "MORE TIKTOK" },
  { key: "aviation", label: "AVIATION EXAMPLES" },
  { key: "cta", label: "ADD CTA" },
  { key: "regen_hook", label: "REGEN HOOK" },
  { key: "regen_caption", label: "REGEN CAPTION" },
];

export default function SocialStudio() {
  const { user } = useAuth();
  const router = useRouter();
  const [posts, setPosts] = useState<Post[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [selected, setSelected] = useState<Post | null>(null);
  const [schedDate, setSchedDate] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<{ posts: Post[] }>("/social/posts");
      setPosts(r.posts || []);
    } catch (e: any) {
      // if 403 → not admin
      if (e?.status === 403) Alert.alert("Admin only", "This section is admin-only.");
    } finally { setLoading(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  // Access guard
  if (user && user.role !== "admin" && user.role !== "coach") {
    return (
      <SafeAreaView style={styles.root} edges={["top"]}>
        <View style={styles.emptyBox}>
          <Ionicons name="lock-closed" size={30} color={theme.color.textMuted} />
          <Text style={styles.emptyT}>Admin only</Text>
        </View>
      </SafeAreaView>
    );
  }

  const generateDaily = async () => {
    setBusy("daily");
    try {
      await api("/social/daily/generate", { method: "POST", body: {} });
      await load();
    } catch (e: any) { Alert.alert("Couldn't generate", e?.message || "Try again"); }
    finally { setBusy(null); }
  };

  const regen = async (id: string, action: string) => {
    setBusy(action);
    try {
      const r = await api<{ post: Post }>(`/social/posts/${id}/regenerate`, { method: "POST", body: { action } });
      setSelected(r.post);
      await load();
    } catch (e: any) { Alert.alert("Regenerate failed", e?.message || "Try again"); }
    finally { setBusy(null); }
  };

  const approve = async (id: string) => {
    setBusy("approve");
    try {
      await api(`/social/posts/${id}/approve`, { method: "POST" });
      await load();
      setSelected((s) => s && s.id === id ? { ...s, status: "Approved" } : s);
    } catch (e: any) { Alert.alert("Approve failed", e?.message || "Try again"); }
    finally { setBusy(null); }
  };

  const schedule = async (id: string) => {
    if (!schedDate || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(schedDate)) {
      Alert.alert("Use YYYY-MM-DDTHH:MM", "Example: 2026-07-15T09:00");
      return;
    }
    setBusy("schedule");
    try {
      await api(`/social/posts/${id}/schedule`, { method: "POST", body: {
        scheduled_local_datetime: schedDate,
        scheduled_time_zone: "Europe/London",
      }});
      await load();
      setSelected(null);
      setSchedDate("");
    } catch (e: any) { Alert.alert("Schedule failed", e?.message || "Try again"); }
    finally { setBusy(null); }
  };

  const dismiss = async (id: string) => {
    setBusy("dismiss");
    try {
      await api(`/social/posts/${id}/dismiss`, { method: "POST" });
      await load();
      setSelected(null);
    } catch (e: any) { Alert.alert("Dismiss failed", e?.message || "Try again"); }
    finally { setBusy(null); }
  };

  const copyText = async (t: string, label: string) => {
    try {
      // React Native web has navigator.clipboard; RN needs @react-native-clipboard/clipboard but not installed here.
      // Best-effort: prompt Alert with the text for now.
      Alert.alert(label, t);
    } catch { /* ignore */ }
  };

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={8}>
          <Ionicons name="chevron-back" size={26} color={theme.color.text} />
        </Pressable>
        <Text style={styles.headerT}>SOCIAL STUDIO</Text>
        <Pressable onPress={generateDaily} disabled={!!busy} hitSlop={8}>
          {busy === "daily" ? <ActivityIndicator color={theme.color.brand} /> : <Ionicons name="sparkles" size={20} color={theme.color.brand} />}
        </Pressable>
      </View>

      {selected ? (
        <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 100 }}>
          <Pressable onPress={() => setSelected(null)} style={styles.backChip}>
            <Ionicons name="arrow-back" size={14} color={theme.color.brand} />
            <Text style={styles.backChipT}>ALL POSTS</Text>
          </Pressable>
          <PostDetail post={selected} />

          <Text style={styles.sect}>REGENERATE</Text>
          <View style={styles.toneWrap}>
            {TONE_ACTIONS.map((a) => (
              <Pressable key={a.key} testID={`tone-${a.key}`} onPress={() => regen(selected.id, a.key)} disabled={!!busy} style={[styles.toneBtn, busy === a.key && { opacity: 0.5 }]}>
                <Text style={styles.toneT}>{a.label}</Text>
              </Pressable>
            ))}
          </View>

          <Text style={styles.sect}>ACTIONS</Text>
          <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
            {selected.status !== "Approved" ? (
              <Pressable testID="btn-approve" onPress={() => approve(selected.id)} disabled={!!busy} style={styles.actBtn}>
                <Text style={styles.actT}>APPROVE</Text>
              </Pressable>
            ) : null}
            {selected.caption ? (
              <Pressable onPress={() => copyText(selected.caption || "", "Caption")} style={styles.altBtn}>
                <Text style={styles.altT}>COPY CAPTION</Text>
              </Pressable>
            ) : null}
            {(selected.hashtags || []).length > 0 ? (
              <Pressable onPress={() => copyText((selected.hashtags || []).join(" "), "Hashtags")} style={styles.altBtn}>
                <Text style={styles.altT}>COPY HASHTAGS</Text>
              </Pressable>
            ) : null}
            <Pressable testID="btn-dismiss" onPress={() => dismiss(selected.id)} disabled={!!busy} style={styles.altBtn}>
              <Text style={styles.altT}>DISMISS</Text>
            </Pressable>
          </View>

          <Text style={styles.sect}>SCHEDULE</Text>
          <TextInput
            testID="sched-input"
            value={schedDate}
            onChangeText={setSchedDate}
            placeholder="YYYY-MM-DDTHH:MM"
            placeholderTextColor={theme.color.textDim}
            style={styles.input}
          />
          <Pressable testID="btn-schedule" onPress={() => schedule(selected.id)} disabled={!!busy || selected.status !== "Approved"} style={[styles.actBtn, { marginTop: 8, opacity: selected.status !== "Approved" ? 0.4 : 1 }]}>
            <Text style={styles.actT}>SCHEDULE (MANUAL)</Text>
          </Pressable>
          {selected.status !== "Approved" ? <Text style={styles.hint}>Approve first, then schedule.</Text> : null}
        </ScrollView>
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: 16, paddingBottom: 40 }}
          refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}
        >
          <Pressable testID="generate-daily" onPress={generateDaily} disabled={!!busy} style={styles.dailyCta}>
            <Ionicons name="sparkles" size={16} color="#fff" />
            <Text style={styles.dailyCtaT}>GENERATE TODAY&apos;S POST</Text>
          </Pressable>

          {loading && posts.length === 0 ? (
            <ActivityIndicator color={theme.color.brand} style={{ marginTop: 40 }} />
          ) : posts.length === 0 ? (
            <View style={styles.emptyBox}>
              <Ionicons name="megaphone-outline" size={30} color={theme.color.textDim} />
              <Text style={styles.emptyT}>No posts yet. Tap ✨ to generate today&apos;s.</Text>
            </View>
          ) : (
            posts.map((p) => (
              <Pressable key={p.id} testID={`post-${p.id}`} onPress={() => setSelected(p)} style={styles.postCard}>
                <View style={{ flex: 1 }}>
                  <View style={styles.rowTop}>
                    <Text style={styles.platformTag}>{(p.platform || "?").toUpperCase()}</Text>
                    <Text style={styles.postType}>· {p.post_type}</Text>
                    <View style={{ flex: 1 }} />
                    <View style={[styles.statusPill, statusColor(p.status)]}>
                      <Text style={styles.statusPillT}>{p.status.toUpperCase()}</Text>
                    </View>
                  </View>
                  <Text style={styles.postHook} numberOfLines={2}>{p.hook || p.title}</Text>
                  {p.content_pillar ? <Text style={styles.postPillar}>{p.content_pillar}</Text> : null}
                </View>
              </Pressable>
            ))
          )}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

function PostDetail({ post }: { post: Post }) {
  return (
    <View>
      <View style={styles.postHeader}>
        <Text style={styles.platformTag}>{(post.platform || "?").toUpperCase()} · {post.post_type}</Text>
        <View style={[styles.statusPill, statusColor(post.status)]}>
          <Text style={styles.statusPillT}>{post.status.toUpperCase()}</Text>
        </View>
      </View>
      <Text style={styles.detailTitle}>{post.title}</Text>
      {post.content_pillar ? <Text style={styles.postPillar}>{post.content_pillar}</Text> : null}

      <Text style={styles.sect}>HOOK</Text>
      <Text style={styles.detailBody}>{post.hook}</Text>

      {post.script ? (<><Text style={styles.sect}>SCRIPT</Text><Text style={styles.detailBody}>{post.script}</Text></>) : null}
      {post.caption ? (<><Text style={styles.sect}>CAPTION</Text><Text style={styles.detailBody}>{post.caption}</Text></>) : null}
      {(post.hashtags || []).length > 0 ? (
        <><Text style={styles.sect}>HASHTAGS</Text>
        <Text style={styles.detailBody}>{(post.hashtags || []).join(" ")}</Text></>
      ) : null}
      {post.cta ? (<><Text style={styles.sect}>CTA</Text><Text style={styles.detailBody}>{post.cta}</Text></>) : null}
    </View>
  );
}

function statusColor(status: string): any {
  if (status === "Posted") return { backgroundColor: theme.color.green };
  if (status === "Approved") return { backgroundColor: theme.color.brand };
  if (status === "Scheduled") return { backgroundColor: theme.color.brand };
  if (status === "Dismissed" || status === "Archived") return { backgroundColor: theme.color.textDim };
  if (status === "Failed") return { backgroundColor: "#c94a4a" };
  return { backgroundColor: theme.color.amber };
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", padding: 16, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  headerT: { color: theme.color.text, fontSize: 14, letterSpacing: 2, fontWeight: "900" },
  dailyCta: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingVertical: 14, borderRadius: 10, backgroundColor: theme.color.brand, marginBottom: 14 },
  dailyCtaT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 1.5 },
  emptyBox: { alignItems: "center", padding: 40, gap: 10 },
  emptyT: { color: theme.color.textMuted, fontSize: 12 },
  postCard: { flexDirection: "row", gap: 10, padding: 12, marginBottom: 8, borderRadius: 10, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  rowTop: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 4 },
  platformTag: { color: theme.color.brand, fontSize: 9, fontWeight: "900", letterSpacing: 1.5 },
  postType: { color: theme.color.textDim, fontSize: 9, fontWeight: "800", letterSpacing: 1 },
  statusPill: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 3 },
  statusPillT: { color: "#fff", fontSize: 8, fontWeight: "900", letterSpacing: 1 },
  postHook: { color: theme.color.text, fontSize: 13, fontWeight: "700", marginTop: 2 },
  postPillar: { color: theme.color.textMuted, fontSize: 10, marginTop: 4, letterSpacing: 0.5 },
  backChip: { flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start", paddingHorizontal: 10, paddingVertical: 6, borderRadius: 4, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand, marginBottom: 12 },
  backChipT: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },
  postHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  detailTitle: { color: theme.color.text, fontSize: 20, fontWeight: "900", marginTop: 6 },
  detailBody: { color: theme.color.text, fontSize: 13, marginTop: 6, lineHeight: 18 },
  sect: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 2, marginTop: 16, marginBottom: 4 },
  toneWrap: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  toneBtn: { paddingHorizontal: 10, paddingVertical: 8, borderRadius: 6, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.brand },
  toneT: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },
  actBtn: { paddingHorizontal: 14, paddingVertical: 12, borderRadius: 10, backgroundColor: theme.color.brand },
  actT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  altBtn: { paddingHorizontal: 14, paddingVertical: 12, borderRadius: 10, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  altT: { color: theme.color.text, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  input: { padding: 12, borderRadius: 8, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, color: theme.color.text, fontSize: 14 },
  hint: { color: theme.color.textMuted, fontSize: 11, marginTop: 6, fontStyle: "italic" },
});
