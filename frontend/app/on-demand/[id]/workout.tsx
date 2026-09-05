/**
 * On Demand · Workout preview screen.
 *
 * The member arrives here from a category card. This screen ONLY reads
 * the on-demand item — it does NOT touch the member's calendar. A
 * `db.workouts` row is only created when the member explicitly taps
 * "START WORKOUT" here, which calls `POST /on-demand/items/{id}/start-workout`
 * and then navigates to `/workout/{new_id}` for the guided flow.
 *
 * This mirrors the video/audio preview screens (`./video.tsx`,
 * `./audio.tsx`) so all three content types have the same
 * browse-vs-start separation.
 *
 * Route: /on-demand/[id]/workout
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Image,
} from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { resolveThumbnail } from "@/src/lib/onDemandThumbnails";

type Item = {
  id: string;
  title: string;
  description?: string;
  duration_seconds?: number | null;
  content_type: string;
  thumbnail_filename?: string | null;
  thumbnail_storage_key?: string | null;
  workout_json?: any;
  equipment?: string[];
  category_id?: string | null;
};

function _flatCount(rows: any[]): number {
  let n = 0;
  for (const row of rows || []) {
    if (!row) continue;
    if (row.kind === "group") n += (row.items || []).length;
    else n += 1;
  }
  return n;
}

export default function OnDemandWorkoutPreview() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [item, setItem] = useState<Item | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  // Iter200 · R2 presigned URL for the persistent thumbnail — resolved
  // lazily when the item is loaded. Preferred over the bundled asset so
  // this screen keeps working after a fresh deploy wipes the pod
  // filesystem.
  const [thumbUrl, setThumbUrl] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await api<{ item: Item }>(`/on-demand/items/${id}`);
      setItem(r.item);
      if (r.item?.thumbnail_storage_key) {
        try {
          const u = await api<{ url: string }>(`/on-demand/items/${id}/thumbnail-url`);
          if (u?.url) setThumbUrl(u.url);
        } catch { /* fall through to bundle / placeholder */ }
      }
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const startWorkout = useCallback(async () => {
    if (!id) return;
    setStarting(true);
    setError(null);
    try {
      // ONLY here — after explicit confirmation — do we write to
      // `db.workouts` (i.e. the member's calendar for today).
      const r = await api<{ workout_id: string }>(
        `/on-demand/items/${id}/start-workout`,
        { method: "POST", body: {} },
      );
      // Replace the current screen so the back button skips the
      // preview and returns to the on-demand list.
      router.replace(`/workout/${r.workout_id}` as any);
    } catch (e: any) {
      setError(e?.message || String(e));
      setStarting(false);
    }
  }, [id, router]);

  const dur = item?.duration_seconds
    ? `${Math.max(1, Math.round(item.duration_seconds / 60))} min`
    : null;

  const wj = item?.workout_json || {};
  const warmupCount = useMemo(() => _flatCount(wj.warmup || []), [wj]);
  const mainCount = useMemo(() => _flatCount(wj.exercises || []), [wj]);
  const cooldownCount = useMemo(() => _flatCount(wj.cooldown || []), [wj]);

  const bundledThumb = resolveThumbnail(item?.thumbnail_filename || null);

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <View style={styles.topBar}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="od-workout-close">
          <Ionicons name="close" size={26} color={theme.color.text} />
        </Pressable>
        <Text style={styles.eyebrow}>ON DEMAND · PREVIEW</Text>
        <View style={{ width: 26 }} />
      </View>

      {loading ? (
        <View style={styles.centre}>
          <ActivityIndicator color={theme.color.brand} />
        </View>
      ) : error && !item ? (
        <View style={styles.centre}>
          <Ionicons name="alert-circle-outline" size={36} color={theme.color.brand} />
          <Text style={styles.errorText}>{error}</Text>
        </View>
      ) : item ? (
        <>
          <ScrollView contentContainerStyle={styles.body} showsVerticalScrollIndicator={false}>
            <View style={styles.thumbWrap}>
              {thumbUrl ? (
                <Image source={{ uri: thumbUrl }} style={styles.thumb} resizeMode="cover" />
              ) : bundledThumb ? (
                <Image source={bundledThumb} style={styles.thumb} resizeMode="cover" />
              ) : (
                <View style={styles.thumbFallback}>
                  <Ionicons name="barbell" size={44} color={theme.color.brand} />
                </View>
              )}
              <View style={styles.badge}>
                <Ionicons name="barbell" size={11} color="#fff" />
                <Text style={styles.badgeText}>WORKOUT</Text>
              </View>
            </View>

            <Text style={styles.title}>{item.title}</Text>
            {dur ? (
              <View style={styles.metaRow}>
                <Ionicons name="time-outline" size={14} color={theme.color.textMuted} />
                <Text style={styles.metaText}>{dur}</Text>
                {item.equipment && item.equipment.length > 0 ? (
                  <>
                    <Text style={styles.metaSep}>•</Text>
                    <Ionicons name="cube-outline" size={14} color={theme.color.textMuted} />
                    <Text style={styles.metaText} numberOfLines={1}>
                      {item.equipment.join(", ")}
                    </Text>
                  </>
                ) : null}
              </View>
            ) : null}

            {item.description ? (
              <Text style={styles.description}>{item.description}</Text>
            ) : null}

            <View style={styles.blocks}>
              <View style={styles.block}>
                <Ionicons name="flame" size={16} color={theme.color.brand} />
                <Text style={styles.blockLabel}>WARM-UP</Text>
                <Text style={styles.blockCount}>{warmupCount}</Text>
              </View>
              <View style={styles.block}>
                <Ionicons name="barbell" size={16} color={theme.color.brand} />
                <Text style={styles.blockLabel}>MAIN</Text>
                <Text style={styles.blockCount}>{mainCount}</Text>
              </View>
              <View style={styles.block}>
                <Ionicons name="leaf" size={16} color={theme.color.brand} />
                <Text style={styles.blockLabel}>COOL-DOWN</Text>
                <Text style={styles.blockCount}>{cooldownCount}</Text>
              </View>
            </View>

            {/* Small note so the member knows tapping start replaces
                today's calendar entry. Only shows on the workout content
                type — video/audio previews are consumption-only. */}
            <View style={styles.noteBox}>
              <Ionicons name="information-circle-outline" size={16} color={theme.color.text} />
              <Text style={styles.noteText}>
                Tapping <Text style={styles.noteBold}>START WORKOUT</Text> will add this session
                to today&apos;s calendar. You can browse this preview freely — nothing is written
                until you confirm.
              </Text>
            </View>

            {error ? (
              <View style={styles.errBox}>
                <Ionicons name="alert-circle-outline" size={16} color="#EF4444" />
                <Text style={styles.errText}>{error}</Text>
              </View>
            ) : null}
          </ScrollView>

          <View style={styles.footer}>
            <Pressable
              onPress={startWorkout}
              disabled={starting}
              style={[styles.startBtn, starting && styles.startBtnDisabled]}
              testID="od-workout-start"
              accessibilityRole="button"
              accessibilityLabel="Start this workout"
            >
              {starting ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <>
                  <Ionicons name="play" size={18} color="#fff" />
                  <Text style={styles.startBtnText}>START WORKOUT</Text>
                </>
              )}
            </Pressable>
          </View>
        </>
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  topBar: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 18, paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: theme.color.border,
  },
  eyebrow: {
    color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1.5,
  },

  centre: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  errorText: { color: theme.color.text, fontSize: 13, marginTop: 12, textAlign: "center" },

  body: { paddingHorizontal: 20, paddingTop: 16, paddingBottom: 32 },

  thumbWrap: {
    width: "100%", aspectRatio: 16 / 10, borderRadius: 14, overflow: "hidden",
    backgroundColor: "#000",
  },
  thumb: { width: "100%", height: "100%" },
  thumbFallback: {
    width: "100%", height: "100%", alignItems: "center", justifyContent: "center",
    backgroundColor: theme.color.surface2,
  },
  badge: {
    position: "absolute", top: 10, left: 10,
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6,
    backgroundColor: "rgba(0,0,0,0.7)",
  },
  badgeText: { color: "#fff", fontSize: 9, fontWeight: "800", letterSpacing: 0.8 },

  title: { color: theme.color.text, fontSize: 20, fontWeight: "800", marginTop: 18 },
  metaRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 6 },
  metaText: { color: theme.color.textMuted, fontSize: 12 },
  metaSep: { color: theme.color.textMuted, fontSize: 12, marginHorizontal: 2 },

  description: { color: theme.color.text, fontSize: 13, lineHeight: 20, marginTop: 14, opacity: 0.9 },

  blocks: { flexDirection: "row", gap: 10, marginTop: 20 },
  block: {
    flex: 1, alignItems: "center",
    paddingVertical: 14, borderRadius: 12,
    backgroundColor: theme.color.surface2,
    borderWidth: StyleSheet.hairlineWidth, borderColor: theme.color.border,
  },
  blockLabel: {
    color: theme.color.textMuted, fontSize: 9, fontWeight: "900",
    letterSpacing: 1.2, marginTop: 6,
  },
  blockCount: { color: theme.color.text, fontSize: 20, fontWeight: "800", marginTop: 2 },

  noteBox: {
    marginTop: 20, padding: 12, borderRadius: 10,
    flexDirection: "row", gap: 8,
    backgroundColor: "rgba(245,158,11,0.10)",
    borderWidth: 1, borderColor: "rgba(245,158,11,0.35)",
  },
  noteText: { color: theme.color.text, fontSize: 11, lineHeight: 16, flex: 1 },
  noteBold: { fontWeight: "900" },

  errBox: {
    marginTop: 14, padding: 10, borderRadius: 10,
    flexDirection: "row", gap: 8, alignItems: "center",
    backgroundColor: "rgba(239,68,68,0.10)",
    borderWidth: 1, borderColor: "rgba(239,68,68,0.45)",
  },
  errText: { color: theme.color.text, fontSize: 12, flex: 1 },

  footer: {
    paddingHorizontal: 20, paddingVertical: 14,
    borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.color.border,
    backgroundColor: theme.color.surface,
  },
  startBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    paddingVertical: 16, borderRadius: 12, backgroundColor: theme.color.brand,
  },
  startBtnDisabled: { opacity: 0.6 },
  startBtnText: { color: "#fff", fontWeight: "900", letterSpacing: 1.4, fontSize: 13 },
});
