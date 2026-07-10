/**
 * UIIssueReporter — Modal opened from the preview banner so a coach can
 * file a UI issue against the current screen without leaving the app.
 */
import React, { useState } from "react";
import { Modal, View, Text, TextInput, Pressable, StyleSheet, ActivityIndicator, Alert, Platform } from "react-native";
import { usePathname } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Priority = "low" | "medium" | "high";
type IssueType = "visual" | "copy" | "broken" | "other";

async function captureScreenshotWeb(): Promise<string | null> {
  if (Platform.OS !== "web") return null;
  try {
    // html2canvas is optional — fall back gracefully if not installed.
    const html2canvas = (await import("html2canvas")).default;
    const canvas = await html2canvas(document.body, {
      logging: false, scale: 0.6, useCORS: true,
      windowWidth: window.innerWidth, windowHeight: window.innerHeight,
    });
    return canvas.toDataURL("image/jpeg", 0.6);
  } catch {
    return null;
  }
}

export function UIIssueReporter({ onClose }: { onClose: () => void }) {
  const pathname = usePathname();
  const [note, setNote] = useState("");
  const [priority, setPriority] = useState<Priority>("medium");
  const [issueType, setIssueType] = useState<IssueType>("visual");
  const [attachShot, setAttachShot] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (note.trim().length < 3) {
      Alert.alert("Please add a short note describing what you saw.");
      return;
    }
    setBusy(true);
    try {
      let screenshot: string | null = null;
      if (attachShot) screenshot = await captureScreenshotWeb();
      await api("/preview/ui-issue", {
        method: "POST",
        body: {
          screen: pathname || "unknown",
          note: note.trim(),
          priority, issue_type: issueType,
          screenshot_data_url: screenshot,
        },
      });
      Alert.alert("Issue reported", "Saved to the admin UI issues list.");
      onClose();
    } catch (e: any) {
      Alert.alert("Could not save", e?.message || "Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.card}>
          <Text style={styles.h1}>Report UI Issue</Text>
          <Text style={styles.sub}>Screen: {pathname}</Text>

          <Text style={styles.label}>Note</Text>
          <TextInput
            value={note}
            onChangeText={setNote}
            placeholder="What did you see?"
            placeholderTextColor={theme.color.textDim}
            multiline
            style={styles.textarea}
            testID="issue-note"
          />

          <Text style={styles.label}>Type</Text>
          <View style={styles.row}>
            {(["visual", "copy", "broken", "other"] as IssueType[]).map((t) => (
              <Pressable key={t} onPress={() => setIssueType(t)} style={[styles.chip, issueType === t && styles.chipActive]} testID={`issue-type-${t}`}>
                <Text style={[styles.chipT, issueType === t && styles.chipTActive]}>{t.toUpperCase()}</Text>
              </Pressable>
            ))}
          </View>

          <Text style={styles.label}>Priority</Text>
          <View style={styles.row}>
            {(["low", "medium", "high"] as Priority[]).map((p) => (
              <Pressable key={p} onPress={() => setPriority(p)} style={[styles.chip, priority === p && styles.chipActive]} testID={`issue-priority-${p}`}>
                <Text style={[styles.chipT, priority === p && styles.chipTActive]}>{p.toUpperCase()}</Text>
              </Pressable>
            ))}
          </View>

          {Platform.OS === "web" ? (
            <Pressable onPress={() => setAttachShot(!attachShot)} style={styles.attachRow}>
              <View style={[styles.checkbox, attachShot && styles.checkboxOn]} />
              <Text style={styles.attachT}>Attach screenshot of this screen</Text>
            </Pressable>
          ) : null}

          <View style={[styles.row, { marginTop: 16 }]}>
            <Pressable onPress={onClose} style={[styles.btn, styles.btnGhost]} disabled={busy} testID="issue-cancel">
              <Text style={styles.btnGhostT}>CANCEL</Text>
            </Pressable>
            <Pressable onPress={submit} style={[styles.btn, styles.btnPrimary]} disabled={busy} testID="issue-submit">
              {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.btnPrimaryT}>SUBMIT</Text>}
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.7)", padding: 16, justifyContent: "center", alignItems: "center" },
  card: { backgroundColor: theme.color.surface, padding: 20, borderRadius: 12, borderWidth: 1, borderColor: theme.color.border, width: "100%", maxWidth: 480 },
  h1: { color: theme.color.text, fontSize: 18, fontWeight: "800", marginBottom: 4 },
  sub: { color: theme.color.textDim, fontSize: 12, marginBottom: 12 },
  label: { color: theme.color.textMuted, fontSize: 11, fontWeight: "800", letterSpacing: 1, marginTop: 12, marginBottom: 6 },
  textarea: { color: theme.color.text, backgroundColor: theme.color.surface2, borderRadius: 8, padding: 12, minHeight: 80, textAlignVertical: "top", borderWidth: 1, borderColor: theme.color.border },
  row: { flexDirection: "row", gap: 6, flexWrap: "wrap" },
  chip: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  chipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "800", letterSpacing: 0.6 },
  chipTActive: { color: "#fff" },
  attachRow: { flexDirection: "row", gap: 8, marginTop: 12, alignItems: "center" },
  checkbox: { width: 18, height: 18, borderRadius: 4, borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface2 },
  checkboxOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  attachT: { color: theme.color.textMuted, fontSize: 12 },
  btn: { flex: 1, paddingVertical: 12, borderRadius: 8, alignItems: "center" },
  btnGhost: { backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  btnGhostT: { color: theme.color.textMuted, fontWeight: "800", letterSpacing: 1 },
  btnPrimary: { backgroundColor: theme.color.brand },
  btnPrimaryT: { color: "#fff", fontWeight: "800", letterSpacing: 1 },
});
