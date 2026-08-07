/**
 * WelcomeVideoBanner — surfaces a one-shot "watch your welcome video" card
 * on the client home screen when the coach has recorded and sent a welcome
 * video that the client hasn't opened yet.
 *
 * Iter 156 (Welcome Video Phase 2). The banner:
 *   1. Fetches `/videos/welcome-for-me` on mount and on focus.
 *   2. Renders nothing when the endpoint returns `{video: null}` or the
 *      video has already been watched.
 *   3. On tap: fires `POST /coach/videos/{id}/viewed` (fire-and-forget) so
 *      the server flips `status → viewed` (the /welcome-for-me endpoint
 *      then stops returning it), and immediately navigates to `/video/{id}`.
 *   4. Also hides locally (setState) so the card disappears the moment
 *      the user taps, without waiting for the server round-trip.
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
};

export function WelcomeVideoBanner() {
  const router = useRouter();
  const [video, setVideo] = useState<WelcomeVideo | null>(null);
  const [dismissedLocally, setDismissedLocally] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api<{ video: WelcomeVideo | null }>("/videos/welcome-for-me");
      setVideo(r?.video || null);
    } catch { /* silent — welcome video is optional */ }
  }, []);

  useFocusEffect(useCallback(() => {
    setDismissedLocally(false);
    load();
  }, [load]));

  if (!video || dismissedLocally) return null;
  if (video.watched_at) return null;

  const onWatch = () => {
    setDismissedLocally(true);
    // Server-side flip — status → "viewed", drops the row from future
    // /welcome-for-me responses. Fire-and-forget: the client already
    // navigated so we don't want to block on this.
    api(`/coach/videos/${video.id}/viewed`, { method: "POST", body: {} })
      .catch(() => { /* silent — banner is already hidden client-side */ });
    router.push(`/video/${video.id}` as any);
  };

  const durHint = typeof video.duration_seconds === "number" && video.duration_seconds > 0
    ? `${Math.max(1, Math.round(video.duration_seconds / 60))} min`
    : null;

  return (
    <Pressable style={styles.card} onPress={onWatch} testID="welcome-video-banner">
      <View style={styles.iconWrap}>
        <Ionicons name="videocam" size={22} color="#fff" />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.eyebrow}>NEW · WELCOME</Text>
        <Text style={styles.title}>Your coach recorded you a welcome video</Text>
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
