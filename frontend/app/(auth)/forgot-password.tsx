/**
 * Forgot Password — self-serve reset via email link.
 *
 * Route: /(auth)/forgot-password
 *
 * Iter200: swapped from a mailto placeholder to a real
 * `POST /api/auth/forgot-password` call. The backend always responds
 * with a uniform 200 message (so we don't leak whether the email is
 * on file), and Resend delivers the reset link to the user's inbox.
 * The link opens `/(auth)/reset-password?token=…` where the user
 * chooses a new password.
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, Pressable, StyleSheet, ScrollView, Linking,
  TextInput, ActivityIndicator,
} from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { CrewFitLogo } from "@/src/components/Logo";
import { theme } from "@/src/lib/theme";
import { PUBLIC_URLS } from "@/src/lib/publicUrls";
import { api } from "@/src/lib/api";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function ForgotPassword() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = useCallback(async () => {
    setError(null);
    const trimmed = email.trim().toLowerCase();
    if (!EMAIL_RE.test(trimmed)) {
      setError("Enter a valid email address.");
      return;
    }
    setBusy(true);
    try {
      await api<{ message: string }>("/auth/forgot-password", {
        method: "POST",
        body: { email: trimmed },
      });
      // We deliberately trust the uniform 200 — even if the account
      // doesn't exist the UI must show the same success state so we
      // never leak account existence via UI copy or timing.
      setSent(true);
    } catch (e: any) {
      // Network / server hiccup only lands here (4xx/5xx from api()).
      setError(e?.message || "Something went wrong. Try again in a moment.");
    } finally {
      setBusy(false);
    }
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
            {sent ? (
              <View testID="forgot-sent-box">
                <View style={styles.checkCircle}>
                  <Ionicons name="checkmark" size={30} color="#fff" />
                </View>
                <Text style={styles.h1}>Check your inbox</Text>
                <Text style={styles.sub}>
                  If an account exists for{" "}
                  <Text style={styles.subEmail}>{email.trim().toLowerCase()}</Text>,
                  we&apos;ve sent a reset link. The link expires in 15
                  minutes.
                </Text>
                <Text style={[styles.footNote, { marginTop: theme.space.xl }]}>
                  Didn&apos;t get anything? Check your spam folder, then
                  try again in a few minutes.
                </Text>

                <Pressable
                  testID="forgot-resend"
                  onPress={() => { setSent(false); setError(null); }}
                  style={({ pressed }) => [
                    styles.ctaSecondary,
                    pressed && { opacity: 0.7 },
                  ]}
                >
                  <Text style={styles.ctaSecondaryText}>SEND ANOTHER LINK</Text>
                </Pressable>
              </View>
            ) : (
              <>
                <Text style={styles.h1}>Forgot your password?</Text>
                <Text style={styles.sub}>
                  Enter the email on your CrewFit account and we&apos;ll
                  send a reset link. The link works once and expires in
                  15 minutes.
                </Text>

                <Text style={styles.label}>EMAIL</Text>
                <TextInput
                  testID="forgot-email-input"
                  style={styles.input}
                  value={email}
                  onChangeText={(t) => { setEmail(t); if (error) setError(null); }}
                  keyboardType="email-address"
                  autoCapitalize="none"
                  autoCorrect={false}
                  placeholder="you@airline.com"
                  placeholderTextColor={theme.color.textDim}
                  onSubmitEditing={onSubmit}
                  returnKeyType="send"
                />

                {error ? (
                  <Text style={styles.errText} testID="forgot-error">{error}</Text>
                ) : null}

                <Pressable
                  testID="forgot-submit"
                  onPress={onSubmit}
                  disabled={busy}
                  style={({ pressed }) => [
                    styles.cta,
                    (pressed || busy) && { backgroundColor: theme.color.brandDark },
                  ]}
                >
                  {busy ? (
                    <ActivityIndicator color="#fff" />
                  ) : (
                    <>
                      <Ionicons name="mail-outline" size={16} color="#fff" />
                      <Text style={styles.ctaText}>SEND RESET LINK</Text>
                    </>
                  )}
                </Pressable>
              </>
            )}

            <View style={{ height: 20 }} />

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
  checkCircle: {
    width: 56, height: 56, borderRadius: 28,
    backgroundColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
    marginBottom: theme.space.md,
    alignSelf: "flex-start",
  },
  h1: { color: theme.color.text, fontSize: 22, fontWeight: "800" },
  sub: {
    color: theme.color.textMuted, marginTop: 6, lineHeight: 20,
    fontSize: 13,
  },
  subEmail: { color: theme.color.text, fontWeight: "700" },
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
  errText: {
    color: theme.color.brand,
    fontSize: 12,
    marginTop: theme.space.xs,
    fontWeight: "600",
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
    minHeight: 48,
  },
  ctaText: { color: "#fff", fontWeight: "800", letterSpacing: 2, fontSize: 14 },
  ctaSecondary: {
    marginTop: theme.space.xl,
    paddingVertical: 12,
    borderRadius: theme.radius.md,
    alignItems: "center",
    borderWidth: 1,
    borderColor: theme.color.border,
  },
  ctaSecondaryText: {
    color: theme.color.textMuted, fontWeight: "700", letterSpacing: 2, fontSize: 12,
  },
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
