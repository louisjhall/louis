/**
 * WorkoutMediaCarousel — swipeable image carousel for the workout player.
 *
 * Pulls approved media from the unified V2 Exercise Library (source of
 * truth). Resolves the exercise by name via /exercise-content?q=<name>,
 * then displays every filled slot in canonical order (primary → start →
 * bottom / apex / loaded / stretch → top → end / finish → mid).
 *
 * If the V2 record has NO approved media, falls back to the dark CrewFit
 * placeholder. Video URLs and drafts are deliberately ignored here — this
 * component is image-only.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Dimensions, ActivityIndicator,
  NativeScrollEvent, NativeSyntheticEvent,
} from "react-native";
import { Image } from "expo-image";
import { Ionicons } from "@expo/vector-icons";
import { api, API_BASE, getToken } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

const SLOT_ORDER = ["primary", "start", "bottom", "apex", "loaded", "stretch", "top", "end", "finish", "mid"] as const;
const SLOT_LABELS: Record<string, string> = {
  primary: "PRIMARY", start: "START", bottom: "BOTTOM", apex: "APEX",
  loaded: "LOADED", stretch: "STRETCH", top: "TOP", end: "END",
  finish: "FINISH", mid: "MID",
};

// Small resolver cache so multiple carousel mounts on the same workout
// don't hammer the exercise endpoint.
const _resolveCache = new Map<string, ResolvedMedia | null>();

type Slide = { slot: string; label: string; url: string };
type ResolvedMedia = {
  hasApprovedMedia: boolean;
  slides: Slide[];
  approvalStatus?: string | null;
};

async function resolveMediaForName(name: string): Promise<ResolvedMedia | null> {
  const key = name.trim().toLowerCase();
  if (!key) return null;
  if (_resolveCache.has(key)) return _resolveCache.get(key)!;

  try {
    const r = await api<{ exercises: any[] }>(
      `/exercise-content?q=${encodeURIComponent(name)}&limit=1`,
    );
    const ex = r?.exercises?.[0];
    if (!ex) { _resolveCache.set(key, null); return null; }

    // Client safety: only render media when the exercise is approved and
    // its image approval status is 'Live' or 'Approved'. Anything drafty
    // → falls through to placeholder so drafts never leak.
    const approved =
      ex.approval_status === "approved" ||
      ex.status === "Live" ||
      ex.approved_image_status === "Approved" ||
      ex.approved_image_status === "Live";

    const token = await getToken();
    const legacy: Record<string, string | undefined> = {
      primary: ex.primary_image_id,
      start:   ex.demo_start_image_id,
      end:     ex.demo_end_image_id,
    };
    const dyn = (ex.demo_slots || {}) as Record<string, string | undefined>;

    const slides: Slide[] = [];
    const seen = new Set<string>();
    for (const slot of SLOT_ORDER) {
      const imgId = dyn[slot] || legacy[slot];
      if (!imgId || seen.has(imgId)) continue;   // dedupe if the same ID mirrors into two slots
      seen.add(imgId);
      const url = `${API_BASE}/exercise-content/images/${imgId}/stream${
        token ? `?token=${encodeURIComponent(token)}` : ""
      }`;
      slides.push({ slot, label: SLOT_LABELS[slot] || slot.toUpperCase(), url });
    }

    // Slide-level approval isn't tracked yet — we key on the exercise's
    // overall approval instead. If the exercise isn't approved, blank out
    // the slides so the fallback fires.
    const resolved: ResolvedMedia = {
      hasApprovedMedia: approved && slides.length > 0,
      slides: approved ? slides : [],
      approvalStatus: ex.approval_status || ex.status || null,
    };
    _resolveCache.set(key, resolved);
    return resolved;
  } catch {
    _resolveCache.set(key, null);
    return null;
  }
}

export function WorkoutMediaCarousel({
  exerciseName,
  height = 260,
  showCoachDraftBadge = false,
  autoScroll = false,
  autoScrollIntervalMs = 4000,
  contentFit = "cover",
}: {
  exerciseName: string;
  height?: number;
  /** When true, coach-preview mode surfaces a small "DRAFT" warning if the
   * exercise isn't yet approved. Client mode leaves this off. */
  showCoachDraftBadge?: boolean;
  /** Iter 94t (Phase 2) — When true, cycle through slides automatically so
   * the client can follow along hands-free during timed exercises. The
   * auto-scroll pauses if the client manually swipes and resumes after 10s
   * idle. */
  autoScroll?: boolean;
  /** Interval in ms between auto-advances. 3–5s for standard exercises,
   * 5–7s for mobility / stretch. */
  autoScrollIntervalMs?: number;
  /** How images fill the frame. Default "cover" (workout index / play).
   * Guided flow passes "contain" so the whole exercise is visible without
   * head / feet cropping on portrait phone screens. */
  contentFit?: "cover" | "contain";
}) {
  const [media, setMedia] = useState<ResolvedMedia | null | undefined>(undefined);
  const [page, setPage] = useState(0);
  const [autoPaused, setAutoPaused] = useState(false);
  // Iter 94t — Track slides whose image failed to load (expo-image onError).
  // Any slot key in this set is filtered out of the render so the client
  // never sees a broken/empty frame; if every slide fails we fall through
  // to the placeholder.
  const [brokenSlots, setBrokenSlots] = useState<Set<string>>(new Set());
  const width = Dimensions.get("window").width - 32;
  const scrollRef = useRef<ScrollView | null>(null);
  const resumeTimerRef = useRef<any>(null);

  useEffect(() => {
    let cancel = false;
    // Reset broken tracking whenever the exercise changes so a new
    // exercise gets a fair chance to load its media.
    setBrokenSlots(new Set());
    setPage(0);
    (async () => {
      const r = await resolveMediaForName(exerciseName);
      if (!cancel) setMedia(r);
    })();
    return () => { cancel = true; };
  }, [exerciseName]);

  const markBroken = (slot: string) => {
    setBrokenSlots((prev) => {
      if (prev.has(slot)) return prev;
      const next = new Set(prev);
      next.add(slot);
      return next;
    });
  };

  const allSlides = media?.slides || [];
  const slides = useMemo(
    () => allSlides.filter((s) => !brokenSlots.has(s.slot)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [media, brokenSlots],
  );

  // Keep the page index in-bounds when slides shrink due to load errors.
  useEffect(() => {
    if (page >= slides.length && slides.length > 0) {
      setPage(slides.length - 1);
      scrollRef.current?.scrollTo({ x: (slides.length - 1) * width, animated: false });
    }
  }, [slides.length, page, width]);

  // Iter 94t (Phase 2) — Auto-advance the carousel every N ms while enabled
  // and while the client hasn't recently swiped. Pauses when off-screen or
  // when there are fewer than two slides.
  useEffect(() => {
    if (!autoScroll || autoPaused) return;
    if (slides.length < 2) return;
    const id = setInterval(() => {
      setPage((prev) => {
        const next = (prev + 1) % slides.length;
        scrollRef.current?.scrollTo({ x: next * width, animated: true });
        return next;
      });
    }, Math.max(1500, autoScrollIntervalMs));
    return () => clearInterval(id);
  }, [autoScroll, autoPaused, slides.length, autoScrollIntervalMs, width]);

  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const p = Math.round(e.nativeEvent.contentOffset.x / width);
    if (p !== page) setPage(p);
  };

  // Iter 94t (Phase 2) — If the client swipes manually, pause auto-scroll
  // for 10s so we don't fight their finger, then resume.
  const onTouchStart = () => {
    if (!autoScroll) return;
    setAutoPaused(true);
    if (resumeTimerRef.current) clearTimeout(resumeTimerRef.current);
    resumeTimerRef.current = setTimeout(() => setAutoPaused(false), 10_000);
  };

  const draftPill = useMemo(() => {
    if (!showCoachDraftBadge || !media) return null;
    if (media.hasApprovedMedia) return null;
    return (
      <View style={styles.draftPill}>
        <Ionicons name="warning" size={10} color="#F59E0B" />
        <Text style={styles.draftPillT}>
          {slides.length > 0 ? "NOT APPROVED — CLIENTS SEE PLACEHOLDER" : "NO MEDIA — CLIENTS SEE PLACEHOLDER"}
        </Text>
      </View>
    );
  }, [showCoachDraftBadge, media, slides.length]);

  // Loading
  if (media === undefined) {
    return (
      <View style={[styles.wrap, { height }]}>
        <View style={styles.placeholder}>
          <ActivityIndicator color={theme.color.brand} />
        </View>
      </View>
    );
  }

  // Fallback — no approved media, or every slide failed to load.
  if (!media || !media.hasApprovedMedia || slides.length === 0) {
    return (
      <View style={[styles.wrap, { height }]}>
        <View style={styles.placeholder}>
          <Ionicons name="body" size={54} color={theme.color.brand} />
          <Text style={styles.placeholderT}>{exerciseName}</Text>
          <Text style={styles.placeholderS}>Follow the coaching cues below.</Text>
        </View>
        {draftPill}
      </View>
    );
  }

  // Single-image mode — no carousel affordance.
  if (slides.length === 1) {
    return (
      <View style={[styles.wrap, { height }]}>
        <Image
          source={{ uri: slides[0].url }}
          style={StyleSheet.absoluteFillObject}
          contentFit={contentFit}
          onError={() => markBroken(slides[0].slot)}
        />
        <View style={styles.labelPill}>
          <Text style={styles.labelPillT}>{slides[0].label}</Text>
        </View>
      </View>
    );
  }

  // Multi-image carousel with page indicators.
  return (
    <View style={[styles.wrap, { height }]}>
      <ScrollView
        ref={scrollRef}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        onMomentumScrollEnd={onScroll}
        onTouchStart={onTouchStart}
        style={StyleSheet.absoluteFillObject}
      >
        {slides.map((s) => (
          <View key={s.slot} style={{ width, height }}>
            <Image
              source={{ uri: s.url }}
              style={StyleSheet.absoluteFillObject}
              contentFit={contentFit}
              onError={() => markBroken(s.slot)}
            />
            <View style={styles.labelPill}>
              <Text style={styles.labelPillT}>{s.label}</Text>
            </View>
          </View>
        ))}
      </ScrollView>
      <View style={styles.dotsRow} pointerEvents="none">
        {slides.map((_, i) => (
          <View key={i} style={[styles.dot, i === page && styles.dotActive]} />
        ))}
      </View>
      {draftPill}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    width: "100%", borderRadius: 16, overflow: "hidden",
    backgroundColor: "#0A0A0B", borderWidth: 1, borderColor: theme.color.border,
    position: "relative",
  },
  placeholder: {
    flex: 1, alignItems: "center", justifyContent: "center",
    gap: 8, padding: 16,
  },
  placeholderT: { color: theme.color.text, fontWeight: "900", fontSize: 15, textAlign: "center" },
  placeholderS: { color: theme.color.textMuted, fontSize: 11, textAlign: "center" },
  labelPill: {
    position: "absolute", top: 12, left: 12,
    backgroundColor: "rgba(0,0,0,0.65)", borderRadius: 6,
    paddingHorizontal: 8, paddingVertical: 3,
    borderWidth: 1, borderColor: "rgba(255,255,255,0.15)",
  },
  labelPillT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.4 },
  dotsRow: {
    position: "absolute", bottom: 10, left: 0, right: 0,
    flexDirection: "row", justifyContent: "center", gap: 6,
  },
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: "rgba(255,255,255,0.35)" },
  dotActive: { width: 18, backgroundColor: theme.color.brand },
  draftPill: {
    position: "absolute", bottom: 12, left: 12, right: 12,
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "rgba(0,0,0,0.75)", borderRadius: 8,
    paddingHorizontal: 8, paddingVertical: 6,
    borderWidth: 1, borderColor: "rgba(245,158,11,0.5)",
  },
  draftPillT: { color: "#F59E0B", fontSize: 11, fontWeight: "800", letterSpacing: 0.8, flex: 1 },
});
