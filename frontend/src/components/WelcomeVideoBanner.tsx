/**
 * WelcomeVideoBanner — surfaces a "watch your coach's video" pill on the
 * client home screen.
 *
 * Iter 156 · Original — welcome video only.
 * Iter 165 · Persistence — welcome video sticky for 24 h after first view.
 * Iter 200 · Check-in takeover:
 *   Once the coach has sent a check-in (weekly) video, the pill is
 *   permanently taken over by the LATEST check-in video. Subsequent
 *   check-ins replace the previous one in place. The welcome video is
 *   never surfaced separately once a check-in exists — the backend
 *   `/videos/welcome-for-me` endpoint now returns whichever video
 *   belongs in the pill.
 *
 * Behaviour:
 *   1. Fetches `/videos/welcome-for-me` on mount and on focus.
 *   2. Renders nothing when the endpoint returns `{video: null}`.
 *   3. Renders welcome-video copy when `video_kind === "welcome"`.
 *   4. Renders check-in copy when `video_kind === "weekly"`.
 *   5. On tap: navigates to `/video/{id}`. The mark-viewed flip happens
 *      only when the player itself reports the video was fully watched.
 */
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useFocusEffect } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type HomePillVideo = {
  id: string;
  script?: string;
  duration_seconds?: number | null;
  watched_at?: string | null;
  sent_at?: string | null;
  status?: string | null;
  video_kind?: string | null;
};

export function WelcomeVideoBanner() {
  const router = useRouter();
  const [video, setVideo] = useState<HomePillVideo | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await api<{ video: HomePillVideo | null }>("/videos/welcome-for-me");
      setVideo(r?.video || null);
    } catch { /* silent — pill is optional */ }
  }, []);

  useFocusEffect(useCallback(() => {
    load();
  }, [load]));

  if (!video) return null;

  const onWatch = () => {
    // The mark-viewed flip happens only when the player reports full
    // watch (see video/[id].tsx). Just open the player here.
    router.push(`/video/${video.id}` as any);
  };

  const durHint = typeof video.duration_seconds === "number" && video.duration_seconds > 0
    ? `${Math.max(1, Math.round(video.duration_seconds / 60))} min`
    : null;

  const kind = (video.video_kind || "welcome").toLowerCase();
  const isCheckIn = kind === "weekly";
  const isReturn = !!video.watched_at;

  let eyebrow: string;
  let title: string;
  if (isCheckIn) {
    // Check-in / weekly review video — persistent pill.
    eyebrow = isReturn ? "LATEST CHECK-IN" : "NEW · CHECK-IN VIDEO";
    title = isReturn
      ? "Rewatch your coach's check-in video"
      : "Your coach sent you a check-in video";
  } else {
    // Welcome video (only surfaced before the first check-in exists).
    eyebrow = isReturn ? "PICK UP WHERE YOU LEFT OFF" : "NEW · WELCOME";
    title = isReturn
      ? "Rewatch your welcome video"
      : "Your coach recorded you a welcome video";
  }

  return (
    <Pressable style={styles.card} onPress={onWatch} testID="welcome-video-banner">
      <View style={styles.iconWrap}>
        <Ionicons name="videocam" size={22} color="#fff" />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.eyebrow}>{eyebrow}</Text>
        <Text style={styles.title}>{title}</Text>
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
    fontSize: 11,
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
    fontSize: 11,
    fontWeight: "900",
    letterSpacing: 1.5,
  },
});
