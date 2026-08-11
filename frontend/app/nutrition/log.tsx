/**
 * Nutrition · Manual Log — Phase 1.
 */
import React, { useState } from "react";
import {
  ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView,
  StyleSheet, Text, TextInput, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useLocalSearchParams } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast } from "@/src/lib/ux";

const MEALS = [
  { key: "breakfast", label: "BREAKFAST" }, { key: "lunch", label: "LUNCH" }, { key: "dinner", label: "DINNER" },
  { key: "snack", label: "SNACK" }, { key: "pre_flight", label: "PRE-FLIGHT" }, { key: "in_flight", label: "IN-FLIGHT" },
  { key: "post_flight", label: "POST-FLIGHT" }, { key: "post_workout", label: "POST-WORKOUT" },
  { key: "hotel_meal", label: "HOTEL" }, { key: "airport_meal", label: "AIRPORT" }, { key: "crew_meal", label: "CREW" },
];

const ROSTER = [
  { key: "home", label: "HOME" }, { key: "flight_day", label: "FLIGHT DAY" },
  { key: "long_haul", label: "LONG-HAUL" }, { key: "short_haul", label: "SHORT-HAUL" },
  { key: "layover_full", label: "LAYOVER" }, { key: "night_flight", label: "NIGHT FLIGHT" },
  { key: "early_start", label: "EARLY START" }, { key: "standby", label: "STANDBY" },
  { key: "recovery", label: "RECOVERY" }, { key: "home_training", label: "TRAINING" },
];

export default function LogMeal() {
  const router = useRouter();
  const params = useLocalSearchParams<{ barcode?: string }>();
  const barcodeParam = typeof params?.barcode === "string" ? params.barcode : undefined;
  const [name, setName] = useState("");
  const [mealType, setMealType] = useState("snack");
  const [cal, setCal] = useState("");
  const [pro, setPro] = useState("");
  const [carb, setCarb] = useState("");
  const [fat, setFat] = useState("");
  const [portion, setPortion] = useState("");
  const [notes, setNotes] = useState(barcodeParam ? `Barcode ${barcodeParam}` : "");
  const [location, setLocation] = useState("");
  const [rosterCtx, setRosterCtx] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveAsFav, setSaveAsFav] = useState(!!barcodeParam);

  const save = async () => {
    if (!name.trim()) { toast("Please enter a food name", "error"); return; }
    setSaving(true);
    try {
      await api("/nutrition/logs", {
        method: "POST",
        body: {
          food_name: name.trim(),
          meal_type: mealType,
          calories: parseInt(cal || "0", 10) || 0,
          protein_g: parseFloat(pro || "0") || 0,
          carbs_g: parseFloat(carb || "0") || 0,
          fats_g: parseFloat(fat || "0") || 0,
          portion: portion || undefined,
          notes: notes || undefined,
          location_context: location || undefined,
          roster_context: rosterCtx || undefined,
          source: "manual",
        },
      });
      if (saveAsFav) {
        await api("/nutrition/favourites", {
          method: "POST",
          body: {
            name: name.trim(),
            meal_type: mealType,
            calories: parseInt(cal || "0", 10) || 0,
            protein_g: parseFloat(pro || "0") || 0,
            carbs_g: parseFloat(carb || "0") || 0,
            fats_g: parseFloat(fat || "0") || 0,
            portion: portion || undefined,
          },
        });
      }
      toast("Meal logged", "success");
      router.back();
    } catch (e: any) { toast(e?.message || "Save failed", "error"); }
    finally { setSaving(false); }
  };

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="chevron-back" size={24} color={theme.color.text} />
        </Pressable>
        <Text style={styles.headerT}>LOG A MEAL</Text>
        <View style={{ width: 24 }} />
      </View>

      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 120, gap: 12 }} keyboardShouldPersistTaps="handled">
          <Text style={styles.label}>FOOD NAME *</Text>
          <TextInput value={name} onChangeText={setName} style={styles.input}
            placeholder="e.g. Chicken rice bowl" placeholderTextColor={theme.color.textDim} autoFocus />

          <Text style={styles.label}>MEAL TYPE</Text>
          <View style={styles.chipRow}>
            {MEALS.map((m) => (
              <Pressable key={m.key} onPress={() => setMealType(m.key)}
                style={[styles.chip, mealType === m.key && styles.chipOn]}>
                <Text style={[styles.chipT, mealType === m.key && styles.chipTOn]}>{m.label}</Text>
              </Pressable>
            ))}
          </View>

          <View style={styles.macroRow}>
            <Field label="CALORIES" value={cal} setValue={setCal} placeholder="420" unit="kcal" />
            <Field label="PROTEIN" value={pro} setValue={setPro} placeholder="32" unit="g" />
          </View>
          <View style={styles.macroRow}>
            <Field label="CARBS" value={carb} setValue={setCarb} placeholder="48" unit="g" />
            <Field label="FATS" value={fat} setValue={setFat} placeholder="14" unit="g" />
          </View>

          <Text style={styles.label}>PORTION</Text>
          <TextInput value={portion} onChangeText={setPortion} style={styles.input}
            placeholder="e.g. 1 large bowl / 200g" placeholderTextColor={theme.color.textDim} />

          <Text style={styles.label}>ROSTER CONTEXT (optional)</Text>
          <View style={styles.chipRow}>
            {ROSTER.map((r) => (
              <Pressable key={r.key} onPress={() => setRosterCtx(rosterCtx === r.key ? null : r.key)}
                style={[styles.chip, rosterCtx === r.key && styles.chipOn]}>
                <Text style={[styles.chipT, rosterCtx === r.key && styles.chipTOn]}>{r.label}</Text>
              </Pressable>
            ))}
          </View>

          <Text style={styles.label}>LOCATION (optional)</Text>
          <TextInput value={location} onChangeText={setLocation} style={styles.input}
            placeholder="e.g. Dubai hotel breakfast" placeholderTextColor={theme.color.textDim} />

          <Text style={styles.label}>NOTES (optional)</Text>
          <TextInput value={notes} onChangeText={setNotes} style={[styles.input, { minHeight: 60 }]}
            placeholder="Anything worth remembering…" placeholderTextColor={theme.color.textDim}
            multiline textAlignVertical="top" />

          <Pressable onPress={() => setSaveAsFav((v) => !v)} style={styles.favRow}>
            <Ionicons name={saveAsFav ? "checkmark-circle" : "ellipse-outline"}
              size={18} color={saveAsFav ? theme.color.brand : theme.color.textMuted} />
            <Text style={styles.favT}>SAVE AS FAVOURITE</Text>
          </Pressable>
        </ScrollView>

        <View style={styles.footer}>
          <Pressable onPress={() => router.back()} style={[styles.btn, styles.btnGhost]}>
            <Text style={styles.btnGhostT}>CANCEL</Text>
          </Pressable>
          <Pressable onPress={save} disabled={saving} style={[styles.btn, styles.btnPri, saving && { opacity: 0.5 }]}>
            {saving ? <ActivityIndicator color="#fff" /> : <Text style={styles.btnPriT}>SAVE MEAL</Text>}
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function Field({ label, value, setValue, placeholder, unit }: { label: string; value: string; setValue: (v: string) => void; placeholder: string; unit: string; }) {
  return (
    <View style={{ flex: 1 }}>
      <Text style={styles.label}>{label} ({unit})</Text>
      <TextInput value={value} onChangeText={setValue} style={styles.input}
        placeholder={placeholder} placeholderTextColor={theme.color.textDim}
        keyboardType="decimal-pad" />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 14, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  headerT: { color: theme.color.text, fontSize: 14, letterSpacing: 3, fontWeight: "900", fontFamily: theme.font.display },
  label: { color: theme.color.brand, fontSize: 11, letterSpacing: 2, fontWeight: "900", marginTop: 6, fontFamily: theme.font.textSemi },
  input: { color: theme.color.text, backgroundColor: theme.color.surface2, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 10, fontSize: 14, borderWidth: 1, borderColor: theme.color.border },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: { paddingHorizontal: 10, paddingVertical: 7, borderRadius: 20, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  chipOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1 },
  chipTOn: { color: "#fff" },
  macroRow: { flexDirection: "row", gap: 8 },
  favRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 10, marginTop: 4 },
  favT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  footer: { flexDirection: "row", gap: 8, padding: 14, borderTopWidth: 1, borderTopColor: theme.color.divider, backgroundColor: theme.color.surface },
  btn: { flex: 1, paddingVertical: 14, borderRadius: 8, alignItems: "center" },
  btnGhost: { backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  btnGhostT: { color: theme.color.textMuted, fontSize: 12, fontWeight: "900", letterSpacing: 1.5 },
  btnPri: { backgroundColor: theme.color.brand },
  btnPriT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 1.5 },
});
