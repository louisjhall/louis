/**
 * Nutrition · Food Search — Phase 2.
 *
 * Search bar + aviation quick-chips + curated local DB + Open Food Facts +
 * Atlas estimate fallback. Selecting a result opens a serving/meal-type
 * editor that lets the client adjust portion, quantity and meal type
 * before saving via the existing /api/nutrition/logs endpoint.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView,
  StyleSheet, Text, TextInput, View, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast } from "@/src/lib/ux";

type FoodResult = {
  id: string;
  source: "local" | "off" | "atlas" | "atlas-local" | "atlas-placeholder";
  name: string;
  brand?: string | null;
  image_url?: string | null;
  calories: number;
  protein_g: number;
  carbs_g: number;
  fats_g: number;
  serving_size?: string | null;
  per_100g?: boolean;
  estimated?: boolean;
  explanation?: string;
};

type QuickChip = { label: string; query: string };

const MEALS = [
  { key: "breakfast", label: "Breakfast" }, { key: "lunch", label: "Lunch" },
  { key: "dinner", label: "Dinner" }, { key: "snack", label: "Snack" },
  { key: "pre_flight", label: "Pre-flight" }, { key: "in_flight", label: "In-flight" },
  { key: "post_flight", label: "Post-flight" }, { key: "hotel_meal", label: "Hotel" },
  { key: "airport_meal", label: "Airport" }, { key: "crew_meal", label: "Crew" },
];

export default function FoodSearchScreen() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [results, setResults] = useState<FoodResult[]>([]);
  const [chips, setChips] = useState<QuickChip[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recent, setRecent] = useState<any[]>([]);

  const [editing, setEditing] = useState<FoodResult | null>(null);
  const [atlasOpen, setAtlasOpen] = useState(false);

  // Debounce search.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 350);
    return () => clearTimeout(t);
  }, [q]);

  const runSearch = useCallback(async (term: string) => {
    if (term.length < 2) { setResults([]); setError(null); return; }
    setLoading(true); setError(null);
    try {
      const res = await api<{ results: FoodResult[]; chips: QuickChip[] }>(
        `/nutrition/food-search?q=${encodeURIComponent(term)}&limit=8`,
      );
      setResults(res.results || []);
      setChips(res.chips || []);
    } catch {
      setError("Food search is temporarily unavailable. You can still log manually.");
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { runSearch(debouncedQ); }, [debouncedQ, runSearch]);

  useEffect(() => {
    (async () => {
      try {
        const r = await api<{ results: any[] }>("/nutrition/food-recent?limit=6");
        setRecent(r.results || []);
      } catch { /* non-fatal */ }
    })();
  }, []);

  // Also fetch chips even before typing so the empty state is populated.
  useEffect(() => {
    if (chips.length === 0) {
      runSearch("chicken"); // priming call also seeds `chips`
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="food-search-back">
          <Ionicons name="chevron-back" size={22} color={theme.color.text} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>Search Food Database</Text>
          <Text style={styles.subtitle}>Search common foods, meals and branded items.</Text>
        </View>
      </View>

      <View style={styles.searchWrap}>
        <Ionicons name="search" size={16} color={theme.color.textDim} />
        <TextInput
          testID="food-search-input"
          style={styles.searchInput}
          placeholder="Search for a food, meal or brand…"
          placeholderTextColor={theme.color.textDim}
          value={q}
          onChangeText={setQ}
          autoCapitalize="none"
          autoCorrect
          returnKeyType="search"
        />
        {q.length > 0 && (
          <Pressable onPress={() => setQ("")} hitSlop={8} testID="food-search-clear">
            <Ionicons name="close-circle" size={16} color={theme.color.textDim} />
          </Pressable>
        )}
      </View>

      <ScrollView contentContainerStyle={{ paddingBottom: 40 }} keyboardShouldPersistTaps="handled">
        {/* Aviation quick chips */}
        {chips.length > 0 && (
          <>
            <Text style={styles.sect}>QUICK</Text>
            <View style={styles.chipsRow}>
              {chips.map((c) => (
                <Pressable
                  key={c.label}
                  onPress={() => setQ(c.query)}
                  style={styles.chip}
                  testID={`food-chip-${c.label}`}
                >
                  <Text style={styles.chipText}>{c.label}</Text>
                </Pressable>
              ))}
            </View>
          </>
        )}

        {/* Recent */}
        {recent.length > 0 && debouncedQ.length < 2 && (
          <>
            <Text style={styles.sect}>RECENT</Text>
            {recent.map((r, i) => (
              <ResultCard
                key={`recent-${i}`}
                item={{
                  id: `recent-${i}`,
                  source: "local",
                  name: r.food_name,
                  brand: null,
                  calories: r.calories, protein_g: r.protein_g,
                  carbs_g: r.carbs_g, fats_g: r.fats_g,
                  serving_size: r.portion || "1 serving",
                  per_100g: false,
                }}
                onSelect={setEditing}
              />
            ))}
          </>
        )}

        {/* Results */}
        {debouncedQ.length >= 2 && (
          <>
            <Text style={styles.sect}>RESULTS</Text>
            {loading && <ActivityIndicator color={theme.color.brand} style={{ marginTop: 12 }} />}
            {!loading && error && (
              <View style={styles.errorBox}>
                <Ionicons name="alert-circle" size={16} color={theme.color.brand} />
                <Text style={styles.errorText}>{error}</Text>
              </View>
            )}
            {!loading && !error && results.length === 0 && (
              <View style={styles.emptyBox}>
                <Text style={styles.emptyTitle}>No foods found</Text>
                <Text style={styles.emptyCopy}>Try a simpler search or estimate with Atlas.</Text>
              </View>
            )}
            {!loading && results.map((r) => (
              <ResultCard key={r.id} item={r} onSelect={setEditing} />
            ))}
          </>
        )}

        {/* Atlas estimate */}
        <View style={styles.atlasWrap}>
          <Text style={styles.atlasQuestion}>Can’t find it?</Text>
          <Pressable
            testID="food-atlas-open"
            onPress={() => setAtlasOpen(true)}
            style={styles.atlasBtn}
          >
            <Ionicons name="sparkles" size={14} color="#fff" />
            <Text style={styles.atlasBtnText}>ESTIMATE WITH ATLAS</Text>
          </Pressable>
          <Text style={styles.disclaimer}>
            Nutrition values are estimates and may vary by brand, portion and preparation method.
          </Text>
        </View>
      </ScrollView>

      <ServingEditorModal
        food={editing}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          // refresh recent so the just-logged food shows up
          api<{ results: any[] }>("/nutrition/food-recent?limit=6").then((r) => setRecent(r.results || [])).catch(() => {});
        }}
      />
      <AtlasEstimateModal
        visible={atlasOpen}
        onClose={() => setAtlasOpen(false)}
        onEstimated={(food) => {
          setAtlasOpen(false);
          setEditing(food);
        }}
      />
    </SafeAreaView>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ResultCard({ item, onSelect }: { item: FoodResult; onSelect: (f: FoodResult) => void }) {
  const macro = `${Math.round(item.protein_g)}g P · ${Math.round(item.carbs_g)}g C · ${Math.round(item.fats_g)}g F`;
  const serving = item.serving_size || (item.per_100g ? "100g" : "1 serving");
  return (
    <View style={styles.card}>
      <View style={{ flex: 1 }}>
        <Text style={styles.cardName} numberOfLines={1}>{item.name}</Text>
        <View style={styles.cardMetaRow}>
          {item.brand ? <Text style={styles.cardBrand} numberOfLines={1}>{item.brand}</Text> : null}
          <SourceBadge source={item.source} estimated={item.estimated} />
        </View>
        <Text style={styles.cardKcal}>{Math.round(item.calories)} kcal per {serving}</Text>
        <Text style={styles.cardMacro}>{macro}</Text>
      </View>
      <Pressable onPress={() => onSelect(item)} style={styles.addBtn} testID={`food-add-${item.id}`}>
        <Ionicons name="add" size={18} color="#fff" />
        <Text style={styles.addBtnText}>ADD</Text>
      </Pressable>
    </View>
  );
}

function SourceBadge({ source, estimated }: { source: FoodResult["source"]; estimated?: boolean }) {
  const isAtlas = source && source.startsWith("atlas");
  if (isAtlas || estimated) return <Text style={[styles.badge, styles.badgeAtlas]}>ATLAS EST.</Text>;
  if (source === "off") return <Text style={[styles.badge, styles.badgeOff]}>BRANDED</Text>;
  return <Text style={[styles.badge, styles.badgeLocal]}>CREWFIT</Text>;
}

function ServingEditorModal({
  food, onClose, onSaved,
}: { food: FoodResult | null; onClose: () => void; onSaved: () => void }) {
  const isOpen = !!food;
  const [servings, setServings] = useState("1");
  const [meal, setMeal] = useState("snack");
  const [kcal, setKcal] = useState("0");
  const [pro, setPro] = useState("0");
  const [carb, setCarb] = useState("0");
  const [fat, setFat] = useState("0");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (food) {
      setServings("1");
      setMeal("snack");
      setKcal(String(Math.round(food.calories)));
      setPro(String(Math.round(food.protein_g)));
      setCarb(String(Math.round(food.carbs_g)));
      setFat(String(Math.round(food.fats_g)));
    }
  }, [food]);

  const scaled = useMemo(() => {
    const s = Math.max(0.25, parseFloat(servings || "1") || 1);
    return {
      kcal: Math.round((parseFloat(kcal || "0") || 0) * s),
      pro: Math.round((parseFloat(pro || "0") || 0) * s),
      carb: Math.round((parseFloat(carb || "0") || 0) * s),
      fat: Math.round((parseFloat(fat || "0") || 0) * s),
    };
  }, [servings, kcal, pro, carb, fat]);

  const save = async () => {
    if (!food) return;
    setSaving(true);
    try {
      await api("/nutrition/logs", {
        method: "POST",
        body: {
          food_name: food.name,
          meal_type: meal,
          calories: scaled.kcal,
          protein_g: scaled.pro,
          carbs_g: scaled.carb,
          fats_g: scaled.fat,
          portion: `${servings} × ${food.serving_size || "1 serving"}`,
          notes: food.estimated ? "Atlas estimate — please verify." : undefined,
          source: food.estimated ? "food_search_atlas" : (food.source === "off" ? "food_search_off" : "food_search"),
          brand: food.brand || undefined,
          estimated: !!food.estimated,
        },
      });
      toast("Logged to today", "success");
      onSaved();
    } catch (e: any) {
      Alert.alert("Couldn’t save", e?.message || "Try again.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal visible={isOpen} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose} />
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={styles.sheetWrap}>
        <View style={styles.sheet}>
          <View style={styles.grabber} />
          {food && (
            <ScrollView keyboardShouldPersistTaps="handled">
              <Text style={styles.sheetTitle} numberOfLines={2}>{food.name}</Text>
              {food.brand ? <Text style={styles.sheetBrand}>{food.brand}</Text> : null}
              <Text style={styles.sheetKcal}>
                {scaled.kcal} kcal · {scaled.pro}g P · {scaled.carb}g C · {scaled.fat}g F
              </Text>

              {food.estimated && (
                <View style={styles.estimateBanner}>
                  <Ionicons name="information-circle" size={14} color="#fff" />
                  <Text style={styles.estimateBannerText}>
                    This is an estimate. Adjust if needed.
                  </Text>
                </View>
              )}

              <Text style={styles.fieldLabel}>SERVINGS</Text>
              <View style={styles.servingRow}>
                <Pressable style={styles.stepBtn} onPress={() => setServings((s) => String(Math.max(0.25, +parseFloat(s || "1") - 0.5)))}>
                  <Ionicons name="remove" color={theme.color.text} size={18} />
                </Pressable>
                <TextInput
                  style={styles.servingInput}
                  keyboardType="decimal-pad"
                  value={servings}
                  onChangeText={setServings}
                  testID="food-servings"
                />
                <Text style={styles.servingUnit}>× {food.serving_size || "serving"}</Text>
                <Pressable style={styles.stepBtn} onPress={() => setServings((s) => String((parseFloat(s || "1") || 1) + 0.5))}>
                  <Ionicons name="add" color={theme.color.text} size={18} />
                </Pressable>
              </View>

              <Text style={styles.fieldLabel}>MEAL</Text>
              <View style={styles.mealsGrid}>
                {MEALS.map((m) => (
                  <Pressable
                    key={m.key}
                    onPress={() => setMeal(m.key)}
                    style={[styles.mealChip, meal === m.key && styles.mealChipActive]}
                  >
                    <Text style={[styles.mealChipText, meal === m.key && { color: "#fff" }]}>{m.label}</Text>
                  </Pressable>
                ))}
              </View>

              <Text style={styles.fieldLabel}>MACROS (per serving)</Text>
              <View style={styles.macroRow}>
                <MacroInput label="kcal" value={kcal} onChange={setKcal} />
                <MacroInput label="P" value={pro} onChange={setPro} />
                <MacroInput label="C" value={carb} onChange={setCarb} />
                <MacroInput label="F" value={fat} onChange={setFat} />
              </View>

              <Pressable
                testID="food-add-to-log"
                onPress={save}
                disabled={saving}
                style={[styles.primaryBtn, saving && { opacity: 0.6 }]}
              >
                {saving ? <ActivityIndicator color="#fff" /> : (
                  <>
                    <Ionicons name="checkmark" color="#fff" size={16} />
                    <Text style={styles.primaryBtnText}>ADD TO LOG</Text>
                  </>
                )}
              </Pressable>
              <Text style={styles.disclaimer}>
                Values are estimates. Edit them if the portion or brand differs.
              </Text>
              <View style={{ height: 20 }} />
            </ScrollView>
          )}
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

function MacroInput({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <View style={styles.macroBox}>
      <Text style={styles.macroBoxLabel}>{label}</Text>
      <TextInput
        style={styles.macroBoxInput}
        keyboardType="decimal-pad"
        value={value}
        onChangeText={onChange}
      />
    </View>
  );
}

function AtlasEstimateModal({
  visible, onClose, onEstimated,
}: { visible: boolean; onClose: () => void; onEstimated: (food: FoodResult) => void }) {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);

  const go = async () => {
    if (!text.trim() || text.trim().length < 3) {
      toast("Describe the food (e.g. Hotel eggs and toast)", "error");
      return;
    }
    setLoading(true);
    try {
      const est = await api<FoodResult>("/nutrition/food-estimate", {
        method: "POST",
        body: { description: text.trim() },
      });
      onEstimated({ ...est, id: `atlas-${Date.now()}` });
    } catch (e: any) {
      Alert.alert("Estimate unavailable", e?.message || "Please try again.");
    } finally { setLoading(false); }
  };

  useEffect(() => { if (!visible) setText(""); }, [visible]);

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose} />
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={styles.sheetWrap}>
        <View style={styles.sheet}>
          <View style={styles.grabber} />
          <Text style={styles.sheetTitle}>Estimate with Atlas</Text>
          <Text style={styles.sheetBrand}>Describe the meal — Atlas will estimate macros.</Text>
          <TextInput
            testID="food-atlas-input"
            style={[styles.searchInput, { backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, padding: 12, borderRadius: 10, marginTop: 12 }]}
            placeholder="e.g. Chicken wrap from airport"
            placeholderTextColor={theme.color.textDim}
            value={text}
            onChangeText={setText}
            multiline
          />
          <Pressable
            testID="food-atlas-submit"
            onPress={go}
            disabled={loading}
            style={[styles.primaryBtn, loading && { opacity: 0.6 }]}
          >
            {loading ? <ActivityIndicator color="#fff" /> : (
              <>
                <Ionicons name="sparkles" color="#fff" size={16} />
                <Text style={styles.primaryBtnText}>ESTIMATE</Text>
              </>
            )}
          </Pressable>
          <Text style={styles.disclaimer}>
            Atlas estimates are educated guesses. You’ll be able to adjust the macros before saving.
          </Text>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: theme.space.lg, paddingTop: theme.space.md, paddingBottom: theme.space.sm },
  title: { color: theme.color.text, fontSize: 20, fontWeight: "900", letterSpacing: 0.3 },
  subtitle: { color: theme.color.textMuted, fontSize: 12, marginTop: 2 },
  searchWrap: {
    flexDirection: "row", alignItems: "center", gap: 8,
    marginHorizontal: theme.space.lg, marginBottom: theme.space.md,
    backgroundColor: theme.color.surface2, borderRadius: 12,
    borderWidth: 1, borderColor: theme.color.border,
    paddingHorizontal: 12, paddingVertical: Platform.OS === "ios" ? 10 : 4,
  },
  searchInput: { flex: 1, color: theme.color.text, fontSize: 15 },
  sect: { color: theme.color.textDim, fontSize: 11, fontWeight: "900", letterSpacing: 2, marginTop: theme.space.md, marginHorizontal: theme.space.lg, marginBottom: 8 },
  // Chips
  chipsRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, paddingHorizontal: theme.space.lg },
  chip: {
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: theme.radius.pill,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  chipText: { color: theme.color.text, fontSize: 12, fontWeight: "700" },
  // Cards
  card: {
    flexDirection: "row", alignItems: "center", gap: 10,
    marginHorizontal: theme.space.lg, marginBottom: 10, padding: 12,
    backgroundColor: theme.color.surface2, borderRadius: 12,
    borderWidth: 1, borderColor: theme.color.border,
  },
  cardName: { color: theme.color.text, fontWeight: "800", fontSize: 15 },
  cardMetaRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 2, flexWrap: "wrap" },
  cardBrand: { color: theme.color.textDim, fontSize: 11, flexShrink: 1 },
  cardKcal: { color: theme.color.text, fontWeight: "700", fontSize: 13, marginTop: 4 },
  cardMacro: { color: theme.color.textMuted, fontSize: 12, marginTop: 2 },
  addBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: theme.color.brand, paddingHorizontal: 12, paddingVertical: 8, borderRadius: theme.radius.pill,
  },
  addBtnText: { color: "#fff", fontWeight: "900", fontSize: 12, letterSpacing: 1 },
  // Badges
  badge: {
    fontSize: 11, fontWeight: "900", letterSpacing: 1,
    paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4, overflow: "hidden",
  },
  badgeLocal: { backgroundColor: theme.color.brandTint, color: theme.color.brand },
  badgeOff: { backgroundColor: "rgba(255,255,255,0.06)", color: theme.color.textMuted },
  badgeAtlas: { backgroundColor: "#3a2900", color: "#F59E0B" },
  // Empty / error
  errorBox: {
    marginHorizontal: theme.space.lg, marginTop: 8, padding: 10, borderRadius: 10,
    borderWidth: 1, borderColor: theme.color.border,
    backgroundColor: theme.color.brandTint, flexDirection: "row", alignItems: "center", gap: 8,
  },
  errorText: { color: theme.color.text, fontSize: 12 },
  emptyBox: { marginHorizontal: theme.space.lg, marginTop: 10, padding: 16, alignItems: "center", gap: 4 },
  emptyTitle: { color: theme.color.text, fontWeight: "800" },
  emptyCopy: { color: theme.color.textMuted, fontSize: 12 },
  // Atlas
  atlasWrap: { marginTop: 24, marginHorizontal: theme.space.lg, alignItems: "center", gap: 8, paddingTop: 16, borderTopWidth: 1, borderTopColor: theme.color.divider },
  atlasQuestion: { color: theme.color.textMuted, fontSize: 13, fontWeight: "700" },
  atlasBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 18, paddingVertical: 12, borderRadius: theme.radius.pill,
    backgroundColor: theme.color.brand,
  },
  atlasBtnText: { color: "#fff", fontWeight: "900", fontSize: 12, letterSpacing: 1.4 },
  disclaimer: { color: theme.color.textDim, fontSize: 11, textAlign: "center", marginTop: 8, paddingHorizontal: 20, lineHeight: 15 },
  // Sheet
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)" },
  sheetWrap: { position: "absolute", left: 0, right: 0, bottom: 0 },
  sheet: {
    backgroundColor: theme.color.surface, borderTopLeftRadius: 22, borderTopRightRadius: 22,
    padding: 18, paddingBottom: Platform.OS === "ios" ? 34 : 20, maxHeight: "88%",
  },
  grabber: { width: 40, height: 4, borderRadius: 2, backgroundColor: theme.color.border, alignSelf: "center", marginBottom: 10 },
  sheetTitle: { color: theme.color.text, fontSize: 18, fontWeight: "900" },
  sheetBrand: { color: theme.color.textMuted, fontSize: 12, marginTop: 2 },
  sheetKcal: { color: theme.color.brand, fontSize: 14, fontWeight: "800", marginTop: 8 },
  estimateBanner: {
    marginTop: 10, padding: 10, borderRadius: 10, flexDirection: "row",
    gap: 6, alignItems: "center", backgroundColor: "#3a2900",
  },
  estimateBannerText: { color: "#F59E0B", fontSize: 12, fontWeight: "700", flex: 1 },
  fieldLabel: { color: theme.color.textDim, fontSize: 11, fontWeight: "900", letterSpacing: 1.4, marginTop: 16 },
  servingRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 8 },
  stepBtn: {
    width: 40, height: 40, borderRadius: 20, backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border, alignItems: "center", justifyContent: "center",
  },
  servingInput: {
    width: 60, textAlign: "center", color: theme.color.text, fontWeight: "900", fontSize: 18,
    backgroundColor: theme.color.surface2, borderRadius: 10, paddingVertical: 8,
    borderWidth: 1, borderColor: theme.color.border,
  },
  servingUnit: { color: theme.color.textMuted, fontSize: 13, flex: 1 },
  mealsGrid: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 8 },
  mealChip: {
    paddingHorizontal: 10, paddingVertical: 6, borderRadius: theme.radius.pill,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  mealChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  mealChipText: { color: theme.color.text, fontSize: 11, fontWeight: "700" },
  macroRow: { flexDirection: "row", gap: 8, marginTop: 8 },
  macroBox: {
    flex: 1, backgroundColor: theme.color.surface2, borderRadius: 10,
    padding: 8, borderWidth: 1, borderColor: theme.color.border, alignItems: "center",
  },
  macroBoxLabel: { color: theme.color.textDim, fontSize: 11, fontWeight: "800", letterSpacing: 1 },
  macroBoxInput: { color: theme.color.text, fontSize: 16, fontWeight: "800", textAlign: "center", minWidth: 50 },
  primaryBtn: {
    marginTop: 18, backgroundColor: theme.color.brand, borderRadius: theme.radius.pill,
    paddingVertical: 14, alignItems: "center", justifyContent: "center",
    flexDirection: "row", gap: 6,
  },
  primaryBtnText: { color: "#fff", fontWeight: "900", letterSpacing: 1.2, fontSize: 13 },
});
