import React from "react";
import { View, Text, StyleSheet, Image } from "react-native";
import { theme } from "@/src/lib/theme";

// The full-color CrewFit logo (wings + wordmark), sized to whatever height you pass.
// The image is designed on a black backdrop, so we render it directly.
export function CrewFitLogo({ size = 96, style }: { size?: number; style?: any }) {
  return (
    <Image
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      source={require("../../assets/images/crewfit-logo.png")}
      resizeMode="contain"
      style={[{ width: size, height: size }, style]}
      accessibilityLabel="CrewFit logo"
    />
  );
}

// A tighter wordmark: shows the wings mark on the left with red "CREW" + white "FIT" text.
// Useful in headers where a full square logo would waste vertical space.
export function CrewFitWordmark({ size = 22, showMark = true, style }: { size?: number; showMark?: boolean; style?: any }) {
  return (
    <View style={[styles.row, style]}>
      {showMark ? (
        <Image
          // eslint-disable-next-line @typescript-eslint/no-require-imports
          source={require("../../assets/images/crewfit-logo-sm.png")}
          resizeMode="contain"
          style={{ width: size * 1.4, height: size * 1.4, marginRight: 6 }}
          accessibilityLabel="CrewFit"
        />
      ) : null}
      <Text style={[styles.wordCrew, { fontSize: size }]}>CREW</Text>
      <Text style={[styles.wordFit, { fontSize: size }]}>FIT</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center" },
  wordCrew: { color: theme.color.brand, fontWeight: "900", letterSpacing: 2 },
  wordFit: { color: theme.color.text, fontWeight: "900", letterSpacing: 2 },
});
