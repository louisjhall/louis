import React, { useState } from "react";
import { View, Text, ScrollView, StyleSheet, TextInput, Pressable, ActivityIndicator, Alert, Platform } from "react-native";
import { Stack, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { theme } from "../../src/lib/theme";
import { api, API_BASE, getToken } from "../../src/lib/api";
import { confirm as uxConfirm, toast as uxToast } from "../../src/lib/ux";

export default function DeleteAccount() {
  const [confirmText, setConfirmText] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<null | { scheduled_purge_at: string; message: string }>(null);
  const router = useRouter();

  const submit = async () => {
    if (confirmText !== "DELETE") {
      uxToast("Type DELETE to confirm.", "error");
      return;
    }
    const ok = await uxConfirm({
      title: "Delete CrewFit account?",
      message: "You have 30 days to change your mind. After that, all your data is permanently removed.",
      confirmLabel: "Delete my account",
      destructive: true,
    });
    if (!ok) return;
    setBusy(true);
    try {
      const r: any = await api("/gdpr/delete-account", { method: "POST", body: { confirmation: "DELETE", reason } });
      setStatus(r);
      uxToast("Deletion scheduled.", "info");
    } catch (e: any) {
      Alert.alert("Delete failed", e?.message || "Please try again.");
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    setBusy(true);
    try {
      await api("/gdpr/delete-account/cancel", { method: "POST" });
      setStatus(null);
      uxToast("Deletion cancelled.", "info");
    } catch (e: any) {
      Alert.alert("Cancel failed", e?.message || "Please try again.");
    } finally {
      setBusy(false);
    }
  };

  const exportData = async () => {
    setBusy(true);
    try {
      const token = await getToken();
      if (Platform.OS === "web") {
        const res = await fetch(`${API_BASE}/gdpr/export`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `crewfit-export-${Date.now()}.json`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
        uxToast("Export downloaded.", "info");
      } else {
        // Native: open the URL — the platform will offer share/save.
        const { Linking } = require("react-native");
        const url = `${API_BASE}/gdpr/export?token=${token || ""}`;
        await Linking.openURL(url);
      }
    } catch (e: any) {
      Alert.alert("Export failed", e?.message || "Please try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.wrap} edges={["top", "left", "right"]}>
      <Stack.Screen options={{ title: "Delete Account" }} />
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 60 }}>
        <Text style={styles.h1}>Delete My Account</Text>
        <Text style={styles.p}>
          Deletion is a two-step process:
          {"\n\n"}
          1. You mark your account for deletion here.{"\n"}
          2. After 30 days, all your data is permanently removed. You can cancel within that window.
        </Text>

        <View style={styles.exportCard}>
          <Text style={styles.label}>Before you go</Text>
          <Text style={styles.p2}>Download a copy of everything CrewFit knows about you — workouts, habits, nutrition, roster, messages — in a single JSON file.</Text>
          <Pressable onPress={exportData} disabled={busy} style={[styles.altBtn, busy && { opacity: 0.5 }]} testID="btn-export">
            <Text style={styles.altT}>EXPORT MY DATA</Text>
          </Pressable>
        </View>

        {status ? (
          <View style={styles.pendingCard}>
            <Text style={styles.pendingT}>Deletion scheduled</Text>
            <Text style={styles.p2}>{status.message}</Text>
            <Text style={styles.p2}>Scheduled purge: {new Date(status.scheduled_purge_at).toLocaleString()}</Text>
            <Pressable onPress={cancel} disabled={busy} style={[styles.altBtn, { marginTop: 12 }, busy && { opacity: 0.5 }]} testID="btn-cancel-delete">
              <Text style={styles.altT}>CANCEL DELETION</Text>
            </Pressable>
          </View>
        ) : (
          <>
            <Text style={styles.label}>Reason (optional)</Text>
            <TextInput
              value={reason}
              onChangeText={setReason}
              placeholder="Help us improve — why are you leaving?"
              placeholderTextColor={theme.color.textDim}
              multiline
              style={styles.textarea}
              testID="delete-reason"
            />

            <Text style={styles.label}>Type DELETE to confirm</Text>
            <TextInput
              value={confirmText}
              onChangeText={setConfirmText}
              placeholder="DELETE"
              placeholderTextColor={theme.color.textDim}
              autoCapitalize="characters"
              style={styles.input}
              testID="delete-confirm"
            />

            <Pressable onPress={submit} disabled={busy || confirmText !== "DELETE"}
              style={[styles.dangerBtn, (busy || confirmText !== "DELETE") && { opacity: 0.4 }]} testID="btn-delete">
              {busy ? <ActivityIndicator color={"#fff"} /> : <Text style={styles.dangerT}>DELETE MY ACCOUNT</Text>}
            </Pressable>
          </>
        )}

        <Pressable onPress={() => router.back()} style={{ marginTop: 24, alignSelf: "center" }}>
          <Text style={styles.link}>Never mind, take me back.</Text>
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: theme.color.surface },
  h1: { color: theme.color.text, fontFamily: theme.font.display, fontSize: 28, marginBottom: 12 },
  p: { color: theme.color.textMuted, fontFamily: theme.font.text, fontSize: 14, lineHeight: 22, marginBottom: 20 },
  p2: { color: theme.color.textMuted, fontFamily: theme.font.text, fontSize: 13, lineHeight: 20, marginBottom: 6 },
  label: { color: theme.color.textMuted, fontFamily: theme.font.textSemi, fontSize: 12, textTransform: "uppercase", letterSpacing: 0.6, marginTop: 16, marginBottom: 6 },
  input: { color: theme.color.text, fontFamily: theme.font.text, fontSize: 16, backgroundColor: theme.color.surface2, borderRadius: 8, padding: 12, borderWidth: 1, borderColor: theme.color.border },
  textarea: { color: theme.color.text, fontFamily: theme.font.text, fontSize: 14, backgroundColor: theme.color.surface2, borderRadius: 8, padding: 12, borderWidth: 1, borderColor: theme.color.border, minHeight: 80, textAlignVertical: "top" },
  exportCard: { backgroundColor: theme.color.surface2, borderRadius: 12, padding: 16, marginBottom: 20, borderWidth: 1, borderColor: theme.color.border },
  pendingCard: { backgroundColor: theme.color.brandTint, borderRadius: 12, padding: 16, marginBottom: 20, borderWidth: 1, borderColor: theme.color.brand },
  pendingT: { color: theme.color.brand, fontFamily: theme.font.textBold, fontSize: 15, marginBottom: 8 },
  altBtn: { padding: 12, borderRadius: 8, borderWidth: 1, borderColor: theme.color.brand, alignItems: "center" },
  altT: { color: theme.color.brand, fontFamily: theme.font.textBold, fontSize: 13, letterSpacing: 0.8 },
  dangerBtn: { padding: 14, borderRadius: 8, backgroundColor: theme.color.brand, alignItems: "center", marginTop: 20 },
  dangerT: { color: "#fff", fontFamily: theme.font.textBold, fontSize: 14, letterSpacing: 0.8 },
  link: { color: theme.color.brand, fontFamily: theme.font.textSemi, fontSize: 14 },
});
