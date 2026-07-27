/**
 * CoachRosterUploadButton — Phase A · A2 (Iter 109)
 *
 * Renders an "UPLOAD ROSTER FOR CLIENT" button on the coach client
 * dashboard. Opens a document picker, uploads the file to
 *     POST /api/coach/clients/{clientId}/roster/upload-parse
 * polls the resulting job, then auto-confirms via
 *     POST /api/coach/clients/{clientId}/roster/pending/{rid}/confirm
 * and returns the client's dashboard to a clean state.
 *
 * Strictly Louis-branded copy — no "AI" / "generated" wording.
 */
import { useCallback, useRef, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ActivityIndicator, Modal, Platform,
} from "react-native";
import * as DocumentPicker from "expo-document-picker";
import * as FileSystem from "expo-file-system/legacy";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast as uxToast } from "@/src/lib/ux";

type JobState = {
  id: string;
  status?: string;
  stage?: string;
  progress?: number;
  message?: string;
  pending_roster_id?: string | null;
  roster_id?: string | null;
  error?: string | null;
};

async function uriToBase64(uri: string): Promise<string> {
  if (uri.startsWith("data:")) {
    const c = uri.indexOf(",");
    if (c >= 0) return uri.slice(c + 1);
  }
  if (Platform.OS === "web") {
    const res = await fetch(uri);
    const blob = await res.blob();
    return await new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onloadend = () => {
        const s = String(r.result || "");
        const c = s.indexOf(",");
        resolve(c >= 0 ? s.slice(c + 1) : s);
      };
      r.onerror = () => reject(r.error);
      r.readAsDataURL(blob);
    });
  }
  try {
    return await FileSystem.readAsStringAsync(uri, {
      encoding: FileSystem.EncodingType.Base64,
    });
  } catch {
    const tmp = `${FileSystem.cacheDirectory}coach_roster_${Date.now()}`;
    await FileSystem.copyAsync({ from: uri, to: tmp });
    return await FileSystem.readAsStringAsync(tmp, {
      encoding: FileSystem.EncodingType.Base64,
    });
  }
}

export function CoachRosterUploadButton({
  clientId,
  clientName,
  onComplete,
  compact = false,
}: {
  clientId: string;
  clientName?: string;
  onComplete?: () => void;
  compact?: boolean;
}) {
  const [job, setJob] = useState<JobState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);
  const pollRef = useRef<any>(null);

  const stopPoll = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const finish = useCallback((msg?: string) => {
    stopPoll();
    setBusy(false);
    setJob(null);
    setShowModal(false);
    if (msg) uxToast(msg, "success");
    onComplete?.();
  }, [onComplete, stopPoll]);

  const confirmPending = useCallback(async (rid: string) => {
    try {
      const r = await api<any>(
        `/coach/clients/${clientId}/roster/pending/${rid}/confirm`,
        { method: "POST", body: {} },
      );
      // Start polling the generation job so the coach sees progress.
      const jid = r?.job_id;
      if (!jid) {
        finish("Roster saved for " + (clientName || "client"));
        return;
      }
      setJob({ id: jid, status: "processing", stage: "generating", progress: 80, message: "Generating plan…" });
      pollRef.current = setInterval(async () => {
        try {
          const p = await api<any>(`/roster/jobs/${jid}`);
          setJob(p);
          if (p?.status === "complete") {
            finish("Plan ready for " + (clientName || "client"));
          } else if (p?.status === "failed") {
            stopPoll();
            setBusy(false);
            setError(p?.error || "Plan generation failed.");
          }
        } catch { /* ignore */ }
      }, 2500);
    } catch (e: any) {
      setError(e?.message || "Couldn't confirm roster.");
      setBusy(false);
    }
  }, [clientId, clientName, finish, stopPoll]);

  const startPoll = useCallback((jobId: string) => {
    stopPoll();
    pollRef.current = setInterval(async () => {
      try {
        const p = await api<any>(`/roster/jobs/${jobId}`);
        setJob(p);
        if (p?.status === "awaiting_confirmation" && p?.pending_roster_id) {
          stopPoll();
          // Auto-confirm on behalf of the client.
          await confirmPending(p.pending_roster_id);
        } else if (p?.status === "failed") {
          stopPoll();
          setBusy(false);
          setError(p?.error || "Roster couldn't be read. Try a clearer file.");
        } else if (p?.status === "complete") {
          finish("Roster saved for " + (clientName || "client"));
        }
      } catch { /* ignore, keep polling */ }
    }, 2000);
  }, [clientName, confirmPending, finish, stopPoll]);

  const pickAndUpload = useCallback(async () => {
    setError(null);
    setBusy(true);
    setShowModal(true);
    try {
      const res = await DocumentPicker.getDocumentAsync({
        type: ["application/pdf", "image/*"],
        copyToCacheDirectory: true,
        multiple: false,
      });
      if (res.canceled || !res.assets?.[0]) {
        setBusy(false);
        setShowModal(false);
        return;
      }
      const a = res.assets[0];
      const b64 = await uriToBase64(a.uri);
      const nameLower = (a.name || "").toLowerCase();
      const mime = a.mimeType
        || (nameLower.endsWith(".pdf") ? "application/pdf" : "image/jpeg");

      const r = await api<any>(
        `/coach/clients/${clientId}/roster/upload-parse`,
        {
          method: "POST",
          body: {
            file_base64: b64,
            mime_type: mime,
            filename: a.name || "roster",
          },
        },
      );
      if (!r?.job_id) throw new Error("No job id returned");
      setJob({ id: r.job_id, status: "queued", stage: "uploading", progress: 1, message: "Uploading roster…" });
      startPoll(r.job_id);
    } catch (e: any) {
      setError(e?.message || "Upload failed.");
      setBusy(false);
    }
  }, [clientId, startPoll]);

  const closeModal = useCallback(() => {
    stopPoll();
    setBusy(false);
    setJob(null);
    setError(null);
    setShowModal(false);
  }, [stopPoll]);

  return (
    <>
      <Pressable
        testID="coach-upload-roster-btn"
        onPress={pickAndUpload}
        disabled={busy}
        style={[
          compact ? styles.compactBtn : styles.btn,
          busy && { opacity: 0.6 },
        ]}
      >
        <Ionicons name="cloud-upload" size={compact ? 14 : 16} color="#fff" />
        <Text style={compact ? styles.compactBtnT : styles.btnT}>
          {compact ? "UPLOAD ROSTER" : "UPLOAD ROSTER FOR CLIENT"}
        </Text>
      </Pressable>

      <Modal
        visible={showModal}
        transparent
        animationType="fade"
        onRequestClose={closeModal}
      >
        <View style={styles.modalScrim}>
          <View style={styles.modalCard}>
            <View style={styles.modalHead}>
              <Ionicons name="cloud-upload" size={18} color={theme.color.brand} />
              <Text style={styles.modalTitle}>
                Uploading roster{clientName ? ` for ${clientName}` : ""}
              </Text>
              <Pressable onPress={closeModal} hitSlop={10} testID="coach-upload-close">
                <Ionicons name="close" size={20} color={theme.color.textMuted} />
              </Pressable>
            </View>

            {error ? (
              <View style={styles.errBox}>
                <Ionicons name="alert-circle" size={16} color="#c85450" />
                <Text style={styles.errT}>{error}</Text>
              </View>
            ) : (
              <View style={styles.progressBox}>
                <ActivityIndicator color={theme.color.brand} />
                <Text style={styles.progressT}>
                  {job?.message || "Preparing…"}
                </Text>
                {typeof job?.progress === "number" ? (
                  <View style={styles.barOuter}>
                    <View style={[styles.barInner, { width: `${Math.max(4, Math.min(100, job.progress))}%` }]} />
                  </View>
                ) : null}
                <Text style={styles.progressSub}>
                  {job?.stage ? job.stage.toUpperCase() : ""}
                </Text>
              </View>
            )}

            <Pressable style={styles.modalBtn} onPress={closeModal} testID="coach-upload-dismiss">
              <Text style={styles.modalBtnT}>{error ? "CLOSE" : "HIDE"}</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  btn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 8,
    backgroundColor: "#4a90e2",
  },
  btnT: {
    color: "#fff",
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 0.5,
  },
  compactBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 6,
    borderRadius: 6,
    backgroundColor: "#4a90e2",
  },
  compactBtnT: {
    color: "#fff",
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.4,
  },
  modalScrim: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.55)",
    alignItems: "center",
    justifyContent: "center",
    padding: 20,
  },
  modalCard: {
    width: "100%",
    maxWidth: 380,
    backgroundColor: theme.color.surface,
    borderRadius: 12,
    padding: 16,
  },
  modalHead: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginBottom: 12,
  },
  modalTitle: {
    flex: 1,
    color: theme.color.text,
    fontSize: 14,
    fontWeight: "700",
  },
  progressBox: {
    alignItems: "center",
    paddingVertical: 12,
    gap: 10,
  },
  progressT: {
    color: theme.color.text,
    fontSize: 13,
    textAlign: "center",
    paddingHorizontal: 12,
  },
  progressSub: {
    color: theme.color.textMuted,
    fontSize: 10,
    fontWeight: "600",
    letterSpacing: 0.6,
  },
  barOuter: {
    width: "80%",
    height: 6,
    backgroundColor: theme.color.surface2,
    borderRadius: 3,
    overflow: "hidden",
  },
  barInner: {
    height: "100%",
    backgroundColor: theme.color.brand,
    borderRadius: 3,
  },
  errBox: {
    flexDirection: "row",
    gap: 8,
    padding: 12,
    borderRadius: 8,
    backgroundColor: "rgba(200,84,80,0.1)",
    borderWidth: 1,
    borderColor: "rgba(200,84,80,0.4)",
    marginBottom: 12,
  },
  errT: {
    flex: 1,
    color: theme.color.text,
    fontSize: 12,
    lineHeight: 17,
  },
  modalBtn: {
    marginTop: 8,
    alignItems: "center",
    paddingVertical: 10,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: theme.color.border,
  },
  modalBtnT: {
    color: theme.color.text,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 0.6,
  },
});
