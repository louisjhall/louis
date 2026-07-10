/**
 * Coach · Exercise Content Library (unified).
 *
 * Left  — searchable list + status/filter tabs + usage badges.
 * Right — selected exercise detail: images, start/end demo, coaching points,
 *         video, alternatives, approval controls, content log.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator, Alert, FlatList, Pressable, RefreshControl, ScrollView,
  StyleSheet, Text, TextInput, View,
} from "react-native";
import { Image } from "expo-image";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useFocusEffect } from "expo-router";
import { api, API_BASE, getToken } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Exercise = {
  id: string;
  exercise_name: string;
  category?: string;
  training_type?: string;
  body_area?: string;
  equipment_type?: string[];
  status: string;
  approval_status: string;
  approved_image_status?: string;
  approved_video_status?: string;
  content_status?: { images?: boolean; coaching_points?: boolean; video?: boolean };
  coaching_points?: string[];
  common_mistakes?: string[];
  client_facing_instructions?: string;
  primary_video_url?: string;
  primary_image_id?: string | null;
  demo_start_image_id?: string | null;
  demo_end_image_id?: string | null;
  used_in_tomorrow_workouts_count?: number;
  used_in_active_programmes_count?: number;
  alternatives?: string[];
};

const FILTERS: { key: string; label: string; q: Record<string, string | boolean> }[] = [
  { key: "all", label: "ALL", q: {} },
  { key: "warmup", label: "WARM-UP", q: { training_type: "warmup" } },
  { key: "mobility", label: "MOBILITY", q: { category: "mobility" } },
  { key: "strength", label: "STRENGTH", q: { training_type: "strength" } },
  { key: "cardio", label: "CARDIO", q: { training_type: "cardio" } },
  { key: "rehab", label: "REHAB", q: { category: "rehab" } },
  { key: "cooldown", label: "COOLDOWN", q: { training_type: "cooldown" } },
  { key: "tomorrow", label: "TOMORROW", q: { used_tomorrow: true } },
  { key: "missing", label: "MISSING", q: { missing_content: true } },
  { key: "approved", label: "APPROVED", q: { approved_only: true } },
];

export default function ExerciseContentScreen() {
  const router = useRouter();
  const [items, setItems] = useState<Exercise[]>([]);
  const [selected, setSelected] = useState<Exercise | null>(null);
  const [detail, setDetail] = useState<Exercise | null>(null);
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [token, setToken] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const f = FILTERS.find((x) => x.key === filter) || FILTERS[0];
      const params = new URLSearchParams(Object.entries({ ...f.q, ...(query ? { q: query } : {}) }).map(([k, v]) => [k, String(v)])).toString();
      const r = await api<{ exercises: Exercise[] }>(`/exercise-content${params ? `?${params}` : ""}`);
      setItems(r.exercises || []);
      if (!selected && (r.exercises || []).length) setSelected(r.exercises[0]);
    } catch (e: any) {
      Alert.alert("Load failed", e?.message || "");
    } finally { setLoading(false); }
    setToken(await getToken());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter, query]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  useEffect(() => {
    if (!selected) { setDetail(null); return; }
    (async () => {
      try {
        const r = await api<{ exercise: Exercise }>(`/exercise-content/${selected.id}`);
        setDetail(r.exercise);
      } catch { /* silent */ }
    })();
  }, [selected]);

  const scanTodos = async () => {
    setBusy("scan");
    try {
      const r = await api<{ created: number }>("/exercise-content/scan-todos", { method: "POST", body: {} });
      Alert.alert("Scan complete", `${r.created} coach task${r.created === 1 ? "" : "s"} created.`);
    } catch (e: any) { Alert.alert("Scan failed", e?.message || ""); }
    finally { setBusy(null); }
  };

  const genImage = async (slot: "primary" | "start" | "end") => {
    if (!detail) return;
    setBusy(`gen-${slot}`);
    try {
      await api(`/exercise-content/${detail.id}/generate-image`, { method: "POST", body: { slot } });
      Alert.alert("Generating", "Nano Banana is generating your exercise image. Refresh in ~15s.");
      setTimeout(load, 15000);
    } catch (e: any) { Alert.alert("Failed", e?.message || ""); }
    finally { setBusy(null); }
  };

  const approve = async (scope: string) => {
    if (!detail) return;
    setBusy(`approve-${scope}`);
    try {
      const r = await api<{ exercise: Exercise }>(`/exercise-content/${detail.id}/approve`, {
        method: "POST", body: { scope },
      });
      setDetail(r.exercise);
      await load();
    } catch (e: any) { Alert.alert("Failed", e?.message || ""); }
    finally { setBusy(null); }
  };

  const imgUrl = (id?: string | null) => id && token ? `${API_BASE}/exercise-content/images/${id}/stream?token=${encodeURIComponent(token)}` : null;

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.top}>
        <Pressable onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="chevron-back" size={24} color={theme.color.text} />
        </Pressable>
        <Text style={styles.topT}>EXERCISE CONTENT</Text>
        <Pressable onPress={scanTodos} hitSlop={12} disabled={!!busy}>
          {busy === "scan" ? <ActivityIndicator color={theme.color.brand} size="small" /> : (
            <Ionicons name="notifications" size={20} color={theme.color.brand} />
          )}
        </Pressable>
      </View>

      <View style={{ paddingHorizontal: 14, paddingTop: 10 }}>
        <TextInput
          value={query} onChangeText={setQuery} placeholder="Search exercises, tags, equipment…"
          placeholderTextColor={theme.color.textDim} style={styles.search}
          returnKeyType="search" onSubmitEditing={load}
        />
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: 14, paddingVertical: 10, gap: 6 }}>
        {FILTERS.map((f) => (
          <Pressable key={f.key} onPress={() => setFilter(f.key)}
            style={[styles.filter, filter === f.key && styles.filterOn]}>
            <Text style={[styles.filterT, filter === f.key && styles.filterTOn]}>{f.label}</Text>
          </Pressable>
        ))}
      </ScrollView>

      <View style={{ flex: 1, flexDirection: "row" }}>
        {/* LEFT: list */}
        <View style={styles.leftPane}>
          <FlatList
            data={items} keyExtractor={(i) => i.id}
            refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}
            renderItem={({ item }) => {
              const missing = !(item.content_status?.images && item.content_status?.coaching_points && item.content_status?.video);
              const isSel = selected?.id === item.id;
              return (
                <Pressable onPress={() => setSelected(item)} style={[styles.row, isSel && styles.rowOn]}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.rowName} numberOfLines={1}>{item.exercise_name}</Text>
                    <View style={styles.rowMeta}>
                      <View style={[styles.dot, { backgroundColor: statusColor(item.status) }]} />
                      <Text style={styles.rowMetaT}>{item.status.toUpperCase()}</Text>
                      {item.used_in_tomorrow_workouts_count ? (
                        <View style={styles.tomBadge}>
                          <Ionicons name="calendar" size={9} color={theme.color.amber} />
                          <Text style={styles.tomT}>{item.used_in_tomorrow_workouts_count} TMW</Text>
                        </View>
                      ) : null}
                      {missing ? <View style={styles.missBadge}><Text style={styles.missT}>MISSING</Text></View> : null}
                    </View>
                  </View>
                </Pressable>
              );
            }}
            ListEmptyComponent={!loading ? <Text style={styles.empty}>No exercises. Create one to begin.</Text> : null}
          />
        </View>

        {/* RIGHT: detail */}
        <ScrollView style={styles.rightPane} contentContainerStyle={{ padding: 12, paddingBottom: 100 }}>
          {!detail ? (
            <Text style={styles.empty}>Select an exercise.</Text>
          ) : (
            <>
              <Text style={styles.detailName}>{detail.exercise_name}</Text>
              <Text style={styles.detailCat}>{[detail.category, detail.training_type, detail.body_area].filter(Boolean).join(" · ").toUpperCase()}</Text>

              <View style={styles.pillsRow}>
                <View style={[styles.statusPill, { backgroundColor: statusColor(detail.status) }]}>
                  <Text style={styles.statusPillT}>{detail.status.toUpperCase()}</Text>
                </View>
                {detail.used_in_tomorrow_workouts_count ? (
                  <View style={[styles.statusPill, { backgroundColor: theme.color.amber }]}>
                    <Text style={styles.statusPillT}>{detail.used_in_tomorrow_workouts_count} TOMORROW</Text>
                  </View>
                ) : null}
              </View>

              {/* Images */}
              <Text style={styles.sect}>DEMO IMAGES</Text>
              <View style={styles.imgGrid}>
                <ImgSlot title="START" url={imgUrl(detail.demo_start_image_id)} onGen={() => genImage("start")} busy={busy === "gen-start"} />
                <ImgSlot title="END" url={imgUrl(detail.demo_end_image_id)} onGen={() => genImage("end")} busy={busy === "gen-end"} />
                <ImgSlot title="PRIMARY" url={imgUrl(detail.primary_image_id)} onGen={() => genImage("primary")} busy={busy === "gen-primary"} />
              </View>

              {/* Coaching points */}
              <Text style={styles.sect}>COACHING POINTS · {detail.coaching_points?.length || 0}</Text>
              {(detail.coaching_points || []).length ? (detail.coaching_points || []).map((p, i) => (
                <View key={i} style={styles.cpRow}>
                  <Ionicons name="checkmark-circle" size={13} color={theme.color.brand} />
                  <Text style={styles.cpT}>{p}</Text>
                </View>
              )) : <Text style={styles.empty}>No coaching points yet.</Text>}

              {(detail.common_mistakes || []).length ? (
                <>
                  <Text style={styles.sect}>COMMON MISTAKES</Text>
                  {(detail.common_mistakes || []).map((m, i) => (
                    <View key={i} style={styles.cpRow}>
                      <Ionicons name="warning" size={13} color={theme.color.amber} />
                      <Text style={styles.cpT}>{m}</Text>
                    </View>
                  ))}
                </>
              ) : null}

              {/* Video */}
              <Text style={styles.sect}>VIDEO</Text>
              <View style={styles.metaCard}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.metaCardK}>PRIMARY</Text>
                  <Text style={styles.metaCardV} numberOfLines={1}>{detail.primary_video_url || "— none —"}</Text>
                </View>
                <View style={[styles.videoBadge, videoBadgeStyle(detail.approved_video_status)]}>
                  <Text style={styles.videoBadgeT}>{(detail.approved_video_status || "MISSING").toUpperCase()}</Text>
                </View>
              </View>

              {/* Approval controls */}
              <Text style={styles.sect}>APPROVAL</Text>
              <View style={styles.approveGrid}>
                <ApproveBtn label="APPROVE ALL" onPress={() => approve("all")} busy={busy === "approve-all"} primary />
                <ApproveBtn label="IMAGES" onPress={() => approve("images")} busy={busy === "approve-images"} />
                <ApproveBtn label="COACHING" onPress={() => approve("coaching")} busy={busy === "approve-coaching"} />
                <ApproveBtn label="VIDEO" onPress={() => approve("video")} busy={busy === "approve-video"} />
                <ApproveBtn label="MARK LIVE" onPress={() => approve("mark_live")} busy={busy === "approve-mark_live"} primary />
                <ApproveBtn label="NEEDS UPDATE" onPress={() => approve("needs_update")} busy={busy === "approve-needs_update"} muted />
              </View>
            </>
          )}
        </ScrollView>
      </View>
    </SafeAreaView>
  );
}

function ImgSlot({ title, url, onGen, busy }: any) {
  return (
    <View style={styles.imgSlot}>
      <View style={styles.imgBox}>
        {url ? <Image source={{ uri: url }} style={{ width: "100%", height: "100%" }} contentFit="cover" /> : (
          <Ionicons name="image-outline" size={22} color={theme.color.textDim} />
        )}
      </View>
      <Text style={styles.imgSlotT}>{title}</Text>
      <Pressable onPress={onGen} disabled={busy} style={styles.genBtn} testID={`gen-${String(title).toLowerCase()}`}>
        {busy ? <ActivityIndicator color="#fff" size="small" /> : (<>
          <Ionicons name="sparkles" size={11} color="#fff" />
          <Text style={styles.genT}>{url ? "REGEN" : "GENERATE"}</Text>
        </>)}
      </Pressable>
    </View>
  );
}

function ApproveBtn({ label, onPress, busy, primary, muted }: any) {
  return (
    <Pressable onPress={onPress} disabled={busy} style={[styles.appBtn, primary && styles.appBtnPri, muted && styles.appBtnMuted, busy && { opacity: 0.5 }]}>
      {busy ? <ActivityIndicator color="#fff" /> : <Text style={[styles.appBtnT, primary && { color: "#fff" }, muted && { color: theme.color.textMuted }]}>{label}</Text>}
    </Pressable>
  );
}

function statusColor(s: string): string {
  const m: Record<string, string> = {
    "Live": theme.color.green, "Approved": theme.color.green,
    "Draft": theme.color.textDim, "Archived": theme.color.textDim,
    "Rejected": "#c94a4a", "Needs Update": "#c94a4a",
    "Needs Review": theme.color.amber, "Ready for Approval": theme.color.amber,
    "Artwork Needed": theme.color.brand, "Coaching Points Needed": theme.color.brand,
    "Video Needed": theme.color.brand,
  };
  return m[s] || theme.color.textDim;
}

function videoBadgeStyle(s?: string): any {
  const m: Record<string, any> = {
    Approved: { backgroundColor: theme.color.green },
    "Auto Found": { backgroundColor: theme.color.amber },
    "Needs Review": { backgroundColor: theme.color.amber },
    Rejected: { backgroundColor: "#c94a4a" },
    Missing: { backgroundColor: theme.color.textDim },
  };
  return m[s || "Missing"] || m.Missing;
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  top: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 14, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  topT: { color: theme.color.text, fontSize: 14, letterSpacing: 2, fontWeight: "900", fontFamily: theme.font.display },
  search: { backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 8, color: theme.color.text, fontSize: 13 },
  filter: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 20, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  filterOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  filterT: { color: theme.color.textMuted, fontSize: 9, fontWeight: "900", letterSpacing: 1 },
  filterTOn: { color: "#fff" },

  leftPane: { width: 170, borderRightWidth: 1, borderRightColor: theme.color.divider, backgroundColor: theme.color.surface2 },
  rightPane: { flex: 1 },
  empty: { color: theme.color.textDim, textAlign: "center", marginTop: 40, fontStyle: "italic", padding: 20 },

  row: { padding: 10, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: theme.color.divider },
  rowOn: { backgroundColor: theme.color.surface3 },
  rowName: { color: theme.color.text, fontSize: 12, fontWeight: "800", fontFamily: theme.font.textSemi },
  rowMeta: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 4, flexWrap: "wrap" },
  dot: { width: 6, height: 6, borderRadius: 3 },
  rowMetaT: { color: theme.color.textMuted, fontSize: 8, letterSpacing: 1, fontWeight: "800" },
  tomBadge: { flexDirection: "row", alignItems: "center", gap: 2, paddingHorizontal: 4, paddingVertical: 2, borderRadius: 8, backgroundColor: "rgba(245,158,11,0.15)" },
  tomT: { color: theme.color.amber, fontSize: 8, fontWeight: "900", letterSpacing: 0.5 },
  missBadge: { paddingHorizontal: 4, paddingVertical: 2, borderRadius: 8, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand },
  missT: { color: theme.color.brand, fontSize: 8, fontWeight: "900", letterSpacing: 0.5 },

  detailName: { color: theme.color.text, fontSize: 20, fontWeight: "900", letterSpacing: 0.5, fontFamily: theme.font.display },
  detailCat: { color: theme.color.brand, fontSize: 10, letterSpacing: 2, fontWeight: "900", marginTop: 2, fontFamily: theme.font.textSemi },
  pillsRow: { flexDirection: "row", gap: 6, marginTop: 8, flexWrap: "wrap" },
  statusPill: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 12 },
  statusPillT: { color: "#fff", fontSize: 9, fontWeight: "900", letterSpacing: 1 },

  sect: { color: theme.color.brand, fontSize: 10, letterSpacing: 2, fontWeight: "900", fontFamily: theme.font.textSemi, marginTop: 14, marginBottom: 6 },
  imgGrid: { flexDirection: "row", gap: 8 },
  imgSlot: { flex: 1, alignItems: "stretch", gap: 4 },
  imgBox: { aspectRatio: 3 / 4, borderRadius: 10, backgroundColor: "#000", borderWidth: 1, borderColor: theme.color.border, alignItems: "center", justifyContent: "center", overflow: "hidden" },
  imgSlotT: { color: theme.color.textMuted, fontSize: 9, fontWeight: "900", letterSpacing: 1, textAlign: "center" },
  genBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 4, paddingVertical: 6, borderRadius: 8, backgroundColor: theme.color.brand },
  genT: { color: "#fff", fontSize: 9, fontWeight: "900", letterSpacing: 0.7 },

  cpRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 4 },
  cpT: { color: theme.color.text, fontSize: 13, flex: 1, fontFamily: theme.font.text },

  metaCard: { flexDirection: "row", alignItems: "center", gap: 8, padding: 10, borderRadius: 10, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  metaCardK: { color: theme.color.textDim, fontSize: 9, letterSpacing: 1, fontWeight: "800" },
  metaCardV: { color: theme.color.text, fontSize: 12, marginTop: 2 },
  videoBadge: { paddingHorizontal: 6, paddingVertical: 3, borderRadius: 10 },
  videoBadgeT: { color: "#fff", fontSize: 8, fontWeight: "900", letterSpacing: 1 },

  approveGrid: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 4 },
  appBtn: { flexBasis: "48%", paddingVertical: 10, borderRadius: 8, borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface2, alignItems: "center" },
  appBtnPri: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  appBtnMuted: { backgroundColor: theme.color.surface3 },
  appBtnT: { color: theme.color.text, fontSize: 10, fontWeight: "900", letterSpacing: 1 },
});
