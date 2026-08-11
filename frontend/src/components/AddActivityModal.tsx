/**
 * AddActivityModal — bottom sheet form for adding a personal activity.
 * Used from the client Today screen and Calendar screen.
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  Modal, View, Text, StyleSheet, Pressable, TextInput, ScrollView,
  ActivityIndicator, Alert, KeyboardAvoidingView, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";
import {
  loadPresets, createActivity,
  INTENSITY_LABEL, PLANNING_LABEL, RECURRENCE_LABEL,
  type ActivityPreset, type Intensity, type PlanningMode, type Recurrence, type PresetsResponse,
} from "@/src/lib/personalActivities";

type Props = {
  visible: boolean;
  onClose: () => void;
  onCreated?: (count: number) => void;
  initialDate?: string;
};

const DURATION_CHIPS = [30, 45, 60, 90, 120, 180, 240];

export function AddActivityModal({ visible, onClose, onCreated, initialDate }: Props) {
  const [presets, setPresets] = useState<PresetsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const [selectedKey, setSelectedKey] = useState<string>("tennis");
  const [customName, setCustomName] = useState<string>("");
  const [date, setDate] = useState<string>(initialDate || new Date().toISOString().slice(0, 10));
  const [startTime, setStartTime] = useState<string>("");
  const [duration, setDuration] = useState<number>(60);
  const [intensity, setIntensity] = useState<Intensity>("moderate");
  const [recurrence, setRecurrence] = useState<Recurrence>("once");
  const [planningMode, setPlanningMode] = useState<PlanningMode>("count_as_training");
  const [location, setLocation] = useState<string>("");
  const [notes, setNotes] = useState<string>("");
  const [isCompetition, setIsCompetition] = useState<boolean>(false);

  useEffect(() => {
    if (!visible) return;
    setLoading(true);
    loadPresets()
      .then((p) => {
        setPresets(p);
      })
      .catch(() => Alert.alert("Load failed", "Could not load activity presets."))
      .finally(() => setLoading(false));
  }, [visible]);

  useEffect(() => {
    if (initialDate) setDate(initialDate);
  }, [initialDate]);

  const selectedPreset: ActivityPreset | null = useMemo(() => {
    if (!presets) return null;
    return presets.presets.find((p) => p.key === selectedKey) || null;
  }, [presets, selectedKey]);

  // When user picks a preset, seed sensible defaults.
  useEffect(() => {
    if (!selectedPreset) return;
    setDuration(selectedPreset.default_duration_min);
    setIntensity(selectedPreset.default_intensity);
  }, [selectedPreset]);

  const submit = async () => {
    if (!date) { Alert.alert("Missing date", "Pick a date."); return; }
    setSaving(true);
    try {
      const r = await createActivity({
        activity_type: selectedKey,
        activity_name: selectedKey === "custom" ? (customName || "Custom activity") : undefined,
        date_local: date,
        start_time: startTime || undefined,
        duration_minutes: duration,
        intensity,
        recurrence,
        planning_mode: planningMode,
        notes,
        location,
        is_competition: isCompetition,
      });
      onCreated?.(r.count);
      onClose();
    } catch (e: any) {
      Alert.alert("Could not save", e?.message || "Please try again");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View style={styles.root}>
        <Pressable style={styles.backdrop} onPress={onClose} />
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={styles.sheet}>
            <View style={styles.head}>
              <View style={styles.headIcon}><Ionicons name="add-circle" size={16} color={theme.color.brand} /></View>
              <View style={{ flex: 1 }}>
                <Text style={styles.eyebrow}>PERSONAL ACTIVITY</Text>
                <Text style={styles.title}>Add sport or hobby</Text>
              </View>
              <Pressable onPress={onClose} hitSlop={12} testID="add-activity-close">
                <Ionicons name="close" size={22} color={theme.color.text} />
              </Pressable>
            </View>

            {loading || !presets ? (
              <View style={{ padding: 32, alignItems: "center" }}>
                <ActivityIndicator color={theme.color.brand} />
              </View>
            ) : (
              <ScrollView style={{ maxHeight: "82%" }} contentContainerStyle={{ padding: 16, paddingBottom: 28 }} keyboardShouldPersistTaps="handled">
                <Text style={styles.label}>ACTIVITY</Text>
                <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8, paddingBottom: 4 }}>
                  {presets.presets.map((p) => {
                    const active = p.key === selectedKey;
                    return (
                      <Pressable
                        key={p.key}
                        onPress={() => setSelectedKey(p.key)}
                        style={[styles.presetChip, active && styles.presetChipActive]}
                        testID={`preset-${p.key}`}
                      >
                        <Ionicons name={p.icon as any} size={14} color={active ? "#fff" : theme.color.brand} />
                        <Text style={[styles.presetChipT, active && { color: "#fff" }]}>{p.label}</Text>
                      </Pressable>
                    );
                  })}
                </ScrollView>

                {selectedKey === "custom" ? (
                  <TextInput
                    value={customName}
                    onChangeText={setCustomName}
                    placeholder="Name your activity (e.g. Rock climbing)"
                    placeholderTextColor={theme.color.textDim}
                    style={styles.input}
                    testID="activity-custom-name"
                  />
                ) : null}

                {selectedPreset?.note ? (
                  <View style={styles.noteBox}>
                    <Ionicons name="information-circle" size={13} color={theme.color.brand} />
                    <Text style={styles.noteT}>{selectedPreset.note}</Text>
                  </View>
                ) : null}

                <Text style={styles.label}>DATE</Text>
                <TextInput
                  value={date}
                  onChangeText={setDate}
                  placeholder="YYYY-MM-DD"
                  placeholderTextColor={theme.color.textDim}
                  style={styles.input}
                  testID="activity-date"
                />

                <Text style={styles.label}>START TIME (OPTIONAL)</Text>
                <TextInput
                  value={startTime}
                  onChangeText={setStartTime}
                  placeholder="e.g. 19:00"
                  placeholderTextColor={theme.color.textDim}
                  style={styles.input}
                  testID="activity-start-time"
                />

                <Text style={styles.label}>DURATION</Text>
                <View style={styles.chipRow}>
                  {DURATION_CHIPS.map((n) => (
                    <Pressable key={n} onPress={() => setDuration(n)} style={[styles.chip, duration === n && styles.chipOn]} testID={`duration-${n}`}>
                      <Text style={[styles.chipT, duration === n && { color: "#fff" }]}>{n} min</Text>
                    </Pressable>
                  ))}
                </View>

                <Text style={styles.label}>INTENSITY</Text>
                <View style={styles.chipRow}>
                  {(["light", "moderate", "hard", "very_hard", "not_sure"] as Intensity[]).map((k) => (
                    <Pressable key={k} onPress={() => setIntensity(k)} style={[styles.chip, intensity === k && styles.chipOn]} testID={`intensity-${k}`}>
                      <Text style={[styles.chipT, intensity === k && { color: "#fff" }]}>{INTENSITY_LABEL[k]}</Text>
                    </Pressable>
                  ))}
                </View>

                <Text style={styles.label}>HOW SHOULD CREWFIT HANDLE THIS?</Text>
                {(["protect", "count_as_training", "note_only", "ask_coach"] as PlanningMode[]).map((k) => (
                  <Pressable
                    key={k}
                    onPress={() => setPlanningMode(k)}
                    style={[styles.mode, planningMode === k && styles.modeOn]}
                    testID={`planning-${k}`}
                  >
                    <Ionicons
                      name={planningMode === k ? "radio-button-on" : "radio-button-off"}
                      size={16}
                      color={planningMode === k ? theme.color.brand : theme.color.textDim}
                    />
                    <Text style={[styles.modeT, planningMode === k && { color: theme.color.brand }]}>{PLANNING_LABEL[k]}</Text>
                  </Pressable>
                ))}

                <Text style={styles.label}>RECURRENCE</Text>
                <View style={styles.chipRow}>
                  {(["once", "weekly", "biweekly", "monthly"] as Recurrence[]).map((k) => (
                    <Pressable key={k} onPress={() => setRecurrence(k)} style={[styles.chip, recurrence === k && styles.chipOn]} testID={`recurrence-${k}`}>
                      <Text style={[styles.chipT, recurrence === k && { color: "#fff" }]}>{RECURRENCE_LABEL[k]}</Text>
                    </Pressable>
                  ))}
                </View>

                <Text style={styles.label}>LOCATION (OPTIONAL)</Text>
                <TextInput
                  value={location}
                  onChangeText={setLocation}
                  placeholder="e.g. Local club, hotel gym"
                  placeholderTextColor={theme.color.textDim}
                  style={styles.input}
                  testID="activity-location"
                />

                <Text style={styles.label}>NOTES (OPTIONAL)</Text>
                <TextInput
                  value={notes}
                  onChangeText={setNotes}
                  placeholder="Anything for your coach to know?"
                  placeholderTextColor={theme.color.textDim}
                  style={[styles.input, { minHeight: 60, textAlignVertical: "top" }]}
                  multiline
                  testID="activity-notes"
                />

                <Pressable
                  onPress={() => setIsCompetition((x) => !x)}
                  style={[styles.mode, isCompetition && styles.modeOn]}
                  testID="activity-competition-toggle"
                >
                  <Ionicons
                    name={isCompetition ? "checkbox" : "square-outline"}
                    size={16}
                    color={isCompetition ? theme.color.brand : theme.color.textDim}
                  />
                  <Text style={[styles.modeT, isCompetition && { color: theme.color.brand }]}>This is a competition or event</Text>
                </Pressable>

                {selectedPreset?.safety_note ? (
                  <View style={styles.safetyBox}>
                    <Ionicons name="warning" size={13} color={theme.color.amber} />
                    <Text style={styles.safetyT}>{selectedPreset.safety_note}</Text>
                  </View>
                ) : null}

                <View style={styles.disclaimer}>
                  <Ionicons name="shield-checkmark" size={12} color={theme.color.textMuted} />
                  <Text style={styles.disclaimerT}>
                    CrewFit helps plan training load around this activity — it does not replace professional instruction, medical advice or sport-specific safety guidance.
                  </Text>
                </View>

                <Pressable onPress={submit} disabled={saving} style={[styles.cta, saving && { opacity: 0.6 }]} testID="activity-save">
                  {saving ? <ActivityIndicator color="#fff" /> : <Ionicons name="checkmark" size={16} color="#fff" />}
                  <Text style={styles.ctaT}>{saving ? "SAVING..." : "ADD ACTIVITY"}</Text>
                </Pressable>
              </ScrollView>
            )}
          </View>
        </KeyboardAvoidingView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, justifyContent: "flex-end" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.65)" },
  sheet: {
    backgroundColor: theme.color.surface,
    borderTopLeftRadius: 20, borderTopRightRadius: 20,
    borderWidth: 1, borderColor: theme.color.border,
    maxHeight: "94%",
  },
  head: {
    flexDirection: "row", alignItems: "center", gap: 12,
    padding: 16, borderBottomWidth: 1, borderBottomColor: theme.color.divider,
  },
  headIcon: {
    width: 34, height: 34, borderRadius: 17, backgroundColor: theme.color.brandTint,
    alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: theme.color.brand,
  },
  eyebrow: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  title: { color: theme.color.text, fontSize: 16, fontWeight: "800", marginTop: 3 },
  label: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2, marginTop: 16, marginBottom: 8 },
  presetChip: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: 20,
    borderWidth: 1, borderColor: theme.color.brand, backgroundColor: theme.color.brandTint,
  },
  presetChipActive: { backgroundColor: theme.color.brand },
  presetChipT: { color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 0.5 },
  input: {
    backgroundColor: theme.color.surface2, color: theme.color.text,
    borderRadius: 10, padding: 12, borderWidth: 1, borderColor: theme.color.border,
    fontSize: 14,
  },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: {
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  chipOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipT: { color: theme.color.text, fontSize: 11, fontWeight: "700" },
  mode: {
    flexDirection: "row", alignItems: "center", gap: 10,
    padding: 12, borderRadius: 8, marginBottom: 6,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  modeOn: { borderColor: theme.color.brand, backgroundColor: theme.color.brandTint },
  modeT: { color: theme.color.text, fontSize: 12, fontWeight: "600" },
  noteBox: {
    flexDirection: "row", gap: 8, padding: 10, marginTop: 10,
    borderRadius: 8, backgroundColor: theme.color.brandTint,
    borderWidth: 1, borderColor: theme.color.brand,
  },
  noteT: { color: theme.color.text, fontSize: 11, lineHeight: 15, flex: 1 },
  safetyBox: {
    flexDirection: "row", gap: 8, padding: 10, marginTop: 10,
    borderRadius: 8, backgroundColor: "rgba(245,158,11,0.10)",
    borderWidth: 1, borderColor: theme.color.amber,
  },
  safetyT: { color: theme.color.text, fontSize: 11, lineHeight: 15, flex: 1 },
  disclaimer: {
    flexDirection: "row", gap: 6, padding: 10, marginTop: 12,
    borderRadius: 8, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.divider,
  },
  disclaimerT: { color: theme.color.textMuted, fontSize: 11, lineHeight: 14, flex: 1 },
  cta: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    paddingVertical: 14, borderRadius: 10, backgroundColor: theme.color.brand,
    marginTop: 16,
  },
  ctaT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 2 },
});
