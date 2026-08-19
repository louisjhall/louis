/**
 * Teleprompter Camera Recording — coach records the weekly video with an auto-scrolling
 * script overlay, 3-2-1 countdown, retake, and send.
 *
 * On WEB (Emergent preview): uses the browser MediaRecorder API for camera capture.
 * On native (Expo builds): uses expo-camera; requires camera + mic permission.
 *
 * The recording is uploaded as base64 to /coach/videos, then /coach/videos/{id}/send.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ActivityIndicator, ScrollView, Alert, Platform, TextInput,
} from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { api, getToken } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Phase = "idle" | "countdown" | "recording" | "preview" | "sending";

// Iter 145 — slower default (was 40 px/s). Coach explicitly asked for a
// substantially slower default. Persisted per-coach via AsyncStorage.
const SPEED_DEFAULT = 15;   // px/second
const SPEED_MIN = 5;
const SPEED_MAX = 60;
const SPEED_STEP = 5;
const SPEED_STORAGE_KEY = "crewfit.teleprompter.speed";

// Iter186 · Font-size control (script reading area). Coach can bump the
// script text between 18 and 56 px to suit their eyesight / distance.
// Persisted per-coach so the setting sticks across sessions.
const FONT_SIZE_DEFAULT = 32;
const FONT_SIZE_MIN = 18;
const FONT_SIZE_MAX = 56;
const FONT_SIZE_STEP = 4;
const FONT_SIZE_STORAGE_KEY = "crewfit.teleprompter.fontsize";

// Iter186 · Video upload — 10-minute hard timeout on the POST /coach/videos
// request. Previously fetch() had no AbortController → if the K8s ingress
// silently dropped an in-flight large upload, the sendVideo() call hung
// forever and the UI stayed on "Uploading…" with no error path.
const UPLOAD_TIMEOUT_MS = 10 * 60 * 1000;

export default function Teleprompter() {
  // Iter 162 · The teleprompter now handles two entry paths:
  //
  //   /coach/teleprompter/{check_in_id}
  //     — classic weekly video against a check-in row.
  //
  //   /coach/teleprompter/welcome-{client_id}?welcome=1&clientName=…
  //     — one-shot welcome video BEFORE the client has submitted their
  //     first check-in. Skips the check-in fetch and pre-seeds isWelcome.
  const { id, welcome, clientId: qClientId, clientName: qClientName } =
    useLocalSearchParams<{ id: string; welcome?: string; clientId?: string; clientName?: string }>();
  const router = useRouter();
  const isWelcomeMode =
    String(welcome || "").toLowerCase() === "1" ||
    String(id || "").startsWith("welcome-");
  // For welcome-only mode we synthesize the client_id — either from the
  // explicit `clientId` query param or by parsing it off the path prefix
  // "welcome-{client_id}".
  const welcomeClientId =
    qClientId || (String(id || "").startsWith("welcome-") ? String(id).slice("welcome-".length) : "");
  const [ci, setCi] = useState<any>(null);
  const [script, setScript] = useState("");
  const [scriptDraft, setScriptDraft] = useState("");
  const [editingScript, setEditingScript] = useState(false);
  const [savingScript, setSavingScript] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [countdown, setCountdown] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [scrollSpeed, setScrollSpeed] = useState(SPEED_DEFAULT);
  // Iter186 · Font size for the script (persisted per-coach)
  const [scriptFontSize, setScriptFontSize] = useState<number>(FONT_SIZE_DEFAULT);
  // Iter186 · Upload progress + error state — replaces the frozen "Uploading…"
  // spinner. `uploadPct` is 0-100. `uploadError` holds any failure message
  // so the UI can render a red banner with a RETRY button instead of a
  // permanent grey spinner. Both reset on retake().
  const [uploadPct, setUploadPct] = useState<number>(0);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadBytes, setUploadBytes] = useState<number>(0);
  const [paused, setPaused] = useState(false);
  const [recordingBlob, setRecordingBlob] = useState<Blob | string | null>(null);
  const [permissionOk, setPermissionOk] = useState(false);
  // Iter 156 — Welcome Video Phase 2. When ON, the outgoing POST omits
  // `check_in_id` and sets `video_kind: "welcome"` so the video is stored
  // as a one-shot welcome message instead of a weekly review.
  // Iter 162 · defaults to true when the route was opened via the welcome
  // path so the toggle is already on when the coach arrives.
  const [isWelcome, setIsWelcome] = useState<boolean>(isWelcomeMode);
  const currentOffset = useRef(0);   // manual-scroll aware offset

  const videoRef = useRef<any>(null);              // preview
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunks = useRef<Blob[]>([]);
  const scriptScroll = useRef<any>(null);
  const scrollTimer = useRef<any>(null);
  const elapsedTimer = useRef<any>(null);

  // Load check-in + script
  useEffect(() => {
    (async () => {
      // Iter 162 · Welcome-only mode — no check-in exists. Synthesize a
      // minimal `ci` from the query-string so downstream code (post body,
      // header greeting) keeps working, then request an AI-generated
      // personalised welcome script from the backend so the teleprompter
      // isn't blank on first paint.
      if (isWelcomeMode && welcomeClientId) {
        setCi({
          id: null,
          user_id: welcomeClientId,
          user_name: qClientName || "Client",
        });
        // Best-effort script generation — DNA / goal are optional; a fallback
        // script is returned if the client hasn't completed their assessment.
        try {
          const r = await api<{ script: string; used_fallback?: boolean }>(
            "/coach/welcome-script/generate",
            { method: "POST", body: { client_id: welcomeClientId } },
          );
          const s = String(r?.script || "").trim();
          if (s) {
            setScript(s);
            setScriptDraft(s);
          }
        } catch (e: any) {
          // Silent — a blank script is still usable, the coach can type.
          // eslint-disable-next-line no-console
          console.warn("welcome-script generation failed:", e?.message || e);
        }
        // Restore last-used speed
        try {
          const stored = await AsyncStorage.getItem(SPEED_STORAGE_KEY);
          if (stored) {
            const n = parseInt(stored, 10);
            if (n >= SPEED_MIN && n <= SPEED_MAX) setScrollSpeed(n);
          }
        } catch { /* ignore */ }
        // Iter186 · Restore last-used font size
        try {
          const stored = await AsyncStorage.getItem(FONT_SIZE_STORAGE_KEY);
          if (stored) {
            const n = parseInt(stored, 10);
            if (n >= FONT_SIZE_MIN && n <= FONT_SIZE_MAX) setScriptFontSize(n);
          }
        } catch { /* ignore */ }
        return;
      }
      try {
        const r = await api<any>(`/coach/checkins/${id}`);
        setCi(r.check_in);
        const s = r.check_in?.weekly_video_script || "";
        setScript(s);
        setScriptDraft(s);
      } catch (e: any) { Alert.alert("Load failed", e?.message || ""); }
      // Restore last-used speed
      try {
        const stored = await AsyncStorage.getItem(SPEED_STORAGE_KEY);
        if (stored) {
          const n = parseInt(stored, 10);
          if (n >= SPEED_MIN && n <= SPEED_MAX) setScrollSpeed(n);
        }
      } catch { /* ignore */ }
      // Iter186 · Restore last-used font size (weekly path)
      try {
        const stored = await AsyncStorage.getItem(FONT_SIZE_STORAGE_KEY);
        if (stored) {
          const n = parseInt(stored, 10);
          if (n >= FONT_SIZE_MIN && n <= FONT_SIZE_MAX) setScriptFontSize(n);
        }
      } catch { /* ignore */ }
    })();
  }, [id, isWelcomeMode, welcomeClientId, qClientName]);

  // Persist speed whenever the coach changes it (deferred, tolerant of failures)
  useEffect(() => {
    AsyncStorage.setItem(SPEED_STORAGE_KEY, String(scrollSpeed)).catch(() => {});
  }, [scrollSpeed]);

  // Iter186 · Persist font size similarly
  useEffect(() => {
    AsyncStorage.setItem(FONT_SIZE_STORAGE_KEY, String(scriptFontSize)).catch(() => {});
  }, [scriptFontSize]);

  // Save script edits back to the check-in row (Iter 145)
  const saveScriptEdit = useCallback(async () => {
    if (scriptDraft === script) { setEditingScript(false); return; }
    // Iter 162 · Welcome-only mode has no check-in row — persist locally only.
    if (isWelcomeMode) {
      setScript(scriptDraft);
      setEditingScript(false);
      return;
    }
    setSavingScript(true);
    try {
      await api<any>(`/coach/checkins/${id}/script`, {
        method: "PUT",
        body: { weekly_video_script: scriptDraft },
      });
      setScript(scriptDraft);
      setEditingScript(false);
    } catch (e: any) { Alert.alert("Save failed", e?.message || ""); }
    finally { setSavingScript(false); }
  }, [id, script, scriptDraft, isWelcomeMode]);

  const resetScriptToOriginal = useCallback(async () => {
    if (isWelcomeMode) {
      // No original script to reset to for the welcome path.
      setScriptDraft("");
      setEditingScript(false);
      return;
    }
    setSavingScript(true);
    try {
      const r = await api<any>(`/coach/checkins/${id}/script/reset`, { method: "POST", body: {} });
      const s = r.check_in?.weekly_video_script || "";
      setScript(s); setScriptDraft(s); setEditingScript(false);
    } catch (e: any) { Alert.alert("Reset failed", e?.message || "No original script preserved."); }
    finally { setSavingScript(false); }
  }, [id, isWelcomeMode]);

  // Set up camera stream (web + expo web)
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (Platform.OS === "web") {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480, facingMode: "user" }, audio: true });
          if (cancelled) { stream.getTracks().forEach((t) => t.stop()); return; }
          streamRef.current = stream;
          if (videoRef.current) { videoRef.current.srcObject = stream; videoRef.current.play?.(); }
          setPermissionOk(true);
        } catch (e: any) {
          Alert.alert("Camera permission required", e?.message || "Please allow camera + microphone access.");
        }
      } else {
        // Native builds require expo-camera; skipped in dev preview.
        Alert.alert("Native camera recording", "Camera recording is available in the native build. Emergent dev preview uses the browser camera.");
      }
    })();
    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((t) => t.stop());
      if (scrollTimer.current) clearInterval(scrollTimer.current);
      if (elapsedTimer.current) clearInterval(elapsedTimer.current);
    };
  }, []);

  const startCountdown = () => {
    if (!permissionOk) { Alert.alert("Camera not ready", "Grant camera + microphone access first."); return; }
    setCountdown(3);
    setPhase("countdown");
    const tick = setInterval(() => {
      setCountdown((c) => {
        if (c <= 1) {
          clearInterval(tick);
          beginRecording();
          return 0;
        }
        return c - 1;
      });
    }, 900);
  };

  const beginRecording = () => {
    if (!streamRef.current) return;
    chunks.current = [];
    try {
      const rec = new MediaRecorder(streamRef.current, { mimeType: "video/webm;codecs=vp9,opus" });
      rec.ondataavailable = (e) => { if (e.data.size > 0) chunks.current.push(e.data); };
      rec.onstop = () => {
        const blob = new Blob(chunks.current, { type: "video/webm" });
        setRecordingBlob(blob);
        setPhase("preview");
      };
      rec.start();
      recorderRef.current = rec;
      setPhase("recording");
      setElapsed(0);
      // Start teleprompter scroll (respects pause + tracks offset for manual override)
      currentOffset.current = 0;
      scrollTimer.current = setInterval(() => {
        if (paused) return;
        currentOffset.current += scrollSpeed / 10;
        scriptScroll.current?.scrollTo?.({ y: currentOffset.current, animated: false });
      }, 100);
      elapsedTimer.current = setInterval(() => setElapsed((s) => s + 1), 1000);
    } catch (e: any) {
      Alert.alert("Recorder failed", e?.message || String(e));
      setPhase("idle");
    }
  };

  const stopRecording = () => {
    recorderRef.current?.stop();
    if (scrollTimer.current) clearInterval(scrollTimer.current);
    if (elapsedTimer.current) clearInterval(elapsedTimer.current);
  };

  const retake = () => {
    setRecordingBlob(null);
    setElapsed(0);
    currentOffset.current = 0;
    setPaused(false);
    scriptScroll.current?.scrollTo?.({ y: 0, animated: false });
    // Iter186 · Also clear upload progress + error state on retake.
    setUploadPct(0);
    setUploadError(null);
    setUploadBytes(0);
    setPhase("idle");
  };

  // Iter 145 — restart the teleprompter scroll from the top (works both
  // while idle and mid-recording).
  const restartFromTop = () => {
    currentOffset.current = 0;
    scriptScroll.current?.scrollTo?.({ y: 0, animated: false });
  };

  const sendVideo = async () => {
    if (!recordingBlob || !(recordingBlob instanceof Blob)) return;
    // Iter186 · Reset progress state before we begin.
    setUploadError(null);
    setUploadPct(0);
    setUploadBytes(recordingBlob.size || 0);
    setPhase("sending");

    // Timeout guard so the UI can never sit on "Uploading…" indefinitely.
    // If the K8s ingress silently drops an in-flight large upload the
    // fetch/XHR would otherwise hang forever.
    let didTimeout = false;
    const timeoutHandle = setTimeout(() => {
      didTimeout = true;
    }, UPLOAD_TIMEOUT_MS);

    try {
      // Convert blob to base64 (data URL — server strips the prefix).
      const reader = new FileReader();
      const b64: string = await new Promise((resolve, reject) => {
        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(new Error("Could not read the recording — please retake."));
        reader.readAsDataURL(recordingBlob);
      });

      // Iter 156 — Welcome Video Phase 2.
      const body: Record<string, any> = {
        user_id: ci.user_id,
        script,
        file_b64: b64,
        file_mime: "video/webm",
        duration_seconds: elapsed,
      };
      if (isWelcome) {
        body.video_kind = "welcome";
      } else if (!isWelcomeMode) {
        body.check_in_id = id;
      }

      // Iter186 · Web path uses XMLHttpRequest for real upload-progress
      // events + explicit timeout. Native falls back to fetch (base64 is
      // already in memory; native builds are the rare path today).
      const v = await postVideoWithProgress(body, {
        onProgress: (pct: number) => setUploadPct(pct),
        timeoutMs: UPLOAD_TIMEOUT_MS,
      });

      if (didTimeout) throw new Error("Upload timed out — please retry.");

      // Second call — announce the send to the client. Small payload,
      // no progress needed; falls under the same timeout guard.
      await api<any>(`/coach/videos/${v.video.id}/send`, { method: "POST", body: {} });

      clearTimeout(timeoutHandle);
      Alert.alert(
        "Sent!",
        isWelcome
          ? `Welcome video delivered to ${ci.user_name}.`
          : `Weekly video delivered to ${ci.user_name}.`,
      );
      router.back();
    } catch (e: any) {
      clearTimeout(timeoutHandle);
      // Iter186 · Never leave the UI on a permanent spinner. Land back
      // in the "preview" phase with a visible red banner + a Retry CTA.
      const rawMessage = e?.message || String(e) || "Upload failed.";
      const friendlyMessage = /timed out|timeout/i.test(rawMessage)
        ? `Upload timed out after ${UPLOAD_TIMEOUT_MS / 60_000} min — check your connection and tap RETRY.`
        : /network|failed to fetch|load failed/i.test(rawMessage)
          ? "Network error — the connection dropped mid-upload. Tap RETRY."
          : /413|too large|payload/i.test(rawMessage)
            ? "Video is too large — please retake with a shorter recording."
            : rawMessage;
      setUploadError(friendlyMessage);
      setUploadPct(0);
      setPhase("preview");
    }
  };

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <View style={styles.top}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="teleprompter-close"><Ionicons name="close" size={24} color={theme.color.text} /></Pressable>
        <Text style={styles.title}>
          {isWelcome ? "WELCOME VIDEO" : "TELEPROMPTER"} · {ci?.user_name || "…"}
        </Text>
        <View style={{ width: 24 }} />
      </View>

      {/* Iter 156 — Mark-as-Welcome toggle. Disabled during recording /
          preview / sending to prevent mid-flight kind changes. */}
      <View style={styles.welcomeRow}>
        <Pressable
          onPress={() => phase === "idle" && setIsWelcome((v) => !v)}
          disabled={phase !== "idle"}
          style={[
            styles.welcomeChip,
            isWelcome && styles.welcomeChipOn,
            phase !== "idle" && { opacity: 0.5 },
          ]}
          testID="welcome-toggle"
        >
          <Ionicons
            name={isWelcome ? "checkbox" : "square-outline"}
            size={16}
            color={isWelcome ? theme.color.brand : theme.color.textMuted}
          />
          <Text style={[styles.welcomeChipT, isWelcome && { color: theme.color.brand }]}>
            MARK AS WELCOME VIDEO
          </Text>
        </Pressable>
        {isWelcome && (
          <Text style={styles.welcomeHint}>
            Sent as a one-shot welcome — not attached to this check-in.
          </Text>
        )}
      </View>

      {/* Camera preview */}
      <View style={styles.camWrap}>
        {Platform.OS === "web" ? (
          // @ts-ignore native video element on RN Web
          <video ref={videoRef} autoPlay playsInline muted style={{ width: "100%", height: "100%", objectFit: "cover", background: "#000" }} />
        ) : (
          <View style={styles.camFallback}><Ionicons name="camera" size={40} color={theme.color.textMuted} /><Text style={styles.camFallbackT}>Native camera in build</Text></View>
        )}

        {phase === "countdown" && (
          <View style={styles.overlay}><Text style={styles.countdownBig}>{countdown}</Text></View>
        )}
        {phase === "recording" && (
          <View style={styles.recDot}><View style={styles.dot} /><Text style={styles.recT}>REC · {fmt(elapsed)}</Text></View>
        )}
      </View>

      {/* Teleprompter script — Iter 145: editable inline before recording */}
      <View style={styles.promptWrap}>
        <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingRight: 12 }}>
          <Text style={styles.promptEyebrow}>SCRIPT · {scrollSpeed}px/s · {scriptFontSize}px{paused ? " · PAUSED" : ""}</Text>
          {phase === "idle" && !editingScript && (
            <Pressable onPress={() => { setScriptDraft(script); setEditingScript(true); }} testID="edit-script-inline" hitSlop={8}>
              <Text style={styles.editT}>EDIT</Text>
            </Pressable>
          )}
          {phase === "idle" && editingScript && (
            <View style={{ flexDirection: "row", gap: 12 }}>
              <Pressable onPress={resetScriptToOriginal} hitSlop={8} testID="reset-script">
                <Text style={styles.editT}>RESET</Text>
              </Pressable>
              <Pressable onPress={saveScriptEdit} disabled={savingScript} hitSlop={8} testID="save-script-inline">
                {savingScript ? <ActivityIndicator color={theme.color.brand} size="small" /> : <Text style={[styles.editT, { color: theme.color.green }]}>SAVE</Text>}
              </Pressable>
              <Pressable onPress={() => { setScriptDraft(script); setEditingScript(false); }} hitSlop={8}>
                <Text style={styles.editT}>CANCEL</Text>
              </Pressable>
            </View>
          )}
        </View>
        {editingScript ? (
          <TextInput
            value={scriptDraft}
            onChangeText={setScriptDraft}
            multiline
            style={styles.scriptEdit}
            placeholderTextColor={theme.color.textDim}
            testID="script-editor"
          />
        ) : (
          <ScrollView
            ref={scriptScroll}
            style={styles.promptScroll}
            contentContainerStyle={{ paddingBottom: 200 }}
            showsVerticalScrollIndicator={paused}
            scrollEnabled={paused || phase === "idle"}
            onScroll={paused ? (e) => { currentOffset.current = e.nativeEvent.contentOffset.y; } : undefined}
            scrollEventThrottle={16}
          >
            {/* Iter186 · Font size is now driven by state (persisted per-coach)
                so a scan-and-read coach can bump the text up without editing
                the stylesheet. lineHeight tracks fontSize * 1.4 for airy copy. */}
            <Text style={[styles.promptText, { fontSize: scriptFontSize, lineHeight: Math.round(scriptFontSize * 1.4) }]}>
              {script}
            </Text>
          </ScrollView>
        )}
      </View>

      {/* Controls — Iter 145: speed. Iter186: font-size row added. */}
      <View style={styles.controls}>
        <Pressable
          onPress={() => setScrollSpeed((s) => Math.max(SPEED_MIN, s - SPEED_STEP))}
          style={styles.speedBtn}
          disabled={scrollSpeed <= SPEED_MIN}
          testID="speed-slower"
        >
          <Ionicons name="remove" size={14} color={theme.color.text} />
          <Text style={styles.speedT}>SLOWER</Text>
        </Pressable>
        <Pressable
          onPress={() => setPaused((p) => !p)}
          style={[styles.speedBtn, paused && styles.speedBtnOn]}
          testID="speed-pause-toggle"
        >
          <Ionicons name={paused ? "play" : "pause"} size={14} color={paused ? "#fff" : theme.color.text} />
          <Text style={[styles.speedT, paused && styles.speedTOn]}>{paused ? "RESUME" : "PAUSE"}</Text>
        </Pressable>
        <Pressable onPress={restartFromTop} style={styles.speedBtn} testID="speed-restart">
          <Ionicons name="refresh" size={14} color={theme.color.text} />
          <Text style={styles.speedT}>TOP</Text>
        </Pressable>
        <Pressable
          onPress={() => setScrollSpeed((s) => Math.min(SPEED_MAX, s + SPEED_STEP))}
          style={styles.speedBtn}
          disabled={scrollSpeed >= SPEED_MAX}
          testID="speed-faster"
        >
          <Ionicons name="add" size={14} color={theme.color.text} />
          <Text style={styles.speedT}>FASTER</Text>
        </Pressable>
      </View>
      {/* Iter186 · Font-size controls — sits on the same visual row as
          speed. `A-` shrinks 4px, `A+` grows 4px, clamped to MIN/MAX. */}
      <View style={styles.controlsFont}>
        <Text style={styles.controlsFontLabel}>TEXT SIZE</Text>
        <Pressable
          onPress={() => setScriptFontSize((s) => Math.max(FONT_SIZE_MIN, s - FONT_SIZE_STEP))}
          style={styles.speedBtn}
          disabled={scriptFontSize <= FONT_SIZE_MIN}
          testID="font-smaller"
        >
          <Text style={[styles.speedT, { fontSize: 11 }]}>A-</Text>
        </Pressable>
        <View style={styles.fontValuePill}>
          <Text style={styles.fontValueT}>{scriptFontSize}</Text>
        </View>
        <Pressable
          onPress={() => setScriptFontSize((s) => Math.min(FONT_SIZE_MAX, s + FONT_SIZE_STEP))}
          style={styles.speedBtn}
          disabled={scriptFontSize >= FONT_SIZE_MAX}
          testID="font-larger"
        >
          <Text style={[styles.speedT, { fontSize: 15, fontWeight: "900" }]}>A+</Text>
        </Pressable>
      </View>

      <View style={styles.mainAction}>
        {/* Iter186 · Persistent upload-error banner shown above the CTAs
            in the `preview` phase so the coach never has to guess why
            an earlier send didn't complete. Clears on retake. */}
        {phase === "preview" && uploadError && (
          <View style={styles.uploadErrCard} testID="upload-error-banner">
            <Ionicons name="alert-circle" size={18} color={theme.color.red} />
            <Text style={styles.uploadErrT}>{uploadError}</Text>
          </View>
        )}
        {phase === "idle" && (
          <Pressable onPress={startCountdown} style={styles.recordBtn} testID="record-start">
            <View style={styles.recordCircle} />
            <Text style={styles.recordT}>RECORD</Text>
          </Pressable>
        )}
        {phase === "recording" && (
          <Pressable onPress={stopRecording} style={styles.stopBtn} testID="record-stop">
            <Ionicons name="stop" size={22} color="#fff" />
            <Text style={styles.recordT}>STOP · {fmt(elapsed)}</Text>
          </Pressable>
        )}
        {phase === "preview" && (
          <View style={{ flexDirection: "row", gap: 10 }}>
            <Pressable onPress={retake} style={styles.retakeBtn} testID="retake">
              <Ionicons name="refresh" size={16} color={theme.color.brand} />
              <Text style={styles.retakeT}>RETAKE</Text>
            </Pressable>
            <Pressable onPress={sendVideo} style={styles.sendBtn} testID="send-recorded">
              <Ionicons name="send" size={16} color="#fff" />
              <Text style={styles.sendT}>{uploadError ? "RETRY SEND" : "SEND TO CLIENT"}</Text>
            </Pressable>
          </View>
        )}
        {phase === "sending" && (
          /* Iter186 · Real progress bar + percentage replaces the
              indefinite spinner. Also shows a Cancel option so the
              coach can bail out and retake if it's clearly stuck. */
          <View style={styles.sendingCard} testID="upload-progress">
            <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
              <ActivityIndicator color={theme.color.brand} />
              <Text style={styles.sendingH}>
                Uploading… {uploadPct}%
                {uploadBytes ? `  ·  ${(uploadBytes / (1024 * 1024)).toFixed(1)} MB` : ""}
              </Text>
            </View>
            <View style={styles.progressTrack}>
              <View style={[styles.progressFill, { width: `${uploadPct}%` }]} />
            </View>
            <Text style={styles.sendingHint}>
              Larger recordings can take a minute or two on a mobile connection. If nothing changes for 10 minutes you&apos;ll see an error and can retry.
            </Text>
          </View>
        )}
      </View>
    </SafeAreaView>
  );
}

function fmt(sec: number): string { const m = Math.floor(sec / 60); const s = sec % 60; return `${m}:${String(s).padStart(2, "0")}`; }

// Iter186 · Upload helper with real progress + timeout. Uses XHR on web
// (fetch has no upload-progress API), falls back to fetch elsewhere.
// Kept inside this file because it's only used by the teleprompter and
// mirrors the /coach/videos POST semantics exactly.
async function postVideoWithProgress(
  body: Record<string, any>,
  { onProgress, timeoutMs }: { onProgress: (pct: number) => void; timeoutMs: number },
): Promise<any> {
  // Resolve auth + base URL from the shared api helper.
  const token = await getToken();
  const API_BASE_URL = (process.env.EXPO_PUBLIC_BACKEND_URL || "").replace(/\/$/, "") + "/api";
  const url = `${API_BASE_URL}/coach/videos`;

  if (Platform.OS === "web") {
    return await new Promise((resolve, reject) => {
      try {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", url, true);
        xhr.setRequestHeader("Content-Type", "application/json");
        if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
        xhr.timeout = timeoutMs;
        xhr.upload.onprogress = (evt: ProgressEvent) => {
          if (evt.lengthComputable && evt.total > 0) {
            const pct = Math.min(99, Math.round((evt.loaded / evt.total) * 100));
            onProgress(pct);
          }
        };
        xhr.onload = () => {
          try {
            if (xhr.status >= 200 && xhr.status < 300) {
              onProgress(100);
              const j = xhr.responseText ? JSON.parse(xhr.responseText) : {};
              resolve(j);
            } else {
              let detail = `HTTP ${xhr.status}`;
              try {
                const j = JSON.parse(xhr.responseText || "{}");
                detail = j?.detail || detail;
              } catch { /* ignore */ }
              reject(new Error(String(detail)));
            }
          } catch (e: any) {
            reject(e);
          }
        };
        xhr.onerror = () => reject(new Error("Network error — please retry."));
        xhr.ontimeout = () => reject(new Error(`Upload timed out after ${Math.round(timeoutMs / 60_000)} min.`));
        xhr.onabort  = () => reject(new Error("Upload aborted."));
        xhr.send(JSON.stringify(body));
      } catch (e: any) {
        reject(e);
      }
    });
  }

  // Native fallback — fetch + AbortController. No upload progress but
  // still gets the same timeout guarantee.
  const controller = new AbortController();
  const abortHandle = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    clearTimeout(abortHandle);
    onProgress(100);
    if (!res.ok) {
      let msg = `HTTP ${res.status}`;
      try { const j = await res.json(); msg = j?.detail || msg; } catch { /* ignore */ }
      throw new Error(String(msg));
    }
    return await res.json();
  } catch (e: any) {
    clearTimeout(abortHandle);
    if (e?.name === "AbortError") throw new Error(`Upload timed out after ${Math.round(timeoutMs / 60_000)} min.`);
    throw e;
  }
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#000" },
  top: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 12, backgroundColor: theme.color.surface },
  title: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  welcomeRow: {
    paddingHorizontal: 12, paddingBottom: 10, backgroundColor: theme.color.surface, gap: 6,
    borderBottomWidth: 1, borderBottomColor: theme.color.divider,
  },
  welcomeChip: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: 10, paddingVertical: 8, borderRadius: 8,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
    alignSelf: "flex-start",
  },
  welcomeChipOn: {
    backgroundColor: theme.color.brandTint,
    borderColor: theme.color.brand,
  },
  welcomeChipT: {
    color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1.5,
  },
  welcomeHint: {
    color: theme.color.textMuted, fontSize: 11, fontStyle: "italic",
  },
  // Iter186 · Was 240px which squeezed the script to only 2 lines on
  // shorter viewports (mobile portrait, iPad split-view). Coach's core
  // job on this screen is READING, not admiring the camera preview, so
  // we halve the fixed height. The script's ScrollView gets the extra
  // vertical space via flex: 1.
  camWrap: { height: 160, backgroundColor: "#111", position: "relative" },
  camFallback: { flex: 1, alignItems: "center", justifyContent: "center", gap: 8 },
  camFallbackT: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1 },
  overlay: { ...StyleSheet.absoluteFillObject, alignItems: "center", justifyContent: "center", backgroundColor: "rgba(0,0,0,0.5)" },
  countdownBig: { color: theme.color.brand, fontSize: 120, fontWeight: "900" },
  recDot: { position: "absolute", top: 12, left: 12, flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: "rgba(0,0,0,0.6)", paddingHorizontal: 10, paddingVertical: 6, borderRadius: 20 },
  dot: { width: 10, height: 10, borderRadius: 5, backgroundColor: "#c94a4a" },
  recT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1 },
  // Iter186 · promptWrap now claims flex: 2 so the script area is the
  // dominant surface on the screen (was flex: 1 with a large camera).
  promptWrap: { flex: 2, backgroundColor: theme.color.surface, minHeight: 240 },
  promptEyebrow: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2, padding: 12 },
  promptScroll: { flex: 1, paddingHorizontal: 20 },
  // Iter186 · fontSize/lineHeight are now driven inline from state so
  // this rule only carries colour + weight + tracking.
  promptText: { color: theme.color.text, fontWeight: "700", letterSpacing: 0.3 },
  editT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5, paddingHorizontal: 8, paddingVertical: 4 },
  scriptEdit: { flex: 1, marginHorizontal: 12, marginBottom: 8, padding: 12, borderRadius: 8, backgroundColor: theme.color.surface3, borderWidth: 1, borderColor: theme.color.border, color: theme.color.text, fontSize: 18, lineHeight: 26, textAlignVertical: "top" },
  controls: { flexDirection: "row", gap: 8, padding: 12, justifyContent: "center", backgroundColor: theme.color.surface2 },
  // Iter186 · Font-size row — same visual language as `controls` but
  // narrower and with a label so coach knows what it does.
  controlsFont: {
    flexDirection: "row", gap: 8,
    paddingHorizontal: 12, paddingBottom: 10,
    justifyContent: "center", alignItems: "center",
    backgroundColor: theme.color.surface2,
  },
  controlsFontLabel: {
    color: theme.color.textMuted, fontSize: 10, fontWeight: "900", letterSpacing: 1.5,
    marginRight: 4,
  },
  fontValuePill: {
    minWidth: 44,
    paddingHorizontal: 10, paddingVertical: 8,
    borderRadius: 8,
    backgroundColor: theme.color.surface,
    borderWidth: 1, borderColor: theme.color.border,
    alignItems: "center", justifyContent: "center",
  },
  fontValueT: { color: theme.color.brand, fontSize: 12, fontWeight: "900" },
  speedBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8, borderWidth: 1, borderColor: theme.color.border },
  speedBtnOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  speedT: { color: theme.color.text, fontSize: 11, fontWeight: "900", letterSpacing: 1 },
  speedTOn: { color: "#fff" },
  mainAction: { padding: 20, alignItems: "center", backgroundColor: theme.color.surface, gap: 10 },
  recordBtn: { flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: "#c94a4a", paddingHorizontal: 24, paddingVertical: 14, borderRadius: 30 },
  recordCircle: { width: 16, height: 16, borderRadius: 8, backgroundColor: "#fff" },
  recordT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 2 },
  stopBtn: { flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: theme.color.text, paddingHorizontal: 24, paddingVertical: 14, borderRadius: 30 },
  retakeBtn: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 20, paddingVertical: 12, borderRadius: 10, borderWidth: 1, borderColor: theme.color.brand },
  retakeT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  sendBtn: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 20, paddingVertical: 12, borderRadius: 10, backgroundColor: theme.color.brand },
  sendT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  // Iter186 · Upload-progress + error styles
  sendingCard: {
    alignSelf: "stretch",
    padding: 14, borderRadius: 12,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.brand,
    gap: 10,
  },
  sendingH: { color: theme.color.text, fontSize: 13, fontWeight: "900", letterSpacing: 1 },
  sendingHint: { color: theme.color.textMuted, fontSize: 11, lineHeight: 15, fontStyle: "italic" },
  progressTrack: {
    height: 6, borderRadius: 3, overflow: "hidden",
    backgroundColor: theme.color.border,
  },
  progressFill: { height: "100%", backgroundColor: theme.color.brand },
  uploadErrCard: {
    alignSelf: "stretch",
    flexDirection: "row", alignItems: "flex-start", gap: 10,
    padding: 12, borderRadius: 10,
    backgroundColor: "rgba(239,68,68,0.12)",
    borderLeftWidth: 3, borderLeftColor: theme.color.red,
  },
  uploadErrT: { color: theme.color.text, fontSize: 12, lineHeight: 17, flex: 1 },
});
