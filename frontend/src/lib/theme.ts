export const theme = {
  color: {
    // Surfaces — dark charcoal gray for the refreshed dashboard (Iter 151).
    // Previously #000000 (pure black) — softened to #121212 for better
    // readability and less harsh contrast.
    surface: "#121212",
    surface2: "#0E0E12",
    surface3: "#1A1A20",
    // Iter 162 · Premium V2 — neutral dark gray for card borders.
    // Reserves red exclusively for primary CTAs and critical alerts;
    // ambient outlines/dividers switch to this subtle mid-gray.
    border: "#2C2C2E",
    borderStrong: "#3A3A3E",
    divider: "#1E1E22",
    text: "#F3F4F6",
    /** Alias — high-contrast text (used by V2 components). Same as `text`. */
    textHi: "#F3F4F6",
    /** Alias — page background (used by V2 components). Charcoal gray. */
    bg: "#121212",
    /** Iter 162 · Gradient stops for the app root — pure black at the top of
     *  the viewport fading into the charcoal card surface at the bottom.
     *  Applied via <LinearGradient/> in each screen root. */
    bgGradientTop: "#000000",
    bgGradientBottom: "#121212",
    textMuted: "#9CA3AF",
    textDim: "#6B7280",
    /** Iter 162 · Secondary/tertiary text tone — softer gray used for meta
     *  lines, timestamps, and dim captions per the Premium V2 spec. */
    textSoft: "#8E8E93",
    /** Alias — elevated card background (used by V2 + manual builder). */
    card: "#0E0E12",
    // Brand — CrewFit crimson wings on black
    brand: "#A3182E",
    brandDark: "#7A1122",
    brandTint: "#2A0810",
    brandGlow: "#C42239",
    onBrand: "#FFFFFF",
    green: "#10B981",
    amber: "#F59E0B",
    red: "#EF4444",
    info: "#6B7280",
    // Deep aviation navy for premium cards
    navy: "#0A1220",
    navySoft: "#101828",
  },
  space: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32, xxxl: 48,
           /** Iter 162 · Section gap between major dashboard blocks. */
           section: 20 },
  radius: { sm: 4, md: 8, lg: 12, pill: 999,
            /** Iter 162 · Card corner radius across the redesigned dashboard. */
            card: 16 },
  /**
   * Font-size scale (Iter 151 — dashboard refresh, tuned Iter 162 Premium V2).
   * `base` is 16px enforced app-wide via defaultProps on `<Text>`.
   *   base:  16 — body copy
   *   sm:    14 — secondary info / captions
   *   lg:    18 — sub-section titles
   *   xl:    20 — section headers (bold)
   *   xxl:   28 — hero / dashboard names
   */
  size: {
    xxs: 11,
    xs: 12,
    sm: 14,
    base: 16,
    lg: 18,
    xl: 20,
    xxl: 28,
    display: 32,
  },
  font: {
    /** Display / headline — Creo (licensed). Falls back to system if font not yet loaded. */
    display: "Creo-ExtraBold",
    displayLight: "Creo-ExtraLight",
    /** Body — Source Sans 3 */
    text: "SourceSans3-Regular",
    textSemi: "SourceSans3-SemiBold",
    textBold: "SourceSans3-Bold",
  },
} as const;

export const loadColor = (l?: string) => {
  switch (l) {
    case "green": return theme.color.green;
    case "amber": return theme.color.amber;
    case "red": return theme.color.red;
    case "blue": return "#3B82F6";
    case "purple": return "#A855F7";
    case "grey": return theme.color.textDim;
    default: return theme.color.info;
  }
};

export const loadLabel = (l?: string) => (l ? l.toUpperCase() : "—");
