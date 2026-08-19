import { useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ScrollView, ActivityIndicator, Alert,
  Platform, Linking,
} from "react-native";
import * as ImagePicker from "expo-image-picker";
import * as DocumentPicker from "expo-document-picker";
// Iter 95e — use the legacy File System API (readAsStringAsync + EncodingType
// live under `expo-file-system/legacy` in v19+; still fully supported).
import * as FileSystem from "expo-file-system/legacy";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { PUBLIC_URLS } from "@/src/lib/publicUrls";

const STAGES = [
  { key: "uploading", label: "Uploading roster", copy: "Uploading your roster..." },
  { key: "reading", label: "Reading file", copy: "Reading your duty pattern..." },
  { key: "extracting", label: "Extracting duties", copy: "Extracting duties..." },
  { key: "detecting", label: "Detecting layovers", copy: "Detecting layovers and turnarounds..." },
  { key: "ready_to_confirm", label: "Review your roster", copy: "Ready to review — confirm your duty pattern next." },
  { key: "overlap", label: "Checking overlaps", copy: "Checking for roster overlaps..." },
  { key: "calendar", label: "Reading your roster", copy: "Reading your roster..." },
  { key: "generating", label: "Louis is looking over your week", copy: "Louis is looking over your week..." },
  { key: "coach", label: "Louis is finalising your programme", copy: "Louis is finalising your programme..." },
];

// If we see no progress movement for this many milliseconds, warn the user.
const SLOW_MS = 90_000;
// If we see no movement for this many milliseconds, offer recovery actions.
const STUCK_MS = 210_000;

/**
 * Cross-platform "URI → base64" — Iter 95e regression fix.
 *
 * Previous version used `fetch(uri) → blob → FileReader.readAsDataURL()`,
 * which works on the web preview but fails on native RN with `file://` and
 * `content://` URIs — the exact scheme `expo-document-picker` returns on
 * device. That's why roster upload silently died in Expo mobile testing.
 *
 * We now branch:
 *   - web  → keep the fetch/FileReader flow (blob:/data: URIs are supported).
 *   - native → use `expo-file-system`, which reads any file URI reliably.
 */
async function uriToBase64(uri: string): Promise<string> {
  // Data URIs — already base64.
  if (uri.startsWith("data:")) {
    const comma = uri.indexOf(",");
    if (comma >= 0) return uri.slice(comma + 1);
  }

  if (Platform.OS === "web") {
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

  // Native (iOS/Android) — expo-file-system reliably handles file:// and content://.
  try {
    return await FileSystem.readAsStringAsync(uri, {
      encoding: FileSystem.EncodingType.Base64,
    });
  } catch {
    // Some Android content:// URIs need copying to cache first.
    const tmp = `${FileSystem.cacheDirectory}roster_${Date.now()}`;
    await FileSystem.copyAsync({ from: uri, to: tmp });
    return await FileSystem.readAsStringAsync(tmp, {
      encoding: FileSystem.EncodingType.Base64,
    });
  }
}

export default function RosterUpload() {
  const router = useRouter();
  const [job, setJob] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [slowness, setSlowness] = useState<"none" | "slow" | "stuck">("none");
  // Multi-file upload staging area.
  const [multiFiles, setMultiFiles] = useState<
    { base64: string; mime: string; filename: string }[]
  >([]);
  const [mergeAsOne, setMergeAsOne] = useState(true);
  const pollRef = useRef<any>(null);
  const lastMoveRef = useRef<{ progress: number; at: number }>({ progress: 0, at: Date.now() });

  // Iter186 · Client-facing lock state — computed server-side by the new
  // /roster/submission-state endpoint. Any state other than
  // `none | coach_rejected` renders the SubmittedLockCard instead of
  // the upload buttons so the client can't reset their own submission
  // between the moment they confirm duties and the moment the coach
  // approves (or the 24-h auto-approve tick fires).
  const [submission, setSubmission] = useState<{
    state: string;
    submitted_at?: string;
    coach_review_at?: string;
    coach_review_actor?: string;
    roster_id?: string;
    pending_roster_id?: string;
    job_id?: string;
    legacy_backfill?: boolean;
  } | null>(null);
  const [subLoading, setSubLoading] = useState(true);

  const reloadSubmission = async () => {
    try {
      const s = await api<any>("/roster/submission-state");
      setSubmission(s);
    } catch {
      // Silently swallow — if the endpoint is temporarily unreachable
      // we default to the upload UI (matches pre-Iter186 behaviour).
      setSubmission({ state: "none" });
    } finally {
      setSubLoading(false);
    }
  };

  useEffect(() => {
    (async () => {
      // Iter186 · Submission-state gate MUST run before the legacy job
      // check — if a roster is awaiting coach review, we short-circuit
      // the entire upload UI and render the lock card.
      await reloadSubmission();
      try {
        const j = await api<any>(`/roster/jobs/active`);
        if (j && j.id) { setJob(j); startPolling(j.id); }
      } catch { /* ignore */ }
    })();
    return () => pollRef.current && clearInterval(pollRef.current);
  }, []);

  const startPolling = (jobId: string) => {
    if (pollRef.current) clearInterval(pollRef.current);
    lastMoveRef.current = { progress: 0, at: Date.now() };
    setSlowness("none");
    pollRef.current = setInterval(async () => {
      try {
        const j = await api<any>(`/roster/jobs/${jobId}`);
        setJob(j);
        const p = Number(j?.progress || 0);
        const now = Date.now();
        if (p > lastMoveRef.current.progress) {
          lastMoveRef.current = { progress: p, at: now };
          setSlowness("none");
        } else {
          const stillFor = now - lastMoveRef.current.at;
          if (stillFor > STUCK_MS) setSlowness("stuck");
          else if (stillFor > SLOW_MS) setSlowness("slow");
        }
        if (j.status === "awaiting_confirmation" && j.pending_roster_id) {
          clearInterval(pollRef.current);
          // Iter186 · Refresh submission-state so the lock screen owns
          // the flow — it will now offer a "REVIEW DUTIES" primary CTA
          // rather than us silently auto-navigating, which was the root
          // cause of the bounce-loop when clients pressed Back.
          await reloadSubmission();
          return;
        }
        if (j.status === "complete") {
          clearInterval(pollRef.current);
          // Iter188 · The completion of the confirm_build job does NOT
          // mean the plan is ready — in MANUAL_MODE the roster is now
          // sitting in the coach's approval inbox (`awaiting_review`).
          // The old success card ("YOUR NEW PLAN IS READY") was flat-out
          // wrong here. Redirect straight to the dedicated
          // `/roster/received` screen so the client sees the correct
          // "Coach is reviewing your programme" message.
          //
          // We check submission state first so a legacy non-manual-mode
          // path (where the plan really IS ready) still lands on the
          // calendar via `reloadSubmission` → RosterSubmittedLockScreen.
          try {
            const s = await api<any>("/roster/submission-state");
            if (s?.state === "awaiting_coach_review" || s?.state === "coach_approved") {
              router.replace("/roster/received");
              return;
            }
          } catch { /* fall through to legacy behaviour */ }
          // Legacy behaviour — refresh submission-state so the lock
          // screen owns the flow.
          await reloadSubmission();
        }
        if (j.status === "failed" || j.status === "partial" || j.status === "needs_review") {
          clearInterval(pollRef.current);
          // Iter 157 — False-failure guard.
          // The backend watchdog CAN still stamp `failed` on jobs whose
          // worker was interrupted between the roster insert and the
          // final status transition (very rare after the guards added in
          // this iter, but not impossible). Before showing the red error
          // banner, check `/roster/current`. If the user actually has an
          // active roster (recently confirmed), the job's "failed" flag
          // is stale — flip the UI to success and stop polling.
          if (j.status === "failed") {
            try {
              const cur = await api<any>("/roster/current");
              const active = cur?.roster;
              const activeCreatedAt = active?.created_at || active?.updated_at;
              // Consider it a false-failure if there is any active roster
              // and it was created/updated within the last hour (i.e. this
              // upload session, not an older roster from last week).
              const isRecent =
                !!activeCreatedAt &&
                (Date.now() - new Date(activeCreatedAt).getTime() < 60 * 60 * 1000);
              if (active?.id && isRecent) {
                setJob((prev: any) => ({
                  ...(prev || {}),
                  status: "complete",
                  progress: 100,
                  message: "Roster ready — you can open your calendar.",
                  error: null,
                  interrupted_by: null,
                  _false_failure_recovered: true,
                }));
                return;
              }
            } catch { /* silent — if /roster/current fails we fall through to showing the error */ }
          }
        }
      } catch (e: any) {
        setError(e?.message || "Failed to check status");
      }
    }, 2000);
  };

  const startJob = async (fileBase64: string, mimeType: string, filename: string) => {
    setStarting(true); setError(null);
    try {
      const res = await api<any>(`/roster/upload-parse`, {
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
    const res = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      base64: true,
      quality: 0.7,
      allowsMultipleSelection: true,
      selectionLimit: 12,
    });
    if (res.canceled || !res.assets?.length) return;

    // Single image → keep the existing single-file path.
    if (res.assets.length === 1) {
      const a = res.assets[0];
      if (!a.base64) return;
      await startJob(a.base64, a.mimeType || "image/jpeg", a.fileName || "roster.jpg");
      return;
    }

    // Multi-image → stage for review before upload.
    const staged = res.assets
      .filter((a) => !!a.base64)
      .map((a, i) => ({
        base64: a.base64!,
        mime: a.mimeType || "image/jpeg",
        filename: a.fileName || `roster_${i + 1}.jpg`,
      }));
    setMultiFiles(staged);
    setMergeAsOne(true);
  };
  const pickPdf = async () => {
    setError(null);
    const res = await DocumentPicker.getDocumentAsync({
      type: ["application/pdf", "image/*"],
      copyToCacheDirectory: true,
      multiple: true,
    });
    if (res.canceled || !res.assets?.length) return;

    // Single file → keep the existing single-file path.
    if (res.assets.length === 1) {
      const a = res.assets[0];
      try {
        const b64 = await uriToBase64(a.uri);
        const mime = a.mimeType || (a.name?.toLowerCase().endsWith(".pdf") ? "application/pdf" : "image/jpeg");
        await startJob(b64, mime, a.name || (mime === "application/pdf" ? "roster.pdf" : "roster.jpg"));
      } catch (e: any) {
        setError(e?.message || "Could not read that file. Try a different one.");
      }
      return;
    }

    // Multi-file → stage for review.
    try {
      const staged = await Promise.all(
        res.assets.slice(0, 12).map(async (a, i) => {
          const b64 = await uriToBase64(a.uri);
          const nameLower = (a.name || "").toLowerCase();
          const mime = a.mimeType
            || (nameLower.endsWith(".pdf") ? "application/pdf"
            : nameLower.endsWith(".png") ? "image/png"
            : "image/jpeg");
          return { base64: b64, mime, filename: a.name || `roster_${i + 1}` };
        })
      );
      setMultiFiles(staged);
      // Default merge=OFF when several PDFs (usually separate months) — heuristic.
      const pdfCount = staged.filter((s) => s.mime === "application/pdf").length;
      setMergeAsOne(!(pdfCount >= 2 && staged.length >= 2));
    } catch (e: any) {
      setError(e?.message || "Could not read one of those files. Try again.");
    }
  };
  // Iter 94h — full "browse anywhere" escape hatch. Uses `type: "*/*"` which on
  // Android forces the system SAF picker to expose the ☰ menu with Downloads,
  // Documents, OneDrive, Google Drive, phone storage, etc. — instead of only
  // showing PDF-source apps' shortcuts. Fixes the "it only lets me open from
  // other apps" complaint.
  const pickAnyFile = async () => {
    setError(null);
    try {
      const res = await DocumentPicker.getDocumentAsync({
        type: "*/*",
        copyToCacheDirectory: true,
        multiple: false,
      });
      if (res.canceled || !res.assets?.[0]) return;
      const a = res.assets[0];
      const nameLower = (a.name || "").toLowerCase();
      const mime = a.mimeType
        || (nameLower.endsWith(".pdf") ? "application/pdf"
        : nameLower.endsWith(".png") ? "image/png"
        : nameLower.endsWith(".jpg") || nameLower.endsWith(".jpeg") ? "image/jpeg"
        : "");
      if (!mime.startsWith("image/") && mime !== "application/pdf") {
        setError(`We can only read PDFs and photos of your roster. "${a.name || "This file"}" isn't supported — try exporting your roster as a PDF or taking a screenshot.`);
        return;
      }
      const b64 = await uriToBase64(a.uri);
      await startJob(b64, mime, a.name || "roster");
    } catch (e: any) {
      setError(e?.message || "Could not read that file. Try a different one.");
    }
  };

  const startFresh = () => { setJob(null); setError(null); setSlowness("none"); setMultiFiles([]); };

  const removeMultiFile = (idx: number) => {
    setMultiFiles((files) => files.filter((_, i) => i !== idx));
  };

  const submitMulti = async () => {
    if (!multiFiles.length) return;
    setStarting(true);
    setError(null);
    try {
      const res = await api<any>(`/roster/upload-parse-multi`, {
        method: "POST",
        body: {
          files: multiFiles.map((f) => ({
            file_base64: f.base64,
            mime_type: f.mime,
            filename: f.filename,
          })),
          merge_as_one: mergeAsOne,
        },
      });
      const primary = res?.job_id || res?.first_job_id;
      if (!primary) throw new Error("No job id returned");
      setJob({
        id: primary,
        status: "queued",
        stage: "uploading",
        progress: 1,
        message: mergeAsOne
          ? `Uploading ${multiFiles.length} page(s)...`
          : `Uploading ${multiFiles.length} rosters...`,
      });
      setMultiFiles([]);
      startPolling(primary);
    } catch (e: any) {
      setError(e?.message || "Upload failed. Please try again with fewer files.");
    } finally {
      setStarting(false);
    }
  };

  const retryPlanGeneration = async () => {
    if (!job?.id) return;
    setRetrying(true);
    try {
      await api(`/roster/jobs/${job.id}/retry`, { method: "POST" });
      setSlowness("none");
      startPolling(job.id);
    } catch (e: any) {
      Alert.alert("Retry failed", e?.message || "Please try uploading again.");
    } finally {
      setRetrying(false);
    }
  };

  const messageLouis = () => {
    // Message screen picks up the optional draft via query param.
    router.push({
      pathname: "/(client)/messages",
      params: {
        draft: "Hi Louis, my roster uploaded but I haven't seen my week yet. Can you take a look?",
      },
    });
  };

  const cancelWithConfirm = () => {
    Alert.alert(
      "Stop this upload?",
      "Your uploaded roster can be kept, but the plan may not be created yet.",
      [
        { text: "Continue waiting", style: "cancel" },
        { text: "Keep roster and exit", onPress: () => { pollRef.current && clearInterval(pollRef.current); router.replace("/(client)/home"); } },
        { text: "Stop upload", style: "destructive", onPress: () => { pollRef.current && clearInterval(pollRef.current); setJob(null); } },
      ],
    );
  };

  const leaveScreen = () => router.replace("/(client)/home");

  const active = job && (job.status === "queued" || job.status === "processing");
  const failed = job && job.status === "failed";
  const needsReview = job && job.status === "needs_review";
  const partial = job && job.status === "partial";
  const done = job && job.status === "complete";
  const currentStageIdx = STAGES.findIndex((s) => s.key === job?.stage);
  const progress = Math.max(0, Math.min(100, job?.progress || 0));

  // Iter186 · Compute lock — anything other than `none | coach_rejected`
  // means the client has already submitted and is either mid-processing
  // or waiting for the coach. Show the lock card, NOT the upload UI.
  const lockedStates = new Set([
    "awaiting_client_confirmation",
    "awaiting_coach_review",
    "coach_approved",
  ]);
  const isLocked = !!submission && lockedStates.has(submission.state);

  // While the state is loading (very first paint) show a plain spinner
  // so the upload buttons don't flash before the lock card takes over.
  if (subLoading) {
    return (
      <SafeAreaView style={styles.root} edges={["top"]}>
        <View style={styles.header}>
          <Text style={styles.title}>UPLOAD ROSTER</Text>
        </View>
        <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
          <ActivityIndicator color={theme.color.brand} />
        </View>
      </SafeAreaView>
    );
  }

  if (isLocked && submission) {
    return (
      <RosterSubmittedLockScreen
        submission={submission}
        onBackHome={() => router.replace("/(client)/home")}
        onOpenConfirm={
          submission.state === "awaiting_client_confirmation" && submission.pending_roster_id
            ? () => router.replace({
                pathname: "/roster/confirm/[id]" as any,
                params: { id: submission.pending_roster_id! },
              } as any)
            : undefined
        }
      />
    );
  }

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} testID="ru-back"><Ionicons name="chevron-back" size={22} color={theme.color.text} /></Pressable>
        <View style={{ alignItems: "center" }}>
          <Text style={styles.title}>UPLOAD ROSTER</Text>
          {/* Iter188 · OTA build marker — matches the video screen's
              `b188` tag. If this shows on production, you're on the new
              bundle. */}
          <Text style={{
            color: theme.color.textMuted, fontSize: 9, fontWeight: "700",
            letterSpacing: 1.2, marginTop: 2, opacity: 0.55,
          }} testID="ru-build-tag">b188</Text>
        </View>
        <View style={{ width: 22 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: 20, paddingBottom: 60 }}>
        {!job ? (
          <>
            <Text style={styles.subtitle}>Upload roster and CrewFit does the rest.</Text>
            <Text style={styles.helper}>PDF or photo of your roster — Louis reads it and plans your training around your flights and layovers.</Text>

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

            <Pressable testID="ru-pick-any" onPress={pickAnyFile} disabled={starting} style={[styles.pickBtn, starting && { opacity: 0.5 }]}>
              <Ionicons name="folder-open-outline" size={22} color={theme.color.brand} />
              <View style={{ flex: 1 }}>
                <Text style={styles.pickBtnTitle}>BROWSE FILES</Text>
                <Text style={styles.pickBtnSub}>Pick from Downloads, Documents, Drive, OneDrive…</Text>
              </View>
              <Ionicons name="chevron-forward" size={18} color={theme.color.textMuted} />
            </Pressable>

            <Text style={styles.browseTip} testID="ru-browse-tip">
              On Android, tap the <Text style={{ fontWeight: "800" }}>☰</Text> menu at the top-left of the file picker to browse your phone storage, Downloads or any cloud drive.
            </Text>
            <Text style={[styles.browseTip, { marginTop: 6 }]}>
              Have multiple pages or multiple months? Pick them all — you&apos;ll get to say whether they&apos;re one roster or separate.
            </Text>

            {/* Multi-file staging area — appears after selecting 2+ files. */}
            {multiFiles.length > 0 ? (
              <View style={styles.multiCard} testID="ru-multi-stage">
                <Text style={styles.multiTitle}>{multiFiles.length} FILES SELECTED</Text>

                <View style={styles.mergeToggleRow}>
                  <Pressable
                    onPress={() => setMergeAsOne(true)}
                    style={[styles.mergeToggle, mergeAsOne && styles.mergeToggleOn]}
                    testID="ru-merge-one"
                  >
                    <Ionicons name="albums" size={14} color={mergeAsOne ? "#fff" : theme.color.brand} />
                    <Text style={[styles.mergeToggleT, mergeAsOne && { color: "#fff" }]}>
                      ONE ROSTER (pages)
                    </Text>
                  </Pressable>
                  <Pressable
                    onPress={() => setMergeAsOne(false)}
                    style={[styles.mergeToggle, !mergeAsOne && styles.mergeToggleOn]}
                    testID="ru-merge-many"
                  >
                    <Ionicons name="documents" size={14} color={!mergeAsOne ? "#fff" : theme.color.brand} />
                    <Text style={[styles.mergeToggleT, !mergeAsOne && { color: "#fff" }]}>
                      SEPARATE ROSTERS
                    </Text>
                  </Pressable>
                </View>

                <Text style={styles.mergeHint}>
                  {mergeAsOne
                    ? "Louis will merge all pages into one roster (best for multi-page monthly rosters)."
                    : "Each file becomes its own roster (best for uploading multiple months at once)."}
                </Text>

                <View style={{ marginTop: 10 }}>
                  {multiFiles.map((f, i) => (
                    <View key={`${f.filename}-${i}`} style={styles.multiRow}>
                      <Ionicons
                        name={f.mime === "application/pdf" ? "document-text" : "image"}
                        size={16}
                        color={theme.color.brand}
                      />
                      <Text style={styles.multiFile} numberOfLines={1}>{f.filename}</Text>
                      <Pressable
                        onPress={() => removeMultiFile(i)}
                        hitSlop={8}
                        testID={`ru-multi-remove-${i}`}
                      >
                        <Ionicons name="close-circle" size={18} color={theme.color.textMuted} />
                      </Pressable>
                    </View>
                  ))}
                </View>

                <Pressable
                  onPress={submitMulti}
                  disabled={starting || multiFiles.length === 0}
                  style={[styles.multiSubmit, (starting || !multiFiles.length) && { opacity: 0.5 }]}
                  testID="ru-multi-submit"
                >
                  {starting ? (
                    <ActivityIndicator color="#fff" />
                  ) : (
                    <>
                      <Ionicons name="cloud-upload" size={16} color="#fff" />
                      <Text style={styles.multiSubmitT}>
                        UPLOAD {mergeAsOne ? "AS ONE ROSTER" : `${multiFiles.length} ROSTERS`}
                      </Text>
                    </>
                  )}
                </Pressable>

                <Pressable onPress={() => setMultiFiles([])} style={styles.multiCancel} testID="ru-multi-cancel">
                  <Text style={styles.multiCancelT}>CANCEL</Text>
                </Pressable>
              </View>
            ) : null}

            {starting ? (
              <View style={{ marginTop: 20, alignItems: "center" }}>
                <ActivityIndicator color={theme.color.brand} />
                <Text style={styles.helper}>Starting upload...</Text>
              </View>
            ) : null}
            {error ? (
              <View style={styles.errCardBox} testID="ru-upload-error">
                <Text style={styles.errCardT}>Roster upload did not complete.</Text>
                <Text style={styles.errCardB}>{error}</Text>
                <View style={{ height: 8 }} />
                <Text style={styles.errCardHint}>
                  Please try again or send the roster to Louis on WhatsApp.
                </Text>
                <View style={styles.errActionsRow}>
                  <Pressable
                    testID="ru-err-try-again"
                    onPress={() => { setError(null); pickPdf(); }}
                    style={[styles.actBtn, { backgroundColor: theme.color.brand, flex: 1 }]}
                  >
                    <Text style={styles.actBtnText}>TRY AGAIN</Text>
                  </Pressable>
                  <Pressable
                    testID="ru-err-choose-different"
                    onPress={() => { setError(null); pickAnyFile(); }}
                    style={[styles.actBtn, styles.actBtnGhost, { flex: 1 }]}
                  >
                    <Text style={styles.actBtnGhostT}>CHOOSE DIFFERENT FILE</Text>
                  </Pressable>
                </View>
                <Pressable
                  testID="ru-err-whatsapp"
                  onPress={() => Linking.openURL(PUBLIC_URLS.whatsapp)}
                  style={[styles.actBtn, styles.actBtnWa, { marginTop: 8 }]}
                >
                  <Ionicons name="logo-whatsapp" size={16} color="#fff" />
                  <Text style={styles.actBtnText}>MESSAGE LOUIS ON WHATSAPP</Text>
                </Pressable>
              </View>
            ) : null}
          </>
        ) : (
          <>
            <View style={styles.progressCard}>
              <View style={styles.progressHeader}>
                <ActivityIndicator size="large" color={theme.color.brand} animating={active} />
                <Text style={styles.progressTitle} testID="ru-progress-message">
                  {/* Iter188 · Copy fix — the confirm_build job flipping
                      to 100% does NOT mean the plan is ready; the coach
                      still has to approve it in MANUAL_MODE. This card
                      is now only a fallback — the polling handler
                      normally redirects to /roster/received on complete. */}
                  {done ? "ROSTER RECEIVED — COACH IS REVIEWING"
                    : failed ? "PROCESSING FAILED"
                    : needsReview ? "ROSTER SAVED — PLAN NEEDS REVIEW"
                    : partial ? "ROSTER SAVED — PLAN NEEDS RETRY"
                    : (job.message || "Processing...")}
                </Text>
                <Text style={styles.progressPct}>{done ? "100%" : needsReview || partial ? "SAVED" : `${progress}%`}</Text>
              </View>
              <View style={styles.progressBarWrap}>
                <View testID="ru-progress-bar" style={[styles.progressBarFill, {
                  width: `${progress}%`,
                  backgroundColor: failed ? theme.color.red : needsReview || partial ? theme.color.amber : done ? theme.color.green : theme.color.brand,
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

              {/* Slow / stuck banners */}
              {active && slowness === "slow" && (
                <View style={styles.slowBanner} testID="ru-slow-banner">
                  <Ionicons name="time" size={14} color={theme.color.amber} />
                  <Text style={styles.slowBannerT}>This is taking longer than expected. You can leave this screen — we&apos;ll keep working in the background.</Text>
                </View>
              )}
              {active && slowness === "stuck" && (
                <View style={styles.stuckBanner} testID="ru-stuck-banner">
                  <Ionicons name="warning" size={14} color={theme.color.red} />
                  <Text style={styles.stuckBannerT}>Your roster is in. Louis wants a second look at this one before it goes live.</Text>
                </View>
              )}
            </View>

            {(failed || needsReview || partial) && (
              <View style={styles.errCard}>
                <Ionicons name={needsReview || partial ? "alert-circle" : "close-circle"} size={18} color={needsReview || partial ? theme.color.amber : theme.color.red} />
                <Text style={styles.errCardText}>{job.error || (needsReview ? "Louis wants a second look at this one — he'll be in touch shortly." : "This roster wasn't clear enough to work with. Try a sharper photo or PDF, or enter the details manually.")}</Text>
              </View>
            )}

            <View style={{ gap: 10, marginTop: 20 }}>
              {active && (
                <>
                  <View style={{ flexDirection: "row", gap: 10 }}>
                    <Pressable testID="ru-leave" onPress={leaveScreen} style={[styles.actBtn, styles.actBtnGhost]}>
                      <Text style={styles.actBtnGhostText}>KEEP WORKING</Text>
                    </Pressable>
                    <Pressable testID="ru-cancel" onPress={cancelWithConfirm} style={[styles.actBtn, styles.actBtnGhost]}>
                      <Text style={styles.actBtnGhostText}>CANCEL</Text>
                    </Pressable>
                  </View>
                  {slowness !== "none" && (
                    <View style={{ flexDirection: "row", gap: 10 }}>
                      <Pressable testID="ru-message-louis-slow" onPress={messageLouis} style={[styles.actBtn, styles.actBtnGhost]}>
                        <Text style={styles.actBtnGhostText}>MESSAGE LOUIS</Text>
                      </Pressable>
                      <Pressable testID="ru-go-home-slow" onPress={leaveScreen} style={[styles.actBtn, styles.actBtnGhost]}>
                        <Text style={styles.actBtnGhostText}>GO TO HOME</Text>
                      </Pressable>
                    </View>
                  )}
                </>
              )}
              {(needsReview || partial) && (
                <>
                  <Pressable testID="ru-retry-plan" onPress={retryPlanGeneration} disabled={retrying} style={[styles.actBtn, { backgroundColor: theme.color.brand }, retrying && { opacity: 0.6 }]}>
                    {retrying ? <ActivityIndicator color="#fff" /> : <Text style={styles.actBtnText}>SEND TO LOUIS AGAIN</Text>}
                  </Pressable>
                  <View style={{ flexDirection: "row", gap: 10 }}>
                    <Pressable testID="ru-message-louis" onPress={messageLouis} style={[styles.actBtn, styles.actBtnGhost]}>
                      <Text style={styles.actBtnGhostText}>MESSAGE LOUIS</Text>
                    </Pressable>
                    <Pressable testID="ru-go-home" onPress={leaveScreen} style={[styles.actBtn, styles.actBtnGhost]}>
                      <Text style={styles.actBtnGhostText}>GO TO HOME</Text>
                    </Pressable>
                  </View>
                </>
              )}
              {failed && (
                <Pressable testID="ru-try-again" onPress={startFresh} style={[styles.actBtn, { backgroundColor: theme.color.brand }]}>
                  <Text style={styles.actBtnText}>TRY AGAIN</Text>
                </Pressable>
              )}
              {done && (
                <View style={{ flexDirection: "row", gap: 10 }}>
                  {/* Iter188 · The plan is NOT ready at this point in
                      MANUAL_MODE — coach still has to approve. The
                      primary action leads to the dedicated
                      "Roster Received / coach is reviewing" screen. */}
                  <Pressable
                    testID="ru-see-status"
                    onPress={() => router.replace("/roster/received")}
                    style={[styles.actBtn, { backgroundColor: theme.color.brand }]}
                  >
                    <Text style={styles.actBtnText}>SEE STATUS</Text>
                  </Pressable>
                  <Pressable
                    testID="ru-go-home"
                    onPress={() => router.replace("/(client)/home")}
                    style={[styles.actBtn, styles.actBtnGhost]}
                  >
                    <Text style={styles.actBtnGhostText}>GO TO HOME</Text>
                  </Pressable>
                </View>
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
  // Iter 95e — upload error card with escape hatches (new key to avoid clash with existing `errCard`).
  errCardBox: {
    marginTop: 20,
    padding: 16,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: theme.color.red,
    backgroundColor: theme.color.surface2,
  },
  errCardT: { color: theme.color.text, fontSize: 15, fontWeight: "800", marginBottom: 4 },
  errCardB: { color: theme.color.textMuted, fontSize: 13, lineHeight: 18 },
  errCardHint: { color: theme.color.textMuted, fontSize: 12, fontStyle: "italic", marginTop: 8, marginBottom: 6 },
  errActionsRow: { flexDirection: "row", gap: 8, marginTop: 8 },
  actBtnGhostT: { color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 1.2 },
  actBtnWa: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    backgroundColor: "#25D366",
  },

  progressCard: { padding: 20, backgroundColor: theme.color.surface2, borderRadius: 12, borderWidth: 1, borderColor: theme.color.border },
  progressHeader: { alignItems: "center", gap: 10, marginBottom: 16 },
  progressTitle: { color: theme.color.text, fontSize: 14, fontWeight: "800", letterSpacing: 1.5, textAlign: "center" },
  progressPct: { color: theme.color.brand, fontSize: 34, fontWeight: "900" },
  progressBarWrap: { height: 8, borderRadius: 4, backgroundColor: theme.color.border, overflow: "hidden" },
  progressBarFill: { height: "100%", borderRadius: 4 },
  stageRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  stageLabel: { color: theme.color.textDim, fontSize: 13 },

  slowBanner: {
    flexDirection: "row", gap: 8, alignItems: "flex-start", padding: 12, marginTop: 14,
    borderRadius: 8, backgroundColor: "rgba(245,158,11,0.10)", borderWidth: 1, borderColor: theme.color.amber,
  },
  slowBannerT: { color: theme.color.text, fontSize: 12, lineHeight: 17, flex: 1 },
  stuckBanner: {
    flexDirection: "row", gap: 8, alignItems: "flex-start", padding: 12, marginTop: 14,
    borderRadius: 8, backgroundColor: "rgba(220,38,38,0.10)", borderWidth: 1, borderColor: theme.color.red,
  },
  stuckBannerT: { color: theme.color.text, fontSize: 12, lineHeight: 17, flex: 1 },

  errCard: { flexDirection: "row", gap: 10, alignItems: "flex-start", padding: 14, backgroundColor: "rgba(239,68,68,0.12)", borderRadius: 10, borderLeftWidth: 3, borderLeftColor: theme.color.red, marginTop: 14 },
  errCardText: { color: theme.color.text, fontSize: 13, flex: 1, lineHeight: 18 },

  actBtn: { flex: 1, alignItems: "center", justifyContent: "center", paddingVertical: 14, borderRadius: 10 },
  actBtnGhost: { backgroundColor: "transparent", borderWidth: 1, borderColor: theme.color.brand },
  actBtnText: { color: "#fff", fontSize: 12, fontWeight: "800", letterSpacing: 1.5 },
  actBtnGhostText: { color: theme.color.brand, fontSize: 12, fontWeight: "800", letterSpacing: 1.5 },

  leaveHint: { color: theme.color.textMuted, fontSize: 12, marginTop: 14, textAlign: "center", fontStyle: "italic" },
  browseTip: { color: theme.color.textMuted, fontSize: 11, marginTop: 6, marginBottom: 6, lineHeight: 16, fontStyle: "italic" },

  multiCard: {
    marginTop: 14,
    padding: 14,
    borderRadius: 12,
    backgroundColor: theme.color.surface2,
    borderWidth: 1,
    borderColor: theme.color.brand,
  },
  multiTitle: {
    color: theme.color.brand,
    fontSize: 11,
    fontWeight: "900",
    letterSpacing: 1.6,
    marginBottom: 10,
  },
  mergeToggleRow: {
    flexDirection: "row",
    gap: 6,
    marginBottom: 6,
  },
  mergeToggle: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 10,
    paddingHorizontal: 8,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: theme.color.brand,
    backgroundColor: "transparent",
  },
  mergeToggleOn: {
    backgroundColor: theme.color.brand,
  },
  mergeToggleT: {
    color: theme.color.brand,
    fontSize: 11,
    fontWeight: "900",
    letterSpacing: 1.2,
  },
  mergeHint: {
    color: theme.color.textMuted,
    fontSize: 11,
    lineHeight: 15,
    fontStyle: "italic",
    marginTop: 4,
  },
  multiRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 8,
    paddingHorizontal: 10,
    borderRadius: 8,
    backgroundColor: theme.color.surface,
    borderWidth: 1,
    borderColor: theme.color.border,
    marginBottom: 4,
  },
  multiFile: {
    flex: 1,
    color: theme.color.text,
    fontSize: 12,
    fontWeight: "700",
  },
  multiSubmit: {
    marginTop: 12,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    paddingVertical: 12,
    borderRadius: 10,
    backgroundColor: theme.color.brand,
  },
  multiSubmitT: {
    color: "#fff",
    fontSize: 12,
    fontWeight: "900",
    letterSpacing: 1.5,
  },
  multiCancel: {
    marginTop: 6,
    alignItems: "center",
    paddingVertical: 8,
  },
  multiCancelT: {
    color: theme.color.textMuted,
    fontSize: 11,
    fontWeight: "800",
    letterSpacing: 1.4,
  },
  // Iter186 · Lock screen (post-submission success card)
  lockRoot: { flex: 1, backgroundColor: theme.color.surface },
  lockScroll: { padding: 20, paddingBottom: 40, gap: 18 },
  lockHero: {
    padding: 22,
    borderRadius: 18,
    backgroundColor: theme.color.brandTint,
    borderWidth: 1,
    borderColor: theme.color.brand,
    alignItems: "center",
    gap: 12,
  },
  lockIconWrap: {
    width: 68, height: 68, borderRadius: 34,
    backgroundColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
  },
  lockEyebrow: {
    color: theme.color.brand,
    fontSize: 11, fontWeight: "900", letterSpacing: 2.2, marginTop: 4,
  },
  lockTitle: {
    color: theme.color.text,
    fontSize: 22, fontWeight: "900", textAlign: "center", letterSpacing: 0.3,
  },
  lockBody: {
    color: theme.color.textMuted,
    fontSize: 13, lineHeight: 20, textAlign: "center", paddingHorizontal: 6,
  },
  lockMeta: {
    marginTop: 6, flexDirection: "row", gap: 6, alignItems: "center",
  },
  lockMetaT: {
    color: theme.color.textMuted, fontSize: 11, fontStyle: "italic",
  },
  lockCta: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
    paddingVertical: 15,
    borderRadius: 12,
    backgroundColor: theme.color.brand,
  },
  lockCtaT: {
    color: "#fff", fontSize: 13, fontWeight: "900", letterSpacing: 1.6,
  },
  lockGhost: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    paddingVertical: 14,
    borderRadius: 12,
    borderWidth: 1, borderColor: theme.color.brand,
    backgroundColor: "transparent",
  },
  lockGhostT: {
    color: theme.color.brand, fontSize: 12, fontWeight: "900", letterSpacing: 1.4,
  },
  lockChecklist: {
    padding: 16, borderRadius: 12,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border, gap: 10,
  },
  lockChecklistH: {
    color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2,
  },
  lockChecklistRow: {
    flexDirection: "row", alignItems: "flex-start", gap: 10,
  },
  lockChecklistT: {
    color: theme.color.text, fontSize: 12, lineHeight: 18, flex: 1,
  },
});

/* --------------------------------------------------------------------- */
/*  Iter186 · Submitted-lock success screen                              */
/*                                                                       */
/*  Replaces the upload buttons entirely when the client has already      */
/*  submitted. Copy sets expectations ("up to 24 hours") so the client    */
/*  doesn't fear their submission was lost + can't accidentally re-upload */
/*  before the coach reviews. Three variants keyed off `state`:            */
/*     awaiting_client_confirmation → "please confirm your duties"        */
/*     awaiting_coach_review        → "coach is building your programme"  */
/*     coach_approved               → "your programme is live"            */
/* --------------------------------------------------------------------- */
function RosterSubmittedLockScreen({
  submission,
  onBackHome,
  onOpenConfirm,
}: {
  submission: {
    state: string;
    submitted_at?: string;
    coach_review_at?: string;
    coach_review_actor?: string;
    legacy_backfill?: boolean;
  };
  onBackHome: () => void;
  onOpenConfirm?: () => void;
}) {
  const router = useRouter();
  const state = submission.state;

  const copy = (() => {
    if (state === "awaiting_client_confirmation") {
      return {
        icon: "hand-right" as const,
        eyebrow: "ONE MORE STEP",
        title: "Review your duty pattern",
        body: "We've parsed your roster — please open the duty confirmation screen and check we've read your flights correctly. Louis can't build your programme until you confirm.",
        primary: { label: "REVIEW DUTIES", action: onOpenConfirm ?? onBackHome, icon: "arrow-forward" as const },
      };
    }
    if (state === "coach_approved") {
      return {
        icon: "checkmark-done" as const,
        eyebrow: "PROGRAMME LIVE",
        title: "Your programme is live",
        body:
          submission.coach_review_actor === "auto_24h"
            ? "Your coach has been busy — we've released your programme automatically so you can get started. Louis will drop any tweaks in the chat over the coming days."
            : "Your coach has reviewed your roster and released your personalised programme. Head to your calendar to see what's on today.",
        primary: { label: "OPEN CALENDAR", action: () => router.replace("/(client)/calendar"), icon: "calendar" as const },
      };
    }
    // Default: awaiting_coach_review
    return {
      icon: "checkmark-circle" as const,
      eyebrow: "ROSTER RECEIVED",
      title: "Your coach is on it",
      body: "Your coach is building your personalised programme. This can take up to 24 hours. We'll notify you when it's ready.",
      primary: { label: "GO TO HOME", action: onBackHome, icon: "home" as const },
    };
  })();

  const submittedDate = submission.submitted_at
    ? new Date(submission.submitted_at).toLocaleDateString(undefined, {
        weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
      })
    : null;

  return (
    <SafeAreaView style={styles.lockRoot} edges={["top"]} testID="ru-lock-screen">
      <View style={styles.header}>
        <Pressable onPress={onBackHome} testID="ru-lock-back">
          <Ionicons name="chevron-back" size={22} color={theme.color.text} />
        </Pressable>
        <Text style={styles.title}>UPLOAD ROSTER</Text>
        <View style={{ width: 22 }} />
      </View>

      <ScrollView contentContainerStyle={styles.lockScroll}>
        <View style={styles.lockHero}>
          <View style={styles.lockIconWrap}>
            <Ionicons name={copy.icon} size={32} color="#fff" />
          </View>
          <Text style={styles.lockEyebrow}>{copy.eyebrow}</Text>
          <Text style={styles.lockTitle}>{copy.title}</Text>
          <Text style={styles.lockBody}>{copy.body}</Text>
          {submittedDate && state !== "awaiting_client_confirmation" ? (
            <View style={styles.lockMeta}>
              <Ionicons name="time-outline" size={11} color={theme.color.textMuted} />
              <Text style={styles.lockMetaT}>Submitted {submittedDate}</Text>
            </View>
          ) : null}
        </View>

        <Pressable
          onPress={copy.primary.action}
          style={styles.lockCta}
          testID="ru-lock-primary-cta"
        >
          <Ionicons name={copy.primary.icon} size={16} color="#fff" />
          <Text style={styles.lockCtaT}>{copy.primary.label}</Text>
        </Pressable>

        {state === "awaiting_coach_review" ? (
          <View style={styles.lockChecklist}>
            <Text style={styles.lockChecklistH}>WHAT&apos;S HAPPENING NEXT</Text>
            <View style={styles.lockChecklistRow}>
              <Ionicons name="checkmark-circle" size={16} color={theme.color.green} />
              <Text style={styles.lockChecklistT}>Roster parsed and saved.</Text>
            </View>
            <View style={styles.lockChecklistRow}>
              <ActivityIndicator size="small" color={theme.color.brand} />
              <Text style={styles.lockChecklistT}>Louis is reviewing your week and building your personalised programme.</Text>
            </View>
            <View style={styles.lockChecklistRow}>
              <Ionicons name="ellipse-outline" size={16} color={theme.color.textDim} />
              <Text style={styles.lockChecklistT}>You&apos;ll get a notification (and a chat message) the moment it&apos;s live — usually within 24 hours.</Text>
            </View>
          </View>
        ) : null}

        {state !== "awaiting_client_confirmation" ? (
          <Pressable
            onPress={onBackHome}
            style={styles.lockGhost}
            testID="ru-lock-home"
          >
            <Ionicons name="home-outline" size={14} color={theme.color.brand} />
            <Text style={styles.lockGhostT}>BACK TO HOME</Text>
          </Pressable>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}
