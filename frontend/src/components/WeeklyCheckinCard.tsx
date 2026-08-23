/**
 * WeeklyCheckinCard — home surface card for the Sunday check-in touchpoint.
 * Fetches /checkins/current + /videos/for-me and renders three states:
 *   1. Not submitted this week → prompt to complete
 *   2. Submitted, video pending → "Louis is preparing your video"
 *   3. Video ready → tap to open video screen
 */
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

export function WeeklyCheckinCard() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [current, setCurrent] = useState<any>(null);
  const [video, setVideo] = useState<any>(null);

  const load = useCallback(async () => {
    try {
      const [cur, vids] = await Promise.all([
        api<any>("/checkins/current"),
        api<any>("/videos/for-me").catch(() => ({ videos: [] })),
      ]);
      setCurrent(cur);
      const latest = (vids?.videos || [])[0];
      // Only show latest if it matches this week's check-in
      if (latest && cur?.check_in && latest.check_in_id === cur.check_in.id) setVideo(latest);
      else setVideo(null);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (loading) return <View style={styles.skeleton}><ActivityIndicator color={theme.color.brand} size="small" /></View>;
  if (!current) return null;

  const ci = current.check_in;

  // Iter 83 — Sunday gating: hide the card entirely unless the backend says
  // it's due today. Prevents brand-new signups from seeing "Ready when you
  // are" the moment they land on home.
  if (!ci && current.should_show_card === false) return null;

  // State 1: not submitted
  if (!ci) {
    // Format the human-readable "next Sunday" string once, defensively.
    const nextSunPretty = (() => {
      const raw = current.next_sunday_local;
      if (!raw) return "This Sunday";
      try {
        const d = new Date(raw);
        return d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "short" });
      } catch { return "This Sunday"; }
    })();
    return (
      <Pressable onPress={() => router.push("/checkin" as any)} style={styles.pending} testID="weekly-checkin-open">
        <View style={styles.icon}><Ionicons name="clipboard" size={22} color={theme.color.brand} /></View>
        <View style={{ flex: 1 }}>
          <Text style={styles.eyebrow}>WEEKLY CHECK-IN · SUNDAY</Text>
          <Text style={styles.title}>Ready when you are</Text>
          <Text style={styles.sub}>
            {current.is_sunday_local
              ? "Sunday review — takes 90 seconds. On duty today? Do it after your sector."
              : `Next scheduled: ${nextSunPretty}. Tap to fill it in early if you're flying that day.`}
          </Text>
        </View>
        <Ionicons name="arrow-forward" size={16} color={theme.color.brand} />
      </Pressable>
    );
  }

  // State 3: video ready — Iter 145 rich card with summary + date + View Full Review
  if (video && video.status === "sent") {
    const dateStr = (() => {
      try {
        return new Date(video.sent_at || ci.submitted_at).toLocaleDateString("en-GB",
          { weekday: "long", day: "numeric", month: "short" });
      } catch { return ""; }
    })();
    const summary = (ci.atlas_client_summary || "").trim();
    return (
      <View style={styles.videoReadyCard} testID="weekly-video-card">
        <Pressable onPress={() => router.push(`/video/${video.id}` as any)} style={styles.videoTopRow} testID="weekly-video-open">
          <View style={styles.thumb}>
            <Ionicons name="play" size={28} color="#fff" />
          </View>
          <View style={{ flex: 1, marginLeft: 12 }}>
            <Text style={styles.videoEyebrow}>WEEKLY CHECK-IN VIDEO READY</Text>
            <Text style={styles.videoTitle}>Video from Louis</Text>
            {dateStr ? <Text style={styles.videoDate}>{dateStr}</Text> : null}
          </View>
        </Pressable>
        {summary ? (
          <Text style={styles.summaryTxt} numberOfLines={5}>{summary}</Text>
        ) : null}
        <View style={styles.videoActions}>
          <Pressable
            onPress={() => router.push(`/video/${video.id}` as any)}
            style={styles.playBtn}
            testID="weekly-video-play"
          >
            <Ionicons name="play-circle" size={16} color="#fff" />
            <Text style={styles.playT}>PLAY VIDEO</Text>
          </Pressable>
          <Pressable
            onPress={() => router.push(`/checkin/history` as any)}
            style={styles.fullReviewBtn}
            testID="view-full-review"
          >
            <Text style={styles.fullReviewT}>VIEW FULL REVIEW</Text>
          </Pressable>
        </View>
      </View>
    );
  }

  // State 2: submitted, waiting for video — Iter 145 show coach-approved summary when present
  const pendingSummary = (ci.atlas_client_summary || "").trim();
  return (
    <View style={styles.pending}>
      <View style={styles.icon}><Ionicons name="checkmark-circle" size={22} color={theme.color.green} /></View>
      <View style={{ flex: 1 }}>
        <Text style={styles.eyebrow}>WEEKLY CHECK-IN SUBMITTED</Text>
        <Text style={styles.title}>Louis is reviewing your week</Text>
        <Text style={styles.sub} numberOfLines={3}>
          {pendingSummary
            ? pendingSummary.slice(0, 220)
            : (ci.next_week_focus ? ci.next_week_focus.slice(0, 160) : "You'll get a notification when your video is ready.")}
        </Text>
        <Text style={styles.nextT}>Your weekly video will appear here when Louis sends it.</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  skeleton: { padding: 16, borderRadius: 12, backgroundColor: theme.color.surface2, alignItems: "center" },
  pending: {
    flexDirection: "row", alignItems: "center", gap: 12,
    padding: 14, borderRadius: 12,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  videoReadyCard: {
    padding: 14, borderRadius: 12,
    backgroundColor: theme.color.brand,
  },
  videoTopRow: { flexDirection: "row", alignItems: "center" },
  thumb: {
    width: 60, height: 60, borderRadius: 10,
    backgroundColor: "rgba(0,0,0,0.35)",
    alignItems: "center", justifyContent: "center",
  },
  videoEyebrow: { color: "rgba(255,255,255,0.85)", fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  videoTitle: { color: "#fff", fontSize: 15, fontWeight: "900", marginTop: 4 },
  videoDate: { color: "rgba(255,255,255,0.8)", fontSize: 11, marginTop: 2 },
  summaryTxt: { color: "#fff", fontSize: 12, lineHeight: 17, marginTop: 12 },
  videoActions: { flexDirection: "row", gap: 8, marginTop: 12 },
  playBtn: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: "rgba(0,0,0,0.35)", paddingHorizontal: 14, paddingVertical: 10, borderRadius: 8, flex: 1, justifyContent: "center" },
  playT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  fullReviewBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", paddingHorizontal: 14, paddingVertical: 10, borderRadius: 8, borderWidth: 1, borderColor: "rgba(255,255,255,0.6)", flex: 1 },
  fullReviewT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  icon: {
    width: 40, height: 40, borderRadius: 20,
    backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
  },
  eyebrow: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  title: { color: theme.color.text, fontSize: 14, fontWeight: "800", marginTop: 4 },
  sub: { color: theme.color.textMuted, fontSize: 11, marginTop: 4, lineHeight: 15 },
  nextT: { color: theme.color.textDim, fontSize: 11, marginTop: 6, fontStyle: "italic" },
});
