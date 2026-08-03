/**
 * ReportIssueSheet — client-facing bug/support report modal.
 *
 * Reuses:
 *   • existing api() helper, theme, ux toast() & confirm()
 *   • existing base64 image capture path (react-native `Image.getSize`)
 *   • existing modal / bottom-sheet styling from other confirm sheets
 *
 * Never blocks submission on screenshot. Auto-captures technical context.
 */
import React, { useState, useCallback } from "react";
import {
  View, Text, StyleSheet, Modal, Pressable, ScrollView, TextInput,
  ActivityIndicator, Platform, Image,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";
import { api } from "@/src/lib/api";
import { toast } from "@/src/lib/ux";
import Constants from "expo-constants";
import * as ImagePicker from "expo-image-picker";

export type ReportIssueContext = {
  route?: string;
  workoutId?: string;
  workoutDate?: string;
  exerciseId?: string;
  exerciseName?: string;
  rosterId?: string;
  flightSupportId?: string;
  realitySelection?: string;
  variant?: string;
  errorCode?: string;
};

const CATEGORIES: { key: string; label: string; icon: any }[] = [
  { key: "workout_not_working",  label: "Workout not working",       icon: "barbell-outline" },
  { key: "exercise_or_media",    label: "Exercise or media problem", icon: "image-outline" },
  { key: "roster",               label: "Roster problem",            icon: "calendar-outline" },
  { key: "flight_support",       label: "Flight Support problem",    icon: "airplane-outline" },
  { key: "todays_reality",       label: "Today's Reality problem",   icon: "sync-outline" },
  { key: "app_button_or_screen", label: "App button or screen",      icon: "phone-portrait-outline" },
  { key: "login_or_account",     label: "Login or account",          icon: "lock-closed-outline" },
  { key: "progress_or_habit",    label: "Progress or habit",         icon: "trending-up-outline" },
  { key: "other",                label: "Other",                     icon: "help-circle-outline" },
];

export function ReportIssueSheet({
  visible, onClose, context,
}: {
  visible: boolean;
  onClose: () => void;
  context?: ReportIssueContext;
}) {
  const [category, setCategory] = useState<string | null>(null);
  const [desc, setDesc] = useState("");
  const [expected, setExpected] = useState("");
  const [urgency, setUrgency] = useState<"normal" | "blocking">("normal");
  const [screenshot, setScreenshot] = useState<string | null>(null);
  const [contactPerm, setContactPerm] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const reset = () => {
    setCategory(null); setDesc(""); setExpected("");
    setUrgency("normal"); setScreenshot(null); setContactPerm(true);
    setSubmitting(false); setSubmitted(false);
  };

  const close = useCallback(() => { reset(); onClose(); }, [onClose]);

  const pickScreenshot = useCallback(async () => {
    try {
      const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) {
        toast("Photo library permission required to attach a screenshot.", "error");
        return;
      }
      const r = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        base64: true, quality: 0.7,
      });
      if (r.canceled || !r.assets?.[0]) return;
      const b64 = r.assets[0].base64;
      if (!b64) { toast("Couldn't read that image.", "error"); return; }
      const dataUri = `data:image/jpeg;base64,${b64}`;
      // Keep the request under ~5 MB.
      if (dataUri.length > 5_500_000) {
        toast("Screenshot too large — try a smaller image.", "error");
        return;
      }
      setScreenshot(dataUri);
    } catch (e: any) {
      toast(`Couldn't attach — ${e?.message || "please try again"}`, "error");
    }
  }, []);

  const submit = useCallback(async () => {
    if (!category) { toast("Pick a category first.", "error"); return; }
    if (!desc.trim()) { toast("Tell us what happened.", "error"); return; }
    if (submitting || submitted) return; // duplicate-tap guard
    setSubmitting(true);
    try {
      const expoConfig: any = (Constants as any).expoConfig || {};
      const platform = Platform.OS;
      const app_version = expoConfig?.version || "unknown";
      const app_build = String(
        expoConfig?.ios?.buildNumber ||
        expoConfig?.android?.versionCode ||
        expoConfig?.runtimeVersion || "",
      ) || undefined;
      let timezone: string | undefined;
      try {
        timezone = Intl?.DateTimeFormat?.().resolvedOptions?.().timeZone;
      } catch { timezone = undefined; }
      const body = {
        category, description: desc.trim(),
        what_should_happen: expected.trim() || undefined,
        urgency, contact_permission: contactPerm,
        screenshot_base64: screenshot || undefined,
        route:       context?.route,
        app_version, app_build, platform, timezone,
        workout_id:       context?.workoutId,
        workout_date:     context?.workoutDate,
        exercise_id:      context?.exerciseId,
        exercise_name:    context?.exerciseName,
        roster_id:        context?.rosterId,
        flight_support_id: context?.flightSupportId,
        reality_selection: context?.realitySelection,
        variant:          context?.variant,
        error_code:       context?.errorCode,
      };
      await api("/client/issues", { method: "POST", body });
      setSubmitted(true);
      toast("Issue reported — Louis has been alerted.", "success");
      setTimeout(close, 900);
    } catch (e: any) {
      toast(`Couldn't submit — ${e?.message || "please try again"}`, "error");
      setSubmitting(false);
    }
  }, [category, desc, expected, urgency, screenshot, contactPerm, submitting, submitted, context, close]);

  return (
    <Modal transparent visible={visible} animationType="slide" onRequestClose={close}>
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <View style={styles.header}>
            <Text style={styles.title}>REPORT AN ISSUE</Text>
            <Pressable onPress={close} testID="report-close" style={styles.closeBtn}>
              <Ionicons name="close" size={20} color={theme.color.textHi} />
            </Pressable>
          </View>
          <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
            {/* Category */}
            <Text style={styles.section}>Category *</Text>
            <View style={styles.catGrid}>
              {CATEGORIES.map((c) => {
                const selected = category === c.key;
                return (
                  <Pressable
                    key={c.key}
                    onPress={() => setCategory(c.key)}
                    style={[styles.catChip, selected && styles.catChipOn]}
                    testID={`report-cat-${c.key}`}
                  >
                    <Ionicons
                      name={c.icon}
                      size={13}
                      color={selected ? theme.color.brand : theme.color.textDim}
                    />
                    <Text style={[styles.catChipT, selected && { color: theme.color.brand }]}>
                      {c.label}
                    </Text>
                  </Pressable>
                );
              })}
            </View>

            {/* Description */}
            <Text style={styles.section}>What happened? *</Text>
            <TextInput
              value={desc} onChangeText={setDesc}
              placeholder="Tell us what you were trying to do and what happened."
              placeholderTextColor={theme.color.textDim}
              style={[styles.input, { minHeight: 90 }]}
              multiline testID="report-desc"
            />

            {/* Expected */}
            <Text style={styles.section}>What should have happened? (optional)</Text>
            <TextInput
              value={expected} onChangeText={setExpected}
              placeholder="What did you expect to see?"
              placeholderTextColor={theme.color.textDim}
              style={[styles.input, { minHeight: 60 }]}
              multiline testID="report-expected"
            />

            {/* Urgency */}
            <Text style={styles.section}>Urgency</Text>
            <View style={styles.urgRow}>
              {[
                { k: "normal",   l: "Normal" },
                { k: "blocking", l: "Blocking me from continuing" },
              ].map((o) => {
                const on = urgency === o.k;
                return (
                  <Pressable
                    key={o.k}
                    onPress={() => setUrgency(o.k as any)}
                    style={[styles.urgBtn, on && styles.urgBtnOn,
                             o.k === "blocking" && on && { borderColor: "#ff6b6b" }]}
                    testID={`report-urg-${o.k}`}
                  >
                    <Text style={[styles.urgT,
                                   on && { color: o.k === "blocking" ? "#ff6b6b" : theme.color.brand }]}>
                      {o.l}
                    </Text>
                  </Pressable>
                );
              })}
            </View>

            {/* Screenshot */}
            <Text style={styles.section}>Screenshot (optional)</Text>
            {screenshot ? (
              <View style={styles.shotWrap}>
                <Image source={{ uri: screenshot }} style={styles.shot} />
                <Pressable onPress={() => setScreenshot(null)} style={styles.shotRemove}>
                  <Ionicons name="close-circle" size={22} color="#ff6b6b" />
                </Pressable>
              </View>
            ) : (
              <Pressable onPress={pickScreenshot} style={styles.shotAdd} testID="report-shot-add">
                <Ionicons name="image-outline" size={16} color={theme.color.brand} />
                <Text style={styles.shotAddT}>ATTACH SCREENSHOT</Text>
              </Pressable>
            )}

            {/* Contact permission */}
            <Pressable
              onPress={() => setContactPerm((v) => !v)}
              style={styles.permRow}
              testID="report-contact-perm"
            >
              <Ionicons
                name={contactPerm ? "checkbox" : "square-outline"}
                size={18}
                color={contactPerm ? theme.color.brand : theme.color.textDim}
              />
              <Text style={styles.permT}>You may contact me about this issue.</Text>
            </Pressable>

            {/* Submit */}
            <Pressable
              onPress={submit}
              disabled={submitting || submitted || !category || !desc.trim()}
              style={[styles.submit,
                       (submitting || submitted || !category || !desc.trim()) && { opacity: 0.5 }]}
              testID="report-submit"
            >
              {submitting ? (
                <ActivityIndicator color="#000" size="small" />
              ) : submitted ? (
                <>
                  <Ionicons name="checkmark" size={14} color="#000" />
                  <Text style={styles.submitT}>REPORTED</Text>
                </>
              ) : (
                <>
                  <Ionicons name="send" size={13} color="#000" />
                  <Text style={styles.submitT}>SUBMIT</Text>
                </>
              )}
            </Pressable>
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.75)", justifyContent: "flex-end" },
  sheet: {
    backgroundColor: theme.color.surface,
    borderTopLeftRadius: 20, borderTopRightRadius: 20,
    maxHeight: "92%",
    borderTopWidth: 1, borderColor: theme.color.border,
  },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 16, paddingTop: 14, paddingBottom: 10,
    borderBottomWidth: 1, borderColor: theme.color.border,
  },
  title: { color: theme.color.brand, fontWeight: "900", letterSpacing: 2, fontSize: 12 },
  closeBtn: { padding: 4 },
  body: { paddingHorizontal: 16, paddingTop: 12, paddingBottom: 40 },
  section: {
    color: theme.color.textDim, fontSize: 11, fontWeight: "800",
    letterSpacing: 1.5, marginTop: 14, marginBottom: 8,
  },
  catGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  catChip: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingVertical: 8, paddingHorizontal: 12, borderRadius: 6,
    borderWidth: 1, borderColor: theme.color.border,
    backgroundColor: theme.color.bg,
  },
  catChipOn: { borderColor: theme.color.brand, backgroundColor: `${theme.color.brand}12` },
  catChipT: { color: theme.color.textDim, fontSize: 12, fontWeight: "700" },
  input: {
    backgroundColor: theme.color.bg,
    borderWidth: 1, borderColor: theme.color.border,
    borderRadius: 8, paddingHorizontal: 10, paddingVertical: 10,
    color: theme.color.textHi, fontSize: 14,
  },
  urgRow: { flexDirection: "row", gap: 10 },
  urgBtn: {
    flex: 1, paddingVertical: 12, borderRadius: 8,
    borderWidth: 1, borderColor: theme.color.border,
    backgroundColor: theme.color.bg, alignItems: "center",
  },
  urgBtnOn: { borderColor: theme.color.brand, backgroundColor: `${theme.color.brand}12` },
  urgT: { color: theme.color.textHi, fontSize: 12, fontWeight: "800" },
  shotAdd: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    paddingVertical: 12, borderRadius: 8, borderWidth: 1, borderStyle: "dashed",
    borderColor: theme.color.border, backgroundColor: theme.color.bg,
  },
  shotAddT: { color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 1.2 },
  shotWrap: { position: "relative" },
  shot: { width: "100%", height: 180, borderRadius: 8, backgroundColor: "#000" },
  shotRemove: { position: "absolute", top: 4, right: 4 },
  permRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 16 },
  permT: { color: theme.color.textHi, fontSize: 12 },
  submit: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    marginTop: 22, paddingVertical: 14, borderRadius: 8,
    backgroundColor: theme.color.brand,
  },
  submitT: { color: "#000", fontWeight: "900", letterSpacing: 1.5, fontSize: 12 },
});
