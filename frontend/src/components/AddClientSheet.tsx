/**
 * AddClientSheet
 * --------------
 * Coach-only modal that mimics the on-device client signup screen inside
 * a "virtual phone" frame. Louis (or any coach) can hand-create a client
 * account when self-service signup fails, then share the credentials.
 *
 * Backend: POST /api/coach/clients/create  (coach auth)
 */
import React, { useMemo, useState } from "react";
import {
  View, Text, StyleSheet, Modal, Pressable, ScrollView, TextInput,
  ActivityIndicator, Platform, KeyboardAvoidingView,
} from "react-native";
import * as Clipboard from "expo-clipboard";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast as uxToast } from "@/src/lib/ux";

type Sex = "male" | "female" | "prefer_not_to_say";

const SEX_OPTIONS: { key: Sex; label: string }[] = [
  { key: "male", label: "Male" },
  { key: "female", label: "Female" },
  { key: "prefer_not_to_say", label: "Prefer not to say" },
];

const ROLE_OPTIONS = [
  "Captain", "First Officer", "Cabin Crew", "Purser",
  "Ground Ops", "Corporate Aviation", "Other",
];


function suggestPassword(email: string): string {
  const base = (email.split("@")[0] || "crewfit").replace(/[^a-zA-Z0-9]/g, "");
  const seed = String(Math.floor(1000 + Math.random() * 9000));
  return `${base.charAt(0).toUpperCase()}${base.slice(1).toLowerCase().slice(0, 6)}${seed}!`;
}


export function AddClientSheet({
  visible,
  onClose,
  onCreated,
}: {
  visible: boolean;
  onClose: () => void;
  onCreated?: (client: any) => void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [age, setAge] = useState("");
  const [sex, setSex] = useState<Sex | null>(null);
  const [jobTitle, setJobTitle] = useState<string | null>(null);
  const [airline, setAirline] = useState("");
  const [homeBase, setHomeBase] = useState("");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [createdCredentials, setCreatedCredentials] = useState<
    { email: string; password: string; name: string } | null
  >(null);

  const emailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
  const pwValid = password.trim().length >= 6;
  const nameValid = (firstName || lastName).trim().length > 0;
  const canSubmit = emailValid && pwValid && nameValid && !submitting;

  const displayName = useMemo(() => {
    return `${firstName.trim()} ${lastName.trim()}`.trim() || email.split("@")[0];
  }, [firstName, lastName, email]);

  const reset = () => {
    setEmail(""); setPassword(""); setFirstName(""); setLastName("");
    setAge(""); setSex(null); setJobTitle(null); setAirline("");
    setHomeBase(""); setNotes(""); setCreatedCredentials(null);
  };

  const handleClose = () => {
    reset();
    onClose();
  };

  const submit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      const payload: any = {
        email: email.trim().toLowerCase(),
        password: password.trim(),
        first_name: firstName.trim() || undefined,
        last_name:  lastName.trim() || undefined,
        name: displayName,
      };
      const parsedAge = parseInt(age, 10);
      if (!Number.isNaN(parsedAge) && parsedAge > 0 && parsedAge < 120) payload.age = parsedAge;
      if (sex) payload.sex = sex;
      if (jobTitle) payload.job_title = jobTitle;
      if (airline.trim())  payload.airline = airline.trim();
      if (homeBase.trim()) payload.home_base = homeBase.trim().toUpperCase();
      if (notes.trim())    payload.notes = notes.trim();

      const r = await api<any>("/coach/clients/create", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      const created = r?.client || r;
      setCreatedCredentials({
        email: payload.email,
        password: payload.password,
        name: displayName,
      });
      uxToast(`✓ ${displayName} added`);
      onCreated?.(created);
    } catch (e: any) {
      const msg = String(e?.message || e || "Couldn't create client");
      uxToast(msg.length > 100 ? "Couldn't create client — check the details" : msg);
    } finally {
      setSubmitting(false);
    }
  };

  const copyCredentials = async () => {
    if (!createdCredentials) return;
    const text =
      `Hi ${createdCredentials.name.split(" ")[0]},\n\n` +
      `Your CrewFit account is ready. Log in with:\n\n` +
      `Email: ${createdCredentials.email}\n` +
      `Password: ${createdCredentials.password}\n\n` +
      `Please change your password in Profile once you're in.\n\n— Louis`;
    try {
      await Clipboard.setStringAsync(text);
      uxToast("Copied to clipboard — paste into WhatsApp/email");
    } catch {
      uxToast("Copy failed");
    }
  };

  // ---- Success view ----
  if (createdCredentials) {
    return (
      <Modal visible={visible} animationType="slide" transparent onRequestClose={handleClose}>
        <View style={styles.backdrop}>
          <View style={styles.phoneFrame}>
            <View style={styles.notch} />
            <View style={styles.phoneScreenSuccess}>
              <View style={styles.successIcon}>
                <Ionicons name="checkmark-circle" size={72} color={theme.color.green} />
              </View>
              <Text style={styles.successTitle}>Client added</Text>
              <Text style={styles.successSub}>
                {createdCredentials.name} can now log in with these details:
              </Text>

              <View style={styles.credBox}>
                <Text style={styles.credLabel}>EMAIL</Text>
                <Text style={styles.credValue}>{createdCredentials.email}</Text>
                <View style={styles.credDivider} />
                <Text style={styles.credLabel}>PASSWORD</Text>
                <Text style={styles.credValue}>{createdCredentials.password}</Text>
              </View>

              <Pressable style={styles.copyBtn} onPress={copyCredentials} testID="copy-credentials">
                <Ionicons name="copy" size={16} color="#fff" />
                <Text style={styles.copyBtnT}>COPY WELCOME MESSAGE</Text>
              </Pressable>

              <View style={{ height: 12 }} />
              <Pressable style={styles.ghostBtn} onPress={handleClose} testID="add-client-done">
                <Text style={styles.ghostBtnT}>DONE</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    );
  }

  // ---- Signup form view ----
  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={handleClose}>
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={{ flex: 1 }}
      >
        <View style={styles.backdrop}>
          <View style={styles.phoneFrame}>
            <View style={styles.notch} />
            <ScrollView
              style={styles.phoneScreen}
              contentContainerStyle={{ paddingBottom: 30 }}
              showsVerticalScrollIndicator={false}
              keyboardShouldPersistTaps="handled"
            >
              <View style={styles.head}>
                <Pressable onPress={handleClose} hitSlop={10} testID="add-client-close" style={styles.headClose}>
                  <Ionicons name="close" size={20} color={theme.color.text} />
                </Pressable>
                <View style={{ flex: 1, alignItems: "center" }}>
                  <Text style={styles.crewBrand}>CREWFIT</Text>
                  <Text style={styles.crewBrandSub}>NEW CLIENT · COACH SETUP</Text>
                </View>
                <View style={{ width: 32 }} />
              </View>

              <Text style={styles.formTitle}>Create their account</Text>
              <Text style={styles.formSub}>
                Fill in the essentials — they&apos;ll finish onboarding on-device.
              </Text>

              {/* ---- Required ---- */}
              <Text style={styles.section}>ESSENTIALS</Text>

              <Field label="First name" required>
                <TextInput
                  value={firstName}
                  onChangeText={setFirstName}
                  placeholder="Pietro"
                  placeholderTextColor={theme.color.textDim}
                  style={styles.input}
                  autoCapitalize="words"
                  testID="ac-firstname"
                />
              </Field>

              <Field label="Last name">
                <TextInput
                  value={lastName}
                  onChangeText={setLastName}
                  placeholder="Sangermano"
                  placeholderTextColor={theme.color.textDim}
                  style={styles.input}
                  autoCapitalize="words"
                  testID="ac-lastname"
                />
              </Field>

              <Field label="Email" required error={email.length > 0 && !emailValid ? "Invalid email" : undefined}>
                <TextInput
                  value={email}
                  onChangeText={setEmail}
                  placeholder="pietrosangermano1992@hotmail.com"
                  placeholderTextColor={theme.color.textDim}
                  style={styles.input}
                  autoCapitalize="none"
                  keyboardType="email-address"
                  autoCorrect={false}
                  testID="ac-email"
                />
              </Field>

              <Field
                label="Temporary password"
                required
                error={password.length > 0 && !pwValid ? "Min 6 characters" : undefined}
                rightAction={
                  <Pressable
                    onPress={() => setPassword(suggestPassword(email || "crewfit"))}
                    hitSlop={6}
                    testID="ac-suggest-pw"
                  >
                    <Text style={styles.suggestT}>SUGGEST</Text>
                  </Pressable>
                }
              >
                <TextInput
                  value={password}
                  onChangeText={setPassword}
                  placeholder="e.g. CrewFit2026!"
                  placeholderTextColor={theme.color.textDim}
                  style={styles.input}
                  autoCapitalize="none"
                  autoCorrect={false}
                  testID="ac-password"
                />
              </Field>

              {/* ---- Optional ---- */}
              <Text style={styles.section}>ROSTER CONTEXT · OPTIONAL</Text>

              <View style={styles.row2}>
                <View style={{ flex: 1 }}>
                  <Field label="Age">
                    <TextInput
                      value={age}
                      onChangeText={setAge}
                      placeholder="34"
                      placeholderTextColor={theme.color.textDim}
                      style={styles.input}
                      keyboardType="number-pad"
                      testID="ac-age"
                    />
                  </Field>
                </View>
                <View style={{ flex: 1 }}>
                  <Field label="Home base">
                    <TextInput
                      value={homeBase}
                      onChangeText={setHomeBase}
                      placeholder="LHR"
                      placeholderTextColor={theme.color.textDim}
                      style={styles.input}
                      autoCapitalize="characters"
                      maxLength={4}
                      testID="ac-homebase"
                    />
                  </Field>
                </View>
              </View>

              <Field label="Sex">
                <View style={styles.chipRow}>
                  {SEX_OPTIONS.map((o) => (
                    <Pressable
                      key={o.key}
                      onPress={() => setSex(o.key)}
                      style={[styles.chip, sex === o.key && styles.chipOn]}
                      testID={`ac-sex-${o.key}`}
                    >
                      <Text style={[styles.chipT, sex === o.key && styles.chipOnT]}>{o.label}</Text>
                    </Pressable>
                  ))}
                </View>
              </Field>

              <Field label="Role">
                <View style={styles.chipRow}>
                  {ROLE_OPTIONS.map((o) => (
                    <Pressable
                      key={o}
                      onPress={() => setJobTitle(o === jobTitle ? null : o)}
                      style={[styles.chip, jobTitle === o && styles.chipOn]}
                      testID={`ac-role-${o}`}
                    >
                      <Text style={[styles.chipT, jobTitle === o && styles.chipOnT]}>{o}</Text>
                    </Pressable>
                  ))}
                </View>
              </Field>

              <Field label="Airline">
                <TextInput
                  value={airline}
                  onChangeText={setAirline}
                  placeholder="British Airways"
                  placeholderTextColor={theme.color.textDim}
                  style={styles.input}
                  autoCapitalize="words"
                  testID="ac-airline"
                />
              </Field>

              <Field label="Notes (for the audit log)">
                <TextInput
                  value={notes}
                  onChangeText={setNotes}
                  placeholder="e.g. Signup failed — created manually"
                  placeholderTextColor={theme.color.textDim}
                  style={[styles.input, { minHeight: 44 }]}
                  multiline
                  testID="ac-notes"
                />
              </Field>

              {/* ---- Submit ---- */}
              <Pressable
                onPress={submit}
                disabled={!canSubmit}
                style={[styles.submitBtn, !canSubmit && { opacity: 0.5 }]}
                testID="ac-submit"
              >
                {submitting ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <>
                    <Ionicons name="person-add" size={16} color="#fff" />
                    <Text style={styles.submitBtnT}>CREATE ACCOUNT</Text>
                  </>
                )}
              </Pressable>

              <Text style={styles.footNote}>
                By creating this account you confirm the client is 16+. This is recorded in the audit log.
              </Text>
            </ScrollView>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}


function Field({
  label, required, error, rightAction, children,
}: {
  label: string; required?: boolean; error?: string;
  rightAction?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <View style={styles.field}>
      <View style={styles.fieldHead}>
        <Text style={styles.fieldLabel}>
          {label.toUpperCase()}{required ? " *" : ""}
        </Text>
        {rightAction}
      </View>
      {children}
      {error ? <Text style={styles.fieldError}>{error}</Text> : null}
    </View>
  );
}


const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.7)",
    justifyContent: "center",
    alignItems: "center",
    padding: 12,
  },
  phoneFrame: {
    width: "100%",
    maxWidth: 420,
    height: "94%",
    backgroundColor: "#101012",
    borderRadius: 40,
    borderWidth: 6,
    borderColor: "#1a1a1e",
    padding: 8,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.6,
    shadowRadius: 30,
    elevation: 30,
    overflow: "hidden",
  },
  notch: {
    position: "absolute",
    top: 12,
    alignSelf: "center",
    width: 100,
    height: 22,
    borderRadius: 12,
    backgroundColor: "#000",
    zIndex: 2,
  },
  phoneScreen: {
    flex: 1,
    backgroundColor: theme.color.surface,
    borderRadius: 30,
    paddingHorizontal: 16,
    paddingTop: 44,
  },
  phoneScreenSuccess: {
    flex: 1,
    backgroundColor: theme.color.surface,
    borderRadius: 30,
    padding: 24,
    paddingTop: 60,
    alignItems: "center",
    justifyContent: "flex-start",
  },
  head: {
    flexDirection: "row",
    alignItems: "center",
    marginBottom: 20,
  },
  headClose: {
    padding: 6,
    borderRadius: 8,
    backgroundColor: theme.color.surface2,
    borderWidth: 1,
    borderColor: theme.color.border,
    width: 32,
    height: 32,
    alignItems: "center",
    justifyContent: "center",
  },
  crewBrand: {
    color: theme.color.brand,
    fontSize: 14,
    fontWeight: "900",
    letterSpacing: 3,
  },
  crewBrandSub: {
    color: theme.color.textDim,
    fontSize: 9,
    fontWeight: "800",
    letterSpacing: 1.5,
    marginTop: 2,
  },
  formTitle: {
    color: theme.color.text,
    fontSize: 22,
    fontWeight: "900",
    marginBottom: 4,
  },
  formSub: {
    color: theme.color.textMuted,
    fontSize: 13,
    lineHeight: 18,
    marginBottom: 16,
  },
  section: {
    color: theme.color.brand,
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 2,
    marginTop: 14,
    marginBottom: 8,
  },
  field: { marginBottom: 12 },
  fieldHead: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 4,
  },
  fieldLabel: {
    color: theme.color.textMuted,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 1.4,
  },
  suggestT: {
    color: theme.color.brand,
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 1.4,
  },
  input: {
    backgroundColor: theme.color.surface2,
    borderWidth: 1,
    borderColor: theme.color.border,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: Platform.OS === "ios" ? 12 : 8,
    color: theme.color.text,
    fontSize: 15,
  },
  fieldError: {
    color: theme.color.red,
    fontSize: 11,
    marginTop: 3,
    fontWeight: "700",
  },
  row2: {
    flexDirection: "row",
    gap: 10,
  },
  chipRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
  },
  chip: {
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: theme.color.border,
    backgroundColor: theme.color.surface2,
  },
  chipOn: {
    borderColor: theme.color.brand,
    backgroundColor: theme.color.brandTint,
  },
  chipT: {
    color: theme.color.textMuted,
    fontSize: 12,
    fontWeight: "700",
  },
  chipOnT: {
    color: theme.color.brand,
    fontWeight: "800",
  },
  submitBtn: {
    marginTop: 20,
    backgroundColor: theme.color.brand,
    borderRadius: 12,
    paddingVertical: 14,
    flexDirection: "row",
    gap: 8,
    alignItems: "center",
    justifyContent: "center",
  },
  submitBtnT: {
    color: "#fff",
    fontSize: 13,
    fontWeight: "900",
    letterSpacing: 1.8,
  },
  footNote: {
    color: theme.color.textDim,
    fontSize: 11,
    lineHeight: 16,
    textAlign: "center",
    marginTop: 12,
  },

  // ---- Success view ----
  successIcon: {
    marginBottom: 12,
  },
  successTitle: {
    color: theme.color.text,
    fontSize: 24,
    fontWeight: "900",
    marginBottom: 6,
    textAlign: "center",
  },
  successSub: {
    color: theme.color.textMuted,
    fontSize: 13,
    textAlign: "center",
    marginBottom: 20,
  },
  credBox: {
    width: "100%",
    backgroundColor: theme.color.surface2,
    borderRadius: 14,
    padding: 16,
    borderWidth: 1,
    borderColor: theme.color.border,
    marginBottom: 16,
  },
  credLabel: {
    color: theme.color.textMuted,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 1.5,
    marginBottom: 4,
  },
  credValue: {
    color: theme.color.text,
    fontSize: 16,
    fontWeight: "800",
    fontFamily: Platform.select({ ios: "Menlo", android: "monospace" }),
    marginBottom: 4,
  },
  credDivider: {
    height: 1,
    backgroundColor: theme.color.border,
    marginVertical: 8,
  },
  copyBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    backgroundColor: theme.color.brand,
    paddingVertical: 12,
    paddingHorizontal: 18,
    borderRadius: 10,
    alignSelf: "stretch",
  },
  copyBtnT: {
    color: "#fff",
    fontSize: 12,
    fontWeight: "900",
    letterSpacing: 1.6,
  },
  ghostBtn: {
    borderWidth: 1,
    borderColor: theme.color.border,
    paddingVertical: 12,
    paddingHorizontal: 18,
    borderRadius: 10,
    alignSelf: "stretch",
    alignItems: "center",
  },
  ghostBtnT: {
    color: theme.color.textMuted,
    fontSize: 12,
    fontWeight: "800",
    letterSpacing: 1.4,
  },
});
