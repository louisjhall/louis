export const theme = {
  color: {
    surface: "#0F0F13",
    surface2: "#1C1C22",
    surface3: "#272730",
    border: "#272730",
    borderStrong: "#3F3F4E",
    divider: "#1C1C22",
    text: "#F3F4F6",
    textMuted: "#9CA3AF",
    textDim: "#6B7280",
    brand: "#E85D04",
    brandDark: "#DC4F00",
    brandTint: "#361D0C",
    onBrand: "#FFFFFF",
    green: "#10B981",
    amber: "#F59E0B",
    red: "#EF4444",
    info: "#6B7280",
  },
  space: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32, xxxl: 48 },
  radius: { sm: 4, md: 8, lg: 12, pill: 999 },
  font: {
    display: "System",
    text: "System",
  },
} as const;

export const loadColor = (l?: string) => {
  switch (l) {
    case "green":
      return theme.color.green;
    case "amber":
      return theme.color.amber;
    case "red":
      return theme.color.red;
    default:
      return theme.color.info;
  }
};

export const loadLabel = (l?: string) => (l ? l.toUpperCase() : "—");
