/**
 * Iter169 · Dual-theme palette (Dark + Light).
 * `theme.color` starts as DARK. On boot we read AsyncStorage and, if the
 * user has opted into light mode, we MUTATE the exported `theme.color`
 * object in place before StyleSheets are created. Toggling at runtime
 * mutates the same object AND emits a change event so the app can
 * choose to reload (recommended for a clean switch).
 */
export type ThemeMode = "dark" | "light";

export const DARK_PALETTE = {
  // Iter174 · MANDATORY UI RESTORATION — locked palette per PRD.
  //   bg / surface  : #0B0B0D  (Deep Black)   — page background
  //   surface2/card : #1E1E1E  (Charcoal)     — visible card elevation
  //   text / textHi : #FFFFFF  (Pure White)   — ensures names like
  //                                             "PIETRO" render legibly
  //   onBrand/onRed : #FFFFFF                  — text/icons on brand-red
  surface: "#0B0B0D",
  surface2: "#1E1E1E",
  surface3: "#242427",
  border: "#2C2C2E",
  borderStrong: "#3A3A3E",
  divider: "#1E1E22",
  text: "#FFFFFF",
  textHi: "#FFFFFF",
  bg: "#0B0B0D",
  // Iter186 · Alias — some legacy screens reference `theme.color.background`
  // instead of `.bg`. Without this alias, styles set to undefined which
  // renders TRANSPARENT on Android → user sees the OS window (BLACK) during
  // route transitions (signup → training-setup → assessment). Point the
  // alias at `bg` so those styles paint correctly with zero migration risk.
  background: "#0B0B0D",
  bgGradientTop: "#000000",
  bgGradientBottom: "#0B0B0D",
  // Iter178 · PURE RULE — no grey text. All muted tokens collapse to
  // pure white in Dark Mode so nothing renders as low-contrast grey.
  textMuted: "#FFFFFF",
  textDim: "#FFFFFF",
  textSoft: "#FFFFFF",
  card: "#1E1E1E",
  brand: "#A3182E",
  brandDark: "#7A1122",
  brandTint: "#2A0810",
  brandGlow: "#C42239",
  onBrand: "#FFFFFF",
  // Iter173 · Text/icon color for on-red surfaces (same in both modes).
  onRed: "#FFFFFF",
  onBrandMuted: "#FFFFFF",
  // Iter178 · Semantic "button inside a card" tokens.
  //   Dark Mode  : PRIMARY buttons on the page use brand-red bg.
  //   Both modes : buttons INSIDE a red card use black bg + white text.
  cardBtnBg: "#000000",
  cardBtnText: "#FFFFFF",
  primaryBtnBg: "#A3182E",
  primaryBtnText: "#FFFFFF",
  green: "#10B981",
  amber: "#F59E0B",
  red: "#EF4444",
  info: "#FFFFFF",
  navy: "#0A1220",
  navySoft: "#101828",
} as const;

export const LIGHT_PALETTE = {
  // Iter174 · MANDATORY UI RESTORATION — locked palette per PRD.
  //   bg / surface   : #FFFFFF (Pure White)  — page background
  //   surface2/card  : #A3182E (Brand Red)   — every card sits on red
  //   onRed/onBrand  : #FFFFFF               — text/icons on red MUST
  //                                            use this token so cards
  //                                            never render red-on-red
  //   text / textHi  : #000000               — primary black text on
  //                                            the white page background
  surface: "#FFFFFF",
  surface2: "#A3182E",
  surface3: "#7A1122",
  border: "#D4D4DC",
  borderStrong: "#B8B8C4",
  divider: "#E5E5EC",
  text: "#000000",
  textHi: "#000000",
  bg: "#FFFFFF",
  // Iter186 · Alias mirror in Light Mode (see DARK_PALETTE above).
  background: "#FFFFFF",
  bgGradientTop: "#FFFFFF",
  bgGradientBottom: "#F4F4F9",
  // Iter178 · PURE RULE — no grey text in Light Mode either.
  //   textMuted / Dim / Soft = #000000 when on the white page bg
  //   Text INSIDE a red card is `theme.color.onRed` (#FFFFFF) — set
  //   explicitly on each card-interior style, never inherited from
  //   these muted tokens.
  textMuted: "#000000",
  textDim: "#000000",
  textSoft: "#000000",
  card: "#A3182E",
  brand: "#A3182E",
  brandDark: "#7A1122",
  brandTint: "#FBE3E7",
  brandGlow: "#C42239",
  // Iter174 · Every card sits on brand red — text on red MUST use
  // `theme.color.onBrand` / `theme.color.onRed`.
  onBrand: "#FFFFFF",
  onRed: "#FFFFFF",
  onBrandMuted: "#FFFFFF",
  // Iter178 · Semantic button tokens (see DARK_PALETTE comment).
  cardBtnBg: "#000000",
  cardBtnText: "#FFFFFF",
  primaryBtnBg: "#A3182E",
  primaryBtnText: "#FFFFFF",
  green: "#047857",
  amber: "#B45309",
  red: "#B91C1C",
  info: "#000000",
  navy: "#0A1220",
  navySoft: "#1F2937",
} as const;

/* --------------------------------------------------------------------------
 * Iter175 · SYNCHRONOUS palette pick at module init.
 *
 * Every `StyleSheet.create({ backgroundColor: theme.color.surface })` bakes
 * the hex STRING at import time. If we wait for AsyncStorage (async), all
 * stylesheets across the app get frozen to the DARK default before the
 * user's saved preference has a chance to apply — which is exactly why
 * names like "PIETRO" render invisible in Light Mode.
 *
 * The fix (Iter176 · native): read the persisted mode SYNCHRONOUSLY on
 * BOTH web and native.
 *   • Web / Expo Web:  `localStorage.getItem` (native sync API).
 *   • iOS / Android:   `expo-secure-store`'s sync `getItem` (added in
 *                      SDK 51). Wrapped in try/catch so a missing
 *                      keychain entry falls through to DARK gracefully.
 * ------------------------------------------------------------------------ */
const _THEME_STORAGE_KEY = "crewfit.theme.mode";

// Lazy-required so the Metro web bundle doesn't fail if the native module
// isn't shimmed there (SecureStore no-ops on web anyway, but the require
// path can throw in some SSR setups).
let _SecureStore: {
  getItem?: (k: string) => string | null;
  setItem?: (k: string, v: string) => void;
} | null = null;
try {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  _SecureStore = require("expo-secure-store");
} catch {
  _SecureStore = null;
}

function _readInitialModeSync(): ThemeMode {
  // 1) Web: localStorage is the AsyncStorage backing on Expo Web. This
  //    remains the primary path in the browser preview.
  try {
    if (typeof globalThis !== "undefined") {
      const ls: Storage | undefined = (globalThis as any).localStorage;
      if (ls && typeof ls.getItem === "function") {
        const raw = ls.getItem(_THEME_STORAGE_KEY);
        if (raw === "light" || raw === "dark") return raw;
      }
    }
  } catch {
    /* ignore */
  }
  // 2) Native (iOS / Android): SecureStore.getItem is fully synchronous
  //    from Expo SDK 51+ and reads straight from the platform keychain
  //    with no bridge round-trip. This unfreezes the theme on physical
  //    devices — StyleSheets across the app now capture the correct
  //    palette on very first module evaluation.
  try {
    if (_SecureStore && typeof _SecureStore.getItem === "function") {
      const raw = _SecureStore.getItem(_THEME_STORAGE_KEY);
      if (raw === "light" || raw === "dark") return raw;
    }
  } catch {
    /* ignore */
  }
  return "dark";
}

// Iter176 · Exported so `useThemeMode` can mirror-write on toggle. Sync
// on both platforms → the value is durable for the very next reload.
export function persistThemeModeSync(mode: ThemeMode): void {
  try {
    if (typeof globalThis !== "undefined") {
      const ls: Storage | undefined = (globalThis as any).localStorage;
      if (ls && typeof ls.setItem === "function") ls.setItem(_THEME_STORAGE_KEY, mode);
    }
  } catch { /* ignore */ }
  try {
    if (_SecureStore && typeof _SecureStore.setItem === "function") {
      _SecureStore.setItem(_THEME_STORAGE_KEY, mode);
    }
  } catch { /* ignore */ }
}

const _INITIAL_MODE: ThemeMode = _readInitialModeSync();
const _INITIAL_PALETTE = _INITIAL_MODE === "light" ? LIGHT_PALETTE : DARK_PALETTE;

export const theme = {
  // Iter175 · Palette is pre-selected SYNCHRONOUSLY (see above) so every
  // StyleSheet.create() call in the codebase captures the CORRECT hex
  // values on its very first evaluation.
  color: { ..._INITIAL_PALETTE } as Record<string, string>,
  // Track current mode so useThemeMode() can read it at boot.
  mode: _INITIAL_MODE,
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
    /** Display / headline — Creo (licensed). Key uses a SPACE (not hyphen)
     *  to match the expo-font config plugin registration in app.json so
     *  production builds resolve the family reliably. */
    display: "Creo ExtraBold",
    displayLight: "Creo ExtraLight",
    /** Body — Source Sans 3 */
    text: "SourceSans3-Regular",
    textSemi: "SourceSans3-SemiBold",
    textBold: "SourceSans3-Bold",
  },
  /**
   * Iter168 · Global typography weights.
   *   hero    (900) — reserved for ONE hero title per screen.
   *   header  (800) — section headers / eyebrow labels / primary CTAs.
   *   strong  (700) — meta labels / prominent secondary text.
   *   body    (600) — default body copy.
   *
   * Ensure no font in the app is smaller than `size.xxs` (11pt).
   */
  weight: {
    hero:   "900" as const,
    header: "800" as const,
    strong: "700" as const,
    body:   "600" as const,
  },
};

/* -------------------------------------------------------------------------- */
/*  Iter169 · Runtime theme switching                                          */
/* -------------------------------------------------------------------------- */

// Listeners subscribed via `subscribeThemeMode`. Called after every mutation.
const _themeListeners: Array<(mode: ThemeMode) => void> = [];

/** Read the current theme mode. */
export function getThemeMode(): ThemeMode {
  return (theme as any).mode as ThemeMode;
}

/** Change the theme mode. Mutates `theme.color` in place AND notifies
 *  listeners so any React component using `useThemeMode()` re-renders.
 *  Note: existing StyleSheet.create() calls that captured colours at
 *  first-render time will keep their old values until the JS bundle
 *  reloads. Restart the app to fully repaint. */
export function setThemeMode(mode: ThemeMode): void {
  const palette = mode === "light" ? LIGHT_PALETTE : DARK_PALETTE;
  // In-place mutation so any reference to `theme.color.xxx` in a running
  // component gets the new value on next render.
  for (const k of Object.keys(palette)) {
    (theme.color as any)[k] = (palette as any)[k];
  }
  (theme as any).mode = mode;
  for (const fn of _themeListeners) {
    try { fn(mode); } catch { /* ignore */ }
  }
}

/** Subscribe to theme changes. Returns an unsubscribe function. */
export function subscribeThemeMode(fn: (mode: ThemeMode) => void): () => void {
  _themeListeners.push(fn);
  return () => {
    const i = _themeListeners.indexOf(fn);
    if (i >= 0) _themeListeners.splice(i, 1);
  };
}

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
