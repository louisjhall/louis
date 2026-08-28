/**
 * On Demand — Client browse (Stage 2).
 *
 * Replaces the Stage 1 placeholder with a real browse experience:
 *   • Horizontal category rail across the top (prominent) — tapping
 *     one filters the grid below. "All" is the default.
 *   • Two-column grid of content cards. Each card shows the thumbnail
 *     (or a type-appropriate placeholder), title, duration and a
 *     content-type badge (WORKOUT / VIDEO / AUDIO).
 *   • Only published items are visible — the backend enforces this on
 *     `/api/on-demand/items` but the coach cache is also filtered
 *     defensively client-side.
 *
 * Tap-through routing:
 *   • Workout → POST /on-demand/items/{id}/start-workout, then push
 *     `/workout/{new_id}/guided` so completion tracking uses the
 *     existing system.
 *   • Video   → push `/on-demand/{id}/video` — full-screen player.
 *   • Audio   → push `/on-demand/{id}/audio` — simple in-app player.
 *
 * Route: /(client)/on-demand
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, Image,
  ActivityIndicator, RefreshControl, useWindowDimensions, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { theme } from "@/src/lib/theme";
import { api } from "@/src/lib/api";
import { useBottomSafePad } from "@/src/lib/useBottomSafePad";

type ContentType = "workout" | "video" | "audio";

type Category = { id: string; name: string; slug: string };
type Item = {
  id: string;
  title: string;
  description?: string;
  content_type: ContentType;
  category_id: string | null;
  tag_ids: string[];
  duration_seconds: number | null;
  thumbnail_storage_key?: string | null;
  published: boolean;
};

export default function OnDemandClientScreen() {
  const router = useRouter();
  const bottomPad = useBottomSafePad();
  const { width } = useWindowDimensions();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [items, setItems] = useState<Item[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [activeCategory, setActiveCategory] = useState<string | "all">("all");
  const [thumbUrls, setThumbUrls] = useState<Record<string, string>>({});
  const [startingId, setStartingId] = useState<string | null>(null);

  const reload = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const [cRes, iRes] = await Promise.all([
        api<{ categories: Category[] }>("/on-demand/categories"),
        // The public list endpoint returns published items only.
        api<{ items: Item[] }>("/on-demand/items?limit=200"),
      ]);
      setCategories(cRes.categories || []);
      setItems((iRes.items || []).filter((it) => it.published));
    } catch (e: any) {
      if (!silent) Alert.alert("Couldn't load On Demand", e?.message || String(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  // Fetch presigned thumbnail URLs lazily — only for items that have a
  // thumbnail and aren't already resolved. Runs after the item list lands.
  useEffect(() => {
    const missing = items.filter(
      (it) => it.thumbnail_storage_key && !thumbUrls[it.id],
    );
    if (missing.length === 0) return;
    let cancelled = false;
    (async () => {
      const next: Record<string, string> = {};
      for (const it of missing) {
        try {
          const r = await api<{ url: string }>(`/on-demand/items/${it.id}/thumbnail-url`);
          if (r?.url) next[it.id] = r.url;
        } catch { /* ignore per-thumbnail failures */ }
      }
      if (!cancelled && Object.keys(next).length > 0) {
        setThumbUrls((prev) => ({ ...prev, ...next }));
      }
    })();
    return () => { cancelled = true; };
  }, [items, thumbUrls]);

  // Category counts for the rail — "All" first, then categories with ≥ 1 item.
  const rail = useMemo(() => {
    const counts = new Map<string, number>();
    for (const it of items) {
      const key = it.category_id || "__uncat";
      counts.set(key, (counts.get(key) || 0) + 1);
    }
    const chips: { id: string | "all"; label: string; count: number }[] = [
      { id: "all", label: "All", count: items.length },
    ];
    for (const c of categories) {
      const n = counts.get(c.id) || 0;
      if (n > 0) chips.push({ id: c.id, label: c.name, count: n });
    }
    if (counts.get("__uncat")) {
      chips.push({ id: "__uncat" as any, label: "Uncategorised", count: counts.get("__uncat") || 0 });
    }
    return chips;
  }, [items, categories]);

  const filtered = useMemo(() => {
    if (activeCategory === "all") return items;
    if ((activeCategory as any) === "__uncat") return items.filter((it) => !it.category_id);
    return items.filter((it) => it.category_id === activeCategory);
  }, [items, activeCategory]);

  const onOpen = useCallback(async (item: Item) => {
    if (item.content_type === "workout") {
      try {
        setStartingId(item.id);
        const r = await api<{ workout_id: string }>(`/on-demand/items/${item.id}/start-workout`, {
          method: "POST", body: {},
        });
        setStartingId(null);
        // Iter196 · Route to the standard workout entry point so the user
        // gets the same Guided / Manual choice as any other workout. If
        // they've already chosen a preferred mode via
        // `getRememberedMode()`, that path deep-links straight through.
        router.push(`/workout/${r.workout_id}` as any);
      } catch (e: any) {
        setStartingId(null);
        Alert.alert("Couldn't start", e?.message || String(e));
      }
      return;
    }
    if (item.content_type === "video") {
      router.push(`/on-demand/${item.id}/video` as any);
      return;
    }
    if (item.content_type === "audio") {
      router.push(`/on-demand/${item.id}/audio` as any);
    }
  }, [router]);

  // Iter196 · Vertical category list on the left instead of horizontal
  // chips. On phones ≥ 360px wide we give the list a fixed 130px column;
  // narrower devices fall back to a stacked layout (list on top, cards
  // below) so we don't crush the cards.
  const useSideList = width >= 360;
  const listColumnWidth = 130;
  const cardsAreaWidth = useSideList ? width - 20 * 2 - listColumnWidth - 12 : width - 20 * 2;
  const cardWidthNew = Math.floor((cardsAreaWidth - 12) / 2);

  const categoryList = (
    <View style={useSideList ? styles.listCol : styles.listStack}>
      <Text style={styles.listHeading}>CATEGORIES</Text>
      <ScrollView
        style={{ flexGrow: 0 }}
        contentContainerStyle={styles.listBody}
        showsVerticalScrollIndicator={false}
      >
        {rail.map((c) => {
          const active = activeCategory === c.id;
          return (
            <Pressable
              key={String(c.id)}
              onPress={() => setActiveCategory(c.id as any)}
              style={[styles.listRow, active && styles.listRowActive]}
              testID={`od-cat-${c.id}`}
              accessibilityRole="button"
              accessibilityState={{ selected: active }}
            >
              <View style={{ flex: 1 }}>
                <Text style={[styles.listRowLabel, active && styles.listRowLabelActive]} numberOfLines={2}>
                  {c.label}
                </Text>
                <Text style={[styles.listRowCount, active && styles.listRowCountActive]}>
                  {c.count} {c.count === 1 ? "item" : "items"}
                </Text>
              </View>
              {active ? (
                <Ionicons name="chevron-forward" size={16} color="#fff" />
              ) : null}
            </Pressable>
          );
        })}
      </ScrollView>
    </View>
  );

  const cardsPane = (
    <View style={{ flex: 1 }}>
      {loading ? (
        <View style={styles.centerFill}>
          <ActivityIndicator color={theme.color.brand} />
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={[styles.grid, { paddingBottom: bottomPad + 24 }]}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => { setRefreshing(true); reload(true); }}
              tintColor={theme.color.brand}
            />
          }
        >
          {filtered.length === 0 ? (
            <View style={styles.emptyBox}>
              <Ionicons name="albums-outline" size={38} color={theme.color.brand} />
              <Text style={styles.emptyTitle}>Nothing here yet</Text>
              <Text style={styles.emptyBody}>
                Your coach hasn&apos;t published any items in this category. Pull to refresh, or tap another category.
              </Text>
            </View>
          ) : (
            <View style={styles.cards}>
              {filtered.map((it) => (
                <ContentCard
                  key={it.id}
                  item={it}
                  thumbUrl={thumbUrls[it.id]}
                  width={cardWidthNew}
                  starting={startingId === it.id}
                  onPress={() => onOpen(it)}
                />
              ))}
            </View>
          )}
        </ScrollView>
      )}
    </View>
  );

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <Text style={styles.title}>ON DEMAND</Text>
        <Text style={styles.subtitle}>Curated by your coach</Text>
      </View>

      {useSideList ? (
        <View style={styles.splitRow}>
          {categoryList}
          {cardsPane}
        </View>
      ) : (
        <View style={{ flex: 1 }}>
          {categoryList}
          {cardsPane}
        </View>
      )}
    </SafeAreaView>
  );
}

/* ---------------------------------------------------------------------- */
/* Card                                                                    */
/* ---------------------------------------------------------------------- */

function ContentCard({
  item, thumbUrl, width, starting, onPress,
}: {
  item: Item;
  thumbUrl?: string;
  width: number;
  starting: boolean;
  onPress: () => void;
}) {
  const badge = item.content_type.toUpperCase();
  const badgeIcon: any = item.content_type === "workout" ? "barbell"
                       : item.content_type === "video"   ? "videocam"
                       :                                    "headset";
  const dur = item.duration_seconds
    ? `${Math.max(1, Math.round(item.duration_seconds / 60))} min`
    : null;
  return (
    <Pressable
      onPress={onPress}
      style={[styles.card, { width }]}
      testID={`od-card-${item.id}`}
      accessibilityRole="button"
      accessibilityLabel={`${item.title} — ${badge}${dur ? ` — ${dur}` : ""}`}
      disabled={starting}
    >
      <View style={styles.thumbWrap}>
        {thumbUrl ? (
          <Image source={{ uri: thumbUrl }} style={styles.thumb} />
        ) : (
          <View style={styles.thumbFallback}>
            <Ionicons name={badgeIcon} size={30} color={theme.color.brand} />
          </View>
        )}
        <View style={styles.badge}>
          <Ionicons name={badgeIcon} size={11} color="#fff" />
          <Text style={styles.badgeText}>{badge}</Text>
        </View>
        {starting ? (
          <View style={styles.startingOverlay}>
            <ActivityIndicator color="#fff" />
          </View>
        ) : null}
      </View>
      <Text style={styles.cardTitle} numberOfLines={2}>{item.title}</Text>
      {dur ? <Text style={styles.cardMeta}>{dur}</Text> : null}
    </Pressable>
  );
}

/* ---------------------------------------------------------------------- */
/* Styles                                                                  */
/* ---------------------------------------------------------------------- */

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.color.surface },
  header: {
    paddingHorizontal: 20, paddingTop: 16, paddingBottom: 10,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: theme.color.border,
  },
  title: {
    color: theme.color.text, fontSize: 22, fontWeight: "800", letterSpacing: 1.5,
  },
  subtitle: {
    color: theme.color.textDim, fontSize: 12, letterSpacing: 1, marginTop: 2,
  },

  rail: {
    // Iter196 · Kept for backward compatibility with any external ref;
    // no longer rendered — categories use the vertical list below.
    display: "none",
  },
  railBody: { display: "none" },

  splitRow: { flex: 1, flexDirection: "row" },
  listCol: {
    width: 130,
    borderRightWidth: StyleSheet.hairlineWidth,
    borderRightColor: theme.color.border,
    backgroundColor: theme.color.surface,
    paddingTop: 12,
    paddingHorizontal: 10,
  },
  listStack: {
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: theme.color.border,
    paddingHorizontal: 16,
    paddingTop: 12,
    paddingBottom: 8,
  },
  listHeading: {
    color: theme.color.textDim,
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 1.4,
    marginBottom: 8,
  },
  listBody: { paddingBottom: 8 },
  listRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 10,
    paddingVertical: 10,
    borderRadius: 10,
    marginBottom: 4,
    backgroundColor: theme.color.surface2,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.color.border,
  },
  listRowActive: {
    backgroundColor: theme.color.brand,
    borderColor: theme.color.brand,
  },
  listRowLabel: {
    color: theme.color.text,
    fontSize: 13,
    fontWeight: "800",
    letterSpacing: 0.4,
  },
  listRowLabelActive: { color: "#fff" },
  listRowCount: {
    color: theme.color.textDim,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 0.4,
    marginTop: 2,
  },
  listRowCountActive: { color: "rgba(255,255,255,0.85)" },

  centerFill: { flex: 1, alignItems: "center", justifyContent: "center" },
  grid: { paddingHorizontal: 12, paddingTop: 12 },
  cards: {
    flexDirection: "row", flexWrap: "wrap", gap: 12,
  },
  card: {
    borderRadius: 14, backgroundColor: theme.color.surface2,
    borderWidth: StyleSheet.hairlineWidth, borderColor: theme.color.border,
    overflow: "hidden",
  },
  thumbWrap: {
    width: "100%", aspectRatio: 16 / 10, backgroundColor: "#000",
    alignItems: "center", justifyContent: "center", overflow: "hidden",
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
    borderRadius: 6, backgroundColor: "rgba(0,0,0,0.7)",
  },
  badgeText: {
    color: "#fff", fontSize: 9, fontWeight: "800", letterSpacing: 0.8,
  },
  startingOverlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(0,0,0,0.55)",
    alignItems: "center", justifyContent: "center",
  },
  cardTitle: {
    color: theme.color.text, fontSize: 13, fontWeight: "700",
    paddingHorizontal: 10, paddingTop: 10,
  },
  cardMeta: {
    color: theme.color.textDim, fontSize: 11,
    paddingHorizontal: 10, paddingBottom: 10, paddingTop: 3,
  },

  emptyBox: {
    marginTop: 40, alignItems: "center", padding: 24,
    borderRadius: 16, borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.color.border, backgroundColor: theme.color.surface2,
  },
  emptyTitle: {
    color: theme.color.text, fontSize: 16, fontWeight: "800", marginTop: 10,
  },
  emptyBody: {
    color: theme.color.text, fontSize: 12, lineHeight: 18,
    textAlign: "center", marginTop: 6, opacity: 0.8,
  },
});
