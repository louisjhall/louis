/**
 * Reset Password — deep-link target from the Resend "reset your
 * password" email (link shape: `/reset-password?token=<opaque>`).
 *
 * Route: /(auth)/reset-password
 *
 * The email lives OUTSIDE the app, so this screen must be reachable
 * without a session. It parses the token from the URL, asks for a new
 * password (with confirm), POSTs to `/api/auth/reset-password`, then
 * uses the returned JWT to auto-log-in and route the user home.
 *
 * Failure paths:
 *   • token missing / malformed  → red "invalid link" state, no CTA
 *   • token expired / used       → same red state, offer "start over"
 *   • password rules violated    → inline validation, no request
 *   • server error               → banner + retry
 */
import React, { useCallback, useMemo, useState } from "react";
import {
  View, Text, Pressable, StyleSheet, ScrollView, TextInput,
  ActivityIndicator, Linking,
} from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { CrewFitLogo } from "@/src/components/Logo";
import { theme } from "@/src/lib/theme";
import { PUBLIC_URLS } from "@/src/lib/publicUrls";
import { api, setToken } from "@/src/lib/api";
import { useAuth } from "@/src/lib/auth";

const MIN_PASSWORD_LEN = 8;

type ResetResponse = {
  message: string;
  token: string | null;
  user: { id: string; email: string; name: string; role: string } | null;
};

export default function ResetPassword() {
  const router = useRouter();
  const params = useLocalSearchParams<{ token?: string }>();
  const { setUser } = useAuth();

  const rawToken = useMemo(() => {
    // useLocalSearchParams can hand us a string OR array (repeated key).
    const t = params.token;
    return Array.isArray(t) ? t[0] : (t || "");
  }, [params.token]);

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPw, setShowPw] = useState(false);

  const tokenLooksValid = rawToken.length >= 16;

  const validate = useCallback(() => {
    if (password.length < MIN_PASSWORD_LEN) {
      return `Password must be at least ${MIN_PASSWORD_LEN} characters.`;
    }
    if (password !== confirm) {
      return "The two passwords don't match.";
    }
    return null;
  }, [password, confirm]);

  const onSubmit = useCallback(async () => {
    setError(null);
    if (!tokenLooksValid) {
      setError("This reset link is invalid. Request a new one from the sign-in screen.");
      return;
    }
    const vErr = validate();
    if (vErr) { setError(vErr); return; }

    setBusy(true);
    try {
      const r = await api<ResetResponse>("/auth/reset-password", {
        method: "POST",
        body: { token: rawToken, new_password: password },
        noAuth: true,
      });
      // Backend returns a fresh JWT on success → auto-sign-in.
      if (r.token && r.user) {
        await setToken(r.token);
        setUser(r.user as any);
      }
      // Route to home regardless — if the token wasn't returned we
      // fall back to the login screen and the user re-enters credentials.
      if (r.token) {
        router.replace("/");
      } else {
        router.replace("/(auth)/login");
      }
    } catch (e: any) {
      const msg = (e?.message || "").toLowerCase();
      if (msg.includes("reset_token_invalid_or_expired") || msg.includes("400")) {
        setError(
          "This reset link is invalid or has expired. Request a fresh " +
          "one from the sign-in screen."
        );
      } else {
        setError(e?.message || "Something went wrong. Try again in a moment.");
      }
    } finally {
      setBusy(false);
    }
  }, [rawToken, tokenLooksValid, validate, password, router, setUser]);

  return (
    <View style={styles.root}>
      <LinearGradient
        colors={["rgba(0,0,0,0.55)", "rgba(0,0,0,0.92)", "#000000"]}
        style={StyleSheet.absoluteFill}
      />
      <SafeAreaView style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <Pressable
            onPress={() => router.replace("/(auth)/login")}
            style={styles.backBtn}
            hitSlop={10}
            testID="reset-back"
          >
            <Ionicons name="chevron-back" size={22} color={theme.color.text} />
            <Text style={styles.backText}>Back to sign in</Text>
          </Pressable>

          <View style={styles.top}>
            <CrewFitLogo size={110} style={{ alignSelf: "center" }} />
            <Text style={styles.tag}>NEW PASSWORD</Text>
          </View>

          <View style={styles.card}>
            {!tokenLooksValid ? (
              <View testID="reset-invalid-box">
                <View style={[styles.checkCircle, { backgroundColor: "#4a1a1e" }]}>
                  <Ionicons name="alert" size={30} color={theme.color.brand} />
                </View>
                <Text style={styles.h1}>Invalid reset link</Text>
                <Text style={styles.sub}>
                  This link is missing its token. Ask for a fresh reset
                  from the sign-in screen — the new email will contain
                  a working link.
                </Text>
                <Pressable
                  testID="reset-goto-forgot"
                  onPress={() => router.replace("/(auth)/forgot-password")}
                  style={({ pressed }) => [
                    styles.cta,
                    pressed && { backgroundColor: theme.color.brandDark },
                  ]}
                >
                  <Text style={styles.ctaText}>REQUEST NEW LINK</Text>
                </Pressable>
              </View>
            ) : (
              <>
                <Text style={styles.h1}>Choose a new password</Text>
                <Text style={styles.sub}>
                  Pick something you&apos;ll remember. Minimum {MIN_PASSWORD_LEN}
                  {" "}characters.
                </Text>

                <Text style={styles.label}>NEW PASSWORD</Text>
                <View style={styles.inputRow}>
                  <TextInput
                    testID="reset-password-input"
                    style={styles.inputFlex}
                    value={password}
                    onChangeText={(t) => { setPassword(t); if (error) setError(null); }}
                    secureTextEntry={!showPw}
                    autoCapitalize="none"
                    autoCorrect={false}
                    placeholder="At least 8 characters"
                    placeholderTextColor={theme.color.textDim}
                  />
                  <Pressable onPress={() => setShowPw((v) => !v)} hitSlop={8} style={styles.eyeBtn}>
                    <Ionicons
                      name={showPw ? "eye-off-outline" : "eye-outline"}
                      size={18}
                      color={theme.color.textMuted}
                    />
                  </Pressable>
                </View>

                <Text style={styles.label}>CONFIRM PASSWORD</Text>
                <TextInput
                  testID="reset-confirm-input"
                  style={styles.input}
                  value={confirm}
                  onChangeText={(t) => { setConfirm(t); if (error) setError(null); }}
                  secureTextEntry={!showPw}
                  autoCapitalize="none"
                  autoCorrect={false}
                  placeholder="Type it again"
                  placeholderTextColor={theme.color.textDim}
                  onSubmitEditing={onSubmit}
                  returnKeyType="done"
                />

                {error ? (
                  <Text style={styles.errText} testID="reset-error">{error}</Text>
                ) : null}

                <Pressable
                  testID="reset-submit"
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
                      <Ionicons name="lock-closed-outline" size={16} color="#fff" />
                      <Text style={styles.ctaText}>UPDATE PASSWORD</Text>
                    </>
                  )}
                </Pressable>
              </>
            )}

            <View style={{ height: 20 }} />

            <View style={styles.publicLinksRow}>
              <Pressable
                onPress={() => Linking.openURL(PUBLIC_URLS.privacy)}
                testID="reset-privacy-link"
                hitSlop={8}
              >
                <Text style={styles.publicLink}>Privacy Policy</Text>
              </Pressable>
              <Text style={styles.publicSep}>·</Text>
              <Pressable
                onPress={() => Linking.openURL(PUBLIC_URLS.support)}
                testID="reset-support-link"
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
  inputRow: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: theme.color.surface3,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.color.border,
  },
  inputFlex: {
    flex: 1,
    color: theme.color.text,
    paddingHorizontal: theme.space.md,
    paddingVertical: 14,
    fontSize: 16,
  },
  eyeBtn: {
    paddingHorizontal: theme.space.md,
  },
  errText: {
    color: theme.color.brand,
    fontSize: 12,
    marginTop: theme.space.sm,
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
