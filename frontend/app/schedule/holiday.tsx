import { useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator, KeyboardAvoidingView, Platform } from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

const TYPES = ["business_trip", "beach", "city", "cruise", "adventure", "ski", "family", "staycation"];
const GOALS = ["maintain", "improve", "relax", "normal", "break"];
const EQUIP = ["hotel gym", "commercial gym", "pool", "running", "bike hire", "none"];

export default function Holiday() {
  const router = useRouter();
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [htype, setHtype] = useState(TYPES[1]);
  const [goal, setGoal] = useState(GOALS[0]);
  const [equipment, setEquipment] = useState<string[]>(["running"]);
  const [saving, setSaving] = useState(false);

  const toggle = (v: string) => setEquipment((p) => p.includes(v) ? p.filter((x) => x !== v) : [...p, v]);

  const submit = async (active: boolean) => {
    if (active && (!start || !end)) return;
    setSaving(true);
    try {
      await api("/schedule/holiday", {
        method: "POST",
        body: { active, start_date: start || null, end_date: end || null, holiday_type: htype, goal, equipment },
      });
      if (active && start) {
        const days: string[] = [];
        const s = new Date(start); const e = new Date(end || start);
        const cur = new Date(s);
        while (cur <= e) { days.push(cur.toISOString().slice(0, 10)); cur.setDate(cur.getDate() + 1); }
        api("/schedule/smart-replan", { method: "POST", body: { reason: `Holiday: ${htype}, goal ${goal}`, dates: days, scope: "affected" } }).catch(() => {});
      }
      router.back();
    } finally { setSaving(false); }
  };

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()}><Ionicons name="chevron-back" size={26} color={theme.color.text} /></Pressable>
        <Text style={styles.title}>HOLIDAY MODE</Text>
        <View style={{ width: 26 }} />
      </View>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 140 }}>
          <View style={{ flexDirection: "row", gap: 8 }}>
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>START (YYYY-MM-DD)</Text>
              <TextInput testID="hol-start" style={styles.input} value={start} onChangeText={setStart} placeholder="2026-03-01" placeholderTextColor={theme.color.textDim} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>END</Text>
              <TextInput testID="hol-end" style={styles.input} value={end} onChangeText={setEnd} placeholder="2026-03-14" placeholderTextColor={theme.color.textDim} />
            </View>
          </View>
          <Text style={styles.label}>HOLIDAY TYPE</Text>
          <View style={styles.chipsWrap}>
            {TYPES.map((t) => <Pressable key={t} testID={`hol-type-${t}`} onPress={() => setHtype(t)} style={[styles.chip, htype === t && styles.chipActive]}><Text style={[styles.chipText, htype === t && { color: "#fff" }]}>{t.replace("_", " ")}</Text></Pressable>)}
          </View>
          <Text style={styles.label}>GOAL</Text>
          <View style={styles.chipsWrap}>
            {GOALS.map((g) => <Pressable key={g} testID={`hol-goal-${g}`} onPress={() => setGoal(g)} style={[styles.chip, goal === g && styles.chipActive]}><Text style={[styles.chipText, goal === g && { color: "#fff" }]}>{g}</Text></Pressable>)}
          </View>
          <Text style={styles.label}>EQUIPMENT AVAILABLE</Text>
          <View style={styles.chipsWrap}>
            {EQUIP.map((e) => <Pressable key={e} testID={`hol-eq-${e}`} onPress={() => toggle(e)} style={[styles.chip, equipment.includes(e) && styles.chipActive]}><Text style={[styles.chipText, equipment.includes(e) && { color: "#fff" }]}>{e}</Text></Pressable>)}
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
      <View style={styles.sticky}>
        <Pressable testID="hol-off" onPress={() => submit(false)} style={styles.ctaSec}><Text style={styles.ctaSecText}>END HOLIDAY</Text></Pressable>
        <Pressable testID="hol-on" onPress={() => submit(true)} disabled={saving} style={[styles.cta, saving && { opacity: 0.6 }]}>
          {saving ? <ActivityIndicator color="#fff" /> : <Text style={styles.ctaText}>ACTIVATE HOLIDAY MODE</Text>}
        </Pressable>
      </View>
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  title: { color: theme.color.text, fontSize: 14, letterSpacing: 2, fontWeight: "900" },
  label: { color: theme.color.textMuted, letterSpacing: 2, fontSize: 11, fontWeight: "800", marginTop: theme.space.md, marginBottom: theme.space.sm },
  input: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, color: theme.color.onRed, padding: theme.space.md, borderWidth: 1, borderColor: theme.color.border },
  chipsWrap: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: theme.radius.pill, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, flexShrink: 0 },
  chipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipText: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700" },
  sticky: { flexDirection: "row", gap: 8, padding: theme.space.lg, borderTopWidth: 1, borderTopColor: theme.color.border, backgroundColor: theme.color.surface },
  cta: { flex: 2, backgroundColor: theme.color.brand, paddingVertical: 14, borderRadius: theme.radius.md, alignItems: "center" },
  ctaText: { color: "#fff", fontWeight: "800", letterSpacing: 1.5, fontSize: 12 },
  ctaSec: { flex: 1, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.green, paddingVertical: 14, borderRadius: theme.radius.md, alignItems: "center" },
  ctaSecText: { color: theme.color.green, fontWeight: "800", letterSpacing: 1.5, fontSize: 11 },
});
