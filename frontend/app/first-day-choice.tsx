import { useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, Alert, ActivityIndicator } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

// Iter 94j — First-day choice screen (Parts 4 + 6 of the spec).
// Client chooses between:
//   1. Setup day     — start training tomorrow (DEFAULT, RECOMMENDED)
//   2. Light mobility today
//   3. I'm ready to train today
// Louis sees the choice in the coach dashboard.
// No AI wording anywhere.

type Choice = "setup_day" | "light_mobility_today" | "train_today";

const OPTIONS: { key: Choice; title: string; badge?: string; body: string }[] = [
  {
    key: "setup_day",
    title: "Setup day — start training tomorrow",
    badge: "RECOMMENDED",
    body:
      "Use today to review your plan, check your equipment, confirm your roster and get ready. " +
      "Your first proper session will be scheduled for tomorrow or the next suitable roster day.",
  },
  {
    key: "light_mobility_today",
    title: "Light mobility today",
    badge: "OPTIONAL",
    body:
      "Add a short 10–15 minute mobility or activation session today. " +
      "This will not count as a full training session.",
  },
  {
    key: "train_today",
    title: "I'm ready to train today",
    body:
      "CrewFit will only schedule a full workout today if your roster, recovery and equipment make it suitable.",
  },
];

export default function FirstDayChoice() {
  const router = useRouter();
  const [selected, setSelected] = useState<Choice>("setup_day");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [needsChoice, setNeedsChoice] = useState<boolean | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const s = await api<any>("/programme/first-day-status");
        setNeedsChoice(!!s.needs_choice);
        if (!s.needs_choice) {
          // Nothing to answer — send them home.
          router.replace("/(client)/home" as any);
          return;
        }
      } catch {
        // If the endpoint fails we still show the screen — safer than skipping.
        setNeedsChoice(true);
      } finally {
        setLoading(false);
      }
    })();
    // router is stable; hook only needs to fire once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = async () => {
    setSubmitting(true);
    try {
      const r = await api<any>("/programme/first-day-choice", {
        method: "POST", body: { choice: selected },
      });
      if (r?.block_reason) {
        Alert.alert("Today is better as a setup or recovery day",
          `${r.block_reason}\n\nYour first proper session has been moved to the next suitable day.`);
      }
      router.replace("/(client)/home" as any);
    } catch (e: any) {
      Alert.alert("Couldn't save your choice", e?.message || "Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading || needsChoice === null) {
    return (
      <SafeAreaView style={styles.container}>
        <ActivityIndicator color={theme.color.brand} />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      <ScrollView contentContainerStyle={{ padding: theme.space.lg }}>
        <Text style={styles.title}>Start today or prepare first?</Text>
        <Text style={styles.body}>
          Your CrewFit programme is ready to start. Most crew use the first day to review
          their plan, check equipment and prepare for the first proper session.
        </Text>
        <Text style={styles.question}>Would you like a workout today?</Text>

        {OPTIONS.map(opt => {
          const active = selected === opt.key;
          return (
            <Pressable
              key={opt.key}
              testID={`first-day-opt-${opt.key}`}
              onPress={() => setSelected(opt.key)}
              style={[styles.card, active && styles.cardActive]}
            >
              <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
                <View style={[styles.radio, active && styles.radioOn]}>
                  {active ? <View style={styles.radioDot} /> : null}
                </View>
                <View style={{ flex: 1 }}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <Text style={styles.cardTitle}>{opt.title}</Text>
                    {opt.badge ? (
                      <View style={[
                        styles.badge,
                        opt.badge === "RECOMMENDED" ? styles.badgeRecommended : styles.badgeOptional,
                      ]}>
                        <Text style={[
                          styles.badgeT,
                          opt.badge === "RECOMMENDED" ? styles.badgeRecommendedT : styles.badgeOptionalT,
                        ]}>{opt.badge}</Text>
                      </View>
                    ) : null}
                  </View>
                  <Text style={styles.cardBody}>{opt.body}</Text>
                </View>
              </View>
            </Pressable>
          );
        })}

        <Pressable
          testID="first-day-continue"
          onPress={submit}
          disabled={submitting}
          style={[styles.continueBtn, submitting && { opacity: 0.5 }]}
        >
          {submitting ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <>
              <Text style={styles.continueLabel}>CONTINUE</Text>
              <Ionicons name="arrow-forward" size={16} color="#fff" />
            </>
          )}
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.color.surface, justifyContent: "center" },
  title: { color: theme.color.text, fontFamily: theme.font.display, fontSize: 26, fontWeight: "800", letterSpacing: 0.3, marginBottom: 10 },
  body: { color: theme.color.text, fontSize: 14, lineHeight: 20, marginBottom: theme.space.lg },
  question: { color: theme.color.text, fontSize: 15, fontWeight: "800", marginBottom: theme.space.md, letterSpacing: 0.2 },
  card: {
    padding: theme.space.md, marginBottom: theme.space.md,
    backgroundColor: theme.color.surfaceElev, borderRadius: 12,
    borderWidth: 1, borderColor: theme.color.border,
  },
  cardActive: { borderColor: theme.color.brand, backgroundColor: theme.color.brandTint },
  cardTitle: { color: theme.color.text, fontSize: 14, fontWeight: "800" },
  cardBody: { color: theme.color.textMuted, fontSize: 12, lineHeight: 18, marginTop: 6 },
  radio: {
    width: 22, height: 22, borderRadius: 11, borderWidth: 2,
    borderColor: theme.color.textMuted, alignItems: "center", justifyContent: "center",
  },
  radioOn: { borderColor: theme.color.brand },
  radioDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: theme.color.brand },
  badge: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  badgeRecommended: { backgroundColor: "rgba(47,158,108,0.16)" },
  badgeOptional: { backgroundColor: "rgba(74,144,226,0.16)" },
  badgeT: { fontSize: 9, fontWeight: "900", letterSpacing: 1 },
  badgeRecommendedT: { color: "#2f9e6c" },
  badgeOptionalT: { color: "#4a90e2" },
  continueBtn: {
    marginTop: theme.space.md, padding: 16, borderRadius: 12,
    backgroundColor: theme.color.brand,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10,
  },
  continueLabel: { color: "#fff", fontWeight: "900", fontSize: 14, letterSpacing: 1.5 },
});
