import { useState } from "react";
import {
  View, Text, TextInput, Pressable, StyleSheet, KeyboardAvoidingView, Platform,
  ScrollView, ActivityIndicator, useWindowDimensions, Linking,
} from "react-native";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { useAuth } from "@/src/lib/auth";
import { usePreview } from "@/src/lib/preview";
import { theme } from "@/src/lib/theme";
import { CrewFitLogo } from "@/src/components/Logo";
import { PUBLIC_URLS } from "@/src/lib/publicUrls";
import { SocialButtons, useEmergentAuthCallback } from "@/src/components/SocialButtons";

// Iter 94t — Login hero shows airline crew in uniform (pilot walking through
// airport with roller bag) to match the "crew, not civilian" brand feel.
const HERO = "https://images.unsplash.com/photo-1436491865332-7a61a109cc05?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200";

function errMsg(e: any): string {
  if (!e) return "Login failed";
  if (typeof e === "string") return e;
  if (typeof e.message === "string") return e.message;
  if (typeof e.detail === "string") return e.detail;
  try { return JSON.stringify(e); } catch { return "Login failed"; }
}

export default function Login() {
  const { login } = useAuth();
  const { preview, exit: exitPreview } = usePreview();
  const router = useRouter();
  const { width } = useWindowDimensions();
  const isDesktopWeb = Platform.OS === "web" && width >= 1024;
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // Iter200 · Watch for the Emergent OAuth callback on this screen —
  // when the user returns from auth.emergentagent.com with a
  // ``session_id`` on the URL we exchange it and land straight in
  // the app. The root-layout gate handles the actual navigation.
  useEmergentAuthCallback();

  const submit = async () => {
    setErr(null);
    // If a preview session is active, always exit first so we don't try to
    // log in while the preview JWT is stashed / write-guarded.
    if (preview.active) {
      try { await exitPreview(); } catch {}
    }
    setLoading(true);
    try {
      const u = await login(email.trim(), password);
      if (u.role === "coach") router.replace("/(coach)/v2-home");
      else if (!u.onboarded) router.replace("/assessment");
      else router.replace("/(client)/home");
    } catch (e: any) {
      setErr(errMsg(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={styles.root}>
      <Image source={HERO} style={styles.bg} contentFit="cover" />
      <LinearGradient
        colors={["rgba(0,0,0,0.55)", "rgba(0,0,0,0.92)", "#000000"]}
        locations={[0, 0.55, 1]}
        style={StyleSheet.absoluteFill}
      />
      <SafeAreaView style={{ flex: 1 }}>
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : "height"}
          style={{ flex: 1 }}
        >
          <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
            <View style={styles.top}>
              <CrewFitLogo size={140} style={{ alignSelf: "center" }} />
              <Text style={styles.tag}>TRAIN AROUND THE ROSTER</Text>
            </View>

            <View style={styles.card}>
              <Text style={styles.h1}>Sign in</Text>
              <Text style={styles.sub}>Client or coach access</Text>

              {preview.active ? (
                <View style={styles.previewNotice} testID="login-preview-notice">
                  <Text style={styles.previewNoticeT}>PREVIEW SESSION ACTIVE</Text>
                  <Text style={styles.previewNoticeS}>
                    You&apos;re still impersonating {preview.target?.email || preview.target?.name || "a preview client"}. Sign in below (or use the button) to return to your coach account — we&apos;ll exit preview automatically.
                  </Text>
                  <Pressable
                    testID="login-exit-preview"
                    onPress={async () => {
                      try { await exitPreview(); } catch {}
                      // Iter 122e — do not autofill real credentials in the
                      // shipped bundle. Coach types their own password.
                      setEmail("");
                      setPassword("");
                    }}
                    style={styles.previewNoticeBtn}
                  >
                    <Text style={styles.previewNoticeBtnT}>EXIT PREVIEW & RETURN TO LOGIN</Text>
                  </Pressable>
                </View>
              ) : null}

              <Text style={styles.label}>EMAIL</Text>
              <TextInput
                testID="login-email-input"
                style={styles.input}
                value={email}
                onChangeText={setEmail}
                keyboardType="email-address"
                autoCapitalize="none"
                placeholder="you@airline.com"
                placeholderTextColor={theme.color.textDim}
              />
              <Text style={styles.label}>PASSWORD</Text>
              <TextInput
                testID="login-password-input"
                style={styles.input}
                value={password}
                onChangeText={setPassword}
                secureTextEntry
                placeholder="••••••••"
                placeholderTextColor={theme.color.textDim}
              />
              {err && <Text style={styles.err} testID="login-error">{err}</Text>}

              <Pressable
                testID="signin-submit"
                accessibilityLabel="SIGN IN"
                onPress={submit}
                disabled={loading}
                style={({ pressed }) => [
                  styles.cta,
                  pressed && { backgroundColor: theme.color.brandDark },
                  loading && { opacity: 0.6 },
                ]}
              >
                {loading ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <Text style={styles.ctaText}>SIGN IN</Text>
                )}
              </Pressable>

              {/* Iter200 · Google + Apple sign-in. Google is available
                * on every platform; Apple auto-hides on non-iOS and
                * on iOS < 13. Neither button changes the destination
                * screen — the root-layout gate redirects to home the
                * moment auth state resolves. */}
              <SocialButtons busy={loading} ctaCopy="Sign in" />

              {/* Forgot Password — routes to a simple support screen. Once a
                * public email-based reset flow is wired (Resend integration),
                * point this at /(auth)/forgot-password with an email input. */}
              <Pressable
                testID="login-forgot-password"
                onPress={() => router.push("/(auth)/forgot-password")}
                hitSlop={6}
                style={styles.forgotRow}
              >
                <Text style={styles.forgotLink}>Forgot password?</Text>
              </Pressable>

              <Pressable
                testID="login-signup-link"
                onPress={() => router.push("/(auth)/signup")}
                style={styles.linkRow}
              >
                <Text style={styles.linkDim}>New crew?</Text>
                <Text style={styles.link}> Create account</Text>
              </Pressable>

              <Text style={styles.betaLine} testID="login-beta-line">
                Private beta access only.
              </Text>

              {/* Iter 95b — Public Privacy + Support links for App Store review. */}
              <View style={styles.publicLinksRow} testID="login-public-links">
                <Pressable
                  onPress={() => Linking.openURL(PUBLIC_URLS.privacy)}
                  testID="login-privacy-public-link"
                  hitSlop={8}
                >
                  <Text style={styles.publicLink}>Privacy Policy</Text>
                </Pressable>
                <Text style={styles.publicSep}>·</Text>
                <Pressable
                  onPress={() => Linking.openURL(PUBLIC_URLS.support)}
                  testID="login-support-public-link"
                  hitSlop={8}
                >
                  <Text style={styles.publicLink}>Support</Text>
                </Pressable>
              </View>

              {/* Iter 94l — Louis's dev quick-login is now gated behind the
                * EXPO_PUBLIC_SHOW_DEMO_LOGIN_SHORTCUTS flag (default OFF).
                * Set it in the frontend .env only for local dev. Never leave
                * it enabled in beta/TestFlight/production. Public login screen
                * no longer displays any demo credentials or admin shortcuts. */}
              {process.env.EXPO_PUBLIC_SHOW_DEMO_LOGIN_SHORTCUTS === "true" && __DEV__ && (
                <Pressable
                  testID="dev-coach-login"
                  onPress={async () => {
                    setErr(null);
                    if (preview.active) {
                      try { await exitPreview(); } catch {}
                    }
                    setLoading(true);
                    try {
                      // Iter 122e — no hardcoded credentials in source. The
                      // DEV shortcut reads them from EXPO_PUBLIC_DEV_LOGIN_*
                      // env vars (never populated in production builds).
                      const devEmail = process.env.EXPO_PUBLIC_DEV_LOGIN_EMAIL || "";
                      const devPass  = process.env.EXPO_PUBLIC_DEV_LOGIN_PASSWORD || "";
                      if (!devEmail || !devPass) {
                        setErr("Dev login env vars not set.");
                        return;
                      }
                      const u = await login(devEmail, devPass);
                      if (u.role === "coach") {
                        router.replace("/(coach)/v2-home");
                      } else {
                        router.replace("/(client)/home");
                      }
                    } catch (e: any) {
                      setErr(errMsg(e));
                    } finally {
                      setLoading(false);
                    }
                  }}
                  style={styles.devBtn}
                >
                  <Text style={styles.devBtnT}>◈ DEV LOGIN</Text>
                </Pressable>
              )}
            </View>
          </ScrollView>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  bg: { position: "absolute", top: 0, left: 0, right: 0, height: 380 },
  scroll: { flexGrow: 1, padding: theme.space.lg, justifyContent: "space-between" },
  top: { marginTop: theme.space.xl, alignItems: "center" },
  brand: { color: theme.color.text, fontSize: 40, fontWeight: "900", letterSpacing: 4 },
  tag: { color: theme.color.brand, letterSpacing: 3, marginTop: 8, fontSize: 11, fontWeight: "700", textAlign: "center" },
  card: {
    backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.lg,
    padding: theme.space.xl,
    borderWidth: 1,
    borderColor: theme.color.border,
    marginTop: theme.space.xxl,
  },
  h1: { color: theme.color.text, fontSize: 24, fontWeight: "800" },
  sub: { color: theme.color.textMuted, marginTop: 4, marginBottom: theme.space.lg },
  label: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1.5, marginTop: theme.space.md, marginBottom: theme.space.xs, fontWeight: "700" },
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
  err: { color: theme.color.red, marginTop: theme.space.md, fontSize: 13 },
  cta: {
    backgroundColor: theme.color.brand,
    marginTop: theme.space.xl,
    paddingVertical: 16,
    borderRadius: theme.radius.md,
    alignItems: "center",
  },
  ctaText: { color: "#fff", fontWeight: "800", letterSpacing: 2, fontSize: 14 },
  linkRow: { flexDirection: "row", justifyContent: "center", marginTop: theme.space.lg },
  linkDim: { color: theme.color.textMuted },
  link: { color: theme.color.brand, fontWeight: "700" },
  forgotRow: {
    marginTop: theme.space.md,
    alignItems: "center",
    paddingVertical: 6,
  },
  forgotLink: {
    color: theme.color.textMuted,
    fontSize: 13,
    fontWeight: "600",
    textDecorationLine: "underline",
  },
  publicLinksRow: {
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    gap: 10,
    marginTop: 10,
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
  betaLine: {
    marginTop: theme.space.xl, textAlign: "center",
    color: theme.color.textMuted, fontSize: 11, fontStyle: "italic",
  },
  seedBox: {
    marginTop: theme.space.xl,
    padding: theme.space.md,
    borderRadius: theme.radius.sm,
    backgroundColor: theme.color.surface3,
    borderLeftWidth: 3,
    borderLeftColor: theme.color.brand,
  },
  seedTitle: { color: theme.color.brand, fontSize: 11, letterSpacing: 2, fontWeight: "700" },
  seedText: { color: theme.color.textMuted, fontSize: 12, marginTop: 4 },
  devBtn: {
    marginTop: theme.space.md,
    padding: theme.space.md,
    borderRadius: theme.radius.sm,
    borderWidth: 1,
    borderColor: theme.color.brand,
    borderStyle: "dashed",
    alignItems: "center",
    backgroundColor: "transparent",
  },
  devBtnT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  previewNotice: { marginTop: 12, padding: 12, borderRadius: theme.radius.md, borderWidth: 1, borderColor: "#e5a337", backgroundColor: "rgba(229,163,55,0.10)" },
  previewNoticeT: { color: "#e5a337", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  previewNoticeS: { color: theme.color.text, fontSize: 12, marginTop: 6, lineHeight: 17 },
  previewNoticeBtn: { marginTop: 10, paddingVertical: 10, paddingHorizontal: 12, borderRadius: theme.radius.md, backgroundColor: "#e5a337", alignItems: "center" },
  previewNoticeBtnT: { color: "#000", fontSize: 11, fontWeight: "900", letterSpacing: 1.2 },
});
