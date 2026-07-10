/**
 * Social Studio — Subtitle Editor (stub).
 *
 * Post-recording landing that:
 *   • Streams the newly-saved video from the backend (auth-signed URL)
 *   • Triggers a stub subtitle-generation call (real Whisper integration ships next)
 *   • Provides a "Back to Social Studio" and "Generate Subtitles" button
 */
import React, { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Alert, Platform, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api, buildStreamUrl } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Asset = {
  id: string; post_id: string; kind: string; mime?: string;
  duration_seconds?: number; size_bytes?: number; status?: string;
  subtitle_id?: string | null;
};

export default function SubtitleEditorStub() {
  const { assetId } = useLocalSearchParams<{ assetId: string }>();
  const router = useRouter();
  const [asset, setAsset] = useState<Asset | null>(null);
  const [streamUrl, setStreamUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [gen, setGen] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api<{ asset: Asset }>(`/social/assets/${assetId}`);
      setAsset(r.asset);
      const s = await api<{ subtitle: any }>(`/social/assets/${assetId}/subtitles`);
      setGen(s.subtitle);
      const url = await buildStreamUrl(`/social/assets/${assetId}/stream`);
      setStreamUrl(url);
    } catch (e: any) {
      Alert.alert("Load failed", e?.message || "");
    } finally { setLoading(false); }
  }, [assetId]);

  useEffect(() => { load(); }, [load]);

  const generate = async () => {
    setBusy(true);
    try {
      const r = await api<any>(`/social/assets/${assetId}/subtitles/generate`, { method: "POST", body: {} });
      setGen(r.subtitle);
      Alert.alert(
        "Subtitles queued",
        "Real Whisper-1 subtitle generation ships in the next release. For now, a placeholder has been created so you can wire this into the workflow.",
      );
    } catch (e: any) {
      Alert.alert("Generation failed", e?.message || "");
    } finally { setBusy(false); }
  };

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
        <ScrollView contentContainerStyle={{ padding: 16, gap: 14 }}>
          <View style={styles.videoWrap}>
            {Platform.OS === "web" && streamUrl ? (
              // @ts-ignore native <video>
              <video src={streamUrl} controls playsInline style={{ width: "100%", height: 460, background: "#000", objectFit: "contain" }} />
            ) : (
              <View style={styles.videoFallback}>
                <Ionicons name="film" size={44} color={theme.color.brand} />
                <Text style={styles.videoFallbackT}>Video preview available on device build.</Text>
                {asset?.duration_seconds ? <Text style={styles.videoMeta}>{Math.round(asset.duration_seconds)}s · {((asset.size_bytes || 0) / (1024 * 1024)).toFixed(1)} MB</Text> : null}
              </View>
            )}
          </View>

          <View style={styles.card}>
            <Text style={styles.sect}>ASSET</Text>
            <Row k="ID" v={asset?.id?.slice(0, 8) || "—"} />
            <Row k="KIND" v={(asset?.kind || "video").toUpperCase()} />
            <Row k="DURATION" v={asset?.duration_seconds ? `${Math.round(asset.duration_seconds)}s` : "—"} />
            <Row k="SIZE" v={asset?.size_bytes ? `${(asset.size_bytes / (1024 * 1024)).toFixed(2)} MB` : "—"} />
            <Row k="STATUS" v={(asset?.status || "draft").toUpperCase()} />
          </View>

          <View style={styles.card}>
            <Text style={styles.sect}>SUBTITLES</Text>
            {gen ? (
              <>
                <Row k="STATE" v={(gen.status || "pending").toUpperCase()} />
                <Row k="PROVIDER" v={gen.provider || "whisper-1-stub"} />
                <Text style={styles.hint}>
                  Placeholder record created. When the real Whisper-1 pipeline lands you&apos;ll be able to
                  edit .SRT segments, restyle captions, and burn-in to the exported video from here.
                </Text>
              </>
            ) : (
              <Text style={styles.hint}>No subtitle job yet. Tap Generate to create one.</Text>
            )}
            <Pressable disabled={busy} onPress={generate} style={[styles.primaryBtn, busy && { opacity: 0.5 }]} testID="sub-generate">
              {busy ? <ActivityIndicator color="#fff" /> : (
                <>
                  <Ionicons name="sparkles" size={16} color="#fff" />
                  <Text style={styles.primaryBtnT}>{gen ? "REGENERATE" : "GENERATE SUBTITLES"}</Text>
                </>
              )}
            </Pressable>
          </View>

          <Pressable onPress={() => router.replace("/social-studio")} style={styles.altBtn}>
            <Ionicons name="arrow-back" size={16} color={theme.color.brand} />
            <Text style={styles.altBtnT}>BACK TO SOCIAL STUDIO</Text>
          </Pressable>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowK}>{k}</Text>
      <Text style={styles.rowV}>{v}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  top: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 14, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  topT: { color: theme.color.text, fontSize: 14, letterSpacing: 2, fontWeight: "900" },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  videoWrap: { borderRadius: 12, overflow: "hidden", backgroundColor: "#000" },
  videoFallback: { height: 220, alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: theme.color.surface2 },
  videoFallbackT: { color: theme.color.textMuted, fontSize: 12, letterSpacing: 0.5, textAlign: "center", paddingHorizontal: 24 },
  videoMeta: { color: theme.color.textDim, fontSize: 11, letterSpacing: 1 },

  card: { backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, borderRadius: 12, padding: 14, gap: 8 },
  sect: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 2, marginBottom: 4 },
  row: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 2 },
  rowK: { color: theme.color.textDim, fontSize: 11, letterSpacing: 1, fontWeight: "800" },
  rowV: { color: theme.color.text, fontSize: 12, fontWeight: "700" },
  hint: { color: theme.color.textMuted, fontSize: 12, lineHeight: 18, marginTop: 6 },

  primaryBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, marginTop: 10, backgroundColor: theme.color.brand, paddingVertical: 12, borderRadius: 10 },
  primaryBtnT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  altBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingVertical: 12, borderRadius: 10, borderWidth: 1, borderColor: theme.color.brand, backgroundColor: theme.color.brandTint },
  altBtnT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
});
