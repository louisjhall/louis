/**
 * Forgot Password — support screen (placeholder for future self-serve reset).
 *
 * Route: /(auth)/forgot-password
 *
 * Today: there is no public email-based password reset endpoint on the
 * backend (only the coach-authenticated `POST /coach/clients/{id}/reset-password`).
 * This screen therefore guides the client to email the CrewFit support
 * inbox — Louis reads that inbox and can trigger the coach-side reset from
 * the client admin drawer in under a minute.
 *
 * When we later wire up a real reset flow (Resend / Emergent-managed email
 * with a signed reset token), replace this file with:
 *   1. An email input,
 *   2. A "Send reset link" button that hits `/auth/request-password-reset`,
 *   3. A success message stating that a link has been emailed if the
 *      account exists (uniform response — no user enumeration).
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, Pressable, StyleSheet, ScrollView, Linking, Platform,
  TextInput,
} from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { CrewFitLogo } from "@/src/components/Logo";
import { theme } from "@/src/lib/theme";
import { PUBLIC_URLS } from "@/src/lib/publicUrls";

const SUPPORT_EMAIL = "support@crewfit.net";

export default function ForgotPassword() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);

  const openMail = useCallback(async () => {
    const subject = "Password reset request";
    const body = [
      "Hi Louis,",
      "",
      "I need to reset my CrewFit password.",
      "",
      email ? `My email on the app: ${email}` : "My email on the app: (please add here)",
      "",
      "Thanks.",
    ].join("\n");
    const url =
      `mailto:${SUPPORT_EMAIL}` +
      `?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;

    // Web browsers may block mailto — fall back to copying the address.
    try {
      const supported = await Linking.canOpenURL(url);
      if (supported) {
        await Linking.openURL(url);
      } else {
        // Fallback: copy to clipboard if available (web).
        if (Platform.OS === "web" && (navigator as any)?.clipboard?.writeText) {
          try { await (navigator as any).clipboard.writeText(SUPPORT_EMAIL); } catch {}
        }
      }
    } catch {
      /* silent — the coach's email is visible on screen anyway */
    }
    setSent(true);
  }, [email]);

  return (
    <View style={styles.root}>
      <LinearGradient
        colors={["rgba(0,0,0,0.55)", "rgba(0,0,0,0.92)", "#000000"]}
        style={StyleSheet.absoluteFill}
      />
      <SafeAreaView style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <Pressable
            onPress={() => router.back()}
            style={styles.backBtn}
            hitSlop={10}
            testID="forgot-back"
          >
            <Ionicons name="chevron-back" size={22} color={theme.color.text} />
            <Text style={styles.backText}>Back to sign in</Text>
          </Pressable>

          <View style={styles.top}>
            <CrewFitLogo size={110} style={{ alignSelf: "center" }} />
            <Text style={styles.tag}>PASSWORD RESET</Text>
          </View>

          <View style={styles.card}>
            <Text style={styles.h1}>Forgot your password?</Text>
            <Text style={styles.sub}>
              We&apos;re in private beta, so password resets are handled by your
              coach directly. Enter your email and hit the button — it opens
              a pre-filled message to Louis who will reset your password
              within the day.
            </Text>

            <Text style={styles.label}>EMAIL</Text>
            <TextInput
              testID="forgot-email-input"
              style={styles.input}
              value={email}
              onChangeText={setEmail}
              keyboardType="email-address"
              autoCapitalize="none"
              autoCorrect={false}
              placeholder="you@airline.com"
              placeholderTextColor={theme.color.textDim}
            />

            <Pressable
              testID="forgot-email-coach"
              onPress={openMail}
              style={({ pressed }) => [
                styles.cta,
                pressed && { backgroundColor: theme.color.brandDark },
              ]}
            >
              <Ionicons name="mail-outline" size={16} color="#fff" />
              <Text style={styles.ctaText}>EMAIL MY COACH</Text>
            </Pressable>

            {sent && (
              <View style={styles.sentBox} testID="forgot-sent-box">
                <Ionicons name="checkmark-circle" size={18} color={theme.color.green} />
                <Text style={styles.sentText}>
                  Message opened. If your email app didn&apos;t launch,
                  send a note to{" "}
                  <Text style={styles.sentEmail} selectable>{SUPPORT_EMAIL}</Text>{" "}
                  yourself — Louis will reset your password by end of day.
                </Text>
              </View>
            )}

            <View style={{ height: 20 }} />

            <Text style={styles.footNote}>
              Once we exit beta, this screen will send you an automated reset
              link instead. Nothing to do on your side.
            </Text>

            <View style={styles.publicLinksRow}>
              <Pressable
                onPress={() => Linking.openURL(PUBLIC_URLS.privacy)}
                testID="forgot-privacy-link"
                hitSlop={8}
              >
                <Text style={styles.publicLink}>Privacy Policy</Text>
              </Pressable>
              <Text style={styles.publicSep}>·</Text>
              <Pressable
                onPress={() => Linking.openURL(PUBLIC_URLS.support)}
                testID="forgot-support-link"
                hitSlop={8}
              >
                <Text style={styles.publicLink}>Support</Text>
              </Pressable>
            </View>
          </View>
        </ScrollView>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  scroll: { flexGrow: 1, padding: theme.space.lg },
  backBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingVertical: 6, paddingHorizontal: 4, alignSelf: "flex-start",
  },
  backText: { color: theme.color.text, fontSize: 14, fontWeight: "600" },
  top: { marginTop: theme.space.lg, alignItems: "center" },
  tag: { color: theme.color.brand, letterSpacing: 3, marginTop: 6, fontSize: 11, fontWeight: "700" },
  card: {
    backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.lg,
    padding: theme.space.xl,
    borderWidth: 1,
    borderColor: theme.color.border,
    marginTop: theme.space.xxl,
  },
  h1: { color: theme.color.text, fontSize: 22, fontWeight: "800" },
  sub: {
    color: theme.color.textMuted, marginTop: 6, lineHeight: 20,
    fontSize: 13,
  },
  label: {
    color: theme.color.textMuted, fontSize: 11, letterSpacing: 1.5,
    marginTop: theme.space.lg, marginBottom: theme.space.xs, fontWeight: "700",
  },
  input: {
    backgroundColor: theme.color.surface3,
    borderRadius: theme.radius.md,
    color: theme.color.text,
    paddingHorizontal: theme.space.md,
    paddingVertical: 14,
    borderWidth: 1,
    borderColor: theme.color.border,
    fontSize: 16,
  },
  cta: {
    backgroundColor: theme.color.brand,
    marginTop: theme.space.xl,
    paddingVertical: 14,
    borderRadius: theme.radius.md,
    alignItems: "center",
    flexDirection: "row",
    justifyContent: "center",
    gap: 8,
  },
  ctaText: { color: "#fff", fontWeight: "800", letterSpacing: 2, fontSize: 14 },
  sentBox: {
    marginTop: theme.space.md,
    padding: theme.space.md,
    borderRadius: theme.radius.md,
    backgroundColor: "rgba(52,211,153,0.10)",
    borderWidth: 1,
    borderColor: theme.color.green,
    flexDirection: "row",
    gap: 8,
  },
  sentText: { color: theme.color.text, fontSize: 12, lineHeight: 17, flex: 1 },
  sentEmail: { color: theme.color.brand, fontWeight: "700" },
  footNote: {
    color: theme.color.textDim, fontSize: 11, lineHeight: 15,
    textAlign: "center", fontStyle: "italic",
  },
  publicLinksRow: {
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    gap: 10,
    marginTop: 14,
  },
  publicLink: {
    color: theme.color.textMuted,
    fontSize: 12,
    textDecorationLine: "underline",
    fontWeight: "600",
  },
  publicSep: {
    color: theme.color.textDim,
    fontSize: 12,
  },
});
