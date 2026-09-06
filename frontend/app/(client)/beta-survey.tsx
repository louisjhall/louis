/**
 * Beta Survey — Iter202 · Phase 2A.
 *
 * Five-question survey shown from the Day 25 milestone. One submission
 * per user — repeat visits show the thank-you state.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TextInput, Pressable,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

export default function BetaSurveyScreen() {
  const router = useRouter();
  const [experience, setExperience] = useState(0);
  const [recommend, setRecommend] = useState(0);
  const [mostValuable, setMostValuable] = useState("");
  const [couldBeBetter, setCouldBeBetter] = useState("");
  const [blocker, setBlocker] = useState("");
  const [alreadyDone, setAlreadyDone] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api<{ id?: string }>("/beta/survey/mine")
      .then((r) => setAlreadyDone(!!r?.id))
      .catch(() => setAlreadyDone(false));
  }, []);

  const submit = useCallback(async () => {
    setErr(null);
    if (experience < 1 || recommend < 1) {
      setErr("Please rate your experience and how likely you are to recommend.");
      return;
    }
    setBusy(true);
    try {
      await api("/beta/survey", {
        method: "POST",
        body: {
          experience_rating: experience,
          most_valuable: mostValuable || null,
          could_be_better: couldBeBetter || null,
          recommendation_rating: recommend,
          continuation_blocker: blocker || null,
        },
      });
      setDone(true);
    } catch (e: any) {
      setErr(e?.message || "Couldn't save your survey. Please try again.");
    } finally { setBusy(false); }
  }, [experience, recommend, mostValuable, couldBeBetter, blocker]);

  if (alreadyDone === null) {
    return (
      <View style={[styles.root, { justifyContent: "center", alignItems: "center" }]}>
        <ActivityIndicator color={theme.color.brand} />
      </View>
    );
  }

  if (alreadyDone || done) {
    return (
      <SafeAreaView style={styles.root}>
        <View style={styles.thankWrap}>
          <View style={styles.tick}><Ionicons name="checkmark" size={40} color="#fff" /></View>
          <Text style={styles.thankTitle}>Thank you.</Text>
          <Text style={styles.thankSub}>Your feedback helps shape the app. Louis will read every response.</Text>
          <Pressable
            testID="beta-survey-goto-membership"
            style={({ pressed }) => [styles.primary, pressed && { opacity: 0.75 }]}
            onPress={() => router.replace("/(client)/membership" as any)}
          >
            <Text style={styles.primaryText}>VIEW MEMBERSHIP OPTIONS</Text>
          </Pressable>
          <Pressable onPress={() => router.back()} style={styles.linkBtn}>
            <Text style={styles.linkText}>Back to CrewFit</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.root}>
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} style={{ padding: 4 }} hitSlop={10}>
            <Ionicons name="chevron-back" size={22} color={theme.color.text} />
          </Pressable>
          <Text style={styles.headerTitle}>Beta feedback</Text>
          <View style={{ width: 32 }} />
        </View>

        <Text style={styles.lead}>
          Under 2 minutes. Your answers help us make CrewFit better for every crew member.
        </Text>

        <Question label="How would you rate your CrewFit experience so far?">
          <StarRow value={experience} onChange={setExperience} testID="q1-star" />
        </Question>

        <Question label="What has been most valuable to you?">
          <TextInput
            style={styles.textarea}
            multiline
            numberOfLines={3}
            value={mostValuable}
            onChangeText={setMostValuable}
            placeholder="Optional"
            placeholderTextColor={theme.color.textDim}
            testID="q2-text"
          />
        </Question>

        <Question label="What could be better?">
          <TextInput
            style={styles.textarea}
            multiline
            numberOfLines={3}
            value={couldBeBetter}
            onChangeText={setCouldBeBetter}
            placeholder="Optional"
            placeholderTextColor={theme.color.textDim}
            testID="q3-text"
          />
        </Question>

        <Question label="How likely are you to recommend CrewFit?">
          <StarRow value={recommend} onChange={setRecommend} testID="q4-star" />
        </Question>

        <Question label="Is there anything stopping you from continuing?">
          <TextInput
            style={styles.textarea}
            multiline
            numberOfLines={3}
            value={blocker}
            onChangeText={setBlocker}
            placeholder="Optional"
            placeholderTextColor={theme.color.textDim}
            testID="q5-text"
          />
        </Question>

        {err ? <Text style={styles.err}>{err}</Text> : null}

        <Pressable
          testID="beta-survey-submit"
          disabled={busy}
          onPress={submit}
          style={({ pressed }) => [styles.primary, (pressed || busy) && { opacity: 0.75 }]}
        >
          {busy ? <ActivityIndicator color="#fff" /> : (
            <Text style={styles.primaryText}>SUBMIT FEEDBACK</Text>
          )}
        </Pressable>

        <View style={{ height: 40 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

function Question({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <View style={styles.qWrap}>
      <Text style={styles.qLabel}>{label}</Text>
      {children}
    </View>
  );
}

function StarRow({ value, onChange, testID }: { value: number; onChange: (n: number) => void; testID: string }) {
  return (
    <View style={{ flexDirection: "row", gap: 8, marginTop: 6 }}>
      {[1, 2, 3, 4, 5].map((n) => (
        <Pressable key={n} onPress={() => onChange(n)} testID={`${testID}-${n}`} hitSlop={6}>
          <Ionicons
            name={n <= value ? "star" : "star-outline"}
            size={30}
            color={n <= value ? "#f7b955" : theme.color.textDim}
          />
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.bg },
  scroll: { padding: theme.space.lg },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: theme.space.lg },
  headerTitle: { color: theme.color.text, fontWeight: "800", fontSize: 16 },
  lead: { color: theme.color.textMuted, fontSize: 13, lineHeight: 19, marginBottom: theme.space.lg },
  qWrap: { marginBottom: theme.space.lg },
  qLabel: { color: theme.color.text, fontSize: 14, fontWeight: "700", marginBottom: 4 },
  textarea: {
    backgroundColor: theme.color.surface2, color: theme.color.text,
    borderWidth: 1, borderColor: theme.color.border, borderRadius: theme.radius.md,
    paddingHorizontal: 12, paddingVertical: 10, minHeight: 80, textAlignVertical: "top",
    fontSize: 14,
  },
  err: { color: theme.color.brand, fontSize: 12, fontWeight: "600", marginBottom: theme.space.md },
  primary: {
    backgroundColor: theme.color.brand, paddingVertical: 14, borderRadius: theme.radius.md,
    alignItems: "center", minHeight: 48, justifyContent: "center",
  },
  primaryText: { color: "#fff", fontWeight: "800", letterSpacing: 1.4, fontSize: 13 },
  linkBtn: { marginTop: theme.space.lg, padding: 8, alignItems: "center" },
  linkText: { color: theme.color.textMuted, fontSize: 12, fontWeight: "700" },
  thankWrap: { flex: 1, alignItems: "center", justifyContent: "center", padding: theme.space.xl },
  tick: { width: 72, height: 72, borderRadius: 36, backgroundColor: theme.color.brand, alignItems: "center", justifyContent: "center", marginBottom: theme.space.lg },
  thankTitle: { color: theme.color.text, fontSize: 24, fontWeight: "800" },
  thankSub: { color: theme.color.textMuted, fontSize: 14, marginTop: 8, textAlign: "center", lineHeight: 20 },
});
