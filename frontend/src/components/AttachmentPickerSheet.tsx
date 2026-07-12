/**
 * AttachmentPickerSheet — the 5-option chooser that pops when the client
 * taps the “+” icon on the composer. Contextual permission requests are
 * done inside each handler so we never surface a prompt before intent.
 */
import React, { useState } from "react";
import {
  View, Text, Pressable, Modal, StyleSheet, Alert, Platform, Linking,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as ImagePicker from "expo-image-picker";
import { theme } from "@/src/lib/theme";
import type { AttachmentKind } from "@/src/lib/messageAttachments";

export type PickedFile = {
  uri: string;
  mimeType: string;
  kind: AttachmentKind;
  fileName?: string;
  fileSize?: number;
  durationSeconds?: number;
};

async function ensurePermission(
  reqFn: () => Promise<ImagePicker.PermissionResponse>,
  label: string,
) {
  const status = await reqFn();
  if (status.granted) return true;
  const canAskAgain = (status as any).canAskAgain;
  if (canAskAgain === false) {
    Alert.alert(
      `${label} access blocked`,
      `Enable ${label.toLowerCase()} access in Settings so you can share form check-ins with Louis.`,
      [
        { text: "Not now", style: "cancel" },
        { text: "Open Settings", onPress: () => Linking.openSettings() },
      ],
    );
  } else {
    Alert.alert(`${label} access needed`, `Grant ${label.toLowerCase()} access to attach this to your message.`);
  }
  return false;
}

function guessMime(uri: string, isVideo: boolean, fallback?: string | null): string {
  const lower = (uri.split("?")[0] || "").toLowerCase();
  if (fallback && /^(image|video)\//.test(fallback)) return fallback;
  if (isVideo) {
    if (lower.endsWith(".mov")) return "video/quicktime";
    if (lower.endsWith(".webm")) return "video/webm";
    return "video/mp4";
  }
  if (lower.endsWith(".png")) return "image/png";
  if (lower.endsWith(".webp")) return "image/webp";
  if (lower.endsWith(".heic") || lower.endsWith(".heif")) return "image/heic";
  return "image/jpeg";
}

async function pickImages(source: "camera" | "library", multiple: boolean): Promise<PickedFile[]> {
  const okCamera = source === "camera"
    ? await ensurePermission(ImagePicker.requestCameraPermissionsAsync, "Camera")
    : true;
  const okLib = source === "library"
    ? await ensurePermission(ImagePicker.requestMediaLibraryPermissionsAsync, "Photo library")
    : true;
  if (!okCamera || !okLib) return [];

  const fn = source === "camera" ? ImagePicker.launchCameraAsync : ImagePicker.launchImageLibraryAsync;
  const res = await fn({
    mediaTypes: ["images"],
    allowsMultipleSelection: multiple && source === "library",
    selectionLimit: 5,
    quality: 0.85,
    exif: false,
  });
  if (res.canceled) return [];
  const assets = res.assets || [];
  return assets.map((a) => ({
    uri: a.uri,
    mimeType: guessMime(a.uri, false, a.mimeType),
    kind: "image" as const,
    fileName: a.fileName || undefined,
    fileSize: (a as any).fileSize,
  }));
}

async function pickVideo(source: "camera" | "library"): Promise<PickedFile[]> {
  const okCamera = source === "camera"
    ? await ensurePermission(ImagePicker.requestCameraPermissionsAsync, "Camera")
    : true;
  const okLib = source === "library"
    ? await ensurePermission(ImagePicker.requestMediaLibraryPermissionsAsync, "Photo library")
    : true;
  if (!okCamera || !okLib) return [];

  const fn = source === "camera" ? ImagePicker.launchCameraAsync : ImagePicker.launchImageLibraryAsync;
  const res = await fn({
    mediaTypes: ["videos"],
    videoMaxDuration: 60, // ≤ 60 s hard cap; matches backend
    quality: 1,
    exif: false,
  });
  if (res.canceled) return [];
  const assets = res.assets || [];
  return assets.map((a) => ({
    uri: a.uri,
    mimeType: guessMime(a.uri, true, a.mimeType),
    kind: "video" as const,
    fileName: a.fileName || undefined,
    fileSize: (a as any).fileSize,
    durationSeconds: a.duration ? Math.round(a.duration / 1000) : undefined,
  }));
}

export function AttachmentPickerSheet({
  visible,
  onClose,
  onPicked,
  onVoiceRequested,
}: {
  visible: boolean;
  onClose: () => void;
  onPicked: (files: PickedFile[]) => void;
  onVoiceRequested: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);

  const run = async (id: string, fn: () => Promise<PickedFile[]>) => {
    if (busy) return;
    setBusy(id);
    try {
      const picked = await fn();
      if (picked.length > 0) {
        onPicked(picked);
        onClose();
      }
    } catch (e: any) {
      Alert.alert("Something went wrong", e?.message || "Please try again.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose} />
      <View style={styles.sheet}>
        <View style={styles.grabber} />
        <Text style={styles.title}>Attach to your message</Text>
        <Text style={styles.helper}>Send a form check video, meal photo, roster screenshot or voice note.</Text>

        <Row testID="att-camera-photo" icon="camera" label="Take photo" hint="Snap a quick photo"
             onPress={() => run("cp", () => pickImages("camera", false))} busy={busy === "cp"} />
        <Row testID="att-lib-photo" icon="image" label="Choose image" hint="Up to 5 photos from your library"
             onPress={() => run("li", () => pickImages("library", true))} busy={busy === "li"} />
        <Row testID="att-camera-video" icon="videocam" label="Record video" hint="Up to 60 seconds"
             onPress={() => run("cv", () => pickVideo("camera"))} busy={busy === "cv"} />
        <Row testID="att-lib-video" icon="film" label="Choose video" hint="Up to 60 seconds from your library"
             onPress={() => run("lv", () => pickVideo("library"))} busy={busy === "lv"} />
        <Row testID="att-voice" icon="mic" label="Record voice note" hint="Up to 5 minutes"
             onPress={() => { onClose(); onVoiceRequested(); }} busy={false} />

        <Pressable style={styles.cancelRow} onPress={onClose} testID="att-cancel">
          <Text style={styles.cancelText}>Cancel</Text>
        </Pressable>
      </View>
    </Modal>
  );
}

function Row({
  icon, label, hint, onPress, busy, testID,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  hint: string;
  onPress: () => void;
  busy: boolean;
  testID?: string;
}) {
  return (
    <Pressable style={[styles.row, busy && { opacity: 0.5 }]} onPress={onPress} disabled={busy} testID={testID}>
      <View style={styles.rowIcon}>
        <Ionicons name={icon} size={20} color={theme.color.brand} />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.rowLabel}>{label}</Text>
        <Text style={styles.rowHint}>{hint}</Text>
      </View>
      <Ionicons name="chevron-forward" size={18} color={theme.color.textDim} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)" },
  sheet: {
    position: "absolute", left: 0, right: 0, bottom: 0,
    backgroundColor: theme.color.surface,
    borderTopLeftRadius: 22, borderTopRightRadius: 22,
    paddingHorizontal: 18, paddingTop: 10, paddingBottom: Platform.OS === "ios" ? 32 : 20,
    gap: 8,
  },
  grabber: { width: 40, height: 4, borderRadius: 2, backgroundColor: theme.color.border, alignSelf: "center", marginBottom: 8 },
  title: { color: theme.color.text, fontSize: 17, fontWeight: "900" },
  helper: { color: theme.color.textMuted, fontSize: 12, marginBottom: 6 },
  row: {
    flexDirection: "row", alignItems: "center", gap: 14,
    paddingVertical: 12, paddingHorizontal: 6, borderBottomWidth: 1,
    borderBottomColor: theme.color.divider,
  },
  rowIcon: {
    width: 40, height: 40, borderRadius: 10,
    backgroundColor: theme.color.brandTint, alignItems: "center", justifyContent: "center",
  },
  rowLabel: { color: theme.color.text, fontWeight: "800", fontSize: 14 },
  rowHint: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },
  cancelRow: { alignItems: "center", paddingVertical: 12, marginTop: 4 },
  cancelText: { color: theme.color.brand, fontWeight: "800", fontSize: 13, letterSpacing: 1.1 },
});
