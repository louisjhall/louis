import { useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator, KeyboardAvoidingView, Platform } from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

const ILLNESS = ["cold", "flu", "fever", "injury", "COVID", "food poisoning", "other"];

export default function Sickness() {
  const router = useRouter();
  const [illness, setIllness] = useState(ILLNESS[0]);
  const [severity, setSeverity] = useState(4);
  const [doctorRest, setDoctorRest] = useState(false);
  const [saving, setSaving] = useState(false);

  const submit = async (active: boolean) => {
    setSaving(true);
    try {
      await api("/schedule/sickness", {
        method: "POST",
        body: { active, illness, severity, doctor_advised_rest: doctorRest, started_at: new Date().toISOString() },
      });
      if (active) {
        // Trigger replan for next 7 days
        const days: string[] = [];
        for (let i = 0; i < 7; i++) {
          const d = new Date(); d.setDate(d.getDate() + i);
          days.push(d.toISOString().slice(0, 10));
        }
        api("/schedule/smart-replan", { method: "POST", body: { reason: `Sickness reported (${illness}, severity ${severity})`, dates: days, scope: "affected" } }).catch(() => {});
      }
      router.back();
    } finally { setSaving(false); }
  };

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()}><Ionicons name="chevron-back" size={26} color={theme.color.text} /></Pressable>
        <Text style={styles.title}>SICKNESS MODE</Text>
        <View style={{ width: 26 }} />
      </View>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 140 }}>
          <Text style={styles.sub}>Tell us what's up — we'll pause hard training and gradually rebuild.</Text>
          <Text style={styles.label}>ILLNESS</Text>
          <View style={styles.chipsWrap}>
            {ILLNESS.map((i) => (
              <Pressable key={i} testID={`ill-${i}`} onPress={() => setIllness(i)} style={[styles.chip, illness === i && styles.chipActive]}>
                <Text style={[styles.chipText, illness === i && { color: "#fff" }]}>{i}</Text>
              </Pressable>
            ))}
          </View>
          <Text style={styles.label}>SEVERITY  <Text style={styles.bigVal}>{severity}</Text></Text>
          <View style={styles.dotsRow}>
            {Array.from({ length: 10 }).map((_, i) => (
              <Pressable key={i} testID={`sev-${i + 1}`} onPress={() => setSeverity(i + 1)} style={[styles.dot, { backgroundColor: i < severity ? theme.color.brand : theme.color.surface3 }]} />
            ))}
          </View>
          <Pressable testID="doctor-toggle" onPress={() => setDoctorRest(!doctorRest)} style={[styles.chip, doctorRest && styles.chipActive, { marginTop: theme.space.md, alignSelf: "flex-start" }]}>
            <Text style={[styles.chipText, doctorRest && { color: "#fff" }]}>Doctor advised rest</Text>
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>
      <View style={styles.sticky}>
        <Pressable testID="sick-off" onPress={() => submit(false)} style={[styles.ctaSec]}>
          <Text style={styles.ctaSecText}>MARK RECOVERED</Text>
        </Pressable>
        <Pressable testID="sick-on" onPress={() => submit(true)} disabled={saving} style={[styles.cta, saving && { opacity: 0.6 }]}>
          {saving ? <ActivityIndicator color="#fff" /> : <Text style={styles.ctaText}>ACTIVATE SICKNESS MODE</Text>}
        </Pressable>
      </View>
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  title: { color: theme.color.text, fontSize: 14, letterSpacing: 2, fontWeight: "900" },
  sub: { color: theme.color.textMuted, fontSize: 12, marginBottom: theme.space.md },
  label: { color: theme.color.textMuted, letterSpacing: 2, fontSize: 11, fontWeight: "800", marginTop: theme.space.lg, marginBottom: theme.space.sm },
  bigVal: { color: theme.color.brand, fontSize: 18, fontWeight: "900" },
  chipsWrap: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: theme.radius.pill, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, flexShrink: 0 },
  chipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipText: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700" },
  dotsRow: { flexDirection: "row", gap: 4 },
  dot: { flex: 1, height: 12, borderRadius: 3 },
  sticky: { flexDirection: "row", gap: 8, padding: theme.space.lg, borderTopWidth: 1, borderTopColor: theme.color.border, backgroundColor: theme.color.surface },
  cta: { flex: 2, backgroundColor: theme.color.brand, paddingVertical: 14, borderRadius: theme.radius.md, alignItems: "center" },
  ctaText: { color: "#fff", fontWeight: "800", letterSpacing: 1.5, fontSize: 12 },
  ctaSec: { flex: 1, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.green, paddingVertical: 14, borderRadius: theme.radius.md, alignItems: "center" },
  ctaSecText: { color: theme.color.green, fontWeight: "800", letterSpacing: 1.5, fontSize: 11 },
});
