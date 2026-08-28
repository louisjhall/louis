/**
 * On Demand · Video player screen.
 *
 * Full-screen expo-video player fed by the presigned R2 URL returned by
 * `GET /api/on-demand/items/{id}/media-url`. Refreshes the URL on
 * re-mount (URLs have a 30-min TTL so a stale one is only possible if
 * you leave the app open in the background for that long).
 *
 * Route: /on-demand/[id]/video
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { VideoView, useVideoPlayer } from "expo-video";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Item = {
  id: string;
  title: string;
  description?: string;
  duration_seconds?: number | null;
  content_type: string;
};

export default function OnDemandVideoScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [item, setItem] = useState<Item | null>(null);
  const [uri, setUri] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [itemRes, urlRes] = await Promise.all([
        api<{ item: Item }>(`/on-demand/items/${id}`),
        api<{ url: string }>(`/on-demand/items/${id}/media-url`),
      ]);
      setItem(itemRes.item);
      setUri(urlRes.url);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const player = useVideoPlayer(uri || null, (p) => { p.loop = false; });

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <View style={styles.topBar}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="od-video-close">
          <Ionicons name="close" size={26} color={theme.color.text} />
        </Pressable>
        <Text style={styles.eyebrow}>ON DEMAND · VIDEO</Text>
        <View style={{ width: 26 }} />
      </View>

      {loading ? (
        <View style={styles.centre}>
          <ActivityIndicator color={theme.color.brand} />
        </View>
      ) : error ? (
        <View style={styles.centre}>
          <Ionicons name="alert-circle-outline" size={36} color={theme.color.brand} />
          <Text style={styles.errorText}>{error}</Text>
        </View>
      ) : (
        <ScrollView contentContainerStyle={styles.body} showsVerticalScrollIndicator={false}>
          <View style={styles.playerBox}>
            {uri ? (
              <VideoView
                testID="od-video-player"
                player={player}
                style={styles.player}
                contentFit="contain"
                allowsFullscreen
                allowsPictureInPicture={false}
                nativeControls
              />
            ) : (
              <View style={styles.centre}>
                <Text style={styles.errorText}>Video not available.</Text>
              </View>
            )}
          </View>

          {item ? (
            <View style={styles.meta}>
              <Text style={styles.title}>{item.title}</Text>
              {item.description ? (
                <Text style={styles.description}>{item.description}</Text>
              ) : null}
            </View>
          ) : null}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  topBar: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    padding: 16,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: theme.color.border,
  },
  eyebrow: {
    color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2,
  },
  centre: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24, gap: 10 },
  errorText: { color: theme.color.text, fontSize: 13, textAlign: "center" },
  body: { padding: 16, paddingBottom: 40 },
  playerBox: {
    borderRadius: 14, backgroundColor: "#000", overflow: "hidden",
    borderWidth: 1, borderColor: theme.color.border,
    aspectRatio: 16 / 9, width: "100%",
    alignItems: "center", justifyContent: "center",
  },
  player: { width: "100%", height: "100%", backgroundColor: "#000" },
  meta: {
    marginTop: 16, padding: 16, borderRadius: 12,
    backgroundColor: theme.color.surface2,
    borderWidth: StyleSheet.hairlineWidth, borderColor: theme.color.border,
  },
  title: { color: theme.color.text, fontSize: 18, fontWeight: "800" },
  description: {
    color: theme.color.text, fontSize: 13, lineHeight: 20, marginTop: 8, opacity: 0.85,
  },
});
