import { useCallback, useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator } from "react-native";
import { useLocalSearchParams, useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { useAuth } from "@/src/lib/auth";
import { theme, loadColor } from "@/src/lib/theme";
import { ExerciseThumbnail } from "@/src/components/ExerciseThumbnail";
import { StatusBadge, deriveStatus, statusMeta } from "@/src/components/StatusBadge";
import { RealityModal } from "@/src/components/RealityModal";
import { ModePickerModal } from "@/src/components/ModePickerModal";
import { AIHeroImage } from "@/src/components/AIHeroImage";
import { WhatsAppSupportButton } from "@/src/components/WhatsAppSupportButton";
import { PostWorkoutRatingSheet } from "@/src/components/PostWorkoutRatingSheet";
import { getRememberedMode, WorkoutMode } from "@/src/lib/workoutMode";

const PREFERRED_CHANNELS = [
  "Jeff Nippard", "Squat University", "Renaissance Periodization",
  "Athlean-X", "Built With Science",
];

type VariantKey = "green" | "amber" | "red";
const VARIANT_LABELS: Record<VariantKey, { label: string; sub: string; color: string; icon: keyof typeof Ionicons.glyphMap }> = {
  green: { label: "FULL",     sub: "Planned session",  color: "#2f9e6c", icon: "flash" },
  amber: { label: "LIGHTER",  sub: "~65% volume",      color: "#e5a337", icon: "battery-half" },
  red:   { label: "RECOVERY", sub: "Mobility & breath", color: "#c85450", icon: "leaf" },
};

export default function WorkoutDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const isCoach = user?.role === "coach";
  const [w, setW] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [rpe, setRpe] = useState("");
  const [realityOpen, setRealityOpen] = useState(false);
  const [modeOpen, setModeOpen] = useState(false);
  // Iter 94i — dismissed flag lets the client tap "Start Bodyweight Session"
  // and hide the fallback banner so the workout looks calm again. Server-side
  // state (needs_coach_review) is unchanged — Louis still sees the task.
  const [dismissed, setDismissed] = useState(false);
  // Traffic-light variants — client-only. Coach view always sees Green.
  const [variant, setVariant] = useState<VariantKey>("green");
  const [variants, setVariants] = useState<any>(null);

  // Lazily fetch variants (backfills on the server if the doc has empty stubs).
  useEffect(() => {
    if (!w?.id || isCoach) return;
    const v = w.variants;
    if (v && v.green && v.amber && v.red) { setVariants(v); return; }
    let cancelled = false;
    api<any>(`/workouts/${w.id}/variants`)
      .then((r) => { if (!cancelled) setVariants(r?.variants || null); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [w?.id, isCoach]);

  // Overlay the selected variant on top of the base workout for rendering.
  // The base `w` is preserved for edit/save/complete paths.
  const view = useMemo(() => {
    if (!w) return null;
    if (isCoach || variant === "green" || !variants) return w;
    const vv = variants[variant];
    if (!vv || typeof vv !== "object") return w;
    return {
      ...w,
      title: vv.title ?? w.title,
      duration_min: vv.duration_min ?? w.duration_min,
      focus: vv.focus ?? w.focus,
      warmup: vv.warmup ?? w.warmup,
      exercises: vv.exercises ?? w.exercises,
      rationale: vv.rationale ?? w.rationale,
      _variant_intensity_note: vv.intensity_note || null,
    };
  }, [w, variants, variant, isCoach]);

  // Fire-and-forget: log the selected variant for coach dashboards.
  const pickVariant = useCallback((next: VariantKey) => {
    setVariant(next);
    if (!w?.id || isCoach) return;
    api(`/workouts/${w.id}/select-variant`, { method: "POST", body: { variant: next } }).catch(() => {});
  }, [w?.id, isCoach]);

  const startWorkout = useCallback(async () => {
    // Route to the mode the user has remembered, or open the picker.
    const remembered = await getRememberedMode();
    if (remembered === "guided") {
      router.push(`/workout/${w.id}/guided` as any);
    } else if (remembered === "manual") {
      router.push(`/workout/${w.id}/play` as any);
    } else {
      setModeOpen(true);
    }
  }, [router, w]);

  const chooseMode = (mode: WorkoutMode) => {
    setModeOpen(false);
    if (mode === "guided") {
      router.push(`/workout/${w.id}/guided` as any);
    } else {
      router.push(`/workout/${w.id}/play` as any);
    }
  };

  const load = useCallback(async () => {
    setLoading(true);
    try { setW(await api<any>(`/workouts/${id}`)); } finally { setLoading(false); }
  }, [id]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  // Note: we intentionally do NOT preload videos here anymore. The preview
  // shows image-only cards; videos are loaded lazily when the user opens
  // the exercise detail modal, guided mode, or manual play mode.

  const updateEx = (idx: number, key: string, val: any) => {
    setW((prev: any) => ({ ...prev, exercises: prev.exercises.map((e: any, i: number) => (i === idx ? { ...e, [key]: val } : e)) }));
  };
  const removeEx = (idx: number) => setW((p: any) => ({ ...p, exercises: p.exercises.filter((_: any, i: number) => i !== idx) }));
  const addEx = () => setW((p: any) => ({ ...p, exercises: [...(p.exercises || []), { name: "New Exercise", sets: 3, reps: "10", rest_sec: 60, rpe: 7, notes: "" }] }));

  const save = async (extra: any = {}) => {
    setSaving(true);
    try {
      const updated = await api<any>(`/workouts/${id}`, { method: "PATCH", body: { exercises: w.exercises, title: w.title, coach_notes: w.coach_notes, location: w.location, ...extra } });
      setW(updated); setEditing(false);
    } finally { setSaving(false); }
  };
  const approve = () => save({ approved: true });
  const toggleLock = () => save({ coach_locked: !w.coach_locked });
  const cycleLoad = () => {
    const order = ["green", "amber", "red", "blue", "purple", "grey"];
    const next = order[(order.indexOf(w.day_load) + 1) % order.length];
    save({ day_load: next });
  };
  const [rateOpen, setRateOpen] = useState(false);
  const complete = async () => {
    // Iter 101 — quick post-workout rating sheet before firing /complete.
    setRateOpen(true);
  };
  const onRatingDone = async (result: { rating: any; completedDoc: any }) => {
    setRateOpen(false);
    if (result.completedDoc) setW(result.completedDoc);
    // Route back to home so the client sees an updated dashboard.
    router.replace("/(client)/home" as any);
  };

  if (loading || !w) {
    return <View style={{ flex: 1, backgroundColor: theme.color.surface, alignItems: "center", justifyContent: "center" }}><ActivityIndicator color={theme.color.brand} /></View>;
  }

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} testID="workout-back"><Ionicons name="chevron-back" size={26} color={theme.color.text} /></Pressable>
        <View style={[styles.loadPill, { backgroundColor: loadColor(w.day_load) }]}>
          <Text style={styles.loadPillText}>{String(w.day_load || "").toUpperCase()}</Text>
        </View>
        <Pressable testID="edit-toggle" onPress={() => setEditing((e) => !e)}>
          <Text style={{ color: theme.color.brand, letterSpacing: 2, fontWeight: "800", fontSize: 12 }}>{editing ? "DONE" : "EDIT"}</Text>
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 160 }}>
        <AIHeroImage
          ctx={{
            workout_type: (view.focus || "").toLowerCase().includes("run") ? "endurance"
              : (view.focus || "").toLowerCase().includes("strength") ? "strength"
              : "strength",
            phase: w.event_phase || undefined,
          }}
          style={styles.workoutBanner}
        >
          <View style={styles.workoutBannerInner}>
            <Text style={styles.workoutBannerEyebrow}>{String(view.focus || "SESSION").toUpperCase()}</Text>
            <Text style={styles.workoutBannerTitle} numberOfLines={2}>{view.title}</Text>
          </View>
        </AIHeroImage>
        <Text style={styles.date}>{w.date}</Text>
        {(() => {
          const s = deriveStatus(w);
          const m = statusMeta(s);
          return (
            <View style={{ marginTop: 4, marginBottom: 8 }}>
              <StatusBadge status={s} onPress={() => alert(m.desc)} />
            </View>
          );
        })()}
        {editing ? (
          <TextInput value={w.title} onChangeText={(v) => setW({ ...w, title: v })} style={styles.titleInput} testID="edit-title" />
        ) : (
          <Text style={styles.title}>{view.title}</Text>
        )}
        <View style={styles.metaRow}>
          <View style={styles.metaChipRow}>
            <Ionicons name="location" size={11} color={theme.color.textMuted} />
            <Text style={styles.metaChipT}>{w.location || "Home Workout"}</Text>
          </View>
          <View style={styles.metaChipRow}>
            <Ionicons name="time" size={11} color={theme.color.textMuted} />
            <Text style={styles.metaChipT}>{view.duration_min}min</Text>
          </View>
          <Text style={styles.metaChip}>{String(view.focus || "").toUpperCase()}</Text>
          {w.key_session && (
            <View style={[styles.metaChipRow, { backgroundColor: theme.color.brand, borderColor: theme.color.brand }]}>
              <Ionicons name="star" size={11} color="#fff" />
              <Text style={[styles.metaChipT, { color: "#fff" }]}>KEY SESSION</Text>
            </View>
          )}
          {w.event_phase && <Text style={[styles.metaChip, { color: theme.color.brand, borderColor: theme.color.brand }]}>{String(w.event_phase).toUpperCase().replace("_", " ")}</Text>}
        </View>

        {!isCoach && !editing && variants && (
          <View style={styles.variantRow} testID="variant-row">
            {(Object.keys(VARIANT_LABELS) as VariantKey[]).map((k) => {
              const meta = VARIANT_LABELS[k];
              const active = variant === k;
              return (
                <Pressable
                  key={k}
                  testID={`variant-chip-${k}`}
                  onPress={() => pickVariant(k)}
                  style={[
                    styles.variantChip,
                    active && { borderColor: meta.color, backgroundColor: meta.color },
                  ]}
                >
                  <Ionicons name={meta.icon} size={13} color={active ? "#fff" : meta.color} />
                  <View style={{ marginLeft: 6 }}>
                    <Text style={[styles.variantChipLabel, active && { color: "#fff" }]}>{meta.label}</Text>
                    <Text style={[styles.variantChipSub, active && { color: "rgba(255,255,255,0.85)" }]}>{meta.sub}</Text>
                  </View>
                </Pressable>
              );
            })}
          </View>
        )}
        {!isCoach && variant !== "green" && view._variant_intensity_note ? (
          <View style={styles.variantNote}>
            <Ionicons name="information-circle" size={14} color={VARIANT_LABELS[variant].color} />
            <Text style={styles.variantNoteText}>{view._variant_intensity_note}</Text>
          </View>
        ) : null}

        {w.override_applied || w.override_generated ? (
          <View style={styles.overrideBanner}>
            <Text style={styles.overrideLabel}>PLAN ADJUSTED</Text>
            <Text style={styles.overrideText}>{w.override_reason || "Your day edit changed this workout."}</Text>
          </View>
        ) : null}

        {!isCoach && (
          <Pressable
            testID="reality-btn-workout"
            onPress={() => setRealityOpen(true)}
            style={styles.realityBtn}
          >
            <View style={styles.realityBtnLeft}>
              <View style={styles.realityIconWrapW}>
                <Ionicons name="compass" size={20} color={theme.color.brand} />
              </View>
              <View>
                <Text style={styles.realityTitleW}>TODAY&apos;S REALITY</Text>
                <Text style={styles.realitySubW}>What has changed today?</Text>
              </View>
            </View>
            <Ionicons name="arrow-forward" size={14} color={theme.color.brand} />
          </Pressable>
        )}

        {view.change_reason && !dismissed && (
          <View
            style={[
              styles.changeReason,
              (view.needs_coach_review || view.validation_status === "adjusted_fallback") && styles.changeReasonAlert,
            ]}
            testID="workout-change-reason"
          >
            <Ionicons
              name={view.needs_coach_review ? "alert-circle" : "information-circle"}
              size={18}
              color={view.needs_coach_review ? theme.color.amber : theme.color.brand}
            />
            <View style={{ flex: 1 }}>
              <Text style={[styles.changeReasonLabel, view.needs_coach_review && { color: theme.color.amber }]}>
                {view.validation_status === "adjusted_fallback"
                  ? "SESSION ADJUSTED"
                  : "WHY THIS CHANGED"}
              </Text>
              <Text style={styles.changeReasonText}>{view.change_reason}</Text>

              {/* Iter 94i — Client-facing action buttons for fallback / needs-review sessions */}
              {!isCoach && (view.needs_coach_review || view.validation_status === "adjusted_fallback") && (
                <View style={styles.actionsRow} testID="workout-fallback-actions">
                  <Pressable
                    style={styles.actionBtn}
                    onPress={() => {
                      // "Start Bodyweight Session" just dismisses the banner and
                      // scrolls to the first exercise — the bodyweight-safe
                      // version is already loaded into view.exercises.
                      // We use a `key` state to fade the banner rather than fully
                      // remove it, so tests can still find it if needed.
                      setDismissed(true);
                    }}
                    testID="workout-fallback-start"
                  >
                    <Ionicons name="play" size={14} color={theme.color.brand} />
                    <Text style={styles.actionBtnLabel}>START BODYWEIGHT SESSION</Text>
                  </Pressable>
                  <Pressable
                    style={styles.actionBtn}
                    onPress={() => router.push("/(client)/messages" as any)}
                    testID="workout-fallback-message"
                  >
                    <Ionicons name="chatbubble-ellipses" size={14} color={theme.color.brand} />
                    <Text style={styles.actionBtnLabel}>MESSAGE LOUIS</Text>
                  </Pressable>
                  <Pressable
                    style={styles.actionBtn}
                    onPress={() => router.push("/(client)/profile" as any)}
                    testID="workout-fallback-equipment"
                  >
                    <Ionicons name="barbell" size={14} color={theme.color.brand} />
                    <Text style={styles.actionBtnLabel}>UPDATE EQUIPMENT</Text>
                  </Pressable>
                </View>
              )}
              {/* Iter 94k — WhatsApp support option for fallback/needs-review workouts */}
              {!isCoach && (view.needs_coach_review || view.validation_status === "adjusted_fallback") && (
                <View style={{ marginTop: 10 }} testID="workout-fallback-whatsapp">
                  <WhatsAppSupportButton
                    screen="workout_detail"
                    context={
                      view.validation_status === "adjusted_fallback"
                        ? "workout_fallback_used"
                        : "workout_needs_review"
                    }
                    workoutId={view.id}
                    variant="outline"
                    showCaption={false}
                  />
                </View>
              )}
            </View>
          </View>
        )}

        {view.rationale && (
          <View style={styles.rationale}>
            <Text style={styles.rLabel}>WHY THIS SESSION?</Text>
            <Text style={styles.rText}>{view.rationale}</Text>
          </View>
        )}

        {/* Iter 102 — Layover context reason line. Shown when this workout
            was built around a detected layover day. Louis-branded, no AI
            wording. */}
        {view.layover_context?.client_reason ? (
          <View style={styles.layoverCtx} testID="workout-layover-context">
            <View style={styles.layoverCtxHead}>
              <Text style={styles.layoverCtxEyebrow}>LAYOVER CONTEXT</Text>
              {view.layover_context.needs_destination_review ? (
                <Text style={styles.layoverCtxFlag}>NEEDS COACH REVIEW</Text>
              ) : null}
            </View>
            <Text style={styles.layoverCtxBody}>
              {view.layover_context.client_reason}
            </Text>
          </View>
        ) : null}

        {isCoach && editing && (
          <Pressable testID="cycle-load" onPress={cycleLoad} style={styles.cycleBtn}>
            <Text style={{ color: theme.color.brand, fontWeight: "800", letterSpacing: 1.5 }}>CYCLE LOAD → NEXT</Text>
          </Pressable>
        )}

        {view.warmup?.length > 0 && (
          <>
            <Text style={styles.sect}>WARM-UP</Text>
            {view.warmup.map((wu: any, i: number) => (
              <View key={i} style={styles.warmupRow}>
                <Text style={styles.warmupName}>{wu.name}</Text>
                <Text style={styles.warmupTime}>{wu.duration_sec || 30}s</Text>
              </View>
            ))}
          </>
        )}

        <Text style={styles.sect}>EXERCISES</Text>
        {((editing ? w.exercises : view.exercises) || []).map((ex: any, idx: number) => (
          <View key={idx} style={styles.exCard} testID={`ex-${idx}`}>
            {editing ? (
              <>
                <TextInput style={styles.exNameInput} value={ex.name} onChangeText={(v) => updateEx(idx, "name", v)} />
                <View style={styles.exRow}>
                  <TextInput style={styles.exSmall} value={String(ex.sets ?? "")} onChangeText={(v) => updateEx(idx, "sets", parseInt(v) || 0)} keyboardType="number-pad" placeholder="sets" placeholderTextColor={theme.color.textDim} />
                  <TextInput style={styles.exSmall} value={String(ex.reps ?? "")} onChangeText={(v) => updateEx(idx, "reps", v)} placeholder="reps" placeholderTextColor={theme.color.textDim} />
                  <TextInput style={styles.exSmall} value={String(ex.rest_sec ?? "")} onChangeText={(v) => updateEx(idx, "rest_sec", parseInt(v) || 0)} keyboardType="number-pad" placeholder="rest" placeholderTextColor={theme.color.textDim} />
                  <TextInput style={styles.exSmall} value={String(ex.rpe ?? "")} onChangeText={(v) => updateEx(idx, "rpe", parseInt(v) || 0)} keyboardType="number-pad" placeholder="RPE" placeholderTextColor={theme.color.textDim} />
                  <Pressable onPress={() => removeEx(idx)} testID={`remove-ex-${idx}`}><Ionicons name="trash" size={20} color={theme.color.red} /></Pressable>
                </View>
              </>
            ) : (
              // Preview cards: image only (no auto-mounted video). Client taps
              // the thumbnail (or starts the workout) to reach the video.
              <View style={styles.exPreviewRow}>
                <ExerciseThumbnail name={ex.name} testIDPrefix={`ex-thumb-${idx}`} />
                <View style={{ flex: 1, minWidth: 0 }}>
                  <Text style={styles.exName} numberOfLines={2}>{ex.name}</Text>
                  <Text style={styles.exMeta}>
                    {ex.sets} × {ex.reps} · rest {ex.rest_sec}s{ex.rpe ? ` · RPE ${ex.rpe}` : ""}
                  </Text>
                  {ex.notes ? <Text style={styles.exNotes} numberOfLines={2}>{ex.notes}</Text> : null}
                  {ex.equipment_check === "fail" && ex.equipment_reason ? (
                    <View style={styles.eqWarn} testID={`ex-eq-warn-${idx}`}>
                      <Ionicons name="warning" size={11} color={theme.color.amber} />
                      <Text style={styles.eqWarnText} numberOfLines={2}>{ex.equipment_reason}</Text>
                    </View>
                  ) : null}
                </View>
              </View>
            )}
          </View>
        ))}
        {editing && (
          <Pressable testID="add-ex" onPress={addEx} style={styles.addExBtn}>
            <Ionicons name="add" size={18} color={theme.color.brand} />
            <Text style={{ color: theme.color.brand, marginLeft: 6, fontWeight: "700" }}>ADD EXERCISE</Text>
          </Pressable>
        )}

        {w.alternatives && (
          <>
            <Text style={styles.sect}>ALTERNATIVES</Text>
            {(["home", "hotel", "no_equipment", "easier", "harder"] as const).map((k) => (
              w.alternatives[k] ? (
                <View key={k} style={styles.altRow}>
                  <Text style={styles.altKey}>{k.replace("_", " ").toUpperCase()}</Text>
                  <Text style={styles.altVal}>{w.alternatives[k]}</Text>
                </View>
              ) : null
            ))}
          </>
        )}

        {isCoach && (
          <View style={{ marginTop: theme.space.lg }}>
            <Text style={styles.sect}>COACH NOTES</Text>
            <TextInput testID="coach-notes" style={[styles.exNameInput, { minHeight: 80 }]} value={w.coach_notes || ""} onChangeText={(v) => setW({ ...w, coach_notes: v })} placeholder="Add note for client…" placeholderTextColor={theme.color.textDim} multiline />
            <Pressable testID="lock-toggle" onPress={toggleLock} style={styles.lockBtn}>
              <Ionicons name={w.coach_locked ? "lock-closed" : "lock-open"} size={14} color={theme.color.brand} />
              <Text style={styles.lockText}>{w.coach_locked ? "COACH-LOCKED — click to unlock" : "LOCK (protect from auto-regenerate)"}</Text>
            </Pressable>
          </View>
        )}
        {!isCoach && w.coach_notes && (
          <View style={styles.rationale}>
            <Text style={styles.rLabel}>COACH NOTE</Text>
            <Text style={styles.rText}>{w.coach_notes}</Text>
          </View>
        )}

        {!isCoach && !w.completed && (
          <View style={styles.compBox}>
            <Text style={styles.sectSm}>RATE THIS SESSION (RPE 1-10)</Text>
            <TextInput style={styles.exNameInput} value={rpe} onChangeText={setRpe} keyboardType="number-pad" placeholder="7" placeholderTextColor={theme.color.textDim} testID="rpe-input" />
          </View>
        )}
      </ScrollView>

      <View style={styles.sticky}>
        {editing ? (
          <Pressable testID="save-workout" onPress={() => save()} disabled={saving} style={[styles.cta, saving && { opacity: 0.6 }]}>
            {saving ? <ActivityIndicator color="#fff" /> : <Text style={styles.ctaText}>SAVE CHANGES</Text>}
          </Pressable>
        ) : isCoach ? (
          <View style={{ flexDirection: "row", gap: 8 }}>
            <Pressable testID="reject-workout" onPress={() => save({ approved: false })} style={[styles.ctaSecondary, { flex: 1 }]}><Text style={styles.ctaSecondaryText}>REJECT</Text></Pressable>
            <Pressable testID="approve-workout" onPress={approve} disabled={saving || w.approved} style={[styles.cta, { flex: 1 }, w.approved && { backgroundColor: theme.color.green }]}>
              <Text style={styles.ctaText}>{w.approved ? "APPROVED ✓" : "APPROVE"}</Text>
            </Pressable>
          </View>
        ) : (
          <View style={{ flexDirection: "row", gap: 8 }}>
            <Pressable testID="atlas-play" onPress={startWorkout} disabled={w.completed} style={[styles.cta, { flex: 2 }, w.completed && { backgroundColor: theme.color.green }]}>
              <Text style={styles.ctaText}>{w.completed ? "COMPLETED ✓" : "START WORKOUT →"}</Text>
            </Pressable>
            <Pressable testID="complete-workout" onPress={complete} disabled={saving || w.completed} style={[styles.ctaSecondary, { flex: 1 }, saving && { opacity: 0.6 }]}>
              {saving ? <ActivityIndicator color={theme.color.brand} /> : <Text style={styles.ctaSecondaryText}>{w.completed ? "DONE" : "MARK DONE"}</Text>}
            </Pressable>
          </View>
        )}
      </View>
      <RealityModal
        visible={realityOpen}
        date={w?.date || null}
        onClose={() => setRealityOpen(false)}
        onApplied={() => { setRealityOpen(false); load(); }}
      />
      <ModePickerModal
        visible={modeOpen}
        onClose={() => setModeOpen(false)}
        onChoose={chooseMode}
      />
      <PostWorkoutRatingSheet
        visible={rateOpen}
        workoutId={id as string}
        workoutTitle={w?.title}
        extraPayload={{
          completed_exercises: w?.exercises || [],
          rpe: rpe ? parseInt(rpe) : null,
        }}
        onClose={() => setRateOpen(false)}
        onDone={onRatingDone}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  loadPill: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: theme.radius.sm },
  loadPillText: { color: "#fff", fontWeight: "800", fontSize: 10, letterSpacing: 1.5 },
  date: { color: theme.color.textMuted, letterSpacing: 2, fontSize: 11, fontWeight: "700" },
  title: { color: theme.color.text, fontSize: 30, fontWeight: "900", marginTop: 6, letterSpacing: -0.5 },
  titleInput: { color: theme.color.text, fontSize: 26, fontWeight: "900", marginTop: 6, backgroundColor: theme.color.surface2, padding: 12, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border },
  metaRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 8 },
  metaChip: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1, fontWeight: "700", backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, paddingHorizontal: 8, paddingVertical: 4, borderRadius: theme.radius.pill },
  metaChipRow: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, paddingHorizontal: 8, paddingVertical: 4, borderRadius: theme.radius.pill },
  metaChipT: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1, fontWeight: "700", fontFamily: theme.font.textSemi },
  variantRow: { flexDirection: "row", gap: 6, marginTop: theme.space.md },
  variantChip: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center",
    borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border,
    backgroundColor: theme.color.surface2, paddingVertical: 10, paddingHorizontal: 8, minHeight: 48,
  },
  variantChipLabel: { color: theme.color.text, fontSize: 11, fontWeight: "800", letterSpacing: 1 },
  variantChipSub: { color: theme.color.textDim, fontSize: 9, marginTop: 1 },
  variantNote: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: theme.color.surface2, borderRadius: theme.radius.md,
    borderWidth: 1, borderColor: theme.color.border,
    paddingVertical: 10, paddingHorizontal: 12, marginTop: theme.space.sm,
  },
  variantNoteText: { color: theme.color.textMuted, fontSize: 12, flex: 1, lineHeight: 16 },
  realityIconWrapW: { width: 34, height: 34, borderRadius: 17, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand, alignItems: "center", justifyContent: "center" },
  workoutBanner: { height: 180, borderRadius: 14, marginBottom: 14, overflow: "hidden" },
  workoutBannerInner: { flex: 1, justifyContent: "flex-end", padding: 14, gap: 4 },
  workoutBannerEyebrow: { color: theme.color.brand, fontSize: 10, letterSpacing: 2.5, fontWeight: "900", fontFamily: theme.font.textSemi },
  workoutBannerTitle: { color: theme.color.text, fontSize: 22, letterSpacing: 0.4, fontWeight: "900", fontFamily: theme.font.display },
  rationale: { marginTop: theme.space.lg, padding: theme.space.md, backgroundColor: theme.color.brandTint, borderRadius: theme.radius.md, borderLeftWidth: 3, borderLeftColor: theme.color.brand },
  // Iter 102 — Layover context block
  layoverCtx: {
    marginTop: theme.space.md,
    padding: theme.space.md,
    borderRadius: theme.radius.md,
    backgroundColor: theme.color.surface2,
    borderWidth: 1,
    borderColor: theme.color.border,
  },
  layoverCtxHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 6 },
  layoverCtxEyebrow: { color: theme.color.brand, fontSize: 9, fontWeight: "900", letterSpacing: 1.5 },
  layoverCtxFlag: {
    color: theme.color.amber,
    fontSize: 8, fontWeight: "900", letterSpacing: 1,
    borderWidth: 1, borderColor: theme.color.amber,
    paddingHorizontal: 5, paddingVertical: 2, borderRadius: 3,
  },
  layoverCtxBody: { color: theme.color.text, fontSize: 12, lineHeight: 17 },
  changeReason: {
    flexDirection: "row", alignItems: "flex-start", gap: 8,
    marginTop: theme.space.md, padding: theme.space.md,
    backgroundColor: "rgba(163,24,46,0.08)",
    borderRadius: theme.radius.md,
    borderLeftWidth: 3, borderLeftColor: theme.color.brand,
  },
  changeReasonLabel: {
    fontSize: 10, letterSpacing: 1.2, fontWeight: "800",
    color: theme.color.brand, marginBottom: 4,
  },
  changeReasonText: {
    fontSize: 12, color: theme.color.text, lineHeight: 17,
  },
  // Iter 94i — escalated styling when a workout has been adjusted to a
  // safe fallback. Amber border/background makes it unmissable + clearly
  // ties to the client-facing action buttons below.
  changeReasonAlert: {
    backgroundColor: "rgba(245,158,11,0.12)",
    borderLeftWidth: 3, borderLeftColor: theme.color.amber,
  },
  actionsRow: {
    flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 12,
  },
  actionBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingVertical: 8, paddingHorizontal: 10,
    borderRadius: 8,
    borderWidth: 1, borderColor: theme.color.brand,
    backgroundColor: theme.color.brandTint,
  },
  actionBtnLabel: {
    color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 0.5,
  },
  eqWarn: {
    flexDirection: "row", alignItems: "flex-start", gap: 4,
    marginTop: 6, paddingHorizontal: 6, paddingVertical: 4,
    borderRadius: 4,
    backgroundColor: "rgba(245,158,11,0.10)",
    borderLeftWidth: 2, borderLeftColor: theme.color.amber,
  },
  eqWarnText: {
    fontSize: 11, color: theme.color.textMuted, flex: 1, lineHeight: 15,
  },
  rLabel: { color: theme.color.brand, letterSpacing: 2, fontSize: 10, fontWeight: "800" },
  overrideBanner: { marginTop: theme.space.md, padding: theme.space.md, backgroundColor: "rgba(245, 158, 11, 0.12)", borderRadius: theme.radius.md, borderLeftWidth: 3, borderLeftColor: theme.color.amber },
  overrideLabel: { color: theme.color.amber, letterSpacing: 2, fontSize: 10, fontWeight: "900" },
  overrideText: { color: theme.color.text, marginTop: 6, fontSize: 13, lineHeight: 19 },
  realityBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    marginTop: theme.space.md,
    paddingVertical: 12, paddingHorizontal: theme.space.md,
    borderRadius: theme.radius.md,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.brand,
  },
  realityBtnLeft: { flexDirection: "row", alignItems: "center", gap: 10 },
  realityEmojiW: { fontSize: 20 },
  realityTitleW: { color: theme.color.text, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  realitySubW: { color: theme.color.textMuted, fontSize: 10, marginTop: 1 },
  rText: { color: theme.color.text, marginTop: 6, fontSize: 13, lineHeight: 19 },
  cycleBtn: { marginTop: theme.space.md, padding: 10, borderRadius: theme.radius.sm, borderWidth: 1, borderColor: theme.color.brand, alignItems: "center" },
  sect: { color: theme.color.textMuted, letterSpacing: 2, fontSize: 11, fontWeight: "800", marginTop: theme.space.lg, marginBottom: theme.space.sm },
  sectSm: { color: theme.color.textMuted, letterSpacing: 1.5, fontSize: 10, fontWeight: "800" },
  warmupRow: { flexDirection: "row", justifyContent: "space-between", padding: 10, backgroundColor: theme.color.surface2, borderRadius: theme.radius.sm, borderWidth: 1, borderColor: theme.color.border, marginBottom: 4 },
  warmupName: { color: theme.color.text, fontSize: 13, fontWeight: "600" },
  warmupTime: { color: theme.color.brand, fontSize: 12, fontWeight: "700" },
  exCard: { padding: theme.space.md, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, marginBottom: theme.space.sm },
  exPreviewRow: { flexDirection: "row", gap: 12, alignItems: "flex-start" },
  exName: { color: theme.color.text, fontSize: 15, fontWeight: "800" },
  exMeta: { color: theme.color.brand, marginTop: 4, letterSpacing: 1, fontWeight: "600", fontSize: 13 },
  exNotes: { color: theme.color.textMuted, marginTop: 4, fontSize: 12 },
  demoBtn: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 8, paddingVertical: 6, paddingHorizontal: 10, borderRadius: theme.radius.sm, backgroundColor: theme.color.surface3, borderWidth: 1, borderColor: theme.color.border, alignSelf: "flex-start" },
  demoText: { color: theme.color.text, fontSize: 11, fontWeight: "700" },
  exNameInput: { color: theme.color.text, fontSize: 15, fontWeight: "700", backgroundColor: theme.color.surface3, padding: 10, borderRadius: theme.radius.sm, borderWidth: 1, borderColor: theme.color.border },
  exRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 8 },
  exSmall: { flex: 1, color: theme.color.text, backgroundColor: theme.color.surface3, padding: 8, borderRadius: theme.radius.sm, borderWidth: 1, borderColor: theme.color.border, textAlign: "center" },
  addExBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", padding: 12, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.brand, marginTop: 8 },
  altRow: { flexDirection: "row", padding: 10, backgroundColor: theme.color.surface2, borderRadius: theme.radius.sm, borderWidth: 1, borderColor: theme.color.border, marginBottom: 4 },
  altKey: { color: theme.color.brand, fontSize: 10, letterSpacing: 1.5, fontWeight: "800", width: 100 },
  altVal: { color: theme.color.text, fontSize: 12, flex: 1, marginLeft: 8 },
  lockBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, marginTop: 10, padding: 10, borderRadius: theme.radius.sm, borderWidth: 1, borderColor: theme.color.brand },
  lockText: { color: theme.color.brand, fontSize: 10, letterSpacing: 1.5, fontWeight: "800" },
  compBox: { marginTop: theme.space.lg },
  timerBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, marginTop: theme.space.lg, padding: 12, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.brand },
  timerText: { color: theme.color.brand, fontSize: 10, letterSpacing: 1.5, fontWeight: "800" },
  sticky: { position: "absolute", left: 0, right: 0, bottom: 0, padding: theme.space.lg, backgroundColor: theme.color.surface, borderTopWidth: 1, borderTopColor: theme.color.border },
  cta: { backgroundColor: theme.color.brand, paddingVertical: 16, borderRadius: theme.radius.md, alignItems: "center" },
  ctaText: { color: "#fff", fontWeight: "800", letterSpacing: 2, fontSize: 13 },
  ctaSecondary: { backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.red, paddingVertical: 16, borderRadius: theme.radius.md, alignItems: "center" },
  ctaSecondaryText: { color: theme.color.red, fontWeight: "800", letterSpacing: 2, fontSize: 13 },
});
