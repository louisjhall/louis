import { useState } from "react";
import {
  View, Text, TextInput, Pressable, StyleSheet, ScrollView,
  KeyboardAvoidingView, Platform, ActivityIndicator,
} from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useAuth, Role } from "@/src/lib/auth";
import { theme } from "@/src/lib/theme";

export default function Signup() {
  const { signup } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<Role>("client");
  const [ageConfirmed, setAgeConfirmed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const canSubmit = !!name.trim() && !!email.trim() && password.length >= 6 && ageConfirmed && !loading;

  const submit = async () => {
    setErr(null);
    if (!ageConfirmed) {
      setErr("You must confirm you are 16 or older to sign up.");
      return;
    }
    setLoading(true);
    try {
      const u = await signup(email.trim(), password, name.trim(), role, ageConfirmed);
      if (u.role === "coach") router.replace("/(coach)/clients");
      else router.replace("/assessment");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.root}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={{ padding: theme.space.lg }} keyboardShouldPersistTaps="handled">
          <Pressable onPress={() => router.back()} testID="signup-back">
            <Text style={{ color: theme.color.brand, letterSpacing: 2, fontWeight: "700" }}>← BACK</Text>
          </Pressable>

          <Text style={styles.title}>CREATE ACCOUNT</Text>
          <Text style={styles.sub}>Join CrewFit</Text>

          <Text style={styles.label}>NAME</Text>
          <TextInput testID="signup-name-input" style={styles.input} value={name} onChangeText={setName} placeholder="Alex Rivera" placeholderTextColor={theme.color.textDim} />

          <Text style={styles.label}>EMAIL</Text>
          <TextInput testID="signup-email-input" style={styles.input} value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address" placeholder="you@airline.com" placeholderTextColor={theme.color.textDim} />

          <Text style={styles.label}>PASSWORD</Text>
          <TextInput testID="signup-password-input" style={styles.input} value={password} onChangeText={setPassword} secureTextEntry placeholder="min 6 chars" placeholderTextColor={theme.color.textDim} />

          <Text style={styles.label}>ROLE</Text>
          <View style={styles.rolesRow}>
            {(["client", "coach"] as Role[]).map((r) => (
              <Pressable
                key={r}
                testID={`signup-role-${r}`}
                onPress={() => setRole(r)}
                style={[styles.roleBtn, role === r && styles.roleBtnActive]}
              >
                <Text style={[styles.roleText, role === r && { color: "#fff" }]}>{r.toUpperCase()}</Text>
              </Pressable>
            ))}
          </View>

          <Pressable
            testID="signup-age-gate"
            onPress={() => setAgeConfirmed(!ageConfirmed)}
            style={styles.ageRow}
            accessibilityRole="checkbox"
            accessibilityState={{ checked: ageConfirmed }}
          >
            <View style={[styles.checkbox, ageConfirmed && styles.checkboxOn]}>
              {ageConfirmed ? <Ionicons name="checkmark" size={16} color="#fff" /> : null}
            </View>
            <Text style={styles.ageText}>I confirm I am 16 or older.</Text>
          </Pressable>

          {err && <Text style={styles.err} testID="signup-error">{err}</Text>}

          <Pressable testID="signup-submit-button" onPress={submit} disabled={!canSubmit} style={[styles.cta, !canSubmit && { opacity: 0.5 }]}>
            {loading ? <ActivityIndicator color="#fff" /> : <Text style={styles.ctaText}>CREATE ACCOUNT</Text>}
          </Pressable>

          <Text style={styles.legalNote}>
            By continuing you accept our{" "}
            <Text onPress={() => router.push("/legal/terms" as any)} style={styles.legalLink}>Terms</Text>
            {" "}and{" "}
            <Text onPress={() => router.push("/legal/privacy" as any)} style={styles.legalLink}>Privacy Policy</Text>.
          </Text>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  title: { color: theme.color.text, fontSize: 28, fontWeight: "900", marginTop: theme.space.lg, letterSpacing: 2 },
  sub: { color: theme.color.textMuted, marginTop: 4, marginBottom: theme.space.lg },
  label: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1.5, marginTop: theme.space.md, marginBottom: theme.space.xs, fontWeight: "700" },
  input: {
    backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, color: theme.color.text,
    paddingHorizontal: theme.space.md, paddingVertical: 14, borderWidth: 1, borderColor: theme.color.border, fontSize: 16,
  },
  rolesRow: { flexDirection: "row", gap: theme.space.sm },
  roleBtn: {
    flex: 1, paddingVertical: 14, borderRadius: theme.radius.md, alignItems: "center",
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  roleBtnActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  roleText: { color: theme.color.textMuted, fontWeight: "800", letterSpacing: 1.5 },
  ageRow: { flexDirection: "row", alignItems: "center", gap: 12, marginTop: theme.space.lg, paddingVertical: 4, minHeight: 44 },
  checkbox: { width: 24, height: 24, borderRadius: 6, borderWidth: 1.5, borderColor: theme.color.border, alignItems: "center", justifyContent: "center", backgroundColor: theme.color.surface2 },
  checkboxOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  ageText: { color: theme.color.text, fontSize: 14, flex: 1 },
  err: { color: theme.color.red, marginTop: theme.space.md, fontSize: 13 },
  cta: { backgroundColor: theme.color.brand, marginTop: theme.space.xl, paddingVertical: 16, borderRadius: theme.radius.md, alignItems: "center" },
  ctaText: { color: "#fff", fontWeight: "800", letterSpacing: 2, fontSize: 14 },
  legalNote: { color: theme.color.textDim, fontSize: 12, textAlign: "center", marginTop: 16, lineHeight: 18 },
  legalLink: { color: theme.color.brand, fontWeight: "700" },
});
