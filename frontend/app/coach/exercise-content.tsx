/**
 * Coach · Exercise Content Library (unified).
 *
 * Left  — searchable list + status/filter tabs + usage badges.
 * Right — selected exercise detail: images, start/end demo, coaching points,
 *         video, alternatives, approval controls, content log.
 */
import React, { useCallback, useEffect, useState } from "react";
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
import { confirm, toast } from "@/src/lib/ux";
import {
  EditListModal, EditTextModal, CreateExerciseModal, ChangeLogModal,
} from "@/src/components/coach/ExerciseEditModals";

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

  // Modals
  const [showEditPoints, setShowEditPoints] = useState(false);
  const [showEditMistakes, setShowEditMistakes] = useState(false);
  const [showEditAlts, setShowEditAlts] = useState(false);
  const [showEditVideo, setShowEditVideo] = useState(false);
  const [showEditInstr, setShowEditInstr] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [showLog, setShowLog] = useState(false);
  const [logRows, setLogRows] = useState<any[]>([]);
  const [logLoading, setLogLoading] = useState(false);

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

  const refreshDetail = useCallback(async (id?: string) => {
    const targetId = id || detail?.id || selected?.id;
    if (!targetId) return;
    try {
      const r = await api<{ exercise: Exercise }>(`/exercise-content/${targetId}`);
      setDetail(r.exercise);
      setItems((prev) => prev.map((x) => (x.id === r.exercise.id ? { ...x, ...r.exercise } : x)));
    } catch { /* silent */ }
  }, [detail?.id, selected?.id]);

  useEffect(() => {
    if (!selected) { setDetail(null); return; }
    refreshDetail(selected.id);
  }, [selected, refreshDetail]);

  const scanTodos = async () => {
    setBusy("scan");
    try {
      const r = await api<{ created: number }>("/exercise-content/scan-todos", { method: "POST", body: {} });
      toast(`Scan complete · ${r.created} task${r.created === 1 ? "" : "s"} created`, "success");
    } catch (e: any) { toast(e?.message || "Scan failed", "error"); }
    finally { setBusy(null); }
  };

  const genImage = async (slot: "primary" | "start" | "end") => {
    if (!detail) return;
    setBusy(`gen-${slot}`);
    try {
      const r = await api<{ image_id: string }>(`/exercise-content/${detail.id}/generate-image`, { method: "POST", body: { slot } });
      // Optimistic detail refresh so the "generating…" state shows immediately.
      await refreshDetail(detail.id);
      // Poll the image doc until ready/failed (max ~45s)
      pollImage(r.image_id, detail.id);
    } catch (e: any) { Alert.alert("Failed", e?.message || ""); }
    finally { setBusy(null); }
  };

  const pollImage = async (imageId: string, exerciseId: string) => {
    const start = Date.now();
    const tick = async () => {
      if (Date.now() - start > 60000) return;
      try {
        const r = await api<{ image: { status: string } }>(`/exercise-content/images/${imageId}`);
        if (r.image.status === "ready" || r.image.status === "failed") {
          if (r.image.status === "failed") Alert.alert("Image failed", "Nano Banana returned no image. Try again.");
          await refreshDetail(exerciseId);
          return;
        }
      } catch { /* silent */ }
      setTimeout(tick, 3000);
    };
    setTimeout(tick, 4000);
  };

  const patchExercise = async (patch: Record<string, any>, kind: string) => {
    if (!detail) return;
    setBusy(`patch-${kind}`);
    try {
      const r = await api<{ exercise: Exercise }>(`/exercise-content/${detail.id}`, { method: "PATCH", body: patch });
      setDetail(r.exercise);
      setItems((prev) => prev.map((x) => (x.id === r.exercise.id ? { ...x, ...r.exercise } : x)));
    } catch (e: any) { Alert.alert("Save failed", e?.message || ""); }
    finally { setBusy(null); }
  };

  const createExercise = async (body: any) => {
    setBusy("create");
    try {
      const r = await api<{ exercise: Exercise }>("/exercise-content", { method: "POST", body });
      await load();
      setSelected(r.exercise);
    } catch (e: any) { Alert.alert("Create failed", e?.message || ""); throw e; }
    finally { setBusy(null); }
  };

  const archiveExercise = async () => {
    if (!detail) return;
    const ok = await confirm({
      title: "Archive exercise?",
      message: `"${detail.exercise_name}" will be moved to Archived. You can restore it by editing status.`,
      confirmLabel: "ARCHIVE",
      destructive: true,
    });
    if (!ok) return;
    setBusy("archive");
    try {
      await api(`/exercise-content/${detail.id}`, { method: "DELETE" });
      setSelected(null); setDetail(null);
      await load();
      toast("Archived", "success");
    } catch (e: any) { toast(e?.message || "Failed", "error"); }
    finally { setBusy(null); }
  };

  const openLog = async () => {
    if (!detail) return;
    setShowLog(true); setLogLoading(true);
    try {
      const r = await api<{ log: any[] }>(`/exercise-content/${detail.id}/log`);
      setLogRows(r.log || []);
    } catch (e: any) { Alert.alert("Log failed", e?.message || ""); }
    finally { setLogLoading(false); }
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
        <View style={{ flexDirection: "row", gap: 14 }}>
          <Pressable onPress={() => setShowCreate(true)} hitSlop={12} disabled={!!busy} testID="new-exercise">
            <Ionicons name="add-circle" size={22} color={theme.color.brand} />
          </Pressable>
          <Pressable onPress={scanTodos} hitSlop={12} disabled={!!busy} testID="scan-todos">
            {busy === "scan" ? <ActivityIndicator color={theme.color.brand} size="small" /> : (
              <Ionicons name="notifications" size={20} color={theme.color.brand} />
            )}
          </Pressable>
        </View>
      </View>

      <View style={{ paddingHorizontal: 14, paddingTop: 10 }}>
        <TextInput
          value={query} onChangeText={setQuery} placeholder="Search exercises, tags, equipment…"
          placeholderTextColor={theme.color.textDim} style={styles.search}
          returnKeyType="search" onSubmitEditing={load}
        />
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.filterScroll} contentContainerStyle={styles.filterContent}>
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
              <SectionHeader label={`COACHING POINTS · ${detail.coaching_points?.length || 0}`}
                onEdit={() => setShowEditPoints(true)} />
              {(detail.coaching_points || []).length ? (detail.coaching_points || []).map((p, i) => (
                <View key={i} style={styles.cpRow}>
                  <Ionicons name="checkmark-circle" size={13} color={theme.color.brand} />
                  <Text style={styles.cpT}>{p}</Text>
                </View>
              )) : <Text style={styles.empty}>No coaching points yet. Tap edit to add.</Text>}

              {/* Common Mistakes */}
              <SectionHeader label={`COMMON MISTAKES · ${detail.common_mistakes?.length || 0}`}
                onEdit={() => setShowEditMistakes(true)} />
              {(detail.common_mistakes || []).length ? (detail.common_mistakes || []).map((m, i) => (
                <View key={i} style={styles.cpRow}>
                  <Ionicons name="warning" size={13} color={theme.color.amber} />
                  <Text style={styles.cpT}>{m}</Text>
                </View>
              )) : <Text style={styles.empty}>None recorded.</Text>}

              {/* Client-Facing Instructions */}
              <SectionHeader label="CLIENT INSTRUCTIONS" onEdit={() => setShowEditInstr(true)} />
              <Text style={detail.client_facing_instructions ? styles.instrT : styles.empty}>
                {detail.client_facing_instructions || "No instructions yet. Tap edit."}
              </Text>

              {/* Alternatives */}
              <SectionHeader label={`ALTERNATIVES · ${detail.alternatives?.length || 0}`}
                onEdit={() => setShowEditAlts(true)} />
              {(detail.alternatives || []).length ? (detail.alternatives || []).map((a, i) => (
                <View key={i} style={styles.cpRow}>
                  <Ionicons name="swap-horizontal" size={13} color={theme.color.textMuted} />
                  <Text style={styles.cpT}>{a}</Text>
                </View>
              )) : <Text style={styles.empty}>None linked.</Text>}

              {/* Video */}
              <SectionHeader label="VIDEO" onEdit={() => setShowEditVideo(true)} />
              <View style={styles.metaCard}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.metaCardK}>PRIMARY URL</Text>
                  <Text style={styles.metaCardV} numberOfLines={2}>{detail.primary_video_url || "— none —"}</Text>
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

              {/* Footer actions */}
              <View style={styles.footerActs}>
                <Pressable onPress={openLog} style={styles.footerBtn} testID="change-log">
                  <Ionicons name="time-outline" size={13} color={theme.color.textMuted} />
                  <Text style={styles.footerBtnT}>CHANGE LOG</Text>
                </Pressable>
                <Pressable onPress={archiveExercise} disabled={busy === "archive"}
                  style={[styles.footerBtn, styles.footerBtnDanger]} testID="archive-ex">
                  {busy === "archive" ? <ActivityIndicator size="small" color="#c94a4a" /> : (
                    <>
                      <Ionicons name="archive-outline" size={13} color="#c94a4a" />
                      <Text style={[styles.footerBtnT, { color: "#c94a4a" }]}>ARCHIVE</Text>
                    </>
                  )}
                </Pressable>
              </View>
            </>
          )}
        </ScrollView>
      </View>

      {/* Modals */}
      {detail ? (
        <>
          <EditListModal
            visible={showEditPoints}
            title="EDIT COACHING POINTS"
            items={detail.coaching_points || []}
            placeholder="e.g. Drive through the heel"
            onSave={(next) => patchExercise({ coaching_points: next }, "coaching")}
            onClose={() => setShowEditPoints(false)}
          />
          <EditListModal
            visible={showEditMistakes}
            title="EDIT COMMON MISTAKES"
            items={detail.common_mistakes || []}
            placeholder="e.g. Knees caving inward"
            onSave={(next) => patchExercise({ common_mistakes: next }, "mistakes")}
            onClose={() => setShowEditMistakes(false)}
          />
          <EditListModal
            visible={showEditAlts}
            title="EDIT ALTERNATIVES"
            items={detail.alternatives || []}
            placeholder="Related exercise name"
            onSave={(next) => patchExercise({ alternatives: next }, "alts")}
            onClose={() => setShowEditAlts(false)}
          />
          <EditTextModal
            visible={showEditVideo}
            title="EDIT VIDEO URL"
            value={detail.primary_video_url || ""}
            placeholder="https://…"
            multiline={false}
            onSave={(v) => patchExercise({ primary_video_url: v }, "video")}
            onClose={() => setShowEditVideo(false)}
          />
          <EditTextModal
            visible={showEditInstr}
            title="CLIENT-FACING INSTRUCTIONS"
            value={detail.client_facing_instructions || ""}
            placeholder="What the client sees before starting the movement…"
            onSave={(v) => patchExercise({ client_facing_instructions: v }, "instr")}
            onClose={() => setShowEditInstr(false)}
          />
          <ChangeLogModal
            visible={showLog}
            loading={logLoading}
            log={logRows}
            onClose={() => setShowLog(false)}
          />
        </>
      ) : null}
      <CreateExerciseModal
        visible={showCreate}
        onCreate={createExercise}
        onClose={() => setShowCreate(false)}
      />
    </SafeAreaView>
  );
}

function SectionHeader({ label, onEdit }: { label: string; onEdit?: () => void }) {
  return (
    <View style={styles.sectHeadRow}>
      <Text style={[styles.sect, { marginTop: 0, marginBottom: 0 }]}>{label}</Text>
      {onEdit ? (
        <Pressable onPress={onEdit} hitSlop={10} style={styles.sectEditBtn}>
          <Ionicons name="create-outline" size={13} color={theme.color.brand} />
          <Text style={styles.sectEditT}>EDIT</Text>
        </Pressable>
      ) : null}
    </View>
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
  filter: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 20, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, alignSelf: "center" },
  filterScroll: { flexGrow: 0, maxHeight: 46 },
  filterContent: { paddingHorizontal: 14, paddingVertical: 10, gap: 6, alignItems: "center" },
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
  sectHeadRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 14, marginBottom: 6 },
  sectEditBtn: { flexDirection: "row", alignItems: "center", gap: 3, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand },
  sectEditT: { color: theme.color.brand, fontSize: 9, fontWeight: "900", letterSpacing: 1 },
  instrT: { color: theme.color.text, fontSize: 13, fontFamily: theme.font.text, lineHeight: 19 },
  footerActs: { flexDirection: "row", gap: 8, marginTop: 20, marginBottom: 6 },
  footerBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 5, paddingVertical: 10, borderRadius: 8, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  footerBtnDanger: { borderColor: "#3a1216", backgroundColor: "#180608" },
  footerBtnT: { color: theme.color.textMuted, fontSize: 10, fontWeight: "900", letterSpacing: 1.2 },
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
