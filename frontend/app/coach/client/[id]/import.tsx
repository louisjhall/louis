/**
 * Monthly Programme Import — Coach screen
 *
 * Route: /coach/client/[id]/import
 *
 * A no-frills paste-JSON → preview → apply flow.
 *   1. Coach pastes a ChatGPT-generated JSON envelope.
 *   2. Preview button hits `/api/coach/programme-import/preview` and
 *      renders a per-workout summary table with warnings, conflicts and
 *      counters.
 *   3. Apply Programme button hits `/api/coach/programme-import/apply`,
 *      then surfaces a success banner with a link back to the client's
 *      workspace so the imported month is immediately reviewable.
 *
 * The design language matches the rest of the coach dashboard (dark
 * surface, crimson brand accent, 8pt spacing). All heavy lifting is on
 * the backend — this screen is a thin driver.
 */
import React, { useCallback, useMemo, useState } from "react";
import {
  View,
  Text,
  Pressable,
  StyleSheet,
  ScrollView,
  TextInput,
  ActivityIndicator,
  Platform,
} from "react-native";
import { useRouter, useLocalSearchParams } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

// ---------------------------------------------------------------------------
// Types — mirror the backend response shape (see MONTHLY_PROGRAMME_JSON_IMPORT_DESIGN.md §3.2)
// ---------------------------------------------------------------------------

type PerWorkoutWarning = {
  code: string;
  section?: string;
  exercise_index?: number;
  raw_name?: string;
  matched?: string;
  score?: number;
  reason?: string;
};

type PerWorkoutError = {
  code: string;
  message?: string;
  raw_name?: string;
  existing_workout_id?: string;
  existing_source?: string;
};

type PerWorkoutCounts = {
  warmup: number;
  main: number;
  cooldown: number;
  supersets: number;
  circuits: number;
  emom_amrap: number;
  media_queue_new_items: number;
};

type PerWorkout = {
  date: string;
  title: string;
  workout_type: string;
  status: "ready" | "blocked" | "skip" | "already_imported";
  warnings: PerWorkoutWarning[];
  errors: PerWorkoutError[];
  conflict?: {
    has_conflict: boolean;
    action: string;
    existing_workout_id?: string;
    existing_source?: string;
  } | null;
  counts: PerWorkoutCounts;
};

type PreviewResponse = {
  preview_id: string;
  expires_at: string;
  meta: {
    client_id: string;
    client_email: string;
    client_display: string;
    month: string;
    workout_count: number;
    days_covered: number;
    override_policy: string;
    out_of_month_dates: string[];
  };
  summary: {
    workouts_ready: number;
    workouts_blocked: number;
    workouts_skipped: number;
    exercises_resolved: number;
    exercises_direct_id: number;
    exercises_fuzzy_substituted: number;
    exercises_new_drafts: number;
    media_queue_new_items: number;
    date_conflicts: number;
    supersets: number;
    circuits: number;
    emom_amrap: number;
  };
  per_workout: PerWorkout[];
  blocking_errors: number;
  next_actions: string[];
  schema_id: string;
};

type ApplyResult = {
  date: string;
  status: string;
  workout_id?: string;
  replaced_workout_id?: string | null;
  drafts_created?: number;
  media_queue_added?: number;
  reason?: string;
};

type ApplyResponse = {
  ok: boolean;
  preview_id: string;
  client_id: string;
  client_email: string;
  month: string;
  counters: {
    inserted: number;
    replaced: number;
    skipped: number;
    already_imported: number;
    failed: number;
    drafts_created: number;
    media_queue_added: number;
  };
  workout_ids: string[];
  results: ApplyResult[];
};

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

const STATUS_STYLES: Record<PerWorkout["status"], { bg: string; fg: string; label: string }> = {
  ready: { bg: "#0B3B1E", fg: "#34D399", label: "READY" },
  blocked: { bg: "#3B0B12", fg: "#FCA5A5", label: "BLOCKED" },
  skip: { bg: "#33280B", fg: "#FCD34D", label: "SKIP" },
  already_imported: { bg: "#1F2937", fg: "#93C5FD", label: "ALREADY IMPORTED" },
};

function StatusPill({ status }: { status: PerWorkout["status"] }) {
  const s = STATUS_STYLES[status] || STATUS_STYLES.ready;
  return (
    <View style={[styles.pill, { backgroundColor: s.bg }]}>
      <Text style={[styles.pillText, { color: s.fg }]}>{s.label}</Text>
    </View>
  );
}

function SummaryStat({ label, value, tone }: { label: string; value: number | string; tone?: "brand" | "ok" | "warn" | "muted" }) {
  const color =
    tone === "brand" ? theme.color.brand :
    tone === "ok" ? theme.color.green :
    tone === "warn" ? theme.color.amber :
    theme.color.textMuted;
  return (
    <View style={styles.stat}>
      <Text style={[styles.statValue, { color }]}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

function humanCode(code: string): string {
  switch (code) {
    case "fuzzy_match": return "Fuzzy match";
    case "unresolved_exercise": return "Unresolved — will draft";
    case "unknown_exercise_id": return "Unknown exercise id";
    case "missing_ref": return "Missing ref";
    case "invalid_group_type": return "Invalid group type";
    case "invalid_workout_type": return "Invalid workout type";
    case "conflict_reject": return "Existing workout (reject policy)";
    case "conflict_manual": return "Existing manual workout";
    case "conflict_completed": return "Existing completed workout";
    case "empty_main": return "No main exercises";
    default: return code;
  }
}

// ---------------------------------------------------------------------------
// Screen
// ---------------------------------------------------------------------------

export default function MonthlyImportScreen() {
  const router = useRouter();
  const { id: clientId } = useLocalSearchParams<{ id: string }>();
  const insets = useSafeAreaInsets();

  const [jsonText, setJsonText] = useState("");
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [applyResult, setApplyResult] = useState<ApplyResponse | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedWorkout, setExpandedWorkout] = useState<string | null>(null);

  const clearAll = useCallback(() => {
    setJsonText("");
    setPreview(null);
    setApplyResult(null);
    setError(null);
    setExpandedWorkout(null);
  }, []);

  const runPreview = useCallback(async () => {
    setError(null);
    setPreview(null);
    setApplyResult(null);
    setExpandedWorkout(null);

    const raw = jsonText.trim();
    if (!raw) {
      setError("Paste your programme JSON first.");
      return;
    }
    let envelope: any;
    try {
      envelope = JSON.parse(raw);
    } catch (e: any) {
      setError(`Invalid JSON — ${e?.message || String(e)}`);
      return;
    }

    setPreviewing(true);
    try {
      const res = await api<PreviewResponse>(
        "/coach/programme-import/preview",
        { method: "POST", body: envelope },
      );
      setPreview(res);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setPreviewing(false);
    }
  }, [jsonText]);

  const runApply = useCallback(async () => {
    if (!preview) return;
    setError(null);
    setApplying(true);
    try {
      const res = await api<ApplyResponse>(
        "/coach/programme-import/apply",
        { method: "POST", body: { preview_id: preview.preview_id } },
      );
      setApplyResult(res);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setApplying(false);
    }
  }, [preview]);

  const goToWorkspace = useCallback(() => {
    if (!clientId) return;
    router.push(`/coach/client/${clientId}/workspace`);
  }, [clientId, router]);

  // ------------------------------------------------------------------
  // Derived state
  // ------------------------------------------------------------------
  const canApply = useMemo(() => {
    if (!preview || applyResult) return false;
    return preview.blocking_errors === 0 && preview.summary.workouts_ready > 0;
  }, [preview, applyResult]);

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------
  return (
    <View style={[styles.root, { paddingTop: insets.top }]}>
      {/* Header */}
      <View style={styles.header}>
        <Pressable
          onPress={() => router.back()}
          style={styles.backBtn}
          hitSlop={8}
          accessibilityLabel="Back"
        >
          <Ionicons name="chevron-back" size={22} color={theme.color.text} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.headerTitle}>Monthly Import</Text>
          <Text style={styles.headerSubtitle}>
            Paste a ChatGPT-generated month of workouts. Preview then apply.
          </Text>
        </View>
      </View>

      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={{ padding: 16, paddingBottom: 96 }}
        keyboardShouldPersistTaps="handled"
      >
        {/* Success banner (after successful apply) */}
        {applyResult && applyResult.ok && (
          <View style={styles.successBanner}>
            <View style={styles.successIcon}>
              <Ionicons name="checkmark-circle" size={28} color={theme.color.green} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.successTitle}>Programme imported</Text>
              <Text style={styles.successBody}>
                {applyResult.counters.inserted} inserted
                {applyResult.counters.replaced > 0 ? ` · ${applyResult.counters.replaced} replaced` : ""}
                {applyResult.counters.already_imported > 0 ? ` · ${applyResult.counters.already_imported} already imported` : ""}
                {applyResult.counters.skipped > 0 ? ` · ${applyResult.counters.skipped} skipped` : ""}
                {applyResult.counters.drafts_created > 0 ? ` · ${applyResult.counters.drafts_created} new drafts` : ""}
                {applyResult.counters.media_queue_added > 0 ? ` · ${applyResult.counters.media_queue_added} media queued` : ""}
              </Text>
              <View style={{ flexDirection: "row", marginTop: 10, gap: 8, flexWrap: "wrap" }}>
                <Pressable onPress={goToWorkspace} style={styles.primaryBtn}>
                  <Ionicons name="calendar-outline" size={16} color={theme.color.onBrand} />
                  <Text style={styles.primaryBtnText}>Open calendar</Text>
                </Pressable>
                <Pressable onPress={clearAll} style={styles.secondaryBtn}>
                  <Ionicons name="add-circle-outline" size={16} color={theme.color.text} />
                  <Text style={styles.secondaryBtnText}>Import another</Text>
                </Pressable>
              </View>
              {(applyResult.results || []).some((r) => r.status !== "inserted" && r.status !== "replaced") && (
                <View style={{ marginTop: 12 }}>
                  <Text style={styles.applyResultsHeader}>Per-day results</Text>
                  {(applyResult.results || []).map((r) => (
                    <Text key={r.date} style={styles.applyResultsLine}>
                      • {r.date} — <Text style={{ color: theme.color.textHi }}>{r.status}</Text>
                      {r.reason ? ` (${r.reason})` : ""}
                    </Text>
                  ))}
                </View>
              )}
            </View>
          </View>
        )}

        {/* JSON input */}
        {!applyResult && (
          <View style={styles.card}>
            <View style={styles.cardHeaderRow}>
              <Text style={styles.cardTitle}>Programme JSON</Text>
              {jsonText.length > 0 && (
                <Pressable
                  onPress={clearAll}
                  hitSlop={6}
                  style={styles.linkBtn}
                >
                  <Text style={styles.linkText}>Clear</Text>
                </Pressable>
              )}
            </View>
            <TextInput
              value={jsonText}
              onChangeText={setJsonText}
              placeholder='Paste the full JSON envelope here — starts with `{ "$schema": "crewfit://programme-import/v1", ... }`.'
              placeholderTextColor={theme.color.textDim}
              multiline
              textAlignVertical="top"
              autoCapitalize="none"
              autoCorrect={false}
              spellCheck={false}
              style={styles.textarea}
            />
            <Text style={styles.helper}>
              {jsonText.length > 0
                ? `${jsonText.length.toLocaleString()} characters`
                : "Tip: use the CrewFit ChatGPT prompt (see docs/MONTHLY_PROGRAMME_CHATGPT_PROMPT.md) so the JSON is guaranteed to match the schema."}
            </Text>

            <View style={styles.actionRow}>
              <Pressable
                onPress={runPreview}
                disabled={previewing || !jsonText.trim()}
                style={[
                  styles.primaryBtn,
                  (previewing || !jsonText.trim()) && styles.btnDisabled,
                ]}
              >
                {previewing ? (
                  <ActivityIndicator color={theme.color.onBrand} size="small" />
                ) : (
                  <Ionicons name="eye-outline" size={16} color={theme.color.onBrand} />
                )}
                <Text style={styles.primaryBtnText}>
                  {previewing ? "Previewing…" : "Preview"}
                </Text>
              </Pressable>
            </View>
          </View>
        )}

        {/* Error banner */}
        {error && (
          <View style={styles.errorBanner}>
            <Ionicons name="alert-circle" size={20} color={theme.color.red} />
            <Text style={styles.errorText} selectable>
              {error}
            </Text>
          </View>
        )}

        {/* Preview summary */}
        {preview && !applyResult && (
          <>
            <View style={[styles.card, { marginTop: 12 }]}>
              <View style={styles.cardHeaderRow}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.cardTitle}>Preview</Text>
                  <Text style={styles.cardSubtitle}>
                    {preview.meta.client_display} · {preview.meta.month} ·
                    {" "}{preview.meta.workout_count} workouts · policy: {preview.meta.override_policy}
                  </Text>
                </View>
              </View>

              <View style={styles.statsRow}>
                <SummaryStat label="Ready" value={preview.summary.workouts_ready} tone="ok" />
                <SummaryStat label="Blocked" value={preview.summary.workouts_blocked} tone={preview.summary.workouts_blocked > 0 ? "warn" : "muted"} />
                <SummaryStat label="Skipped" value={preview.summary.workouts_skipped} tone="muted" />
                <SummaryStat label="Direct" value={preview.summary.exercises_direct_id} tone="muted" />
                <SummaryStat label="Fuzzy" value={preview.summary.exercises_fuzzy_substituted} tone={preview.summary.exercises_fuzzy_substituted > 0 ? "warn" : "muted"} />
                <SummaryStat label="Drafts" value={preview.summary.exercises_new_drafts} tone={preview.summary.exercises_new_drafts > 0 ? "warn" : "muted"} />
                <SummaryStat label="Media+" value={preview.summary.media_queue_new_items} tone="muted" />
                <SummaryStat label="Supersets" value={preview.summary.supersets} tone="muted" />
                <SummaryStat label="Circuits" value={preview.summary.circuits} tone="muted" />
                <SummaryStat label="EMOM/AMRAP" value={preview.summary.emom_amrap} tone="muted" />
              </View>

              {preview.next_actions && preview.next_actions.length > 0 && (
                <View style={styles.nextActionsBox}>
                  <Text style={styles.nextActionsHeader}>Next actions</Text>
                  {preview.next_actions.map((n, i) => (
                    <Text key={i} style={styles.nextActionsLine}>• {n}</Text>
                  ))}
                </View>
              )}
            </View>

            {/* Per-workout table */}
            <View style={[styles.card, { marginTop: 12 }]}>
              <Text style={styles.cardTitle}>Workouts</Text>
              <View style={{ marginTop: 8 }}>
                {preview.per_workout.map((w) => {
                  const isOpen = expandedWorkout === w.date;
                  const warnCount = w.warnings.length;
                  const errCount = w.errors.length;
                  const groupBits: string[] = [];
                  if (w.counts.supersets > 0) groupBits.push(`${w.counts.supersets}× superset`);
                  if (w.counts.circuits > 0) groupBits.push(`${w.counts.circuits}× circuit`);
                  if (w.counts.emom_amrap > 0) groupBits.push(`${w.counts.emom_amrap}× EMOM/AMRAP`);

                  return (
                    <View key={w.date} style={styles.workoutRow}>
                      <Pressable
                        onPress={() =>
                          setExpandedWorkout(isOpen ? null : w.date)
                        }
                        style={styles.workoutRowHeader}
                      >
                        <View style={{ flex: 1 }}>
                          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                            <Text style={styles.workoutDate}>{w.date}</Text>
                            <StatusPill status={w.status} />
                          </View>
                          <Text style={styles.workoutTitle} numberOfLines={1}>
                            {w.title}
                          </Text>
                          <Text style={styles.workoutMeta} numberOfLines={1}>
                            {w.workout_type} · wu {w.counts.warmup}  main {w.counts.main}  cd {w.counts.cooldown}
                            {groupBits.length > 0 ? ` · ${groupBits.join(", ")}` : ""}
                            {w.counts.media_queue_new_items > 0 ? ` · +${w.counts.media_queue_new_items} media` : ""}
                          </Text>
                        </View>
                        <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                          {errCount > 0 && (
                            <View style={[styles.chip, { backgroundColor: "#3B0B12" }]}>
                              <Text style={[styles.chipText, { color: theme.color.red }]}>{errCount} err</Text>
                            </View>
                          )}
                          {warnCount > 0 && (
                            <View style={[styles.chip, { backgroundColor: "#33280B" }]}>
                              <Text style={[styles.chipText, { color: theme.color.amber }]}>{warnCount} warn</Text>
                            </View>
                          )}
                          <Ionicons
                            name={isOpen ? "chevron-up" : "chevron-down"}
                            size={18}
                            color={theme.color.textMuted}
                          />
                        </View>
                      </Pressable>

                      {isOpen && (
                        <View style={styles.workoutDetail}>
                          {/* Conflict info */}
                          {w.conflict && w.conflict.has_conflict && (
                            <View style={styles.detailLine}>
                              <Ionicons
                                name={w.conflict.action === "already_imported" ? "checkmark-done-outline" : "warning-outline"}
                                size={14}
                                color={theme.color.amber}
                              />
                              <Text style={styles.detailText}>
                                Conflict → <Text style={{ color: theme.color.textHi }}>{w.conflict.action}</Text>
                                {w.conflict.existing_workout_id ? ` (existing: ${w.conflict.existing_workout_id.slice(0, 8)})` : ""}
                              </Text>
                            </View>
                          )}

                          {/* Errors */}
                          {w.errors.map((e, i) => (
                            <View key={`e${i}`} style={styles.detailLine}>
                              <Ionicons name="close-circle" size={14} color={theme.color.red} />
                              <Text style={styles.detailText}>
                                <Text style={{ color: theme.color.red, fontWeight: "600" }}>
                                  {humanCode(e.code)}
                                </Text>
                                {e.message ? ` — ${e.message}` : ""}
                                {e.raw_name ? ` (“${e.raw_name}”)` : ""}
                              </Text>
                            </View>
                          ))}

                          {/* Warnings */}
                          {w.warnings.map((wn, i) => (
                            <View key={`w${i}`} style={styles.detailLine}>
                              <Ionicons name="alert-circle" size={14} color={theme.color.amber} />
                              <Text style={styles.detailText}>
                                <Text style={{ color: theme.color.amber, fontWeight: "600" }}>
                                  {humanCode(wn.code)}
                                </Text>
                                {wn.raw_name ? ` — “${wn.raw_name}”` : ""}
                                {wn.matched ? ` → “${wn.matched}”` : ""}
                                {typeof wn.score === "number" ? ` (score ${wn.score})` : ""}
                              </Text>
                            </View>
                          ))}

                          {/* Empty state */}
                          {w.warnings.length === 0 && w.errors.length === 0 && !w.conflict?.has_conflict && (
                            <Text style={[styles.detailText, { fontStyle: "italic" }]}>
                              No warnings — clean import.
                            </Text>
                          )}
                        </View>
                      )}
                    </View>
                  );
                })}
              </View>
            </View>

            {/* Apply CTA */}
            <View style={{ marginTop: 16, gap: 8 }}>
              {!canApply && preview.blocking_errors > 0 && (
                <View style={styles.warningBanner}>
                  <Ionicons name="warning" size={18} color={theme.color.red} />
                  <Text style={styles.warningText}>
                    {preview.blocking_errors} workout{preview.blocking_errors === 1 ? "" : "s"} blocked. Fix the errors above (rename exercises, delete existing manual workouts, or change the override_policy) and preview again.
                  </Text>
                </View>
              )}
              {!canApply && preview.blocking_errors === 0 && preview.summary.workouts_ready === 0 && (
                <View style={styles.warningBanner}>
                  <Ionicons name="information-circle" size={18} color={theme.color.amber} />
                  <Text style={styles.warningText}>
                    Nothing ready to import — all workouts are already imported or being skipped.
                  </Text>
                </View>
              )}
              <Pressable
                onPress={runApply}
                disabled={!canApply || applying}
                style={[
                  styles.applyBtn,
                  (!canApply || applying) && styles.btnDisabled,
                ]}
              >
                {applying ? (
                  <ActivityIndicator color={theme.color.onBrand} />
                ) : (
                  <Ionicons name="cloud-upload-outline" size={18} color={theme.color.onBrand} />
                )}
                <Text style={styles.applyBtnText}>
                  {applying ? "Applying…" : `Apply Programme (${preview.summary.workouts_ready} workouts)`}
                </Text>
              </Pressable>
              <Text style={styles.applyHint}>
                Preview id: <Text style={{ color: theme.color.textHi }}>{preview.preview_id}</Text> · expires {new Date(preview.expires_at).toLocaleTimeString()}
              </Text>
            </View>
          </>
        )}
      </ScrollView>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.bg },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: theme.color.border,
    gap: 12,
    backgroundColor: theme.color.surface,
  },
  backBtn: {
    width: 32, height: 32, alignItems: "center", justifyContent: "center",
    borderRadius: 16,
  },
  headerTitle: {
    color: theme.color.text,
    fontSize: 18,
    fontWeight: "700",
    letterSpacing: 0.2,
  },
  headerSubtitle: {
    color: theme.color.textMuted,
    fontSize: 12,
    marginTop: 2,
  },
  card: {
    backgroundColor: theme.color.card,
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.color.border,
    padding: 16,
  },
  cardHeaderRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 10,
  },
  cardTitle: {
    color: theme.color.text,
    fontSize: 15,
    fontWeight: "700",
    letterSpacing: 0.2,
  },
  cardSubtitle: {
    color: theme.color.textMuted,
    fontSize: 12,
    marginTop: 3,
  },
  textarea: {
    minHeight: 220,
    maxHeight: 400,
    backgroundColor: theme.color.surface2,
    borderRadius: 8,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.color.border,
    padding: 12,
    color: theme.color.text,
    fontFamily: Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }),
    fontSize: 12,
    lineHeight: 16,
  },
  helper: {
    color: theme.color.textDim,
    fontSize: 11,
    marginTop: 6,
  },
  actionRow: {
    flexDirection: "row",
    justifyContent: "flex-end",
    marginTop: 12,
    gap: 8,
  },
  primaryBtn: {
    backgroundColor: theme.color.brand,
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 10,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  primaryBtnText: {
    color: theme.color.onBrand,
    fontWeight: "700",
    fontSize: 13,
    letterSpacing: 0.2,
  },
  secondaryBtn: {
    backgroundColor: theme.color.surface3,
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 10,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.color.border,
  },
  secondaryBtnText: {
    color: theme.color.text,
    fontWeight: "600",
    fontSize: 13,
  },
  linkBtn: { paddingVertical: 4, paddingHorizontal: 4 },
  linkText: { color: theme.color.textMuted, fontSize: 12 },
  btnDisabled: { opacity: 0.4 },

  errorBanner: {
    marginTop: 12,
    backgroundColor: "#3B0B12",
    borderRadius: 8,
    padding: 12,
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 10,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: "#7A1122",
  },
  errorText: {
    color: theme.color.text,
    fontSize: 12,
    lineHeight: 16,
    flex: 1,
  },

  warningBanner: {
    backgroundColor: theme.color.surface2,
    borderRadius: 8,
    padding: 12,
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 10,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.color.border,
  },
  warningText: {
    color: theme.color.text,
    fontSize: 12,
    lineHeight: 16,
    flex: 1,
  },

  successBanner: {
    backgroundColor: "#0B2A1A",
    borderRadius: 12,
    padding: 16,
    flexDirection: "row",
    gap: 12,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: "#065F46",
    marginBottom: 12,
  },
  successIcon: { paddingTop: 2 },
  successTitle: {
    color: theme.color.text,
    fontWeight: "700",
    fontSize: 15,
  },
  successBody: {
    color: theme.color.textMuted,
    fontSize: 12,
    marginTop: 4,
    lineHeight: 16,
  },
  applyResultsHeader: {
    color: theme.color.text,
    fontSize: 12,
    fontWeight: "600",
    marginBottom: 4,
  },
  applyResultsLine: {
    color: theme.color.textMuted,
    fontSize: 11,
    lineHeight: 15,
  },

  statsRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 12,
    marginTop: 4,
  },
  stat: { minWidth: 84 },
  statValue: {
    fontSize: 20,
    fontWeight: "800",
    letterSpacing: 0.2,
  },
  statLabel: {
    fontSize: 11,
    color: theme.color.textDim,
    marginTop: 2,
    textTransform: "uppercase",
    letterSpacing: 0.6,
  },
  nextActionsBox: {
    marginTop: 14,
    padding: 12,
    borderRadius: 8,
    backgroundColor: theme.color.surface2,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.color.border,
  },
  nextActionsHeader: {
    color: theme.color.text,
    fontSize: 12,
    fontWeight: "700",
    marginBottom: 4,
    textTransform: "uppercase",
    letterSpacing: 0.6,
  },
  nextActionsLine: {
    color: theme.color.textMuted,
    fontSize: 12,
    lineHeight: 17,
  },

  workoutRow: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: theme.color.divider,
  },
  workoutRowHeader: {
    paddingVertical: 12,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  workoutDate: {
    color: theme.color.text,
    fontSize: 13,
    fontWeight: "700",
    letterSpacing: 0.2,
  },
  workoutTitle: {
    color: theme.color.text,
    fontSize: 13,
    marginTop: 2,
  },
  workoutMeta: {
    color: theme.color.textMuted,
    fontSize: 11,
    marginTop: 3,
  },
  workoutDetail: {
    paddingBottom: 12,
    paddingLeft: 4,
    gap: 6,
  },
  detailLine: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 6,
  },
  detailText: {
    color: theme.color.textMuted,
    fontSize: 12,
    lineHeight: 17,
    flex: 1,
  },

  chip: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 12,
  },
  chipText: {
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.4,
  },
  pill: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 12,
  },
  pillText: {
    fontSize: 11,
    fontWeight: "800",
    letterSpacing: 0.6,
  },

  applyBtn: {
    backgroundColor: theme.color.brand,
    borderRadius: 10,
    paddingVertical: 14,
    paddingHorizontal: 16,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
  },
  applyBtnText: {
    color: theme.color.onBrand,
    fontWeight: "800",
    fontSize: 15,
    letterSpacing: 0.4,
  },
  applyHint: {
    color: theme.color.textDim,
    fontSize: 11,
    textAlign: "center",
  },
});
