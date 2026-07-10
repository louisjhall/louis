// Brand font loader: loads Source Sans 3 (body) + Creo (display) via expo-font.
// Fonts live at /app/frontend/assets/fonts. Only loaded once at app boot.

import { useFonts } from "expo-font";

export const BRAND_FONTS = {
  // Body / UI — Source Sans 3
  "SourceSans3-Regular":  require("../../assets/fonts/SourceSans3-Regular.ttf"),
  "SourceSans3-SemiBold": require("../../assets/fonts/SourceSans3-SemiBold.ttf"),
  "SourceSans3-Bold":     require("../../assets/fonts/SourceSans3-Bold.ttf"),
  // Display / Headline — Creo (licensed)
  "Creo-ExtraBold":  require("../../assets/fonts/CreoExtraBold.ttf"),
  "Creo-ExtraLight": require("../../assets/fonts/CreoExtraLight.ttf"),
} as const;

/** Reads as `[loaded, error]`. Non-blocking — App can still render if this fails. */
export const useBrandFonts = (): readonly [boolean, Error | null] =>
  useFonts(BRAND_FONTS as any);
