import { useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ScrollView, ActivityIndicator, Alert,
} from "react-native";
import * as ImagePicker from "expo-image-picker";
import * as DocumentPicker from "expo-document-picker";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

const STAGES = [
  { key: "uploading", label: "Uploading roster", copy: "Uploading your roster..." },
  { key: "reading", label: "Reading file", copy: "Reading your duty pattern..." },
  { key: "extracting", label: "Extracting duties", copy: "Extracting duties..." },
  { key: "detecting", label: "Detecting layovers", copy: "Detecting layovers and turnarounds..." },
  { key: "overlap", label: "Checking overlaps", copy: "Checking for roster overlaps..." },
  { key: "calendar", label: "Building calendar", copy: "Building your CrewFit calendar..." },
  { key: "generating", label: "Generating plan", copy: "Generating your personalised plan..." },
  { key: "coach", label: "Preparing coach review", copy: "Preparing coach review..." },
];

async function uriToBase64(uri: string): Promise<string> {
  const res = await fetch(uri);
  const blob = await res.blob();
  return await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const s = String(reader.result || "");
      const comma = s.indexOf(",");
      resolve(comma >= 0 ? s.slice(comma + 1) : s);
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

export default function RosterUpload() {
  const router = useRouter();
  const [job, setJob] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const pollRef = useRef<any>(null);

  useEffect(() => {
    // Resume any active in-progress job
    (async () => {
      try {
        const j = await api<any>(`/roster/jobs/active`);
        if (j && j.id) { setJob(j); startPolling(j.id); }
      } catch { /* ignore */ }
    })();
    return () => pollRef.current && clearInterval(pollRef.current);
  }, []);

  const startPolling = (jobId: string) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const j = await api<any>(`/roster/jobs/${jobId}`);
        setJob(j);
        if (j.status === "complete") {
          clearInterval(pollRef.current);
          setTimeout(() => router.replace("/(client)/calendar"), 800);
        }
        if (j.status === "failed" || j.status === "partial") {
          clearInterval(pollRef.current);
        }
      } catch (e: any) {
        setError(e?.message || "Failed to check status");
      }
    }, 2000);
  };

  const startJob = async (fileBase64: string, mimeType: string, filename: string) => {
    setStarting(true); setError(null);
    try {
      const res = await api<any>(`/roster/upload-and-generate`, {
        method: "POST",
        body: { file_base64: fileBase64, mime_type: mimeType, filename },
      });
      setJob({ id: res.job_id, status: "queued", stage: "uploading", progress: 1, message: "Uploading your roster..." });
      startPolling(res.job_id);
    } catch (e: any) {
      setError(e?.message || "Upload failed. Please try a different file.");
    } finally {
      setStarting(false);
    }
  };

  const pickImage = async () => {
    setError(null);
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) {
      Alert.alert("Permission needed", "Please allow photo library access to upload a roster image.");
      return;
    }
    const res = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ImagePicker.MediaTypeOptions.Images, base64: true, quality: 0.7 });
    if (res.canceled || !res.assets?.[0]?.base64) return;
    const a = res.assets[0];
    await startJob(a.base64!, a.mimeType || "image/jpeg", a.fileName || "roster.jpg");
  };
  const pickPdf = async () => {
    setError(null);
    const res = await DocumentPicker.getDocumentAsync({ type: "application/pdf", copyToCacheDirectory: true });
    if (res.canceled || !res.assets?.[0]) return;
    const a = res.assets[0];
    try {
      const b64 = await uriToBase64(a.uri);
      await startJob(b64, a.mimeType || "application/pdf", a.name || "roster.pdf");
    } catch (e: any) {
      setError(e?.message || "Could not read PDF");
    }
  };

  const retry = () => { setJob(null); setError(null); };
  const cancel = () => { pollRef.current && clearInterval(pollRef.current); setJob(null); };
  const leaveScreen = () => router.replace("/(client)/home");

  const active = job && (job.status === "queued" || job.status === "processing");
  const failed = job && (job.status === "failed" || job.status === "partial");
  const done = job && job.status === "complete";
  const currentStageIdx = STAGES.findIndex((s) => s.key === job?.stage);
  const progress = Math.max(0, Math.min(100, job?.progress || 0));

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} testID="ru-back"><Ionicons name="chevron-back" size={22} color={theme.color.text} /></Pressable>
        <Text style={styles.title}>UPLOAD ROSTER</Text>
        <View style={{ width: 22 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: 20, paddingBottom: 60 }}>
        {!job ? (
          <>
            <Text style={styles.subtitle}>Upload roster and CrewFit does the rest.</Text>
            <Text style={styles.helper}>PDF or photo of your roster — we parse it, build your calendar, and generate your training plan automatically.</Text>

            <Pressable testID="ru-pick-image" onPress={pickImage} disabled={starting} style={[styles.pickBtn, starting && { opacity: 0.5 }]}>
              <Ionicons name="image-outline" size={22} color={theme.color.brand} />
              <View style={{ flex: 1 }}>
                <Text style={styles.pickBtnTitle}>UPLOAD PHOTO</Text>
                <Text style={styles.pickBtnSub}>JPEG / PNG screenshot of your roster</Text>
              </View>
              <Ionicons name="chevron-forward" size={18} color={theme.color.textMuted} />
            </Pressable>

            <Pressable testID="ru-pick-pdf" onPress={pickPdf} disabled={starting} style={[styles.pickBtn, starting && { opacity: 0.5 }]}>
              <Ionicons name="document-text-outline" size={22} color={theme.color.brand} />
              <View style={{ flex: 1 }}>
                <Text style={styles.pickBtnTitle}>UPLOAD PDF</Text>
                <Text style={styles.pickBtnSub}>Full roster PDF export</Text>
              </View>
              <Ionicons name="chevron-forward" size={18} color={theme.color.textMuted} />
            </Pressable>

            {starting ? (
              <View style={{ marginTop: 20, alignItems: "center" }}>
                <ActivityIndicator color={theme.color.brand} />
                <Text style={styles.helper}>Starting upload...</Text>
              </View>
            ) : null}
            {error ? <Text style={styles.err}>{error}</Text> : null}
          </>
        ) : (
          <>
            <View style={styles.progressCard}>
              <View style={styles.progressHeader}>
                <ActivityIndicator size="large" color={theme.color.brand} animating={active} />
                <Text style={styles.progressTitle} testID="ru-progress-message">
                  {done ? "YOUR NEW PLAN IS READY" : failed ? "PROCESSING FAILED" : (job.message || "Processing...")}
                </Text>
                <Text style={styles.progressPct}>{progress}%</Text>
              </View>
              <View style={styles.progressBarWrap}>
                <View testID="ru-progress-bar" style={[styles.progressBarFill, {
                  width: `${progress}%`,
                  backgroundColor: failed ? theme.color.red : done ? theme.color.green : theme.color.brand,
                }]} />
              </View>
              <View style={{ gap: 8, marginTop: 16 }}>
                {STAGES.map((s, i) => {
                  const passed = currentStageIdx > i || done;
                  const current = currentStageIdx === i && active;
                  return (
                    <View key={s.key} style={styles.stageRow} testID={`ru-stage-${s.key}`}>
                      {passed ? (
                        <Ionicons name="checkmark-circle" size={16} color={theme.color.green} />
                      ) : current ? (
                        <ActivityIndicator size="small" color={theme.color.brand} />
                      ) : (
                        <Ionicons name="ellipse-outline" size={16} color={theme.color.textDim} />
                      )}
                      <Text style={[styles.stageLabel, (passed || current) && { color: theme.color.text }, current && { color: theme.color.brand, fontWeight: "800" }]}>{s.label}</Text>
                    </View>
                  );
                })}
              </View>
            </View>

            {failed && (
              <View style={styles.errCard}>
                <Ionicons name="alert-circle" size={18} color={theme.color.red} />
                <Text style={styles.errCardText}>{job.error || "We couldn't read this roster clearly. Please upload a clearer file or enter the details manually."}</Text>
              </View>
            )}

            <View style={{ flexDirection: "row", gap: 10, marginTop: 20 }}>
              {active && (
                <>
                  <Pressable testID="ru-leave" onPress={leaveScreen} style={[styles.actBtn, styles.actBtnGhost]}>
                    <Text style={styles.actBtnGhostText}>KEEP WORKING</Text>
                  </Pressable>
                  <Pressable testID="ru-cancel" onPress={cancel} style={[styles.actBtn, styles.actBtnGhost]}>
                    <Text style={styles.actBtnGhostText}>CANCEL</Text>
                  </Pressable>
                </>
              )}
              {(failed || done) && (
                <>
                  <Pressable testID="ru-retry" onPress={retry} style={[styles.actBtn, { backgroundColor: theme.color.brand }]}>
                    <Text style={styles.actBtnText}>{failed ? "TRY AGAIN" : "UPLOAD ANOTHER"}</Text>
                  </Pressable>
                  {done && (
                    <Pressable testID="ru-open-calendar" onPress={() => router.replace("/(client)/calendar")} style={[styles.actBtn, styles.actBtnGhost]}>
                      <Text style={styles.actBtnGhostText}>OPEN CALENDAR</Text>
                    </Pressable>
                  )}
                </>
              )}
            </View>

            {active && (
              <Text style={styles.leaveHint} testID="ru-leave-hint">
                You can leave this screen — we&apos;ll keep processing in the background and let you know when it&apos;s ready.
              </Text>
            )}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 16, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: theme.color.border },
  title: { color: theme.color.text, fontSize: 14, fontWeight: "800", letterSpacing: 2 },
  subtitle: { color: theme.color.text, fontSize: 20, fontWeight: "800", marginBottom: 6 },
  helper: { color: theme.color.textMuted, fontSize: 13, marginBottom: 20 },
  pickBtn: {
    flexDirection: "row", alignItems: "center", gap: 12,
    padding: 16, backgroundColor: theme.color.surface2, borderRadius: 10,
    borderWidth: 1, borderColor: theme.color.border, marginBottom: 10,
  },
  pickBtnTitle: { color: theme.color.text, fontSize: 13, fontWeight: "800", letterSpacing: 1.5 },
  pickBtnSub: { color: theme.color.textMuted, fontSize: 11, marginTop: 3 },
  err: { color: theme.color.red, marginTop: 20 },

  progressCard: { padding: 20, backgroundColor: theme.color.surface2, borderRadius: 12, borderWidth: 1, borderColor: theme.color.border },
  progressHeader: { alignItems: "center", gap: 10, marginBottom: 16 },
  progressTitle: { color: theme.color.text, fontSize: 14, fontWeight: "800", letterSpacing: 1.5, textAlign: "center" },
  progressPct: { color: theme.color.brand, fontSize: 34, fontWeight: "900" },
  progressBarWrap: { height: 8, borderRadius: 4, backgroundColor: theme.color.border, overflow: "hidden" },
  progressBarFill: { height: "100%", borderRadius: 4 },
  stageRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  stageLabel: { color: theme.color.textDim, fontSize: 13 },

  errCard: { flexDirection: "row", gap: 10, alignItems: "flex-start", padding: 14, backgroundColor: "rgba(239,68,68,0.12)", borderRadius: 10, borderLeftWidth: 3, borderLeftColor: theme.color.red, marginTop: 14 },
  errCardText: { color: theme.color.text, fontSize: 13, flex: 1, lineHeight: 18 },

  actBtn: { flex: 1, alignItems: "center", justifyContent: "center", paddingVertical: 14, borderRadius: 10 },
  actBtnGhost: { backgroundColor: "transparent", borderWidth: 1, borderColor: theme.color.brand },
  actBtnText: { color: "#fff", fontSize: 12, fontWeight: "800", letterSpacing: 1.5 },
  actBtnGhostText: { color: theme.color.brand, fontSize: 12, fontWeight: "800", letterSpacing: 1.5 },

  leaveHint: { color: theme.color.textMuted, fontSize: 12, marginTop: 14, textAlign: "center", fontStyle: "italic" },
});
