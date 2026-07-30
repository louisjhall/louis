/**
 * Crew Base — client-facing community feed (Iter 129).
 *
 * Replaces the previous "Coming Soon" placeholder. Clients see published
 * posts only. Comments + a single aviation-themed "Wings" reaction are
 * available. Identity of other clients is resolved server-side according
 * to each user's crew_base_identity_mode preference.
 *
 * A gear icon in the header opens the client's Crew Base settings
 * (notification toggle + community identity mode).
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, ActivityIndicator, Pressable, RefreshControl } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { CrewBasePostCard, CrewBasePost } from "@/src/components/crew-base/CrewBasePostCard";

export default function BaseScreen() {
  const router = useRouter();
  const [posts, setPosts] = useState<CrewBasePost[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await api<{ posts: CrewBasePost[] }>("/crew-base/feed?limit=60");
      setPosts(res.posts || []);
      // Mark as seen (clears sidebar badge, does not affect push toggle)
      api("/crew-base/mark-seen", { method: "POST", body: {} }).catch(() => null);
    } catch (_e) {
      setPosts([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const onRefresh = () => { setRefreshing(true); load(); };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.headerBar}>
        <View>
          <Text style={styles.h1} testID="base-h1">Crew Base</Text>
          <Text style={styles.sub}>Community posts from Louis & the crew</Text>
        </View>
        <Pressable
          onPress={() => router.push("/(client)/crew-base-settings" as any)}
          hitSlop={12}
          testID="cb-settings-btn"
        >
          <Ionicons name="settings-outline" size={20} color={theme.color.textMuted} />
        </Pressable>
      </View>

      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.color.brand} />}
      >
        {loading ? (
          <View style={{ padding: 40, alignItems: "center" }}>
            <ActivityIndicator />
          </View>
        ) : posts.length === 0 ? (
          <View style={styles.empty} testID="cb-empty-state">
            <Ionicons name="megaphone-outline" size={40} color={theme.color.textDim} />
            <Text style={styles.emptyT}>The community feed is quiet right now.</Text>
            <Text style={styles.emptySub}>New posts from Louis and CrewFit will appear here.</Text>
          </View>
        ) : (
          posts.map((p) => (
            <CrewBasePostCard key={p.id} post={p} viewerIsCoach={false} onChanged={load} />
          ))
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.color.bg },
  headerBar: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: theme.space.lg, paddingVertical: theme.space.md,
    borderBottomWidth: 1, borderBottomColor: theme.color.divider,
  },
  h1: { color: theme.color.text, fontSize: 22, fontWeight: "900" },
  sub: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },
  scroll: { padding: theme.space.md, paddingBottom: 60 },
  empty: { padding: 40, alignItems: "center" },
  emptyT: { color: theme.color.textMuted, fontWeight: "800", marginTop: 12 },
  emptySub: { color: theme.color.textDim, fontSize: 12, marginTop: 4, textAlign: "center" },
});
