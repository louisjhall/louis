/**
 * VoiceRecorderOverlay — modal recorder for message voice notes.
 *
 * Uses expo-audio's recorder pipeline (not deprecated expo-av). Enforces
 * the 5-minute cap client-side; the backend also enforces it. Provides
 * cancel + preview + send.
 */
import React, { useEffect, useRef, useState } from "react";
import {
  View, Text, Pressable, StyleSheet, Modal, ActivityIndicator, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";
import {
  useAudioRecorder,
  useAudioRecorderState,
  useAudioPlayer,
  RecordingPresets,
  AudioModule,
  setAudioModeAsync,
} from "expo-audio";

const MAX_SECONDS = 5 * 60;

export type RecordedVoiceNote = {
  uri: string;
  mimeType: string;
  durationSeconds: number;
};

export function VoiceRecorderOverlay({
  visible,
  onCancel,
  onSend,
}: {
  visible: boolean;
  onCancel: () => void;
  onSend: (note: RecordedVoiceNote) => void;
}) {
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const recorderState = useAudioRecorderState(recorder);
  const [elapsed, setElapsed] = useState(0);
  const [preview, setPreview] = useState<RecordedVoiceNote | null>(null);
  const [permError, setPermError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const timerRef = useRef<any>(null);

  const player = useAudioPlayer(preview ? { uri: preview.uri } : null);

  // Request mic permission + start recording when the sheet opens.
  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    (async () => {
      try {
        const status = await AudioModule.requestRecordingPermissionsAsync();
        if (!status.granted) {
          setPermError(
            status.canAskAgain
              ? "Microphone access is needed to record a voice note."
              : "Microphone access is blocked. Enable it from Settings to send Louis a voice note.",
          );
          return;
        }
        await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
        if (cancelled) return;
        await recorder.prepareToRecordAsync();
        recorder.record();
        setElapsed(0);
        timerRef.current = setInterval(() => {
          setElapsed((e) => {
            if (e + 1 >= MAX_SECONDS) {
              // hit the cap — stop and go to preview
              clearInterval(timerRef.current);
              _stopAndPreview();
              return MAX_SECONDS;
            }
            return e + 1;
          });
        }, 1000);
      } catch (e: any) {
        setPermError("Couldn\u2019t start the recorder. " + (e?.message || ""));
      }
    })();
    return () => {
      cancelled = true;
      if (timerRef.current) clearInterval(timerRef.current);
      // If sheet closes without send, stop the mic + drop the temp file.
      try { recorder.stop(); } catch { /* ignore */ }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  const _stopAndPreview = async () => {
    try {
      setBusy(true);
      await recorder.stop();
      const uri = recorder.uri;
      if (!uri) throw new Error("no recording uri");
      // The high-quality preset produces .m4a on both platforms.
      setPreview({
        uri,
        mimeType: "audio/m4a",
        durationSeconds: Math.max(1, elapsed || 1),
      });
    } catch (e: any) {
      Alert.alert("Recording failed", e?.message || "Try again.");
    } finally {
      setBusy(false);
      if (timerRef.current) clearInterval(timerRef.current);
    }
  };

  const _cancel = async () => {
    if (timerRef.current) clearInterval(timerRef.current);
    try { if (recorderState.isRecording) await recorder.stop(); } catch {}
    setPreview(null);
    setElapsed(0);
    setPermError(null);
    onCancel();
  };

  const _send = () => {
    if (!preview) return;
    onSend(preview);
    setPreview(null);
    setElapsed(0);
  };

  const _togglePlayback = () => {
    if (!player) return;
    if (player.playing) player.pause();
    else player.play();
  };

  const mm = String(Math.floor(elapsed / 60)).padStart(2, "0");
  const ss = String(elapsed % 60).padStart(2, "0");

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={_cancel}>
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <View style={styles.grabber} />

          {permError ? (
            <>
              <Text style={styles.title}>Mic access needed</Text>
              <Text style={styles.copy}>{permError}</Text>
              <Pressable style={styles.primary} onPress={_cancel}>
                <Text style={styles.primaryText}>CLOSE</Text>
              </Pressable>
            </>
          ) : preview ? (
            <>
              <Text style={styles.title}>Voice note ready</Text>
              <Text style={styles.copy}>{preview.durationSeconds}s recorded · tap to preview</Text>
              <Pressable style={styles.previewBtn} onPress={_togglePlayback} testID="voice-preview-play">
                <Ionicons name={player?.playing ? "pause" : "play"} size={30} color="#fff" />
              </Pressable>
              <View style={styles.row}>
                <Pressable style={styles.secondary} onPress={_cancel} testID="voice-cancel">
                  <Text style={styles.secondaryText}>DISCARD</Text>
                </Pressable>
                <Pressable style={styles.primary} onPress={_send} testID="voice-send">
                  <Ionicons name="send" size={16} color="#fff" />
                  <Text style={styles.primaryText}>  SEND</Text>
                </Pressable>
              </View>
            </>
          ) : (
            <>
              <View style={styles.recordingDot} />
              <Text style={styles.timer}>{mm}:{ss}</Text>
              <Text style={styles.copy}>Recording… max 5 minutes.</Text>
              <View style={styles.row}>
                <Pressable style={styles.secondary} onPress={_cancel} testID="voice-cancel">
                  <Text style={styles.secondaryText}>CANCEL</Text>
                </Pressable>
                <Pressable style={styles.primary} onPress={_stopAndPreview} disabled={busy} testID="voice-stop">
                  {busy ? <ActivityIndicator color="#fff" /> : (
                    <>
                      <Ionicons name="stop" size={16} color="#fff" />
                      <Text style={styles.primaryText}>  STOP</Text>
                    </>
                  )}
                </Pressable>
              </View>
            </>
          )}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  sheet: {
    backgroundColor: theme.color.surface, borderTopLeftRadius: 22, borderTopRightRadius: 22,
    padding: 22, paddingTop: 12, alignItems: "center", gap: 12,
  },
  grabber: { width: 40, height: 4, borderRadius: 2, backgroundColor: theme.color.border, marginBottom: 6 },
  title: { color: theme.color.text, fontSize: 18, fontWeight: "900" },
  copy: { color: theme.color.textMuted, fontSize: 13, textAlign: "center" },
  recordingDot: { width: 14, height: 14, borderRadius: 7, backgroundColor: theme.color.brand, marginTop: 4 },
  timer: { color: theme.color.text, fontSize: 34, fontWeight: "900", letterSpacing: 3, marginTop: 4 },
  previewBtn: {
    backgroundColor: theme.color.brand, width: 64, height: 64, borderRadius: 32,
    alignItems: "center", justifyContent: "center", marginTop: 4,
  },
  row: { flexDirection: "row", gap: 10, marginTop: 12, width: "100%" },
  secondary: {
    flex: 1, paddingVertical: 12, borderRadius: 999, borderWidth: 1,
    borderColor: theme.color.border, alignItems: "center", justifyContent: "center",
  },
  secondaryText: { color: theme.color.text, fontWeight: "800", fontSize: 12, letterSpacing: 1.2 },
  primary: {
    flex: 1, paddingVertical: 12, borderRadius: 999, backgroundColor: theme.color.brand,
    alignItems: "center", justifyContent: "center", flexDirection: "row",
  },
  primaryText: { color: "#fff", fontWeight: "800", fontSize: 12, letterSpacing: 1.2 },
});
