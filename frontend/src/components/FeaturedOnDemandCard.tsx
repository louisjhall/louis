/**
 * Featured On Demand card — client Today tab.
 *
 * Renders nothing until the coach pins one On Demand item as "featured
 * this week" from `/(coach)/on-demand`. Tapping the card routes to the
 * appropriate viewer:
 *
 *   • workout → POST /on-demand/items/{id}/start-workout → guided flow
 *   • video   → /on-demand/{id}/video
 *   • audio   → /on-demand/{id}/audio
 *
 * The heavy `workout_json` blob is stripped by the backend on
 * `/api/on-demand/featured` so this card is cheap even when the
 * underlying workout has hundreds of exercises.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, Image, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { theme } from "@/src/lib/theme";
import { api } from "@/src/lib/api";

type FeaturedItem = {
  id: string;
  title: string;
  description?: string;
  content_type: "workout" | "video" | "audio";
  duration_seconds?: number | null;
  thumbnail_storage_key?: string | null;
};

export function FeaturedOnDemandCard() {
  const router = useRouter();
  const [item, setItem] = useState<FeaturedItem | null>(null);
  const [thumbUrl, setThumbUrl] = useState<string | null>(null);
  const [starting] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api<{ item: FeaturedItem | null }>("/on-demand/featured");
      setItem(r?.item || null);
      // Fetch a presigned thumbnail URL if we have one to show.
      if (r?.item?.thumbnail_storage_key) {
        try {
          const t = await api<{ url: string }>(`/on-demand/items/${r.item.id}/thumbnail-url`);
          setThumbUrl(t?.url || null);
        } catch { setThumbUrl(null); }
      } else {
        setThumbUrl(null);
      }
    } catch {
      // Silent — the card is optional; hide if the endpoint is missing.
      setItem(null);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const onOpen = useCallback(() => {
    if (!item) return;
    if (item.content_type === "workout") {
      // Iter200 · Do NOT call `/start-workout` here — that would mutate
      // today's calendar before the member has confirmed. Route to the
      // preview screen; the workout row is only created when the member
      // taps START on the preview.
      router.push(`/on-demand/${item.id}/workout` as any);
      return;
    }
    if (item.content_type === "video") {
      router.push(`/on-demand/${item.id}/video` as any);
      return;
    }
    if (item.content_type === "audio") {
      router.push(`/on-demand/${item.id}/audio` as any);
    }
  }, [item, router]);

  if (!item) return null;

  const icon: any = item.content_type === "workout" ? "barbell"
                  : item.content_type === "video"   ? "videocam"
                  :                                    "headset";
  const durMin = item.duration_seconds
    ? Math.max(1, Math.round(item.duration_seconds / 60))
    : null;

  return (
    <Pressable
      onPress={onOpen}
      disabled={starting}
      style={({ pressed }) => [styles.card, pressed && { opacity: 0.9 }]}
      testID="home-featured-on-demand"
      accessibilityRole="button"
      accessibilityLabel={`Featured On Demand: ${item.title}`}
    >
      <View style={styles.thumbBox}>
        {thumbUrl ? (
          <Image source={{ uri: thumbUrl }} style={styles.thumb} />
        ) : (
          <View style={styles.thumbFallback}>
            <Ionicons name={icon} size={40} color={theme.color.brand} />
          </View>
        )}
        <View style={styles.badge}>
          <Ionicons name="star" size={11} color="#fff" />
          <Text style={styles.badgeText}>ON DEMAND</Text>
        </View>
        {starting ? (
          <View style={styles.overlay}>
            <ActivityIndicator color="#fff" />
          </View>
        ) : null}
      </View>
      <View style={styles.copy}>
        <Text style={styles.eyebrow}>FEATURED THIS WEEK</Text>
        <Text style={styles.title} numberOfLines={2}>{item.title}</Text>
        <View style={styles.metaRow}>
          <Ionicons name={icon} size={12} color={theme.color.textDim} />
          <Text style={styles.meta}>
            {item.content_type.toUpperCase()}
            {durMin ? ` · ${durMin} min` : ""}
          </Text>
        </View>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: "row",
    borderRadius: 14,
    backgroundColor: theme.color.surface2,
    borderWidth: 1,
    borderColor: theme.color.brand,
    overflow: "hidden",
    shadowColor: theme.color.brand,
    shadowOpacity: 0.25,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 },
    elevation: 3,
  },
  thumbBox: {
    width: 120, height: 100, backgroundColor: "#000",
    alignItems: "center", justifyContent: "center",
  },
  thumb: { width: "100%", height: "100%" },
  thumbFallback: {
    width: "100%", height: "100%",
    alignItems: "center", justifyContent: "center",
    backgroundColor: theme.color.surface,
  },
  badge: {
    position: "absolute", top: 8, left: 8,
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 8, paddingVertical: 3,
    borderRadius: 6, backgroundColor: theme.color.brand,
  },
  badgeText: { color: "#fff", fontSize: 9, fontWeight: "900", letterSpacing: 0.8 },
  overlay: {
    ...StyleSheet.absoluteFillObject,
    alignItems: "center", justifyContent: "center",
    backgroundColor: "rgba(0,0,0,0.55)",
  },
  copy: { flex: 1, padding: 12, justifyContent: "center" },
  eyebrow: {
    color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1.4,
    marginBottom: 4,
  },
  title: {
    color: theme.color.text, fontSize: 15, fontWeight: "800", lineHeight: 20,
  },
  metaRow: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 6 },
  meta: { color: theme.color.textDim, fontSize: 11, fontWeight: "700", letterSpacing: 0.5 },
});
