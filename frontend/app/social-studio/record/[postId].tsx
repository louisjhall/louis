/**
 * Social Studio — Recording Studio + Teleprompter
 *
 * Full-screen vertical (9:16) recorder for CrewFit social posts. The generated
 * script auto-scrolls as an overlay above the camera. Users can:
 *   • Adjust scroll speed and font size before recording
 *   • Trigger a 3-2-1 countdown before REC starts
 *   • Stop manually or automatically at 60s
 *   • Retake, Save Draft, or Send to Subtitle Editor
 *
 * Native (Expo build): uses expo-camera `CameraView` with `recordAsync`.
 * Web preview: uses browser `MediaRecorder` for testing the UI end-to-end.
 * The camera behaviour only lands fully on a device build after Publish.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator, Alert, Linking, Platform, Pressable, ScrollView, StyleSheet, Text, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { CameraView, useCameraPermissions, useMicrophonePermissions } from "expo-camera";
import * as FileSystem from "expo-file-system";
import { api, uploadFile } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

const MAX_CLIP_SECONDS = 60;
const SCROLL_TICK_MS = 100;

type Phase =
  | "loading"
  | "permission"           // permission prompt / denied
  | "ready"                // idle, camera visible
  | "countdown"
  | "recording"
  | "processing"           // stopping / awaiting native file
  | "preview"
  | "uploading";

type SocialPost = {
  id: string;
  title?: string;
  platform?: string;
  post_type?: string;
  hook?: string;
  script?: string;
  teleprompter_script?: string;
  status?: string;
};

export default function RecordScreen() {
  const { postId } = useLocalSearchParams<{ postId: string }>();
  const router = useRouter();

  // --- Server state --------------------------------------------------------
  const [post, setPost] = useState<SocialPost | null>(null);
  const [loading, setLoading] = useState(true);

  // --- Camera + mic permissions -------------------------------------------
  const [camPerm, requestCam] = useCameraPermissions();
  const [micPerm, requestMic] = useMicrophonePermissions();

  // --- Phase / recording state --------------------------------------------
  const [phase, setPhase] = useState<Phase>("loading");
  const [countdown, setCountdown] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [scrollSpeed, setScrollSpeed] = useState(45);    // px/s
  const [fontSize, setFontSize] = useState(22);
  const [uploadPct, setUploadPct] = useState(0);
  const [recordedUri, setRecordedUri] = useState<string | null>(null);   // native cache URI or web object URL
  const [recordedBlob, setRecordedBlob] = useState<Blob | null>(null);   // web fallback

  // --- Refs ----------------------------------------------------------------
  const camRef = useRef<CameraView | null>(null);
  const scriptScroll = useRef<ScrollView | null>(null);
  const scrollTimer = useRef<any>(null);
  const elapsedTimer = useRef<any>(null);
  const autoStopTimer = useRef<any>(null);
  const scrollOffset = useRef(0);

  // web fallback refs
  const webStreamRef = useRef<MediaStream | null>(null);
  const webRecorderRef = useRef<MediaRecorder | null>(null);
  const webChunks = useRef<Blob[]>([]);
  const webVideoRef = useRef<any>(null);

  const teleprompter = (post?.teleprompter_script || post?.script || post?.hook || "").trim();

  // ------------------------------------------------------------------------
  // Load post
  // ------------------------------------------------------------------------
  useEffect(() => {
    (async () => {
      try {
        const r = await api<{ post: SocialPost }>(`/social/posts/${postId}`);
        setPost(r.post);
      } catch (e: any) {
        Alert.alert("Load failed", e?.message || "Could not load post");
        router.back();
      } finally { setLoading(false); }
    })();
  }, [postId, router]);

  // ------------------------------------------------------------------------
  // Permission gate — kicks in once loading finishes
  // ------------------------------------------------------------------------
  useEffect(() => {
    if (loading) return;
    (async () => {
      // On web we use MediaRecorder — expo-camera permission hooks are still safe to call.
      if (Platform.OS === "web") {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: "user", width: { ideal: 720 }, height: { ideal: 1280 } },
            audio: true,
          });
          webStreamRef.current = stream;
          if (webVideoRef.current) {
            webVideoRef.current.srcObject = stream;
            try { await webVideoRef.current.play(); } catch { /* autoplay may need gesture */ }
          }
          setPhase("ready");
        } catch (e: any) {
          setPhase("permission");
        }
        return;
      }
      // Native path — request both perms sequentially with contextual pre-explainer
      let cur = camPerm;
      if (!cur || cur.status === "undetermined") {
        cur = await requestCam();
      }
      let curMic = micPerm;
      if (!curMic || curMic.status === "undetermined") {
        curMic = await requestMic();
      }
      if (cur?.granted && curMic?.granted) setPhase("ready");
      else setPhase("permission");
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading]);

  // ------------------------------------------------------------------------
  // Cleanup
  // ------------------------------------------------------------------------
  useEffect(() => {
    return () => {
      clearTimers();
      webStreamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  const clearTimers = () => {
    if (scrollTimer.current) { clearInterval(scrollTimer.current); scrollTimer.current = null; }
    if (elapsedTimer.current) { clearInterval(elapsedTimer.current); elapsedTimer.current = null; }
    if (autoStopTimer.current) { clearTimeout(autoStopTimer.current); autoStopTimer.current = null; }
  };

  // ------------------------------------------------------------------------
  // Recording control
  // ------------------------------------------------------------------------
  const startCountdown = () => {
    if (!teleprompter) {
      Alert.alert("Script missing", "Generate a script for this post before recording.");
      return;
    }
    setPhase("countdown");
    setCountdown(3);
    const tick = setInterval(() => {
      setCountdown((c) => {
        if (c <= 1) { clearInterval(tick); beginRecording(); return 0; }
        return c - 1;
      });
    }, 900);
  };

  const beginRecording = async () => {
    setElapsed(0);
    scrollOffset.current = 0;
    scriptScroll.current?.scrollTo({ y: 0, animated: false });

    // Auto-scroll teleprompter
    scrollTimer.current = setInterval(() => {
      scrollOffset.current += (scrollSpeed * SCROLL_TICK_MS) / 1000;
      scriptScroll.current?.scrollTo({ y: scrollOffset.current, animated: false });
    }, SCROLL_TICK_MS);

    // Elapsed timer + auto-stop
    elapsedTimer.current = setInterval(() => setElapsed((s) => s + 1), 1000);
    autoStopTimer.current = setTimeout(() => stopRecording(true), MAX_CLIP_SECONDS * 1000);

    if (Platform.OS === "web") {
      startWebRecording();
    } else {
      startNativeRecording();
    }
  };

  const startNativeRecording = async () => {
    setPhase("recording");
    try {
      const result = await camRef.current?.recordAsync({ maxDuration: MAX_CLIP_SECONDS });
      // recordAsync resolves when stopRecording is called or maxDuration elapses
      clearTimers();
      if (result?.uri) {
        setRecordedUri(result.uri);
        setPhase("preview");
      } else {
        setPhase("ready");
      }
    } catch (e: any) {
      clearTimers();
      Alert.alert("Recording failed", e?.message || "Try again");
      setPhase("ready");
    }
  };

  const startWebRecording = () => {
    if (!webStreamRef.current) { Alert.alert("Camera not ready", "Reload the page and grant camera access."); return; }
    webChunks.current = [];
    try {
      const mime = pickMime();
      const rec = new MediaRecorder(webStreamRef.current, mime ? { mimeType: mime } : undefined);
      rec.ondataavailable = (e) => { if (e.data.size > 0) webChunks.current.push(e.data); };
      rec.onstop = () => {
        const type = mime || "video/webm";
        const blob = new Blob(webChunks.current, { type });
        setRecordedBlob(blob);
        setRecordedUri(URL.createObjectURL(blob));
        setPhase("preview");
      };
      rec.start();
      webRecorderRef.current = rec;
      setPhase("recording");
    } catch (e: any) {
      Alert.alert("Recorder failed", e?.message || "Browser did not support MediaRecorder.");
      setPhase("ready");
      clearTimers();
    }
  };

  const stopRecording = (auto = false) => {
    clearTimers();
    if (Platform.OS === "web") {
      try { webRecorderRef.current?.stop(); } catch { /* ignore */ }
    } else {
      try { camRef.current?.stopRecording(); } catch { /* ignore */ }
      // Native recordAsync promise will resolve and flip to preview
    }
    if (auto) { /* auto-stop hint UI could go here */ }
  };

  // ------------------------------------------------------------------------
  // Preview actions
  // ------------------------------------------------------------------------
  const doRetake = () => {
    if (recordedUri && recordedUri.startsWith("blob:")) URL.revokeObjectURL(recordedUri);
    setRecordedUri(null);
    setRecordedBlob(null);
    setElapsed(0);
    scrollOffset.current = 0;
    scriptScroll.current?.scrollTo({ y: 0, animated: false });
    setPhase("ready");
  };

  const doSaveDraft = useCallback(async (goToSubtitles = false) => {
    if (!recordedUri) return;
    setPhase("uploading");
    setUploadPct(0);
    try {
      let filePayload: any;
      let mimeType = "video/mp4";
      if (Platform.OS === "web") {
        if (!recordedBlob) throw new Error("no blob to upload");
        mimeType = recordedBlob.type || "video/webm";
        filePayload = recordedBlob;
      } else {
        // native: derive mime from extension
        const uriLower = recordedUri.toLowerCase();
        if (uriLower.endsWith(".mov")) mimeType = "video/quicktime";
        else if (uriLower.endsWith(".webm")) mimeType = "video/webm";
        else mimeType = "video/mp4";
        const name = `crewfit-${postId}-${Date.now()}.${mimeType.split("/")[1] || "mp4"}`;
        filePayload = { uri: recordedUri, name, type: mimeType };
      }
      const r = await uploadFile<{ asset: { id: string } }>(
        `/social/posts/${postId}/assets`,
        filePayload,
        {
          kind: "video",
          duration_seconds: String(elapsed),
        },
        { onProgress: (loaded, total) => setUploadPct(total ? loaded / total : 0) },
      );
      const assetId = r?.asset?.id;
      // Cleanup native temp file (best effort)
      if (Platform.OS !== "web" && recordedUri) {
        try { await FileSystem.deleteAsync(recordedUri, { idempotent: true }); } catch { /* ignore */ }
      }
      if (goToSubtitles && assetId) {
        router.replace(`/social-studio/subtitles/${assetId}`);
      } else {
        Alert.alert("Draft saved", "Recording saved to Social Studio.");
        router.back();
      }
    } catch (e: any) {
      Alert.alert("Upload failed", e?.message || "Try again");
      setPhase("preview");
    }
  }, [recordedUri, recordedBlob, postId, elapsed, router]);

  const openSettings = () => Linking.openSettings().catch(() => {});

  // ------------------------------------------------------------------------
  // Render helpers
  // ------------------------------------------------------------------------
  if (loading || phase === "loading") {
    return (
      <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
        <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>
      </SafeAreaView>
    );
  }

  if (phase === "permission") {
    const isWeb = Platform.OS === "web";
    return (
      <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
        <View style={styles.topBar}>
          <Pressable onPress={() => router.back()} hitSlop={12} testID="record-close">
            <Ionicons name="close" size={24} color={theme.color.text} />
          </Pressable>
          <Text style={styles.topTitle}>RECORDING STUDIO</Text>
          <View style={{ width: 24 }} />
        </View>
        <View style={styles.permWrap}>
          <Ionicons name="videocam" size={44} color={theme.color.brand} />
          <Text style={styles.permTitle}>Camera & microphone access</Text>
          <Text style={styles.permBody}>
            CrewFit needs your camera and mic to record vertical social videos with the Atlas
            teleprompter. Nothing is uploaded until you tap Save Draft.
          </Text>
          <Pressable
            onPress={async () => {
              if (isWeb) {
                try {
                  const s = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" }, audio: true });
                  webStreamRef.current = s;
                  if (webVideoRef.current) { webVideoRef.current.srcObject = s; try { await webVideoRef.current.play(); } catch {} }
                  setPhase("ready");
                } catch { openSettings(); }
              } else {
                const c = await requestCam();
                const m = await requestMic();
                if (c.granted && m.granted) setPhase("ready");
                else if (!c.canAskAgain || !m.canAskAgain) openSettings();
              }
            }}
            style={styles.primaryBtn}
            testID="record-grant"
          >
            <Text style={styles.primaryBtnT}>GRANT ACCESS</Text>
          </Pressable>
          {(!isWeb && ((camPerm && !camPerm.canAskAgain) || (micPerm && !micPerm.canAskAgain))) ? (
            <Pressable onPress={openSettings} style={styles.altBtn}>
              <Text style={styles.altBtnT}>OPEN SETTINGS</Text>
            </Pressable>
          ) : null}
        </View>
      </SafeAreaView>
    );
  }

  // Main recording UI
  const showTeleprompter = phase === "ready" || phase === "countdown" || phase === "recording";
  const showPreview = phase === "preview" || phase === "uploading";

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <View style={styles.topBar}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="record-close" disabled={phase === "recording"}>
          <Ionicons name="close" size={24} color={phase === "recording" ? theme.color.textDim : theme.color.text} />
        </Pressable>
        <Text style={styles.topTitle}>RECORDING STUDIO · {(post?.platform || "").toUpperCase()}</Text>
        <View style={{ width: 24 }} />
      </View>

      {/* 9:16 camera stage */}
      <View style={styles.stage}>
        {showPreview && recordedUri ? (
          Platform.OS === "web" ? (
            // @ts-ignore native video for RN Web
            <video
              src={recordedUri}
              controls
              playsInline
              style={{ width: "100%", height: "100%", objectFit: "cover", background: "#000" }}
            />
          ) : (
            // Native native preview: fall back to a placeholder card;
            // (expo-video preview is deferred to real device build)
            <View style={styles.previewNative}>
              <Ionicons name="film-outline" size={40} color={theme.color.text} />
              <Text style={styles.previewNativeT}>Draft ready · {fmt(elapsed)}</Text>
              <Text style={styles.previewNativeSub}>Preview will be available in the native build.</Text>
            </View>
          )
        ) : Platform.OS === "web" ? (
          // @ts-ignore native <video> element on RN Web
          <video
            ref={webVideoRef}
            autoPlay
            playsInline
            muted
            style={{ width: "100%", height: "100%", objectFit: "cover", background: "#000", transform: "scaleX(-1)" }}
          />
        ) : (
          <CameraView
            ref={(r) => { camRef.current = r; }}
            style={styles.cam}
            facing="front"
            mode="video"
            videoQuality="1080p"
          />
        )}

        {/* Teleprompter overlay */}
        {showTeleprompter && teleprompter ? (
          <View pointerEvents={phase === "recording" ? "none" : "auto"} style={styles.telepromWrap}>
            <Text style={styles.telepromEyebrow}>TELEPROMPTER · {scrollSpeed}px/s</Text>
            <ScrollView
              ref={scriptScroll}
              style={styles.telepromScroll}
              showsVerticalScrollIndicator={false}
              contentContainerStyle={{ padding: 16 }}
            >
              <Text style={[styles.telepromT, { fontSize, lineHeight: Math.round(fontSize * 1.45) }]}>
                {teleprompter}
              </Text>
              <View style={{ height: 260 }} />
            </ScrollView>
          </View>
        ) : null}

        {/* Countdown overlay */}
        {phase === "countdown" ? (
          <View style={styles.overlay}>
            <Text style={styles.countdownBig}>{countdown}</Text>
          </View>
        ) : null}

        {/* REC pill */}
        {phase === "recording" ? (
          <View style={styles.recPill}>
            <View style={styles.recDot} />
            <Text style={styles.recT}>REC · {fmt(elapsed)} / {fmt(MAX_CLIP_SECONDS)}</Text>
          </View>
        ) : null}
      </View>

      {/* Bottom control bar */}
      <View style={styles.bottom}>
        {phase === "ready" ? (
          <>
            <View style={styles.chipsRow}>
              <Text style={styles.chipsLabel}>SPEED</Text>
              <Chip label="SLOW" active={scrollSpeed === 30} onPress={() => setScrollSpeed(30)} />
              <Chip label="NORMAL" active={scrollSpeed === 45} onPress={() => setScrollSpeed(45)} />
              <Chip label="FAST" active={scrollSpeed === 65} onPress={() => setScrollSpeed(65)} />
            </View>
            <View style={styles.chipsRow}>
              <Text style={styles.chipsLabel}>TEXT</Text>
              <Chip label="A" active={fontSize === 18} onPress={() => setFontSize(18)} />
              <Chip label="A+" active={fontSize === 22} onPress={() => setFontSize(22)} />
              <Chip label="A++" active={fontSize === 28} onPress={() => setFontSize(28)} />
            </View>
            <Pressable onPress={startCountdown} style={styles.recordBtn} testID="record-start">
              <View style={styles.recordCircle} />
              <Text style={styles.recordBtnT}>START RECORDING</Text>
            </Pressable>
          </>
        ) : null}

        {phase === "countdown" ? (
          <View style={styles.center}><Text style={styles.hint}>Get ready…</Text></View>
        ) : null}

        {phase === "recording" ? (
          <Pressable onPress={() => stopRecording(false)} style={styles.stopBtn} testID="record-stop">
            <Ionicons name="stop" size={20} color="#fff" />
            <Text style={styles.recordBtnT}>STOP · {fmt(elapsed)}</Text>
          </Pressable>
        ) : null}

        {phase === "preview" ? (
          <>
            <Text style={styles.previewLine}>Draft · {fmt(elapsed)} · {(post?.platform || "social").toUpperCase()}</Text>
            <View style={styles.previewActions}>
              <Pressable onPress={doRetake} style={styles.altBtn} testID="record-retake">
                <Ionicons name="refresh" size={16} color={theme.color.brand} />
                <Text style={styles.altBtnT}>RETAKE</Text>
              </Pressable>
              <Pressable onPress={() => doSaveDraft(false)} style={styles.secondaryBtn} testID="record-save-draft">
                <Ionicons name="save" size={16} color={theme.color.text} />
                <Text style={styles.secondaryBtnT}>SAVE DRAFT</Text>
              </Pressable>
              <Pressable onPress={() => doSaveDraft(true)} style={styles.primaryBtn} testID="record-send-subs">
                <Ionicons name="chatbubbles" size={16} color="#fff" />
                <Text style={styles.primaryBtnT}>SEND TO SUBTITLES</Text>
              </Pressable>
            </View>
          </>
        ) : null}

        {phase === "uploading" ? (
          <View style={styles.uploadingRow}>
            <ActivityIndicator color={theme.color.brand} />
            <Text style={styles.uploadingT}>Uploading… {Math.round(uploadPct * 100)}%</Text>
          </View>
        ) : null}
      </View>
    </SafeAreaView>
  );
}

// ---------- Small pieces ---------------------------------------------------

function Chip({ label, active, onPress }: { label: string; active: boolean; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={[styles.chip, active && styles.chipOn]}>
      <Text style={[styles.chipT, active && styles.chipTOn]}>{label}</Text>
    </Pressable>
  );
}

function pickMime(): string | null {
  if (typeof MediaRecorder === "undefined") return null;
  const candidates = [
    "video/mp4;codecs=h264,aac",
    "video/webm;codecs=vp9,opus",
    "video/webm;codecs=vp8,opus",
    "video/webm",
  ];
  for (const c of candidates) {
    // @ts-ignore
    if (MediaRecorder.isTypeSupported?.(c)) return c;
  }
  return null;
}

function fmt(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.max(0, Math.floor(sec % 60));
  return `${m}:${String(s).padStart(2, "0")}`;
}

// ---------- Styles ---------------------------------------------------------

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#000" },
  topBar: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 14, paddingVertical: 10, backgroundColor: theme.color.surface,
    borderBottomWidth: 1, borderBottomColor: theme.color.divider,
  },
  topTitle: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },

  // Camera stage — 9:16 vertical framing
  stage: { flex: 1, backgroundColor: "#000", position: "relative", overflow: "hidden" },
  cam: { flex: 1 },
  previewNative: { flex: 1, alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: theme.color.surface2 },
  previewNativeT: { color: theme.color.text, fontSize: 16, fontWeight: "800", letterSpacing: 1 },
  previewNativeSub: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 0.8, textAlign: "center", paddingHorizontal: 24 },

  // Teleprompter overlay
  telepromWrap: {
    position: "absolute", top: 24, left: 16, right: 16, bottom: 170,
    backgroundColor: "rgba(0,0,0,0.6)", borderRadius: 12, overflow: "hidden",
    borderWidth: 1, borderColor: "rgba(255,255,255,0.12)",
  },
  telepromScroll: { flex: 1 },
  telepromEyebrow: { color: theme.color.brand, fontSize: 9, fontWeight: "900", letterSpacing: 2, paddingHorizontal: 16, paddingTop: 10 },
  telepromT: { color: "#fff", fontWeight: "800", textShadowColor: "rgba(0,0,0,0.9)", textShadowRadius: 4 },

  overlay: { ...StyleSheet.absoluteFillObject, alignItems: "center", justifyContent: "center", backgroundColor: "rgba(0,0,0,0.55)" },
  countdownBig: { color: theme.color.brand, fontSize: 140, fontWeight: "900" },

  recPill: {
    position: "absolute", top: 12, left: 12, flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: "rgba(0,0,0,0.75)", paddingHorizontal: 10, paddingVertical: 6, borderRadius: 20,
  },
  recDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: theme.color.brand },
  recT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1 },

  // Bottom control bar
  bottom: {
    paddingHorizontal: 14, paddingTop: 10, paddingBottom: 14,
    backgroundColor: theme.color.surface, borderTopWidth: 1, borderTopColor: theme.color.divider,
    gap: 10,
  },
  chipsRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  chipsLabel: { color: theme.color.textDim, fontSize: 10, fontWeight: "900", letterSpacing: 1.5, width: 46 },
  chip: {
    paddingHorizontal: 12, paddingVertical: 7, borderRadius: 20,
    borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface2,
  },
  chipOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipT: { color: theme.color.text, fontSize: 10, fontWeight: "900", letterSpacing: 1 },
  chipTOn: { color: "#fff" },

  recordBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10,
    backgroundColor: theme.color.brand, paddingVertical: 15, borderRadius: 30,
    marginTop: 4,
  },
  recordCircle: { width: 16, height: 16, borderRadius: 8, backgroundColor: "#fff" },
  recordBtnT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 1.8 },

  stopBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10,
    backgroundColor: "#c94a4a", paddingVertical: 15, borderRadius: 30,
  },

  previewLine: { color: theme.color.textMuted, fontSize: 11, fontWeight: "800", letterSpacing: 1, textAlign: "center" },
  previewActions: { flexDirection: "row", flexWrap: "wrap", gap: 8, justifyContent: "center" },

  primaryBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: theme.color.brand, paddingHorizontal: 16, paddingVertical: 12, borderRadius: 10,
  },
  primaryBtnT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  secondaryBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: theme.color.surface2, paddingHorizontal: 16, paddingVertical: 12, borderRadius: 10,
    borderWidth: 1, borderColor: theme.color.border,
  },
  secondaryBtnT: { color: theme.color.text, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  altBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 16, paddingVertical: 12, borderRadius: 10,
    borderWidth: 1, borderColor: theme.color.brand, backgroundColor: theme.color.brandTint,
  },
  altBtnT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },

  uploadingRow: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10, paddingVertical: 14 },
  uploadingT: { color: theme.color.textMuted, fontSize: 12, fontWeight: "700", letterSpacing: 1 },

  // Permission screen
  permWrap: { flex: 1, padding: 24, alignItems: "center", justifyContent: "center", gap: 16 },
  permTitle: { color: theme.color.text, fontSize: 18, fontWeight: "900", letterSpacing: 0.5, textAlign: "center" },
  permBody: { color: theme.color.textMuted, fontSize: 13, lineHeight: 20, textAlign: "center", paddingHorizontal: 20 },

  hint: { color: theme.color.textMuted, fontSize: 12, letterSpacing: 1 },
});
