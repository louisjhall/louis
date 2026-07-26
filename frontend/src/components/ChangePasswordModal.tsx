/**
 * ChangePasswordModal
 * -------------------
 * Lets a signed-in client update their password from Profile without
 * needing a coach or reset link. Reuses the coach-styled modal shell for
 * consistency with the rest of the settings UI.
 *
 * Backend: POST /api/auth/change-password
 *   body: { current_password, new_password }
 *   resp: { status: "ok", token }  (fresh token so the session keeps going)
 */
import React, { useState } from "react";
import {
  View, Text, StyleSheet, Modal, Pressable, TextInput,
  ActivityIndicator, Platform, KeyboardAvoidingView,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api, setToken } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast as uxToast } from "@/src/lib/ux";

export function ChangePasswordModal({
  visible,
  onClose,
}: {
  visible: boolean;
  onClose: () => void;
}) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const nextValid = next.trim().length >= 6;
  const confirmValid = confirm === next && confirm.length > 0;
  const canSubmit = current.length > 0 && nextValid && confirmValid && !busy;

  const reset = () => {
    setCurrent(""); setNext(""); setConfirm(""); setError(null); setBusy(false);
  };
  const handleClose = () => { reset(); onClose(); };

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api<any>("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({
          current_password: current,
          new_password: next,
        }),
      });
      if (r?.token) {
        // Rotate token silently so the session keeps working.
        await setToken(r.token);
      }
      uxToast("Password updated");
      handleClose();
    } catch (e: any) {
      const msg = String(e?.message || e || "Couldn't change password");
      setError(msg.length > 120 ? "Couldn't change password — check current password" : msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={handleClose}>
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={{ flex: 1 }}
      >
        <View style={styles.backdrop}>
          <View style={styles.sheet}>
            <View style={styles.head}>
              <View style={{ flex: 1 }}>
                <Text style={styles.brand}>SECURITY</Text>
                <Text style={styles.title}>Change your password</Text>
              </View>
              <Pressable onPress={handleClose} hitSlop={10} style={styles.close} testID="pw-close">
                <Ionicons name="close" size={20} color={theme.color.text} />
              </Pressable>
            </View>

            <Field label="Current password">
              <TextInput
                value={current}
                onChangeText={setCurrent}
                placeholder="Your current password"
                placeholderTextColor={theme.color.textDim}
                style={styles.input}
                secureTextEntry
                autoCapitalize="none"
                autoCorrect={false}
                testID="pw-current"
              />
            </Field>

            <Field
              label="New password"
              hint="At least 6 characters"
              error={next.length > 0 && !nextValid ? "Too short" : undefined}
            >
              <TextInput
                value={next}
                onChangeText={setNext}
                placeholder="New password"
                placeholderTextColor={theme.color.textDim}
                style={styles.input}
                secureTextEntry
                autoCapitalize="none"
                autoCorrect={false}
                testID="pw-new"
              />
            </Field>

            <Field
              label="Confirm new password"
              error={confirm.length > 0 && !confirmValid ? "Doesn&apos;t match" : undefined}
            >
              <TextInput
                value={confirm}
                onChangeText={setConfirm}
                placeholder="Re-enter new password"
                placeholderTextColor={theme.color.textDim}
                style={styles.input}
                secureTextEntry
                autoCapitalize="none"
                autoCorrect={false}
                testID="pw-confirm"
              />
            </Field>

            {error ? (
              <View style={styles.errBox}>
                <Ionicons name="alert-circle" size={14} color={theme.color.red} />
                <Text style={styles.errT}>{error}</Text>
              </View>
            ) : null}

            <Pressable
              onPress={submit}
              disabled={!canSubmit}
              style={[styles.submit, !canSubmit && { opacity: 0.5 }]}
              testID="pw-submit"
            >
              {busy ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <>
                  <Ionicons name="checkmark-circle" size={16} color="#fff" />
                  <Text style={styles.submitT}>UPDATE PASSWORD</Text>
                </>
              )}
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}


function Field({
  label, hint, error, children,
}: {
  label: string; hint?: string; error?: string; children: React.ReactNode;
}) {
  return (
    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{label.toUpperCase()}</Text>
      {children}
      {hint && !error ? <Text style={styles.hint}>{hint}</Text> : null}
      {error ? <Text style={styles.err}>{error}</Text> : null}
    </View>
  );
}


const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.6)",
    justifyContent: "flex-end",
  },
  sheet: {
    backgroundColor: theme.color.surface,
    borderTopLeftRadius: 18,
    borderTopRightRadius: 18,
    paddingHorizontal: 16,
    paddingTop: 14,
    paddingBottom: 30,
    borderTopWidth: 1,
    borderColor: theme.color.border,
  },
  head: {
    flexDirection: "row",
    alignItems: "flex-start",
    marginBottom: 14,
  },
  brand: {
    color: theme.color.brand,
    fontSize: 11,
    fontWeight: "900",
    letterSpacing: 2,
  },
  title: {
    color: theme.color.text,
    fontSize: 18,
    fontWeight: "900",
    marginTop: 3,
  },
  close: {
    padding: 6,
    borderRadius: 8,
    backgroundColor: theme.color.surface2,
    borderWidth: 1,
    borderColor: theme.color.border,
  },
  field: { marginBottom: 12 },
  fieldLabel: {
    color: theme.color.textMuted,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 1.4,
    marginBottom: 5,
  },
  input: {
    backgroundColor: theme.color.surface2,
    borderWidth: 1,
    borderColor: theme.color.border,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: Platform.OS === "ios" ? 12 : 10,
    color: theme.color.text,
    fontSize: 15,
  },
  hint: {
    color: theme.color.textDim,
    fontSize: 11,
    marginTop: 4,
    fontStyle: "italic",
  },
  err: {
    color: theme.color.red,
    fontSize: 11,
    marginTop: 4,
    fontWeight: "700",
  },
  errBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: theme.color.surface2,
    borderColor: theme.color.red,
    borderWidth: 1,
    borderRadius: 10,
    padding: 10,
    marginBottom: 12,
  },
  errT: {
    color: theme.color.red,
    fontSize: 12,
    fontWeight: "700",
    flex: 1,
  },
  submit: {
    marginTop: 6,
    backgroundColor: theme.color.brand,
    borderRadius: 12,
    paddingVertical: 14,
    flexDirection: "row",
    gap: 8,
    alignItems: "center",
    justifyContent: "center",
  },
  submitT: {
    color: "#fff",
    fontSize: 13,
    fontWeight: "900",
    letterSpacing: 1.6,
  },
});
