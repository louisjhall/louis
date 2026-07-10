/**
 * Nutrition · AI Photo Meal Scan (Phase 3).
 *
 * Flow:
 *   1. Pick a photo (camera OR gallery, iOS/Android; upload input on web).
 *   2. POST /nutrition/photo/analyse with base64 payload → Claude Sonnet 4.5
 *      vision estimates items + macros + confidence + Atlas tip.
 *   3. Review card — every field is editable (macros, items list, tip).
 *   4. Save → writes a nutrition_logs row with source="photo" and links back
 *      to the stored photo via /api/nutrition/photo/{id}/image?token=... .
 */
import React, { useState } from "react";
import {
  ActivityIndicator, Image, Linking, Platform, Pressable, ScrollView, StyleSheet,
  Text, TextInput, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useLocalSearchParams } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import { api, API_BASE, getToken } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast, confirm } from "@/src/lib/ux";

type Scan = {
  id: string;
  mode: string;
  meal_type?: string;
  estimate: {
    items: { name: string; portion?: string }[];
    calories: number; protein_g: number; carbs_g: number; fats_g: number;
    confidence: "low" | "medium" | "high";
    atlas_tip: string;
    warnings?: string[];
    mode: string;
  };
};

const MEALS = [
  { key: "breakfast", label: "BREAKFAST" }, { key: "lunch", label: "LUNCH" }, { key: "dinner", label: "DINNER" },
  { key: "snack", label: "SNACK" }, { key: "pre_flight", label: "PRE-FLIGHT" }, { key: "in_flight", label: "IN-FLIGHT" },
  { key: "post_flight", label: "POST-FLIGHT" }, { key: "post_workout", label: "POST-WORKOUT" },
  { key: "hotel_meal", label: "HOTEL" },
];

export default function PhotoScan() {
  const router = useRouter();
  const params = useLocalSearchParams<{ mode?: string }>();
  const initialMode: "meal" | "hotel_buffet" = params?.mode === "hotel_buffet" ? "hotel_buffet" : "meal";

  const [phase, setPhase] = useState<"pick" | "analysing" | "review">("pick");
  const [mode, setMode] = useState<"meal" | "hotel_buffet">(initialMode);
  const [previewUri, setPreviewUri] = useState<string | null>(null);
  const [scan, setScan] = useState<Scan | null>(null);
  const [mealType, setMealType] = useState<string>("lunch");
  const [saveFav, setSaveFav] = useState(false);
  const [saving, setSaving] = useState(false);
  const [token, setTokenState] = useState<string | null>(null);

  React.useEffect(() => { getToken().then(setTokenState); }, []);

  /* ---------------- Picker ---------------- */

  const pickFromCamera = async () => {
    if (Platform.OS === "web") { pickFromLibrary(); return; }
    const perm = await ImagePicker.requestCameraPermissionsAsync();
    if (perm.status !== "granted") {
      if (perm.canAskAgain === false) {
        const ok = await confirm({
          title: "Camera Access", message: "Camera access was denied. Open Settings to enable it?",
          confirmLabel: "OPEN SETTINGS",
        });
        if (ok) Linking.openSettings();
      } else {
        toast("Camera access needed", "error");
      }
      return;
    }
    const r = await ImagePicker.launchCameraAsync({
      quality: 0.7, base64: true, mediaTypes: ImagePicker.MediaTypeOptions.Images,
    });
    if (r.canceled) return;
    handlePicked(r.assets[0]);
  };

  const pickFromLibrary = async () => {
    if (Platform.OS !== "web") {
      const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (perm.status !== "granted") { toast("Photo access needed", "error"); return; }
    }
    const r = await ImagePicker.launchImageLibraryAsync({
      quality: 0.7, base64: true, mediaTypes: ImagePicker.MediaTypeOptions.Images,
    });
    if (r.canceled) return;
    handlePicked(r.assets[0]);
  };

  const handlePicked = async (asset: ImagePicker.ImagePickerAsset) => {
    if (!asset.base64) { toast("Could not read image", "error"); return; }
    // Detect a sensible mime; ImagePicker doesn't always set it.
    const mime = asset.mimeType || (asset.uri?.match(/\.png/i) ? "image/png" : "image/jpeg");
    setPreviewUri(asset.uri);
    setPhase("analysing");
    try {
      const r = await api<{ scan: Scan }>("/nutrition/photo/analyse", {
        method: "POST",
        body: {
          image_base64: asset.base64, mime,
          mode, meal_type: mealType,
        },
      });
      setScan(r.scan);
      setPhase("review");
      if (r.scan.estimate.warnings?.length) {
        toast("Atlas couldn't fully estimate — please edit anything wrong.", "info");
      }
    } catch (e: any) {
      toast(e?.message || "Analysis failed", "error");
      setPhase("pick");
      setPreviewUri(null);
    }
  };

  /* ---------------- Save ---------------- */

  const save = async () => {
    if (!scan) return;
    setSaving(true);
    try {
      // If the user edited macros/items, PATCH the scan first so backend + edited log stay in sync.
      await api(`/nutrition/photo/${scan.id}/patch`, {
        method: "POST",
        body: {
          items: scan.estimate.items,
          calories: scan.estimate.calories,
          protein_g: scan.estimate.protein_g,
          carbs_g: scan.estimate.carbs_g,
          fats_g: scan.estimate.fats_g,
        },
      });
      await api(`/nutrition/photo/${scan.id}/save-log`, {
        method: "POST",
        body: { meal_type: mealType, save_as_favourite: saveFav },
      });
      toast("Meal logged", "success");
      router.back();
    } catch (e: any) { toast(e?.message || "Save failed", "error"); }
    finally { setSaving(false); }
  };

  const scanAgain = () => {
    setScan(null); setPreviewUri(null); setPhase("pick"); setSaveFav(false);
  };

  const bumpMacro = (key: "calories" | "protein_g" | "carbs_g" | "fats_g", delta: number) => {
    setScan((prev) => {
      if (!prev) return prev;
      const cur = (prev.estimate as any)[key] || 0;
      const next = Math.max(0, +(cur + delta).toFixed(1));
      return { ...prev, estimate: { ...prev.estimate, [key]: next } };
    });
  };

  const setMacro = (key: "calories" | "protein_g" | "carbs_g" | "fats_g", raw: string) => {
    const n = parseFloat(raw.replace(/[^0-9.]/g, "")) || 0;
    setScan((prev) => (prev ? { ...prev, estimate: { ...prev.estimate, [key]: n } } : prev));
  };

  const removeItem = (i: number) => {
    setScan((prev) => prev
      ? { ...prev, estimate: { ...prev.estimate, items: prev.estimate.items.filter((_, idx) => idx !== i) } }
      : prev);
  };

  const addItem = () => {
    setScan((prev) => prev
      ? { ...prev, estimate: { ...prev.estimate, items: [...prev.estimate.items, { name: "", portion: "" }] } }
      : prev);
  };

  const updateItem = (i: number, k: "name" | "portion", v: string) => {
    setScan((prev) => prev
      ? { ...prev, estimate: { ...prev.estimate, items: prev.estimate.items.map((it, idx) => idx === i ? { ...it, [k]: v } : it) } }
      : prev);
  };

  /* ---------------- Render ---------------- */

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => phase === "review" ? scanAgain() : router.back()} hitSlop={12}>
          <Ionicons name={phase === "review" ? "close" : "chevron-back"} size={24} color={theme.color.text} />
        </Pressable>
        <Text style={styles.headerT}>{mode === "hotel_buffet" ? "BUFFET SCAN" : "PHOTO SCAN"}</Text>
        <View style={{ width: 24 }} />
      </View>

      {phase === "pick" ? (
        <ScrollView contentContainerStyle={{ padding: 20, gap: 16 }}>
          <View style={styles.hero}>
            <View style={styles.heroIcon}>
              <Ionicons name={mode === "hotel_buffet" ? "restaurant" : "camera"} size={40} color={theme.color.brand} />
            </View>
            <Text style={styles.heroTitle}>{mode === "hotel_buffet" ? "Hotel Buffet Plate" : "Meal Photo"}</Text>
            <Text style={styles.heroSub}>
              {mode === "hotel_buffet"
                ? "Snap your buffet plate — Atlas will estimate the items and give one practical coaching call."
                : "Snap or upload a photo of your meal. Atlas will estimate items, portions, and macros — always editable."}
            </Text>
          </View>

          <Text style={styles.label}>MODE</Text>
          <View style={styles.modeRow}>
            <ModeCard
              active={mode === "meal"}
              icon="restaurant-outline"
              label="MEAL PHOTO"
              sub="Standard plate estimate"
              onPress={() => setMode("meal")}
            />
            <ModeCard
              active={mode === "hotel_buffet"}
              icon="business"
              label="HOTEL BUFFET"
              sub="Buffet-plate coaching"
              onPress={() => setMode("hotel_buffet")}
            />
          </View>

          <Text style={styles.label}>MEAL TYPE</Text>
          <View style={styles.chipRow}>
            {MEALS.map((m) => (
              <Pressable key={m.key} onPress={() => setMealType(m.key)}
                style={[styles.chip, mealType === m.key && styles.chipOn]}>
                <Text style={[styles.chipT, mealType === m.key && styles.chipTOn]}>{m.label}</Text>
              </Pressable>
            ))}
          </View>

          <View style={{ height: 8 }} />

          {Platform.OS !== "web" ? (
            <Pressable onPress={pickFromCamera} style={styles.primaryBtn} testID="photo-camera">
              <Ionicons name="camera" size={16} color="#fff" />
              <Text style={styles.primaryBtnT}>TAKE PHOTO</Text>
            </Pressable>
          ) : null}
          <Pressable onPress={pickFromLibrary} style={[styles.primaryBtn, Platform.OS !== "web" && styles.primaryBtnAlt]}
            testID="photo-library">
            <Ionicons name={Platform.OS === "web" ? "cloud-upload" : "images"} size={16}
              color={Platform.OS !== "web" ? theme.color.brand : "#fff"} />
            <Text style={[styles.primaryBtnT, Platform.OS !== "web" && { color: theme.color.brand }]}>
              {Platform.OS === "web" ? "UPLOAD PHOTO" : "PICK FROM LIBRARY"}
            </Text>
          </Pressable>

          <Text style={styles.disclaimer}>
            Atlas estimates are coaching guidance, not lab measurements. Always adjust anything that looks wrong before logging.
          </Text>
        </ScrollView>
      ) : phase === "analysing" ? (
        <View style={styles.center}>
          {previewUri ? <Image source={{ uri: previewUri }} style={styles.previewImg} /> : null}
          <ActivityIndicator color={theme.color.brand} size="large" style={{ marginTop: 20 }} />
          <Text style={styles.loadingTitle}>Atlas is analysing your meal…</Text>
          <Text style={styles.loadingSub}>Estimating items, portions and macros. This usually takes 5–15 seconds.</Text>
        </View>
      ) : scan ? (
        <>
          <ScrollView contentContainerStyle={{ padding: 14, gap: 12, paddingBottom: 120 }}>
            {/* Photo */}
            <View style={styles.reviewPhotoWrap}>
              {previewUri ? (
                <Image source={{ uri: previewUri }} style={styles.reviewPhoto} />
              ) : token ? (
                <Image source={{ uri: `${API_BASE}/nutrition/photo/${scan.id}/image?token=${encodeURIComponent(token)}` }}
                  style={styles.reviewPhoto} />
              ) : null}
              <View style={[styles.confPill, confStyle(scan.estimate.confidence)]}>
                <Ionicons name="analytics" size={11} color="#fff" />
                <Text style={styles.confT}>{scan.estimate.confidence.toUpperCase()} CONFIDENCE</Text>
              </View>
            </View>

            {/* Atlas tip */}
            <View style={styles.tipCard}>
              <View style={styles.tipHead}>
                <Ionicons name="sparkles" size={13} color={theme.color.brand} />
                <Text style={styles.tipHeadT}>ATLAS ESTIMATE</Text>
              </View>
              <Text style={styles.tipT}>{scan.estimate.atlas_tip}</Text>
            </View>

            {/* Macros — editable */}
            <View style={styles.macroCard}>
              <MacroInput label="KCAL" value={scan.estimate.calories}
                onDec={() => bumpMacro("calories", -25)} onInc={() => bumpMacro("calories", 25)}
                onChange={(v) => setMacro("calories", v)} unit="" />
              <MacroInput label="PROTEIN" value={scan.estimate.protein_g}
                onDec={() => bumpMacro("protein_g", -5)} onInc={() => bumpMacro("protein_g", 5)}
                onChange={(v) => setMacro("protein_g", v)} unit="g" />
              <MacroInput label="CARBS" value={scan.estimate.carbs_g}
                onDec={() => bumpMacro("carbs_g", -5)} onInc={() => bumpMacro("carbs_g", 5)}
                onChange={(v) => setMacro("carbs_g", v)} unit="g" />
              <MacroInput label="FATS" value={scan.estimate.fats_g}
                onDec={() => bumpMacro("fats_g", -2)} onInc={() => bumpMacro("fats_g", 2)}
                onChange={(v) => setMacro("fats_g", v)} unit="g" />
            </View>

            {/* Items — editable */}
            <Text style={styles.label}>DETECTED ITEMS · {scan.estimate.items.length}</Text>
            {scan.estimate.items.map((it, i) => (
              <View key={i} style={styles.itemRow}>
                <TextInput value={it.name} onChangeText={(v) => updateItem(i, "name", v)}
                  placeholder="Item name" placeholderTextColor={theme.color.textDim}
                  style={[styles.itemInput, { flex: 2 }]} />
                <TextInput value={it.portion || ""} onChangeText={(v) => updateItem(i, "portion", v)}
                  placeholder="Portion" placeholderTextColor={theme.color.textDim}
                  style={[styles.itemInput, { flex: 1.2 }]} />
                <Pressable onPress={() => removeItem(i)} hitSlop={8} style={styles.itemDel}>
                  <Ionicons name="close" size={14} color="#c94a4a" />
                </Pressable>
              </View>
            ))}
            <Pressable onPress={addItem} style={styles.addItemBtn}>
              <Ionicons name="add" size={14} color={theme.color.brand} />
              <Text style={styles.addItemBtnT}>ADD ITEM</Text>
            </Pressable>

            {/* Meal type override */}
            <Text style={styles.label}>MEAL TYPE</Text>
            <View style={styles.chipRow}>
              {MEALS.map((m) => (
                <Pressable key={m.key} onPress={() => setMealType(m.key)}
                  style={[styles.chip, mealType === m.key && styles.chipOn]}>
                  <Text style={[styles.chipT, mealType === m.key && styles.chipTOn]}>{m.label}</Text>
                </Pressable>
              ))}
            </View>

            <Pressable onPress={() => setSaveFav((v) => !v)} style={styles.favRow}>
              <Ionicons name={saveFav ? "checkmark-circle" : "ellipse-outline"}
                size={18} color={saveFav ? theme.color.brand : theme.color.textMuted} />
              <Text style={styles.favT}>SAVE AS FAVOURITE</Text>
            </Pressable>

            {scan.estimate.warnings?.length ? (
              <View style={styles.warnCard}>
                <Ionicons name="warning" size={12} color={theme.color.amber} />
                <Text style={styles.warnT}>{scan.estimate.warnings.join(" · ")}</Text>
              </View>
            ) : null}
          </ScrollView>

          <View style={styles.footer}>
            <Pressable onPress={scanAgain} style={[styles.footerBtn, styles.footerBtnGhost]}>
              <Text style={styles.footerBtnGhostT}>NEW PHOTO</Text>
            </Pressable>
            <Pressable onPress={save} disabled={saving} style={[styles.footerBtn, styles.footerBtnPri, saving && { opacity: 0.5 }]}
              testID="photo-save">
              {saving ? <ActivityIndicator color="#fff" /> : <Text style={styles.footerBtnT}>LOG MEAL</Text>}
            </Pressable>
          </View>
        </>
      ) : null}
    </SafeAreaView>
  );
}

/* -------------------- sub-components -------------------- */

function ModeCard({ active, icon, label, sub, onPress }: { active: boolean; icon: any; label: string; sub: string; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={[styles.modeCard, active && styles.modeCardOn]}>
      <Ionicons name={icon} size={22} color={active ? "#fff" : theme.color.brand} />
      <Text style={[styles.modeCardT, active && { color: "#fff" }]}>{label}</Text>
      <Text style={[styles.modeCardSub, active && { color: "rgba(255,255,255,0.75)" }]}>{sub}</Text>
    </Pressable>
  );
}

function MacroInput({ label, value, unit, onDec, onInc, onChange }: {
  label: string; value: number; unit: string;
  onDec: () => void; onInc: () => void; onChange: (v: string) => void;
}) {
  return (
    <View style={styles.macroCol}>
      <Text style={styles.macroK}>{label}</Text>
      <View style={styles.macroInputRow}>
        <Pressable onPress={onDec} hitSlop={6} style={styles.macroStep}><Ionicons name="remove" size={12} color="#fff" /></Pressable>
        <TextInput
          value={String(Math.round(value))}
          onChangeText={onChange}
          keyboardType="numeric"
          style={styles.macroInput}
        />
        <Pressable onPress={onInc} hitSlop={6} style={styles.macroStep}><Ionicons name="add" size={12} color="#fff" /></Pressable>
      </View>
      {unit ? <Text style={styles.macroUnit}>{unit}</Text> : <View style={{ height: 10 }} />}
    </View>
  );
}

function confStyle(c: string) {
  if (c === "high") return { backgroundColor: theme.color.green };
  if (c === "low") return { backgroundColor: "#c94a4a" };
  return { backgroundColor: theme.color.amber };
}

/* -------------------- styles -------------------- */

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 14, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  headerT: { color: theme.color.text, fontSize: 14, letterSpacing: 3, fontWeight: "900", fontFamily: theme.font.display },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24, gap: 8 },

  hero: { alignItems: "center", gap: 8, marginBottom: 6 },
  heroIcon: { width: 74, height: 74, borderRadius: 37, backgroundColor: theme.color.brandTint, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: theme.color.brand },
  heroTitle: { color: theme.color.text, fontSize: 20, fontWeight: "900", fontFamily: theme.font.display, letterSpacing: 0.5, textAlign: "center" },
  heroSub: { color: theme.color.textMuted, fontSize: 13, lineHeight: 20, textAlign: "center", fontFamily: theme.font.text, paddingHorizontal: 20 },

  label: { color: theme.color.brand, fontSize: 10, letterSpacing: 2, fontWeight: "900", marginTop: 6, fontFamily: theme.font.textSemi },

  modeRow: { flexDirection: "row", gap: 8 },
  modeCard: { flex: 1, padding: 14, borderRadius: 12, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, gap: 4 },
  modeCardOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  modeCardT: { color: theme.color.text, fontSize: 12, fontWeight: "900", letterSpacing: 1, marginTop: 4, fontFamily: theme.font.textSemi },
  modeCardSub: { color: theme.color.textMuted, fontSize: 10, fontFamily: theme.font.text },

  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 20, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  chipOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipT: { color: theme.color.textMuted, fontSize: 9, fontWeight: "900", letterSpacing: 1 },
  chipTOn: { color: "#fff" },

  primaryBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingVertical: 14, borderRadius: 10, backgroundColor: theme.color.brand },
  primaryBtnAlt: { backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.brand },
  primaryBtnT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 1.5 },
  disclaimer: { color: theme.color.textDim, fontSize: 11, textAlign: "center", fontStyle: "italic", lineHeight: 17, paddingHorizontal: 10, marginTop: 4 },

  loadingTitle: { color: theme.color.text, fontSize: 15, fontWeight: "900", marginTop: 14, fontFamily: theme.font.display },
  loadingSub: { color: theme.color.textMuted, fontSize: 12, textAlign: "center", lineHeight: 18, fontFamily: theme.font.text },
  previewImg: { width: 220, height: 220, borderRadius: 16 },

  reviewPhotoWrap: { position: "relative" },
  reviewPhoto: { width: "100%", aspectRatio: 4 / 3, borderRadius: 14, backgroundColor: theme.color.surface3 },
  confPill: { position: "absolute", top: 10, right: 10, flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6 },
  confT: { color: "#fff", fontSize: 9, letterSpacing: 1, fontWeight: "900" },

  tipCard: { padding: 12, borderRadius: 12, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand },
  tipHead: { flexDirection: "row", alignItems: "center", gap: 5, marginBottom: 6 },
  tipHeadT: { color: theme.color.brand, fontSize: 10, letterSpacing: 2, fontWeight: "900" },
  tipT: { color: theme.color.text, fontSize: 13, lineHeight: 20, fontFamily: theme.font.text },

  macroCard: { flexDirection: "row", gap: 6, padding: 10, borderRadius: 10, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  macroCol: { flex: 1, alignItems: "center" },
  macroK: { color: theme.color.textMuted, fontSize: 9, letterSpacing: 1.5, fontWeight: "900" },
  macroInputRow: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 6 },
  macroStep: { width: 22, height: 22, borderRadius: 11, backgroundColor: theme.color.brand, alignItems: "center", justifyContent: "center" },
  macroInput: { width: 44, height: 28, color: theme.color.text, backgroundColor: theme.color.surface3, borderRadius: 6, textAlign: "center", fontSize: 13, fontWeight: "900", fontFamily: theme.font.display, borderWidth: 1, borderColor: theme.color.border, padding: 0 },
  macroUnit: { color: theme.color.textDim, fontSize: 9, marginTop: 3, letterSpacing: 0.5 },

  itemRow: { flexDirection: "row", gap: 6, alignItems: "center" },
  itemInput: { color: theme.color.text, backgroundColor: theme.color.surface2, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 8, fontSize: 13, borderWidth: 1, borderColor: theme.color.border },
  itemDel: { width: 30, height: 30, borderRadius: 15, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, alignItems: "center", justifyContent: "center" },
  addItemBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 5, paddingVertical: 10, borderRadius: 8, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand, borderStyle: "dashed" },
  addItemBtnT: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1 },

  favRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 10 },
  favT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },

  warnCard: { flexDirection: "row", alignItems: "center", gap: 6, padding: 10, borderRadius: 8, backgroundColor: "#1F1608", borderWidth: 1, borderColor: theme.color.amber },
  warnT: { color: theme.color.amber, fontSize: 11, fontWeight: "800", flex: 1 },

  footer: { flexDirection: "row", gap: 8, padding: 14, borderTopWidth: 1, borderTopColor: theme.color.divider, backgroundColor: theme.color.surface },
  footerBtn: { flex: 1, paddingVertical: 14, borderRadius: 8, alignItems: "center" },
  footerBtnGhost: { backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  footerBtnGhostT: { color: theme.color.textMuted, fontSize: 12, fontWeight: "900", letterSpacing: 1.5 },
  footerBtnPri: { backgroundColor: theme.color.brand },
  footerBtnT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 1.5 },
});
