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
  const tz = current.time_zone || "Europe/London";

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

  // State 3: video ready
  if (video && video.status === "sent") {
    return (
      <Pressable onPress={() => router.push(`/video/${video.id}` as any)} style={styles.videoReady} testID="weekly-video-open">
        <View style={styles.icon}><Ionicons name="videocam" size={22} color="#fff" /></View>
        <View style={{ flex: 1 }}>
          <Text style={[styles.eyebrow, { color: "#fff" }]}>VIDEO FROM LOUIS</Text>
          <Text style={[styles.title, { color: "#fff" }]}>Your weekly review is ready</Text>
          <Text style={[styles.sub, { color: "rgba(255,255,255,0.85)" }]}>Tap to watch</Text>
        </View>
        <Ionicons name="play-circle" size={26} color="#fff" />
      </Pressable>
    );
  }

  // State 2: submitted, waiting for video
  return (
    <View style={styles.pending}>
      <View style={styles.icon}><Ionicons name="checkmark-circle" size={22} color={theme.color.green} /></View>
      <View style={{ flex: 1 }}>
        <Text style={styles.eyebrow}>WEEKLY CHECK-IN COMPLETE</Text>
        <Text style={styles.title}>Louis is preparing your video</Text>
        <Text style={styles.sub} numberOfLines={2}>
          {ci.next_week_focus ? ci.next_week_focus.slice(0, 120) : "You'll be notified when it's ready."}
        </Text>
        <Text style={styles.nextT}>Next check-in: Sunday 09:00 {tz}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  skeleton: { marginHorizontal: 16, marginTop: 12, padding: 16, borderRadius: 12, backgroundColor: theme.color.surface2, alignItems: "center" },
  pending: {
    flexDirection: "row", alignItems: "center", gap: 12,
    marginHorizontal: 16, marginTop: 12, padding: 14, borderRadius: 12,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  videoReady: {
    flexDirection: "row", alignItems: "center", gap: 12,
    marginHorizontal: 16, marginTop: 12, padding: 14, borderRadius: 12,
    backgroundColor: theme.color.brand, borderWidth: 1, borderColor: theme.color.brand,
  },
  icon: {
    width: 40, height: 40, borderRadius: 20,
    backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
  },
  eyebrow: { color: theme.color.brand, fontSize: 9, fontWeight: "900", letterSpacing: 2 },
  title: { color: theme.color.text, fontSize: 14, fontWeight: "800", marginTop: 4 },
  sub: { color: theme.color.textMuted, fontSize: 11, marginTop: 4, lineHeight: 15 },
  nextT: { color: theme.color.textDim, fontSize: 10, marginTop: 6, fontStyle: "italic" },
});
