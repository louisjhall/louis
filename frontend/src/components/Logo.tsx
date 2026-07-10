import React from "react";
import { View, StyleSheet, Image, ImageStyle, StyleProp } from "react-native";

/**
 * CrewFit logo variants.
 *
 *  - `<CrewFitLogo />` — full square lockup (wings + CREWFIT wordmark on transparent bg)
 *  - `<CrewFitWings />` — wings-only mark, ideal for compact headers
 *  - `<CrewFitWordmark />` — wings-only mark placed inline; identical to CrewFitWings
 *    but exported under the old name for backwards compatibility.
 *
 *  Source: `assets/images/crewfit-logo.png` (transparent background, black bg stripped).
 */

type Props = {
  size?: number;
  style?: StyleProp<ImageStyle>;
  tint?: string;                    // optional tint colour
};

export function CrewFitLogo({ size = 96, style, tint }: Props) {
  return (
    <Image
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      source={require("../../assets/images/crewfit-logo.png")}
      resizeMode="contain"
      style={[{ width: size, height: size }, tint ? { tintColor: tint } : null, style]}
      accessibilityLabel="CrewFit logo"
    />
  );
}

export function CrewFitWings({ size = 32, style, tint }: Props) {
  return (
    <Image
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      source={require("../../assets/images/crewfit-wings.png")}
      resizeMode="contain"
      style={[{ width: size, height: Math.round(size * 0.6) }, tint ? { tintColor: tint } : null, style]}
      accessibilityLabel="CrewFit wings"
    />
  );
}

/** Kept for backwards compatibility. Renders the wings-only mark. */
export function CrewFitWordmark({ size = 26, showMark = true, style }: { size?: number; showMark?: boolean; style?: any }) {
  // `showMark` retained as a no-op prop — we now always use the wings.
  void showMark;
  return (
    <View style={[styles.row, style]}>
      <CrewFitWings size={size * 3.2} />
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center" },
});
