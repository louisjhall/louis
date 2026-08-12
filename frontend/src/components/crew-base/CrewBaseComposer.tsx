/**
 * Iter 129b — Crew Base composer (extracted from coach workspace so it can
 * be triggered from either the "+ NEW POST" button OR a day-cell click on
 * the community calendar). Accepts an optional preselected schedule date.
 */
import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ScrollView, TextInput, ActivityIndicator, Image,
  Platform, Modal,
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

function toIsoLocal(date: Date, hh: string, mm: string): string {
  const h = Math.max(0, Math.min(23, parseInt(hh, 10) || 0));
  const m = Math.max(0, Math.min(59, parseInt(mm, 10) || 0));
  const d = new Date(date.getFullYear(), date.getMonth(), date.getDate(), h, m, 0);
  // Store as UTC ISO string (timezone naive; scheduler compares string-wise).
  return d.toISOString();
}

export type ComposerInitial = {
  scheduleDate?: Date;              // pre-populate schedule for this day
  postId?: string;                  // future: edit existing post
};

export function CrewBaseComposer({
  visible, onClose, onSaved, initial,
}: {
  visible: boolean;
  onClose: () => void;
  onSaved: () => void;
  initial?: ComposerInitial;
}) {
  const [text, setText] = useState("");
  const [mediaType, setMediaType] = useState<"none" | "image" | "video">("none");
  const [mediaB64, setMediaB64] = useState<string | null>(null);
  const [mediaMime, setMediaMime] = useState<string | null>(null);
  const [mediaPreview, setMediaPreview] = useState<string | null>(null);
  const [delivery, setDelivery] = useState<"publish" | "schedule" | "draft">("publish");
  const [schedDate, setSchedDate] = useState<Date | null>(null);
  const [schedHH, setSchedHH] = useState("08");
  const [schedMM, setSchedMM] = useState("00");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!visible) return;
    setText(""); setMediaType("none"); setMediaB64(null); setMediaMime(null);
    setMediaPreview(null);
    if (initial?.scheduleDate) {
      setDelivery("schedule");
      setSchedDate(initial.scheduleDate);
      setSchedHH("08"); setSchedMM("00");
    } else {
      setDelivery("publish");
      setSchedDate(null);
    }
  }, [visible, initial]);

  const pickMedia = async (kind: "image" | "video") => {
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

  const clearMedia = () => {
    setMediaType("none"); setMediaB64(null); setMediaMime(null); setMediaPreview(null);
  };

  const submit = async () => {
    const body: any = {
      text: text.trim(),
      media_type: mediaType,
      media_base64: mediaB64,
      media_mime: mediaMime,
      status: delivery === "publish" ? "published" : delivery === "schedule" ? "scheduled" : "draft",
    };
    if (delivery === "schedule") {
      if (!schedDate) { toast("Pick a date for the schedule.", "error"); return; }
      body.scheduled_at = toIsoLocal(schedDate, schedHH, schedMM);
    }
    if (!body.text && body.media_type === "none") {
      toast("Post must have text or media.", "error"); return;
    }
    setBusy(true);
    try {
      await api("/crew-base/posts", { method: "POST", body });
      toast(delivery === "publish" ? "Post published." : delivery === "schedule" ? "Post scheduled." : "Draft saved.", "success");
      onSaved();
    } catch (e: any) {
      toast(e?.message || "Post failed.", "error");
    } finally {
      setBusy(false);
    }
  };

  const dateLabel = schedDate
    ? schedDate.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" })
    : "";

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View style={styles.modalBg}>
        <Pressable style={styles.modalBack} onPress={onClose} />
        <View style={styles.sheet}>
          <View style={styles.sheetHead}>
            <Text style={styles.sheetTitle}>NEW POST</Text>
            <Pressable onPress={onClose} hitSlop={10}><Ionicons name="close" size={20} color={theme.color.textMuted} /></Pressable>
          </View>
          <ScrollView contentContainerStyle={{ paddingBottom: 20 }}>
            <TextInput
              value={text}
              onChangeText={setText}
              placeholder="What's happening at Crew Base?"
              placeholderTextColor={theme.color.textDim}
              multiline
              style={styles.composerBig}
              testID="cb-compose-text"
            />

            <Text style={styles.section}>MEDIA</Text>
            {mediaPreview ? (
              <View style={{ marginTop: 8 }}>
                {mediaType === "image" ? (
                  <Image source={{ uri: mediaPreview }} style={styles.mediaPreview} resizeMode="cover" />
                ) : (
                  <View style={[styles.mediaPreview, { alignItems: "center", justifyContent: "center", backgroundColor: theme.color.surface2 }]}>
                    <Ionicons name="videocam" size={28} color={theme.color.brand} />
                    <Text style={{ color: theme.color.textMuted, marginTop: 6 }}>Video attached</Text>
                  </View>
                )}
                <Pressable onPress={clearMedia} style={styles.removeBtn}>
                  <Ionicons name="close-circle" size={16} color={theme.color.red} />
                  <Text style={{ color: theme.color.red, marginLeft: 6, fontSize: 12, fontWeight: "800" }}>REMOVE</Text>
                </Pressable>
              </View>
            ) : (
              <View style={{ flexDirection: "row", gap: 8, marginTop: 6 }}>
                <Pressable onPress={() => pickMedia("image")} style={styles.mediaBtn} testID="cb-compose-add-image">
                  <Ionicons name="image" size={14} color={theme.color.brand} />
                  <Text style={styles.mediaBtnT}>ADD IMAGE</Text>
                </Pressable>
                <Pressable onPress={() => pickMedia("video")} style={styles.mediaBtn} testID="cb-compose-add-video">
                  <Ionicons name="videocam" size={14} color={theme.color.brand} />
                  <Text style={styles.mediaBtnT}>ADD VIDEO</Text>
                </Pressable>
              </View>
            )}

            <Text style={styles.section}>DELIVERY</Text>
            {(["publish", "schedule", "draft"] as const).map((d) => (
              <Pressable key={d} onPress={() => setDelivery(d)} style={styles.radioRow} testID={`cb-delivery-${d}`}>
                <View style={[styles.radioDot, delivery === d && styles.radioDotActive]}>
                  {delivery === d ? <View style={styles.radioInner} /> : null}
                </View>
                <Text style={styles.radioT}>
                  {d === "publish" ? "Publish now" : d === "schedule" ? "Schedule for later" : "Save as draft"}
                </Text>
              </Pressable>
            ))}
            {delivery === "schedule" ? (
              <View style={{ marginTop: 6, gap: 8 }}>
                <View style={styles.scheduleDateRow}>
                  <Ionicons name="calendar" size={14} color={theme.color.brand} />
                  <Text style={styles.scheduleDateT}>{dateLabel || "Pick a date on the calendar"}</Text>
                </View>
                <View style={{ flexDirection: "row", gap: 8, alignItems: "center" }}>
                  <TextInput
                    value={schedHH}
                    onChangeText={(v) => setSchedHH(v.replace(/[^0-9]/g, "").slice(0, 2))}
                    style={styles.timeInput}
                    keyboardType="number-pad"
                    maxLength={2}
                    placeholder="HH"
                    placeholderTextColor={theme.color.textDim}
                    testID="cb-schedule-hh"
                  />
                  <Text style={{ color: theme.color.textMuted, fontWeight: "900" }}>:</Text>
                  <TextInput
                    value={schedMM}
                    onChangeText={(v) => setSchedMM(v.replace(/[^0-9]/g, "").slice(0, 2))}
                    style={styles.timeInput}
                    keyboardType="number-pad"
                    maxLength={2}
                    placeholder="MM"
                    placeholderTextColor={theme.color.textDim}
                    testID="cb-schedule-mm"
                  />
                  <Text style={{ color: theme.color.textMuted, fontSize: 11, marginLeft: 8 }}>
                    Local time
                  </Text>
                </View>
              </View>
            ) : null}
          </ScrollView>

          <Pressable
            onPress={submit}
            disabled={busy}
            style={[styles.primaryBtn, busy && { opacity: 0.5 }]}
            testID="cb-compose-submit"
          >
            {busy ? <ActivityIndicator color="#fff" /> : (
              <Text style={styles.primaryBtnT}>
                {delivery === "publish" ? "PUBLISH" : delivery === "schedule" ? "SCHEDULE POST" : "SAVE DRAFT"}
              </Text>
            )}
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  modalBack: { ...StyleSheet.absoluteFillObject },
  sheet: {
    backgroundColor: theme.color.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20,
    padding: 16, maxHeight: "92%", minHeight: Platform.OS === "web" ? 520 : "60%" as any,
  },
  sheetHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 10 },
  sheetTitle: { color: theme.color.brand, fontSize: 12, fontWeight: "900", letterSpacing: 2 },
  composerBig: {
    color: theme.color.onRed, fontSize: 15, lineHeight: 20,
    minHeight: 90, textAlignVertical: "top",
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
    borderRadius: 10, padding: 12,
  },
  section: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1.5, marginTop: 16, marginBottom: 6 },
  mediaBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    padding: 12, borderRadius: 10, borderWidth: 1, borderColor: theme.color.brand,
    backgroundColor: theme.color.brandTint,
  },
  mediaBtnT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  mediaPreview: { width: "100%", height: 180, borderRadius: 10, backgroundColor: "#000" },
  removeBtn: { flexDirection: "row", alignItems: "center", alignSelf: "flex-start", marginTop: 6, paddingVertical: 4 },
  radioRow: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 8 },
  radioDot: { width: 18, height: 18, borderRadius: 9, borderWidth: 2, borderColor: theme.color.border, alignItems: "center", justifyContent: "center" },
  radioDotActive: { borderColor: theme.color.brand },
  radioInner: { width: 8, height: 8, borderRadius: 4, backgroundColor: theme.color.brand },
  radioT: { color: theme.color.text, fontSize: 13, fontWeight: "700" },
  scheduleDateRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    padding: 10, borderRadius: 8, backgroundColor: theme.color.brandTint,
    borderWidth: 1, borderColor: theme.color.brand,
  },
  scheduleDateT: { color: theme.color.brand, fontWeight: "800", fontSize: 12 },
  timeInput: {
    width: 56, textAlign: "center",
    color: theme.color.onRed, fontSize: 15, fontWeight: "800",
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
    borderRadius: 8, padding: 8,
  },
  primaryBtn: {
    backgroundColor: theme.color.brand, alignItems: "center", justifyContent: "center",
    padding: 14, borderRadius: 10, marginTop: 12,
  },
  primaryBtnT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 1.8 },
});

export default CrewBaseComposer;
