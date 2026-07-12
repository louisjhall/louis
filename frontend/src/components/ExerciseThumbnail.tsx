/**
 * ExerciseThumbnail — image-only preview for exercise cards in the workout
 * preview list. Explicitly does NOT mount a video player. Video is only
 * accessible after the user taps the thumbnail (opens a modal with the
 * existing `ExerciseVideoPlayer`) or drills into guided / play modes.
 *
 * Media fallback order:
 *   1. exercise.primary_image_id      (curated AI exercise image)
 *   2. exercise.demo_start_image_id   (before/after start frame)
 *   3. exercise.demo_end_image_id
 *   4. neutral dark placeholder       (branded dumbbell + name)
 */
import React, { useEffect, useState } from "react";
import {
  View, Text, Pressable, StyleSheet, Modal, ScrollView, ActivityIndicator, Platform,
} from "react-native";
import { Image } from "expo-image";
import { Ionicons } from "@expo/vector-icons";
import { api, API_BASE, getToken } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { ExerciseVideoPlayer } from "@/src/components/ExerciseVideoPlayer";

// Per-name resolver cache. The workout preview screen renders 5–10 cards
// so this saves an API call on every re-render + scrolls smoothly.
const _resolveCache = new Map<string, ResolvedExercise | null>();

type ResolvedExercise = {
  id: string;
  name: string;
  imageId: string | null;
  hasVideo: boolean;
  coachingPoints?: string[];
};

async function resolveExerciseByName(name: string): Promise<ResolvedExercise | null> {
  const key = name.trim().toLowerCase();
  if (!key) return null;
  if (_resolveCache.has(key)) return _resolveCache.get(key)!;
  try {
    const r = await api<{ exercises: any[] }>(
      `/exercise-content?q=${encodeURIComponent(name)}&limit=1`,
    );
    const ex = r?.exercises?.[0];
    if (!ex) { _resolveCache.set(key, null); return null; }
    const imageId: string | null =
      ex.primary_image_id || ex.demo_start_image_id || ex.demo_end_image_id || null;
    const hasVideo = !!(ex.primary_video_url || ex.content_status?.video);
    const resolved: ResolvedExercise = {
      id: ex.id,
      name: ex.exercise_name || name,
      imageId,
      hasVideo,
      coachingPoints: Array.isArray(ex.coaching_points) ? ex.coaching_points : [],
    };
    _resolveCache.set(key, resolved);
    return resolved;
  } catch {
    _resolveCache.set(key, null);
    return null;
  }
}

async function buildImageUrl(imageId: string): Promise<string> {
  const token = await getToken();
  return `${API_BASE}/exercise-content/images/${imageId}/stream${
    token ? `?token=${encodeURIComponent(token)}` : ""
  }`;
}

export function ExerciseThumbnail({
  name,
  testIDPrefix,
  showVideoBadge = true,
  onOpenDetail,
}: {
  name: string;
  testIDPrefix?: string;
  showVideoBadge?: boolean;
  /** Optional override. If omitted, tapping opens the built-in detail modal. */
  onOpenDetail?: () => void;
}) {
  const [resolved, setResolved] = useState<ResolvedExercise | null | undefined>(undefined);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);

  useEffect(() => {
    let cancel = false;
    (async () => {
      const r = await resolveExerciseByName(name);
      if (cancel) return;
      setResolved(r);
      if (r?.imageId) {
        const url = await buildImageUrl(r.imageId);
        if (!cancel) setImageUrl(url);
      }
    })();
    return () => { cancel = true; };
  }, [name]);

  const openDetail = () => {
    if (onOpenDetail) return onOpenDetail();
    setDetailOpen(true);
  };

  return (
    <>
      <Pressable
        style={styles.wrap}
        onPress={openDetail}
        testID={`${testIDPrefix || "ex-thumb"}`}
        accessibilityLabel={`View demonstration for ${name}`}
      >
        {imageUrl ? (
          <Image
            source={{ uri: imageUrl }}
            style={styles.img}
            contentFit="cover"
            transition={180}
            recyclingKey={imageUrl}
          />
        ) : (
          <View style={styles.placeholder}>
            {resolved === undefined ? (
              <ActivityIndicator color={theme.color.brand} size="small" />
            ) : (
              <>
                <Ionicons name="barbell-outline" size={26} color={theme.color.textDim} />
                <Text style={styles.placeholderText} numberOfLines={2}>{name}</Text>
              </>
            )}
          </View>
        )}

        {/* Subtle "video available" badge — no auto-embedded player */}
        {showVideoBadge && resolved?.hasVideo && (
          <View style={styles.badge} testID={`${testIDPrefix || "ex-thumb"}-video-badge`}>
            <Ionicons name="play" size={9} color="#fff" />
            <Text style={styles.badgeText}>VIDEO</Text>
          </View>
        )}
      </Pressable>

      <ExerciseDetailModal
        visible={detailOpen}
        onClose={() => setDetailOpen(false)}
        name={resolved?.name || name}
        coachingPoints={resolved?.coachingPoints}
        imageUrl={imageUrl}
        hasVideo={!!resolved?.hasVideo}
      />
    </>
  );
}

// ---------------------------------------------------------------------------
// Detail modal — image + coaching points + video (mounted lazily so the
// player is NEVER created for the preview list itself).
// ---------------------------------------------------------------------------

function ExerciseDetailModal({
  visible, onClose, name, coachingPoints, imageUrl, hasVideo,
}: {
  visible: boolean; onClose: () => void; name: string;
  coachingPoints?: string[]; imageUrl: string | null; hasVideo: boolean;
}) {
  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <View style={styles.modalRoot}>
        <View style={styles.modalHeader}>
          <Pressable onPress={onClose} hitSlop={12} testID="ex-detail-close">
            <Ionicons name="close" size={22} color={theme.color.text} />
          </Pressable>
          <Text style={styles.modalTitle} numberOfLines={2}>{name}</Text>
          <View style={{ width: 22 }} />
        </View>
        <ScrollView contentContainerStyle={{ paddingBottom: 40 }}>
          {imageUrl ? (
            <Image source={{ uri: imageUrl }} style={styles.heroImg} contentFit="cover" />
          ) : (
            <View style={[styles.heroImg, styles.placeholder]}>
              <Ionicons name="barbell-outline" size={40} color={theme.color.textDim} />
            </View>
          )}

          {(coachingPoints || []).length > 0 && (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>HOW TO DO IT</Text>
              {coachingPoints!.map((c, i) => (
                <View key={i} style={styles.pointRow}>
                  <Text style={styles.pointNum}>{i + 1}</Text>
                  <Text style={styles.pointText}>{c}</Text>
                </View>
              ))}
            </View>
          )}

          {hasVideo && (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>VIDEO</Text>
              <ExerciseVideoPlayer exerciseName={name} testIDPrefix="ex-detail-video" />
            </View>
          )}
          {!hasVideo && (
            <Text style={styles.noVideoNote}>
              No video available yet. Louis will add one soon.
            </Text>
          )}
        </ScrollView>
      </View>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------
const CARD_W = 100;
const CARD_H = 100;

const styles = StyleSheet.create({
  wrap: {
    width: CARD_W, height: CARD_H, borderRadius: 12, overflow: "hidden",
    backgroundColor: "#0A0A0B", borderWidth: 1, borderColor: theme.color.border,
  },
  img: { width: "100%", height: "100%" },
  placeholder: {
    width: "100%", height: "100%",
    backgroundColor: "#0A0A0B",
    alignItems: "center", justifyContent: "center", gap: 4,
    padding: 6,
  },
  placeholderText: { color: theme.color.textDim, fontSize: 9, textAlign: "center", fontWeight: "700" },
  badge: {
    position: "absolute", bottom: 6, right: 6,
    flexDirection: "row", alignItems: "center", gap: 3,
    backgroundColor: "rgba(0,0,0,0.75)",
    paddingHorizontal: 6, paddingVertical: 3, borderRadius: 6,
    borderWidth: 1, borderColor: "rgba(255,255,255,0.12)",
  },
  badgeText: { color: "#fff", fontSize: 8, fontWeight: "900", letterSpacing: 0.6 },

  // Modal
  modalRoot: { flex: 1, backgroundColor: theme.color.surface, paddingTop: Platform.OS === "ios" ? 44 : 20 },
  modalHeader: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 16, paddingVertical: 12,
    borderBottomWidth: 1, borderBottomColor: theme.color.divider,
  },
  modalTitle: { color: theme.color.text, fontSize: 16, fontWeight: "900", flex: 1, textAlign: "center", paddingHorizontal: 8 },
  heroImg: { width: "100%", height: 260, backgroundColor: "#0A0A0B" },
  section: { paddingHorizontal: 18, paddingTop: 20 },
  sectionTitle: {
    color: theme.color.textDim, fontSize: 11, fontWeight: "900",
    letterSpacing: 2, marginBottom: 10,
  },
  pointRow: { flexDirection: "row", gap: 10, marginBottom: 10 },
  pointNum: {
    width: 22, height: 22, borderRadius: 11, textAlign: "center",
    color: "#fff", backgroundColor: theme.color.brand, fontWeight: "900",
    fontSize: 12, lineHeight: 22, overflow: "hidden",
  },
  pointText: { color: theme.color.text, fontSize: 14, lineHeight: 20, flex: 1 },
  noVideoNote: {
    color: theme.color.textMuted, fontSize: 12, textAlign: "center",
    paddingHorizontal: 24, paddingTop: 20, fontStyle: "italic",
  },
});
