/**
 * LouisAvatar — circular avatar with graceful fallback to "LH" initials.
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
  const uri = imageUrl ?? LOUIS.avatarUrl;
  const label = (initials ?? LOUIS.initials).toUpperCase();
  const canShowImage = !!uri && !failed;

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
          source={{ uri }}
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
