/**
 * Iter200 · Bulk-import modal for the coach On-Demand screen.
 *
 * Two-step flow:
 *   Step 1 — Upload JSON (100-workout array) + ZIP (100 thumbnails
 *            named w-001.jpg…w-100.jpg). Preview parsed item count +
 *            distinct categories.
 *   Step 2 — Confirm & import. Uploads the zip to the backend where it
 *            is unpacked into the bundled thumbnail dir. Then calls
 *            POST /on-demand/coach/items/bulk with the workout payload
 *            (thumbnail_filename derived from array position:
 *            index 0 → w-001.jpg, index 1 → w-002.jpg, ...).
 *
 * NOTE: Metro bundles thumbnails at BUILD time. Newly-uploaded files
 * appear in the current dev preview immediately but require a REDEPLOY
 * to reach production builds — the modal surfaces this note in Step 2.
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ScrollView,
  ActivityIndicator, Alert, Modal, Platform,
  Switch,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as DocumentPicker from "expo-document-picker";
import { theme } from "@/src/lib/theme";
import { api } from "@/src/lib/api";

const CANONICAL_CATEGORIES = [
  "Strength & Gym",
  "Hotel Room",
  "Aviation Mobility",
  "Core & Posture",
  "Cardio & Running",
  "Recovery & Low Energy",
  "Layover & Travel",
  "Pain Relief & Injury Support",
];

const CATEGORY_ALIASES: Record<string, string> = {
  "strength & gym": "Strength & Gym",
  "strength": "Strength & Gym", "gym": "Strength & Gym",
  "hotel room": "Hotel Room", "hotel room & small space": "Hotel Room", "hotel": "Hotel Room",
  "aviation mobility": "Aviation Mobility", "mobility": "Aviation Mobility",
  "core & posture": "Core & Posture", "core": "Core & Posture", "posture": "Core & Posture",
  "cardio & running": "Cardio & Running", "cardio": "Cardio & Running", "running": "Cardio & Running",
  "recovery & low energy": "Recovery & Low Energy", "recovery": "Recovery & Low Energy", "low energy": "Recovery & Low Energy",
  "layover & travel": "Layover & Travel", "layover": "Layover & Travel", "travel": "Layover & Travel",
  "pain relief & injury support": "Pain Relief & Injury Support", "pain relief": "Pain Relief & Injury Support", "injury support": "Pain Relief & Injury Support",
};

function slugify(t: string): string {
  return (t || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "untagged";
}
function canonCat(raw: string | null | undefined): string | null {
  if (!raw) return null;
  return CATEGORY_ALIASES[raw.trim().toLowerCase()] || null;
}

// Cross-platform base64 read for both native URIs and web blob: URIs. Same
// helper the coach on-demand editor uses.
async function fileUriToBase64(uri: string): Promise<string> {
  const res = await fetch(uri);
  const blob = await res.blob();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("read_failed"));
    reader.onload = () => {
      const s = String(reader.result || "");
      const idx = s.indexOf(",");
      resolve(idx >= 0 ? s.slice(idx + 1) : s);
    };
    reader.readAsDataURL(blob);
  });
}

async function fileUriToText(uri: string): Promise<string> {
  const res = await fetch(uri);
  return res.text();
}

// ---------------------------------------------------------------------------

type ParsedItem = {
  external_ref: string;
  title: string;
  description: string;
  category_slug: string | null;
  category_display: string | null;
  duration_seconds: number | null;
  workout_json: any;
  thumbnail_filename: string;
  equipment: string[];
};

type ParseResult = {
  items: ParsedItem[];
  categoryCounts: Record<string, number>;
  unknownCategories: string[];
};

function inferDurationSeconds(w: any): number | null {
  const blockSeconds = (rows: any[]): number => {
    let total = 0;
    for (const row of rows || []) {
      if (!row || typeof row !== "object") continue;
      if (row.kind === "group") {
        let inner = 0;
        for (const m of row.items || []) {
          if (m.duration_sec) inner += Number(m.duration_sec) || 0;
          else if (m.reps) {
            const s = String(m.reps).split("-")[0].split("/")[0];
            const n = Number.parseInt(s, 10);
            inner += Number.isFinite(n) ? n * 3 : 30;
          }
          inner += Number(m.rest_sec || 0) || 0;
        }
        const rounds = Number(row.rounds || 1) || 1;
        const restR = Number(row.rest_between_rounds_sec || 0) || 0;
        total += inner * rounds + restR * Math.max(0, rounds - 1);
      } else {
        let s = 0;
        if (row.duration_sec) s = Number(row.duration_sec) || 0;
        else if (row.reps) {
          const t = String(row.reps).split("-")[0].split("/")[0];
          const n = Number.parseInt(t, 10);
          s = Number.isFinite(n) ? n * 3 : 30;
        }
        const sets = Number(row.sets || 1) || 1;
        total += s * sets + (Number(row.rest_sec || 0) || 0) * Math.max(0, sets - 1);
      }
    }
    return total;
  };
  const t = blockSeconds(w?.warmup || []) + blockSeconds(w?.exercises || []) + blockSeconds(w?.cooldown || []);
  return t || null;
}

function parseWorkoutsPayload(raw: any): ParseResult {
  const rows: any[] = Array.isArray(raw)
    ? raw
    : Array.isArray(raw?.items) ? raw.items : [];
  const items: ParsedItem[] = [];
  const categoryCounts: Record<string, number> = {};
  const unknownSet: Set<string> = new Set();
  rows.forEach((row: any, idx: number) => {
    const catRaw = row?.category || row?.category_name || null;
    const cat = canonCat(catRaw);
    if (catRaw && !cat) unknownSet.add(String(catRaw));
    const displayCat = cat || (catRaw ? String(catRaw) : "Uncategorised");
    categoryCounts[displayCat] = (categoryCounts[displayCat] || 0) + 1;

    let durSec: number | null = null;
    if (row?.duration_min) durSec = Number(row.duration_min) * 60;
    else if (row?.duration_seconds) durSec = Number(row.duration_seconds);
    else durSec = inferDurationSeconds(row);

    const eqRaw = row?.equipment;
    const equipment: string[] = Array.isArray(eqRaw)
      ? eqRaw.map((s: any) => String(s).trim()).filter(Boolean)
      : typeof eqRaw === "string"
        ? eqRaw.split(",").map((s) => s.trim()).filter(Boolean)
        : [];

    items.push({
      external_ref: (row?.external_ref || `W-${String(idx + 1).padStart(3, "0")}`).trim(),
      title: (row?.title || `Workout ${idx + 1}`).trim(),
      description: (row?.description || "").trim(),
      category_slug: cat ? slugify(cat) : null,
      category_display: displayCat,
      duration_seconds: durSec,
      workout_json: {
        title: row?.title,
        workout_type: (row?.workout_type || "other").toLowerCase(),
        duration_min: row?.duration_min,
        location: row?.location,
        equipment_context: Array.isArray(eqRaw) ? eqRaw.join(", ") : row?.equipment_context || eqRaw,
        rpe: row?.rpe,
        coach_notes: row?.coach_notes || row?.notes,
        warmup: row?.warmup || [],
        exercises: row?.exercises || [],
        cooldown: row?.cooldown || [],
        external_ref: row?.external_ref,
      },
      thumbnail_filename: row?.thumbnail_filename || `w-${String(idx + 1).padStart(3, "0")}.jpg`,
      equipment,
    });
  });
  return { items, categoryCounts, unknownCategories: Array.from(unknownSet) };
}

// ---------------------------------------------------------------------------

export function BulkImportOnDemandModal({
  onClose, onImported,
}: {
  onClose: () => void;
  onImported: () => void;
}) {
  const [step, setStep] = useState<1 | 2>(1);

  // Step 1
  const [jsonFileName, setJsonFileName] = useState<string | null>(null);
  const [zipFileName, setZipFileName] = useState<string | null>(null);
  const [zipB64, setZipB64] = useState<string | null>(null);
  const [parseResult, setParseResult] = useState<ParseResult | null>(null);
  const [busy, setBusy] = useState<"json" | "zip" | null>(null);

  // Step 2
  const [publishNow, setPublishNow] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importStep, setImportStep] = useState<string | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [report, setReport] = useState<any | null>(null);
  const [thumbReport, setThumbReport] = useState<any | null>(null);

  const totalItems = parseResult?.items.length || 0;

  const pickJson = useCallback(async () => {
    setBusy("json");
    try {
      const res = await DocumentPicker.getDocumentAsync({
        type: ["application/json", "text/json", "*/*"],
        copyToCacheDirectory: true,
      });
      if (res.canceled) { setBusy(null); return; }
      const a = res.assets[0];
      const txt = await fileUriToText(a.uri);
      if (!txt.trim()) throw new Error("empty_file");
      let parsed: any;
      try { parsed = JSON.parse(txt); }
      catch (e: any) { throw new Error(`invalid_json: ${e?.message || e}`); }
      const result = parseWorkoutsPayload(parsed);
      if (result.items.length === 0) throw new Error("no_workouts_found_in_json");
      setJsonFileName(a.name);
      setParseResult(result);
    } catch (e: any) {
      Alert.alert("JSON parse failed", e?.message || String(e));
    } finally { setBusy(null); }
  }, []);

  const pickZip = useCallback(async () => {
    setBusy("zip");
    try {
      const res = await DocumentPicker.getDocumentAsync({
        type: ["application/zip", "application/x-zip-compressed", "*/*"],
        copyToCacheDirectory: true,
      });
      if (res.canceled) { setBusy(null); return; }
      const a = res.assets[0];
      const b64 = await fileUriToBase64(a.uri);
      if (!b64) throw new Error("empty_file");
      setZipFileName(a.name);
      setZipB64(b64);
    } catch (e: any) {
      Alert.alert("Zip read failed", e?.message || String(e));
    } finally { setBusy(null); }
  }, []);

  const canProceed = !!parseResult && !!zipB64 && totalItems > 0;

  const goToConfirm = useCallback(() => {
    // Iter200 · No `uxConfirm` here — nested `<Modal>` inside our own
    // `<Modal>` doesn't handle button clicks reliably on RN-Web 0.21
    // (the inner dialog renders but events are absorbed by the outer
    // scrim, so the promise never resolves and Step 2 never opens).
    // The item count is prominently shown in both the Step 1 preview
    // and the Step 2 summary card, so the extra confirmation adds
    // nothing besides breakage.
    setStep(2);
  }, []);

  const runImport = useCallback(async () => {
    // Guardrails that used to fail silently — surface a clear inline
    // error instead of returning quietly.
    if (!parseResult) {
      setImportError("No workouts parsed. Go back and pick a JSON file first.");
      return;
    }
    if (!zipB64) {
      setImportError("No thumbnails uploaded. Go back and pick a zip first.");
      return;
    }
    setImporting(true);
    setImportError(null);
    setReport(null);
    setThumbReport(null);
    try {
      // (1) Ensure the 8 canonical categories exist.
      setImportStep("Ensuring categories exist…");
      console.log("[BulkImport] step 1: taxonomy/ensure");
      await api("/on-demand/coach/taxonomy/ensure", {
        method: "POST",
        body: { categories: CANONICAL_CATEGORIES, tags: [] },
      });

      // (2) Upload the thumbnails zip. This can be tens of megabytes;
      // give the coach a heads-up if it's unusually large.
      const zipMb = Math.round((zipB64.length * 0.75) / 1024 / 1024);
      setImportStep(
        zipMb > 20
          ? `Uploading thumbnails (~${zipMb} MB) — this can take a minute…`
          : "Uploading thumbnails…",
      );
      console.log(`[BulkImport] step 2: thumbnails/bulk-upload (~${zipMb} MB base64)`);
      const tr = await api<any>("/on-demand/coach/thumbnails/bulk-upload", {
        method: "POST",
        body: { zip_b64: zipB64 },
      });
      console.log("[BulkImport] thumbnails written:", tr);
      setThumbReport(tr);

      // (3) POST workouts to the bulk endpoint.
      setImportStep(`Creating ${parseResult.items.length} workouts…`);
      console.log(`[BulkImport] step 3: items/bulk (${parseResult.items.length} items)`);
      const payload = {
        default_published: !!publishNow,
        items: parseResult.items.map((it) => ({
          external_ref: it.external_ref,
          title: it.title,
          description: it.description,
          category_slug: it.category_slug,
          tag_slugs: [],
          duration_seconds: it.duration_seconds,
          workout_json: it.workout_json,
          thumbnail_filename: it.thumbnail_filename,
          equipment: it.equipment,
          published: !!publishNow,
        })),
      };
      const r = await api<any>("/on-demand/coach/items/bulk", { method: "POST", body: payload });
      console.log("[BulkImport] items/bulk report:", r);
      setReport(r);
      setImportStep(null);
    } catch (e: any) {
      // RN-Web's Alert.alert can silently fail on some builds. Surface
      // the error inline in the modal AND log to console so the coach
      // (and devtools) always have visibility.
      const msg = e?.message || String(e);
      console.error("[BulkImport] failed:", e);
      setImportError(msg);
      setImportStep(null);
    } finally {
      setImporting(false);
    }
  }, [parseResult, zipB64, publishNow]);

  const closeAndRefresh = useCallback(() => {
    if (report) onImported();
    onClose();
  }, [report, onImported, onClose]);

  return (
    <Modal transparent animationType="slide" visible onRequestClose={closeAndRefresh}>
      <View style={styles.scrim}>
        <View style={styles.card}>
          <View style={styles.head}>
            <View style={{ flex: 1 }}>
              <Text style={styles.title}>BULK IMPORT</Text>
              <Text style={styles.sub}>{step === 1 ? "Step 1 · Upload files" : "Step 2 · Confirm & import"}</Text>
            </View>
            <Pressable onPress={closeAndRefresh} hitSlop={10} testID="od-bulk-close">
              <Ionicons name="close" size={22} color={theme.color.text} />
            </Pressable>
          </View>

          <ScrollView contentContainerStyle={styles.body}>
            {step === 1 ? (
              <>
                {/* JSON PICKER */}
                <Text style={styles.label}>WORKOUTS JSON</Text>
                <Pressable
                  onPress={pickJson}
                  style={[styles.pickBtn, jsonFileName && styles.pickBtnDone]}
                  testID="od-bulk-pick-json"
                  disabled={busy === "json"}
                >
                  <Ionicons name={jsonFileName ? "checkmark-circle" : "document-text-outline"} size={20}
                            color={jsonFileName ? theme.color.brand : theme.color.text} />
                  <Text style={styles.pickBtnT} numberOfLines={1}>
                    {busy === "json" ? "Reading…" : jsonFileName || "Choose .json file"}
                  </Text>
                </Pressable>

                {/* ZIP PICKER */}
                <Text style={[styles.label, { marginTop: 18 }]}>THUMBNAILS ZIP</Text>
                <Pressable
                  onPress={pickZip}
                  style={[styles.pickBtn, zipFileName && styles.pickBtnDone]}
                  testID="od-bulk-pick-zip"
                  disabled={busy === "zip"}
                >
                  <Ionicons name={zipFileName ? "checkmark-circle" : "folder-outline"} size={20}
                            color={zipFileName ? theme.color.brand : theme.color.text} />
                  <Text style={styles.pickBtnT} numberOfLines={1}>
                    {busy === "zip" ? "Reading…" : zipFileName || "Choose .zip of w-001.jpg … w-100.jpg"}
                  </Text>
                </Pressable>

                <Text style={styles.hint}>
                  Filenames must match `w-001.jpg` through `w-100.jpg`. Each image maps to the
                  workout at the same 1-indexed position in the JSON array.
                </Text>

                {/* PREVIEW */}
                {parseResult ? (
                  <View style={styles.preview}>
                    <Text style={styles.previewH}>PARSED PREVIEW</Text>
                    <Text style={styles.previewLine}>
                      <Text style={styles.previewNum}>{totalItems}</Text> workouts
                    </Text>
                    {Object.entries(parseResult.categoryCounts)
                      .sort((a, b) => (b[1] as number) - (a[1] as number))
                      .map(([cat, n]) => (
                        <Text key={cat} style={styles.previewRow}>
                          • {cat}: <Text style={styles.previewNum}>{n as number}</Text>
                        </Text>
                      ))}
                    {parseResult.unknownCategories.length > 0 ? (
                      <Text style={styles.previewWarn}>
                        ⚠️ Unknown categories will land as drafts without a bucket:
                        {" "}{parseResult.unknownCategories.join(", ")}
                      </Text>
                    ) : null}
                  </View>
                ) : null}
              </>
            ) : (
              <>
                {/* STEP 2 — CONFIRM */}
                <View style={styles.summaryBox}>
                  <Text style={styles.summaryH}>READY TO IMPORT</Text>
                  <Text style={styles.summaryLine}>
                    <Text style={styles.summaryNum}>{totalItems}</Text> workouts from{" "}
                    <Text style={styles.mono}>{jsonFileName}</Text>
                  </Text>
                  <Text style={styles.summaryLine}>
                    Thumbnails from <Text style={styles.mono}>{zipFileName}</Text> will be written to{" "}
                    <Text style={styles.mono}>frontend/assets/on-demand-thumbnails/</Text>
                  </Text>
                </View>

                <View style={styles.publishRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.publishTitle}>Publish immediately</Text>
                    <Text style={styles.publishSub}>
                      Off (default) = every workout imports as a DRAFT so you can review before
                      making them visible to members.
                    </Text>
                  </View>
                  <Switch
                    value={publishNow}
                    onValueChange={setPublishNow}
                    trackColor={{ true: theme.color.brand, false: "#555" }}
                    thumbColor="#fff"
                    testID="od-bulk-publish-toggle"
                  />
                </View>

                <View style={styles.noteBox}>
                  <Ionicons name="information-circle-outline" size={16} color={theme.color.text} />
                  <Text style={styles.noteText}>
                    Metro bundles thumbnails at BUILD time. New thumbnails appear in the current
                    dev preview immediately but require a REDEPLOY to reach production builds.
                  </Text>
                </View>

                {/* PROGRESS — visible only while an import is running. */}
                {importing && importStep ? (
                  <View style={styles.progressBox} testID="od-bulk-progress">
                    <ActivityIndicator color={theme.color.brand} />
                    <Text style={styles.progressText}>{importStep}</Text>
                  </View>
                ) : null}

                {/* INLINE ERROR — replaces the flaky Alert.alert. */}
                {importError ? (
                  <View style={styles.errorBox} testID="od-bulk-error">
                    <Ionicons name="alert-circle-outline" size={18} color="#EF4444" />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.errorTitle}>Import failed</Text>
                      <Text style={styles.errorText}>{importError}</Text>
                      <Text style={styles.errorHint}>
                        Open the browser devtools console for the full stack trace.
                      </Text>
                    </View>
                  </View>
                ) : null}

                {/* REPORT */}
                {report ? (
                  <View style={styles.reportBox} testID="od-bulk-report">
                    <Text style={styles.reportH}>IMPORT REPORT</Text>
                    <Text style={styles.reportRow}>
                      In: <Text style={styles.reportNum}>{report.summary?.total_in ?? 0}</Text>
                    </Text>
                    <Text style={styles.reportRow}>
                      Created: <Text style={[styles.reportNum, { color: "#4ADE80" }]}>{report.summary?.created ?? 0}</Text>
                    </Text>
                    <Text style={styles.reportRow}>
                      Skipped (duplicates): <Text style={[styles.reportNum, { color: "#F59E0B" }]}>{report.summary?.skipped ?? 0}</Text>
                    </Text>
                    <Text style={styles.reportRow}>
                      Errors: <Text style={[styles.reportNum, { color: report.summary?.errors ? "#EF4444" : theme.color.textMuted }]}>{report.summary?.errors ?? 0}</Text>
                    </Text>
                    {report.summary?.media_queue ? (
                      <Text style={styles.reportRow}>
                        Media queue: resolved={report.summary.media_queue.resolved} · new drafts=
                        {report.summary.media_queue.drafts_created} · queued for media=
                        {report.summary.media_queue.queued_missing_media}
                      </Text>
                    ) : null}
                    {thumbReport ? (
                      <Text style={styles.reportRow}>
                        Thumbnails written: <Text style={styles.reportNum}>{(thumbReport.written || []).length}</Text>
                        {(thumbReport.skipped || []).length ? ` · skipped: ${(thumbReport.skipped).length}` : ""}
                      </Text>
                    ) : null}
                    {(report.errors || []).slice(0, 5).map((e: any, i: number) => (
                      <Text key={i} style={styles.reportError}>
                        [{e.index}] {e.title}: {e.reason}
                      </Text>
                    ))}
                    {(report.errors || []).length > 5 ? (
                      <Text style={styles.reportError}>
                        …and {(report.errors || []).length - 5} more errors
                      </Text>
                    ) : null}
                  </View>
                ) : null}
              </>
            )}
          </ScrollView>

          {/* FOOTER — ACTIONS */}
          <View style={styles.foot}>
            {step === 1 ? (
              <>
                <Pressable onPress={closeAndRefresh} style={styles.footBtn} testID="od-bulk-cancel">
                  <Text style={styles.footBtnT}>CANCEL</Text>
                </Pressable>
                <Pressable
                  onPress={goToConfirm}
                  style={[styles.footBtn, styles.footBtnPrimary, !canProceed && styles.footBtnDisabled]}
                  disabled={!canProceed}
                  testID="od-bulk-next"
                >
                  <Text style={[styles.footBtnT, { color: "#fff" }]}>REVIEW & IMPORT</Text>
                </Pressable>
              </>
            ) : (
              <>
                <Pressable
                  onPress={() => setStep(1)}
                  style={styles.footBtn}
                  disabled={importing}
                  testID="od-bulk-back"
                >
                  <Text style={styles.footBtnT}>BACK</Text>
                </Pressable>
                {report ? (
                  <Pressable
                    onPress={closeAndRefresh}
                    style={[styles.footBtn, styles.footBtnPrimary]}
                    testID="od-bulk-done"
                  >
                    <Text style={[styles.footBtnT, { color: "#fff" }]}>DONE</Text>
                  </Pressable>
                ) : (
                  <Pressable
                    onPress={runImport}
                    style={[styles.footBtn, styles.footBtnPrimary, importing && styles.footBtnDisabled]}
                    disabled={importing}
                    testID="od-bulk-confirm"
                  >
                    {importing ? (
                      <ActivityIndicator color="#fff" />
                    ) : (
                      <Text style={[styles.footBtnT, { color: "#fff" }]}>
                        IMPORT {totalItems} {publishNow ? "PUBLISHED" : "DRAFTS"}
                      </Text>
                    )}
                  </Pressable>
                )}
              </>
            )}
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  scrim: {
    flex: 1, backgroundColor: "rgba(0,0,0,0.55)",
    justifyContent: "flex-end",
  },
  card: {
    backgroundColor: theme.color.surface,
    borderTopLeftRadius: 22, borderTopRightRadius: 22,
    maxHeight: "92%",
    ...Platform.select({
      ios: { shadowColor: "#000", shadowOpacity: 0.4, shadowRadius: 20, shadowOffset: { width: 0, height: -4 } },
      android: { elevation: 12 },
      default: {},
    }),
  },
  head: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: 20, paddingVertical: 16,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: theme.color.border,
  },
  title: { color: theme.color.text, fontSize: 18, fontWeight: "900", letterSpacing: 1.6 },
  sub: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1, marginTop: 3, fontWeight: "800" },

  body: { paddingHorizontal: 20, paddingVertical: 20, paddingBottom: 32 },
  label: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 1.5, fontWeight: "900", marginBottom: 8 },

  pickBtn: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 14, paddingVertical: 14, borderRadius: 12,
    borderWidth: 1, borderColor: theme.color.border,
    backgroundColor: theme.color.surface2,
  },
  pickBtnDone: { borderColor: theme.color.brand, borderWidth: 1.5 },
  pickBtnT: { color: theme.color.text, fontSize: 13, fontWeight: "700", flex: 1 },
  hint: { color: theme.color.textMuted, fontSize: 11, marginTop: 12, lineHeight: 16 },

  preview: {
    marginTop: 22, padding: 14, borderRadius: 12,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  previewH: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 1.5, fontWeight: "900", marginBottom: 8 },
  previewLine: { color: theme.color.text, fontSize: 15, fontWeight: "800", marginBottom: 6 },
  previewRow: { color: theme.color.text, fontSize: 12, marginTop: 2 },
  previewNum: { color: theme.color.brand, fontWeight: "900" },
  previewWarn: { color: "#F59E0B", fontSize: 11, marginTop: 10, lineHeight: 16 },

  summaryBox: {
    padding: 14, borderRadius: 12, backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
  },
  summaryH: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 1.5, fontWeight: "900", marginBottom: 8 },
  summaryLine: { color: theme.color.text, fontSize: 12, lineHeight: 18, marginTop: 4 },
  summaryNum: { color: theme.color.brand, fontWeight: "900", fontSize: 14 },
  mono: { fontFamily: Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }), fontSize: 11 },

  publishRow: {
    flexDirection: "row", alignItems: "center", gap: 12,
    marginTop: 18, padding: 14, borderRadius: 12,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  publishTitle: { color: theme.color.text, fontSize: 14, fontWeight: "800" },
  publishSub: { color: theme.color.textMuted, fontSize: 11, marginTop: 3, lineHeight: 16 },

  noteBox: {
    marginTop: 18, padding: 12, borderRadius: 10,
    flexDirection: "row", gap: 8,
    backgroundColor: "rgba(245,158,11,0.10)",
    borderWidth: 1, borderColor: "rgba(245,158,11,0.35)",
  },
  noteText: { color: theme.color.text, fontSize: 11, lineHeight: 16, flex: 1 },

  progressBox: {
    marginTop: 18, padding: 14, borderRadius: 10,
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
  },
  progressText: { color: theme.color.text, fontSize: 12, fontWeight: "700", flex: 1 },

  errorBox: {
    marginTop: 18, padding: 12, borderRadius: 10,
    flexDirection: "row", gap: 8, alignItems: "flex-start",
    backgroundColor: "rgba(239,68,68,0.10)",
    borderWidth: 1, borderColor: "rgba(239,68,68,0.45)",
  },
  errorTitle: { color: "#EF4444", fontSize: 12, fontWeight: "900", letterSpacing: 1 },
  errorText: { color: theme.color.text, fontSize: 12, lineHeight: 17, marginTop: 3 },
  errorHint: { color: theme.color.textMuted, fontSize: 10, lineHeight: 15, marginTop: 6, fontStyle: "italic" },

  reportBox: {
    marginTop: 20, padding: 14, borderRadius: 12,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  reportH: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 1.5, fontWeight: "900", marginBottom: 8 },
  reportRow: { color: theme.color.text, fontSize: 12, marginTop: 3 },
  reportNum: { color: theme.color.brand, fontWeight: "900" },
  reportError: { color: "#EF4444", fontSize: 11, marginTop: 5, lineHeight: 16 },

  foot: {
    flexDirection: "row", gap: 10,
    paddingHorizontal: 20, paddingVertical: 14,
    borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.color.border,
  },
  footBtn: {
    flex: 1, paddingVertical: 14, borderRadius: 12, alignItems: "center", justifyContent: "center",
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  footBtnPrimary: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  footBtnDisabled: { opacity: 0.5 },
  footBtnT: { color: theme.color.text, fontWeight: "900", letterSpacing: 1.2, fontSize: 12 },
});
