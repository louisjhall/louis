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

const EQUIP = [
  "no equipment", "yoga mat", "resistance bands", "pull-up bar", "dumbbells",
  "adjustable dumbbells", "kettlebells", "barbell", "squat rack", "bench",
  "cable machine", "treadmill", "bike/turbo trainer", "rowing machine",
  "assault bike", "skipping rope", "medicine ball", "TRX/suspension trainer",
  "foam roller", "mobility tools",
];
const CARDIO = ["treadmill", "bike/turbo trainer", "rowing machine", "assault bike"];
const LOC_OPTS = ["home gym", "commercial gym", "garage gym", "living room", "outdoors"];
const LEVEL = ["beginner", "intermediate", "advanced"];
const POS = ["Pilot", "Cabin Crew", "Ground Ops"];
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]; void DAYS;

// Aviation context — powers roster-aware coaching so the plan adapts
// to your actual flying pattern. Keys mirror `feature_programme_quality`.
const ROUTE_OPTS: { key: string; label: string }[] = [
  { key: "long_haul",  label: "Long haul" },
  { key: "short_haul", label: "Short haul" },
  { key: "mixed",      label: "Mixed" },
  { key: "charter",    label: "Charter" },
  { key: "cargo",      label: "Cargo" },
];

// Structured main-goal picker so the coaching system programmes accurately
// instead of defaulting to "general fitness". Keys MUST match GOAL_MATRIX
// in /app/backend/feature_programme_quality.py.
const GOAL_OPTS: { key: string; label: string }[] = [
  { key: "lose_fat",              label: "Lose body fat" },
  { key: "build_muscle",          label: "Build strength / muscle" },
  { key: "general_fitness",       label: "General fitness" },
  { key: "health_markers",        label: "Health / medical" },
  { key: "event",                 label: "Event training" },
  { key: "aviation_consistency",  label: "Aviation consistency" },
  { key: "improve_energy",        label: "Improve energy" },
  { key: "return_to_training",    label: "Return to training" },
];

export default function Onboarding() {
  const { user, refresh } = useAuth();
  const router = useRouter();
  const p = user?.profile || {};
  const [airline, setAirline] = useState(p.airline || "");
  const [homeBase, setHomeBase] = useState(p.home_base || "");
  const [position, setPosition] = useState(p.position || POS[0]);
  const [jobTitle, setJobTitle] = useState(p.job_title || "");
  const [routeFocus, setRouteFocus] = useState<string>(p.route_focus || "mixed");
  const [mainGoalKey, setMainGoalKey] = useState<string>(p.main_goal_key || "general_fitness");
  const [equipment, setEquipment] = useState<string[]>(p.equipment || ["dumbbells", "yoga mat"]);
  const [cardio, setCardio] = useState<string[]>(p.cardio_equipment || []);
  const [trainLoc, setTrainLoc] = useState(p.training_location || LOC_OPTS[0]);
  const [maxMin, setMaxMin] = useState(String(p.max_home_minutes || 60));
  const [days, setDays] = useState(String(p.training_days_per_week || 4));
  // Preferred weekdays removed — crew rosters change constantly, so we no
  // longer ask (Iter 94r). We still send an empty list so the profile field
  // stays clean.
  const prefDays: string[] = [];
  const [level, setLevel] = useState(p.experience_level || LEVEL[1]);
  const [goal, setGoal] = useState(p.goal || "");
  const [injuries, setInjuries] = useState(p.injuries || "");
  const [dislike, setDislike] = useState(p.disliked_exercises || "");
  const [outside, setOutside] = useState<boolean>(p.will_run_outside ?? true);
  const [weight, setWeight] = useState(p.weight_kg ? String(p.weight_kg) : "");
  const [height, setHeight] = useState(p.height_cm ? String(p.height_cm) : "");
  const [cal, setCal] = useState(String(p.calorie_target || 2400));
  const [pro, setPro] = useState(String(p.protein_target || 160));
  const [loading, setLoading] = useState(false);

  const toggle = (arr: string[], set: (v: string[]) => void, v: string) =>
    set(arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);

  const submit = async () => {
    setLoading(true);
    try {
      await api("/auth/onboarding", {
        method: "POST",
        body: {
          airline: airline || null,
          home_base: homeBase || null,
          position,
          job_title: jobTitle || null,
          route_focus: routeFocus || null,
          main_goal_key: mainGoalKey || null,
          equipment,
          cardio_equipment: cardio,
          training_location: trainLoc,
          max_home_minutes: parseInt(maxMin) || 60,
          preferred_days: prefDays,
          disliked_exercises: dislike || null,
          injuries: injuries || null,
          goal: goal || null,
          experience_level: level,
          strength_level: level,
          will_run_outside: outside,
          swim_cycle: null,
          training_days_per_week: parseInt(days) || 4,
          height_cm: height ? parseFloat(height) : null,
          weight_kg: weight ? parseFloat(weight) : null,
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
    <SafeAreaView style={styles.root} edges={["top"]}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 140 }} keyboardShouldPersistTaps="handled">
          <Text style={styles.title}>PROFILE SETUP</Text>
          <Text style={styles.sub}>Tell your coach how you fly & train</Text>

          <Section label="AVIATION">
            <Field label="AIRLINE"><TextInput testID="ob-airline" style={styles.input} value={airline} onChangeText={setAirline} placeholder="Skyline Air" placeholderTextColor={theme.color.textDim} /></Field>
            <Field label="HOME BASE (IATA)"><TextInput testID="ob-base" style={styles.input} value={homeBase} onChangeText={setHomeBase} placeholder="LHR" autoCapitalize="characters" placeholderTextColor={theme.color.textDim} /></Field>
            <Field label="POSITION"><ChipRow opts={POS} val={position} onChange={setPosition} prefix="ob-pos" /></Field>
            <Field label="JOB TITLE (SPECIFIC)"><TextInput testID="ob-job-title" style={styles.input} value={jobTitle} onChangeText={setJobTitle} placeholder="Captain, First Officer, Purser…" placeholderTextColor={theme.color.textDim} /></Field>
            <Field label="ROUTE FOCUS">
              <View style={styles.chipsWrap}>
                {ROUTE_OPTS.map((r) => (
                  <Pressable
                    key={r.key}
                    testID={`ob-route-${r.key}`}
                    onPress={() => setRouteFocus(r.key)}
                    style={[styles.chip, routeFocus === r.key && styles.chipActive]}
                  >
                    <Text style={[styles.chipText, routeFocus === r.key && { color: "#fff" }]}>{r.label}</Text>
                  </Pressable>
                ))}
              </View>
            </Field>
          </Section>

          <Section label="HOME EQUIPMENT">
            <View style={styles.chipsWrap}>
              {EQUIP.map((e) => (
                <Pressable key={e} testID={`ob-eq-${e}`} onPress={() => toggle(equipment, setEquipment, e)} style={[styles.chip, equipment.includes(e) && styles.chipActive]}>
                  <Text style={[styles.chipText, equipment.includes(e) && { color: "#fff" }]}>{e}</Text>
                </Pressable>
              ))}
            </View>
            <Field label="WHERE DO YOU TRAIN?"><ChipRow opts={LOC_OPTS} val={trainLoc} onChange={setTrainLoc} prefix="ob-loc" /></Field>
            <Field label="MAX MINUTES AT HOME"><TextInput testID="ob-max-min" style={styles.input} value={maxMin} onChangeText={setMaxMin} keyboardType="number-pad" /></Field>
          </Section>

          <Section label="CARDIO OPTIONS">
            <View style={styles.chipsWrap}>
              {CARDIO.map((c) => (
                <Pressable key={c} testID={`ob-cardio-${c}`} onPress={() => toggle(cardio, setCardio, c)} style={[styles.chip, cardio.includes(c) && styles.chipActive]}>
                  <Text style={[styles.chipText, cardio.includes(c) && { color: "#fff" }]}>{c}</Text>
                </Pressable>
              ))}
              <Pressable testID="ob-outside-toggle" onPress={() => setOutside(!outside)} style={[styles.chip, outside && styles.chipActive]}>
                <Text style={[styles.chipText, outside && { color: "#fff" }]}>willing to run outside</Text>
              </Pressable>
            </View>
          </Section>

          <Section label="PREFERENCES">
            <Field label="TRAINING SESSIONS / WEEK"><TextInput testID="ob-days" style={styles.input} value={days} onChangeText={setDays} keyboardType="number-pad" /></Field>
            <Text style={styles.helperNote}>
              Fixed weekdays don&apos;t work for crew — CrewFit maps sessions to your actual roster days.
            </Text>
            <Field label="EXPERIENCE"><ChipRow opts={LEVEL} val={level} onChange={setLevel} prefix="ob-lvl" /></Field>
            <Field label="MAIN GOAL">
              <View style={styles.chipsWrap}>
                {GOAL_OPTS.map((g) => (
                  <Pressable
                    key={g.key}
                    testID={`ob-goal-key-${g.key}`}
                    onPress={() => setMainGoalKey(g.key)}
                    style={[styles.chip, mainGoalKey === g.key && styles.chipActive]}
                  >
                    <Text style={[styles.chipText, mainGoalKey === g.key && { color: "#fff" }]}>{g.label}</Text>
                  </Pressable>
                ))}
              </View>
            </Field>
            <Field label="EXTRA CONTEXT (OPTIONAL)"><TextInput testID="ob-goal" style={[styles.input, { minHeight: 60 }]} multiline value={goal} onChangeText={setGoal} placeholder="Stay strong on rotations, lose 4kg" placeholderTextColor={theme.color.textDim} /></Field>
            <Field label="INJURIES / LIMITATIONS"><TextInput testID="ob-inj" style={[styles.input, { minHeight: 50 }]} multiline value={injuries} onChangeText={setInjuries} placeholder="Left knee — avoid deep loaded lunges" placeholderTextColor={theme.color.textDim} /></Field>
            <Field label="EXERCISES YOU DISLIKE"><TextInput testID="ob-dislike" style={[styles.input, { minHeight: 50 }]} multiline value={dislike} onChangeText={setDislike} placeholder="No burpees" placeholderTextColor={theme.color.textDim} /></Field>
          </Section>

          <Section label="BODY & TARGETS">
            <View style={styles.row2}>
              <Field label="HEIGHT (cm)" flex><TextInput testID="ob-height" style={styles.input} value={height} onChangeText={setHeight} keyboardType="numeric" placeholder="180" placeholderTextColor={theme.color.textDim} /></Field>
              <Field label="WEIGHT (kg)" flex><TextInput testID="ob-weight" style={styles.input} value={weight} onChangeText={setWeight} keyboardType="numeric" placeholder="82" placeholderTextColor={theme.color.textDim} /></Field>
            </View>
            <View style={styles.row2}>
              <Field label="CALORIE TARGET" flex><TextInput testID="ob-cal" style={styles.input} value={cal} onChangeText={setCal} keyboardType="number-pad" /></Field>
              <Field label="PROTEIN (g)" flex><TextInput testID="ob-pro" style={styles.input} value={pro} onChangeText={setPro} keyboardType="number-pad" /></Field>
            </View>
          </Section>
        </ScrollView>
      </KeyboardAvoidingView>
      <View style={styles.sticky}>
        <Pressable testID="ob-submit" onPress={submit} disabled={loading} style={[styles.cta, loading && { opacity: 0.6 }]}>
          {loading ? <ActivityIndicator color="#fff" /> : <Text style={styles.ctaText}>SAVE & CONTINUE</Text>}
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

function Section({ label, children }: any) {
  return (
    <View style={{ marginTop: theme.space.lg }}>
      <Text style={styles.sectLabel}>{label}</Text>
      <View style={styles.sectBody}>{children}</View>
    </View>
  );
}
function Field({ label, children, flex }: any) {
  return (
    <View style={{ marginBottom: theme.space.sm, flex: flex ? 1 : undefined }}>
      <Text style={styles.label}>{label}</Text>
      {children}
    </View>
  );
}
function ChipRow({ opts, val, onChange, prefix }: any) {
  return (
    <View style={styles.chipsWrap}>
      {opts.map((o: string) => (
        <Pressable key={o} testID={`${prefix}-${o}`} onPress={() => onChange(o)} style={[styles.chip, val === o && styles.chipActive]}>
          <Text style={[styles.chipText, val === o && { color: "#fff" }]}>{o}</Text>
        </Pressable>
      ))}
    </View>
  );
}
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  title: { color: theme.color.text, fontSize: 26, fontWeight: "900", letterSpacing: 2, marginTop: theme.space.md },
  sub: { color: theme.color.textMuted, marginTop: 4 },
  sectLabel: { color: theme.color.brand, fontSize: 10, letterSpacing: 2, marginBottom: theme.space.xs, fontWeight: "800" },
  sectBody: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, padding: theme.space.md, gap: 6 },
  label: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 1.5, marginBottom: 4, fontWeight: "700" },
  input: { backgroundColor: theme.color.surface3, borderRadius: theme.radius.md, color: theme.color.text, paddingHorizontal: theme.space.md, paddingVertical: 12, borderWidth: 1, borderColor: theme.color.border, fontSize: 14 },
  chipsWrap: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: theme.radius.pill, backgroundColor: theme.color.surface3, borderWidth: 1, borderColor: theme.color.border, flexShrink: 0 },
  chipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipText: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700" },
  helperNote: { color: theme.color.textMuted, fontSize: 11, marginTop: -4, marginBottom: 6, fontStyle: "italic", lineHeight: 15 },
  row2: { flexDirection: "row", gap: theme.space.md },
  sticky: { position: "absolute", bottom: 0, left: 0, right: 0, padding: theme.space.lg, backgroundColor: theme.color.surface, borderTopWidth: 1, borderTopColor: theme.color.border },
  cta: { backgroundColor: theme.color.brand, paddingVertical: 16, borderRadius: theme.radius.md, alignItems: "center" },
  ctaText: { color: "#fff", fontWeight: "800", letterSpacing: 2, fontSize: 14 },
});
