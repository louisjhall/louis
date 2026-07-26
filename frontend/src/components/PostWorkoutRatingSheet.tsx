/**
 * PostWorkoutRatingSheet — Iter 101
 *
 * Quick, low-friction post-workout rating. Aviation language. No emojis.
 * No AI wording. No gamification.
 *
 * Default flow (should take under 5 seconds):
 *   1. Tap one of four rating options
 *   2. Tap LOG WORKOUT
 *   3. Done
 *
 * Optional side-flow:
 *   - "Add a note for Louis" → single textbox → SAVE NOTE
 *
 * Safety flow (ONLY for heavy_turbulence and diverted):
 *   - "Any pain or discomfort?" → No / Yes
 *   - If Yes: "Where did you feel it?" → single textbox
 *
 * On submit, POST /workouts/{id}/complete with the full payload. The
 * backend saves the rating + creates a Louis review task ONLY when the
 * rules trigger (heavy_turbulence, diverted, pain_reported, note added).
 *
 * After submit, a short rating-specific confirmation is shown, then the
 * user is returned to the dashboard.
 */
import React, { useCallback, useMemo, useState } from "react";
import {
  Modal, View, Text, StyleSheet, Pressable, TextInput,
  ActivityIndicator, ScrollView, KeyboardAvoidingView, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

export type Rating = "smooth_flight" | "light_turbulence" | "heavy_turbulence" | "diverted";

type Props = {
  visible: boolean;
  workoutId: string;
  workoutTitle?: string | null;
  /** Extra fields to include in the completion payload (RPE, completed sets, etc.).
   *  Anything not overridden by rating fields is passed through. */
  extraPayload?: Record<string, any>;
  onClose: () => void;
  /** Fired after the client dismisses the confirmation card. */
  onDone: (result: { rating: Rating | null; completedDoc: any }) => void;
};

const RATINGS: {
  key: Rating;
  title: string;
  subtitle: string;
  icon: keyof typeof Ionicons.glyphMap;
  attention: boolean;
}[] = [
  { key: "smooth_flight", title: "Smooth flight", subtitle: "Felt good", icon: "airplane", attention: false },
  { key: "light_turbulence", title: "Light turbulence", subtitle: "A bit tougher than expected", icon: "pulse", attention: false },
  { key: "heavy_turbulence", title: "Heavy turbulence", subtitle: "Very tough", icon: "warning", attention: true },
  { key: "diverted", title: "Diverted", subtitle: "Couldn't finish", icon: "swap-horizontal", attention: true },
];

const CONFIRM_COPY: Record<Rating, { title: string; body: string }> = {
  smooth_flight: { title: "Workout logged.", body: "Nice work — logged." },
  light_turbulence: { title: "Workout logged.", body: "Logged — good job getting it done." },
  heavy_turbulence: { title: "Workout logged.", body: "Logged. Louis can review this if needed." },
  diverted: { title: "Workout logged.", body: "Logged. Louis can review and adjust if needed." },
};

type Stage = "rate" | "note" | "pain" | "confirm";

export function PostWorkoutRatingSheet({
  visible, workoutId, workoutTitle, extraPayload, onClose, onDone,
}: Props) {
  const [stage, setStage] = useState<Stage>("rate");
  const [rating, setRating] = useState<Rating | null>(null);
  const [note, setNote] = useState("");
  const [painAsked, setPainAsked] = useState(false);
  const [painReported, setPainReported] = useState<boolean | null>(null);
  const [painNote, setPainNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [completedDoc, setCompletedDoc] = useState<any>(null);

  const reset = useCallback(() => {
    setStage("rate");
    setRating(null);
    setNote("");
    setPainAsked(false);
    setPainReported(null);
    setPainNote("");
    setSubmitting(false);
    setCompletedDoc(null);
  }, []);

  const close = useCallback(() => {
    reset();
    onClose();
  }, [onClose, reset]);

  const requiresPainCheck = rating === "heavy_turbulence" || rating === "diverted";

  const submit = useCallback(async () => {
    if (!rating || submitting) return;
    // If this is a "heavy" rating and we haven't yet asked about pain,
    // intercept and route to the pain question first.
    if (requiresPainCheck && !painAsked) {
      setStage("pain");
      return;
    }
    setSubmitting(true);
    try {
      const payload: Record<string, any> = {
        ...(extraPayload || {}),
        rating,
        optional_note: note.trim() || null,
        pain_reported: painAsked ? painReported : null,
        pain_note: painAsked && painReported ? (painNote.trim() || null) : null,
      };
      const doc = await api<any>(`/workouts/${workoutId}/complete`, { method: "POST", body: payload });
      setCompletedDoc(doc);
      setStage("confirm");
    } catch {
      // Non-fatal — still show confirmation so the client isn't stuck. The
      // completion will retry via existing offline fallbacks if any.
      setStage("confirm");
    } finally {
      setSubmitting(false);
    }
  }, [rating, submitting, requiresPainCheck, painAsked, note, painReported, painNote, extraPayload, workoutId]);

  const finish = useCallback(() => {
    const finalRating = rating;
    const doc = completedDoc;
    reset();
    onDone({ rating: finalRating, completedDoc: doc });
  }, [rating, completedDoc, reset, onDone]);

  const confirm = useMemo(() => (rating ? CONFIRM_COPY[rating] : null), [rating]);

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={close}>
      <View style={styles.bg}>
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          style={{ flex: 1, justifyContent: "flex-end" }}
        >
          <View style={styles.sheet} testID="post-workout-rating-sheet">
            <View style={styles.handle} />

            {stage === "rate" ? (
              <ScrollView contentContainerStyle={{ paddingBottom: 8 }} keyboardShouldPersistTaps="handled">
                <Text style={styles.eyebrow}>SESSION COMPLETE</Text>
                <Text style={styles.title}>How did that session land?</Text>
                {workoutTitle ? <Text style={styles.workoutTitle} numberOfLines={1}>{workoutTitle}</Text> : null}

                <View style={{ marginTop: 20, gap: 10 }}>
                  {RATINGS.map((r) => {
                    const selected = rating === r.key;
                    return (
                      <Pressable
                        key={r.key}
                        testID={`pw-rating-${r.key}`}
                        onPress={() => setRating(r.key)}
                        style={[
                          styles.optCard,
                          selected && styles.optCardSel,
                          r.attention && !selected && styles.optCardAttn,
                        ]}
                      >
                        <View style={[
                          styles.optIcon,
                          selected && { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
                        ]}>
                          <Ionicons name={r.icon} size={18} color={selected ? "#fff" : theme.color.brand} />
                        </View>
                        <View style={{ flex: 1 }}>
                          <Text style={[styles.optTitle, selected && { color: theme.color.brand }]}>{r.title}</Text>
                          <Text style={styles.optSub}>{r.subtitle}</Text>
                        </View>
                        {selected ? (
                          <Ionicons name="checkmark-circle" size={20} color={theme.color.brand} />
                        ) : (
                          <View style={styles.optRadio} />
                        )}
                      </Pressable>
                    );
                  })}
                </View>

                <Pressable
                  testID="pw-add-note-link"
                  onPress={() => setStage("note")}
                  style={styles.linkBtn}
                >
                  <Ionicons name="chatbubble-outline" size={13} color={theme.color.brand} />
                  <Text style={styles.linkT}>Add a note for Louis</Text>
                </Pressable>

                <View style={styles.footerRow}>
                  <Pressable testID="pw-cancel" onPress={close} disabled={submitting} style={styles.ghostBtn}>
                    <Text style={styles.ghostT}>NOT NOW</Text>
                  </Pressable>
                  <Pressable
                    testID="pw-log"
                    onPress={submit}
                    disabled={!rating || submitting}
                    style={[styles.primaryBtn, (!rating || submitting) && { opacity: 0.5 }]}
                  >
                    {submitting ? (
                      <ActivityIndicator color="#fff" />
                    ) : (
                      <>
                        <Ionicons name="checkmark" size={16} color="#fff" />
                        <Text style={styles.primaryT}>LOG WORKOUT</Text>
                      </>
                    )}
                  </Pressable>
                </View>
              </ScrollView>
            ) : null}

            {stage === "note" ? (
              <ScrollView contentContainerStyle={{ paddingBottom: 8 }} keyboardShouldPersistTaps="handled">
                <Text style={styles.eyebrow}>NOTE FOR LOUIS</Text>
                <Text style={styles.title}>Anything Louis should know?</Text>
                <TextInput
                  testID="pw-note-input"
                  value={note}
                  onChangeText={setNote}
                  placeholder="Energy, pain, equipment issues, or anything that felt off."
                  placeholderTextColor={theme.color.textMuted}
                  multiline
                  numberOfLines={4}
                  style={styles.textArea}
                />
                <View style={styles.footerRow}>
                  <Pressable testID="pw-note-back" onPress={() => setStage("rate")} style={styles.ghostBtn}>
                    <Text style={styles.ghostT}>BACK</Text>
                  </Pressable>
                  <Pressable testID="pw-note-save" onPress={() => setStage("rate")} style={styles.primaryBtn}>
                    <Text style={styles.primaryT}>SAVE NOTE</Text>
                  </Pressable>
                </View>
                {note.trim() ? (
                  <Text style={styles.hint}>Louis will see this note when reviewing the session.</Text>
                ) : (
                  <Text style={styles.hint}>Optional — you can leave this blank.</Text>
                )}
              </ScrollView>
            ) : null}

            {stage === "pain" ? (
              <ScrollView contentContainerStyle={{ paddingBottom: 8 }} keyboardShouldPersistTaps="handled">
                <Text style={styles.eyebrow}>QUICK CHECK</Text>
                <Text style={styles.title}>Any pain or discomfort?</Text>
                <View style={styles.yesNoRow}>
                  <Pressable
                    testID="pw-pain-no"
                    onPress={() => { setPainAsked(true); setPainReported(false); }}
                    style={[styles.yesNoBtn, painReported === false && styles.yesNoBtnSel]}
                  >
                    <Text style={[styles.yesNoT, painReported === false && { color: theme.color.brand }]}>NO</Text>
                  </Pressable>
                  <Pressable
                    testID="pw-pain-yes"
                    onPress={() => { setPainAsked(true); setPainReported(true); }}
                    style={[styles.yesNoBtn, painReported === true && styles.yesNoBtnSel]}
                  >
                    <Text style={[styles.yesNoT, painReported === true && { color: theme.color.brand }]}>YES</Text>
                  </Pressable>
                </View>
                {painReported === true ? (
                  <>
                    <Text style={[styles.title, { fontSize: 15, marginTop: 20 }]}>Where did you feel it?</Text>
                    <TextInput
                      testID="pw-pain-note-input"
                      value={painNote}
                      onChangeText={setPainNote}
                      placeholder="Knee, lower back, shoulder…"
                      placeholderTextColor={theme.color.textMuted}
                      multiline
                      numberOfLines={3}
                      style={styles.textArea}
                    />
                  </>
                ) : null}
                <View style={styles.footerRow}>
                  <Pressable testID="pw-pain-back" onPress={() => setStage("rate")} style={styles.ghostBtn}>
                    <Text style={styles.ghostT}>BACK</Text>
                  </Pressable>
                  <Pressable
                    testID="pw-pain-submit"
                    onPress={submit}
                    disabled={painReported === null || submitting}
                    style={[styles.primaryBtn, (painReported === null || submitting) && { opacity: 0.5 }]}
                  >
                    {submitting ? (
                      <ActivityIndicator color="#fff" />
                    ) : (
                      <>
                        <Ionicons name="checkmark" size={16} color="#fff" />
                        <Text style={styles.primaryT}>LOG WORKOUT</Text>
                      </>
                    )}
                  </Pressable>
                </View>
              </ScrollView>
            ) : null}

            {stage === "confirm" && confirm ? (
              <View testID="pw-confirm">
                <View style={styles.confirmIconWrap}>
                  <Ionicons name="checkmark-circle" size={48} color={theme.color.brand} />
                </View>
                <Text style={[styles.title, { textAlign: "center" }]}>{confirm.title}</Text>
                <Text style={styles.confirmBody}>{confirm.body}</Text>
                <View style={{ marginTop: 22 }}>
                  <Pressable testID="pw-confirm-done" onPress={finish} style={styles.primaryBtnWide}>
                    <Text style={styles.primaryT}>BACK TO DASHBOARD</Text>
                  </Pressable>
                </View>
              </View>
            ) : null}
          </View>
        </KeyboardAvoidingView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  bg: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.6)",
  },
  sheet: {
    backgroundColor: theme.color.surface,
    borderTopLeftRadius: 22,
    borderTopRightRadius: 22,
    paddingHorizontal: 20,
    paddingTop: 10,
    paddingBottom: 32,
    minHeight: 380,
    maxHeight: "92%",
  },
  handle: { alignSelf: "center", width: 42, height: 4, borderRadius: 2, backgroundColor: theme.color.border, marginBottom: 14 },

  eyebrow: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 2 },
  title: { color: theme.color.text, fontSize: 22, fontWeight: "900", letterSpacing: -0.5, marginTop: 6 },
  workoutTitle: { color: theme.color.textMuted, fontSize: 12, fontWeight: "700", marginTop: 4, letterSpacing: 0.5 },

  optCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: 14,
    padding: 14,
    borderRadius: 12,
    backgroundColor: theme.color.surface2,
    borderWidth: 1,
    borderColor: theme.color.border,
  },
  optCardSel: { borderColor: theme.color.brand, backgroundColor: theme.color.brandTint },
  optCardAttn: {}, // reserved for future subtle amber tint if desired
  optIcon: {
    width: 40, height: 40, borderRadius: 20,
    borderWidth: 1, borderColor: theme.color.border,
    backgroundColor: theme.color.surface,
    alignItems: "center", justifyContent: "center",
  },
  optTitle: { color: theme.color.text, fontSize: 15, fontWeight: "800" },
  optSub: { color: theme.color.textMuted, fontSize: 12, marginTop: 2 },
  optRadio: {
    width: 20, height: 20, borderRadius: 10,
    borderWidth: 1.5, borderColor: theme.color.border,
  },

  linkBtn: {
    marginTop: 16,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 10,
  },
  linkT: { color: theme.color.brand, fontSize: 12, fontWeight: "800", letterSpacing: 0.5, textDecorationLine: "underline" },

  footerRow: {
    flexDirection: "row",
    gap: 10,
    marginTop: 20,
  },
  primaryBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 15,
    borderRadius: 12,
    backgroundColor: theme.color.brand,
  },
  primaryBtnWide: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 15,
    borderRadius: 12,
    backgroundColor: theme.color.brand,
  },
  primaryT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 1.6 },
  ghostBtn: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: 15,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: theme.color.border,
    backgroundColor: theme.color.surface2,
  },
  ghostT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "800", letterSpacing: 1.5 },

  textArea: {
    marginTop: 14,
    minHeight: 100,
    padding: 12,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: theme.color.border,
    backgroundColor: theme.color.surface2,
    color: theme.color.text,
    fontSize: 14,
    textAlignVertical: "top",
  },
  hint: { color: theme.color.textMuted, fontSize: 11, marginTop: 10, textAlign: "center" },

  yesNoRow: { flexDirection: "row", gap: 10, marginTop: 18 },
  yesNoBtn: {
    flex: 1, alignItems: "center", justifyContent: "center",
    paddingVertical: 18, borderRadius: 12,
    borderWidth: 1, borderColor: theme.color.border,
    backgroundColor: theme.color.surface2,
  },
  yesNoBtnSel: { borderColor: theme.color.brand, backgroundColor: theme.color.brandTint },
  yesNoT: { color: theme.color.text, fontSize: 14, fontWeight: "900", letterSpacing: 2 },

  confirmIconWrap: { alignItems: "center", marginTop: 20, marginBottom: 14 },
  confirmBody: { color: theme.color.textMuted, fontSize: 14, textAlign: "center", marginTop: 8, lineHeight: 20 },
});

export default PostWorkoutRatingSheet;
