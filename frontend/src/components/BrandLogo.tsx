/**
 * BrandLogo — Iter169
 *
 * Renders the CrewFit master logo, automatically swapping the asset
 * based on the current theme mode:
 *   · Dark mode  → white-text logo (crewfit-logo-full.png)
 *   · Light mode → black-text logo (crewfit-logo-full-dark.png)
 *
 * TODO(brand-assets): Drop `crewfit-logo-full-dark.png` into
 * `assets/images/` (same 512×160 dimensions as the white version).
 * Until then, the light-mode branch falls back to the white logo tinted
 * black via <Image tintColor> so the header still reads on a white
 * background — will look flat but is legible.
 */
import React from "react";
import { Image } from "expo-image";
import type { ImageStyle } from "react-native";
import { useThemeMode } from "@/src/hooks/use-theme-mode";

// Both requires MUST be static so Metro can bundle them.
const LOGO_DARK  = require("@/assets/images/crewfit-logo-full.png");
// The dark asset does not exist yet — reference the same file and rely
// on tintColor to darken it on light mode. When the real asset ships,
// change this line to `require("@/assets/images/crewfit-logo-full-dark.png")`.
const LOGO_LIGHT = require("@/assets/images/crewfit-logo-full.png");

export function BrandLogo({
  style,
  accessibilityLabel = "CrewFit",
}: {
  style?: ImageStyle;
  accessibilityLabel?: string;
}) {
  const { mode } = useThemeMode();
  const isLight = mode === "light";
  return (
    <Image
      source={isLight ? LOGO_LIGHT : LOGO_DARK}
      style={style}
      contentFit="contain"
      accessibilityLabel={accessibilityLabel}
      // Iter169 · Temporary tint until the dedicated black-text logo lands.
      tintColor={isLight ? "#000000" : undefined}
    />
  );
}
