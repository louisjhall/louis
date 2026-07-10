/**
 * Nutrition · Targets (client read-only + soft self-edit).
 */
import React, { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useFocusEffect } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast } from "@/src/lib/ux";

type T = {
  target: {
    calories?: number; protein_g?: number; carbs_g?: number; fats_g?: number;
    hydration_ml?: number; goal?: string; target_type?: string; is_default?: boolean;
    notes?: string;
  };
  guardrails: { min_calories: number; min_protein_g: number; max_calories: number; max_protein_g: number; min_hydration_ml: number };
};

export default function Targets() {
  const router = useRouter();
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try { setData(await api<T>("/nutrition/targets/mine")); }
    catch (e: any) { toast(e?.message || "Load failed", "error"); }
  }, []);
  useFocusEffect(useCallback(() => { setLoading(true); load().finally(() => setLoading(false)); }, [load]));

  if (loading || !data) {
    return <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>;
  }

  const t = data.target;

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="chevron-back" size={24} color={theme.color.text} />
        </Pressable>
        <Text style={styles.headerT}>MY TARGETS</Text>
        <View style={{ width: 24 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: 16, gap: 12 }}>
        <View style={styles.card}>
          <View style={styles.badgeRow}>
            <View style={[styles.badge, t.is_default ? styles.badgeDefault : styles.badgeCoach]}>
              <Ionicons name={t.is_default ? "sparkles" : "person"} size={11} color="#fff" />
              <Text style={styles.badgeT}>{t.is_default ? "ATLAS DEFAULT" : "COACH SET"}</Text>
            </View>
          </View>
          <Text style={styles.goal}>{goalLabel(t.goal)}</Text>
          {t.notes ? <Text style={styles.notes}>{t.notes}</Text> : null}
        </View>

        <Row label="CALORIES" value={`${t.calories || 0} kcal`} icon="flame" />
        <Row label="PROTEIN" value={`${t.protein_g || 0} g`} icon="barbell" />
        <Row label="CARBS" value={`${t.carbs_g || 0} g`} icon="leaf" />
        <Row label="FATS" value={`${t.fats_g || 0} g`} icon="water-outline" />
        <Row label="HYDRATION" value={`${t.hydration_ml || 0} ml`} icon="water" />

        <Text style={styles.disclaimer}>
          These are coaching estimates. Louis can adjust them via the coach dashboard
          based on your training load and roster. Personalised targets update as you
          log meals consistently.
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}

function Row({ label, value, icon }: { label: string; value: string; icon: any }) {
  return (
    <View style={styles.row}>
      <Ionicons name={icon} size={16} color={theme.color.brand} />
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={styles.rowVal}>{value}</Text>
    </View>
  );
}

function goalLabel(g?: string) {
  return ({ fat_loss: "Fat loss", muscle_gain: "Muscle gain", endurance: "Endurance", general_health: "General health", recovery: "Recovery" } as any)[g || ""] || "General health";
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 14, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  headerT: { color: theme.color.text, fontSize: 14, letterSpacing: 3, fontWeight: "900", fontFamily: theme.font.display },
  card: { padding: 14, borderRadius: 12, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, gap: 8 },
  badgeRow: { flexDirection: "row" },
  badge: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6 },
  badgeDefault: { backgroundColor: theme.color.textDim },
  badgeCoach: { backgroundColor: theme.color.brand },
  badgeT: { color: "#fff", fontSize: 9, letterSpacing: 1, fontWeight: "900" },
  goal: { color: theme.color.text, fontSize: 18, fontWeight: "900", fontFamily: theme.font.display, letterSpacing: 0.5 },
  notes: { color: theme.color.textMuted, fontSize: 12, fontFamily: theme.font.text },
  row: { flexDirection: "row", alignItems: "center", gap: 12, padding: 14, borderRadius: 10, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  rowLabel: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1.5, fontWeight: "900", flex: 1, fontFamily: theme.font.textSemi },
  rowVal: { color: theme.color.text, fontSize: 15, fontWeight: "900", fontFamily: theme.font.display },
  disclaimer: { color: theme.color.textDim, fontSize: 11, textAlign: "center", fontStyle: "italic", lineHeight: 17, marginTop: 12 },
});
