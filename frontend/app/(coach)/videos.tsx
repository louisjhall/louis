import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput,
  ActivityIndicator, RefreshControl, Alert, Modal, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import * as DocumentPicker from "expo-document-picker";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { useIsDesktop } from "@/src/lib/responsive";
import { ExerciseVideoPlayer } from "@/src/components/ExerciseVideoPlayer";

type Item = {
  id: string | null;
  key: string;
  display_name: string;
  category?: string | null;
  primary_video_id?: string | null;
  primary_channel?: string | null;
  primary_thumbnail?: string | null;
  has_custom_url: boolean;
  has_custom_upload: boolean;
  variants_configured: string[];
  preferred_slot: string;
  approval_state: string;
  last_reviewed_at?: string | null;
};

type Slot = {
  source?: string;
  video_id?: string;
  video_url?: string;
  title?: string | null;
  channel?: string | null;
  channel_hint?: string | null;
  thumbnail_url?: string | null;
  approval_status?: string;
  added_by?: string | null;
  added_at?: string;
  reviewed_by?: string | null;
  reviewed_at?: string;
  notes?: string | null;
};

type Record = {
  id: string;
  key: string;
  display_name: string;
  category?: string | null;
  primary?: Slot | null;
  alternative?: Slot | null;
  custom_url?: Slot | null;
  custom_upload?: Slot | null;
  youtube_backup?: Slot | null;
  ai_image?: Slot | null;
  variants?: Record<string, Slot | null>;
  preferred_slot?: string | null;
  last_reviewed_at?: string | null;
  reviewed_by?: string | null;
};

const SLOTS = [
  { key: "primary", label: "PRIMARY (AUTO)", icon: "logo-youtube" as const },
  { key: "custom_url", label: "CUSTOM URL", icon: "link" as const },
  { key: "custom_upload", label: "CREWFIT UPLOAD", icon: "cloud-upload" as const, uploadable: true },
  { key: "alternative", label: "ALTERNATIVE", icon: "swap-horizontal" as const },
  { key: "youtube_backup", label: "YOUTUBE BACKUP", icon: "bookmark" as const },
  { key: "ai_image", label: "GENERATED IMAGE", icon: "image" as const, disabled: true },
];

const VARIANTS = ["home", "hotel", "gym"] as const;

function approvalColor(status?: string): string {
  if (status === "approved") return theme.color.green;
  if (status === "rejected") return theme.color.red;
  if (status === "pending") return theme.color.amber;
  if (status === "auto") return theme.color.brand;
  return theme.color.textMuted;
}

function fmtDate(iso?: string | null): string {
  if (!iso) return "never";
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  } catch { return "—"; }
}

export default function CoachVideos() {
  const isDesktop = useIsDesktop();
  const [items, setItems] = useState<Item[]>([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [detail, setDetail] = useState<any | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [addName, setAddName] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api<any>(`/coach/videos${q ? `?search=${encodeURIComponent(q)}` : ""}`);
      setItems(res.items || []);
      if (!selectedKey && (res.items || []).length && isDesktop) {
        setSelectedKey(res.items[0].key);
      }
    } finally { setLoading(false); }
  }, [q, selectedKey, isDesktop]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const loadDetail = useCallback(async (key: string) => {
    setBusy("detail");
    try {
      const d = await api<any>(`/coach/videos/detail?key=${encodeURIComponent(key)}`);
      setDetail(d);
    } finally { setBusy(null); }
  }, []);

  useEffect(() => {
    if (selectedKey) loadDetail(selectedKey);
  }, [selectedKey, loadDetail]);

  const filtered = useMemo(() => items, [items]);

  const doAddExercise = async () => {
    if (!addName.trim()) return;
    setBusy("add");
    try {
      const d = await api<any>(`/coach/videos/upsert`, { method: "POST", body: { display_name: addName.trim() } });
      setShowAdd(false);
      setAddName("");
      await load();
      setSelectedKey(d.key);
    } finally { setBusy(null); }
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.color.surface }} edges={isDesktop ? [] : ["top"]}>
      <View style={[styles.root, isDesktop ? { flexDirection: "row" } : { flexDirection: "column" }]}>
        {/* MASTER PANEL */}
        <View style={[styles.master, isDesktop ? { width: 340, borderRightWidth: 1, borderRightColor: theme.color.border } : {}]}>
          <View style={styles.masterHeader}>
            <Text style={styles.h1}>VIDEO LIBRARY</Text>
            <Pressable testID="videos-add-btn" onPress={() => setShowAdd(true)} style={styles.addBtn}>
              <Ionicons name="add" size={20} color={theme.color.brand} />
            </Pressable>
          </View>
          <View style={styles.searchRow}>
            <Ionicons name="search" size={16} color={theme.color.textMuted} />
            <TextInput
              testID="videos-search"
              style={styles.searchInput}
              placeholder="Search exercises…"
              placeholderTextColor={theme.color.textDim}
              value={q}
              onChangeText={setQ}
              onSubmitEditing={load}
            />
            {q ? <Pressable onPress={() => { setQ(""); load(); }}><Ionicons name="close-circle" size={16} color={theme.color.textMuted} /></Pressable> : null}
          </View>
          <ScrollView
            style={{ flex: 1 }}
            refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}
            contentContainerStyle={{ padding: 12, gap: 8 }}
          >
            {loading && !filtered.length ? (
              <ActivityIndicator color={theme.color.brand} style={{ marginTop: 30 }} />
            ) : filtered.length === 0 ? (
              <Text style={styles.empty}>No exercises found.</Text>
            ) : (
              filtered.map((it) => {
                const active = selectedKey === it.key;
                return (
                  <Pressable
                    key={it.key}
                    testID={`videos-item-${it.key}`}
                    onPress={() => setSelectedKey(it.key)}
                    style={[styles.itemRow, active && styles.itemRowActive]}
                  >
                    <View style={styles.itemThumb}>
                      {it.primary_thumbnail && Platform.OS === "web"
                        ? React.createElement("img", { src: it.primary_thumbnail, style: { width: "100%", height: "100%", objectFit: "cover", display: "block" }, alt: it.display_name })
                        : <Ionicons name="videocam-off" size={18} color={theme.color.textDim} />}
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.itemName} numberOfLines={1}>{it.display_name}</Text>
                      <View style={styles.itemMetaRow}>
                        <View style={[styles.statusDot, { backgroundColor: approvalColor(it.approval_state) }]} />
                        <Text style={styles.itemMeta}>{it.approval_state.toUpperCase()}</Text>
                        {it.has_custom_url ? <Text style={styles.badge}>URL</Text> : null}
                        {it.has_custom_upload ? <Text style={styles.badge}>UP</Text> : null}
                        {it.variants_configured.length > 0 ? <Text style={styles.badge}>V{it.variants_configured.length}</Text> : null}
                      </View>
                    </View>
                    {active && <Ionicons name="chevron-forward" size={14} color={theme.color.brand} />}
                  </Pressable>
                );
              })
            )}
          </ScrollView>
        </View>

        {/* DETAIL PANEL */}
        <View style={{ flex: 1 }}>
          {!selectedKey ? (
            <View style={styles.detailEmpty}>
              <Ionicons name="videocam-outline" size={48} color={theme.color.textDim} />
              <Text style={styles.detailEmptyText}>Select an exercise to manage its videos</Text>
            </View>
          ) : busy === "detail" || !detail ? (
            <ActivityIndicator color={theme.color.brand} style={{ marginTop: 60 }} />
          ) : (
            <DetailPanel
              detail={detail}
              onReload={async () => {
                await loadDetail(selectedKey);
                load();
              }}
              busy={busy}
              setBusy={setBusy}
            />
          )}
        </View>
      </View>

      {/* Add Exercise Modal */}
      <Modal visible={showAdd} animationType="fade" transparent onRequestClose={() => setShowAdd(false)}>
        <View style={styles.modalRoot}>
          <Pressable style={styles.backdrop} onPress={() => setShowAdd(false)} />
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>ADD EXERCISE</Text>
            <TextInput
              testID="videos-add-name"
              style={styles.modalInput}
              placeholder="e.g. Turkish Get-Up"
              placeholderTextColor={theme.color.textDim}
              value={addName}
              onChangeText={setAddName}
              autoFocus
            />
            <View style={{ flexDirection: "row", justifyContent: "flex-end", gap: 10 }}>
              <Pressable onPress={() => setShowAdd(false)} style={styles.btnGhost}>
                <Text style={styles.btnGhostText}>CANCEL</Text>
              </Pressable>
              <Pressable testID="videos-add-submit" onPress={doAddExercise} style={styles.btnPrimary} disabled={busy === "add"}>
                <Text style={styles.btnPrimaryText}>{busy === "add" ? "ADDING…" : "CREATE"}</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

// -----------------------------------------------------------------------------
// Detail Panel
// -----------------------------------------------------------------------------
function DetailPanel({ detail, onReload, busy, setBusy }: any) {
  const key = detail.key as string;
  const preferred = detail.preferred_slot || "primary";
  const [urlInput, setUrlInput] = useState("");
  const [slotForUrl, setSlotForUrl] = useState<"custom_url" | "alternative" | "youtube_backup">("custom_url");
  const [variantUrls, setVariantUrls] = useState<Record<string, string>>({});

  const call = async (method: string, url: string, body?: any) => {
    setBusy(url);
    try {
      await api<any>(url, { method, ...(body ? { body } : {}) } as any);
      await onReload();
    } catch (e: any) {
      Alert.alert("Failed", e?.message || "Request failed");
    } finally {
      setBusy(null);
    }
  };

  const rescan = () => call("POST", `/coach/videos/rescan?key=${encodeURIComponent(key)}`);

  const setSlot = async () => {
    if (!urlInput.trim()) return;
    await call("POST", `/coach/videos/slot?key=${encodeURIComponent(key)}`, {
      slot: slotForUrl,
      video_url: urlInput.trim(),
    });
    setUrlInput("");
  };

  const setApproval = (slot: string, status: string) =>
    call("POST", `/coach/videos/approve?key=${encodeURIComponent(key)}`, { slot, status });

  const setPreferred = (slot: string) =>
    call("POST", `/coach/videos/preferred?key=${encodeURIComponent(key)}`, { slot });

  const deleteSlot = (slot: string) => {
    Alert.alert("Delete slot", `Remove the ${slot} video?`, [
      { text: "Cancel" },
      { text: "Delete", style: "destructive", onPress: () => call("DELETE", `/coach/videos/slot?key=${encodeURIComponent(key)}&slot=${slot}`) },
    ]);
  };

  const setVariant = async (variant: string) => {
    const url = variantUrls[variant]?.trim();
    if (!url) return;
    await call("POST", `/coach/videos/variant?key=${encodeURIComponent(key)}`, { variant, video_url: url });
    setVariantUrls((s) => ({ ...s, [variant]: "" }));
  };

  const deleteVariant = (variant: string) =>
    call("POST", `/coach/videos/variant?key=${encodeURIComponent(key)}`, { variant, delete: true });

  const [uploadProgress, setUploadProgress] = useState<{ pct: number; label: string } | null>(null);
  const uploadCustomVideo = async () => {
    try {
      const res = await DocumentPicker.getDocumentAsync({
        type: ["video/mp4", "video/quicktime", "video/webm", "video/x-m4v"],
        copyToCacheDirectory: true,
        multiple: false,
      });
      if (res.canceled || !res.assets?.[0]) return;
      const asset = res.assets[0];
      // Validate size client-side
      const sizeBytes = asset.size || 0;
      if (sizeBytes > 10 * 1024 * 1024) {
        Alert.alert("File too large", `Max upload is 10 MB. This file is ${(sizeBytes / 1_048_576).toFixed(1)} MB.`);
        return;
      }
      setUploadProgress({ pct: 5, label: "READING FILE\u2026" });

      // Read file → base64
      let base64: string;
      if (Platform.OS === "web") {
        // On web, DocumentPicker's uri is a blob URL; fetch it and convert
        const blob = await fetch(asset.uri).then((r) => r.blob());
        base64 = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => {
            const s = String(reader.result || "");
            resolve(s.includes(",") ? s.split(",")[1] : s);
          };
          reader.onerror = reject;
          reader.readAsDataURL(blob);
        });
      } else {
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        const FileSystem = require("expo-file-system");
        base64 = await FileSystem.readAsStringAsync(asset.uri, { encoding: FileSystem.EncodingType.Base64 });
      }

      setUploadProgress({ pct: 45, label: `UPLOADING ${((sizeBytes || 0) / 1_048_576).toFixed(1)} MB\u2026` });
      setBusy("upload");
      await api<any>(`/coach/videos/upload?key=${encodeURIComponent(key)}`, {
        method: "POST",
        body: {
          filename: asset.name,
          mime_type: asset.mimeType || "video/mp4",
          data_base64: base64,
          title: asset.name.replace(/\.[^.]+$/, ""),
          make_preferred: true,
        },
      } as any);
      setUploadProgress({ pct: 100, label: "DONE" });
      await onReload();
      setTimeout(() => setUploadProgress(null), 800);
    } catch (e: any) {
      setUploadProgress(null);
      Alert.alert("Upload failed", e?.message || "Something went wrong");
    } finally {
      setBusy(null);
    }
  };

  return (
    <ScrollView contentContainerStyle={styles.detailContent} testID="videos-detail">
      <View style={styles.detailHeader}>
        <View style={{ flex: 1 }}>
          <Text style={styles.detailTitle}>{detail.display_name}</Text>
          <Text style={styles.detailSub}>
            Preferred: <Text style={{ color: theme.color.brand, fontWeight: "800" }}>{preferred.toUpperCase()}</Text>
            {"  ·  "}Last reviewed: {fmtDate(detail.last_reviewed_at)}
          </Text>
        </View>
        <Pressable testID="detail-rescan" onPress={rescan} style={styles.btnGhost} disabled={busy != null}>
          <Ionicons name="refresh" size={14} color={theme.color.brand} />
          <Text style={styles.btnGhostText}>RE-SCAN YOUTUBE</Text>
        </Pressable>
      </View>

      {/* Currently displayed */}
      <Text style={styles.sectionTitle}>CURRENTLY DISPLAYED TO CLIENT</Text>
      <View style={styles.previewBox}>
        <ExerciseVideoPlayer exerciseName={detail.display_name} testIDPrefix="detail-preview" />
      </View>

      {/* Slots */}
      <Text style={styles.sectionTitle}>VIDEO SLOTS</Text>
      <View style={{ gap: 12 }}>
        {SLOTS.map((s) => {
          const slot: Slot | null = detail[s.key] || null;
          const isPreferred = preferred === s.key;
          const has = !!slot?.video_id || !!slot?.video_url;
          const isUploadSlot = (s as any).uploadable;
          return (
            <View key={s.key} style={[styles.slotCard, s.disabled && { opacity: 0.55 }]}>
              <View style={styles.slotHeader}>
                <Ionicons name={s.icon} size={16} color={theme.color.brand} />
                <Text style={styles.slotLabel}>{s.label}</Text>
                {isPreferred && has ? <Text style={styles.preferredBadge}>PREFERRED</Text> : null}
                {s.disabled ? <Text style={styles.comingSoon}>PHASE D</Text> : null}
                {isUploadSlot && !has ? <Text style={[styles.comingSoon, { color: theme.color.brand }]}>MP4 · MAX 10MB</Text> : null}
              </View>
              {has ? (
                <>
                  <View style={styles.slotContent}>
                    <View style={styles.slotThumb}>
                      {slot?.thumbnail_url && Platform.OS === "web"
                        ? React.createElement("img", { src: slot.thumbnail_url, style: { width: "100%", height: "100%", objectFit: "cover", display: "block" }, alt: slot.title || "" })
                        : <Ionicons name={isUploadSlot ? "cloud-done" : "videocam"} size={24} color={isUploadSlot ? theme.color.brand : theme.color.textMuted} />}
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.slotTitle} numberOfLines={2}>{slot?.title || slot?.video_id || slot?.video_url}</Text>
                      <Text style={styles.slotMeta}>
                        {slot?.channel || slot?.channel_hint || "—"}
                        {"  ·  "}
                        <Text style={{ color: approvalColor(slot?.approval_status) }}>{(slot?.approval_status || "—").toUpperCase()}</Text>
                        {slot?.added_at ? `  ·  ${fmtDate(slot.added_at)}` : ""}
                        {isUploadSlot && (slot as any)?.size_bytes ? `  ·  ${((slot as any).size_bytes / 1_048_576).toFixed(1)} MB` : ""}
                      </Text>
                      {slot?.notes ? <Text style={styles.slotNotes}>{slot.notes}</Text> : null}
                    </View>
                  </View>
                  <View style={styles.slotActions}>
                    {slot?.approval_status !== "approved" && (
                      <Pressable testID={`slot-${s.key}-approve`} onPress={() => setApproval(s.key, "approved")} style={[styles.actBtn, { backgroundColor: theme.color.green }]}>
                        <Ionicons name="checkmark" size={13} color="#fff" />
                        <Text style={styles.actBtnText}>APPROVE</Text>
                      </Pressable>
                    )}
                    {slot?.approval_status !== "rejected" && (
                      <Pressable testID={`slot-${s.key}-reject`} onPress={() => setApproval(s.key, "rejected")} style={[styles.actBtn, { backgroundColor: theme.color.red }]}>
                        <Ionicons name="close" size={13} color="#fff" />
                        <Text style={styles.actBtnText}>REJECT</Text>
                      </Pressable>
                    )}
                    {!isPreferred && (
                      <Pressable testID={`slot-${s.key}-prefer`} onPress={() => setPreferred(s.key)} style={[styles.actBtn, { backgroundColor: theme.color.brand }]}>
                        <Ionicons name="star" size={13} color="#fff" />
                        <Text style={styles.actBtnText}>MARK PREFERRED</Text>
                      </Pressable>
                    )}
                    {isUploadSlot && (
                      <Pressable testID={`slot-${s.key}-replace`} onPress={uploadCustomVideo} style={[styles.actBtn, { backgroundColor: theme.color.brand }]} disabled={!!uploadProgress}>
                        <Ionicons name="refresh" size={13} color="#fff" />
                        <Text style={styles.actBtnText}>REPLACE</Text>
                      </Pressable>
                    )}
                    <Pressable testID={`slot-${s.key}-delete`} onPress={() => deleteSlot(s.key)} style={[styles.actBtn, styles.actBtnGhost]}>
                      <Ionicons name="trash-outline" size={13} color={theme.color.red} />
                      <Text style={[styles.actBtnText, { color: theme.color.red }]}>DELETE</Text>
                    </Pressable>
                  </View>
                </>
              ) : isUploadSlot ? (
                <>
                  <Text style={styles.slotEmpty}>Upload your own coaching clip (MP4/MOV/WebM · max 10 MB). It becomes the preferred video the moment it uploads.</Text>
                  {uploadProgress ? (
                    <View style={styles.uploadProgressRow}>
                      <ActivityIndicator size="small" color={theme.color.brand} />
                      <Text style={styles.uploadProgressText}>{uploadProgress.label}</Text>
                    </View>
                  ) : (
                    <Pressable testID={`slot-${s.key}-upload`} onPress={uploadCustomVideo} style={[styles.actBtn, { backgroundColor: theme.color.brand, alignSelf: "flex-start", marginTop: 10 }]}>
                      <Ionicons name="cloud-upload" size={14} color="#fff" />
                      <Text style={styles.actBtnText}>UPLOAD CUSTOM VIDEO</Text>
                    </Pressable>
                  )}
                </>
              ) : (
                <Text style={styles.slotEmpty}>{s.disabled ? "Not available for this workout." : "No video set. Paste a YouTube URL below to add one."}</Text>
              )}
            </View>
          );
        })}
      </View>

      {/* Paste custom URL */}
      <Text style={styles.sectionTitle}>ADD OR REPLACE A VIDEO</Text>
      <View style={styles.urlBox}>
        <View style={styles.slotSelector}>
          {[
            { k: "custom_url", l: "CUSTOM URL" },
            { k: "alternative", l: "ALTERNATIVE" },
            { k: "youtube_backup", l: "BACKUP" },
          ].map((opt) => (
            <Pressable
              key={opt.k}
              testID={`slot-target-${opt.k}`}
              onPress={() => setSlotForUrl(opt.k as any)}
              style={[styles.chip, slotForUrl === opt.k && styles.chipActive]}
            >
              <Text style={[styles.chipText, slotForUrl === opt.k && { color: "#fff" }]}>{opt.l}</Text>
            </Pressable>
          ))}
        </View>
        <View style={{ flexDirection: "row", gap: 8, alignItems: "center" }}>
          <TextInput
            testID="detail-url-input"
            style={styles.urlInput}
            placeholder="Paste YouTube URL (youtube.com/watch?v=… or youtu.be/…)"
            placeholderTextColor={theme.color.textDim}
            value={urlInput}
            onChangeText={setUrlInput}
            autoCapitalize="none"
            autoCorrect={false}
          />
          <Pressable testID="detail-url-submit" onPress={setSlot} style={styles.btnPrimary} disabled={busy != null}>
            <Text style={styles.btnPrimaryText}>SAVE</Text>
          </Pressable>
        </View>
      </View>

      {/* Variants */}
      <Text style={styles.sectionTitle}>PER-LOCATION VARIANTS</Text>
      <Text style={styles.sectionSub}>Optionally show a different video when the client is at HOME, in a HOTEL gym, or a full GYM.</Text>
      <View style={{ gap: 12 }}>
        {VARIANTS.map((v) => {
          const slot = (detail.variants || {})[v];
          const has = !!slot?.video_id || !!slot?.video_url;
          return (
            <View key={v} style={styles.slotCard}>
              <View style={styles.slotHeader}>
                <Ionicons name={v === "home" ? "home" : v === "hotel" ? "bed" : "barbell"} size={16} color={theme.color.brand} />
                <Text style={styles.slotLabel}>{v.toUpperCase()}</Text>
              </View>
              {has ? (
                <>
                  <View style={styles.slotContent}>
                    <View style={styles.slotThumb}>
                      {slot?.thumbnail_url && Platform.OS === "web"
                        ? React.createElement("img", { src: slot.thumbnail_url, style: { width: "100%", height: "100%", objectFit: "cover" }, alt: "" })
                        : <Ionicons name="videocam" size={20} color={theme.color.textMuted} />}
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.slotTitle} numberOfLines={2}>{slot?.title || slot?.video_id || slot?.video_url}</Text>
                      <Text style={styles.slotMeta}>{slot?.channel || "—"}  ·  {fmtDate(slot?.added_at)}</Text>
                    </View>
                  </View>
                  <View style={styles.slotActions}>
                    <Pressable testID={`variant-${v}-delete`} onPress={() => deleteVariant(v)} style={[styles.actBtn, styles.actBtnGhost]}>
                      <Ionicons name="trash-outline" size={13} color={theme.color.red} />
                      <Text style={[styles.actBtnText, { color: theme.color.red }]}>REMOVE OVERRIDE</Text>
                    </Pressable>
                  </View>
                </>
              ) : (
                <>
                  <Text style={styles.slotEmpty}>Uses the default video. Paste a URL below to override for {v.toUpperCase()}.</Text>
                  <View style={{ flexDirection: "row", gap: 8, alignItems: "center", marginTop: 8 }}>
                    <TextInput
                      testID={`variant-${v}-input`}
                      style={styles.urlInput}
                      placeholder={`YouTube URL for ${v}`}
                      placeholderTextColor={theme.color.textDim}
                      value={variantUrls[v] || ""}
                      onChangeText={(t) => setVariantUrls((s) => ({ ...s, [v]: t }))}
                      autoCapitalize="none"
                      autoCorrect={false}
                    />
                    <Pressable testID={`variant-${v}-submit`} onPress={() => setVariant(v)} style={styles.btnPrimary} disabled={busy != null}>
                      <Text style={styles.btnPrimaryText}>SET</Text>
                    </Pressable>
                  </View>
                </>
              )}
            </View>
          );
        })}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  master: { flex: 1, backgroundColor: theme.color.surface2 },
  masterHeader: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    padding: 20, paddingBottom: 12,
  },
  h1: { color: theme.color.text, fontSize: 20, fontWeight: "900", letterSpacing: 2 },
  addBtn: {
    width: 34, height: 34, borderRadius: 17,
    backgroundColor: theme.color.brandTint,
    alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: theme.color.brand,
  },
  searchRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    marginHorizontal: 12, paddingHorizontal: 12, paddingVertical: 8,
    backgroundColor: theme.color.surface3, borderRadius: 8,
    borderWidth: 1, borderColor: theme.color.border,
  },
  searchInput: { flex: 1, color: theme.color.text, fontSize: 13, outlineWidth: 0 } as any,

  empty: { color: theme.color.textMuted, textAlign: "center", padding: 30 },
  itemRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    padding: 10,
    backgroundColor: theme.color.surface3,
    borderRadius: 8,
    borderWidth: 1, borderColor: theme.color.border,
  },
  itemRowActive: { borderColor: theme.color.brand, backgroundColor: theme.color.brandTint },
  itemThumb: {
    width: 60, height: 34, borderRadius: 4, overflow: "hidden",
    backgroundColor: "#000", alignItems: "center", justifyContent: "center",
  },
  itemName: { color: theme.color.text, fontSize: 13, fontWeight: "700" },
  itemMetaRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 3 },
  statusDot: { width: 6, height: 6, borderRadius: 3 },
  itemMeta: { color: theme.color.textDim, fontSize: 11, fontWeight: "800", letterSpacing: 1 },
  badge: {
    color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 1,
    paddingHorizontal: 5, paddingVertical: 2,
    backgroundColor: theme.color.brandTint, borderRadius: 3,
  },

  detailEmpty: { flex: 1, alignItems: "center", justifyContent: "center", gap: 10 },
  detailEmptyText: { color: theme.color.textMuted, fontSize: 13 },
  detailContent: { padding: 24, paddingBottom: 60, gap: 8 },
  detailHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 8 },
  detailTitle: { color: theme.color.text, fontSize: 22, fontWeight: "900", letterSpacing: 1 },
  detailSub: { color: theme.color.textMuted, fontSize: 12, marginTop: 4 },

  sectionTitle: { color: theme.color.text, fontSize: 11, fontWeight: "800", letterSpacing: 2, marginTop: 20, marginBottom: 10 },
  sectionSub: { color: theme.color.textMuted, fontSize: 12, marginTop: -4, marginBottom: 10 },

  previewBox: { maxWidth: 480 },
  slotCard: { padding: 14, backgroundColor: theme.color.surface2, borderRadius: 10, borderWidth: 1, borderColor: theme.color.border },
  slotHeader: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 8 },
  slotLabel: { color: theme.color.text, fontSize: 11, fontWeight: "800", letterSpacing: 1.5 },
  preferredBadge: { color: "#fff", fontSize: 11, fontWeight: "800", letterSpacing: 1, paddingHorizontal: 6, paddingVertical: 2, backgroundColor: theme.color.brand, borderRadius: 3, marginLeft: "auto" },
  comingSoon: { color: theme.color.textDim, fontSize: 11, fontWeight: "800", letterSpacing: 1, marginLeft: "auto" },
  slotContent: { flexDirection: "row", gap: 12, alignItems: "flex-start" },
  slotThumb: { width: 96, height: 54, borderRadius: 4, overflow: "hidden", backgroundColor: "#000", alignItems: "center", justifyContent: "center" },
  slotTitle: { color: theme.color.text, fontSize: 13, fontWeight: "700" },
  slotMeta: { color: theme.color.textMuted, fontSize: 11, marginTop: 3 },
  slotNotes: { color: theme.color.textDim, fontSize: 11, marginTop: 4, fontStyle: "italic" },
  slotEmpty: { color: theme.color.textMuted, fontSize: 12, fontStyle: "italic" },
  uploadProgressRow: { flexDirection: "row", alignItems: "center", gap: 10, marginTop: 12 },
  uploadProgressText: { color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 1.5 },
  slotActions: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 10 },
  actBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6 },
  actBtnGhost: { backgroundColor: "transparent", borderWidth: 1, borderColor: theme.color.red },
  actBtnText: { color: "#fff", fontSize: 11, fontWeight: "800", letterSpacing: 1 },

  urlBox: { padding: 14, backgroundColor: theme.color.surface2, borderRadius: 10, borderWidth: 1, borderColor: theme.color.border, gap: 10 },
  slotSelector: { flexDirection: "row", gap: 6 },
  chip: { paddingHorizontal: 12, paddingVertical: 6, backgroundColor: theme.color.surface3, borderRadius: 6, borderWidth: 1, borderColor: theme.color.border },
  chipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipText: { color: theme.color.textMuted, fontSize: 11, fontWeight: "800", letterSpacing: 1 },
  urlInput: {
    flex: 1, color: theme.color.text, fontSize: 13,
    paddingHorizontal: 12, paddingVertical: 10,
    backgroundColor: theme.color.surface3,
    borderRadius: 6, borderWidth: 1, borderColor: theme.color.border,
    outlineWidth: 0,
  } as any,

  btnPrimary: { paddingHorizontal: 18, paddingVertical: 10, borderRadius: 6, backgroundColor: theme.color.brand, alignItems: "center" },
  btnPrimaryText: { color: "#fff", fontSize: 11, fontWeight: "800", letterSpacing: 1.5 },
  btnGhost: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 6, borderWidth: 1, borderColor: theme.color.brand },
  btnGhostText: { color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 1.5 },

  modalRoot: { flex: 1, alignItems: "center", justifyContent: "center" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.7)" },
  modalCard: { width: 400, maxWidth: "92%", padding: 20, backgroundColor: theme.color.surface2, borderRadius: 12, borderWidth: 1, borderColor: theme.color.border, gap: 14 },
  modalTitle: { color: theme.color.text, fontSize: 14, fontWeight: "800", letterSpacing: 2 },
  modalInput: { color: theme.color.text, fontSize: 14, padding: 12, backgroundColor: theme.color.surface3, borderRadius: 6, borderWidth: 1, borderColor: theme.color.border, outlineWidth: 0 } as any,
});
