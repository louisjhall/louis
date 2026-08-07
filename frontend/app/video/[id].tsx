/**
 * Client video screen — plays a coach-recorded video (weekly review OR the
 * one-shot welcome intro) and shows the script transcript beneath.
 *
 * Iter 155 — replaced the text placeholder with a functional `expo-video`
 * player. Falls back to a friendly "message-only" panel when the record
 * has no `file_url` (edge case: coach sent text without recording).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { VideoView, useVideoPlayer } from "expo-video";
import { api, API_BASE } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

export default function ClientVideo() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [video, setVideo] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      // Try the standard list first; if the video is the welcome kind and
      // not yet listed via /videos/for-me (some deployments filter kind),
      // fall back to /videos/welcome-for-me — same shape, single row.
      const r = await api<any>("/videos/for-me");
      let v = (r?.videos || []).find((x: any) => x.id === id);
      if (!v) {
        try {
          const w = await api<any>("/videos/welcome-for-me");
          if (w?.video?.id === id) v = w.video;
        } catch { /* silent — welcome endpoint may be absent on older backends */ }
      }
      setVideo(v || null);
      if (v && !v.watched_at) {
        api<any>(`/videos/${id}/watched`, { method: "POST", body: {} }).catch(() => {});
      }
    } catch { /* ignore */ } finally { setLoading(false); }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  // Resolve the relative `file_url` (`/api/coach/videos/{id}/file`) against
  // the API_BASE so expo-video can fetch it from the pod / R2 endpoint.
  const playerUri = useMemo(() => {
    const raw = video?.file_url;
    if (!raw) return null;
    if (/^https?:/i.test(raw)) return raw;
    // API_BASE ends with `/api`, and raw starts with `/api/…` — strip one.
    const base = String(API_BASE || "").replace(/\/api\/?$/, "");
    return `${base}${raw.startsWith("/") ? "" : "/"}${raw}`;
  }, [video?.file_url]);

  const player = useVideoPlayer(playerUri || null, (p) => {
    p.loop = false;
  });

  if (loading) {
    return (
      <SafeAreaView style={styles.root}>
        <View style={styles.centre}><ActivityIndicator color={theme.color.brand} /></View>
      </SafeAreaView>
    );
  }
  if (!video) {
    return (
      <SafeAreaView style={styles.root}>
        <View style={styles.centre}>
          <Text style={{ color: theme.color.textMuted }}>Video not found.</Text>
        </View>
      </SafeAreaView>
    );
  }

  const isWelcome = video.video_kind === "welcome";
  const header = isWelcome ? "WELCOME FROM YOUR COACH" : "VIDEO FROM LOUIS";
  const scriptEyebrow = isWelcome ? "WHAT LOUIS WANTED TO SAY" : "YOUR WEEKLY REVIEW";

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <View style={styles.topBar}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="video-close">
          <Ionicons name="close" size={26} color={theme.color.text} />
        </Pressable>
        <Text style={styles.header}>{header}</Text>
        <View style={{ width: 26 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: 20 }}>
        <View style={styles.playerBox}>
          {playerUri ? (
            <VideoView
              testID="video-player"
              player={player}
              style={styles.player}
              contentFit="contain"
              allowsFullscreen
              allowsPictureInPicture={false}
              nativeControls
            />
          ) : (
            <View style={styles.msgOnly}>
              <Ionicons name="chatbubbles" size={44} color={theme.color.brand} />
              <Text style={styles.eyebrow}>WRITTEN COACHING REVIEW</Text>
              <Text style={styles.hint}>
                Louis sent your review as a written message this week — no video attached.
              </Text>
            </View>
          )}
        </View>

        {!!video.script && (
          <View style={styles.scriptCard}>
            <Text style={styles.scriptEyebrow}>{scriptEyebrow}</Text>
            <Text style={styles.scriptBody}>{video.script}</Text>
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.bg },
  centre: { flex: 1, alignItems: "center", justifyContent: "center" },
  topBar: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    padding: 16, borderBottomWidth: 1, borderBottomColor: theme.color.divider,
  },
  header: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  playerBox: {
    borderRadius: 14, backgroundColor: "#000",
    borderWidth: 1, borderColor: theme.color.border, overflow: "hidden",
    aspectRatio: 9 / 16,
    maxHeight: 500,
    alignItems: "center", justifyContent: "center",
  },
  player: { width: "100%", height: "100%", backgroundColor: "#000" },
  msgOnly: {
    flex: 1, alignItems: "center", justifyContent: "center", padding: 30,
    backgroundColor: theme.color.surface2,
  },
  eyebrow: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 2, marginTop: 12 },
  hint: { color: theme.color.textMuted, fontSize: 12, textAlign: "center", marginTop: 10, lineHeight: 17, fontStyle: "italic" },
  scriptCard: {
    marginTop: 16, padding: 16, borderRadius: 12,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
  },
  scriptEyebrow: { color: theme.color.brand, fontSize: 9, fontWeight: "900", letterSpacing: 2 },
  scriptBody: { color: theme.color.text, fontSize: 14, lineHeight: 22, marginTop: 10 },
});
