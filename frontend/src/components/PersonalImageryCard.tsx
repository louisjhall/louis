/**
 * PersonalImageryCard — client-facing "Generate my personal CrewFit image"
 * flow. Shows the user's own personal images (pending / awaiting approval /
 * approved / rejected) and lets them queue a new one.
 *
 * Backend contract:
 *  - POST   /brand-images/personalise                     → kick off gen job
 *  - GET    /brand-images/personal/mine                   → list mine
 *  - GET    /brand-images/{id}/stream?token=...           → view
 *
 * Rate limit: backend blocks a second job while one is pending / awaiting
 * approval so the UI simply reflects that.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ActivityIndicator, Alert, TextInput,
} from "react-native";
import { Image } from "expo-image";
import { Ionicons } from "@expo/vector-icons";
import { api, API_BASE, getToken } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Personal = {
  id: string;
  status: "pending" | "generating" | "ready" | "pending_approval" | "failed" | "hidden";
  prompt?: string;
  context?: Record<string, string>;
  error?: string | null;
  created_at?: string;
};

export function PersonalImageryCard() {
  const [images, setImages] = useState<Personal[]>([]);
  const [busy, setBusy] = useState(false);
  const [hint, setHint] = useState("");
  const [token, setToken] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await api<{ images: Personal[] }>("/brand-images/personal/mine");
      setImages(r.images || []);
    } catch { /* silent */ }
    setToken(await getToken());
  }, []);

  useEffect(() => { load(); }, [load]);

  // Poll while any job is running
  useEffect(() => {
    const running = images.some((i) => ["pending", "generating"].includes(i.status));
    if (!running) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [images, load]);

  const inflight = images.find((i) => ["pending", "generating", "pending_approval"].includes(i.status));

  const generate = async () => {
    if (inflight) {
      Alert.alert("Already in progress", inflight.status === "pending_approval"
        ? "Your last request is awaiting coach approval."
        : "Please wait for your current request to finish.");
      return;
    }
    setBusy(true);
    try {
      await api<{ image: Personal }>("/brand-images/personalise", {
        method: "POST", body: hint.trim() ? { prompt_hint: hint.trim() } : {},
      });
      setHint("");
      await load();
      Alert.alert("Kicked off", "Atlas is generating your personal image. It will be visible on your home screen once your coach approves it.");
    } catch (e: any) {
      Alert.alert("Generation failed", e?.message || "Please try again");
    } finally { setBusy(false); }
  };

  return (
    <View style={styles.card}>
      <View style={styles.head}>
        <Ionicons name="color-palette" size={16} color={theme.color.brand} />
        <Text style={styles.headT}>PERSONAL IMAGERY</Text>
      </View>
      <Text style={styles.hint}>
        Ask Atlas for a personal CrewFit hero image tuned to your role, goal and
        training focus. It appears on your home screen once your coach approves it.
      </Text>

      <TextInput
        value={hint}
        onChangeText={setHint}
        placeholder="Focus (optional): e.g. recovery after night flight, marathon build"
        placeholderTextColor={theme.color.textDim}
        style={styles.input}
        multiline
        maxLength={140}
        editable={!inflight}
      />
      <Pressable
        onPress={generate}
        disabled={busy || !!inflight}
        style={[styles.btn, (busy || !!inflight) && { opacity: 0.5 }]}
        testID="personal-generate"
      >
        {busy ? <ActivityIndicator color="#fff" /> : (
          <>
            <Ionicons name="sparkles" size={16} color="#fff" />
            <Text style={styles.btnT}>
              {inflight ? (inflight.status === "pending_approval" ? "AWAITING COACH APPROVAL" : "GENERATING…") : "GENERATE MY PERSONAL IMAGE"}
            </Text>
          </>
        )}
      </Pressable>

      {images.length > 0 ? (
        <View style={{ marginTop: 12, gap: 8 }}>
          {images.map((img) => {
            const url = img.status === "ready" && token
              ? `${API_BASE}/brand-images/${img.id}/stream?token=${encodeURIComponent(token)}`
              : null;
            return (
              <View key={img.id} style={styles.row}>
                <View style={styles.thumbWrap}>
                  {url ? (
                    <Image source={{ uri: url }} style={styles.thumb} contentFit="cover" />
                  ) : (
                    <View style={[styles.thumb, styles.thumbPh]}>
                      <Ionicons
                        name={img.status === "failed" ? "warning" :
                              img.status === "pending_approval" ? "hourglass" : "sparkles"}
                        size={20} color={theme.color.textMuted}
                      />
                    </View>
                  )}
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowStatus}>{labelFor(img.status)}</Text>
                  <Text style={styles.rowDate} numberOfLines={1}>{img.created_at?.slice(0, 19).replace("T", " ")}</Text>
                  {img.error ? <Text style={styles.rowError} numberOfLines={2}>{img.error}</Text> : null}
                </View>
              </View>
            );
          })}
        </View>
      ) : null}
    </View>
  );
}

function labelFor(s: string): string {
  return ({
    pending: "QUEUED",
    generating: "GENERATING…",
    pending_approval: "AWAITING COACH APPROVAL",
    ready: "READY · ON YOUR HOME SCREEN",
    failed: "FAILED",
    hidden: "REJECTED / REMOVED",
  } as Record<string, string>)[s] || s.toUpperCase();
}

const styles = StyleSheet.create({
  card: { padding: 14, borderRadius: 12, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, marginTop: 12 },
  head: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 6 },
  headT: { color: theme.color.brand, fontSize: 10, letterSpacing: 2, fontWeight: "900", fontFamily: theme.font.textSemi },
  hint: { color: theme.color.textMuted, fontSize: 12, lineHeight: 18, marginBottom: 8, fontFamily: theme.font.text },
  input: {
    backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border,
    borderRadius: 8, padding: 10, color: theme.color.text, fontSize: 13, minHeight: 44,
    fontFamily: theme.font.text,
  },
  btn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, marginTop: 10, backgroundColor: theme.color.brand, paddingVertical: 12, borderRadius: 10 },
  btnT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.3, fontFamily: theme.font.textSemi },
  row: { flexDirection: "row", alignItems: "center", gap: 10, padding: 8, borderRadius: 8, backgroundColor: theme.color.surface },
  thumbWrap: { width: 50, height: 50, borderRadius: 8, overflow: "hidden", backgroundColor: theme.color.surface3 },
  thumb: { width: 50, height: 50 },
  thumbPh: { alignItems: "center", justifyContent: "center" },
  rowStatus: { color: theme.color.text, fontSize: 11, fontWeight: "900", letterSpacing: 1, fontFamily: theme.font.textSemi },
  rowDate: { color: theme.color.textMuted, fontSize: 10, fontFamily: theme.font.text, marginTop: 2 },
  rowError: { color: "#f39a9a", fontSize: 10, fontStyle: "italic", marginTop: 2 },
});
