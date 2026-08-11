/**
 * FlightSupportProtocolModal — dedicated protocol experience for a single
 * Flight Support intervention.
 *
 * Three phases:
 *   overview → guided → complete
 *
 * IMPORTANT
 *   Flight Support is NOT a workout. This modal:
 *     - does not log sets to /workouts/{id}/sets
 *     - does not affect training volume, compliance, or quotas
 *     - only calls the existing /client/flight-support/complete endpoint
 *   Everything about the pilot's programme classification stays identical.
 *
 * Reused components
 *   - ExerciseThumbnail  → demo image + tap-to-video via the curated library
 *   - api                → same fetcher used everywhere
 *   - theme              → shared tokens
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  View, Text, StyleSheet, Modal, Pressable, ScrollView, ActivityIndicator, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Image as ExpoImage } from "expo-image";
import { theme } from "@/src/lib/theme";
import { api, API_BASE, getToken } from "@/src/lib/api";
import { ExerciseThumbnail } from "@/src/components/ExerciseThumbnail";
import { hapticSuccess } from "@/src/lib/haptics";
import { speak, stopNarration } from "@/src/lib/narration";

type Block = {
  name: string;
  duration_sec?: number;
  duration_min?: number;
  cue?: string;
  type?: string;
};

type Intervention = {
  id: string;
  date: string;
  protocol_key: string;
  title: string;
  family: string;
  intensity: string;
  duration_min: number;
  cues?: string[];
  blocks?: Block[];
  trigger_reason?: string;
  completion_status?: "not_started" | "completed" | "skipped" | "partial";
};

type Phase = "overview" | "guided" | "complete";

function blockSeconds(b: Block): number {
  if (b.duration_sec && b.duration_sec > 0) return b.duration_sec;
  if (b.duration_min && b.duration_min > 0) return b.duration_min * 60;
  return 45;
}

function fmtMMSS(sec: number): string {
  const m = Math.max(0, Math.floor(sec / 60));
  const s = Math.max(0, sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** Family → nice label for the aviation-context pill. */
function familyLabel(family: string): string {
  switch ((family || "").toLowerCase()) {
    case "mobility":       return "Mobility";
    case "activation":     return "Activation";
    case "recovery":       return "Recovery";
    case "reset":          return "Reset";
    case "walk":           return "Walk";
    case "movement_break": return "Movement break";
    default:               return "Flight Support";
  }
}

export function FlightSupportProtocolModal({
  visible, intervention, onClose, onCompleted,
}: {
  visible: boolean;
  intervention: Intervention | null;
  onClose: () => void;
  onCompleted?: () => void;
}) {
  const [phase, setPhase] = useState<Phase>("overview");
  const [currentIdx, setCurrentIdx] = useState(0);
  const [remaining, setRemaining] = useState(0);
  const [saving, setSaving] = useState(false);
  const timerRef = useRef<any>(null);

  const blocks: Block[] = useMemo(
    () => (intervention?.blocks || []).filter(Boolean),
    [intervention]
  );
  const total = blocks.length;

  // Reset phase whenever a new intervention is opened.
  useEffect(() => {
    if (visible) {
      setPhase("overview");
      setCurrentIdx(0);
      setRemaining(0);
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    }
  }, [visible, intervention?.id]);

  /* ---------------------------- guided timer ------------------------------ */
  // Use a ref for `advance` so `tickDown` can call it without becoming a
  // useCallback dep (would create a circular reference).
  const advanceRef = useRef<() => void>(() => {});

  const tickDown = useCallback(() => {
    setRemaining((r) => {
      if (r <= 1) {
        if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
        setTimeout(() => advanceRef.current(), 200);
        return 0;
      }
      return r - 1;
    });
  }, []);

  const startCurrent = useCallback((idx: number) => {
    const b = blocks[idx];
    if (!b) return;
    setRemaining(blockSeconds(b));
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(tickDown, 1000);
  }, [blocks, tickDown]);

  const advance = useCallback(() => {
    setCurrentIdx((i) => {
      const next = i + 1;
      if (next >= total) {
        if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
        setPhase("complete");
        try { hapticSuccess(); } catch { /* ignore */ }
        return i;
      }
      startCurrent(next);
      return next;
    });
  }, [total, startCurrent]);

  // Keep the ref in sync so tickDown's callback always sees the latest advance.
  useEffect(() => { advanceRef.current = advance; }, [advance]);

  const skipCurrent = useCallback(() => {
    advance();
  }, [advance]);

  // Stop the timer if modal is dismissed mid-run.
  useEffect(() => {
    if (!visible && timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, [visible]);

  // On phase enter "guided", kick off the first block.
  useEffect(() => {
    if (phase === "guided" && total > 0) {
      startCurrent(0);
      setCurrentIdx(0);
    }
    return () => {
      if (phase !== "guided" && timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  /* --------------------------- completion post ---------------------------- */
  const markCompleted = useCallback(async () => {
    if (!intervention) return;
    setSaving(true);
    try {
      await api("/client/flight-support/complete", {
        method: "POST",
        body: {
          intervention_id: intervention.id,
          status: "completed",
          protocol_key: intervention.protocol_key,
          duration_min: intervention.duration_min,
          date: intervention.date,
        },
      });
      if (onCompleted) onCompleted();
    } catch (e: any) {
      Alert.alert("Couldn't save", String(e?.message || e));
    } finally {
      setSaving(false);
    }
  }, [intervention, onCompleted]);

  if (!intervention) return null;

  const currentBlock = blocks[currentIdx];

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="fullScreen"
      onRequestClose={onClose}
    >
      <SafeAreaView style={s.root} edges={["top", "bottom"]}>
        {phase === "overview" ? (
          <OverviewPhase
            intervention={intervention}
            blocks={blocks}
            onClose={onClose}
            onStart={() => setPhase("guided")}
          />
        ) : phase === "guided" && currentBlock ? (
          <GuidedPhase
            intervention={intervention}
            block={currentBlock}
            index={currentIdx}
            total={total}
            remaining={remaining}
            onSkip={skipCurrent}
            onNext={advance}
            onExit={onClose}
          />
        ) : (
          <CompletePhase
            intervention={intervention}
            saving={saving}
            onDone={onClose}
            onAutoRecord={markCompleted}
          />
        )}
      </SafeAreaView>
    </Modal>
  );
}

/* ============================== overview ================================== */
function OverviewPhase({
  intervention, blocks, onClose, onStart,
}: {
  intervention: Intervention;
  blocks: Block[];
  onClose: () => void;
  onStart: () => void;
}) {
  return (
    <>
      <View style={s.header}>
        <Pressable onPress={onClose} hitSlop={12} testID="fs-protocol-close">
          <Ionicons name="chevron-back" size={26} color={theme.color.text} />
        </Pressable>
        <View style={s.brandRow}>
          <Ionicons name="airplane-outline" size={12} color={theme.color.brand} />
          <Text style={s.brandTag}>FLIGHT SUPPORT</Text>
        </View>
        <View style={{ width: 26 }} />
      </View>

      <ScrollView contentContainerStyle={s.body} showsVerticalScrollIndicator={false}>
        <Text style={s.title}>{intervention.title}</Text>
        <Text style={s.subtitle}>
          {intervention.duration_min} min · {familyLabel(intervention.family)}
        </Text>
        {intervention.trigger_reason ? (
          <Text style={s.description}>{intervention.trigger_reason}</Text>
        ) : null}

        <View style={s.notCountedPill}>
          <Ionicons name="information-circle-outline" size={12} color={theme.color.textMuted} />
          <Text style={s.notCountedText}>Not counted as training</Text>
        </View>

        <View style={s.movementListHeader}>
          <Text style={s.sectionLabel}>MOVEMENTS</Text>
          <Text style={s.sectionCount}>{blocks.length}</Text>
        </View>

        {blocks.map((b, i) => (
          <View key={i} style={s.moveRow} testID={`fs-move-row-${i}`}>
            <View style={s.moveNum}>
              <Text style={s.moveNumText}>{i + 1}</Text>
            </View>
            <View style={s.moveThumb}>
              <ExerciseThumbnail
                name={b.name}
                testIDPrefix={`fs-thumb-${i}`}
                showVideoBadge={true}
              />
            </View>
            <View style={s.moveTextWrap}>
              <Text style={s.moveName} numberOfLines={2}>{b.name}</Text>
              <Text style={s.moveDur}>{fmtMMSS(blockSeconds(b))}</Text>
              {b.cue ? (
                <Text style={s.moveCue} numberOfLines={2}>{b.cue}</Text>
              ) : null}
            </View>
          </View>
        ))}

        <View style={{ height: 24 }} />
      </ScrollView>

      <View style={s.footerBar}>
        <Pressable
          onPress={onStart}
          style={s.startBtn}
          testID="fs-start-btn"
        >
          <Ionicons name="play" size={16} color="#fff" />
          <Text style={s.startBtnText}>START FLIGHT SUPPORT</Text>
        </Pressable>
      </View>
    </>
  );
}

/* ============================== guided ==================================== */
function GuidedPhase({
  intervention, block, index, total, remaining, onSkip, onNext, onExit,
}: {
  intervention: Intervention;
  block: Block;
  index: number;
  total: number;
  remaining: number;
  onSkip: () => void;
  onNext: () => void;
  onExit: () => void;
}) {
  return (
    <>
      <View style={s.header}>
        <Pressable onPress={onExit} hitSlop={12} testID="fs-guided-close">
          <Ionicons name="close" size={26} color={theme.color.text} />
        </Pressable>
        <View style={s.brandRow}>
          <Ionicons name="airplane-outline" size={12} color={theme.color.brand} />
          <Text style={s.brandTag}>FLIGHT SUPPORT</Text>
        </View>
        <Text style={s.progress}>{index + 1} / {total}</Text>
      </View>

      <View style={s.progressBar}>
        <View style={[s.progressFill, { width: `${((index + 1) / total) * 100}%` }]} />
      </View>

      <View style={s.guidedBody}>
        <Text style={s.moveEyebrow}>{intervention.title.toUpperCase()}</Text>
        <Text style={s.moveTitleBig}>{block.name}</Text>

        {/* Iter 158 — single hero image + coaching points + narration.
            Replaces the 3-frame carousel. The child component owns the
            /exercise-content/frames fetch, image resolution and speak()
            side-effects; it also handles stopping narration when `block`
            changes so we never talk over the next exercise. */}
        <FlightBlockDetail block={block} />

        <Text style={s.timerBig} testID="fs-timer">{fmtMMSS(remaining)}</Text>
      </View>

      <View style={s.footerBar}>
        <Pressable
          onPress={onSkip}
          style={[s.secondaryBtn]}
          testID="fs-skip-move"
        >
          <Ionicons name="play-skip-forward-outline" size={16} color={theme.color.textMuted} />
          <Text style={s.secondaryBtnText}>SKIP</Text>
        </Pressable>
        <Pressable
          onPress={onNext}
          style={[s.startBtn, { flex: 2 }]}
          testID="fs-next-move"
        >
          <Text style={s.startBtnText}>
            {index + 1 >= total ? "FINISH" : "NEXT"}
          </Text>
          <Ionicons name="chevron-forward" size={16} color="#fff" />
        </Pressable>
      </View>
    </>
  );
}

/* ============================== complete ================================== */
function CompletePhase({
  intervention, saving, onDone, onAutoRecord,
}: {
  intervention: Intervention;
  saving: boolean;
  onDone: () => void;
  onAutoRecord: () => void;
}) {
  // Auto-record completion when this phase mounts — Flight Support is
  // considered complete the moment the pilot finishes the last movement;
  // RETURN TO HOME is only a dismissal.
  useEffect(() => {
    onAutoRecord();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <View style={s.completeWrap}>
      <View style={s.completeIcon}>
        <Ionicons name="checkmark" size={56} color="#fff" />
      </View>
      <Text style={s.completeTitle}>Flight Support Complete</Text>
      <Text style={s.completeSub}>You&apos;re ready to go.</Text>
      <Text style={s.completeMeta}>
        {intervention.title} · {intervention.duration_min} min
      </Text>
      <View style={{ flex: 1 }} />
      <View style={s.footerBar}>
        <Pressable
          onPress={onDone}
          style={s.startBtn}
          testID="fs-complete-done"
          disabled={saving}
        >
          {saving ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <>
              <Text style={s.startBtnText}>RETURN TO HOME</Text>
              <Ionicons name="checkmark" size={16} color="#fff" />
            </>
          )}
        </Pressable>
      </View>
    </View>
  );
}

/* ============================== block detail (Iter 158) =============== */
/**
 * Renders a single primary image, an inline "Play explanation" narration
 * button, and a bulleted Coaching Points section for the current block.
 *
 * The frames endpoint is queried by exercise NAME (case-insensitive path
 * lookup on the backend). We prefer the response's `primary_image` slot;
 * fall back to the first "start" frame if the exercise doc doesn't have
 * `primary_image_id` yet (auto-media-gen is asynchronous).
 *
 * Narration is auto-stopped whenever `block` changes so the timer moving
 * to the next exercise never talks over the previous one.
 */
type FramesResp = {
  primary_image?: { image_id: string; url: string } | null;
  frames?: { slot: string; url: string; image_id?: string }[];
  coaching_points?: string[];
};

function FlightBlockDetail({ block }: { block: Block }) {
  const [data, setData] = useState<FramesResp | null>(null);
  const [loading, setLoading] = useState(true);
  const [imgUrl, setImgUrl] = useState<string | null>(null);
  const [speaking, setSpeaking] = useState(false);

  // Rebuild coaching-points list: server-supplied or fallback to the block's
  // own `cue` (split on periods/semicolons/newlines for a light bullet list).
  const bullets: string[] = useMemo(() => {
    if (data?.coaching_points && data.coaching_points.length > 0) return data.coaching_points;
    const raw = (block.cue || "").trim();
    if (!raw) return [];
    return raw
      .split(/[\.;\n]+/)
      .map((s) => s.trim())
      .filter(Boolean);
  }, [data?.coaching_points, block.cue]);

  useEffect(() => {
    let cancel = false;
    setLoading(true);
    setData(null);
    setImgUrl(null);
    (async () => {
      try {
        const r = await api<FramesResp>(
          `/exercise-content/frames/${encodeURIComponent(block.name)}?persona=pilot`,
        );
        if (cancel) return;
        setData(r);
        const rel =
          r?.primary_image?.url ||
          (r?.frames || []).find((f) => f.slot === "start")?.url ||
          null;
        if (rel) {
          // frames.url is `/api/exercise-content/images/{id}/stream` — turn
          // into an absolute URL for the streaming binary route. Token is
          // appended so the fetch is authorised.
          const token = await getToken();
          const base = String(API_BASE || "").replace(/\/api\/?$/, "");
          setImgUrl(
            `${base}${rel.startsWith("/") ? "" : "/"}${rel}${token ? `?token=${encodeURIComponent(token)}` : ""}`,
          );
        }
      } catch { /* silent — placeholder tile stays */ } finally {
        if (!cancel) setLoading(false);
      }
    })();
    return () => { cancel = true; };
  }, [block.name]);

  // Auto-stop narration on block change AND on unmount so we never talk
  // over the next exercise or after the modal closes.
  useEffect(() => {
    return () => {
      try { stopNarration(); } catch { /* noop */ }
      setSpeaking(false);
    };
  }, [block.name]);

  const onPlayExplanation = async () => {
    const text = bullets.length ? bullets.join(". ") : (block.cue || block.name);
    if (!text) return;
    if (speaking) {
      stopNarration();
      setSpeaking(false);
      return;
    }
    setSpeaking(true);
    try {
      await speak(text, { dedupeKey: `flight-support:${block.name}` });
    } finally {
      // speak() resolves once queued — we can't easily hook the end event
      // across platforms, so we clear the flag after a short delay
      // proportional to text length (~140 ms/word feels natural).
      const wc = text.split(/\s+/).length;
      setTimeout(() => setSpeaking(false), Math.min(20_000, 400 + wc * 140));
    }
  };

  return (
    <View style={s.blockDetailWrap}>
      <View style={s.heroImageWrap}>
        {loading ? (
          <ActivityIndicator color={theme.color.brand} />
        ) : imgUrl ? (
          <ExpoImage
            source={{ uri: imgUrl }}
            style={s.heroImage}
            contentFit="cover"
            transition={200}
            accessibilityLabel={`${block.name} demonstration`}
          />
        ) : (
          <Ionicons name="fitness-outline" size={44} color={theme.color.textDim} />
        )}
      </View>

      <Pressable
        onPress={onPlayExplanation}
        style={[s.playExplainBtn, speaking && s.playExplainBtnActive]}
        testID="fs-play-explanation"
        accessibilityRole="button"
        accessibilityLabel={speaking ? "Stop explanation" : "Play explanation"}
      >
        <Ionicons
          name={speaking ? "stop-circle" : "volume-high"}
          size={16}
          color={speaking ? "#fff" : theme.color.brand}
        />
        <Text style={[s.playExplainT, speaking && { color: "#fff" }]}>
          {speaking ? "STOP" : "PLAY EXPLANATION"}
        </Text>
      </Pressable>

      {bullets.length > 0 && (
        <View style={s.coachingPointsWrap}>
          <Text style={s.coachingPointsTitle}>COACHING POINTS</Text>
          {bullets.map((b, i) => (
            <View key={i} style={s.bulletRow}>
              <View style={s.bulletDot} />
              <Text style={s.bulletText}>{b}</Text>
            </View>
          ))}
        </View>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 16, paddingVertical: 10,
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  brandRow: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: theme.color.brand + "18",
    borderColor: theme.color.brand,
    borderWidth: 1,
    paddingHorizontal: 10, paddingVertical: 4,
    borderRadius: 12,
  },
  brandTag: {
    color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.8,
  },
  progress: {
    color: theme.color.textMuted, fontSize: 12, fontWeight: "700", letterSpacing: 1,
    minWidth: 26, textAlign: "right",
  },
  progressBar: {
    height: 3, width: "100%", backgroundColor: theme.color.border,
  },
  progressFill: {
    height: "100%", backgroundColor: theme.color.brand,
  },
  body: {
    paddingHorizontal: 20, paddingTop: 18, paddingBottom: 20,
  },
  title: {
    color: theme.color.text, fontSize: 26, fontWeight: "900", lineHeight: 30,
  },
  subtitle: {
    color: theme.color.brand, fontSize: 13, fontWeight: "700",
    letterSpacing: 1.2, marginTop: 6, textTransform: "uppercase",
  },
  description: {
    color: theme.color.textMuted, fontSize: 14, lineHeight: 20, marginTop: 12,
  },
  notCountedPill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    alignSelf: "flex-start",
    backgroundColor: theme.color.surface2,
    borderColor: theme.color.border, borderWidth: 1,
    paddingHorizontal: 8, paddingVertical: 3,
    borderRadius: 6, marginTop: 12,
  },
  notCountedText: {
    color: theme.color.textMuted, fontSize: 11, fontWeight: "600",
  },
  movementListHeader: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    marginTop: 28, marginBottom: 12,
    paddingBottom: 8, borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  sectionLabel: {
    color: theme.color.text, fontSize: 11, fontWeight: "800", letterSpacing: 1.6,
  },
  sectionCount: {
    color: theme.color.textMuted, fontSize: 12, fontWeight: "700",
  },
  moveRow: {
    flexDirection: "row", gap: 12,
    paddingVertical: 12,
    borderBottomWidth: 1, borderBottomColor: theme.color.border + "77",
  },
  moveNum: {
    width: 26, height: 26, borderRadius: 13,
    borderWidth: 1, borderColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
    marginTop: 6,
  },
  moveNumText: {
    color: theme.color.brand, fontSize: 12, fontWeight: "800",
  },
  moveThumb: {
    width: 72, height: 72, borderRadius: 8, overflow: "hidden",
    backgroundColor: theme.color.surface2,
  },
  moveTextWrap: {
    flex: 1, justifyContent: "center", gap: 3,
  },
  moveName: {
    color: theme.color.text, fontSize: 15, fontWeight: "700",
  },
  moveDur: {
    color: theme.color.brand, fontSize: 13, fontWeight: "800",
    letterSpacing: 0.5,
  },
  moveCue: {
    color: theme.color.textMuted, fontSize: 12, lineHeight: 16,
    marginTop: 1,
  },
  footerBar: {
    flexDirection: "row",
    padding: 16, gap: 10,
    borderTopWidth: 1, borderTopColor: theme.color.border,
    backgroundColor: theme.color.surface,
  },
  startBtn: {
    flex: 1, flexDirection: "row",
    alignItems: "center", justifyContent: "center", gap: 8,
    paddingVertical: 16, borderRadius: 12,
    backgroundColor: theme.color.brand,
  },
  startBtnText: {
    color: "#fff", fontSize: 13, fontWeight: "900", letterSpacing: 1.6,
  },
  secondaryBtn: {
    flex: 1, flexDirection: "row",
    alignItems: "center", justifyContent: "center", gap: 6,
    paddingVertical: 16, borderRadius: 12,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
  },
  secondaryBtnText: {
    color: theme.color.textMuted, fontSize: 12, fontWeight: "800", letterSpacing: 1.4,
  },

  // Guided-phase big display
  guidedBody: {
    flex: 1, paddingHorizontal: 20, paddingTop: 20, alignItems: "center",
  },
  moveEyebrow: {
    color: theme.color.textMuted, fontSize: 11, fontWeight: "700",
    letterSpacing: 1.8, marginBottom: 8,
  },
  moveTitleBig: {
    color: theme.color.text, fontSize: 26, fontWeight: "900",
    textAlign: "center", lineHeight: 30, marginBottom: 8,
  },
  moveCueBig: {
    color: theme.color.textMuted, fontSize: 14, lineHeight: 20,
    textAlign: "center", marginBottom: 20, paddingHorizontal: 10,
  },
  guidedThumbFrame: {
    width: 220, height: 220, borderRadius: 16, overflow: "hidden",
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
    marginBottom: 24,
  },
  timerBig: {
    color: theme.color.text, fontSize: 56, fontWeight: "900",
    letterSpacing: 1, fontVariant: ["tabular-nums"],
  },

  // Complete phase
  completeWrap: {
    flex: 1, alignItems: "center", paddingTop: 80, paddingHorizontal: 20,
  },
  completeIcon: {
    width: 100, height: 100, borderRadius: 50,
    backgroundColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
    marginBottom: 24,
  },
  completeTitle: {
    color: theme.color.text, fontSize: 26, fontWeight: "900",
    textAlign: "center",
  },
  completeSub: {
    color: theme.color.textMuted, fontSize: 15, marginTop: 8,
    textAlign: "center",
  },
  completeMeta: {
    color: theme.color.brand, fontSize: 12, fontWeight: "700",
    letterSpacing: 1.2, marginTop: 20,
    textTransform: "uppercase",
  },

  // Iter 158 — single hero + coaching-points + narration button.
  blockDetailWrap: {
    alignItems: "center",
    marginBottom: 24,
    gap: 14,
  },
  heroImageWrap: {
    width: 260, height: 260,
    borderRadius: 16,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
    alignItems: "center", justifyContent: "center",
    overflow: "hidden",
  },
  heroImage: { width: "100%", height: "100%" },
  playExplainBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    paddingHorizontal: 16, paddingVertical: 10,
    borderRadius: 999,
    backgroundColor: theme.color.brandTint,
    borderWidth: 1, borderColor: theme.color.brand,
  },
  playExplainBtnActive: {
    backgroundColor: theme.color.brand,
    borderColor: theme.color.brand,
  },
  playExplainT: {
    color: theme.color.brand,
    fontSize: 11, fontWeight: "900", letterSpacing: 1.5,
  },
  coachingPointsWrap: {
    alignSelf: "stretch",
    paddingHorizontal: 4,
    marginTop: 6,
  },
  coachingPointsTitle: {
    color: theme.color.brand,
    fontSize: 11, fontWeight: "900", letterSpacing: 2,
    marginBottom: 8,
  },
  bulletRow: {
    flexDirection: "row",
    gap: 10,
    marginBottom: 8,
    alignItems: "flex-start",
  },
  bulletDot: {
    width: 6, height: 6, borderRadius: 3,
    backgroundColor: theme.color.brand,
    marginTop: 8,
  },
  bulletText: {
    color: theme.color.text,
    fontSize: 14,
    lineHeight: 20,
    flex: 1,
  },
});

export default FlightSupportProtocolModal;
