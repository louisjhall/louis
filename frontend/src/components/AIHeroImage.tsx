/**
 * AIHeroImage — renders the best-fit CrewFit brand image for a given context.
 *
 * Fetches `/api/brand-images/pick?...` on mount, then builds a token-signed
 * stream URL. If nothing matches or the API errors, gracefully falls back to
 * a solid dark backdrop so cards never look broken.
 */
import React, { useEffect, useState } from "react";
import { View, StyleSheet, StyleProp, ViewStyle, ActivityIndicator } from "react-native";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { api, API_BASE, getToken } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

export type ImageContext = {
  role?: string;                  // "pilot" | "cabin_crew" | ...
  gender?: string;                // "male" | "female"
  goal?: string;                  // "marathon" | "ironman" | ...
  workout_type?: string;          // "strength" | "endurance" | "mobility"
  phase?: string;                 // "base" | "build" | "peak" | "taper"
  context?: string;               // "recovery" | "standby" | "event"
  day_type?: string;              // "long_haul" | "short_haul" | ...
};

type Props = {
  ctx: ImageContext;
  style?: StyleProp<ViewStyle>;
  gradient?: boolean;             // dark overlay on top for text legibility
  children?: React.ReactNode;
  showLoader?: boolean;
};

// Simple in-memory cache to avoid re-picking on every card
const pickCache = new Map<string, { id: string }>();

function cacheKey(c: ImageContext): string {
  return Object.entries(c)
    .filter(([, v]) => !!v)
    .sort()
    .map(([k, v]) => `${k}=${v}`)
    .join("&");
}

export function AIHeroImage({ ctx, style, gradient = true, children, showLoader = false }: Props) {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // Iter172 · Theme-aware hero background. In LIGHT MODE the entire
  // upper header section paints pure white so the ClientProfileHeader
  // sits on a clean white surface (per brand refresh). We suppress
  // both the AI image AND the dark gradient overlay in light mode.
  const isLight = theme.mode === "light";

  useEffect(() => {
    // Iter172 · Skip the image fetch entirely in light mode — the hero
    // is a solid white surface so there's nothing to load.
    if (isLight) {
      setUrl(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const ck = cacheKey(ctx);
        let img = pickCache.get(ck);
        if (!img) {
          const q = new URLSearchParams(
            Object.entries(ctx).filter(([, v]) => v).map(([k, v]) => [k, String(v)]),
          ).toString();
          const r = await api<{ image: { id: string } }>(`/brand-images/pick${q ? `?${q}` : ""}`);
          img = { id: r.image.id };
          pickCache.set(ck, img);
        }
        const token = await getToken();
        if (cancelled) return;
        setUrl(`${API_BASE}/brand-images/${img.id}/stream${token ? `?token=${encodeURIComponent(token)}` : ""}`);
      } catch {
        if (!cancelled) setUrl(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cacheKey(ctx), isLight]);

  return (
    <View style={[styles.wrap, isLight && styles.wrapLight, style]}>
      {url && !isLight ? (
        <Image
          source={{ uri: url }}
          style={StyleSheet.absoluteFill}
          contentFit="cover"
          transition={200}
          accessibilityLabel="CrewFit brand image"
        />
      ) : (
        <View style={[StyleSheet.absoluteFill, isLight ? styles.fallbackLight : styles.fallback]}>
          {loading && showLoader && !isLight ? <ActivityIndicator color={theme.color.brand} /> : null}
        </View>
      )}
      {gradient && !isLight ? (
        <LinearGradient
          colors={["rgba(0,0,0,0.35)", "rgba(0,0,0,0.85)", "#000000"]}
          locations={[0, 0.55, 1]}
          style={StyleSheet.absoluteFill}
        />
      ) : null}
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { backgroundColor: theme.color.surface, overflow: "hidden" },
  // Iter172 · Light-mode override — pure white bg beneath the hero.
  wrapLight: { backgroundColor: "#FFFFFF" },
  fallback: {
    backgroundColor: theme.color.navy,
    alignItems: "center", justifyContent: "center",
  },
  fallbackLight: {
    backgroundColor: "#FFFFFF",
    alignItems: "center", justifyContent: "center",
  },
});
