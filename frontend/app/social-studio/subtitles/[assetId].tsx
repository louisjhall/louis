/**
 * Social Studio — Subtitle Editor (Whisper-1 + burn-in).
 *
 * Flow:
 *   1. Fetch asset + any prior subtitle doc.
 *   2. If no subtitle → GENERATE SUBTITLES button kicks off Whisper.
 *   3. When status flips to "ready"/"edited" → segment list is shown.
 *   4. Edit each segment's text (V1 keeps timing untouched).
 *   5. SAVE persists via PATCH; BURN triggers ffmpeg render → burned video streamable.
 *   6. Download SRT / VTT / burned MP4.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator, Alert, Linking, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api, buildStreamUrl, API_BASE, getToken } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Asset = {
  id: string; post_id: string; kind: string; mime?: string;
  duration_seconds?: number; size_bytes?: number; status?: string;
  subtitle_id?: string | null;
};

type Segment = { index: number; start: number; end: number; text: string };

type Subtitle = {
  id: string; asset_id: string; post_id?: string;
  status: string;                         // pending | generating | ready | edited | failed | burning | burn_failed
  provider?: string;
  language?: string;
  duration?: number;
  text?: string;
  srt?: string | null;
  vtt?: string | null;
  segments?: Segment[];
  error?: string | null;
  burned_video_path?: string | null;
  burned_at?: string | null;
  created_at?: string;
  updated_at?: string;
};

export default function SubtitleEditor() {
  const { assetId } = useLocalSearchParams<{ assetId: string }>();
  const router = useRouter();

  const [asset, setAsset] = useState<Asset | null>(null);
  const [streamUrl, setStreamUrl] = useState<string | null>(null);
  const [burnedUrl, setBurnedUrl] = useState<string | null>(null);
  const [sub, setSub] = useState<Subtitle | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);          // action label
  const [dirty, setDirty] = useState(false);
  const [segs, setSegs] = useState<Segment[]>([]);
  const [showBurned, setShowBurned] = useState(false);
  const pollTimer = useRef<any>(null);

  // ------------------------------------------------------------------------
  // Loading + polling
  // ------------------------------------------------------------------------
  const load = useCallback(async () => {
    try {
      const r = await api<{ asset: Asset }>(`/social/assets/${assetId}`);
      setAsset(r.asset);
      const s = await api<{ subtitle: Subtitle | null }>(`/social/assets/${assetId}/subtitles`);
      setSub(s.subtitle);
      setSegs(s.subtitle?.segments || []);
      const url = await buildStreamUrl(`/social/assets/${assetId}/stream`);
      setStreamUrl(url);
      if (s.subtitle?.burned_video_path) {
        const b = await buildStreamUrl(`/social/subtitles/${s.subtitle.id}/burned/stream`);
        setBurnedUrl(b);
      }
    } catch (e: any) {
      Alert.alert("Load failed", e?.message || "");
    } finally { setLoading(false); }
  }, [assetId]);

  useEffect(() => { load(); }, [load]);

  // Poll if job is in-flight
  useEffect(() => {
    if (!sub) return;
    if (["pending", "generating", "burning"].includes(sub.status)) {
      pollTimer.current = setInterval(async () => {
        try {
          const r = await api<{ subtitle: Subtitle }>(`/social/subtitles/${sub.id}`);
          setSub(r.subtitle);
          if (!dirty) setSegs(r.subtitle.segments || []);
          if (r.subtitle.burned_video_path) {
            const b = await buildStreamUrl(`/social/subtitles/${sub.id}/burned/stream`);
            setBurnedUrl(b);
          }
          if (!["pending", "generating", "burning"].includes(r.subtitle.status)) {
            clearInterval(pollTimer.current);
            pollTimer.current = null;
          }
        } catch { /* ignore transient */ }
      }, 2000);
    }
    return () => { if (pollTimer.current) { clearInterval(pollTimer.current); pollTimer.current = null; } };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sub?.id, sub?.status]);

  // ------------------------------------------------------------------------
  // Actions
  // ------------------------------------------------------------------------
  const generate = async () => {
    setBusy("generate");
    try {
      const r = await api<{ subtitle: Subtitle }>(`/social/assets/${assetId}/subtitles/generate`, { method: "POST", body: {} });
      setSub(r.subtitle);
      setSegs(r.subtitle.segments || []);
      setDirty(false);
    } catch (e: any) {
      Alert.alert("Generation failed", e?.message || "Try again");
    } finally { setBusy(null); }
  };

  const editSegment = (i: number, text: string) => {
    setSegs((cur) => cur.map((s) => s.index === i ? { ...s, text } : s));
    setDirty(true);
  };

  const save = async () => {
    if (!sub) return;
    setBusy("save");
    try {
      const r = await api<{ subtitle: Subtitle }>(`/social/subtitles/${sub.id}`, {
        method: "PATCH",
        body: { segments: segs.map((s) => ({ index: s.index, start: s.start, end: s.end, text: s.text })) },
      });
      setSub(r.subtitle);
      setSegs(r.subtitle.segments || segs);
      setDirty(false);
      setBurnedUrl(null);      // any old burn is invalidated
    } catch (e: any) {
      Alert.alert("Save failed", e?.message || "");
    } finally { setBusy(null); }
  };

  const burn = async () => {
    if (!sub) return;
    if (dirty) {
      Alert.alert("Save first", "Save your edits before burning subtitles into the video.");
      return;
    }
    setBusy("burn");
    try {
      await api<{ ok: boolean }>(`/social/subtitles/${sub.id}/burn`, { method: "POST", body: {} });
      // Poll begins automatically because status flips to "burning"
      const r = await api<{ subtitle: Subtitle }>(`/social/subtitles/${sub.id}`);
      setSub(r.subtitle);
    } catch (e: any) {
      Alert.alert("Burn failed", e?.message || "");
    } finally { setBusy(null); }
  };

  const download = async (fmt: "srt" | "vtt") => {
    if (!sub) return;
    try {
      const token = await getToken();
      const url = `${API_BASE}/social/subtitles/${sub.id}/download?fmt=${fmt}&token=${encodeURIComponent(token || "")}`;
      if (Platform.OS === "web") {
        // @ts-ignore native window
        window.open(url, "_blank");
      } else {
        Linking.openURL(url).catch(() => {});
      }
    } catch (e: any) {
      Alert.alert("Download failed", e?.message || "");
    }
  };

  const downloadBurned = async () => {
    if (!sub || !sub.burned_video_path) return;
    try {
      const token = await getToken();
      const url = `${API_BASE}/social/subtitles/${sub.id}/burned/stream?token=${encodeURIComponent(token || "")}`;
      if (Platform.OS === "web") window.open(url, "_blank");
      else Linking.openURL(url).catch(() => {});
    } catch (e: any) {
      Alert.alert("Download failed", e?.message || "");
    }
  };

  // ------------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------------
  const status = sub?.status || "none";
  const isJobRunning = status === "pending" || status === "generating" || status === "burning";
  const hasSubs = ["ready", "edited"].includes(status);
  const hasBurn = !!sub?.burned_video_path;

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <View style={styles.top}>
        <Pressable onPress={() => router.replace("/social-studio")} hitSlop={12}>
          <Ionicons name="chevron-back" size={26} color={theme.color.text} />
        </Pressable>
        <Text style={styles.topT}>SUBTITLE EDITOR</Text>
        <View style={{ width: 26 }} />
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>
      ) : (
        <ScrollView contentContainerStyle={{ padding: 16, gap: 14, paddingBottom: 60 }}>
          {/* Video preview */}
          <View style={styles.videoWrap}>
            {Platform.OS === "web" && (showBurned && burnedUrl ? burnedUrl : streamUrl) ? (
              // @ts-ignore native <video>
              <video
                key={showBurned ? "burned" : "orig"}
                src={showBurned && burnedUrl ? burnedUrl : (streamUrl || "")}
                controls
                playsInline
                style={{ width: "100%", height: 420, background: "#000", objectFit: "contain" }}
              />
            ) : (
              <View style={styles.videoFallback}>
                <Ionicons name="film" size={40} color={theme.color.brand} />
                <Text style={styles.videoFallbackT}>Video preview shows on native builds after Publish.</Text>
                {asset?.duration_seconds ? <Text style={styles.videoMeta}>{Math.round(asset.duration_seconds)}s</Text> : null}
              </View>
            )}
            {hasBurn ? (
              <View style={styles.previewToggleRow}>
                <ToggleChip label="ORIGINAL" active={!showBurned} onPress={() => setShowBurned(false)} />
                <ToggleChip label="WITH SUBTITLES" active={showBurned} onPress={() => setShowBurned(true)} />
              </View>
            ) : null}
          </View>

          {/* Status banner */}
          <View style={[styles.statusBanner, statusBannerStyle(status)]}>
            <Ionicons name={statusIcon(status) as any} size={16} color="#fff" />
            <Text style={styles.statusBannerT}>{statusLabel(status)}</Text>
            {isJobRunning ? <ActivityIndicator color="#fff" size="small" style={{ marginLeft: 8 }} /> : null}
          </View>
          {sub?.error ? <Text style={styles.errorLine}>{sub.error}</Text> : null}

          {/* Empty state / generate */}
          {!sub || status === "failed" ? (
            <View style={styles.card}>
              <Text style={styles.sect}>WHISPER-1</Text>
              <Text style={styles.hint}>
                Atlas will transcribe your recording using OpenAI Whisper-1, produce SRT + VTT,
                and let you tweak each line before burning captions into the video.
              </Text>
              <Pressable disabled={!!busy} onPress={generate} style={[styles.primaryBtn, busy && { opacity: 0.5 }]} testID="sub-generate">
                {busy === "generate" ? <ActivityIndicator color="#fff" /> : (
                  <>
                    <Ionicons name="sparkles" size={16} color="#fff" />
                    <Text style={styles.primaryBtnT}>GENERATE SUBTITLES</Text>
                  </>
                )}
              </Pressable>
            </View>
          ) : null}

          {/* Segments editor */}
          {hasSubs ? (
            <View style={styles.card}>
              <View style={styles.editorHeader}>
                <Text style={styles.sect}>SEGMENTS · {segs.length}</Text>
                {dirty ? <Text style={styles.dirtyDot}>· UNSAVED</Text> : null}
              </View>
              {segs.length === 0 ? (
                <Text style={styles.hint}>Whisper returned no segments. Try re-generating.</Text>
              ) : (
                segs.map((s) => (
                  <View key={s.index} style={styles.segRow} testID={`seg-${s.index}`}>
                    <Text style={styles.segTime}>{fmt(s.start)} → {fmt(s.end)}</Text>
                    <TextInput
                      value={s.text}
                      onChangeText={(t) => editSegment(s.index, t)}
                      style={styles.segInput}
                      multiline
                      placeholder="(empty)"
                      placeholderTextColor={theme.color.textDim}
                      testID={`seg-input-${s.index}`}
                    />
                  </View>
                ))
              )}

              <View style={styles.actionsRow}>
                <Pressable disabled={!!busy || !dirty} onPress={save} style={[styles.primaryBtn, (!dirty || !!busy) && { opacity: 0.4 }]} testID="sub-save">
                  {busy === "save" ? <ActivityIndicator color="#fff" /> : (<><Ionicons name="save" size={16} color="#fff" /><Text style={styles.primaryBtnT}>SAVE EDITS</Text></>)}
                </Pressable>
                <Pressable disabled={!!busy} onPress={generate} style={[styles.secondaryBtn, !!busy && { opacity: 0.4 }]}>
                  <Ionicons name="refresh" size={14} color={theme.color.text} /><Text style={styles.secondaryBtnT}>REGENERATE</Text>
                </Pressable>
              </View>

              <View style={styles.downloadRow}>
                <Pressable onPress={() => download("srt")} style={styles.downloadBtn} testID="dl-srt"><Ionicons name="download" size={14} color={theme.color.brand} /><Text style={styles.downloadT}>.SRT</Text></Pressable>
                <Pressable onPress={() => download("vtt")} style={styles.downloadBtn} testID="dl-vtt"><Ionicons name="download" size={14} color={theme.color.brand} /><Text style={styles.downloadT}>.VTT</Text></Pressable>
              </View>
            </View>
          ) : null}

          {/* Burn-in */}
          {hasSubs ? (
            <View style={styles.card}>
              <Text style={styles.sect}>BURN-IN EXPORT</Text>
              <Text style={styles.hint}>
                Bake the captions into a new MP4 with the clean CrewFit style (white text, bold, centred at 70% down).
                Good for TikTok / Reels — LinkedIn works fine with the .SRT sidecar.
              </Text>
              <Pressable disabled={!!busy || dirty || status === "burning"} onPress={burn} style={[styles.primaryBtn, (dirty || status === "burning") && { opacity: 0.4 }]} testID="sub-burn">
                {status === "burning" || busy === "burn" ? <ActivityIndicator color="#fff" /> : (
                  <>
                    <Ionicons name="flame" size={16} color="#fff" />
                    <Text style={styles.primaryBtnT}>{hasBurn ? "REBURN" : "BURN CAPTIONS INTO VIDEO"}</Text>
                  </>
                )}
              </Pressable>
              {status === "burn_failed" ? <Text style={styles.errorLine}>Burn failed: {sub?.error || "Try again"}</Text> : null}
              {hasBurn ? (
                <Pressable onPress={downloadBurned} style={styles.altBtn} testID="dl-burned">
                  <Ionicons name="download" size={14} color={theme.color.brand} />
                  <Text style={styles.altBtnT}>DOWNLOAD BURNED .MP4</Text>
                </Pressable>
              ) : null}
            </View>
          ) : null}

          {/* Meta */}
          <View style={styles.card}>
            <Text style={styles.sect}>DETAILS</Text>
            <Row k="LANGUAGE" v={sub?.language ? String(sub.language).toUpperCase() : "—"} />
            <Row k="DURATION" v={sub?.duration ? `${sub.duration.toFixed(1)}s` : (asset?.duration_seconds ? `${asset.duration_seconds}s` : "—")} />
            <Row k="PROVIDER" v={sub?.provider || "whisper-1"} />
            <Row k="STATUS" v={status.toUpperCase()} />
          </View>

          <Pressable onPress={() => router.replace("/social-studio")} style={styles.backBtn}>
            <Ionicons name="arrow-back" size={16} color={theme.color.brand} />
            <Text style={styles.backT}>BACK TO SOCIAL STUDIO</Text>
          </Pressable>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

// ---------- helpers --------------------------------------------------------

function fmt(sec: number): string {
  if (!sec && sec !== 0) return "0:00";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  const ms = Math.floor((sec - Math.floor(sec)) * 100);
  return `${m}:${String(s).padStart(2, "0")}.${String(ms).padStart(2, "0")}`;
}

function statusLabel(s: string): string {
  return ({
    none: "NO SUBTITLES YET",
    pending: "QUEUED",
    generating: "TRANSCRIBING WITH WHISPER-1",
    ready: "READY",
    edited: "EDITED · SAVED",
    failed: "TRANSCRIPTION FAILED",
    burning: "BURNING CAPTIONS INTO VIDEO",
    burn_failed: "BURN FAILED",
  } as Record<string, string>)[s] || s.toUpperCase();
}

function statusIcon(s: string): string {
  return ({
    generating: "sparkles", pending: "hourglass",
    ready: "checkmark-circle", edited: "checkmark-circle",
    failed: "warning", burning: "flame", burn_failed: "warning",
    none: "chatbubbles",
  } as Record<string, string>)[s] || "chatbubbles";
}

function statusBannerStyle(s: string): any {
  if (s === "ready" || s === "edited") return { backgroundColor: theme.color.green };
  if (s === "failed" || s === "burn_failed") return { backgroundColor: "#c94a4a" };
  if (s === "burning" || s === "generating" || s === "pending") return { backgroundColor: theme.color.brand };
  return { backgroundColor: theme.color.textDim };
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowK}>{k}</Text>
      <Text style={styles.rowV}>{v}</Text>
    </View>
  );
}

function ToggleChip({ label, active, onPress }: { label: string; active: boolean; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={[styles.toggleChip, active && styles.toggleChipOn]}>
      <Text style={[styles.toggleChipT, active && styles.toggleChipTOn]}>{label}</Text>
    </Pressable>
  );
}

// ---------- styles ---------------------------------------------------------

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  top: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 14, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  topT: { color: theme.color.text, fontSize: 14, letterSpacing: 2, fontWeight: "900" },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },

  videoWrap: { borderRadius: 12, overflow: "hidden", backgroundColor: "#000" },
  videoFallback: { height: 200, alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: theme.color.surface2 },
  videoFallbackT: { color: theme.color.textMuted, fontSize: 12, letterSpacing: 0.5, textAlign: "center", paddingHorizontal: 24 },
  videoMeta: { color: theme.color.textDim, fontSize: 11, letterSpacing: 1 },
  previewToggleRow: { flexDirection: "row", gap: 8, padding: 10, backgroundColor: theme.color.surface2 },
  toggleChip: { paddingHorizontal: 12, paddingVertical: 7, borderRadius: 20, backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border },
  toggleChipOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  toggleChipT: { color: theme.color.text, fontSize: 10, fontWeight: "900", letterSpacing: 1 },
  toggleChipTOn: { color: "#fff" },

  statusBanner: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 12, paddingVertical: 10, borderRadius: 10 },
  statusBannerT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.2 },
  errorLine: { color: "#f39a9a", fontSize: 11, fontStyle: "italic", marginTop: -4 },

  card: { backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, borderRadius: 12, padding: 14, gap: 8 },
  sect: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 2 },
  hint: { color: theme.color.textMuted, fontSize: 12, lineHeight: 18 },

  editorHeader: { flexDirection: "row", alignItems: "baseline", gap: 8 },
  dirtyDot: { color: theme.color.amber, fontSize: 10, fontWeight: "900", letterSpacing: 1 },

  segRow: { paddingVertical: 8, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.color.divider, gap: 4 },
  segTime: { color: theme.color.textDim, fontSize: 10, fontWeight: "800", letterSpacing: 1 },
  segInput: {
    backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border,
    borderRadius: 8, padding: 10, color: theme.color.text, fontSize: 14, minHeight: 44,
  },

  actionsRow: { flexDirection: "row", gap: 8, marginTop: 10, flexWrap: "wrap" },
  downloadRow: { flexDirection: "row", gap: 8, marginTop: 6 },
  downloadBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8, borderWidth: 1, borderColor: theme.color.brand, backgroundColor: theme.color.brandTint },
  downloadT: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1 },

  row: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 2 },
  rowK: { color: theme.color.textDim, fontSize: 11, letterSpacing: 1, fontWeight: "800" },
  rowV: { color: theme.color.text, fontSize: 12, fontWeight: "700" },

  primaryBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, marginTop: 6, backgroundColor: theme.color.brand, paddingVertical: 12, paddingHorizontal: 14, borderRadius: 10 },
  primaryBtnT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  secondaryBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, marginTop: 6, backgroundColor: theme.color.surface, paddingVertical: 12, paddingHorizontal: 14, borderRadius: 10, borderWidth: 1, borderColor: theme.color.border },
  secondaryBtnT: { color: theme.color.text, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  altBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingVertical: 12, borderRadius: 10, borderWidth: 1, borderColor: theme.color.brand, backgroundColor: theme.color.brandTint, marginTop: 8 },
  altBtnT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  backBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingVertical: 12, borderRadius: 10, borderWidth: 1, borderColor: theme.color.brand, backgroundColor: theme.color.brandTint },
  backT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
});
