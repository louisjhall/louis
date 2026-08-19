/**
 * Roster Received — Iter188 full-screen success confirmation.
 *
 * Product requirement (2026-06):
 *   "After the roster upload completes 100%, immediately navigate the
 *   client to a dedicated success screen — not a progress bar, not a
 *   banner, a full screen — that says: 'Roster Received. Your coach is
 *   reviewing your programme — this can take up to 24 hours. You'll be
 *   notified when it's ready.'"
 *
 * Freely navigable — this is NOT a lock. The client can tap "GO TO
 * HOME" (or the back button on Android) at any time. A persistent
 * home banner takes over from here until the coach approves.
 *
 * Deliberately isolated from `/roster-upload` so the flow can't
 * accidentally flash a progress bar before showing the success
 * message. `router.replace` from the confirm-duties screen lands
 * clients here directly.
 */
import React from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";

export default function RosterReceivedScreen() {
  const router = useRouter();

  const goHome = () => router.replace("/(client)/home");

  return (
    <SafeAreaView
      style={styles.root}
      edges={["top", "bottom", "left", "right"]}
      testID="roster-received-screen"
    >
      <View style={styles.body}>
        <View style={styles.iconWrap}>
          <Ionicons name="checkmark-done" size={44} color="#fff" />
        </View>

        <Text style={styles.eyebrow}>ROSTER RECEIVED</Text>

        <Text style={styles.title}>Your coach is reviewing your programme</Text>

        <Text style={styles.copy}>
          This can take up to 24 hours. You&apos;ll be notified when it&apos;s ready.
        </Text>

        <View style={styles.checklist}>
          <View style={styles.checkRow}>
            <Ionicons name="checkmark-circle" size={18} color={theme.color.green} />
            <Text style={styles.checkT}>Roster parsed and saved</Text>
          </View>
          <View style={styles.checkRow}>
            <Ionicons name="checkmark-circle" size={18} color={theme.color.green} />
            <Text style={styles.checkT}>Duties confirmed</Text>
          </View>
          <View style={styles.checkRow}>
            <Ionicons name="hourglass-outline" size={18} color={theme.color.brand} />
            <Text style={styles.checkT}>
              Louis is reviewing and building your programme
            </Text>
          </View>
        </View>
      </View>

      <View style={styles.footer}>
        <Pressable
          onPress={goHome}
          style={({ pressed }) => [styles.primary, pressed && { opacity: 0.85 }]}
          testID="roster-received-home"
          accessibilityRole="button"
          accessibilityLabel="Go to home"
        >
          <Ionicons name="home" size={16} color="#fff" />
          <Text style={styles.primaryT}>GO TO HOME</Text>
        </Pressable>
        <Text style={styles.hint}>
          You can carry on using the app while you wait.
        </Text>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: theme.color.bg,
  },
  body: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 28,
    gap: 12,
  },
  iconWrap: {
    width: 88, height: 88, borderRadius: 44,
    backgroundColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
    marginBottom: 20,
    shadowColor: theme.color.brand,
    shadowOpacity: 0.35, shadowRadius: 18, shadowOffset: { width: 0, height: 8 },
  },
  eyebrow: {
    color: theme.color.brand,
    fontSize: 12, fontWeight: "900", letterSpacing: 2.6,
  },
  title: {
    color: theme.color.text,
    fontSize: 24, fontWeight: "900",
    textAlign: "center", lineHeight: 30,
    marginTop: 6,
    paddingHorizontal: 8,
  },
  copy: {
    color: theme.color.textMuted,
    fontSize: 15, lineHeight: 22,
    textAlign: "center",
    marginTop: 10,
    paddingHorizontal: 4,
  },
  checklist: {
    marginTop: 28,
    padding: 18,
    borderRadius: 14,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
    gap: 12,
    width: "100%",
  },
  checkRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },
  checkT: {
    color: theme.color.text,
    fontSize: 13, lineHeight: 18,
    flex: 1,
    fontWeight: "600",
  },
  footer: {
    paddingHorizontal: 28,
    paddingBottom: 20,
    gap: 10,
  },
  primary: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
    paddingVertical: 16,
    borderRadius: 14,
    backgroundColor: theme.color.brand,
  },
  primaryT: {
    color: "#fff",
    fontSize: 13, fontWeight: "900", letterSpacing: 1.8,
  },
  hint: {
    color: theme.color.textMuted,
    fontSize: 12,
    fontStyle: "italic",
    textAlign: "center",
  },
});
