/**
 * PreviewBanner — red banner shown at the top of the client app whenever
 * a coach is impersonating. Provides an "EXIT PREVIEW" button and a small
 * device-size selector on web.
 */
import React, { useState } from "react";
import { View, Text, Pressable, StyleSheet, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { usePreview } from "@/src/lib/preview";
import { UIIssueReporter } from "./UIIssueReporter";
import { DeviceSizePicker } from "./DeviceSizePicker";

export function PreviewBanner() {
  const { preview, exit, resetSandbox } = usePreview();
  const router = useRouter();
  const [showIssue, setShowIssue] = useState(false);
  const [busy, setBusy] = useState(false);

  if (!preview.active) return null;

  const isSandbox = preview.mode === "sandbox" || preview.mode === "new_client";
  const label = preview.mode === "demo"
    ? "Demo aviation client"
    : preview.mode === "sandbox"
    ? "New Client Preview — resettable sandbox"
    : preview.mode === "new_client"
    ? "New-client onboarding preview"
    : `Viewing ${preview.target?.name || "client"} as client`;

  const handleExit = async () => {
    if (isSandbox && typeof window !== "undefined" && Platform.OS === "web") {
      // Ask if they want to reset before exiting.
      const doReset = window.confirm("Reset this preview client before exiting?\n\nOK = Reset + Exit\nCancel = Keep progress + Exit");
      if (doReset) {
        setBusy(true);
        try { await resetSandbox(); } catch {}
        setBusy(false);
      }
    }
    await exit();
    router.replace("/(coach)/overview" as any);
  };

  const handleReset = async () => {
    setBusy(true);
    try {
      await resetSandbox();
      // resetSandbox already re-enters the sandbox with a fresh token.
      router.replace("/" as any);
    } catch {}
    setBusy(false);
  };

  return (
    <View style={styles.wrap} testID="preview-banner">
      <View style={styles.row}>
        <View style={styles.left}>
          <View style={styles.dot} />
          <Text style={styles.title}>COACH PREVIEW MODE</Text>
        </View>
        <View style={styles.right}>
          {Platform.OS === "web" ? <DeviceSizePicker /> : null}
          {isSandbox ? (
            <Pressable onPress={handleReset} disabled={busy} style={styles.iconBtn} testID="preview-reset">
              <Ionicons name="refresh" size={14} color="#fff" />
              <Text style={styles.iconBtnT}>RESET</Text>
            </Pressable>
          ) : null}
          <Pressable onPress={() => setShowIssue(true)} style={styles.iconBtn} testID="preview-report-issue">
            <Ionicons name="bug" size={14} color="#fff" />
            <Text style={styles.iconBtnT}>ISSUE</Text>
          </Pressable>
          <Pressable onPress={handleExit} disabled={busy} style={[styles.iconBtn, styles.exitBtn]} testID="preview-exit">
            <Ionicons name="close" size={14} color="#fff" />
            <Text style={styles.iconBtnT}>EXIT</Text>
          </Pressable>
        </View>
      </View>
      <Text style={styles.sub} numberOfLines={1}>{label}</Text>
      {showIssue ? <UIIssueReporter onClose={() => setShowIssue(false)} /> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { backgroundColor: "#7f1d1d", paddingHorizontal: 12, paddingVertical: 6 },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  left: { flexDirection: "row", alignItems: "center", gap: 8 },
  right: { flexDirection: "row", alignItems: "center", gap: 6 },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: "#fca5a5" },
  title: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.2 },
  sub: { color: "#fecaca", fontSize: 11, marginTop: 2 },
  iconBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 4, backgroundColor: "rgba(255,255,255,0.15)" },
  exitBtn: { backgroundColor: "#ef4444" },
  iconBtnT: { color: "#fff", fontSize: 10, fontWeight: "800", letterSpacing: 0.6 },
});
