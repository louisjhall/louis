import { useState } from "react";
import {
  View, Text, TextInput, Pressable, StyleSheet, KeyboardAvoidingView, Platform,
  ScrollView, ActivityIndicator, useWindowDimensions,
} from "react-native";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { useAuth } from "@/src/lib/auth";
import { theme } from "@/src/lib/theme";
import { CrewFitLogo } from "@/src/components/Logo";

const HERO = "https://images.unsplash.com/photo-1687992176093-6417a93fa3d0?crop=entropy&cs=srgb&fm=jpg&q=85";

export default function Login() {
  const { login } = useAuth();
  const router = useRouter();
  const { width } = useWindowDimensions();
  const isDesktopWeb = Platform.OS === "web" && width >= 1024;
  const [email, setEmail] = useState("client@crewfit.com");
  const [password, setPassword] = useState("Client123!");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    setErr(null);
    setLoading(true);
    try {
      const u = await login(email.trim(), password);
      if (u.role === "coach") router.replace(isDesktopWeb ? "/(coach)/overview" : "/(coach)/clients");
      else if (!u.onboarded) router.replace("/(auth)/onboarding");
      else router.replace("/(client)/home");
    } catch (e: any) {
      setErr(e.message || "Login failed");
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
                testID="login-submit-button"
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

              <Pressable
                testID="login-signup-link"
                onPress={() => router.push("/(auth)/signup")}
                style={styles.linkRow}
              >
                <Text style={styles.linkDim}>New crew?</Text>
                <Text style={styles.link}> Create account</Text>
              </Pressable>

              <View style={styles.seedBox}>
                <Text style={styles.seedTitle}>DEMO LOGINS</Text>
                <Text style={styles.seedText}>client@crewfit.com / Client123!</Text>
                <Text style={styles.seedText}>coach@crewfit.com / Coach123!</Text>
              </View>
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
  seedBox: {
    marginTop: theme.space.xl,
    padding: theme.space.md,
    borderRadius: theme.radius.sm,
    backgroundColor: theme.color.surface3,
    borderLeftWidth: 3,
    borderLeftColor: theme.color.brand,
  },
  seedTitle: { color: theme.color.brand, fontSize: 10, letterSpacing: 2, fontWeight: "700" },
  seedText: { color: theme.color.textMuted, fontSize: 12, marginTop: 4 },
});
