import { useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator, KeyboardAvoidingView, Platform } from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Q = { id: string; label: string; type: "scale" | "text"; scale_max?: number; placeholder?: string };

export default function CheckIn() {
  const router = useRouter();
  const [questions, setQuestions] = useState<Q[]>([]);
  const [answers, setAnswers] = useState<Record<string, string | number>>({});
  const [energy, setEnergy] = useState(7);
  const [sleep, setSleep] = useState(7);
  const [soreness, setSoreness] = useState(3);
  const [stress, setStress] = useState(4);
  const [weight, setWeight] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [done, setDone] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const r = await api<{ questions: Q[] }>("/checkins/questions", { method: "POST", body: {} });
        setQuestions(r.questions || []);
      } finally { setLoading(false); }
    })();
  }, []);

  const submit = async () => {
    setSaving(true);
    try {
      await api("/checkins/adaptive", {
        method: "POST",
        body: {
          week_start: new Date().toISOString().slice(0, 10),
          answers, energy, sleep, soreness, stress,
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
        <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 140 }} keyboardShouldPersistTaps="handled">
          <Text style={styles.sub}>Personalised to your goal, roster & current phase.</Text>

          <Scale label="ENERGY" value={energy} onChange={setEnergy} testID="scale-energy" />
          <Scale label="SLEEP" value={sleep} onChange={setSleep} testID="scale-sleep" />
          <Scale label="SORENESS" value={soreness} onChange={setSoreness} testID="scale-soreness" />
          <Scale label="STRESS" value={stress} onChange={setStress} testID="scale-stress" />

          {loading ? (
            <ActivityIndicator color={theme.color.brand} style={{ marginTop: 20 }} />
          ) : (
            questions.map((q) => (
              <View key={q.id} style={styles.qCard} testID={`q-${q.id}`}>
                <Text style={styles.qLabel}>{q.label}</Text>
                {q.type === "scale" ? (
                  <ScaleInline
                    testID={`q-${q.id}-scale`}
                    max={q.scale_max || 10}
                    value={Number(answers[q.id] || 0)}
                    onChange={(v) => setAnswers((a) => ({ ...a, [q.id]: v }))}
                  />
                ) : (
                  <TextInput
                    testID={`q-${q.id}-input`}
                    style={styles.input}
                    value={String(answers[q.id] || "")}
                    onChangeText={(t) => setAnswers((a) => ({ ...a, [q.id]: t }))}
                    placeholder={q.placeholder}
                    placeholderTextColor={theme.color.textDim}
                    multiline
                  />
                )}
              </View>
            ))
          )}

          <Text style={styles.label}>WEIGHT (kg)</Text>
          <TextInput testID="checkin-weight" style={styles.input} value={weight} onChangeText={setWeight} keyboardType="numeric" placeholder="82" placeholderTextColor={theme.color.textDim} />
          <Text style={styles.label}>NOTES</Text>
          <TextInput testID="checkin-notes" style={[styles.input, { minHeight: 80 }]} multiline value={notes} onChangeText={setNotes} placeholder="Anything else to share…" placeholderTextColor={theme.color.textDim} />
        </ScrollView>
        <View style={styles.sticky}>
          <Pressable testID="submit-checkin" onPress={submit} disabled={saving || done} style={[styles.cta, (saving || done) && { opacity: 0.7 }, done && { backgroundColor: theme.color.green }]}>
            {saving ? <ActivityIndicator color="#fff" /> : <Text style={styles.ctaText}>{done ? "SAVED ✓" : "SUBMIT · COACH SEES INSTANTLY"}</Text>}
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
      <ScaleInline max={10} value={value} onChange={onChange} testID={testID} />
    </View>
  );
}
function ScaleInline({ max, value, onChange, testID }: any) {
  return (
    <View style={styles.dotsRow}>
      {Array.from({ length: max }).map((_, i) => (
        <Pressable key={i} testID={`${testID}-${i + 1}`} onPress={() => onChange(i + 1)} style={[styles.dotCell, { backgroundColor: i < value ? theme.color.brand : theme.color.surface3 }]} />
      ))}
    </View>
  );
}
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  title: { color: theme.color.text, fontSize: 14, letterSpacing: 2, fontWeight: "900" },
  sub: { color: theme.color.textMuted, marginBottom: theme.space.md, fontSize: 12 },
  scaleWrap: { marginTop: theme.space.md },
  label: { color: theme.color.textMuted, letterSpacing: 2, fontSize: 11, fontWeight: "800" },
  valBig: { color: theme.color.brand, fontSize: 20, fontWeight: "900" },
  dotsRow: { flexDirection: "row", gap: 4, marginTop: 8 },
  dotCell: { flex: 1, height: 10, borderRadius: 3 },
  input: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, color: theme.color.text, padding: theme.space.md, borderWidth: 1, borderColor: theme.color.border, marginTop: 6 },
  qCard: { marginTop: theme.space.md, padding: theme.space.md, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, borderLeftWidth: 3, borderLeftColor: theme.color.brand },
  qLabel: { color: theme.color.text, fontSize: 13, fontWeight: "700" },
  sticky: { padding: theme.space.lg, borderTopWidth: 1, borderTopColor: theme.color.border, backgroundColor: theme.color.surface },
  cta: { backgroundColor: theme.color.brand, paddingVertical: 16, borderRadius: theme.radius.md, alignItems: "center" },
  ctaText: { color: "#fff", fontWeight: "800", letterSpacing: 2, fontSize: 13 },
});
