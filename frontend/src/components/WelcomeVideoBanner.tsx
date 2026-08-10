/**
 * WelcomeVideoBanner — surfaces a "watch your welcome video" card on the
 * client home screen when the coach has recorded and sent a welcome video.
 *
 * Iter 156 (Welcome Video Phase 2). Iter 165 · Persistence overhaul:
 *   1. Fetches `/videos/welcome-for-me` on mount and on focus.
 *   2. Renders nothing when the endpoint returns `{video: null}`
 *      (backend now returns the row while unwatched AND for a 24-hour
 *      grace period after first view — the client no longer decides
 *      when to hide it).
 *   3. On tap: navigates to `/video/{id}` WITHOUT firing a status flip.
 *      The mark-viewed flip only happens when the player itself reports
 *      the video has been fully watched (inside video/[id].tsx). This
 *      keeps the banner visible if the client dismisses the player
 *      accidentally.
 */
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useFocusEffect } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type WelcomeVideo = {
  id: string;
  script?: string;
  duration_seconds?: number | null;
  watched_at?: string | null;
  sent_at?: string | null;
  status?: string | null;
};

export function WelcomeVideoBanner() {
  const router = useRouter();
  const [video, setVideo] = useState<WelcomeVideo | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await api<{ video: WelcomeVideo | null }>("/videos/welcome-for-me");
      setVideo(r?.video || null);
    } catch { /* silent — welcome video is optional */ }
  }, []);

  useFocusEffect(useCallback(() => {
    load();
  }, [load]));

  if (!video) return null;

  const onWatch = () => {
    // Iter 165 · Do NOT mark viewed on tap — that flip now happens only
    // when the player reports full watch (see video/[id].tsx). Just open
    // the player. If the user dismisses the player without finishing, the
    // banner stays visible so they can come back to it.
    router.push(`/video/${video.id}` as any);
  };

  const durHint = typeof video.duration_seconds === "number" && video.duration_seconds > 0
    ? `${Math.max(1, Math.round(video.duration_seconds / 60))} min`
    : null;
  const isReturn = !!video.watched_at; // seen at least once, still in 24h grace

  return (
    <Pressable style={styles.card} onPress={onWatch} testID="welcome-video-banner">
      <View style={styles.iconWrap}>
        <Ionicons name="videocam" size={22} color="#fff" />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.eyebrow}>{isReturn ? "PICK UP WHERE YOU LEFT OFF" : "NEW · WELCOME"}</Text>
        <Text style={styles.title}>
          {isReturn ? "Rewatch your welcome video" : "Your coach recorded you a welcome video"}
        </Text>
        <Text style={styles.sub}>
          {durHint ? `Tap to watch · ${durHint}` : "Tap to watch"}
        </Text>
      </View>
      <View style={styles.playChip}>
        <Ionicons name="play" size={14} color={theme.color.brand} />
        <Text style={styles.playChipT}>WATCH</Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    padding: 14,
    borderRadius: 14,
    backgroundColor: theme.color.brandTint,
    borderWidth: 1,
    borderColor: theme.color.brand,
  },
  iconWrap: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: theme.color.brand,
    alignItems: "center",
    justifyContent: "center",
  },
  eyebrow: {
    color: theme.color.brand,
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 1.5,
  },
  title: {
    color: theme.color.text,
    fontSize: 14,
    fontWeight: "800",
    marginTop: 3,
  },
  sub: {
    color: theme.color.textMuted,
    fontSize: 11,
    marginTop: 2,
  },
  playChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 8,
    backgroundColor: theme.color.surface,
    borderWidth: 1,
    borderColor: theme.color.brand,
  },
  playChipT: {
    color: theme.color.brand,
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 1.5,
  },
});
