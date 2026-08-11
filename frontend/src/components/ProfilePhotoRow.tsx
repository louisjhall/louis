/**
 * ProfilePhotoRow — inline profile photo picker used inside the client Profile
 * screen. Uses expo-image-picker for library, expo-camera for take-photo. Skip
 * remains the default. Uploads via the multipart /user/profile/photo endpoint.
 */
import React, { useState } from "react";
import { View, Text, StyleSheet, Pressable, Alert, ActivityIndicator, Platform, Linking } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as ImagePicker from "expo-image-picker";
import { theme } from "@/src/lib/theme";
import { api, uploadFile } from "@/src/lib/api";
import { ProfileAvatar } from "@/src/components/ProfileAvatar";

type Props = {
  user: any;
  onChanged?: () => Promise<void> | void;
};

export function ProfilePhotoRow({ user, onChanged }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const hasPhoto = !!user?.profile_photo_url;

  const upload = async (uri: string, mimeGuess: string) => {
    setBusy("upload");
    try {
      let payload: any;
      if (Platform.OS === "web") {
        const res = await fetch(uri);
        payload = await res.blob();
      } else {
        const ext = (uri.split(".").pop() || "jpg").toLowerCase();
        const name = `avatar-${Date.now()}.${ext}`;
        payload = { uri, name, type: mimeGuess || `image/${ext === "jpg" ? "jpeg" : ext}` };
      }
      await uploadFile("/user/profile/photo", payload, {});
      await onChanged?.();
    } catch (e: any) {
      Alert.alert("Upload failed", e?.message || "Please try again");
    } finally { setBusy(null); }
  };

  const pickLibrary = async () => {
    try {
      const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) {
        if (!perm.canAskAgain) Linking.openSettings();
        else Alert.alert("Photo library access needed", "CrewFit needs access to your photos to set a profile picture.");
        return;
      }
      const res = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        allowsEditing: true, aspect: [1, 1], quality: 0.85,
      });
      if (res.canceled) return;
      const a = res.assets?.[0];
      if (!a?.uri) return;
      await upload(a.uri, a.mimeType || "image/jpeg");
    } catch (e: any) { Alert.alert("Library error", e?.message || ""); }
  };

  const takePhoto = async () => {
    try {
      const perm = await ImagePicker.requestCameraPermissionsAsync();
      if (!perm.granted) {
        if (!perm.canAskAgain) Linking.openSettings();
        else Alert.alert("Camera access needed", "CrewFit needs your camera to take a profile photo.");
        return;
      }
      const res = await ImagePicker.launchCameraAsync({ allowsEditing: true, aspect: [1, 1], quality: 0.85 });
      if (res.canceled) return;
      const a = res.assets?.[0];
      if (!a?.uri) return;
      await upload(a.uri, a.mimeType || "image/jpeg");
    } catch (e: any) { Alert.alert("Camera error", e?.message || ""); }
  };

  const removePhoto = async () => {
    setBusy("remove");
    try {
      await api("/user/profile/photo", { method: "DELETE" });
      await onChanged?.();
    } catch (e: any) { Alert.alert("Remove failed", e?.message || ""); }
    finally { setBusy(null); }
  };

  return (
    <View style={styles.row}>
      <ProfileAvatar
        userId={user?.id}
        name={user?.name}
        photoUrl={user?.profile_photo_url || null}
        size={68}
      />
      <View style={{ flex: 1 }}>
        <Text style={styles.title}>PROFILE PHOTO</Text>
        <Text style={styles.hint}>
          Optional. A photo appears in your header, coach dashboard, messages and check-ins.
        </Text>
        <View style={styles.actions}>
          <Pressable disabled={!!busy} onPress={takePhoto} style={styles.primaryBtn} testID="photo-take">
            {busy === "upload" ? <ActivityIndicator color="#fff" /> : (<>
              <Ionicons name="camera" size={14} color="#fff" />
              <Text style={styles.primaryBtnT}>TAKE PHOTO</Text>
            </>)}
          </Pressable>
          <Pressable disabled={!!busy} onPress={pickLibrary} style={styles.secondaryBtn} testID="photo-upload">
            <Ionicons name="image" size={14} color={theme.color.brand} />
            <Text style={styles.secondaryBtnT}>UPLOAD</Text>
          </Pressable>
          {hasPhoto ? (
            <Pressable disabled={!!busy} onPress={removePhoto} style={styles.mutedBtn} testID="photo-remove">
              {busy === "remove" ? <ActivityIndicator color={theme.color.textMuted} /> : (<>
                <Ionicons name="trash-outline" size={14} color={theme.color.textMuted} />
                <Text style={styles.mutedBtnT}>REMOVE</Text>
              </>)}
            </Pressable>
          ) : null}
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row", alignItems: "flex-start", gap: 14, marginBottom: 14,
    padding: 12, borderRadius: 12, backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
  },
  title: {
    color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5,
    fontFamily: theme.font.textSemi,
  },
  hint: { color: theme.color.textMuted, fontSize: 11, lineHeight: 15, marginTop: 4, fontFamily: theme.font.text },
  actions: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 8 },
  primaryBtn: { flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: 10, paddingVertical: 7, borderRadius: 8, backgroundColor: theme.color.brand },
  primaryBtnT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1, fontFamily: theme.font.textSemi },
  secondaryBtn: { flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: 10, paddingVertical: 7, borderRadius: 8, borderWidth: 1, borderColor: theme.color.brand, backgroundColor: theme.color.brandTint },
  secondaryBtnT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1, fontFamily: theme.font.textSemi },
  mutedBtn: { flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: 10, paddingVertical: 7, borderRadius: 8, borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface3 },
  mutedBtnT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1, fontFamily: theme.font.textSemi },
});
