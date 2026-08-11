/**
 * Iter 129e — Instant Post composer for Crew Base right-panel Feed.
 *
 * A lightweight, always-visible composer that publishes immediately.
 * Reuses the existing `/crew-base/posts` endpoint with `status: "published"`
 * and the existing base64 media pattern (image/video). No new backend,
 * no scheduling logic — that lives in the full CrewBaseComposer /
 * calendar-day click flow.
 */
import React, { useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput, ActivityIndicator, Image,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as ImagePicker from "expo-image-picker";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast } from "@/src/lib/ux";

async function fileToBase64(uri: string): Promise<string> {
  const res = await fetch(uri);
  const blob = await res.blob();
  return new Promise<string>((resolve, reject) => {
    const r = new FileReader();
    r.onerror = () => reject(new Error("failed to read file"));
    r.onload = () => {
      const dataUri = String(r.result || "");
      const comma = dataUri.indexOf(",");
      resolve(comma >= 0 ? dataUri.slice(comma + 1) : dataUri);
    };
    r.readAsDataURL(blob);
  });
}

export function InstantPostComposer({ onPosted }: { onPosted: () => void }) {
  const [text, setText] = useState("");
  const [mediaType, setMediaType] = useState<"none" | "image" | "video">("none");
  const [mediaB64, setMediaB64] = useState<string | null>(null);
  const [mediaMime, setMediaMime] = useState<string | null>(null);
  const [mediaPreview, setMediaPreview] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const pick = async (kind: "image" | "video") => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) { toast("Media permission denied.", "error"); return; }
    const res = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: kind === "image" ? ImagePicker.MediaTypeOptions.Images : ImagePicker.MediaTypeOptions.Videos,
      quality: 0.7,
    });
    if (res.canceled || !res.assets?.[0]) return;
    const asset = res.assets[0];
    try {
      let b64 = asset.base64 ?? null;
      if (!b64) b64 = await fileToBase64(asset.uri);
      const mime = asset.mimeType || (kind === "image" ? "image/jpeg" : "video/mp4");
      setMediaType(kind); setMediaB64(b64); setMediaMime(mime);
      setMediaPreview(`data:${mime};base64,${b64}`);
    } catch (e: any) {
      toast(e?.message || "Media load failed.", "error");
    }
  };

  const clear = () => {
    setMediaType("none"); setMediaB64(null); setMediaMime(null); setMediaPreview(null);
  };

  const submit = async () => {
    const t = text.trim();
    if (!t && mediaType === "none") return;
    setBusy(true);
    try {
      await api("/crew-base/posts", {
        method: "POST",
        body: {
          text: t,
          media_type: mediaType,
          media_base64: mediaB64,
          media_mime: mediaMime,
          status: "published",
        },
      });
      setText(""); clear();
      toast("Posted.", "success");
      onPosted();
    } catch (e: any) {
      toast(e?.message || "Post failed.", "error");
    } finally {
      setBusy(false);
    }
  };

  const canPost = (text.trim().length > 0 || mediaType !== "none") && !busy;

  return (
    <View style={styles.wrap}>
      {mediaPreview ? (
        <View style={styles.previewRow}>
          {mediaType === "image" ? (
            <Image source={{ uri: mediaPreview }} style={styles.previewImg} resizeMode="cover" />
          ) : (
            <View style={styles.previewVideo}>
              <Ionicons name="videocam" size={16} color={theme.color.brand} />
              <Text style={styles.previewT}>Video attached</Text>
            </View>
          )}
          <Pressable onPress={clear} hitSlop={8} style={styles.previewRemove} testID="cb-instant-remove-media">
            <Ionicons name="close-circle" size={16} color={theme.color.red} />
          </Pressable>
        </View>
      ) : null}
      <TextInput
        value={text}
        onChangeText={setText}
        placeholder="Share something with Crew Base…"
        placeholderTextColor={theme.color.textDim}
        multiline
        style={styles.input}
        testID="cb-instant-text"
      />
      <View style={styles.row}>
        <Pressable onPress={() => pick("image")} style={styles.iconBtn} disabled={busy} testID="cb-instant-image">
          <Ionicons name="image" size={16} color={theme.color.textMuted} />
        </Pressable>
        <Pressable onPress={() => pick("video")} style={styles.iconBtn} disabled={busy} testID="cb-instant-video">
          <Ionicons name="videocam" size={16} color={theme.color.textMuted} />
        </Pressable>
        <View style={{ flex: 1 }} />
        <Pressable
          onPress={submit}
          disabled={!canPost}
          style={[styles.postBtn, !canPost && { opacity: 0.4 }]}
          testID="cb-instant-post"
        >
          {busy ? <ActivityIndicator color="#fff" /> : (
            <>
              <Text style={styles.postBtnT}>POST</Text>
              <Ionicons name="arrow-forward" size={12} color="#fff" style={{ marginLeft: 6 }} />
            </>
          )}
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    borderTopWidth: 1,
    borderTopColor: theme.color.divider,
    backgroundColor: theme.color.bg,
    padding: 10,
  },
  input: {
    color: theme.color.text,
    fontSize: 13,
    minHeight: 44,
    maxHeight: 100,
    backgroundColor: theme.color.surface2,
    borderWidth: 1,
    borderColor: theme.color.border,
    borderRadius: 10,
    paddingHorizontal: 10,
    paddingVertical: 8,
    textAlignVertical: "top",
  },
  row: { flexDirection: "row", alignItems: "center", marginTop: 8, gap: 4 },
  iconBtn: { padding: 8, borderRadius: 6 },
  postBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    paddingHorizontal: 16, paddingVertical: 9, borderRadius: 8,
    backgroundColor: theme.color.brand,
  },
  postBtnT: { color: "#fff", fontWeight: "900", fontSize: 11, letterSpacing: 1.5 },
  previewRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    padding: 6, marginBottom: 8, borderRadius: 8,
    backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border,
  },
  previewImg: { width: 44, height: 44, borderRadius: 6, backgroundColor: "#000" },
  previewVideo: {
    width: 44, height: 44, borderRadius: 6,
    backgroundColor: theme.color.surface2, alignItems: "center", justifyContent: "center",
  },
  previewT: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },
  previewRemove: { marginLeft: "auto", padding: 4 },
});

export default InstantPostComposer;
