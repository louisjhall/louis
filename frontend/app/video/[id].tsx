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
      // Iter 165 · Robust three-tier fetch — the video row can transition
      // from `sent → viewed` while this screen is loading (banner tap
      // fires the mark-viewed flip in the background). Each list-based
      // endpoint filters by status; the new `/videos/{id}` direct lookup
      // does not, so it always returns the video the user is trying to
      // watch regardless of transient status changes.
      let v: any = null;
      try {
        const r = await api<any>("/videos/for-me");
        v = (r?.videos || []).find((x: any) => x.id === id);
      } catch { /* fall through to welcome */ }
      if (!v) {
        try {
          const w = await api<any>("/videos/welcome-for-me");
          if (w?.video?.id === id) v = w.video;
        } catch { /* fall through to direct */ }
      }
      if (!v) {
        try {
          const d = await api<any>(`/videos/${id}`);
          v = d?.video || null;
        } catch { /* endpoint absent on older backends — fall through */ }
      }
      setVideo(v || null);
      if (v && !v.watched_at) {
        // Only stamp `watched_at` once the player is loaded. The server's
        // 24h grace period keeps the banner alive after this so the client
        // can still find the video if they close it accidentally.
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

      <ScrollView
        contentContainerStyle={styles.scrollBody}
        showsVerticalScrollIndicator={false}
      >
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

        {/* Iter186+ · All videos (welcome + weekly) now render a 3-5
            bullet summary in place of the raw transcript. Falls back
            to a "Summary generating…" placeholder + truncated script
            during the ~10 s LLM window between coach send and
            background summary completion. */}
        {(Array.isArray(video.script_summary) && video.script_summary.length > 0) ? (
          <View style={styles.scriptCard}>
            <Text style={styles.scriptEyebrow}>{scriptEyebrow}</Text>
            <View style={styles.bulletList} testID="video-summary-bullets">
              {video.script_summary.map((b: string, i: number) => (
                <View key={i} style={styles.bulletRow}>
                  <View style={styles.bulletDot} />
                  <Text style={styles.bulletT}>{b}</Text>
                </View>
              ))}
            </View>
          </View>
        ) : video.script ? (
          <View style={styles.scriptCard}>
            <Text style={styles.scriptEyebrow}>{scriptEyebrow}</Text>
            <View style={styles.bulletList} testID="video-summary-pending">
              <View style={styles.bulletRow}>
                <ActivityIndicator size="small" color={theme.color.brand} />
                <Text style={[styles.bulletT, { fontStyle: "italic" }]}>
                  Summary generating… tap back in a moment for the highlights.
                </Text>
              </View>
            </View>
            <Text style={styles.scriptFallback} numberOfLines={4}>
              {video.script}
            </Text>
          </View>
        ) : null}

        {/* Iter186 · Message Your Coach CTA — shown for BOTH welcome and
            weekly videos so clients always have a natural entry point to
            reply to their coach right after watching. Routes to the same
            coach-thread page as the tab-bar Messages icon.

            Iter187 · Removed the `isWelcome` gate; now consistently
            available across every coach video (previously the button was
            also hidden below the fold because the player used a 9:16
            portrait aspect — now 16:9 landscape). */}
        <Pressable
          onPress={() => router.push("/(client)/messages" as any)}
          style={({ pressed }) => [styles.msgCta, pressed && { opacity: 0.85 }]}
          testID="welcome-message-coach"
          accessibilityRole="button"
          accessibilityLabel="Message your coach"
        >
          <Ionicons name="chatbubble-ellipses" size={16} color="#fff" />
          <Text style={styles.msgCtaT}>MESSAGE YOUR COACH</Text>
        </Pressable>
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
  // Iter187 · ScrollView body — generous bottom padding guarantees the
  // Message-Your-Coach CTA never sits behind the home-indicator / gesture
  // bar on iOS and Android navigation gestures.
  scrollBody: { padding: 20, paddingBottom: 48 },
  playerBox: {
    borderRadius: 14, backgroundColor: "#000",
    borderWidth: 1, borderColor: theme.color.border, overflow: "hidden",
    // Iter187 · Landscape 16:9 orientation — coach videos are recorded
    // and stored horizontally (screen-recorder teleprompter + phone
    // horizontal capture), so a 16:9 container fills the width without
    // black side-bars and keeps the CTA above the fold on mobile.
    aspectRatio: 16 / 9,
    width: "100%",
    alignItems: "center", justifyContent: "center",
  },
  player: { width: "100%", height: "100%", backgroundColor: "#000" },
  msgOnly: {
    flex: 1, alignItems: "center", justifyContent: "center", padding: 30,
    backgroundColor: theme.color.surface2,
  },
  eyebrow: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2, marginTop: 12 },
  hint: { color: theme.color.textMuted, fontSize: 12, textAlign: "center", marginTop: 10, lineHeight: 17, fontStyle: "italic" },
  scriptCard: {
    marginTop: 16, padding: 16, borderRadius: 12,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
  },
  scriptEyebrow: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  scriptBody: { color: theme.color.text, fontSize: 14, lineHeight: 22, marginTop: 10 },
  // Iter186 · Bullet-summary list styles
  bulletList: { marginTop: 12, gap: 10 },
  bulletRow: { flexDirection: "row", alignItems: "flex-start", gap: 10 },
  bulletDot: {
    width: 6, height: 6, borderRadius: 3,
    backgroundColor: theme.color.brand,
    marginTop: 8,
  },
  bulletT: {
    color: theme.color.text, fontSize: 14, lineHeight: 20,
    flex: 1, fontWeight: "600",
  },
  scriptFallback: {
    color: theme.color.textMuted, fontSize: 12, lineHeight: 17,
    marginTop: 10, fontStyle: "italic",
  },
  // Iter186 · Message-your-coach CTA
  msgCta: {
    marginTop: 16,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10,
    paddingVertical: 14, borderRadius: 12,
    backgroundColor: theme.color.brand,
  },
  msgCtaT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 1.6 },
});
