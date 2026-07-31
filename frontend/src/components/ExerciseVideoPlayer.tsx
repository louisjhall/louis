import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, Modal, ActivityIndicator,
  Platform, Linking, useWindowDimensions,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";
import { api } from "@/src/lib/api";

type VideoInfo = {
  video_id: string;
  title?: string;
  channel?: string;
  channel_hint?: string;
  thumbnail_url?: string;
  source?: string;
  approval_status?: string;
};

type VideoResult = { key: string; video: VideoInfo | null } | null;

// simple in-memory cache keyed by exerciseName
const memoryCache: Record<string, VideoResult> = {};
const inFlight: Record<string, Promise<VideoResult>> = {};

/**
 * Iter 130c — Clear cached video results.
 *
 * The How-To video for an exercise can change server-side (coach uploads a
 * new demo, changes preferred slot, etc.) and the in-memory cache used to
 * outlive those updates until the whole app was force-restarted, leaving
 * clients staring at a stale video. Callers such as the workout screens
 * invoke `clearVideoCache()` on focus so a fresh /exercises/video lookup
 * runs, without wiping the cache on every render.
 *
 * Passing a name clears just that entry; no arg wipes the whole cache.
 */
export function clearVideoCache(name?: string) {
  if (name) {
    delete memoryCache[name];
    delete inFlight[name];
    return;
  }
  for (const k of Object.keys(memoryCache)) delete memoryCache[k];
  for (const k of Object.keys(inFlight)) delete inFlight[k];
}

async function fetchVideo(name: string): Promise<VideoResult> {
  if (memoryCache[name] !== undefined) return memoryCache[name];
  if (inFlight[name]) return inFlight[name];
  const p = (async () => {
    try {
      const res = await api<any>(`/exercises/video?name=${encodeURIComponent(name)}`);
      const value = res?.video ? { key: res.key, video: res.video } : null;
      memoryCache[name] = value;
      return value;
    } catch {
      memoryCache[name] = null;
      return null;
    } finally {
      delete inFlight[name];
    }
  })();
  inFlight[name] = p;
  return p;
}

export function preloadExerciseVideos(names: string[]) {
  const missing = names.filter((n) => n && memoryCache[n] === undefined && !inFlight[n]);
  if (missing.length === 0) return;
  api<any>(`/exercises/videos-batch`, { method: "POST", body: { exercises: missing } })
    .then((res) => {
      const results = res?.results || {};
      for (const n of missing) {
        const v = results[n];
        memoryCache[n] = v && v.video ? { key: v.key, video: v.video } : null;
      }
    })
    .catch(() => {
      // ignore; individual fetches will fill later
    });
}

// --- YouTube iframe / WebView embed ---
function YouTubeEmbed({ videoId }: { videoId: string }) {
  const src = `https://www.youtube.com/embed/${videoId}?rel=0&modestbranding=1&playsinline=1`;
  if (Platform.OS === "web") {
    // In React Native Web, unknown intrinsic elements pass through to the DOM
    // via React.createElement. iframe is not typed by @types/react-native.
    return React.createElement("iframe", {
      src,
      style: { width: "100%", height: "100%", border: 0, background: "#000" },
      allow: "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share",
      allowFullScreen: true,
      referrerPolicy: "strict-origin-when-cross-origin",
    });
  }
  // Native: use react-native-webview
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { WebView } = require("react-native-webview");
  return (
    <WebView
      testID="yt-webview"
      style={{ flex: 1, backgroundColor: "#000" }}
      source={{ uri: src }}
      allowsFullscreenVideo
      allowsInlineMediaPlayback
      mediaPlaybackRequiresUserAction={false}
      javaScriptEnabled
      domStorageEnabled
    />
  );
}

// --- Custom (MP4/WebM) video embed (used for CrewFit uploads and pasted direct video URLs) ---
function CustomVideoEmbed({ videoUrl, mimeType }: { videoUrl: string; mimeType?: string }) {
  // Resolve relative URLs (like /api/videos/blob/xxx) to the backend base
  const resolved = videoUrl.startsWith("/") ? `${process.env.EXPO_PUBLIC_BACKEND_URL || ""}${videoUrl}` : videoUrl;
  if (Platform.OS === "web") {
    return React.createElement(
      "video",
      {
        src: resolved,
        controls: true,
        playsInline: true,
        style: { width: "100%", height: "100%", background: "#000", display: "block" },
      },
      mimeType ? React.createElement("source", { src: resolved, type: mimeType }) : null,
    );
  }
  // Native: render inside WebView using an HTML shell
  const html = `<!doctype html><html><body style="margin:0;background:#000;height:100vh;display:flex;align-items:center;justify-content:center">` +
    `<video src="${resolved}" controls playsinline autoplay style="max-width:100%;max-height:100%;background:#000"></video></body></html>`;
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { WebView } = require("react-native-webview");
  return (
    <WebView
      testID="custom-video-webview"
      style={{ flex: 1, backgroundColor: "#000" }}
      source={{ html }}
      allowsFullscreenVideo
      allowsInlineMediaPlayback
      mediaPlaybackRequiresUserAction={false}
      javaScriptEnabled
      originWhitelist={["*"]}
    />
  );
}

export function ExerciseVideoPlayer({
  exerciseName,
  compact = false,
  testIDPrefix = "video",
}: {
  exerciseName: string;
  compact?: boolean;
  testIDPrefix?: string;
}) {
  const [state, setState] = useState<{ loading: boolean; data: VideoResult }>({ loading: true, data: null });
  const [open, setOpen] = useState(false);
  const { width } = useWindowDimensions();
  const isWebDesktop = Platform.OS === "web" && width >= 900;

  const load = useCallback(async () => {
    if (memoryCache[exerciseName] !== undefined) {
      setState({ loading: false, data: memoryCache[exerciseName] });
      return;
    }
    setState({ loading: true, data: null });
    const v = await fetchVideo(exerciseName);
    setState({ loading: false, data: v });
  }, [exerciseName]);

  useEffect(() => { load(); }, [load]);

  const video = state.data?.video;

  if (state.loading) {
    return (
      <View style={[styles.card, compact && styles.cardCompact]} testID={`${testIDPrefix}-loading`}>
        <ActivityIndicator size="small" color={theme.color.brand} />
        <Text style={styles.loadingText}>LOADING DEMO…</Text>
      </View>
    );
  }

  if (!video) {
    return (
      <View style={[styles.card, styles.cardEmpty, compact && styles.cardCompact]} testID={`${testIDPrefix}-empty`}>
        <Ionicons name="videocam-off-outline" size={16} color={theme.color.textMuted} />
        <Text style={styles.emptyText}>Follow the written coaching cues below.</Text>
      </View>
    );
  }

  const isCustom = !video.video_id && !!video.video_url;
  const isCrewFitUpload = video.source === "custom_upload";
  const openExternal = () => {
    if (video.video_id) return Linking.openURL(`https://www.youtube.com/watch?v=${video.video_id}`);
    if (video.video_url) {
      const url = video.video_url.startsWith("/") ? `${process.env.EXPO_PUBLIC_BACKEND_URL || ""}${video.video_url}` : video.video_url;
      return Linking.openURL(url);
    }
  };
  const modalW = isWebDesktop ? Math.min(920, width - 80) : Math.min(width - 24, 900);
  const modalH = Math.round(modalW * 9 / 16);

  return (
    <>
      <Pressable
        testID={`${testIDPrefix}-thumb`}
        onPress={() => setOpen(true)}
        style={[styles.card, compact && styles.cardCompact]}
      >
        <View style={[styles.thumbBox, compact && styles.thumbBoxCompact]}>
          {video.thumbnail_url ? (
            Platform.OS === "web"
              ? React.createElement("img", {
                  src: video.thumbnail_url,
                  style: { width: "100%", height: "100%", objectFit: "cover", display: "block" },
                  alt: video.title || exerciseName,
                })
              : null
          ) : (
            <View style={{ flex: 1, backgroundColor: "#000" }} />
          )}
          <View style={styles.thumbOverlay} pointerEvents="none">
            <View style={styles.playBtn}>
              <Ionicons name="play" size={compact ? 16 : 22} color="#fff" />
            </View>
          </View>
        </View>
        <View style={styles.meta}>
          <View style={{ flex: 1 }}>
            <Text style={styles.channel} numberOfLines={1}>
              {isCrewFitUpload ? (
                <><Ionicons name="cloud-done" size={11} color={theme.color.brand} /> CREWFIT UPLOAD</>
              ) : isCustom ? (
                <><Ionicons name="link" size={11} color={theme.color.brand} /> {video.channel || "Custom Video"}</>
              ) : (
                <><Ionicons name="logo-youtube" size={11} color={theme.color.red} /> {video.channel || video.channel_hint || "YouTube"}</>
              )}
            </Text>
            <Text style={styles.title} numberOfLines={compact ? 1 : 2}>{video.title || exerciseName}</Text>
          </View>
          <Text style={styles.tapHint}>TAP TO PLAY</Text>
        </View>
      </Pressable>

      <Modal
        visible={open}
        onRequestClose={() => setOpen(false)}
        animationType="fade"
        transparent
        testID={`${testIDPrefix}-modal`}
      >
        <View style={styles.modalRoot}>
          <Pressable style={styles.backdrop} onPress={() => setOpen(false)} testID={`${testIDPrefix}-backdrop`} />
          <View style={[styles.modalCard, { width: modalW }]}>
            <View style={styles.modalHeader}>
              <View style={{ flex: 1 }}>
                <Text style={styles.modalTitle} numberOfLines={1}>{video.title || exerciseName}</Text>
                <Text style={styles.modalChannel} numberOfLines={1}>
                  {isCrewFitUpload ? (
                    <><Ionicons name="cloud-done" size={11} color={theme.color.brand} /> CREWFIT UPLOAD</>
                  ) : isCustom ? (
                    <><Ionicons name="link" size={11} color={theme.color.brand} /> {video.channel || "Custom Video"}</>
                  ) : (
                    <><Ionicons name="logo-youtube" size={11} color={theme.color.red} /> {video.channel || video.channel_hint || "YouTube"}</>
                  )}
                </Text>
              </View>
              <Pressable testID={`${testIDPrefix}-close`} onPress={() => setOpen(false)} hitSlop={12}>
                <Ionicons name="close" size={22} color={theme.color.text} />
              </Pressable>
            </View>
            <View style={{ width: "100%", height: modalH, backgroundColor: "#000" }}>
              {isCustom ? (
                <CustomVideoEmbed videoUrl={video.video_url!} mimeType={(video as any).mime_type} />
              ) : (
                <YouTubeEmbed videoId={video.video_id!} />
              )}
            </View>
            <View style={styles.modalFoot}>
              <Pressable testID={`${testIDPrefix}-open-yt`} onPress={openExternal} style={styles.footBtn}>
                <Ionicons name="open-outline" size={14} color={theme.color.textMuted} />
                <Text style={styles.footText}>{isCrewFitUpload ? "OPEN IN NEW TAB" : isCustom ? "OPEN VIDEO" : "OPEN ON YOUTUBE"}</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  card: {
    marginTop: 10,
    borderRadius: 10,
    overflow: "hidden",
    backgroundColor: theme.color.surface3,
    borderWidth: 1,
    borderColor: theme.color.border,
    maxWidth: 480,
  },
  cardCompact: { marginTop: 6, maxWidth: 320 },
  cardEmpty: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 10,
    paddingHorizontal: 12,
  },
  thumbBox: {
    width: "100%",
    aspectRatio: 16 / 9,
    backgroundColor: "#000",
    position: "relative",
    overflow: "hidden",
  },
  thumbBoxCompact: { aspectRatio: 16 / 9 },
  thumbOverlay: {
    ...StyleSheet.absoluteFillObject,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(0,0,0,0.15)",
  },
  playBtn: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: "rgba(255, 96, 30, 0.95)",
    alignItems: "center",
    justifyContent: "center",
    shadowColor: "#000",
    shadowOpacity: 0.4,
    shadowRadius: 8,
    elevation: 4,
  },
  meta: {
    flexDirection: "row",
    alignItems: "center",
    padding: 10,
    gap: 10,
  },
  channel: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 0.5, fontWeight: "700" },
  title: { color: theme.color.text, fontSize: 12, fontWeight: "600", marginTop: 2 },
  tapHint: { color: theme.color.brand, fontSize: 9, letterSpacing: 1, fontWeight: "800" },
  loadingText: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 1, fontWeight: "700", padding: 12 },
  emptyText: { color: theme.color.textMuted, fontSize: 12, flex: 1 },

  modalRoot: { flex: 1, alignItems: "center", justifyContent: "center" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.85)" },
  modalCard: {
    backgroundColor: theme.color.surface2,
    borderRadius: 12,
    overflow: "hidden",
    borderWidth: 1,
    borderColor: theme.color.border,
    maxHeight: "92%",
  },
  modalHeader: {
    flexDirection: "row",
    alignItems: "center",
    padding: 14,
    gap: 12,
    borderBottomWidth: 1,
    borderBottomColor: theme.color.border,
  },
  modalTitle: { color: theme.color.text, fontSize: 14, fontWeight: "800" },
  modalChannel: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },
  modalFoot: {
    flexDirection: "row",
    padding: 10,
    justifyContent: "flex-end",
    borderTopWidth: 1,
    borderTopColor: theme.color.border,
  },
  footBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 6,
  },
  footText: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 1.5, fontWeight: "800" },
});
