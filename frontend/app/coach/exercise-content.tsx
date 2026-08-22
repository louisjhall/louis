/**
 * Coach · Exercise Content Library (unified).
 *
 * Left  — searchable list + status/filter tabs + usage badges.
 * Right — selected exercise detail: images, start/end demo, coaching points,
 *         video, alternatives, approval controls, content log.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator, Alert, FlatList, Modal, Platform, Pressable, RefreshControl, ScrollView,
  StyleSheet, Text, TextInput, View,
} from "react-native";
import { Image } from "expo-image";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useFocusEffect, useLocalSearchParams } from "expo-router";
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
  // Iter188 · Coach-forced logging_type override — wins over the
  // client-side classifier when set. null = classifier decides.
  logging_type_override?: "timer" | "cardio" | "reps" | null;
  // Movement-aware image slots — supports bottom / top / apex / etc.
  demo_slots?: Record<string, string | null>;
  demo_slots_female?: Record<string, string | null>;
  // Iter 128c — Pilot-in-uniform frames for Flight Support exercises.
  demo_slots_pilot?: Record<string, string | null>;
  primary_pilot_id?: string | null;
  demo_start_pilot_id?: string | null;
  demo_end_pilot_id?: string | null;
  required_slots?: string[];
  movement_pattern?: string;
  category?: string;
  body_area?: string;
  tags?: string[];
  used_in_tomorrow_workouts_count?: number;
  used_in_active_programmes_count?: number;
  alternatives?: (string | { name?: string; purpose?: string; why?: string })[];
  // Iter189g/j · Purpose-tagged trio. When present, coach UI shows a
  // 3-slot layout with a coloured badge per purpose. Legacy flat
  // `alternatives` still supported for backward compat.
  alternatives_meta?: { name: string; purpose?: string; why?: string; backfilled?: boolean }[];
};

const FILTERS: { key: string; label: string; q: Record<string, string | boolean> }[] = [
  { key: "all", label: "ALL", q: {} },
  // Iter 140f — Phase A: absorb Demand Queue into Exercise Library.
  // Three new status/workflow tabs sit next to ALL so category filters
  // remain untouched further down the row.
  { key: "needs_review", label: "NEEDS REVIEW", q: { needs_review: true } },
  { key: "in_progress", label: "IN PROGRESS", q: { in_progress: true } },
  { key: "needs_media", label: "NEEDS MEDIA", q: { needs_media: true } },
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
  const params = useLocalSearchParams<{ tab?: string }>();
  const [items, setItems] = useState<Exercise[]>([]);
  const [selected, setSelected] = useState<Exercise | null>(null);
  const [detail, setDetail] = useState<Exercise | null>(null);
  const [filter, setFilter] = useState(
    // Iter 140f — deep-link support so /coach/demand-queue → /coach/exercise-content?tab=needs_review lands on the right tab
    typeof params.tab === "string" && FILTERS.some((f) => f.key === params.tab) ? (params.tab as string) : "all"
  );
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
  // Phase 5 P1: pending exercise-request count for the Demand Queue pill.
  const [pendingRequests, setPendingRequests] = useState<number>(0);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const g = await api<any>(`/exercise-requests/grouped`);
        if (cancelled) return;
        setPendingRequests((g?.counts?.needed_soon || 0) + (g?.counts?.awaiting_review || 0));
      } catch {}
    })();
    return () => { cancelled = true; };
  }, []);
  const [showLog, setShowLog] = useState(false);
  const [logRows, setLogRows] = useState<any[]>([]);
  const [logLoading, setLogLoading] = useState(false);

  // Image generation — prompt-preview modal (cross-platform; Alert.alert
  // collapses on web preview to a single "OK" which was the root cause of
  // the REGEN buttons appearing broken).
  // Iter 128c — three-way persona toggle (male-louis / female / pilot in
  // uniform). Legacy state name `genGender` retained via alias below to
  // minimise touch-diff.
  const [genPersona, setGenPersona] = useState<"male" | "female" | "pilot">("male");
  const genGender = genPersona; // legacy alias for existing code paths
  const [promptModal, setPromptModal] = useState<null | {
    slot: "primary" | "start" | "end" | "mid" | "top" | "bottom" | "apex" | "stretch" | "loaded" | "finish";
    persona: "male" | "female" | "pilot";
    prompt: string;
    cost: number;
    extra: string;
  }>(null);

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

  // Iter182 · Sequential bulk-generation of primary frame images for
  // every exercise in DRAFT_REQUESTED / MISSING state. The backend
  // handles the actual work — we kick off (202), then poll status every
  // 2 s so the button can never time out even if the sweep runs for
  // 20+ minutes over ~200 exercises. One image at a time server-side
  // so we never hammer Gemini in parallel.
  const bulkGenPrimaryImages = async () => {
    if (busy) return;
    setBusy("bulk-primary");
    try {
      const dry = await api<any>("/coach/auto-media-gen/bulk-primary-images", {
        method: "POST", body: { dry_run: true },
      });
      const would = Number(dry?.would_queue_count || 0);
      if (!would) {
        toast("No DRAFT_REQUESTED / MISSING exercises are missing a primary image.", "info");
        return;
      }
      const confirmed = await confirm({
        title: `Generate ${would} primary images?`,
        message:
          `${would} exercise${would === 1 ? "" : "s"} in DRAFT_REQUESTED / ` +
          "MISSING state have no primary image. Gemini will be called " +
          "once per exercise — this may take several minutes and will " +
          "spend credits from the auto-media budget.",
        confirmLabel: "GENERATE",
        cancelLabel: "CANCEL",
      });
      if (!confirmed) return;

      let kickoff: any;
      try {
        kickoff = await api<any>("/coach/auto-media-gen/bulk-primary-images", {
          method: "POST", body: {},
        });
      } catch (e: any) {
        const inflightJobId = e?.response?.job_id;
        if (inflightJobId) {
          kickoff = { job_id: inflightJobId, status: "already_running" };
          toast("Attaching to sweep already in progress…", "info");
        } else {
          toast(e?.response?.detail || e?.message || "Kickoff failed.", "error");
          return;
        }
      }
      const jobId: string = kickoff?.job_id;
      if (!jobId) {
        toast("Server did not return a job id.", "error");
        return;
      }

      // Poll every 2s, cap 30 min (900 polls).
      let lastWrote = 0;
      for (let i = 0; i < 900; i += 1) {
        await new Promise((r) => setTimeout(r, 2000));
        let s: any;
        try { s = await api<any>(`/coach/auto-media-gen/backfill-status/${jobId}`); }
        catch { continue; }
        const wrote = Number(s?.wrote || 0);
        const processed = Number(s?.processed || 0);
        const total = Number(s?.total_in_scope || would);
        if (wrote !== lastWrote) {
          toast(`… generating · ${wrote}/${total} images done`, "info");
          lastWrote = wrote;
        }
        if (s?.status === "complete") {
          const errs = Object.values(s?.errors || {}).reduce(
            (a: number, b: any) => a + Number(b || 0), 0,
          );
          if (s.budget_paused) {
            toast(
              `Budget paused mid-run — ${wrote}/${processed} done. Top up + resume + re-tap.`,
              "error",
            );
          } else if (errs) {
            toast(
              `Generated ${wrote}/${processed} primary images (${errs} errors — see logs).`,
              "info",
            );
          } else {
            toast(`Generated ${wrote}/${processed} primary images.`, "success");
          }
          await load();
          return;
        }
        if (s?.status === "failed") {
          toast(`Bulk generation failed: ${s?.error || "unknown"}.`, "error");
          return;
        }
      }
      toast("Bulk generation still running after 30 min — check status manually.", "info");
    } catch (e: any) {
      toast(e?.message || "Bulk generation failed.", "error");
    } finally {
      setBusy(null);
    }
  };

  const genImage = async (slot: "primary" | "start" | "end" | "mid" | "top" | "bottom" | "apex" | "stretch" | "loaded" | "finish") => {
    if (!detail) return;
    // Fetch the prompt preview so Louis sees the branded prompt + estimated
    // cost BEFORE anything is generated.
    setBusy(`prompt-${slot}`);
    try {
      const q = new URLSearchParams({ slot, persona: genPersona }).toString();
      const preview = await api<any>(`/exercise-content/${detail.id}/image-prompt?${q}`);
      setPromptModal({
        slot,
        persona: genPersona,
        prompt: preview?.prompt || "",
        cost: Number(preview?.estimated_cost_usd ?? 0.039),
        extra: "",
      });
    } catch (e: any) {
      Alert.alert("Couldn’t build prompt", e?.message || "");
    } finally {
      setBusy(null);
    }
  };

  const firePromptModal = async () => {
    if (!detail || !promptModal) return;
    const { slot, persona, extra } = promptModal;
    setBusy(`gen-${slot}`);
    setPromptModal(null);
    try {
      const r = await api<{ image_id: string }>(
        `/exercise-content/${detail.id}/generate-image`,
        {
          method: "POST",
          body: {
            slot,
            persona,
            // Keep legacy `female` bool populated for any older middleware.
            female: persona === "female",
            ...(extra.trim() ? { prompt_extra: extra.trim() } : {}),
          },
        },
      );
      await refreshDetail(detail.id);
      pollImage(r.image_id, detail.id);
    } catch (e: any) {
      Alert.alert("Generation failed", e?.message || "Please try again.");
    } finally {
      setBusy(null);
    }
  };

  const genContent = async (kind: "coaching_points" | "common_mistakes" | "alternatives" | "instructions") => {
    if (!detail) return;
    setBusy(`content-${kind}`);
    try {
      const r = await api<{ exercise: Exercise }>(
        `/exercise-content/${detail.id}/generate-content`,
        { method: "POST", body: { kind } },
      );
      setDetail(r.exercise);
      setItems((prev) => prev.map((x) => (x.id === r.exercise.id ? { ...x, ...r.exercise } : x)));
      toast(`${kind.replace("_", " ")} generated`, "success");
    } catch (e: any) {
      Alert.alert("Content generation failed", e?.message || "Please try again.");
    } finally {
      setBusy(null);
    }
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
        <Text style={styles.topT}>EXERCISE CONTENT · v1.0.25</Text>
        <View style={{ flexDirection: "row", gap: 14, alignItems: "center" }}>
          <Pressable
            testID="auto-media-settings-btn"
            onPress={() => router.push("/coach/admin/auto-media" as any)}
            hitSlop={12}
            style={{ flexDirection: "row", alignItems: "center", gap: 4 }}
          >
            <Ionicons name="sparkles-outline" size={20} color={theme.color.brand} />
          </Pressable>
          <Pressable
            testID="demand-queue-btn"
            onPress={() => setFilter("needs_review")}
            hitSlop={12}
            style={{ flexDirection: "row", alignItems: "center", gap: 4 }}
          >
            <Ionicons name="git-pull-request" size={20} color={pendingRequests > 0 ? "#e5a337" : theme.color.brand} />
            {pendingRequests > 0 ? (
              <View style={{ backgroundColor: "#e5a337", paddingHorizontal: 6, paddingVertical: 1, borderRadius: 8, minWidth: 18, alignItems: "center" }}>
                <Text style={{ color: "#fff", fontSize: 11, fontWeight: "800" }}>{pendingRequests}</Text>
              </View>
            ) : null}
          </Pressable>
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

      {/* Iter182 · Bulk primary-image generation for DRAFT_REQUESTED /
          MISSING exercises. One Gemini call at a time server-side so we
          never hammer the API. Disabled while another `busy` action is
          in flight so the coach can't kick off two sweeps. Rendered as
          a filled brand-red button (Iter182c) so it's visually distinct
          from the filter chips below and impossible to miss. */}
      <View style={{ paddingHorizontal: 14, paddingTop: 8, paddingBottom: 4 }}>
        <Pressable
          onPress={bulkGenPrimaryImages}
          disabled={busy === "bulk-primary" || !!busy}
          style={[
            styles.bulkBtn,
            (busy === "bulk-primary" || !!busy) && { opacity: 0.5 },
          ]}
          testID="bulk-gen-primary-images"
        >
          {busy === "bulk-primary" ? (
            <ActivityIndicator color="#fff" size="small" />
          ) : (
            <Ionicons name="images" size={16} color="#fff" />
          )}
          <Text style={styles.bulkBtnT}>
            GENERATE MISSING PRIMARY IMAGES · DRAFT / MISSING
          </Text>
        </Pressable>
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

              {/* Iter188 · Logging-type override — coach escape hatch for
                  any exercise the workout player's automatic classifier
                  puts in the wrong bucket. Default is AUTO (classifier
                  decides via name + reps + category). Force TIMER for a
                  hold that doesn't match the regex, CARDIO for a piece
                  of cardio kit misnamed, or REPS to disable the timer. */}
              <Text style={styles.sect}>WORKOUT PLAYER LOGGING</Text>
              <LoggingTypeOverrideRow
                current={detail.logging_type_override ?? null}
                onChange={async (next) => {
                  const prev = detail.logging_type_override ?? null;
                  setDetail({ ...detail, logging_type_override: next });
                  try {
                    await api(`/coach/library/exercise/${detail.id}/logging-type`, {
                      method: "PATCH",
                      body: { logging_type: next },
                    });
                    const { reloadOverrides } = await import("@/src/lib/loggingTypeOverrides");
                    await reloadOverrides();
                  } catch (e: any) {
                    setDetail({ ...detail, logging_type_override: prev });
                    Alert.alert("Couldn't save override", e?.message || "Please try again.");
                  }
                }}
              />

              {/* Images */}
              <Text style={styles.sect}>DEMO IMAGES</Text>
              <View style={styles.genderRow}>
                <Pressable
                  onPress={() => setGenPersona("male")}
                  style={[styles.gChip, genPersona === "male" && styles.gChipActive]}
                  testID="gen-persona-male"
                >
                  <Ionicons name="man" size={12} color={genPersona === "male" ? "#fff" : theme.color.textMuted} />
                  <Text style={[styles.gChipT, genPersona === "male" && { color: "#fff" }]}>MALE · LOUIS</Text>
                </Pressable>
                <Pressable
                  onPress={() => setGenPersona("female")}
                  style={[styles.gChip, genPersona === "female" && styles.gChipActive]}
                  testID="gen-persona-female"
                >
                  <Ionicons name="woman" size={12} color={genPersona === "female" ? "#fff" : theme.color.textMuted} />
                  <Text style={[styles.gChipT, genPersona === "female" && { color: "#fff" }]}>FEMALE</Text>
                </Pressable>
                <Pressable
                  onPress={() => setGenPersona("pilot")}
                  style={[styles.gChip, genPersona === "pilot" && styles.gChipActive]}
                  testID="gen-persona-pilot"
                >
                  <Ionicons name="airplane" size={12} color={genPersona === "pilot" ? "#fff" : theme.color.textMuted} />
                  <Text style={[styles.gChipT, genPersona === "pilot" && { color: "#fff" }]}>PILOT · UNIFORM</Text>
                </Pressable>
                <Text style={styles.genderHint}>
                  {genPersona === "male"
                    ? "Louis reference locked · red shoes"
                    : genPersona === "female"
                    ? "Athletic female · red shoes"
                    : "Airline pilot · white shirt, black tie, epaulettes"}
                </Text>
              </View>

              {/* Movement-aware slot picker — coach selects which positions
                  this exercise actually needs. Defaults are derived from
                  the movement pattern (e.g. push-up → primary/start/bottom). */}
              <SlotPicker
                required={resolveRequiredSlots(detail)}
                onToggle={async (slot) => {
                  const cur = resolveRequiredSlots(detail);
                  const next = cur.includes(slot) ? cur.filter((s) => s !== slot) : [...cur, slot];
                  // Always keep "primary" as it drives preview cards.
                  const ensured = next.includes("primary") ? next : ["primary", ...next];
                  try {
                    await api(`/exercise-content/${detail.id}/required-slots`, {
                      method: "PATCH",
                      body: { slots: ensured },
                    });
                    setDetail({ ...detail, required_slots: ensured });
                  } catch (e: any) {
                    Alert.alert("Couldn’t save slots", e?.message || "");
                  }
                }}
              />

              <View style={styles.imgGrid}>
                {resolveRequiredSlots(detail).map((slot) => {
                  const iid = imageIdForSlot(detail, slot, genGender) || null;
                  return (
                    <ImgSlot
                      key={`${slot}-${iid || "none"}`}
                      title={slot.toUpperCase()}
                      url={imgUrl(iid)}
                      imageId={iid}
                      onGen={() => genImage(slot as any)}
                      busy={busy === `gen-${slot}` || busy === `prompt-${slot}`}
                    />
                  );
                })}
              </View>

              {/* Coaching points */}
              <SectionHeader
                label={`COACHING POINTS · ${detail.coaching_points?.length || 0}`}
                onEdit={() => setShowEditPoints(true)}
                onAtlas={() => genContent("coaching_points")}
                atlasBusy={busy === "content-coaching_points"}
              />
              {(detail.coaching_points || []).length ? (detail.coaching_points || []).map((p, i) => (
                <View key={i} style={styles.cpRow}>
                  <Ionicons name="checkmark-circle" size={13} color={theme.color.brand} />
                  <Text style={styles.cpT}>{p}</Text>
                </View>
              )) : <Text style={styles.empty}>No coaching points yet. Tap edit or Atlas ✨ to generate.</Text>}

              {/* Common Mistakes */}
              <SectionHeader
                label={`COMMON MISTAKES · ${detail.common_mistakes?.length || 0}`}
                onEdit={() => setShowEditMistakes(true)}
                onAtlas={() => genContent("common_mistakes")}
                atlasBusy={busy === "content-common_mistakes"}
              />
              {(detail.common_mistakes || []).length ? (detail.common_mistakes || []).map((m, i) => (
                <View key={i} style={styles.cpRow}>
                  <Ionicons name="warning" size={13} color={theme.color.amber} />
                  <Text style={styles.cpT}>{m}</Text>
                </View>
              )) : <Text style={styles.empty}>None recorded. Tap Atlas ✨ to generate.</Text>}

              {/* Client-Facing Instructions */}
              <SectionHeader
                label="CLIENT INSTRUCTIONS"
                onEdit={() => setShowEditInstr(true)}
                onAtlas={() => genContent("instructions")}
                atlasBusy={busy === "content-instructions"}
              />
              <Text style={detail.client_facing_instructions ? styles.instrT : styles.empty}>
                {detail.client_facing_instructions || "No instructions yet. Tap edit or Atlas ✨."}
              </Text>

              {/* Alternatives — Iter189j · Defensive rendering.
                  Historically the backend has stored alternatives as
                  plain strings, but iter189g introduced dicts with
                  `purpose` metadata AND some rows on production ended
                  up with stringified JSON (raw {"name": ...}) because
                  of a partial LLM parse. This block normalises every
                  shape into a `{name, purpose}` tuple before rendering. */}
              <SectionHeader
                label={`ALTERNATIVES · ${(detail.alternatives_meta?.length || detail.alternatives?.length || 0)}`}
                onEdit={() => setShowEditAlts(true)}
                onAtlas={() => genContent("alternatives")}
                atlasBusy={busy === "content-alternatives"}
              />
              {(() => {
                // Prefer purpose-tagged meta if present, else the flat
                // legacy list. Deduplicate by lowercased name.
                type NormAlt = { name: string; purpose?: string; why?: string };
                const norm: NormAlt[] = [];
                const seen = new Set<string>();
                const pushIfUnique = (a: NormAlt) => {
                  const k = a.name.trim().toLowerCase();
                  if (!k || seen.has(k)) return;
                  seen.add(k);
                  norm.push(a);
                };
                if (detail.alternatives_meta?.length) {
                  for (const m of detail.alternatives_meta) {
                    if (m?.name) pushIfUnique({ name: m.name, purpose: m.purpose, why: m.why });
                  }
                }
                for (const raw of detail.alternatives || []) {
                  if (typeof raw === "string") {
                    const t = raw.trim();
                    if (!t) continue;
                    // Iter189j · If the string looks like JSON, try to
                    // parse it and pull `.name`. Handles legacy rows
                    // where the LLM output was written into the flat
                    // list before parsing was fixed.
                    if (t.startsWith("{") || t.startsWith("[")) {
                      try {
                        const parsed = JSON.parse(t);
                        const arr = Array.isArray(parsed) ? parsed : [parsed];
                        for (const p of arr) {
                          if (p && typeof p === "object" && (p as any).name) {
                            pushIfUnique({ name: String((p as any).name), purpose: (p as any).purpose, why: (p as any).why });
                          }
                        }
                        continue;
                      } catch { /* fall through — display raw as name */ }
                    }
                    pushIfUnique({ name: t });
                  } else if (raw && typeof raw === "object" && (raw as any).name) {
                    pushIfUnique({ name: String((raw as any).name), purpose: (raw as any).purpose, why: (raw as any).why });
                  }
                }
                if (!norm.length) return <Text style={styles.empty}>None linked.</Text>;
                const purposeMeta: Record<string, { color: string; label: string }> = {
                  equipment_swap:            { color: "#4a90e2", label: "Equipment" },
                  easier_regression:         { color: "#7ac74f", label: "Easier" },
                  injury_mobility_friendly:  { color: "#d99a3f", label: "Injury-friendly" },
                };
                return norm.slice(0, 6).map((a, i) => {
                  const meta = a.purpose ? purposeMeta[a.purpose] : undefined;
                  return (
                    <View key={`${a.name}-${i}`} style={styles.altRow}>
                      <Ionicons name="swap-horizontal" size={13} color={theme.color.textMuted} />
                      <View style={{ flex: 1 }}>
                        <View style={styles.altRowTop}>
                          <Text style={styles.cpT} numberOfLines={2}>{a.name}</Text>
                          {meta && (
                            <View style={[styles.altBadge, { backgroundColor: meta.color + "22", borderColor: meta.color }]}>
                              <Text style={[styles.altBadgeT, { color: meta.color }]}>{meta.label.toUpperCase()}</Text>
                            </View>
                          )}
                        </View>
                        {!!a.why && <Text style={styles.altWhy} numberOfLines={2}>{a.why}</Text>}
                      </View>
                    </View>
                  );
                });
              })()}

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
            // Iter189j · Normalise mixed shapes (string / dict / JSON-string)
            // into plain names so the modal never shows raw JSON. When
            // saved, the backend keeps `alternatives_meta` intact — we only
            // overwrite the flat legacy `alternatives` list here.
            items={(() => {
              const out: string[] = [];
              const seen = new Set<string>();
              const push = (n: string) => {
                const t = n.trim();
                if (!t) return;
                const k = t.toLowerCase();
                if (seen.has(k)) return;
                seen.add(k);
                out.push(t);
              };
              if (detail.alternatives_meta?.length) {
                for (const m of detail.alternatives_meta) if (m?.name) push(m.name);
              }
              for (const raw of detail.alternatives || []) {
                if (typeof raw === "string") {
                  const t = raw.trim();
                  if (t.startsWith("{") || t.startsWith("[")) {
                    try {
                      const parsed = JSON.parse(t);
                      const arr = Array.isArray(parsed) ? parsed : [parsed];
                      for (const p of arr) if (p && typeof p === "object" && (p as any).name) push(String((p as any).name));
                      continue;
                    } catch { /* fall through */ }
                  }
                  push(t);
                } else if (raw && typeof raw === "object" && (raw as any).name) {
                  push(String((raw as any).name));
                }
              }
              return out;
            })()}
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

      {/* Prompt-preview modal — replaces the broken Alert.alert flow so it
          works on iOS, Android AND the web preview. */}
      <Modal
        visible={!!promptModal}
        transparent
        animationType="slide"
        onRequestClose={() => setPromptModal(null)}
      >
        <Pressable style={styles.pmBackdrop} onPress={() => setPromptModal(null)} />
        <View style={styles.pmSheet}>
          <View style={styles.pmGrabber} />
          <Text style={styles.pmTitle}>
            Generate {promptModal?.slot?.toUpperCase()} image ·{" "}
            {promptModal?.persona === "female"
              ? "Female"
              : promptModal?.persona === "pilot"
              ? "Pilot · Uniform"
              : "Male · Louis"}
          </Text>
          <Text style={styles.pmCost}>
            Estimated cost: ${promptModal?.cost.toFixed(3)} · 1 image credit
          </Text>
          <ScrollView style={styles.pmPromptBox} contentContainerStyle={{ padding: 12 }}>
            <Text style={styles.pmPromptT}>{promptModal?.prompt}</Text>
          </ScrollView>
          <Text style={styles.pmLabel}>ADD EXTRA INSTRUCTIONS (OPTIONAL)</Text>
          <TextInput
            testID="prompt-extra-input"
            style={styles.pmInput}
            multiline
            value={promptModal?.extra || ""}
            onChangeText={(v) =>
              setPromptModal((prev) => (prev ? { ...prev, extra: v } : prev))
            }
            placeholder="e.g. emphasise hip hinge, keep hands wide, single arm"
            placeholderTextColor={theme.color.textDim}
          />
          <View style={styles.pmBtnRow}>
            <Pressable
              onPress={() => setPromptModal(null)}
              style={[styles.pmBtn, styles.pmBtnGhost]}
              testID="prompt-cancel"
            >
              <Text style={styles.pmBtnGhostT}>CANCEL</Text>
            </Pressable>
            <Pressable
              onPress={firePromptModal}
              style={[styles.pmBtn, styles.pmBtnPrimary]}
              testID="prompt-generate"
            >
              <Ionicons name="sparkles" size={14} color="#fff" />
              <Text style={styles.pmBtnPrimaryT}>GENERATE</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

function SectionHeader({
  label, onEdit, onAtlas, atlasBusy,
}: { label: string; onEdit?: () => void; onAtlas?: () => void; atlasBusy?: boolean }) {
  return (
    <View style={styles.sectHeadRow}>
      <Text style={[styles.sect, { marginTop: 0, marginBottom: 0, flex: 1 }]}>{label}</Text>
      {onAtlas ? (
        <Pressable onPress={onAtlas} hitSlop={10} disabled={atlasBusy} style={[styles.sectEditBtn, atlasBusy && { opacity: 0.5 }]}>
          {atlasBusy ? <ActivityIndicator color={theme.color.brand} size="small" /> : (
            <>
              <Ionicons name="sparkles" size={12} color={theme.color.brand} />
              <Text style={styles.sectEditT}>ATLAS</Text>
            </>
          )}
        </Pressable>
      ) : null}
      {onEdit ? (
        <Pressable onPress={onEdit} hitSlop={10} style={styles.sectEditBtn}>
          <Ionicons name="create-outline" size={13} color={theme.color.brand} />
          <Text style={styles.sectEditT}>EDIT</Text>
        </Pressable>
      ) : null}
    </View>
  );
}


// ---------------------------------------------------------------------------
// Movement-aware helpers — mirror the backend's `_default_slots_for_movement`
// so the UI can pre-populate the slot picker even before the coach hits save.
// ---------------------------------------------------------------------------
const ALL_SLOTS: string[] = [
  "primary", "start", "mid", "end", "top", "bottom",
  "apex", "stretch", "loaded", "finish",
];

function defaultSlotsForMovement(ex: Exercise): string[] {
  const tokens = [
    ex.exercise_name || "",
    ex.movement_pattern || "",
    ex.category || "",
    ex.body_area || "",
    (ex.tags || []).join(" "),
  ].join(" ").toLowerCase();
  const has = (...ks: string[]) => ks.some((k) => tokens.includes(k));
  if (has("push-up", "push up", "pushup", "press-up", "press up", "pressup", "bench press", "chest press", "dip"))
    return ["primary", "start", "bottom"];
  if (has("overhead press", "shoulder press", "military press", "push press"))
    return ["primary", "start", "top"];
  if (has("row", "pulldown", "pull-up", "pull up", "pullup", "chin-up", "chinup", "face pull", "reverse fly", "high pull"))
    return ["primary", "start", "top"];
  if (has("squat", "lunge", "split squat", "deadlift", "rdl", "hip hinge", "hinge", "step-up", "step up", "good morning"))
    return ["primary", "start", "bottom"];
  if (has("bridge", "hip thrust", "thrust")) return ["primary", "start", "top"];
  if (has("calf raise", "calf")) return ["primary", "start", "top"];
  if (has("rotation", "twist", "windmill", "world's greatest")) return ["primary", "start", "finish"];
  if (has("plank", "hollow hold", "l-sit", "wall sit")) return ["primary", "loaded"];
  if (has("stretch", "mobility", "release", "opener", "myrtl")) return ["primary", "stretch"];
  return ["primary", "start", "end"];
}

function resolveRequiredSlots(ex: Exercise): string[] {
  if (ex.required_slots && ex.required_slots.length > 0) return ex.required_slots;
  return defaultSlotsForMovement(ex);
}

function imageIdForSlot(
  ex: Exercise, slot: string,
  persona: "male" | "female" | "pilot",
): string | null | undefined {
  // Legacy fields for start/end/primary stay in sync for the DEFAULT
  // (male-louis) persona — prefer them so existing readers keep working.
  // Female and Pilot personas live in their own maps and never overwrite
  // Louis's default frames.
  const legacyMale: Record<string, string | null | undefined> = {
    primary: ex.primary_image_id,
    start:   ex.demo_start_image_id,
    end:     ex.demo_end_image_id,
  };
  const legacyPilot: Record<string, string | null | undefined> = {
    primary: ex.primary_pilot_id,
    start:   ex.demo_start_pilot_id,
    end:     ex.demo_end_pilot_id,
  };
  const map =
    persona === "female"
      ? (ex.demo_slots_female || {})
      : persona === "pilot"
      ? (ex.demo_slots_pilot || {})
      : (ex.demo_slots || {});
  const legacy = persona === "pilot" ? legacyPilot : persona === "male" ? legacyMale : {};
  return (map as Record<string, string | null | undefined>)[slot] || (legacy as Record<string, string | null | undefined>)[slot] || null;
}

function SlotPicker({
  required, onToggle,
}: { required: string[]; onToggle: (slot: string) => void }) {
  return (
    <View style={styles.slotPickerWrap}>
      <Text style={styles.slotPickerLabel}>REQUIRED POSITIONS</Text>
      <View style={styles.slotChipsRow}>
        {ALL_SLOTS.map((s) => {
          const on = required.includes(s);
          const isPrimary = s === "primary";
          return (
            <Pressable
              key={s}
              onPress={() => (isPrimary ? null : onToggle(s))}
              style={[styles.slotChip, on && styles.slotChipActive, isPrimary && styles.slotChipLocked]}
              testID={`slot-chip-${s}`}
            >
              {on && <Ionicons name="checkmark" size={10} color="#fff" />}
              <Text style={[styles.slotChipT, on && { color: "#fff" }]}>{s.toUpperCase()}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}


function ImgSlot({ title, url, onGen, busy, imageId }: any) {
  // Nano-Banana generation can lag a few seconds behind the DB update
  // (see feature_exercise_content._run_image_job). Meanwhile the stream
  // endpoint returns a transparent placeholder with no-store. We poll
  // the status API and, once the image lands, force a fresh fetch with
  // a cache-buster so the tile shows the real artwork.
  const [ready, setReady] = React.useState<boolean | null>(null);
  const [bust, setBust] = React.useState<number>(0);
  const [errored, setErrored] = React.useState(false);

  React.useEffect(() => {
    // Reset when either the image_id changes or a fresh gen was kicked off.
    setReady(null); setBust(Date.now()); setErrored(false);
    if (!imageId) return;
    let cancelled = false;
    let attempts = 0;
    const tick = async () => {
      if (cancelled) return;
      try {
        const r = await api<any>(`/exercise-content/images/${imageId}`);
        const st = String(r?.image?.status || "").toLowerCase();
        if (st === "ready") {
          if (!cancelled) { setReady(true); setBust(Date.now()); setErrored(false); }
          return;
        }
        if (st === "failed") {
          if (!cancelled) { setReady(false); setErrored(true); }
          return;
        }
      } catch { /* silent */ }
      attempts += 1;
      if (attempts < 40 && !cancelled) setTimeout(tick, 3000);
    };
    // Small initial delay so we don't hammer during obvious "just clicked".
    const to = setTimeout(tick, 1500);
    return () => { cancelled = true; clearTimeout(to); };
  }, [imageId]);

  const displayUrl = url ? `${url}${url.includes("?") ? "&" : "?"}v=${bust}` : null;
  const showImg = displayUrl && !errored && (ready === true || ready === null);
  const showPending = displayUrl && ready === false && !errored ? false : (displayUrl && ready === null && !errored);
  return (
    <View style={styles.imgSlot}>
      <View style={styles.imgBox}>
        {showImg ? (
          <Image
            key={`${imageId}-${bust}`}
            source={{ uri: displayUrl! }}
            style={{ width: "100%", height: "100%" }}
            contentFit="cover"
            transition={200}
            onError={() => setErrored(true)}
          />
        ) : (
          <Ionicons name={errored ? "warning-outline" : "image-outline"} size={22} color={theme.color.textDim} />
        )}
        {showPending && (
          <View style={{ position: "absolute", inset: 0, alignItems: "center", justifyContent: "center", backgroundColor: "rgba(0,0,0,0.35)" }}>
            <ActivityIndicator color={theme.color.brand} />
          </View>
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

/* -------------------------------------------------------------------------- */
/*  Iter188 · Logging-type override segment control                            */
/* -------------------------------------------------------------------------- */
function LoggingTypeOverrideRow({
  current, onChange,
}: {
  current: "timer" | "cardio" | "reps" | null;
  onChange: (next: "timer" | "cardio" | "reps" | null) => void;
}) {
  const opts: { value: "timer" | "cardio" | "reps" | null; label: string; icon: any; hint: string }[] = [
    { value: null,     label: "AUTO",   icon: "flash",       hint: "Classifier decides (default)" },
    { value: "timer",  label: "TIMER",  icon: "hourglass",   hint: "Force hold timer" },
    { value: "cardio", label: "CARDIO", icon: "bicycle",     hint: "Force cardio stopwatch" },
    { value: "reps",   label: "REPS",   icon: "barbell",     hint: "Force reps + weight" },
  ];
  const activeHint = opts.find((o) => o.value === current)?.hint || opts[0].hint;
  return (
    <View style={ltoStyles.wrap} testID="logging-type-override">
      <View style={ltoStyles.row}>
        {opts.map((o) => {
          const active = current === o.value;
          return (
            <Pressable
              key={String(o.value)}
              onPress={() => onChange(o.value)}
              style={[ltoStyles.opt, active && ltoStyles.optActive]}
              testID={`lto-${o.label.toLowerCase()}`}
              accessibilityRole="button"
              accessibilityState={{ selected: active }}
            >
              <Ionicons
                name={o.icon}
                size={13}
                color={active ? "#fff" : theme.color.textMuted}
              />
              <Text style={[ltoStyles.optT, active && { color: "#fff" }]}>{o.label}</Text>
            </Pressable>
          );
        })}
      </View>
      <Text style={ltoStyles.hint}>{activeHint}</Text>
    </View>
  );
}

const ltoStyles = StyleSheet.create({
  wrap: { marginTop: 4, marginBottom: 12 },
  row: {
    flexDirection: "row",
    gap: 6,
    backgroundColor: theme.color.surface2,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: theme.color.border,
    padding: 4,
  },
  opt: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 4,
    paddingVertical: 8,
    borderRadius: 6,
  },
  optActive: { backgroundColor: theme.color.brand },
  optT: {
    color: theme.color.textMuted,
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 1.2,
  },
  hint: {
    color: theme.color.textMuted,
    fontSize: 10.5,
    fontStyle: "italic",
    marginTop: 6,
    paddingHorizontal: 4,
  },
});

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  top: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 14, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  topT: { color: theme.color.text, fontSize: 14, letterSpacing: 2, fontWeight: "900", fontFamily: theme.font.display },
  search: { backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 8, color: theme.color.onRed, fontSize: 13 },
  // Iter182c · Bulk primary-image generation trigger. Filled brand-red
  // so it visually reads as a primary CTA and can't be mistaken for a
  // filter pill. Previously ghost-outlined which was too subtle.
  bulkBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 8, paddingVertical: 12, borderRadius: 8,
    borderWidth: 1, borderColor: theme.color.brand,
    backgroundColor: theme.color.brand,
  },
  bulkBtnT: {
    color: "#fff", fontSize: 12, fontWeight: "900",
    letterSpacing: 1.2,
  },
  filter: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 20, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, alignSelf: "center" },
  filterScroll: { flexGrow: 0, maxHeight: 46 },
  filterContent: { paddingHorizontal: 14, paddingVertical: 10, gap: 6, alignItems: "center" },
  filterOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  filterT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1 },
  filterTOn: { color: "#fff" },

  leftPane: { width: 170, borderRightWidth: 1, borderRightColor: theme.color.divider, backgroundColor: theme.color.surface2 },
  rightPane: { flex: 1 },
  empty: { color: theme.color.textDim, textAlign: "center", marginTop: 40, fontStyle: "italic", padding: 20 },

  row: { padding: 10, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: theme.color.divider },
  rowOn: { backgroundColor: theme.color.surface3 },
  rowName: { color: theme.color.text, fontSize: 12, fontWeight: "800", fontFamily: theme.font.textSemi },
  rowMeta: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 4, flexWrap: "wrap" },
  dot: { width: 6, height: 6, borderRadius: 3 },
  rowMetaT: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1, fontWeight: "800" },
  tomBadge: { flexDirection: "row", alignItems: "center", gap: 2, paddingHorizontal: 4, paddingVertical: 2, borderRadius: 8, backgroundColor: "rgba(245,158,11,0.15)" },
  tomT: { color: theme.color.amber, fontSize: 11, fontWeight: "900", letterSpacing: 0.5 },
  missBadge: { paddingHorizontal: 4, paddingVertical: 2, borderRadius: 8, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand },
  missT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 0.5 },

  detailName: { color: theme.color.text, fontSize: 20, fontWeight: "900", letterSpacing: 0.5, fontFamily: theme.font.display },
  detailCat: { color: theme.color.brand, fontSize: 11, letterSpacing: 2, fontWeight: "900", marginTop: 2, fontFamily: theme.font.textSemi },
  pillsRow: { flexDirection: "row", gap: 6, marginTop: 8, flexWrap: "wrap" },
  statusPill: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 12 },
  statusPillT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1 },

  sect: { color: theme.color.brand, fontSize: 11, letterSpacing: 2, fontWeight: "900", fontFamily: theme.font.textSemi, marginTop: 14, marginBottom: 6 },
  sectHeadRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 14, marginBottom: 6 },
  sectEditBtn: { flexDirection: "row", alignItems: "center", gap: 3, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand },
  sectEditT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1 },
  instrT: { color: theme.color.text, fontSize: 13, fontFamily: theme.font.text, lineHeight: 19 },
  footerActs: { flexDirection: "row", gap: 8, marginTop: 20, marginBottom: 6 },
  footerBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 5, paddingVertical: 10, borderRadius: 8, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  footerBtnDanger: { borderColor: "#3a1216", backgroundColor: "#180608" },
  footerBtnT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1.2 },
  imgGrid: { flexDirection: "row", gap: 8 },
  imgSlot: { flex: 1, alignItems: "stretch", gap: 4 },
  imgBox: { aspectRatio: 3 / 4, borderRadius: 10, backgroundColor: "#000", borderWidth: 1, borderColor: theme.color.border, alignItems: "center", justifyContent: "center", overflow: "hidden" },
  imgSlotT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1, textAlign: "center" },
  genBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 4, paddingVertical: 6, borderRadius: 8, backgroundColor: theme.color.brand },
  genT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 0.7 },

  cpRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 4 },
  cpT: { color: theme.color.text, fontSize: 13, flex: 1, fontFamily: theme.font.text },
  // Iter189j · Alternatives row layout — supports optional purpose
  // badge + optional "why" subtitle without breaking the plain
  // string-only rendering path.
  altRow: { flexDirection: "row", alignItems: "flex-start", gap: 8, paddingVertical: 6 },
  altRowTop: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 },
  altBadge: {
    alignSelf: "flex-start", paddingHorizontal: 7, paddingVertical: 2,
    borderRadius: 4, borderWidth: 1,
  },
  altBadgeT: { fontSize: 9, fontWeight: "900", letterSpacing: 1.1 },
  altWhy: {
    color: theme.color.textMuted, fontSize: 11, marginTop: 3, lineHeight: 15,
    fontStyle: "italic",
  },

  metaCard: { flexDirection: "row", alignItems: "center", gap: 8, padding: 10, borderRadius: 10, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  metaCardK: { color: theme.color.textDim, fontSize: 11, letterSpacing: 1, fontWeight: "800" },
  metaCardV: { color: theme.color.text, fontSize: 12, marginTop: 2 },
  videoBadge: { paddingHorizontal: 6, paddingVertical: 3, borderRadius: 10 },
  videoBadgeT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1 },

  approveGrid: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 4 },
  appBtn: { flexBasis: "48%", paddingVertical: 10, borderRadius: 8, borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface2, alignItems: "center" },
  appBtnPri: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  appBtnMuted: { backgroundColor: theme.color.surface3 },
  appBtnT: { color: theme.color.text, fontSize: 11, fontWeight: "900", letterSpacing: 1 },
  // Slot picker
  slotPickerWrap: { marginBottom: 10 },
  slotPickerLabel: { color: theme.color.textDim, fontSize: 11, fontWeight: "900", letterSpacing: 1.4, marginBottom: 6 },
  slotChipsRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  slotChip: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  slotChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  slotChipLocked: { opacity: 0.9 },
  slotChipT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1 },
  // Gender toggle
  genderRow: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 10, flexWrap: "wrap" },
  gChip: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  gChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  gChipT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1 },
  genderHint: { flex: 1, color: theme.color.textDim, fontSize: 11, marginLeft: 4 },
  // Prompt preview modal
  pmBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)" },
  pmSheet: {
    position: "absolute", left: 0, right: 0, bottom: 0,
    backgroundColor: theme.color.surface,
    borderTopLeftRadius: 22, borderTopRightRadius: 22,
    paddingHorizontal: 18, paddingTop: 10,
    paddingBottom: Platform.OS === "ios" ? 32 : 20,
    maxHeight: "88%",
  },
  pmGrabber: { width: 40, height: 4, borderRadius: 2, backgroundColor: theme.color.border, alignSelf: "center", marginBottom: 10 },
  pmTitle: { color: theme.color.text, fontSize: 15, fontWeight: "900", letterSpacing: 0.4 },
  pmCost: { color: theme.color.textMuted, fontSize: 11, marginTop: 4, fontWeight: "700" },
  pmPromptBox: {
    marginTop: 12, maxHeight: 210,
    backgroundColor: theme.color.surface2, borderRadius: 10,
    borderWidth: 1, borderColor: theme.color.border,
  },
  pmPromptT: { color: theme.color.text, fontSize: 12, lineHeight: 18 },
  pmLabel: { color: theme.color.textDim, fontSize: 11, fontWeight: "900", letterSpacing: 1.4, marginTop: 14 },
  pmInput: {
    marginTop: 6, minHeight: 60, maxHeight: 120,
    backgroundColor: theme.color.surface2, borderRadius: 10,
    borderWidth: 1, borderColor: theme.color.border,
    padding: 10, color: theme.color.onRed, fontSize: 13, textAlignVertical: "top",
  },
  pmBtnRow: { flexDirection: "row", gap: 10, marginTop: 16 },
  pmBtn: { flex: 1, paddingVertical: 12, borderRadius: 999, alignItems: "center", justifyContent: "center", flexDirection: "row", gap: 6 },
  pmBtnGhost: { borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface2 },
  pmBtnGhostT: { color: theme.color.text, fontWeight: "900", fontSize: 12, letterSpacing: 1.2 },
  pmBtnPrimary: { backgroundColor: theme.color.brand },
  pmBtnPrimaryT: { color: "#fff", fontWeight: "900", fontSize: 12, letterSpacing: 1.2 },
});
