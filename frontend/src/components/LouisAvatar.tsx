/**
 * LouisAvatar — circular avatar with graceful fallback to "LH" initials.
 *
 * Iter 122b — Primary source is now the bundled local asset
 * `assets/louis/louis_avatar.png` so the photo always resolves regardless
 * of network / CORS. Remote `imageUrl` overrides still work if caller
 * provides one (used for coach-provided custom photos in future). Initials
 * remain the final fallback.
 *
 * Usage:
 *   <LouisAvatar size={40} />
 *   <LouisAvatar size={56} showRing />
 *   <LouisAvatar size={28} initials="AR" imageUrl={otherUri} />
 */
import React, { useState } from "react";
import { View, Text, Image, StyleSheet } from "react-native";
import { theme } from "@/src/lib/theme";
import { LOUIS } from "@/src/lib/coachProfile";

// Bundled local asset — same file used by DailyBriefingModal + WeeklyReviewCard.
const LOUIS_LOCAL = require("../../assets/louis/louis_avatar.png");

export function LouisAvatar({
  size = 40,
  showRing = false,
  initials,
  imageUrl,
}: {
  size?: number;
  showRing?: boolean;
  initials?: string;
  imageUrl?: string | null;
}) {
  const [failed, setFailed] = useState(false);
  const label = (initials ?? LOUIS.initials).toUpperCase();
  // If a specific remote imageUrl was passed, honour it (e.g. a coach
  // profile customisation). Otherwise use the reliable bundled asset.
  const remoteSource = imageUrl ? { uri: imageUrl } : null;
  const source = remoteSource || LOUIS_LOCAL;
  const canShowImage = !failed;

  const containerStyle = [
    styles.wrap,
    {
      width: size,
      height: size,
      borderRadius: size / 2,
      borderWidth: showRing ? 2 : 0,
      borderColor: theme.color.brand,
    },
  ];

  return (
    <View style={containerStyle} testID="louis-avatar">
      {canShowImage ? (
        <Image
          source={source}
          style={{ width: "100%", height: "100%" }}
          resizeMode="cover"
          onError={() => setFailed(true)}
        />
      ) : (
        <View style={[styles.initialsWrap, { width: size, height: size }]}>
          <Text
            style={[
              styles.initialsText,
              { fontSize: Math.max(11, Math.round(size * 0.38)) },
            ]}
          >
            {label}
          </Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    overflow: "hidden",
    backgroundColor: theme.color.surface2,
    alignItems: "center",
    justifyContent: "center",
  },
  initialsWrap: {
    backgroundColor: theme.color.brandTint,
    alignItems: "center",
    justifyContent: "center",
  },
  initialsText: {
    color: theme.color.brand,
    fontWeight: "900",
    letterSpacing: 1,
  },
});
