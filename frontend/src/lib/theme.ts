export const theme = {
  color: {
    // Surfaces (deep black to match logo backdrop)
    surface: "#000000",
    surface2: "#0E0E12",
    surface3: "#1A1A20",
    border: "#22222A",
    borderStrong: "#333340",
    divider: "#141419",
    text: "#F3F4F6",
    /** Alias — high-contrast text (used by V2 components). Same as `text`. */
    textHi: "#F3F4F6",
    /** Alias — page background (used by V2 components). Same as `surface`. */
    bg: "#000000",
    textMuted: "#9CA3AF",
    textDim: "#6B7280",
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
  space: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32, xxxl: 48 },
  radius: { sm: 4, md: 8, lg: 12, pill: 999 },
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
