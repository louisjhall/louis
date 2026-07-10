/**
 * ProfileAvatar — premium aviation-style avatar for CrewFit.
 *
 *  - Shows the client's uploaded photo when present (token-signed URL).
 *  - Falls back to a monogrammed circle with a subtle wings mark and
 *    the client's initials — never a raw emoji or blank silhouette.
 */
import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, Image, StyleProp, ViewStyle } from "react-native";
import { theme } from "@/src/lib/theme";
import { API_BASE, getToken } from "@/src/lib/api";
import { CrewFitWings } from "@/src/components/Logo";

type Props = {
  userId?: string | null;
  name?: string | null;
  size?: number;
  photoUrl?: string | null;                // relative path like "/api/user/profile/photo/<id>"
  ring?: boolean;
  style?: StyleProp<ViewStyle>;
};

function initialsFrom(name?: string | null): string {
  if (!name) return "CF";
  const parts = String(name).trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "CF";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function ProfileAvatar({ userId, name, size = 56, photoUrl, ring = true, style }: Props) {
  const [signedUrl, setSignedUrl] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!photoUrl || !userId) { setSignedUrl(null); return; }
      const token = await getToken();
      if (cancelled) return;
      const path = photoUrl.startsWith("/api") ? photoUrl.replace(/^\/api/, "") : `/user/profile/photo/${userId}`;
      const url = `${API_BASE}${path}${token ? `?token=${encodeURIComponent(token)}` : ""}`;
      setSignedUrl(url);
    })();
    return () => { cancelled = true; };
  }, [photoUrl, userId]);

  const dim = { width: size, height: size, borderRadius: size / 2 };
  const initials = initialsFrom(name);

  return (
    <View style={[styles.wrap, dim, ring && styles.ring, style]}>
      {signedUrl ? (
        <Image
          source={{ uri: signedUrl }}
          style={[dim, { position: "absolute" }]}
          accessibilityLabel={`${name || "Client"} photo`}
        />
      ) : (
        <>
          <View style={[styles.mono, dim]}>
            <CrewFitWings size={size * 0.7} tint={"rgba(163,24,46,0.28)"} />
          </View>
          <Text style={[styles.initials, { fontSize: Math.max(11, Math.round(size / 3)) }]} numberOfLines={1}>
            {initials}
          </Text>
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    alignItems: "center", justifyContent: "center",
    backgroundColor: theme.color.surface3, overflow: "hidden",
    borderWidth: 1, borderColor: theme.color.border,
  },
  ring: { borderWidth: 2, borderColor: theme.color.brand },
  mono: {
    position: "absolute",
    alignItems: "center", justifyContent: "center",
    backgroundColor: theme.color.navy,
  },
  initials: {
    color: theme.color.text, fontFamily: theme.font.display, fontWeight: "900",
    letterSpacing: 1.5, textAlign: "center", textShadowColor: "rgba(0,0,0,0.8)", textShadowRadius: 4,
  },
});
