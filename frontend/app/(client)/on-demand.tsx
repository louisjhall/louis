/**
 * On Demand — Client browse (Iter200 redesign).
 *
 * Two-screen flow, contained in a single tab file:
 *
 *   1. **Category picker** (default) — a clean vertical list of the
 *      coach's categories, each with an icon derived from the
 *      category's slug/name. Nothing else is shown. There is NO grid,
 *      NO "all" chip, NO featured strip on this screen.
 *   2. **Category detail** — once the member taps a category, we swap
 *      to a two-column grid of that category's content cards, with a
 *      back button in the header to return to the picker.
 *
 * Tap-through routing (unchanged):
 *   • Workout → POST /on-demand/items/{id}/start-workout, then push
 *     `/workout/{new_id}` so completion tracking uses the existing
 *     system.
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
import { resolveThumbnail } from "@/src/lib/onDemandThumbnails";

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
  thumbnail_filename?: string | null;
  published: boolean;
};

type IoniconName = React.ComponentProps<typeof Ionicons>["name"];

// ---------------------------------------------------------------------------
// Category → icon mapping.
// Uses slug (canonical), falling back to name-substring matches so the coach
// doesn't have to configure anything to get the right icon.
// ---------------------------------------------------------------------------
const CATEGORY_ICON_RULES: { keys: string[]; icon: IoniconName }[] = [
  { keys: ["strength", "weight", "lift", "resistance"], icon: "barbell" },
  { keys: ["cardio", "run", "running", "jog", "endurance"], icon: "flame" },
  { keys: ["hiit", "interval", "conditioning", "metcon"], icon: "flash" },
  { keys: ["mobility", "stretch", "flexibility"], icon: "body" },
  { keys: ["yoga", "meditation", "mindfulness", "breath"], icon: "leaf" },
  { keys: ["pilates", "core", "abs"], icon: "body-outline" },
  { keys: ["recovery", "rest", "sleep", "restorative"], icon: "moon" },
  { keys: ["warm", "warmup", "warm-up", "activation"], icon: "sunny" },
  { keys: ["cool", "cooldown", "cool-down"], icon: "snow" },
  { keys: ["nutrition", "food", "meal", "diet"], icon: "restaurant" },
  { keys: ["podcast", "audio", "listen"], icon: "headset" },
  { keys: ["video", "watch"], icon: "videocam" },
  { keys: ["layover", "hotel", "travel"], icon: "airplane" },
  { keys: ["flight", "in-flight", "onboard"], icon: "paper-plane" },
  { keys: ["standby", "reserve"], icon: "time" },
  { keys: ["walk", "outdoor", "hike"], icon: "walk" },
  { keys: ["swim", "pool"], icon: "water" },
  { keys: ["ride", "bike", "cycle"], icon: "bicycle" },
  { keys: ["beginner", "start", "starter"], icon: "school" },
];

function iconForCategory(cat: { name: string; slug: string }): IoniconName {
  const needle = `${cat.slug || ""} ${cat.name || ""}`.toLowerCase();
  for (const rule of CATEGORY_ICON_RULES) {
    if (rule.keys.some((k) => needle.includes(k))) return rule.icon;
  }
  return "albums-outline";
}

export default function OnDemandClientScreen() {
  const router = useRouter();
  const bottomPad = useBottomSafePad();
  const { width } = useWindowDimensions();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [items, setItems] = useState<Item[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [thumbUrls, setThumbUrls] = useState<Record<string, string>>({});

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

  // Lazy presigned thumbnail URLs for items that have a thumbnail. Only
  // fetches for items in the currently visible category to keep it cheap.
  useEffect(() => {
    if (!selectedCategory) return;
    const visible = selectedCategory === "__uncat"
      ? items.filter((it) => !it.category_id)
      : items.filter((it) => it.category_id === selectedCategory);
    const missing = visible.filter(
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
  }, [items, thumbUrls, selectedCategory]);

  // Category list: only categories that actually have ≥ 1 published item.
  // Uncategorised items surface as a synthetic "Uncategorised" bucket at
  // the end, matching the coach dashboard's behaviour.
  const visibleCategories = useMemo(() => {
    const counts = new Map<string, number>();
    for (const it of items) {
      const key = it.category_id || "__uncat";
      counts.set(key, (counts.get(key) || 0) + 1);
    }
    const rows: {
      id: string;
      name: string;
      slug: string;
      count: number;
      icon: IoniconName;
    }[] = [];
    for (const c of categories) {
      const n = counts.get(c.id) || 0;
      if (n > 0) {
        rows.push({
          id: c.id,
          name: c.name,
          slug: c.slug,
          count: n,
          icon: iconForCategory(c),
        });
      }
    }
    if (counts.get("__uncat")) {
      rows.push({
        id: "__uncat",
        name: "Other",
        slug: "other",
        count: counts.get("__uncat") || 0,
        icon: "albums-outline",
      });
    }
    return rows;
  }, [items, categories]);

  const filtered = useMemo(() => {
    if (!selectedCategory) return [] as Item[];
    if (selectedCategory === "__uncat") return items.filter((it) => !it.category_id);
    return items.filter((it) => it.category_id === selectedCategory);
  }, [items, selectedCategory]);

  const selectedCategoryName = useMemo(() => {
    if (!selectedCategory) return "";
    if (selectedCategory === "__uncat") return "Other";
    return visibleCategories.find((c) => c.id === selectedCategory)?.name || "";
  }, [selectedCategory, visibleCategories]);

  const onOpen = useCallback(async (item: Item) => {
    if (item.content_type === "workout") {
      // Iter200 · Do NOT call `/start-workout` here — that mutates the
      // member's calendar. Route to the preview screen; the workout row
      // is only created when the member explicitly taps START.
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
  }, [router]);

  // Two-column grid width — used only on the category detail sub-screen.
  const cardWidthNew = Math.floor((width - 20 * 2 - 12) / 2);

  const renderCategoryPicker = () => (
    <ScrollView
      contentContainerStyle={[styles.pickerBody, { paddingBottom: bottomPad + 24 }]}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={() => { setRefreshing(true); reload(true); }}
          tintColor={theme.color.brand}
        />
      }
    >
      {loading ? (
        <View style={styles.centerFill}>
          <ActivityIndicator color={theme.color.brand} />
        </View>
      ) : visibleCategories.length === 0 ? (
        <View style={styles.emptyBox}>
          <Ionicons name="albums-outline" size={38} color={theme.color.brand} />
          <Text style={styles.emptyTitle}>Nothing here yet</Text>
          <Text style={styles.emptyBody}>
            Your coach hasn&apos;t published any On Demand content yet. Pull to refresh.
          </Text>
        </View>
      ) : (
        visibleCategories.map((c) => (
          <Pressable
            key={c.id}
            onPress={() => setSelectedCategory(c.id)}
            style={({ pressed }) => [styles.catRow, pressed && styles.catRowPressed]}
            testID={`od-cat-${c.id}`}
            accessibilityRole="button"
            accessibilityLabel={`${c.name} — ${c.count} ${c.count === 1 ? "item" : "items"}`}
          >
            <View style={styles.catIconWrap}>
              <Ionicons name={c.icon} size={26} color={theme.color.brand} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.catName} numberOfLines={1}>{c.name}</Text>
              <Text style={styles.catCount}>
                {c.count} {c.count === 1 ? "item" : "items"}
              </Text>
            </View>
            <Ionicons name="chevron-forward" size={20} color={theme.color.textDim} />
          </Pressable>
        ))
      )}
    </ScrollView>
  );

  const renderCategoryDetail = () => (
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
            Your coach hasn&apos;t published any items in this category. Pull to refresh, or go back to another category.
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
              starting={false}
              onPress={() => onOpen(it)}
            />
          ))}
        </View>
      )}
    </ScrollView>
  );

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        {selectedCategory ? (
          <View style={styles.headerRow}>
            <Pressable
              onPress={() => setSelectedCategory(null)}
              hitSlop={12}
              style={styles.backBtn}
              testID="od-back-to-categories"
              accessibilityRole="button"
              accessibilityLabel="Back to categories"
            >
              <Ionicons name="chevron-back" size={22} color={theme.color.text} />
            </Pressable>
            <View style={{ flex: 1 }}>
              <Text style={styles.title} numberOfLines={1}>
                {(selectedCategoryName || "").toUpperCase()}
              </Text>
              <Text style={styles.subtitle}>
                {filtered.length} {filtered.length === 1 ? "item" : "items"}
              </Text>
            </View>
          </View>
        ) : (
          <>
            <Text style={styles.title}>ON DEMAND</Text>
            <Text style={styles.subtitle}>Choose a category to start</Text>
          </>
        )}
      </View>

      {selectedCategory ? renderCategoryDetail() : renderCategoryPicker()}
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
  const badgeIcon: IoniconName = item.content_type === "workout" ? "barbell"
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
        {(() => {
          // Iter200 · Prefer the bundled thumbnail (fast, offline-safe).
          // Falls back to the R2 presigned URL, then to a themed placeholder.
          const bundled = resolveThumbnail(item.thumbnail_filename || null);
          if (bundled) return <Image source={bundled} style={styles.thumb} />;
          if (thumbUrl) return <Image source={{ uri: thumbUrl }} style={styles.thumb} />;
          return (
            <View style={styles.thumbFallback}>
              <Ionicons name={badgeIcon} size={30} color={theme.color.brand} />
            </View>
          );
        })()}
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
    paddingHorizontal: 20, paddingTop: 16, paddingBottom: 12,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: theme.color.border,
  },
  headerRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  backBtn: {
    width: 34, height: 34, alignItems: "center", justifyContent: "center",
    borderRadius: 17,
  },
  title: {
    color: theme.color.text, fontSize: 22, fontWeight: "800", letterSpacing: 1.5,
  },
  subtitle: {
    color: theme.color.textDim, fontSize: 12, letterSpacing: 1, marginTop: 2,
  },

  pickerBody: {
    paddingHorizontal: 16, paddingTop: 16, gap: 10,
  },
  catRow: {
    flexDirection: "row", alignItems: "center", gap: 14,
    paddingHorizontal: 16, paddingVertical: 16,
    borderRadius: 14,
    backgroundColor: theme.color.surface2,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.color.border,
  },
  catRowPressed: { opacity: 0.7 },
  catIconWrap: {
    width: 48, height: 48, borderRadius: 24,
    backgroundColor: theme.color.brandTint || "rgba(220,38,38,0.10)",
    alignItems: "center", justifyContent: "center",
  },
  catName: {
    color: theme.color.text, fontSize: 16, fontWeight: "800", letterSpacing: 0.3,
  },
  catCount: {
    color: theme.color.textDim, fontSize: 12, marginTop: 3, letterSpacing: 0.4,
  },

  centerFill: {
    minHeight: 240, alignItems: "center", justifyContent: "center",
  },

  grid: { paddingHorizontal: 20, paddingTop: 16 },
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
    marginTop: 40, marginHorizontal: 20, alignItems: "center", padding: 24,
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
