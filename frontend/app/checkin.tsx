import { useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator, KeyboardAvoidingView, Platform } from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

export default function CheckIn() {
  const router = useRouter();
  const [energy, setEnergy] = useState(7);
  const [sleep, setSleep] = useState(7);
  const [soreness, setSoreness] = useState(3);
  const [stress, setStress] = useState(4);
  const [weight, setWeight] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState(false);

  const submit = async () => {
    setSaving(true);
    try {
      await api("/checkins", {
        method: "POST",
        body: {
          week_start: new Date().toISOString().slice(0, 10),
          energy, sleep, soreness, stress,
          weight_kg: weight ? parseFloat(weight) : null,
          notes: notes || null,
        },
      });
      setDone(true);
      setTimeout(() => router.back(), 900);
    } finally { setSaving(false); }
  };

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()}><Ionicons name="chevron-back" size={26} color={theme.color.text} /></Pressable>
        <Text style={styles.title}>WEEKLY CHECK-IN</Text>
        <View style={{ width: 26 }} />
      </View>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 120 }}>
          <Scale label="ENERGY" value={energy} onChange={setEnergy} testID="scale-energy" />
          <Scale label="SLEEP" value={sleep} onChange={setSleep} testID="scale-sleep" />
          <Scale label="SORENESS" value={soreness} onChange={setSoreness} testID="scale-soreness" />
          <Scale label="STRESS" value={stress} onChange={setStress} testID="scale-stress" />
          <Text style={styles.label}>WEIGHT (kg)</Text>
          <TextInput testID="checkin-weight" style={styles.input} value={weight} onChangeText={setWeight} keyboardType="numeric" placeholder="82" placeholderTextColor={theme.color.textDim} />
          <Text style={styles.label}>NOTES</Text>
          <TextInput testID="checkin-notes" style={[styles.input, { minHeight: 90 }]} multiline value={notes} onChangeText={setNotes} placeholder="How did the week feel?" placeholderTextColor={theme.color.textDim} />
        </ScrollView>
        <View style={styles.sticky}>
          <Pressable testID="submit-checkin" onPress={submit} disabled={saving || done} style={[styles.cta, (saving || done) && { opacity: 0.7 }, done && { backgroundColor: theme.color.green }]}>
            {saving ? <ActivityIndicator color="#fff" /> : <Text style={styles.ctaText}>{done ? "SAVED ✓" : "SUBMIT"}</Text>}
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function Scale({ label, value, onChange, testID }: any) {
  return (
    <View style={styles.scaleWrap}>
      <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
        <Text style={styles.label}>{label}</Text>
        <Text style={styles.valBig}>{value}</Text>
      </View>
      <View style={styles.dotsRow}>
        {Array.from({ length: 10 }).map((_, i) => (
          <Pressable key={i} testID={`${testID}-${i + 1}`} onPress={() => onChange(i + 1)} style={[styles.dotCell, { backgroundColor: i < value ? theme.color.brand : theme.color.surface3 }]} />
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  title: { color: theme.color.text, fontSize: 14, letterSpacing: 2, fontWeight: "900" },
  scaleWrap: { marginTop: theme.space.md },
  label: { color: theme.color.textMuted, letterSpacing: 2, fontSize: 11, fontWeight: "800" },
  valBig: { color: theme.color.brand, fontSize: 20, fontWeight: "900" },
  dotsRow: { flexDirection: "row", gap: 4, marginTop: 8 },
  dotCell: { flex: 1, height: 10, borderRadius: 3 },
  input: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, color: theme.color.text, padding: theme.space.md, borderWidth: 1, borderColor: theme.color.border, marginTop: 6 },
  sticky: { padding: theme.space.lg, borderTopWidth: 1, borderTopColor: theme.color.border, backgroundColor: theme.color.surface },
  cta: { backgroundColor: theme.color.brand, paddingVertical: 16, borderRadius: theme.radius.md, alignItems: "center" },
  ctaText: { color: "#fff", fontWeight: "800", letterSpacing: 2, fontSize: 13 },
});
