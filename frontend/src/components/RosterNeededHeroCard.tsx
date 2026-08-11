/**
 * RosterNeededHeroCard — top-of-dashboard hero for clients who haven't
 * confirmed a roster yet.
 *
 * Iter 159. Visibility contract:
 *   - Shows when the caller has NO confirmed roster days.
 *   - Hides during an in-flight roster upload / parsing job so the user
 *     doesn't see conflicting CTAs ("Import now" vs "Processing…").
 *   - Hides the moment `/roster/current` returns a doc with `days.length > 0`.
 *
 * The parent (home.tsx) owns the data fetch — this component is a pure
 * presentational shell. It renders `null` when the parent tells it to.
 */
import React from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { theme } from "@/src/lib/theme";

type Props = {
  /** Truthy if the client has zero confirmed roster days. */
  needsRoster: boolean;
  /** Truthy if a roster job is currently uploading / parsing.
   *  Prevents dual-CTA confusion. */
  jobInFlight: boolean;
};

export function RosterNeededHeroCard({ needsRoster, jobInFlight }: Props) {
  const router = useRouter();
  if (!needsRoster || jobInFlight) return null;

  const onImport = () => {
    router.push("/roster-upload");
  };

  return (
    <View style={styles.card} testID="roster-needed-hero">
      <View style={styles.iconWrap}>
        <Ionicons name="calendar" size={26} color="#fff" />
        <View style={styles.badge}>
          <Ionicons name="alert" size={11} color="#fff" />
        </View>
      </View>

      <Text style={styles.eyebrow}>ACTION REQUIRED</Text>
      <Text style={styles.title}>Your roster builds your plan</Text>
      <Text style={styles.body}>
        Upload your latest roster so CrewFit can schedule workouts around your flights,
        layovers and rest days. Your training plan can&apos;t start without it.
      </Text>

      <Pressable
        onPress={onImport}
        style={({ pressed }) => [styles.cta, pressed && { opacity: 0.85 }]}
        testID="roster-needed-import-cta"
        accessibilityRole="button"
        accessibilityLabel="Import roster now"
      >
        <Ionicons name="cloud-upload" size={18} color="#fff" />
        <Text style={styles.ctaT}>IMPORT ROSTER NOW</Text>
      </Pressable>

      <View style={styles.trustRow}>
        <Ionicons name="lock-closed" size={11} color={theme.color.textMuted} />
        <Text style={styles.trustT}>Private — only you and your coach can see it.</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    padding: 20,
    borderRadius: 16,
    backgroundColor: theme.color.brandTint,
    borderWidth: 1,
    borderColor: theme.color.brand,
    alignItems: "center",
  },
  iconWrap: {
    width: 60,
    height: 60,
    borderRadius: 30,
    backgroundColor: theme.color.brand,
    alignItems: "center",
    justifyContent: "center",
    position: "relative",
  },
  badge: {
    position: "absolute",
    top: -2,
    right: -2,
    width: 20,
    height: 20,
    borderRadius: 10,
    backgroundColor: theme.color.amber,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 2,
    borderColor: theme.color.bg,
  },
  eyebrow: {
    color: theme.color.brand,
    fontSize: 11,
    fontWeight: "900",
    letterSpacing: 2,
    marginTop: 14,
  },
  title: {
    color: theme.color.text,
    fontSize: 20,
    fontWeight: "900",
    marginTop: 6,
    textAlign: "center",
  },
  body: {
    color: theme.color.textMuted,
    fontSize: 13,
    lineHeight: 19,
    textAlign: "center",
    marginTop: 8,
    paddingHorizontal: 8,
  },
  cta: {
    marginTop: 18,
    alignSelf: "stretch",
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
    paddingVertical: 16,
    borderRadius: 12,
    backgroundColor: theme.color.brand,
    // Subtle glow via border to lift the CTA on tinted background.
    borderWidth: 1,
    borderColor: theme.color.brandGlow,
  },
  ctaT: {
    color: "#fff",
    fontSize: 14,
    fontWeight: "900",
    letterSpacing: 2,
  },
  trustRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: 12,
  },
  trustT: {
    color: theme.color.textMuted,
    fontSize: 11,
    fontStyle: "italic",
  },
});
