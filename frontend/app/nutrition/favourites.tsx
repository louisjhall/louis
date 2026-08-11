/**
 * Nutrition · Favourites list — tap to instant-log.
 */
import React, { useCallback, useState } from "react";
import { ActivityIndicator, FlatList, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useFocusEffect } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { confirm, toast } from "@/src/lib/ux";

type Fav = { id: string; name: string; calories: number; protein_g: number; carbs_g: number; fats_g: number; meal_type: string; portion?: string; };

export default function Favs() {
  const router = useRouter();
  const [favs, setFavs] = useState<Fav[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { const r = await api<{ favourites: Fav[] }>("/nutrition/favourites"); setFavs(r.favourites); }
    catch (e: any) { toast(e?.message || "Failed", "error"); }
  }, []);
  useFocusEffect(useCallback(() => { setLoading(true); load().finally(() => setLoading(false)); }, [load]));

  const logIt = async (f: Fav) => {
    setBusyId(f.id);
    try {
      await api("/nutrition/logs", { method: "POST", body: {
        food_name: f.name, meal_type: f.meal_type, calories: f.calories,
        protein_g: f.protein_g, carbs_g: f.carbs_g, fats_g: f.fats_g,
        portion: f.portion, source: "favourite",
      } });
      toast(`Logged · ${f.name}`, "success");
    } catch (e: any) { toast(e?.message || "Failed", "error"); }
    finally { setBusyId(null); }
  };

  const remove = async (f: Fav) => {
    const ok = await confirm({ title: "Remove favourite?", message: f.name, destructive: true, confirmLabel: "REMOVE" });
    if (!ok) return;
    try { await api(`/nutrition/favourites/${f.id}`, { method: "DELETE" }); setFavs((prev) => prev.filter((x) => x.id !== f.id)); }
    catch (e: any) { toast(e?.message || "Failed", "error"); }
  };

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="chevron-back" size={24} color={theme.color.text} />
        </Pressable>
        <Text style={styles.headerT}>FAVOURITES</Text>
        <View style={{ width: 24 }} />
      </View>

      {loading ? <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View> :
        favs.length === 0 ? (
          <View style={styles.center}>
            <Ionicons name="heart-outline" size={40} color={theme.color.textDim} />
            <Text style={styles.empty}>No favourites yet.\nWhen logging a meal, tick “Save as favourite”.</Text>
          </View>
        ) : (
          <FlatList data={favs} keyExtractor={(f) => f.id}
            contentContainerStyle={{ padding: 16, gap: 8 }}
            renderItem={({ item }) => (
              <View style={styles.card}>
                <Pressable style={{ flex: 1 }} onPress={() => logIt(item)}>
                  <Text style={styles.cardName}>{item.name}</Text>
                  <Text style={styles.cardMeta}>{item.meal_type.replace(/_/g, " ").toUpperCase()}{item.portion ? " · " + item.portion : ""}</Text>
                  <Text style={styles.cardMacros}>{item.calories} kcal · {Math.round(item.protein_g)}g P · {Math.round(item.carbs_g)}g C · {Math.round(item.fats_g)}g F</Text>
                </Pressable>
                <Pressable onPress={() => logIt(item)} disabled={busyId === item.id} style={styles.logBtn}>
                  {busyId === item.id ? <ActivityIndicator color="#fff" size="small" /> : (<>
                    <Ionicons name="add" size={14} color="#fff" />
                    <Text style={styles.logBtnT}>LOG</Text>
                  </>)}
                </Pressable>
                <Pressable onPress={() => remove(item)} hitSlop={10} style={styles.trash}>
                  <Ionicons name="trash-outline" size={14} color="#c94a4a" />
                </Pressable>
              </View>
            )} />
        )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 20, gap: 12 },
  empty: { color: theme.color.textMuted, textAlign: "center", fontSize: 13, fontStyle: "italic" },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 14, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  headerT: { color: theme.color.text, fontSize: 14, letterSpacing: 3, fontWeight: "900", fontFamily: theme.font.display },
  card: { flexDirection: "row", alignItems: "center", gap: 8, padding: 12, borderRadius: 10, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  cardName: { color: theme.color.text, fontSize: 14, fontWeight: "800", fontFamily: theme.font.textSemi },
  cardMeta: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1, marginTop: 2 },
  cardMacros: { color: theme.color.textDim, fontSize: 11, marginTop: 3 },
  logBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 8, borderRadius: 6, backgroundColor: theme.color.brand },
  logBtnT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1 },
  trash: { padding: 6 },
});
