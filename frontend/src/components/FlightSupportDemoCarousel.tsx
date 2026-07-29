/**
 * FlightSupportDemoCarousel — Iter 128
 *
 * 3-frame auto-swiping visual demonstration for a Flight Support movement.
 *
 * Behaviour
 *   START → MID → END → loop.
 *   Auto-advances every ~2800 ms.
 *   Manual left/right swipe (via FlatList paging).
 *   Manual tap on a dot jumps to that frame.
 *   Manual interaction pauses auto-advance for 5s, then resumes.
 *
 * Frame source
 *   GET /exercise-content/frames/{exercise_id}?persona=pilot
 *   Returns an ordered array of {slot, url, persona} with graceful degradation:
 *     - 3 frames → full carousel
 *     - 2 frames → carousel with 2 dots
 *     - 1 frame  → single static image
 *     - 0 frames → placeholder tile with the exercise name
 *
 * Performance
 *   Only the frames for the CURRENT exercise are fetched. `Image` component
 *   caches images at the OS/asset level. No preloading of Louis/Female
 *   sibling personas.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, Pressable, ActivityIndicator,
  NativeScrollEvent, NativeSyntheticEvent,
} from "react-native";
import { Image } from "expo-image";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";
import { api, API_BASE } from "@/src/lib/api";

const AUTO_ADVANCE_MS = 2800;
const RESUME_AFTER_MANUAL_MS = 5000;

type Frame = { slot: "start" | "mid" | "end"; url: string; persona: string; image_id: string };
type ResolverResp = {
  exercise_id: string;
  name: string;
  frames: Frame[];
  missing_slots: string[];
  preferred_persona_missing: string[];
  coverage: Record<string, string[]>;
};

export function FlightSupportDemoCarousel({
  exerciseId, exerciseName, sizePx = 220, persona = "pilot",
}: {
  exerciseId?: string;
  exerciseName: string;
  sizePx?: number;
  persona?: "pilot" | "louis" | "female";
}) {
  const [data, setData] = useState<ResolverResp | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeIdx, setActiveIdx] = useState(0);
  const [manualPauseUntil, setManualPauseUntil] = useState(0);
  const listRef = useRef<FlatList<Frame>>(null);
  const autoTimer = useRef<any>(null);

  // Fetch the resolved 3-frame set for this exercise.
  useEffect(() => {
    let cancelled = false;
    if (!exerciseId) { setLoading(false); return; }
    (async () => {
      setLoading(true);
      try {
        const resp = await api<ResolverResp>(
          `/exercise-content/frames/${exerciseId}?persona=${persona}`
        );
        if (!cancelled) setData(resp);
      } catch {
        if (!cancelled) setData(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [exerciseId, persona]);

  // Reset frame index whenever the exercise changes (e.g. between movements)
  useEffect(() => { setActiveIdx(0); }, [exerciseId]);

  // Auto-advance loop
  useEffect(() => {
    if (!data?.frames?.length || data.frames.length < 2) return;
    if (autoTimer.current) clearInterval(autoTimer.current);
    autoTimer.current = setInterval(() => {
      if (Date.now() < manualPauseUntil) return;
      setActiveIdx((i) => {
        const next = (i + 1) % (data.frames.length);
        try {
          listRef.current?.scrollToIndex({ index: next, animated: true });
        } catch { /* ignore */ }
        return next;
      });
    }, AUTO_ADVANCE_MS);
    return () => {
      if (autoTimer.current) { clearInterval(autoTimer.current); autoTimer.current = null; }
    };
  }, [data?.frames?.length, manualPauseUntil]);

  const onMomentumEnd = useCallback((e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const w = e.nativeEvent.layoutMeasurement.width || sizePx;
    const idx = Math.round(e.nativeEvent.contentOffset.x / Math.max(1, w));
    setActiveIdx(idx);
  }, [sizePx]);

  const onTouchStart = useCallback(() => {
    setManualPauseUntil(Date.now() + RESUME_AFTER_MANUAL_MS);
  }, []);

  const jumpTo = useCallback((i: number) => {
    setManualPauseUntil(Date.now() + RESUME_AFTER_MANUAL_MS);
    setActiveIdx(i);
    try { listRef.current?.scrollToIndex({ index: i, animated: true }); } catch { /* ignore */ }
  }, []);

  const frames: Frame[] = useMemo(() => data?.frames ?? [], [data]);

  // ── Loading state ────────────────────────────────────────────────────────
  if (loading) {
    return (
      <View style={[s.frame, { width: sizePx, height: sizePx }]}>
        <ActivityIndicator color={theme.color.brand} />
      </View>
    );
  }

  // ── Zero-frame fallback ──────────────────────────────────────────────────
  if (frames.length === 0) {
    return (
      <View style={[s.frame, { width: sizePx, height: sizePx }]}>
        <Ionicons name="body-outline" size={48} color={theme.color.textMuted} />
        <Text style={s.placeholderName} numberOfLines={2}>{exerciseName}</Text>
        <Text style={s.placeholderHint}>Demo images coming soon</Text>
      </View>
    );
  }

  // ── Carousel ─────────────────────────────────────────────────────────────
  return (
    <View style={{ alignItems: "center" }}>
      <View style={[s.frame, { width: sizePx, height: sizePx, padding: 0 }]}
            onTouchStart={onTouchStart}>
        <FlatList
          ref={listRef}
          data={frames}
          horizontal
          pagingEnabled
          showsHorizontalScrollIndicator={false}
          keyExtractor={(f, i) => `${f.image_id}-${i}`}
          onMomentumScrollEnd={onMomentumEnd}
          getItemLayout={(_, i) => ({ length: sizePx, offset: sizePx * i, index: i })}
          renderItem={({ item }) => (
            <View style={{ width: sizePx, height: sizePx }}>
              <Image
                source={{ uri: `${API_BASE}${item.url}` }}
                style={{ width: sizePx, height: sizePx }}
                contentFit="cover"
                transition={200}
                cachePolicy="memory-disk"
              />
              <View style={s.slotBadge} pointerEvents="none">
                <Text style={s.slotBadgeText}>{item.slot.toUpperCase()}</Text>
              </View>
            </View>
          )}
        />
      </View>

      {/* Dot indicators */}
      {frames.length > 1 ? (
        <View style={s.dotsRow}>
          {frames.map((_, i) => (
            <Pressable key={i} onPress={() => jumpTo(i)} hitSlop={8}>
              <View style={[s.dot, i === activeIdx ? s.dotActive : null]} />
            </Pressable>
          ))}
        </View>
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  frame: {
    borderRadius: 16, overflow: "hidden",
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
    alignItems: "center", justifyContent: "center",
  },
  slotBadge: {
    position: "absolute", top: 10, left: 10,
    backgroundColor: "rgba(0,0,0,0.55)",
    paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6,
  },
  slotBadgeText: {
    color: "#fff", fontSize: 10, fontWeight: "800", letterSpacing: 1.2,
  },
  placeholderName: {
    color: theme.color.text, fontSize: 13, fontWeight: "800",
    textAlign: "center", marginTop: 10, paddingHorizontal: 14,
  },
  placeholderHint: {
    color: theme.color.textMuted, fontSize: 10, marginTop: 4,
  },
  dotsRow: {
    flexDirection: "row", gap: 6, marginTop: 10,
  },
  dot: {
    width: 6, height: 6, borderRadius: 3,
    backgroundColor: theme.color.border,
  },
  dotActive: {
    backgroundColor: theme.color.brand,
    width: 18,
  },
});

export default FlightSupportDemoCarousel;
