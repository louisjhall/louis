import { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput, RefreshControl,
  ActivityIndicator, KeyboardAvoidingView, Platform,
} from "react-native";
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import { useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

export default function Nutrition() {
  const [summary, setSummary] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [meal, setMeal] = useState({ meal_type: "breakfast", description: "" });
  const [photo, setPhoto] = useState<{ base64: string; mime: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const s = await api<any>("/nutrition/summary");
      setSummary(s);
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const pickPhoto = async () => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) return;
    const res = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      base64: true,
      quality: 0.6,
    });
    if (!res.canceled && res.assets[0]?.base64) {
      const a = res.assets[0];
      setPhoto({ base64: a.base64!, mime: a.mimeType || "image/jpeg" });
    }
  };

  const submit = async () => {
    setSaving(true);
    setErr(null);
    try {
      await api("/nutrition/meals", {
        method: "POST",
        body: {
          meal_type: meal.meal_type,
          description: meal.description,
          photo_base64: photo?.base64 || null,
          photo_mime: photo?.mime || null,
        },
      });
      setMeal({ meal_type: "breakfast", description: "" });
      setPhoto(null);
      setShowAdd(false);
      await load();
    } catch (e: any) { setErr(e.message); }
    finally { setSaving(false); }
  };

  const calPct = summary ? Math.min(100, ((summary.calories || 0) / (summary.calorie_target || 1)) * 100) : 0;
  const proPct = summary ? Math.min(100, ((summary.protein_g || 0) / (summary.protein_target || 1)) * 100) : 0;

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Text style={styles.title}>NUTRITION</Text>
        <Pressable testID="add-meal-btn" onPress={() => setShowAdd((x) => !x)} style={styles.addBtn}>
          <Ionicons name={showAdd ? "close" : "add"} size={22} color="#fff" />
        </Pressable>
      </View>
      <ScrollView
        contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 60 }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}
        keyboardShouldPersistTaps="handled"
      >
        {summary && (
          <View style={styles.macros}>
            <Macro label="CALORIES" value={summary.calories} target={summary.calorie_target} pct={calPct} unit="kcal" />
            <Macro label="PROTEIN" value={summary.protein_g} target={summary.protein_target} pct={proPct} unit="g" />
          </View>
        )}

        {showAdd && (
          <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined}>
            <View style={styles.addCard}>
              <Text style={styles.sectLabel}>LOG MEAL</Text>
              <View style={styles.mealRow}>
                {["breakfast", "lunch", "dinner", "snack"].map((t) => (
                  <Pressable
                    key={t}
                    onPress={() => setMeal((m) => ({ ...m, meal_type: t }))}
                    testID={`meal-type-${t}`}
                    style={[styles.chip, meal.meal_type === t && styles.chipActive]}
                  >
                    <Text style={[styles.chipText, meal.meal_type === t && { color: "#fff" }]}>{t}</Text>
                  </Pressable>
                ))}
              </View>
              <TextInput
                testID="meal-description"
                style={styles.input}
                value={meal.description}
                onChangeText={(t) => setMeal((m) => ({ ...m, description: t }))}
                placeholder="Grilled chicken + rice + veg"
                placeholderTextColor={theme.color.textDim}
                multiline
              />
              <Pressable testID="pick-photo" onPress={pickPhoto} style={styles.photoBtn}>
                {photo ? (
                  <Image source={{ uri: `data:${photo.mime};base64,${photo.base64}` }} style={{ width: "100%", height: 160, borderRadius: theme.radius.md }} contentFit="cover" />
                ) : (
                  <>
                    <Ionicons name="camera" size={22} color={theme.color.brand} />
                    <Text style={styles.photoText}>ADD PHOTO (AI FEEDBACK)</Text>
                  </>
                )}
              </Pressable>
              {err && <Text style={{ color: theme.color.red, marginTop: 8 }}>{err}</Text>}
              <Pressable testID="submit-meal" onPress={submit} disabled={saving || !meal.description} style={[styles.cta, (saving || !meal.description) && { opacity: 0.5 }]}>
                {saving ? <ActivityIndicator color="#fff" /> : <Text style={styles.ctaText}>LOG MEAL</Text>}
              </Pressable>
            </View>
          </KeyboardAvoidingView>
        )}

        <Text style={styles.sectLabel}>{`TODAY'S MEALS`}</Text>
        {loading ? (
          <ActivityIndicator color={theme.color.brand} />
        ) : summary?.meals?.length === 0 ? (
          <Text style={{ color: theme.color.textMuted }}>No meals logged yet.</Text>
        ) : (
          summary?.meals?.map((m: any) => (
            <View key={m.id} style={styles.mealCard} testID={`meal-card-${m.id}`}>
              {m.photo_base64 && (
                <Image source={{ uri: `data:${m.photo_mime};base64,${m.photo_base64}` }} style={{ width: 72, height: 72, borderRadius: theme.radius.sm }} contentFit="cover" />
              )}
              <View style={{ flex: 1, marginLeft: m.photo_base64 ? theme.space.md : 0 }}>
                <Text style={styles.mealType}>{m.meal_type?.toUpperCase()}</Text>
                <Text style={styles.mealDesc}>{m.description}</Text>
                <Text style={styles.mealMeta}>
                  {m.calories ? `${m.calories} kcal` : "—"} · {m.protein_g ? `${m.protein_g}g protein` : "—"}
                </Text>
                {m.ai_feedback?.tip && <Text style={styles.aiTip}>💡 {m.ai_feedback.tip}</Text>}
              </View>
            </View>
          ))
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function Macro({ label, value, target, pct, unit }: any) {
  return (
    <View style={styles.macroCol}>
      <Text style={styles.macroLabel}>{label}</Text>
      <Text style={styles.macroVal}>
        {value || 0}<Text style={styles.macroTarget}> / {target}{unit}</Text>
      </Text>
      <View style={styles.progressBg}>
        <View style={[styles.progressFill, { width: `${pct}%` }]} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  title: { color: theme.color.text, fontSize: 20, fontWeight: "900", letterSpacing: 2 },
  addBtn: { backgroundColor: theme.color.brand, width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center" },
  macros: { flexDirection: "row", gap: theme.space.md },
  macroCol: { flex: 1, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, padding: theme.space.md, borderWidth: 1, borderColor: theme.color.border },
  macroLabel: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 2, fontWeight: "800" },
  macroVal: { color: theme.color.text, fontSize: 22, fontWeight: "900", marginTop: 6 },
  macroTarget: { color: theme.color.textDim, fontSize: 12, fontWeight: "500" },
  progressBg: { height: 4, backgroundColor: theme.color.surface3, borderRadius: 2, marginTop: theme.space.sm, overflow: "hidden" },
  progressFill: { height: "100%", backgroundColor: theme.color.brand },
  addCard: { marginTop: theme.space.md, padding: theme.space.md, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border },
  sectLabel: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 2, fontWeight: "800", marginTop: theme.space.lg, marginBottom: theme.space.sm },
  mealRow: { flexDirection: "row", gap: 6, flexWrap: "wrap" },
  chip: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: theme.radius.pill, backgroundColor: theme.color.surface3, borderWidth: 1, borderColor: theme.color.border },
  chipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipText: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700" },
  input: { backgroundColor: theme.color.surface3, borderRadius: theme.radius.md, color: theme.color.text, padding: theme.space.md, borderWidth: 1, borderColor: theme.color.border, marginTop: theme.space.sm, minHeight: 60 },
  photoBtn: { marginTop: theme.space.sm, borderRadius: theme.radius.md, borderWidth: 1, borderStyle: "dashed", borderColor: theme.color.borderStrong, minHeight: 80, alignItems: "center", justifyContent: "center", overflow: "hidden" },
  photoText: { color: theme.color.brand, marginTop: 4, letterSpacing: 1.5, fontWeight: "700", fontSize: 11 },
  cta: { backgroundColor: theme.color.brand, marginTop: theme.space.md, paddingVertical: 14, borderRadius: theme.radius.md, alignItems: "center" },
  ctaText: { color: "#fff", fontWeight: "800", letterSpacing: 2 },
  mealCard: { flexDirection: "row", padding: theme.space.md, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, marginBottom: theme.space.sm },
  mealType: { color: theme.color.brand, fontSize: 10, letterSpacing: 1.5, fontWeight: "800" },
  mealDesc: { color: theme.color.text, marginTop: 2, fontSize: 14 },
  mealMeta: { color: theme.color.textDim, marginTop: 4, fontSize: 12 },
  aiTip: { color: theme.color.amber, marginTop: 6, fontSize: 12, fontStyle: "italic" },
});
