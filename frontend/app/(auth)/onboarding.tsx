import { useState } from "react";
import {
  View, Text, TextInput, Pressable, StyleSheet, ScrollView,
  KeyboardAvoidingView, Platform, ActivityIndicator,
} from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { api } from "@/src/lib/api";
import { useAuth } from "@/src/lib/auth";
import { theme } from "@/src/lib/theme";

const EQUIP_OPTS = ["bodyweight", "dumbbell", "band", "kettlebell", "hotel-gym"];
const LEVEL_OPTS = ["beginner", "intermediate", "advanced"];
const POS_OPTS = ["Pilot", "Cabin Crew", "Ground Ops"];

export default function Onboarding() {
  const router = useRouter();
  const { refresh } = useAuth();
  const [airline, setAirline] = useState("");
  const [position, setPosition] = useState(POS_OPTS[0]);
  const [level, setLevel] = useState(LEVEL_OPTS[1]);
  const [days, setDays] = useState("4");
  const [goals, setGoals] = useState("");
  const [equipment, setEquipment] = useState<string[]>(["bodyweight", "dumbbell"]);
  const [weight, setWeight] = useState("");
  const [height, setHeight] = useState("");
  const [cal, setCal] = useState("2400");
  const [pro, setPro] = useState("160");
  const [loading, setLoading] = useState(false);

  const toggle = (v: string) =>
    setEquipment((prev) => (prev.includes(v) ? prev.filter((x) => x !== v) : [...prev, v]));

  const submit = async () => {
    setLoading(true);
    try {
      await api("/auth/onboarding", {
        method: "POST",
        body: {
          airline: airline || null,
          position,
          experience_level: level,
          training_days_per_week: parseInt(days) || 4,
          goals: goals || null,
          equipment,
          weight_kg: weight ? parseFloat(weight) : null,
          height_cm: height ? parseFloat(height) : null,
          calorie_target: parseInt(cal) || 2200,
          protein_target: parseInt(pro) || 150,
        },
      });
      await refresh();
      router.replace("/(client)/home");
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.root}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 120 }}>
          <Text style={styles.title}>PROFILE SETUP</Text>
          <Text style={styles.sub}>Tell your coach how you fly & train</Text>

          <Text style={styles.label}>AIRLINE</Text>
          <TextInput testID="onboard-airline" style={styles.input} value={airline} onChangeText={setAirline} placeholder="e.g. Skyline Air" placeholderTextColor={theme.color.textDim} />

          <Text style={styles.label}>POSITION</Text>
          <ChipRow options={POS_OPTS} value={position} onChange={setPosition} testPrefix="onboard-position" />

          <Text style={styles.label}>EXPERIENCE</Text>
          <ChipRow options={LEVEL_OPTS} value={level} onChange={setLevel} testPrefix="onboard-level" />

          <Text style={styles.label}>TRAINING DAYS / WEEK</Text>
          <TextInput testID="onboard-days" style={styles.input} value={days} onChangeText={setDays} keyboardType="number-pad" />

          <Text style={styles.label}>EQUIPMENT</Text>
          <View style={styles.chipsRow}>
            {EQUIP_OPTS.map((e) => (
              <Pressable
                key={e}
                testID={`onboard-equip-${e}`}
                onPress={() => toggle(e)}
                style={[styles.chip, equipment.includes(e) && styles.chipActive]}
              >
                <Text style={[styles.chipText, equipment.includes(e) && { color: "#fff" }]}>{e}</Text>
              </Pressable>
            ))}
          </View>

          <Text style={styles.label}>GOALS</Text>
          <TextInput testID="onboard-goals" style={[styles.input, { minHeight: 80 }]} multiline value={goals} onChangeText={setGoals} placeholder="Stay strong on rotations, lose 4kg" placeholderTextColor={theme.color.textDim} />

          <View style={styles.row2}>
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>HEIGHT (cm)</Text>
              <TextInput testID="onboard-height" style={styles.input} value={height} onChangeText={setHeight} keyboardType="numeric" placeholder="180" placeholderTextColor={theme.color.textDim} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>WEIGHT (kg)</Text>
              <TextInput testID="onboard-weight" style={styles.input} value={weight} onChangeText={setWeight} keyboardType="numeric" placeholder="82" placeholderTextColor={theme.color.textDim} />
            </View>
          </View>

          <View style={styles.row2}>
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>CALORIE TARGET</Text>
              <TextInput testID="onboard-cal" style={styles.input} value={cal} onChangeText={setCal} keyboardType="number-pad" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>PROTEIN TARGET (g)</Text>
              <TextInput testID="onboard-pro" style={styles.input} value={pro} onChangeText={setPro} keyboardType="number-pad" />
            </View>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>

      <View style={styles.stickyBar}>
        <Pressable testID="onboard-submit" onPress={submit} disabled={loading} style={[styles.cta, loading && { opacity: 0.6 }]}>
          {loading ? <ActivityIndicator color="#fff" /> : <Text style={styles.ctaText}>SAVE & CONTINUE</Text>}
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

function ChipRow({ options, value, onChange, testPrefix }: { options: string[]; value: string; onChange: (v: string) => void; testPrefix: string }) {
  return (
    <View style={styles.chipsRow}>
      {options.map((o) => (
        <Pressable key={o} testID={`${testPrefix}-${o}`} onPress={() => onChange(o)} style={[styles.chip, value === o && styles.chipActive]}>
          <Text style={[styles.chipText, value === o && { color: "#fff" }]}>{o}</Text>
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  title: { color: theme.color.text, fontSize: 26, fontWeight: "900", letterSpacing: 2 },
  sub: { color: theme.color.textMuted, marginTop: 4, marginBottom: theme.space.md },
  label: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1.5, marginTop: theme.space.md, marginBottom: theme.space.xs, fontWeight: "700" },
  input: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, color: theme.color.text, paddingHorizontal: theme.space.md, paddingVertical: 14, borderWidth: 1, borderColor: theme.color.border, fontSize: 15 },
  chipsRow: { flexDirection: "row", flexWrap: "wrap", gap: theme.space.sm },
  chip: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: theme.radius.pill, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  chipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipText: { color: theme.color.textMuted, fontSize: 12, fontWeight: "700" },
  row2: { flexDirection: "row", gap: theme.space.md },
  stickyBar: { position: "absolute", bottom: 0, left: 0, right: 0, padding: theme.space.lg, backgroundColor: theme.color.surface, borderTopWidth: 1, borderTopColor: theme.color.border },
  cta: { backgroundColor: theme.color.brand, paddingVertical: 16, borderRadius: theme.radius.md, alignItems: "center" },
  ctaText: { color: "#fff", fontWeight: "800", letterSpacing: 2, fontSize: 14 },
});
