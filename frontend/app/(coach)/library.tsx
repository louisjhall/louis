import { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, TextInput, RefreshControl, ActivityIndicator } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { ExerciseVideoPlayer, preloadExerciseVideos } from "@/src/components/ExerciseVideoPlayer";

const CATS = ["push", "pull", "legs", "core", "mobility", "cardio"];

export default function Library() {
  const router = useRouter();
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [cat, setCat] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [name, setName] = useState("");
  const [nCat, setNCat] = useState(CATS[0]);
  const [equip, setEquip] = useState("bodyweight");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // Use unified exercise_content (v2). Fall back to legacy /exercises if v2 is unreachable.
      try {
        const r = await api<{ exercises: any[] }>("/exercise-content?limit=500");
        setItems((r.exercises || []).map((e) => ({
          id: e.id,
          name: e.exercise_name || e.name,
          category: (e.category || e.training_type || "strength").toLowerCase(),
          equipment: e.equipment_type || e.equipment || [],
          _v2: true,
        })));
      } catch {
        setItems(await api<any[]>("/exercises"));
      }
    } finally { setLoading(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const add = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      await api("/exercises", { method: "POST", body: { name: name.trim(), category: nCat, equipment: equip.split(",").map(x => x.trim()).filter(Boolean) } });
      setName(""); setShowAdd(false); await load();
    } finally { setSaving(false); }
  };

  const remove = async (id: string) => {
    await api(`/exercises/${id}`, { method: "DELETE" });
    load();
  };

  const filtered = cat ? items.filter((i) => i.category === cat) : items;

  useEffect(() => {
    const names = filtered.map((e: any) => e?.name).filter(Boolean).slice(0, 20);
    if (names.length) preloadExerciseVideos(names);
  }, [filtered]);

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Text style={styles.title}>EXERCISE LIBRARY</Text>
        <View style={{ flexDirection: "row", gap: 8 }}>
          <Pressable testID="lib-goto-content" onPress={() => router.push("/coach/exercise-content" as any)} style={styles.upgradeBtn}>
            <Ionicons name="sparkles" size={13} color="#fff" />
            <Text style={styles.upgradeBtnT}>V2</Text>
          </Pressable>
          <Pressable testID="lib-add-btn" onPress={() => setShowAdd((x) => !x)} style={styles.addBtn}>
            <Ionicons name={showAdd ? "close" : "add"} size={22} color="#fff" />
          </Pressable>
        </View>
      </View>

      <View style={styles.migratedBanner}>
        <Ionicons name="information-circle" size={13} color={theme.color.brand} />
        <Text style={styles.migratedBannerT}>{items.length} exercises · migrated to Unified Exercise Content</Text>
        <Pressable onPress={() => router.push("/coach/exercise-content" as any)}>
          <Text style={styles.migratedBannerLink}>OPEN &rsaquo;</Text>
        </Pressable>
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false}
        style={styles.chipsScroll} contentContainerStyle={styles.chipsRow}>
        <Pressable onPress={() => setCat(null)} style={[styles.chip, !cat && styles.chipActive]}><Text style={[styles.chipText, !cat && { color: "#fff" }]}>ALL</Text></Pressable>
        {CATS.map((c) => (
          <Pressable key={c} testID={`lib-filter-${c}`} onPress={() => setCat(c)} style={[styles.chip, cat === c && styles.chipActive]}>
            <Text style={[styles.chipText, cat === c && { color: "#fff" }]}>{c.toUpperCase()}</Text>
          </Pressable>
        ))}
      </ScrollView>

      <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 60 }} refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}>
        {showAdd && (
          <View style={styles.addCard}>
            <TextInput testID="lib-name-input" style={styles.input} value={name} onChangeText={setName} placeholder="Exercise name" placeholderTextColor={theme.color.textDim} />
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
              {CATS.map((c) => (
                <Pressable key={c} onPress={() => setNCat(c)} style={[styles.chip, nCat === c && styles.chipActive]}>
                  <Text style={[styles.chipText, nCat === c && { color: "#fff" }]}>{c.toUpperCase()}</Text>
                </Pressable>
              ))}
            </View>
            <TextInput testID="lib-equip-input" style={[styles.input, { marginTop: 8 }]} value={equip} onChangeText={setEquip} placeholder="dumbbell, band" placeholderTextColor={theme.color.textDim} />
            <Pressable testID="lib-submit" onPress={add} disabled={saving} style={[styles.cta, saving && { opacity: 0.6 }]}>
              {saving ? <ActivityIndicator color="#fff" /> : <Text style={styles.ctaText}>ADD EXERCISE</Text>}
            </Pressable>
          </View>
        )}

        {filtered.map((e) => (
          <View key={e.id} style={styles.row} testID={`lib-row-${e.id}`}>
            <View style={{ flex: 1 }}>
              <View style={{ flexDirection: "row", alignItems: "center" }}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.name}>{e.name}</Text>
                  <Text style={styles.meta}>{e.category?.toUpperCase()} · {(e.equipment || []).join(", ")}</Text>
                </View>
                <Pressable onPress={() => remove(e.id)} testID={`lib-remove-${e.id}`}><Ionicons name="trash" size={20} color={theme.color.textDim} /></Pressable>
              </View>
              <ExerciseVideoPlayer exerciseName={e.name} testIDPrefix={`lib-video-${e.id}`} compact />
            </View>
          </View>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  title: { color: theme.color.text, fontSize: 18, letterSpacing: 2, fontWeight: "900" },
  addBtn: { backgroundColor: theme.color.brand, width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center" },
  upgradeBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, height: 36, borderRadius: 8, backgroundColor: theme.color.brand },
  upgradeBtnT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1 },
  migratedBanner: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: theme.space.lg, paddingVertical: 8, backgroundColor: theme.color.brandTint, borderBottomWidth: 1, borderBottomColor: theme.color.brand },
  migratedBannerT: { color: theme.color.text, fontSize: 11, flex: 1, fontWeight: "700" },
  migratedBannerLink: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1 },
  chipsScroll: { flexGrow: 0, maxHeight: 56 },
  chipsRow: { paddingHorizontal: theme.space.lg, paddingVertical: theme.space.md, gap: 8, alignItems: "center" },
  chip: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: theme.radius.pill, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, flexShrink: 0, alignSelf: "center" },
  chipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipText: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700", letterSpacing: 1 },
  addCard: { padding: theme.space.md, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, marginBottom: theme.space.md },
  input: { backgroundColor: theme.color.surface3, borderRadius: theme.radius.md, color: theme.color.text, padding: 12, borderWidth: 1, borderColor: theme.color.border },
  cta: { backgroundColor: theme.color.brand, paddingVertical: 14, borderRadius: theme.radius.md, alignItems: "center", marginTop: theme.space.md },
  ctaText: { color: "#fff", fontWeight: "800", letterSpacing: 2 },
  row: { padding: theme.space.md, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, marginBottom: theme.space.sm, borderWidth: 1, borderColor: theme.color.border },
  name: { color: theme.color.text, fontSize: 15, fontWeight: "700" },
  meta: { color: theme.color.textDim, fontSize: 11, marginTop: 2, letterSpacing: 1 },
});
