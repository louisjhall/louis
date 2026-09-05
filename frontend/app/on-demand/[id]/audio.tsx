/**
 * On Demand · Audio player screen.
 *
 * Minimal in-app player — no background / lock-screen playback (Stage 2
 * scope). Shows: play/pause, progress bar with seek, elapsed / duration.
 *
 * Fed by the presigned R2 URL from
 *   `GET /api/on-demand/items/{id}/media-url`
 *
 * Route: /on-demand/[id]/audio
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator, Platform } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useAudioPlayer, useAudioPlayerStatus, setAudioModeAsync } from "expo-audio";
import { activateKeepAwakeAsync, deactivateKeepAwake } from "expo-keep-awake";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Item = {
  id: string;
  title: string;
  description?: string;
  duration_seconds?: number | null;
};

function fmt(sec: number) {
  if (!isFinite(sec) || sec < 0) return "0:00";
  const s = Math.floor(sec);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r.toString().padStart(2, "0")}`;
}

export default function OnDemandAudioScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [item, setItem] = useState<Item | null>(null);
  const [uri, setUri] = useState<string | null>(null);

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

  // Ensure audio plays even when the phone is on silent mode.
  useEffect(() => {
    setAudioModeAsync({ playsInSilentMode: true }).catch(() => {});
  }, []);

  const player = useAudioPlayer(uri ? { uri } : null);
  const status = useAudioPlayerStatus(player);

  // Fall back to the item's declared duration until the player reports
  // its own (which happens after the header is loaded).
  const duration = useMemo(() => {
    if (status && status.duration > 0) return status.duration;
    if (item?.duration_seconds && item.duration_seconds > 0) return item.duration_seconds;
    return 0;
  }, [status, item?.duration_seconds]);

  const currentTime = status?.currentTime || 0;
  const playing = !!status?.playing;
  const progressPct = duration > 0 ? Math.min(1, Math.max(0, currentTime / duration)) : 0;

  // Iter200 · Keep the screen awake ONLY while audio is actually
  // playing. Meditation and guided-audio sessions were putting the
  // phone to sleep mid-session; now the display stays on until the
  // member pauses / seeks-and-pauses / leaves the screen. On unmount
  // we always release so we never accidentally hold the wake-lock
  // beyond the session.
  useEffect(() => {
    const tag = `on-demand-audio:${id ?? "unknown"}`;
    if (playing) {
      activateKeepAwakeAsync(tag).catch(() => {});
    } else {
      deactivateKeepAwake(tag);
    }
    return () => {
      deactivateKeepAwake(tag);
    };
  }, [playing, id]);

  const togglePlay = useCallback(() => {
    if (!player) return;
    if (playing) player.pause(); else player.play();
  }, [player, playing]);

  const onScrub = useCallback(
    (evt: any) => {
      if (!player || duration <= 0) return;
      const { locationX } = evt.nativeEvent;
      const trackWidth = evt.currentTarget?.offsetWidth
        || evt.nativeEvent?.target?.offsetWidth
        // Fallback for RN native — measure via container. locationX / width ratio.
        || 0;
      // On native, use a percentage-based estimate from the parent view width;
      // we compute this in the Pressable's onLayout below.
      const ratio = trackWidth > 0 ? locationX / trackWidth : locationX / (barWidth || 1);
      const target = Math.max(0, Math.min(duration, ratio * duration));
      player.seekTo(target);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [player, duration],
  );

  // Track the progress bar's width so scrub math works on native (where
  // event.currentTarget.offsetWidth is undefined).
  const [barWidth, setBarWidth] = useState(0);

  const back15 = useCallback(() => {
    if (!player) return;
    player.seekTo(Math.max(0, currentTime - 15));
  }, [player, currentTime]);

  const fwd15 = useCallback(() => {
    if (!player) return;
    player.seekTo(Math.min(duration || currentTime + 15, currentTime + 15));
  }, [player, currentTime, duration]);

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <View style={styles.topBar}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="od-audio-close">
          <Ionicons name="close" size={26} color={theme.color.text} />
        </Pressable>
        <Text style={styles.eyebrow}>ON DEMAND · AUDIO</Text>
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
        <View style={styles.body}>
          <View style={styles.artwork}>
            <Ionicons name="headset" size={72} color={theme.color.brand} />
          </View>
          <Text style={styles.title} numberOfLines={2}>{item?.title || "Audio"}</Text>
          {item?.description ? (
            <Text style={styles.description} numberOfLines={4}>{item.description}</Text>
          ) : null}

          {/* Progress bar */}
          <View style={styles.progressWrap}>
            <Pressable
              testID="od-audio-scrub"
              onPress={onScrub}
              onLayout={(e) => setBarWidth(e.nativeEvent.layout.width)}
              style={styles.progressTrack}
              hitSlop={{ top: 12, bottom: 12, left: 0, right: 0 }}
            >
              <View style={[styles.progressFill, { width: `${progressPct * 100}%` }]} />
              <View
                style={[
                  styles.progressKnob,
                  { left: `${progressPct * 100}%` },
                ]}
              />
            </Pressable>
            <View style={styles.timeRow}>
              <Text style={styles.time}>{fmt(currentTime)}</Text>
              <Text style={styles.time}>{fmt(duration)}</Text>
            </View>
          </View>

          {/* Transport controls */}
          <View style={styles.controls}>
            <Pressable onPress={back15} style={styles.ctrlBtn} testID="od-audio-back15">
              <Ionicons name="play-back" size={26} color={theme.color.text} />
              <Text style={styles.ctrlLabel}>-15s</Text>
            </Pressable>
            <Pressable
              onPress={togglePlay}
              style={styles.playBtn}
              testID="od-audio-toggle"
              accessibilityRole="button"
              accessibilityLabel={playing ? "Pause" : "Play"}
            >
              <Ionicons
                name={playing ? "pause" : "play"}
                size={36}
                color="#fff"
                style={Platform.OS === "web" ? { marginLeft: playing ? 0 : 2 } : undefined}
              />
            </Pressable>
            <Pressable onPress={fwd15} style={styles.ctrlBtn} testID="od-audio-fwd15">
              <Ionicons name="play-forward" size={26} color={theme.color.text} />
              <Text style={styles.ctrlLabel}>+15s</Text>
            </Pressable>
          </View>
        </View>
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
  body: {
    flex: 1, alignItems: "center", justifyContent: "center",
    paddingHorizontal: 32, paddingBottom: 40,
  },

  artwork: {
    width: 200, height: 200, borderRadius: 100,
    alignItems: "center", justifyContent: "center",
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
    marginBottom: 24,
  },
  title: {
    color: theme.color.text, fontSize: 20, fontWeight: "800",
    textAlign: "center", marginBottom: 8,
  },
  description: {
    color: theme.color.text, fontSize: 13, lineHeight: 20,
    textAlign: "center", opacity: 0.8, marginBottom: 24,
  },

  progressWrap: { width: "100%", marginBottom: 24 },
  progressTrack: {
    width: "100%", height: 6, borderRadius: 3,
    backgroundColor: theme.color.surface2,
    justifyContent: "center",
  },
  progressFill: {
    position: "absolute", left: 0, top: 0, bottom: 0,
    backgroundColor: theme.color.brand, borderRadius: 3,
  },
  progressKnob: {
    position: "absolute",
    width: 14, height: 14, borderRadius: 7,
    backgroundColor: theme.color.brand,
    marginLeft: -7, top: -4,
  },
  timeRow: {
    flexDirection: "row", justifyContent: "space-between",
    marginTop: 8,
  },
  time: {
    color: theme.color.textDim, fontSize: 12, fontVariant: ["tabular-nums"],
  },

  controls: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 24,
  },
  ctrlBtn: { alignItems: "center", padding: 12 },
  ctrlLabel: {
    color: theme.color.textDim, fontSize: 10, fontWeight: "700",
    letterSpacing: 0.5, marginTop: 2,
  },
  playBtn: {
    width: 78, height: 78, borderRadius: 39,
    alignItems: "center", justifyContent: "center",
    backgroundColor: theme.color.brand,
  },
});
