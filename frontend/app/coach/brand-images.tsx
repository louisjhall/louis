/**
 * Coach · Brand Images admin screen.
 *
 * Lists every entry in `crewfit_images` with:
 *   - preview (streaming)
 *   - key + category + context chips
 *   - status + is_default badges
 *   - Regenerate / Hide / Set-Default / Restore
 *
 * Also exposes a big SEED LIBRARY button when the collection is empty and a
 * status ticker while jobs are running.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator, Alert, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View,
} from "react-native";
import { Image } from "expo-image";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useFocusEffect } from "expo-router";
import { api, API_BASE, getToken } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type BrandImage = {
  id: string; key: string; category: string;
  status: "pending" | "generating" | "ready" | "failed" | "hidden" | "pending_approval";
  is_default: boolean; label?: string;
  context?: Record<string, string>;
  prompt?: string;
  size_bytes?: number;
  error?: string | null;
  updated_at?: string;
  personalised_for?: string | null;
};

export default function BrandImagesScreen() {
  const router = useRouter();
  const [images, setImages] = useState<BrandImage[]>([]);
  const [pending, setPending] = useState<BrandImage[]>([]);
  const [loading, setLoading] = useState(true);
  const [showHidden, setShowHidden] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [seeding, setSeeding] = useState(false);
  const [token, setToken] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [libR, pendR] = await Promise.all([
        api<{ images: BrandImage[] }>(`/brand-images?include_hidden=${showHidden ? "true" : "false"}&include_personal=true`),
        api<{ images: BrandImage[] }>(`/brand-images/pending-approval`).catch(() => ({ images: [] })),
      ]);
      setImages(libR.images || []);
      setPending(pendR.images || []);
    } catch (e: any) {
      Alert.alert("Load failed", e?.message || "");
    } finally { setLoading(false); }
    setToken(await getToken());
  }, [showHidden]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  // Auto-poll while any job is generating/pending
  useEffect(() => {
    const running = images.some((i) => i.status === "pending" || i.status === "generating");
    if (!running) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [images, load]);

  const runningCount = useMemo(() => images.filter((i) => i.status === "pending" || i.status === "generating").length, [images]);

  const doSeed = async () => {
    setSeeding(true);
    try {
      const r = await api<{ created: string[]; count: number }>("/brand-images/seed", { method: "POST", body: {} });
      Alert.alert("Seed started", r.count > 0 ? `${r.count} images queued for Nano Banana.` : "Library already seeded.");
      await load();
    } catch (e: any) {
      Alert.alert("Seed failed", e?.message || "");
    } finally { setSeeding(false); }
  };

  const doRegen = async (img: BrandImage) => {
    setBusyId(img.id);
    try {
      await api(`/brand-images/${img.id}/regenerate`, { method: "POST", body: {} });
      await load();
    } catch (e: any) { Alert.alert("Regenerate failed", e?.message || ""); }
    finally { setBusyId(null); }
  };

  const doHide = async (img: BrandImage) => {
    setBusyId(img.id);
    try {
      await api(`/brand-images/${img.id}`, { method: "DELETE" });
      await load();
    } catch (e: any) { Alert.alert("Hide failed", e?.message || ""); }
    finally { setBusyId(null); }
  };

  const doRestore = async (img: BrandImage) => {
    setBusyId(img.id);
    try {
      // Restoring a hidden entry — mark as pending and regenerate (path was cleared on hide)
      await api(`/brand-images/${img.id}/regenerate`, { method: "POST", body: {} });
      await load();
    } catch (e: any) { Alert.alert("Restore failed", e?.message || ""); }
    finally { setBusyId(null); }
  };

  const toggleDefault = async (img: BrandImage) => {
    setBusyId(img.id);
    try {
      await api(`/brand-images/${img.id}`, { method: "PATCH", body: { is_default: !img.is_default } });
      await load();
    } catch (e: any) { Alert.alert("Update failed", e?.message || ""); }
    finally { setBusyId(null); }
  };

  const doApprove = async (img: BrandImage) => {
    setBusyId(img.id);
    try {
      await api(`/brand-images/${img.id}`, { method: "PATCH", body: { status: "approved" } });
      await load();
    } catch (e: any) { Alert.alert("Approve failed", e?.message || ""); }
    finally { setBusyId(null); }
  };

  const doReject = async (img: BrandImage) => {
    setBusyId(img.id);
    try {
      await api(`/brand-images/${img.id}`, { method: "PATCH", body: { status: "rejected" } });
      await load();
    } catch (e: any) { Alert.alert("Reject failed", e?.message || ""); }
    finally { setBusyId(null); }
  };

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.top}>
        <Pressable onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="chevron-back" size={24} color={theme.color.text} />
        </Pressable>
        <Text style={styles.topT}>BRAND IMAGES</Text>
        <Pressable onPress={() => setShowHidden((s) => !s)} hitSlop={12}>
          <Ionicons name={showHidden ? "eye-off" : "eye"} size={20} color={theme.color.brand} />
        </Pressable>
      </View>

      <ScrollView
        contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: 100 }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}
      >
        <View style={styles.headerCard}>
          <Text style={styles.headerT}>CREWFIT VISUAL LIBRARY</Text>
          <Text style={styles.headerSub}>
            Nano Banana–generated hero art matched to role, gender, workout type,
            phase, and roster context. Shown on the client home, workouts,
            recovery, standby and event cards.
          </Text>
          {runningCount > 0 ? (
            <View style={styles.runningRow}>
              <ActivityIndicator color={theme.color.brand} size="small" />
              <Text style={styles.runningT}>{runningCount} generating…</Text>
            </View>
          ) : null}
          <Pressable disabled={seeding} onPress={doSeed} style={[styles.seedBtn, seeding && { opacity: 0.5 }]} testID="brand-seed">
            {seeding ? <ActivityIndicator color="#fff" /> : (
              <>
                <Ionicons name="sparkles" size={16} color="#fff" />
                <Text style={styles.seedBtnT}>SEED / TOP UP LIBRARY</Text>
              </>
            )}
          </Pressable>
        </View>

        {/* AWAITING APPROVAL — client-generated personalised images */}
        {pending.length > 0 ? (
          <View style={styles.approvalHeader}>
            <Ionicons name="hourglass" size={14} color={theme.color.amber} />
            <Text style={styles.approvalHeaderT}>AWAITING APPROVAL · {pending.length}</Text>
          </View>
        ) : null}
        {pending.map((img) => {
          const url = token
            ? `${API_BASE}/brand-images/${img.id}/stream?token=${encodeURIComponent(token)}`
            : null;
          const busy = busyId === img.id;
          return (
            <View key={img.id} style={[styles.card, { borderColor: theme.color.amber }]} testID={`pending-${img.id}`}>
              <View style={styles.previewWrap}>
                {url ? <Image source={{ uri: url }} style={styles.preview} contentFit="cover" /> : null}
                <View style={[styles.statusPill, { backgroundColor: theme.color.amber }]}>
                  <Text style={styles.statusPillT}>PENDING APPROVAL</Text>
                </View>
              </View>
              <View style={styles.meta}>
                <Text style={styles.metaKey} numberOfLines={1}>{img.label || img.key}</Text>
                <Text style={styles.metaCat}>PERSONALISED · client {img.personalised_for?.slice(0, 8) || ""}</Text>
                {img.context && Object.keys(img.context).length ? (
                  <View style={styles.ctxRow}>
                    {Object.entries(img.context).filter(([, v]) => v).map(([k, v]) => (
                      <View key={k} style={styles.ctxChip}>
                        <Text style={styles.ctxChipT}>{k}={String(v)}</Text>
                      </View>
                    ))}
                  </View>
                ) : null}
              </View>
              <View style={styles.actionRow}>
                <Pressable disabled={busy} onPress={() => doApprove(img)} style={[styles.actionBtn, { borderColor: theme.color.green, backgroundColor: "rgba(16,185,129,0.12)" }]} testID={`approve-${img.id}`}>
                  <Ionicons name="checkmark-circle" size={13} color={theme.color.green} />
                  <Text style={[styles.actionBtnT, { color: theme.color.green }]}>APPROVE</Text>
                </Pressable>
                <Pressable disabled={busy} onPress={() => doReject(img)} style={styles.actionBtnMuted} testID={`reject-${img.id}`}>
                  <Ionicons name="close-circle" size={13} color={theme.color.textMuted} />
                  <Text style={styles.actionBtnMutedT}>REJECT</Text>
                </Pressable>
                <Pressable disabled={busy} onPress={() => doRegen(img)} style={styles.actionBtn}>
                  <Ionicons name="refresh" size={13} color={theme.color.brand} />
                  <Text style={styles.actionBtnT}>REGEN</Text>
                </Pressable>
              </View>
            </View>
          );
        })}

        {loading && images.length === 0 ? (
          <ActivityIndicator color={theme.color.brand} style={{ marginTop: 40 }} />
        ) : images.length === 0 ? (
          <Text style={styles.emptyT}>No images yet. Tap SEED to generate the CrewFit library.</Text>
        ) : (
          images.map((img) => {
            const url = img.status === "ready" && token
              ? `${API_BASE}/brand-images/${img.id}/stream?token=${encodeURIComponent(token)}`
              : null;
            const busy = busyId === img.id;
            return (
              <View key={img.id} style={styles.card} testID={`brand-${img.key}`}>
                <View style={styles.previewWrap}>
                  {url ? (
                    <Image source={{ uri: url }} style={styles.preview} contentFit="cover" />
                  ) : (
                    <View style={[styles.preview, styles.placeholder]}>
                      {img.status === "generating" || img.status === "pending" ? (
                        <>
                          <ActivityIndicator color={theme.color.brand} />
                          <Text style={styles.placeholderT}>GENERATING</Text>
                        </>
                      ) : img.status === "failed" ? (
                        <>
                          <Ionicons name="warning" size={30} color={"#c94a4a"} />
                          <Text style={[styles.placeholderT, { color: "#c94a4a" }]}>FAILED</Text>
                        </>
                      ) : (
                        <>
                          <Ionicons name="eye-off" size={30} color={theme.color.textDim} />
                          <Text style={styles.placeholderT}>HIDDEN</Text>
                        </>
                      )}
                    </View>
                  )}
                  <View style={[styles.statusPill, statusStyle(img.status)]}>
                    <Text style={styles.statusPillT}>{(img.status || "").toUpperCase()}</Text>
                  </View>
                  {img.is_default ? (
                    <View style={styles.defaultPill}><Text style={styles.defaultPillT}>DEFAULT</Text></View>
                  ) : null}
                </View>

                <View style={styles.meta}>
                  <Text style={styles.metaKey}>{img.key}</Text>
                  <Text style={styles.metaCat}>{(img.category || "").toUpperCase()}</Text>
                  {img.context && Object.keys(img.context).length ? (
                    <View style={styles.ctxRow}>
                      {Object.entries(img.context).map(([k, v]) => (
                        <View key={k} style={styles.ctxChip}>
                          <Text style={styles.ctxChipT}>{k}={String(v)}</Text>
                        </View>
                      ))}
                    </View>
                  ) : null}
                  {img.error ? <Text style={styles.errorT}>{img.error}</Text> : null}
                  {typeof img.size_bytes === "number" ? (
                    <Text style={styles.metaSize}>{(img.size_bytes / 1024).toFixed(0)} KB · {img.updated_at?.slice(0, 19).replace("T", " ")}</Text>
                  ) : null}
                </View>

                <View style={styles.actionRow}>
                  {img.status !== "hidden" ? (
                    <>
                      <Pressable disabled={busy} onPress={() => doRegen(img)} style={styles.actionBtn} testID={`regen-${img.key}`}>
                        {busy ? <ActivityIndicator color={theme.color.brand} size="small" /> : (<>
                          <Ionicons name="refresh" size={13} color={theme.color.brand} />
                          <Text style={styles.actionBtnT}>REGEN</Text>
                        </>)}
                      </Pressable>
                      <Pressable disabled={busy || img.status !== "ready"} onPress={() => toggleDefault(img)} style={[styles.actionBtn, img.is_default && { borderColor: theme.color.green, backgroundColor: "rgba(16,185,129,0.12)" }]}>
                        <Ionicons name={img.is_default ? "star" : "star-outline"} size={13} color={img.is_default ? theme.color.green : theme.color.brand} />
                        <Text style={[styles.actionBtnT, img.is_default && { color: theme.color.green }]}>{img.is_default ? "DEFAULT" : "MAKE DEFAULT"}</Text>
                      </Pressable>
                      <Pressable disabled={busy} onPress={() => doHide(img)} style={styles.actionBtnMuted} testID={`hide-${img.key}`}>
                        <Ionicons name="eye-off" size={13} color={theme.color.textMuted} />
                        <Text style={styles.actionBtnMutedT}>HIDE</Text>
                      </Pressable>
                    </>
                  ) : (
                    <Pressable disabled={busy} onPress={() => doRestore(img)} style={styles.actionBtn}>
                      <Ionicons name="refresh" size={13} color={theme.color.brand} />
                      <Text style={styles.actionBtnT}>RESTORE + REGEN</Text>
                    </Pressable>
                  )}
                </View>
              </View>
            );
          })
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function statusStyle(s: string): any {
  if (s === "ready") return { backgroundColor: theme.color.green };
  if (s === "failed") return { backgroundColor: "#c94a4a" };
  if (s === "hidden") return { backgroundColor: theme.color.textDim };
  return { backgroundColor: theme.color.brand };
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  top: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 14, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  topT: { color: theme.color.text, fontSize: 14, letterSpacing: 2, fontWeight: "900", fontFamily: theme.font.display },

  headerCard: { padding: 14, borderRadius: 12, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, gap: 8 },
  headerT: { color: theme.color.brand, fontSize: 10, letterSpacing: 2, fontWeight: "900", fontFamily: theme.font.textSemi },
  headerSub: { color: theme.color.textMuted, fontSize: 12, lineHeight: 18, fontFamily: theme.font.text },
  runningRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 4 },
  runningT: { color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 1 },
  seedBtn: { marginTop: 4, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: theme.color.brand, paddingVertical: 12, borderRadius: 10 },
  seedBtnT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5, fontFamily: theme.font.textSemi },

  emptyT: { color: theme.color.textMuted, textAlign: "center", marginTop: 40, fontStyle: "italic" },

  card: { borderRadius: 12, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, overflow: "hidden" },
  previewWrap: { position: "relative", height: 180, backgroundColor: "#000" },
  preview: { width: "100%", height: "100%" },
  placeholder: { alignItems: "center", justifyContent: "center", gap: 6 },
  placeholderT: { color: theme.color.textDim, fontSize: 10, letterSpacing: 2, fontWeight: "900" },

  statusPill: { position: "absolute", top: 10, left: 10, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 12 },
  statusPillT: { color: "#fff", fontSize: 9, letterSpacing: 1, fontWeight: "900" },
  defaultPill: { position: "absolute", top: 10, right: 10, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 12, backgroundColor: "rgba(16,185,129,0.85)" },
  defaultPillT: { color: "#fff", fontSize: 9, letterSpacing: 1, fontWeight: "900" },

  meta: { padding: 12, gap: 4 },
  metaKey: { color: theme.color.text, fontSize: 14, fontWeight: "900", letterSpacing: 0.5, fontFamily: theme.font.display },
  metaCat: { color: theme.color.brand, fontSize: 10, letterSpacing: 1.5, fontWeight: "900", fontFamily: theme.font.textSemi },
  ctxRow: { flexDirection: "row", flexWrap: "wrap", gap: 5, marginTop: 4 },
  ctxChip: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 8, backgroundColor: theme.color.surface3 },
  ctxChipT: { color: theme.color.textMuted, fontSize: 10, fontWeight: "700" },
  errorT: { color: "#f39a9a", fontSize: 11, fontStyle: "italic" },
  metaSize: { color: theme.color.textDim, fontSize: 10, letterSpacing: 0.5, marginTop: 2 },

  actionRow: { flexDirection: "row", gap: 6, padding: 10, paddingTop: 0, flexWrap: "wrap" },
  actionBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 8, borderRadius: 8, borderWidth: 1, borderColor: theme.color.brand, backgroundColor: theme.color.brandTint },
  actionBtnT: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1 },
  actionBtnMuted: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 8, borderRadius: 8, borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface3 },
  actionBtnMutedT: { color: theme.color.textMuted, fontSize: 10, fontWeight: "900", letterSpacing: 1 },
  approvalHeader: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 8 },
  approvalHeaderT: { color: theme.color.amber, fontSize: 10, fontWeight: "900", letterSpacing: 2, fontFamily: theme.font.textSemi },
});
