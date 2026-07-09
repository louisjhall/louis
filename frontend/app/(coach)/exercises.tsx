/**
 * Atlas Exercise Content — Coach Dashboard (Phase 2)
 * List all exercises with content-completeness scores and inline editors.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator,
  Alert, Image, RefreshControl, Modal, KeyboardAvoidingView, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect } from "expo-router";
import * as DocumentPicker from "expo-document-picker";
import * as FileSystem from "expo-file-system";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

export default function CoachExercises() {
  const [exercises, setExercises] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<any>(null);
  const [batchOpen, setBatchOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<any>("/coach/exercises");
      setExercises(r.exercises || []);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim();
    return exercises.filter((e) => !q || (e.name || "").toLowerCase().includes(q))
      .sort((a, b) => (a.content_score || 0) - (b.content_score || 0));
  }, [exercises, search]);

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <View style={{ flex: 1 }}>
          <Text style={styles.eyebrow}>ATLAS EXERCISE LIBRARY</Text>
          <Text style={styles.title}>Coach <Text style={styles.brandRed}>Content</Text></Text>
        </View>
        <Pressable onPress={() => setBatchOpen(true)} style={styles.batchBtn} testID="batch-open">
          <Ionicons name="sparkles" size={13} color={theme.color.brand} />
          <Text style={styles.batchBtnT}>BATCH</Text>
        </Pressable>
        <View style={styles.countPill}>
          <Text style={styles.countPillT}>{exercises.length}</Text>
        </View>
      </View>

      <View style={styles.searchWrap}>
        <Ionicons name="search" size={14} color={theme.color.textDim} />
        <TextInput
          value={search} onChangeText={setSearch}
          placeholder="Search exercises..."
          placeholderTextColor={theme.color.textDim}
          style={styles.searchInput}
        />
      </View>

      <ScrollView contentContainerStyle={styles.body}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}>
        {filtered.map((ex) => (
          <Pressable
            key={ex.id}
            onPress={async () => {
              // Fetch the FULL exercise (with full-resolution custom_image_b64) before opening the editor
              try {
                const r = await api<any>(`/coach/exercises/${encodeURIComponent(ex.name)}`);
                setSelected(r.exercise || ex);
              } catch {
                setSelected(ex);
              }
            }}
            style={styles.exRow}
            testID={`ex-${ex.id}`}
          >
            {ex.thumb_b64 ? (
              <Image source={{ uri: ex.thumb_b64 }} style={styles.exThumb} resizeMode="cover" />
            ) : (
              <View style={[styles.exThumb, styles.exThumbEmpty]}>
                <Ionicons name={ex.has_image ? "image" : "image-outline"} size={20} color={theme.color.textDim} />
              </View>
            )}
            <View style={styles.exScore}>
              <Text style={[styles.exScoreT, ex.content_score >= 4 && { color: theme.color.green }]}>{ex.content_score || 0}/5</Text>
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.exName} numberOfLines={1}>{ex.name}</Text>
              <View style={styles.exFlagRow}>
                <Flag on={ex.has_image} label="IMG" />
                <Flag on={ex.has_video} label="VID" />
                <Flag on={ex.has_instructions} label="STEPS" />
                <Flag on={ex.has_cues} label="CUES" />
                <Flag on={ex.has_mistakes} label="MISTAKES" />
              </View>
            </View>
            <Ionicons name="chevron-forward" size={16} color={theme.color.textDim} />
          </Pressable>
        ))}
      </ScrollView>

      {selected && <EditorSheet exercise={selected} onClose={() => setSelected(null)} onSaved={() => { setSelected(null); load(); }} />}
      {batchOpen && (
        <BatchGenerateModal onClose={() => setBatchOpen(false)} onDone={() => { setBatchOpen(false); load(); }} />
      )}
    </SafeAreaView>
  );
}

function Flag({ on, label }: { on: boolean; label: string }) {
  return (
    <View style={[styles.flag, on ? styles.flagOn : styles.flagOff]}>
      <Ionicons name={on ? "checkmark" : "close"} size={9} color={on ? theme.color.green : theme.color.textDim} />
      <Text style={[styles.flagT, on && { color: theme.color.green }]}>{label}</Text>
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/*  Batch Atlas Generation Modal (Images + HOW-TO)                             */
/* -------------------------------------------------------------------------- */
function BatchGenerateModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [kind, setKind] = useState<"image" | "content">("image");
  const [filter, setFilter] = useState<"warmup" | "missing" | "all">("warmup");
  const [starting, setStarting] = useState(false);
  const [job, setJob] = useState<any>(null);
  const pollRef = useRef<any>(null);

  // Endpoints per kind
  const endpoints = kind === "image"
    ? {
        start: "/coach/exercises/batch-generate-images",
        status: "/coach/exercises/batch-generate-images/status",
        cancel: "/coach/exercises/batch-generate-images/cancel",
        missingFilter: "missing_image",
        etaLine: "Each image takes ~10-15s. Atlas runs politely at 1 per second, so 220 warm-ups take ~40-50 min.",
        icon: "sparkles" as const,
        titleT: "Generate images at scale",
      }
    : {
        start: "/coach/exercises/batch-generate-content",
        status: "/coach/exercises/batch-generate-content/status",
        cancel: "/coach/exercises/batch-generate-content/cancel",
        missingFilter: "missing_content",
        etaLine: "Claude writes each move in ~2-3s. 220 warm-ups take ~10 minutes. Coach reviews before approval.",
        icon: "document-text" as const,
        titleT: "Generate coaching how-to at scale",
      };

  const loadStatus = useCallback(async () => {
    try {
      const r = await api<any>(endpoints.status);
      setJob(r.job || null);
      if (r.job && (r.job.status === "done" || r.job.status === "cancelled" || r.job.status === "error")) {
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
      }
    } catch { /* ignore */ }
  }, [endpoints.status]);

  useEffect(() => {
    loadStatus();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [loadStatus]);

  // If the kind toggle changes, re-load status for that kind
  useEffect(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    setJob(null);
    loadStatus();
  }, [kind, loadStatus]);

  const start = async () => {
    setStarting(true);
    try {
      const filterVal = filter === "missing" ? endpoints.missingFilter : filter; // "warmup" | "all" | missing_*
      const r = await api<any>(endpoints.start, {
        method: "POST", body: { filter: filterVal },
      });
      if (r.error) {
        Alert.alert("Cannot start", r.error);
      } else {
        setJob(r.job);
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = setInterval(loadStatus, 3000);
      }
    } catch (e: any) {
      Alert.alert("Failed to start", e?.message || "Please try again.");
    } finally { setStarting(false); }
  };

  const cancel = async () => {
    try {
      await api(endpoints.cancel, { method: "POST", body: {} });
      loadStatus();
    } catch { /* ignore */ }
  };

  const isRunning = job && (job.status === "queued" || job.status === "running");
  const pct = job && job.total ? Math.round(((job.processed || 0) / job.total) * 100) : 0;

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={batchStyles.root}>
        <Pressable style={batchStyles.backdrop} onPress={isRunning ? undefined : onClose} />
        <View style={batchStyles.sheet}>
          <View style={batchStyles.head}>
            <View style={batchStyles.headIcon}><Ionicons name={endpoints.icon} size={16} color={theme.color.brand} /></View>
            <View style={{ flex: 1 }}>
              <Text style={batchStyles.eyebrow}>ATLAS BATCH RENDER</Text>
              <Text style={batchStyles.title}>{endpoints.titleT}</Text>
            </View>
            <Pressable onPress={onClose} hitSlop={12} disabled={isRunning}>
              <Ionicons name="close" size={22} color={isRunning ? theme.color.textDim : theme.color.text} />
            </Pressable>
          </View>

          {/* Kind toggle */}
          {!isRunning && (
            <View style={batchStyles.kindRow}>
              <KindTab label="IMAGES" active={kind === "image"} onPress={() => setKind("image")} />
              <KindTab label="HOW-TO" active={kind === "content"} onPress={() => setKind("content")} />
            </View>
          )}

          <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 24 }}>
            {!isRunning && (
              <>
                <Text style={batchStyles.label}>SELECT SCOPE</Text>
                <View style={batchStyles.filters}>
                  <FilterChip
                    label="WARM-UP MOVES"
                    hint={kind === "image" ? "~220 moves without an image" : "~230 moves without instructions"}
                    active={filter === "warmup"}
                    onPress={() => setFilter("warmup")}
                  />
                  <FilterChip
                    label={kind === "image" ? "ALL MISSING IMAGES" : "ALL MISSING HOW-TO"}
                    hint={kind === "image" ? "Every exercise without a photo" : "Every exercise without instructions"}
                    active={filter === "missing"}
                    onPress={() => setFilter("missing")}
                  />
                  <FilterChip
                    label="ENTIRE LIBRARY"
                    hint="All exercises · slowest"
                    active={filter === "all"}
                    onPress={() => setFilter("all")}
                  />
                </View>
                <View style={batchStyles.warn}>
                  <Ionicons name="information-circle" size={12} color={theme.color.brand} />
                  <Text style={batchStyles.warnT}>{endpoints.etaLine} You can close this window; the job keeps running.</Text>
                </View>
                <Pressable
                  onPress={start}
                  disabled={starting}
                  style={[batchStyles.startBtn, starting && { opacity: 0.35 }]}
                  testID="batch-start"
                >
                  {starting
                    ? <ActivityIndicator color="#fff" size="small" />
                    : <Ionicons name="rocket" size={14} color="#fff" />}
                  <Text style={batchStyles.startBtnT}>{starting ? "STARTING..." : "START BATCH"}</Text>
                </Pressable>
              </>
            )}

            {job && (
              <View style={batchStyles.progressCard}>
                <View style={batchStyles.progressHead}>
                  <View style={[batchStyles.statusDot, statusColor(job.status)]} />
                  <Text style={batchStyles.progressStatus}>{String(job.status || "").toUpperCase()}</Text>
                  <Text style={batchStyles.progressCount}>
                    {job.processed || 0} / {job.total || 0}
                  </Text>
                </View>
                <View style={batchStyles.barTrack}>
                  <View style={[batchStyles.barFill, { width: `${pct}%` }]} />
                </View>
                <View style={batchStyles.stats}>
                  <StatChip label="DONE" value={job.succeeded || 0} color={theme.color.green} />
                  <StatChip label="FAILED" value={job.failed || 0} color={"#c94a4a"} />
                  <StatChip label="TOTAL" value={job.total || 0} color={theme.color.brand} />
                </View>
                {job.current_name && isRunning && (
                  <Text style={batchStyles.currentT}>
                    <Text style={{ color: theme.color.textMuted, fontSize: 10 }}>NOW RENDERING · </Text>
                    {job.current_name}
                  </Text>
                )}
                {job.errors && job.errors.length > 0 && (
                  <View style={batchStyles.errorBox}>
                    <Text style={batchStyles.errorH}>RECENT ERRORS ({job.errors.length})</Text>
                    {job.errors.slice(-5).map((e: any, i: number) => (
                      <Text key={i} style={batchStyles.errorL} numberOfLines={1}>
                        • {e.name || e.exercise_id}: {e.error}
                      </Text>
                    ))}
                  </View>
                )}
                <View style={{ flexDirection: "row", gap: 8, marginTop: 12 }}>
                  {isRunning ? (
                    <Pressable onPress={cancel} style={batchStyles.cancelBtn}>
                      <Ionicons name="stop-circle" size={12} color={theme.color.text} />
                      <Text style={batchStyles.cancelBtnT}>STOP JOB</Text>
                    </Pressable>
                  ) : (
                    <Pressable onPress={onDone} style={batchStyles.startBtn}>
                      <Ionicons name="checkmark-circle" size={14} color="#fff" />
                      <Text style={batchStyles.startBtnT}>DONE</Text>
                    </Pressable>
                  )}
                </View>
              </View>
            )}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

function KindTab({ label, active, onPress }: { label: string; active: boolean; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={[batchStyles.kindTab, active && batchStyles.kindTabActive]}>
      <Text style={[batchStyles.kindTabT, active && batchStyles.kindTabTA]}>{label}</Text>
    </Pressable>
  );
}

function FilterChip({ label, hint, active, onPress }: { label: string; hint: string; active: boolean; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={[batchStyles.chip, active && batchStyles.chipActive]}>
      <View style={{ flex: 1 }}>
        <Text style={[batchStyles.chipL, active && batchStyles.chipLA]}>{label}</Text>
        <Text style={batchStyles.chipH}>{hint}</Text>
      </View>
      <Ionicons name={active ? "radio-button-on" : "radio-button-off"} size={16} color={active ? theme.color.brand : theme.color.textDim} />
    </Pressable>
  );
}

function StatChip({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <View style={[batchStyles.statChip, { borderColor: color }]}>
      <Text style={[batchStyles.statV, { color }]}>{value}</Text>
      <Text style={batchStyles.statL}>{label}</Text>
    </View>
  );
}

function statusColor(s: string) {
  if (s === "running" || s === "queued") return { backgroundColor: theme.color.brand };
  if (s === "done") return { backgroundColor: theme.color.green };
  if (s === "cancelled") return { backgroundColor: theme.color.textDim };
  return { backgroundColor: "#c94a4a" };
}

const batchStyles = StyleSheet.create({
  root: { flex: 1, justifyContent: "flex-end" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.5)" },
  sheet: { backgroundColor: theme.color.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20, maxHeight: "88%" },
  head: { flexDirection: "row", alignItems: "center", gap: 12, padding: 16, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  headIcon: { width: 34, height: 34, borderRadius: 17, backgroundColor: theme.color.brandTint, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: theme.color.brand },
  eyebrow: { color: theme.color.brand, fontSize: 9, fontWeight: "900", letterSpacing: 2 },
  title: { color: theme.color.text, fontSize: 16, fontWeight: "800", marginTop: 3 },
  label: { color: theme.color.brand, fontSize: 9, fontWeight: "900", letterSpacing: 2, marginBottom: 10 },
  filters: { gap: 8, marginBottom: 14 },
  chip: { flexDirection: "row", alignItems: "center", gap: 10, padding: 12, borderRadius: 10, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  chipActive: { borderColor: theme.color.brand, backgroundColor: theme.color.brandTint },
  chipL: { color: theme.color.text, fontSize: 12, fontWeight: "900", letterSpacing: 1.2 },
  chipLA: { color: theme.color.brand },
  chipH: { color: theme.color.textMuted, fontSize: 10, marginTop: 2 },
  warn: { flexDirection: "row", gap: 8, padding: 10, borderRadius: 8, backgroundColor: theme.color.brandTint, marginBottom: 14, borderWidth: 1, borderColor: theme.color.brand },
  warnT: { color: theme.color.text, fontSize: 11, lineHeight: 15, flex: 1 },
  startBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, padding: 14, borderRadius: 10, backgroundColor: theme.color.brand, flex: 1 },
  startBtnT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 2 },
  cancelBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, padding: 14, borderRadius: 10, backgroundColor: theme.color.surface3, borderWidth: 1, borderColor: theme.color.border, flex: 1 },
  cancelBtnT: { color: theme.color.text, fontSize: 12, fontWeight: "900", letterSpacing: 2 },
  progressCard: { padding: 14, borderRadius: 12, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  progressHead: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 10 },
  statusDot: { width: 8, height: 8, borderRadius: 4 },
  progressStatus: { color: theme.color.text, fontSize: 11, fontWeight: "900", letterSpacing: 1.5, flex: 1 },
  progressCount: { color: theme.color.brand, fontSize: 13, fontWeight: "900", fontVariant: ["tabular-nums"] },
  barTrack: { height: 6, borderRadius: 3, backgroundColor: theme.color.surface3, overflow: "hidden" },
  barFill: { height: 6, backgroundColor: theme.color.brand },
  stats: { flexDirection: "row", gap: 8, marginTop: 10 },
  statChip: { flex: 1, alignItems: "center", padding: 8, borderRadius: 8, borderWidth: 1 },
  statV: { fontSize: 18, fontWeight: "900" },
  statL: { color: theme.color.textMuted, fontSize: 9, fontWeight: "900", letterSpacing: 1.2, marginTop: 2 },
  currentT: { color: theme.color.text, fontSize: 11, marginTop: 10, fontStyle: "italic" },
  errorBox: { marginTop: 10, padding: 10, borderRadius: 8, backgroundColor: theme.color.surface3, borderWidth: 1, borderColor: "#c94a4a" },
  errorH: { color: "#c94a4a", fontSize: 9, fontWeight: "900", letterSpacing: 1.5, marginBottom: 6 },
  errorL: { color: theme.color.textMuted, fontSize: 10, lineHeight: 14, marginTop: 2 },
  kindRow: { flexDirection: "row", gap: 8, paddingHorizontal: 16, paddingTop: 12, paddingBottom: 4 },
  kindTab: { flex: 1, paddingVertical: 8, borderRadius: 8, borderWidth: 1, borderColor: theme.color.border, alignItems: "center", backgroundColor: theme.color.surface2 },
  kindTabActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  kindTabT: { color: theme.color.text, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  kindTabTA: { color: "#fff" },
});

/* -------------------------------------------------------------------------- */
/*  Editor Sheet                                                              */
/* -------------------------------------------------------------------------- */
function EditorSheet({ exercise, onClose, onSaved }: { exercise: any; onClose: () => void; onSaved: () => void }) {
  const [ex, setEx] = useState<any>(exercise);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [genImaging, setGenImaging] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api<any>(`/coach/exercises/${encodeURIComponent(exercise.name)}`);
      setEx(r.exercise);
    } catch { /* ignore */ }
  }, [exercise.name]);

  React.useEffect(() => { load(); }, [load]);

  const patch = async (updates: any) => {
    setSaving(true);
    try {
      const r = await api<any>(`/coach/exercises/${encodeURIComponent(exercise.name)}`, {
        method: "PATCH", body: updates,
      });
      setEx(r.exercise);
    } catch (e: any) {
      Alert.alert("Save failed", e?.message || "Please try again");
    } finally { setSaving(false); }
  };

  const generate = async () => {
    setGenerating(true);
    try {
      const r = await api<any>(`/coach/exercises/${encodeURIComponent(exercise.name)}/generate`, {
        method: "POST", body: {},
      });
      setEx(r.exercise);
      Alert.alert("Atlas generated", `Populated: ${r.generated.join(", ")}. Please review and approve.`);
    } catch (e: any) {
      Alert.alert("Generation failed", e?.message || "Please try again");
    } finally { setGenerating(false); }
  };

  const uploadImage = async () => {
    try {
      const res = await DocumentPicker.getDocumentAsync({ type: "image/*", copyToCacheDirectory: true });
      if (res.canceled) return;
      const asset = res.assets[0];
      setUploading(true);
      const b64 = await FileSystem.readAsStringAsync(asset.uri, { encoding: "base64" });
      const dataUrl = `data:${asset.mimeType || "image/jpeg"};base64,${b64}`;
      const r = await api<any>(`/coach/exercises/${encodeURIComponent(exercise.name)}/image`, {
        method: "POST", body: { image_b64: dataUrl },
      });
      setEx(r.exercise);
    } catch (e: any) {
      Alert.alert("Upload failed", e?.message || "Please try again");
    } finally { setUploading(false); }
  };

  const generateImage = async () => {
    if (genImaging) return;
    const doIt = async () => {
      setGenImaging(true);
      try {
        const r = await api<any>(`/coach/exercises/${encodeURIComponent(exercise.name)}/generate-image`, {
          method: "POST", body: {},
        });
        setEx(r.exercise);
        Alert.alert("Atlas image ready", "Louis has been rendered for this exercise. Review and approve.");
      } catch (e: any) {
        Alert.alert("Image generation failed", e?.message || "Atlas could not render this exercise. Please try again.");
      } finally { setGenImaging(false); }
    };
    if (ex.custom_image_b64) {
      Alert.alert(
        "Replace existing image?",
        "This will replace the current photo with a newly generated Atlas image.",
        [
          { text: "Cancel", style: "cancel" },
          { text: "Replace", style: "destructive", onPress: doIt },
        ],
      );
    } else {
      doIt();
    }
  };

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.sheetRoot}>
        <Pressable style={styles.backdrop} onPress={onClose} />
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={styles.sheet}>
            <View style={styles.sheetHead}>
              <View style={{ flex: 1 }}>
                <Text style={styles.sheetEyebrow}>ATLAS EXERCISE CONTENT</Text>
                <Text style={styles.sheetTitle} numberOfLines={2}>{ex.name}</Text>
              </View>
              <Pressable onPress={onClose} hitSlop={12}>
                <Ionicons name="close" size={22} color={theme.color.text} />
              </Pressable>
            </View>

            <ScrollView contentContainerStyle={{ padding: 16 }} keyboardShouldPersistTaps="handled">
              {/* Actions */}
              <View style={styles.actionRow}>
                <Pressable onPress={generate} disabled={generating} style={styles.actionPrimary} testID="ex-generate">
                  {generating ? <ActivityIndicator color="#fff" size="small" /> : <Ionicons name="sparkles" size={13} color="#fff" />}
                  <Text style={styles.actionPrimaryT}>{generating ? "GENERATING..." : "GENERATE WITH ATLAS"}</Text>
                </Pressable>
                <Pressable onPress={uploadImage} disabled={uploading} style={styles.actionSecondary} testID="ex-upload">
                  <Ionicons name="image" size={13} color={theme.color.brand} />
                  <Text style={styles.actionSecondaryT}>{uploading ? "..." : "UPLOAD IMAGE"}</Text>
                </Pressable>
              </View>
              <View style={[styles.actionRow, { marginTop: 8 }]}>
                <Pressable
                  onPress={generateImage}
                  disabled={genImaging}
                  style={[styles.actionPrimary, { backgroundColor: theme.color.text, flex: 1 }]}
                  testID="ex-generate-image"
                >
                  {genImaging
                    ? <ActivityIndicator color="#fff" size="small" />
                    : <Ionicons name="color-wand" size={13} color="#fff" />}
                  <Text style={styles.actionPrimaryT}>
                    {genImaging ? "RENDERING LOUIS..." : (ex.custom_image_b64 ? "REGENERATE ATLAS IMAGE" : "GENERATE ATLAS IMAGE")}
                  </Text>
                </Pressable>
              </View>

              {/* Custom image preview */}
              {ex.custom_image_b64 && (
                <Image source={{ uri: ex.custom_image_b64 }} style={styles.imgPreview} resizeMode="cover" />
              )}

              {/* Instructions */}
              <ListEditor
                label="4-POINT INSTRUCTIONS"
                items={ex.instructions || []}
                onSave={(items) => patch({ instructions: items })}
                placeholder="Step description..."
                maxItems={4}
              />

              {/* Cues */}
              <ListEditor
                label="COACHING CUES"
                items={ex.cues || []}
                onSave={(items) => patch({ cues: items })}
                placeholder="Short cue (e.g. Ribs down)..."
                maxItems={6}
              />

              {/* Mistakes */}
              <ListEditor
                label="COMMON MISTAKES"
                items={ex.mistakes || []}
                onSave={(items) => patch({ mistakes: items })}
                placeholder="Common mistake..."
                maxItems={6}
              />

              {/* Meta fields */}
              <View style={styles.metaBlock}>
                <Text style={styles.metaLbl}>DEFAULT REST</Text>
                <View style={styles.chipRow}>
                  {[60, 90, 120, 180].map((n) => (
                    <Pressable key={n} onPress={() => patch({ default_rest_sec: n })} style={[styles.chip, ex.default_rest_sec === n && styles.chipOn]}>
                      <Text style={[styles.chipT, ex.default_rest_sec === n && { color: "#fff" }]}>{n}s</Text>
                    </Pressable>
                  ))}
                </View>

                <Text style={styles.metaLbl}>LOGGING TYPE</Text>
                <View style={styles.chipRow}>
                  {["weighted", "bodyweight", "cardio", "timer", "mobility"].map((t) => (
                    <Pressable key={t} onPress={() => patch({ logging_type: t })} style={[styles.chip, ex.logging_type === t && styles.chipOn]}>
                      <Text style={[styles.chipT, ex.logging_type === t && { color: "#fff" }]}>{t.toUpperCase()}</Text>
                    </Pressable>
                  ))}
                </View>

                <Text style={styles.metaLbl}>DIFFICULTY</Text>
                <View style={styles.chipRow}>
                  {["beginner", "intermediate", "advanced"].map((d) => (
                    <Pressable key={d} onPress={() => patch({ difficulty: d })} style={[styles.chip, ex.difficulty === d && styles.chipOn]}>
                      <Text style={[styles.chipT, ex.difficulty === d && { color: "#fff" }]}>{d.toUpperCase()}</Text>
                    </Pressable>
                  ))}
                </View>
              </View>

              {ex.content_source === "atlas" && !ex.approved && (
                <View style={styles.pendingCard}>
                  <Ionicons name="alert-circle" size={16} color={theme.color.amber} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.pendingT}>ATLAS-GENERATED · PENDING APPROVAL</Text>
                    <Text style={styles.pendingS}>Review the content above and approve so it becomes visible to clients.</Text>
                  </View>
                  <Pressable onPress={() => patch({ approved: true })} style={styles.approveBtn} testID="ex-approve">
                    <Text style={styles.approveT}>APPROVE</Text>
                  </Pressable>
                </View>
              )}

              <Pressable onPress={onSaved} style={styles.doneBtn} testID="ex-done">
                <Text style={styles.doneT}>DONE</Text>
                <Ionicons name="checkmark" size={14} color="#fff" />
              </Pressable>
            </ScrollView>
          </View>
        </KeyboardAvoidingView>
      </View>
    </Modal>
  );
}

function ListEditor({ label, items, onSave, placeholder, maxItems }: {
  label: string; items: string[]; onSave: (items: string[]) => void; placeholder: string; maxItems: number;
}) {
  const [local, setLocal] = React.useState<string[]>(items);
  React.useEffect(() => { setLocal(items); }, [items]);
  const setAt = (i: number, v: string) => setLocal((s) => s.map((x, j) => (j === i ? v : x)));
  const add = () => setLocal((s) => (s.length < maxItems ? [...s, ""] : s));
  const remove = (i: number) => setLocal((s) => s.filter((_, j) => j !== i));

  const dirty = JSON.stringify(local) !== JSON.stringify(items);

  return (
    <View style={styles.listBlock}>
      <View style={styles.listHead}>
        <Text style={styles.listLbl}>{label}</Text>
        {dirty && (
          <Pressable onPress={() => onSave(local.filter((x) => x.trim()))} style={styles.saveBtn}>
            <Text style={styles.saveT}>SAVE</Text>
          </Pressable>
        )}
      </View>
      {local.map((val, i) => (
        <View key={i} style={styles.listRow}>
          <View style={styles.listNum}><Text style={styles.listNumT}>{i + 1}</Text></View>
          <TextInput
            value={val} onChangeText={(t) => setAt(i, t)}
            placeholder={placeholder} placeholderTextColor={theme.color.textDim}
            style={styles.listInput} multiline
          />
          <Pressable onPress={() => remove(i)} hitSlop={8}>
            <Ionicons name="close-circle" size={16} color={theme.color.textDim} />
          </Pressable>
        </View>
      ))}
      {local.length < maxItems && (
        <Pressable onPress={add} style={styles.addBtn}>
          <Ionicons name="add-circle" size={14} color={theme.color.brand} />
          <Text style={styles.addT}>ADD ITEM</Text>
        </Pressable>
      )}
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/*  Styles                                                                    */
/* -------------------------------------------------------------------------- */
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: {
    flexDirection: "row", alignItems: "center", gap: 12,
    padding: 20, borderBottomWidth: 1, borderBottomColor: theme.color.divider,
  },
  eyebrow: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 2 },
  title: { color: theme.color.text, fontSize: 18, fontWeight: "800", marginTop: 3 },
  brandRed: { color: theme.color.brand, fontWeight: "900" },
  countPill: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 6, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand },
  batchBtn: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand, marginRight: 8 },
  batchBtnT: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },
  countPillT: { color: theme.color.brand, fontSize: 12, fontWeight: "900" },
  searchWrap: {
    flexDirection: "row", alignItems: "center", gap: 8,
    marginHorizontal: 20, marginTop: 10,
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  searchInput: { flex: 1, color: theme.color.text, fontSize: 13 },
  body: { padding: 16, paddingBottom: 40 },

  exRow: {
    flexDirection: "row", alignItems: "center", gap: 12,
    padding: 12, marginBottom: 8, borderRadius: 10,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  exScore: { width: 40, alignItems: "center" },
  exThumb: { width: 44, height: 44, borderRadius: 8, marginRight: 8, backgroundColor: theme.color.surface2 },
  exThumbEmpty: { alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: theme.color.border, borderStyle: "dashed" },
  exScoreT: { color: theme.color.amber, fontSize: 13, fontWeight: "900" },
  exName: { color: theme.color.text, fontSize: 13, fontWeight: "800" },
  exFlagRow: { flexDirection: "row", flexWrap: "wrap", gap: 4, marginTop: 5 },
  flag: {
    flexDirection: "row", alignItems: "center", gap: 3,
    paddingHorizontal: 5, paddingVertical: 2, borderRadius: 3,
  },
  flagOn: { backgroundColor: "rgba(34, 197, 94, 0.12)" },
  flagOff: { backgroundColor: theme.color.surface3 },
  flagT: { color: theme.color.textDim, fontSize: 8, fontWeight: "900", letterSpacing: 1 },

  sheetRoot: { flex: 1, justifyContent: "flex-end" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.75)" },
  sheet: {
    maxHeight: "92%", backgroundColor: theme.color.surface,
    borderTopLeftRadius: 20, borderTopRightRadius: 20,
    borderWidth: 1, borderColor: theme.color.border,
  },
  sheetHead: {
    flexDirection: "row", alignItems: "center", gap: 10,
    padding: 16, borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  sheetEyebrow: { color: theme.color.brand, fontSize: 9, fontWeight: "900", letterSpacing: 2 },
  sheetTitle: { color: theme.color.text, fontSize: 16, fontWeight: "900", marginTop: 3 },

  actionRow: { flexDirection: "row", gap: 8, marginBottom: 16 },
  actionPrimary: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    paddingVertical: 10, borderRadius: 8, backgroundColor: theme.color.brand,
  },
  actionPrimaryT: { color: "#fff", fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },
  actionSecondary: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    paddingHorizontal: 14, paddingVertical: 10, borderRadius: 8,
    borderWidth: 1, borderColor: theme.color.brand,
  },
  actionSecondaryT: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },

  imgPreview: { width: "100%", height: 200, borderRadius: 10, marginBottom: 16 },

  listBlock: { marginBottom: 18 },
  listHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 8 },
  listLbl: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 2 },
  saveBtn: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 4, backgroundColor: theme.color.brand },
  saveT: { color: "#fff", fontSize: 9, fontWeight: "900", letterSpacing: 1.5 },
  listRow: {
    flexDirection: "row", alignItems: "flex-start", gap: 8,
    padding: 8, marginBottom: 6, borderRadius: 6,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  listNum: { width: 22, height: 22, borderRadius: 11, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand, alignItems: "center", justifyContent: "center", marginTop: 4 },
  listNumT: { color: theme.color.brand, fontSize: 10, fontWeight: "900" },
  listInput: { flex: 1, color: theme.color.text, fontSize: 13, minHeight: 34 },
  addBtn: { flexDirection: "row", alignItems: "center", gap: 6, justifyContent: "center", paddingVertical: 8, borderRadius: 6, borderWidth: 1, borderColor: theme.color.brand, borderStyle: "dashed" },
  addT: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },

  metaBlock: { marginBottom: 16 },
  metaLbl: { color: theme.color.textMuted, fontSize: 9, fontWeight: "900", letterSpacing: 2, marginBottom: 6, marginTop: 8 },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  chipOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipT: { color: theme.color.text, fontSize: 10, fontWeight: "700" },

  pendingCard: { flexDirection: "row", alignItems: "center", gap: 10, padding: 12, marginBottom: 10, borderRadius: 10, backgroundColor: "rgba(245, 158, 11, 0.12)", borderWidth: 1, borderColor: theme.color.amber },
  pendingT: { color: theme.color.amber, fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },
  pendingS: { color: theme.color.textMuted, fontSize: 11, marginTop: 3 },
  approveBtn: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6, backgroundColor: theme.color.amber },
  approveT: { color: "#000", fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },

  doneBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    marginTop: 12, paddingVertical: 12, borderRadius: 10,
    backgroundColor: theme.color.brand,
  },
  doneT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 2 },
});
