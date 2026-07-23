/**
 * /(auth)/signup — Multi-section signup with full profile capture BEFORE the
 * DNA assessment. All new accounts are clients — coach accounts are only
 * created by Louis (head coach) via the coach onboarding flow.
 *
 * Sections:
 *  1. YOU               — first name, last name, email, password
 *  2. THE BASICS        — age, sex, height (cm), weight (kg)
 *  3. FLYING            — airline, position, home base
 *  4. PHOTO (optional)  — via expo-image-picker
 *  5. Age gate + submit
 */
import { useState } from "react";
import {
  View, Text, TextInput, Pressable, StyleSheet, ScrollView, Image,
  KeyboardAvoidingView, Platform, ActivityIndicator, Linking,
} from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import * as ImagePicker from "expo-image-picker";
import { useAuth } from "@/src/lib/auth";
import { theme } from "@/src/lib/theme";
import { toast } from "@/src/lib/ux";
import { PUBLIC_URLS } from "@/src/lib/publicUrls";

type Sex = "male" | "female" | "other" | "prefer_not_to_say";
const SEX_OPTIONS: { key: Sex; label: string }[] = [
  { key: "male", label: "MALE" },
  { key: "female", label: "FEMALE" },
  { key: "other", label: "OTHER" },
  { key: "prefer_not_to_say", label: "PREFER NOT TO SAY" },
];

const POSITION_OPTIONS = [
  "Cabin Crew",
  "Senior Cabin Crew",
  "Purser",
  "First Officer",
  "Captain",
  "Ground Crew",
  "Other",
];

export default function Signup() {
  const { signup } = useAuth();
  const router = useRouter();

  // Section 1 — YOU
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  // Section 2 — Basics
  const [age, setAge] = useState("");
  const [sex, setSex] = useState<Sex | null>(null);
  const [heightCm, setHeightCm] = useState("");
  const [weightKg, setWeightKg] = useState("");

  // Section 3 — Flying
  const [airline, setAirline] = useState("");
  const [jobTitle, setJobTitle] = useState<string>("");
  const [homeBase, setHomeBase] = useState("");

  // Section 4 — Photo
  const [photoUri, setPhotoUri] = useState<string | null>(null);
  const [photoBase64, setPhotoBase64] = useState<string | null>(null);
  const [photoMime, setPhotoMime] = useState<string>("image/jpeg");

  const [ageConfirmed, setAgeConfirmed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const canSubmit =
    !!firstName.trim() &&
    !!lastName.trim() &&
    !!email.trim() &&
    password.length >= 6 &&
    ageConfirmed &&
    !loading;

  const pickPhoto = async () => {
    try {
      const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) {
        toast("Photo library access denied", "error");
        return;
      }
      const res = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        allowsEditing: true,
        aspect: [1, 1],
        quality: 0.6,
        base64: true,
      });
      if (res.canceled || !res.assets?.[0]) return;
      const a = res.assets[0];
      setPhotoUri(a.uri);
      if (a.base64) setPhotoBase64(a.base64);
      setPhotoMime(a.mimeType || "image/jpeg");
    } catch (e: any) {
      toast(e?.message || "Couldn't pick photo", "error");
    }
  };

  const submit = async () => {
    setErr(null);
    if (!ageConfirmed) {
      setErr("You must confirm you are 16 or older to sign up.");
      return;
    }
    // Light validation — server does the real work
    const ageNum = age ? parseInt(age, 10) : undefined;
    if (ageNum !== undefined && (isNaN(ageNum) || ageNum < 16 || ageNum > 90)) {
      setErr("Please enter a valid age (16-90).");
      return;
    }
    const heightNum = heightCm ? parseFloat(heightCm) : undefined;
    if (heightNum !== undefined && (isNaN(heightNum) || heightNum < 120 || heightNum > 230)) {
      setErr("Please enter a valid height in cm (120-230).");
      return;
    }
    const weightNum = weightKg ? parseFloat(weightKg) : undefined;
    if (weightNum !== undefined && (isNaN(weightNum) || weightNum < 30 || weightNum > 250)) {
      setErr("Please enter a valid weight in kg (30-250).");
      return;
    }
    setLoading(true);
    try {
      const u = await signup({
        email: email.trim(),
        password,
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        age_confirmed: ageConfirmed,
        age: ageNum,
        sex: sex || undefined,
        height_cm: heightNum,
        weight_kg: weightNum,
        airline: airline.trim() || undefined,
        job_title: jobTitle || undefined,
        home_base: homeBase.trim().toUpperCase() || undefined,
        photo_base64: photoBase64 || undefined,
        photo_mime: photoBase64 ? photoMime : undefined,
      });
      // All new signups are clients — head straight to the DNA assessment.
      if (u.role === "coach") router.replace("/(coach)/clients" as any);
      else router.replace("/training-setup" as any);   // Iter 84 (Task 1.3): setup first, then assessment
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.root}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 60 }} keyboardShouldPersistTaps="handled">
          <Pressable onPress={() => router.back()} testID="signup-back">
            <Text style={{ color: theme.color.brand, letterSpacing: 2, fontWeight: "700" }}>← BACK</Text>
          </Pressable>

          <Text style={styles.title}>CREATE ACCOUNT</Text>
          <Text style={styles.sub}>Louis will review your setup and build your programme.</Text>

          {/* ============================= YOU ============================= */}
          <Text style={styles.section}>1 · YOU</Text>

          <View style={{ flexDirection: "row", gap: 8 }}>
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>FIRST NAME</Text>
              <TextInput
                testID="signup-first-name"
                style={styles.input}
                value={firstName}
                onChangeText={setFirstName}
                placeholder="First name"
                placeholderTextColor={theme.color.textDim}
                autoCapitalize="words"
              />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>LAST NAME</Text>
              <TextInput
                testID="signup-last-name"
                style={styles.input}
                value={lastName}
                onChangeText={setLastName}
                placeholder="Last name"
                placeholderTextColor={theme.color.textDim}
                autoCapitalize="words"
              />
            </View>
          </View>

          <Text style={styles.label}>EMAIL</Text>
          <TextInput
            testID="signup-email-input"
            style={styles.input}
            value={email}
            onChangeText={setEmail}
            autoCapitalize="none"
            keyboardType="email-address"
            placeholder="you@airline.com"
            placeholderTextColor={theme.color.textDim}
          />

          <Text style={styles.label}>PASSWORD</Text>
          <TextInput
            testID="signup-password-input"
            style={styles.input}
            value={password}
            onChangeText={setPassword}
            secureTextEntry
            placeholder="min 6 chars"
            placeholderTextColor={theme.color.textDim}
          />

          {/* ============================= BASICS ============================= */}
          <Text style={styles.section}>2 · THE BASICS</Text>

          <View style={{ flexDirection: "row", gap: 8 }}>
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>AGE</Text>
              <TextInput
                testID="signup-age-input"
                style={styles.input}
                value={age}
                onChangeText={(v) => setAge(v.replace(/[^0-9]/g, ""))}
                placeholder="e.g. 28"
                placeholderTextColor={theme.color.textDim}
                keyboardType="numeric"
                maxLength={2}
              />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>HEIGHT (cm)</Text>
              <TextInput
                testID="signup-height-input"
                style={styles.input}
                value={heightCm}
                onChangeText={(v) => setHeightCm(v.replace(/[^0-9.]/g, ""))}
                placeholder="e.g. 172"
                placeholderTextColor={theme.color.textDim}
                keyboardType="numeric"
              />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>WEIGHT (kg)</Text>
              <TextInput
                testID="signup-weight-input"
                style={styles.input}
                value={weightKg}
                onChangeText={(v) => setWeightKg(v.replace(/[^0-9.]/g, ""))}
                placeholder="e.g. 70"
                placeholderTextColor={theme.color.textDim}
                keyboardType="numeric"
              />
            </View>
          </View>

          <Text style={styles.label}>SEX</Text>
          <View style={styles.pillRow}>
            {SEX_OPTIONS.map((o) => (
              <Pressable
                key={o.key}
                testID={`signup-sex-${o.key}`}
                onPress={() => setSex(o.key)}
                style={[styles.pill, sex === o.key && styles.pillActive]}
              >
                <Text style={[styles.pillText, sex === o.key && styles.pillTextActive]}>{o.label}</Text>
              </Pressable>
            ))}
          </View>

          {/* ============================= FLYING ============================= */}
          <Text style={styles.section}>3 · FLYING</Text>

          <Text style={styles.label}>AIRLINE</Text>
          <TextInput
            testID="signup-airline-input"
            style={styles.input}
            value={airline}
            onChangeText={setAirline}
            placeholder="e.g. British Airways, Emirates, Qatar…"
            placeholderTextColor={theme.color.textDim}
            autoCapitalize="words"
          />

          <Text style={styles.label}>POSITION</Text>
          <View style={styles.pillRow}>
            {POSITION_OPTIONS.map((p) => (
              <Pressable
                key={p}
                testID={`signup-position-${p.toLowerCase().replace(/\s+/g, "-")}`}
                onPress={() => setJobTitle(p)}
                style={[styles.pill, jobTitle === p && styles.pillActive]}
              >
                <Text style={[styles.pillText, jobTitle === p && styles.pillTextActive]}>{p.toUpperCase()}</Text>
              </Pressable>
            ))}
          </View>

          <Text style={styles.label}>HOME BASE (airport code)</Text>
          <TextInput
            testID="signup-home-base-input"
            style={styles.input}
            value={homeBase}
            onChangeText={(v) => setHomeBase(v.toUpperCase())}
            placeholder="e.g. LHR, DXB, JFK"
            placeholderTextColor={theme.color.textDim}
            autoCapitalize="characters"
            maxLength={4}
          />

          {/* ============================= PHOTO ============================= */}
          <Text style={styles.section}>4 · PHOTO (OPTIONAL)</Text>

          <Pressable testID="signup-photo-pick" onPress={pickPhoto} style={styles.photoBtn}>
            {photoUri ? (
              <Image source={{ uri: photoUri }} style={styles.photoPreview} />
            ) : (
              <View style={styles.photoPlaceholder}>
                <Ionicons name="camera" size={22} color={theme.color.textMuted} />
                <Text style={styles.photoPlaceholderText}>TAP TO ADD PHOTO</Text>
              </View>
            )}
          </Pressable>
          {photoUri ? (
            <Pressable
              onPress={() => { setPhotoUri(null); setPhotoBase64(null); }}
              style={{ alignSelf: "center", marginTop: 6 }}
              testID="signup-photo-remove"
            >
              <Text style={{ color: theme.color.textMuted, fontSize: 11, letterSpacing: 1 }}>REMOVE PHOTO</Text>
            </Pressable>
          ) : null}

          {/* ============================= AGE GATE + SUBMIT ============================= */}
          <Pressable
            testID="signup-age-gate"
            onPress={() => setAgeConfirmed(!ageConfirmed)}
            style={styles.ageRow}
            accessibilityRole="checkbox"
            accessibilityState={{ checked: ageConfirmed }}
            hitSlop={12}
          >
            <View style={[styles.checkbox, ageConfirmed && styles.checkboxOn]}>
              {ageConfirmed ? <Text style={styles.checkTick}>✓</Text> : null}
            </View>
            <Text style={styles.ageText}>I confirm I am 16 years of age or older.</Text>
          </Pressable>

          {err && <Text style={styles.err} testID="signup-error">{err}</Text>}

          {/* Iter 95b — Health disclaimer BEFORE the CTA. Required for
              App Store / Play Store beta review. Do not remove or hide. */}
          <View style={styles.healthDisclaimer} testID="signup-health-disclaimer">
            <View style={styles.healthDisclaimerHeader}>
              <Ionicons name="medkit-outline" size={16} color={theme.color.brand} />
              <Text style={styles.healthDisclaimerTitle}>Before you continue</Text>
            </View>
            <Text style={styles.healthDisclaimerBody}>
              CrewFit provides fitness, nutrition and lifestyle coaching support.
              It is not medical advice. Speak to a qualified medical professional
              before starting a new programme if you have any medical condition,
              injury or concern.
            </Text>
          </View>

          <Pressable
            testID="signup-submit-button"
            onPress={submit}
            disabled={!canSubmit}
            style={[styles.cta, !canSubmit && { opacity: 0.5 }]}
          >
            {loading ? <ActivityIndicator color="#fff" /> : <Text style={styles.ctaText}>CREATE ACCOUNT</Text>}
          </Pressable>

          <Text style={styles.legalNote}>
            By continuing you accept our{" "}
            <Text
              onPress={() => router.push("/legal/terms" as any)}
              style={styles.legalLink}
              testID="signup-terms-link"
            >Terms</Text>
            {" "}and{" "}
            <Text
              onPress={() => router.push("/legal/privacy" as any)}
              style={styles.legalLink}
              testID="signup-privacy-link"
            >Privacy Policy</Text>.
          </Text>
          <View style={styles.publicLinksRow}>
            <Pressable
              onPress={() => Linking.openURL(PUBLIC_URLS.privacy)}
              testID="signup-privacy-public-link"
              hitSlop={8}
            >
              <Text style={styles.publicLink}>crewfit.net/privacy</Text>
            </Pressable>
            <Text style={styles.publicSep}>·</Text>
            <Pressable
              onPress={() => Linking.openURL(PUBLIC_URLS.support)}
              testID="signup-support-public-link"
              hitSlop={8}
            >
              <Text style={styles.publicLink}>crewfit.net/support</Text>
            </Pressable>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  title: { color: theme.color.text, fontSize: 28, fontWeight: "900", marginTop: theme.space.lg, letterSpacing: 2 },
  sub: { color: theme.color.textMuted, marginTop: 6, marginBottom: theme.space.lg, fontSize: 13, lineHeight: 18 },
  section: {
    color: theme.color.brand, fontSize: 11, letterSpacing: 2, fontWeight: "900",
    marginTop: theme.space.xl, marginBottom: theme.space.xs,
  },
  label: {
    color: theme.color.textMuted, fontSize: 11, letterSpacing: 1.5,
    marginTop: theme.space.md, marginBottom: theme.space.xs, fontWeight: "700",
  },
  input: {
    backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, color: theme.color.text,
    paddingHorizontal: theme.space.md, paddingVertical: 12, borderWidth: 1, borderColor: theme.color.border, fontSize: 15,
  },
  pillRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  pill: {
    paddingHorizontal: 12, paddingVertical: 8,
    borderRadius: 999, backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
  },
  pillActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  pillText: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700", letterSpacing: 0.6 },
  pillTextActive: { color: "#fff" },

  photoBtn: {
    alignSelf: "center", marginTop: theme.space.sm,
    width: 120, height: 120, borderRadius: 60,
    overflow: "hidden",
  },
  photoPreview: { width: 120, height: 120 },
  photoPlaceholder: {
    width: 120, height: 120, borderRadius: 60,
    alignItems: "center", justifyContent: "center",
    backgroundColor: theme.color.surface2,
    borderWidth: 2, borderColor: theme.color.border, borderStyle: "dashed",
    gap: 6,
  },
  photoPlaceholderText: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 1, fontWeight: "700" },

  ageRow: {
    flexDirection: "row", alignItems: "center", gap: 12,
    marginTop: theme.space.xl, paddingVertical: 8, minHeight: 48,
  },
  checkbox: {
    width: 28, height: 28, borderRadius: 6, borderWidth: 2, borderColor: theme.color.textMuted,
    alignItems: "center", justifyContent: "center", backgroundColor: theme.color.surface2,
  },
  checkboxOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  checkTick: { color: "#fff", fontSize: 18, fontWeight: "900", lineHeight: 20 },
  ageText: { color: theme.color.text, fontSize: 15, flex: 1, lineHeight: 21 },

  err: { color: theme.color.red, marginTop: theme.space.md, fontSize: 13 },

  // Iter 95b — Health disclaimer above signup CTA
  healthDisclaimer: {
    marginTop: theme.space.lg,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.color.border,
    backgroundColor: theme.color.surface2,
    padding: 14,
  },
  healthDisclaimerHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginBottom: 6,
  },
  healthDisclaimerTitle: {
    color: theme.color.brand,
    fontSize: 12,
    fontWeight: "800",
    letterSpacing: 1,
  },
  healthDisclaimerBody: {
    color: theme.color.text,
    fontSize: 13,
    lineHeight: 19,
  },

  cta: {
    backgroundColor: theme.color.brand, marginTop: theme.space.xl,
    paddingVertical: 16, borderRadius: theme.radius.md, alignItems: "center",
  },
  ctaText: { color: "#fff", fontWeight: "800", letterSpacing: 2, fontSize: 14 },
  legalNote: { color: theme.color.textDim, fontSize: 12, textAlign: "center", marginTop: 16, lineHeight: 18 },
  legalLink: { color: theme.color.brand, fontWeight: "700" },
  publicLinksRow: {
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    gap: 8,
    marginTop: 6,
    marginBottom: 4,
  },
  publicLink: {
    color: theme.color.textDim,
    fontSize: 11,
    textDecorationLine: "underline",
    fontWeight: "500",
  },
  publicSep: {
    color: theme.color.textDim,
    fontSize: 11,
  },
});
