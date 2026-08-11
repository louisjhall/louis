/**
 * PreferencesTogglesCard — Iter169
 *
 * Two client-side preference toggles, shipped inside the Profile ▸
 * Preferences & Account accordion:
 *
 *   1. Theme    · Dark / Light (persisted via useThemeMode)
 *   2. Hide Flight Support · when ON, hides the TodayFlightSupport card
 *      on the Today tab (persisted in AsyncStorage under a well-known
 *      key that other screens can also read).
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, Platform } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";
import { useThemeMode } from "@/src/hooks/use-theme-mode";

export const HIDE_FLIGHT_SUPPORT_KEY = "crewfit.pref.hideFlightSupport";

/** Read the current flight-support preference (best-effort). */
export async function getHideFlightSupport(): Promise<boolean> {
  try {
    const v = await AsyncStorage.getItem(HIDE_FLIGHT_SUPPORT_KEY);
    return v === "1";
  } catch {
    return false;
  }
}

export function PreferencesTogglesCard() {
  const { mode, setMode } = useThemeMode();
  const [hideFS, setHideFS] = useState(false);

  useEffect(() => {
    getHideFlightSupport().then(setHideFS);
  }, []);

  const toggleHideFS = useCallback(() => {
    setHideFS((prev) => {
      const next = !prev;
      AsyncStorage.setItem(HIDE_FLIGHT_SUPPORT_KEY, next ? "1" : "0").catch(() => {});
      return next;
    });
  }, []);

  return (
    <View style={styles.card} testID="preferences-toggles-card">
      <Text style={styles.eyebrow}>APP PREFERENCES</Text>

      {/* Theme picker · Dark / Light */}
      <View style={styles.row} testID="pref-row-theme">
        <View style={styles.iconWrap}>
          <Ionicons
            name={mode === "dark" ? "moon" : "sunny"}
            size={16}
            color={theme.color.brand}
          />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.rowT}>THEME</Text>
          <Text style={styles.rowSub}>
            {mode === "dark" ? "Dark mode · black background" : "Light mode · white background"}
          </Text>
        </View>
        <View style={styles.segmented}>
          <Pressable
            testID="pref-theme-dark"
            onPress={() => setMode("dark")}
            style={[styles.segBtn, mode === "dark" && styles.segBtnActive]}
          >
            <Text style={[styles.segBtnT, mode === "dark" && styles.segBtnTActive]}>DARK</Text>
          </Pressable>
          <Pressable
            testID="pref-theme-light"
            onPress={() => setMode("light")}
            style={[styles.segBtn, mode === "light" && styles.segBtnActive]}
          >
            <Text style={[styles.segBtnT, mode === "light" && styles.segBtnTActive]}>LIGHT</Text>
          </Pressable>
        </View>
      </View>

      <Text style={styles.helperT}>
        Theme switches instantly. For a fully-repainted UI you may want to
        {" "}force-close and reopen the app{Platform.OS === "web" ? "" : " (some cached surfaces need a restart)"}.
      </Text>

      {/* Hide flight support toggle */}
      <View style={styles.row} testID="pref-row-hide-flight">
        <View style={styles.iconWrap}>
          <Ionicons name="airplane" size={16} color={theme.color.brand} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.rowT}>HIDE FLIGHT SUPPORT</Text>
          <Text style={styles.rowSub}>
            Hides the operational Flight Support card on Today
          </Text>
        </View>
        <Pressable
          testID="pref-hide-flight-toggle"
          onPress={toggleHideFS}
          style={[styles.pill, hideFS && styles.pillOn]}
        >
          <View style={[styles.pillKnob, hideFS && styles.pillKnobOn]} />
        </Pressable>
      </View>

      {/* Placeholder toggle hook: theme fully working. Toggle above just
          persists a local pref — <TodayFlightSupport /> reads it on
          each mount. */}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    marginTop: 8,
    padding: 14,
    gap: 12,
    borderRadius: 12,
    backgroundColor: theme.color.surface2,
    borderWidth: 1,
    borderColor: theme.color.border,
  },
  eyebrow: {
    color: theme.color.brand,
    fontSize: 11,
    letterSpacing: 2,
    fontWeight: "800",
    fontFamily: theme.font.textSemi,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    minHeight: 48,
  },
  iconWrap: {
    width: 32, height: 32, borderRadius: 16,
    backgroundColor: theme.color.brandTint,
    borderWidth: 1, borderColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
  },
  rowT: {
    color: theme.color.text,
    fontSize: 13,
    fontWeight: "800",
    letterSpacing: 1,
    fontFamily: theme.font.textSemi,
  },
  rowSub: {
    color: theme.color.textMuted,
    fontSize: 11,
    fontWeight: "600",
    marginTop: 2,
  },
  helperT: {
    color: theme.color.textDim,
    fontSize: 11,
    lineHeight: 15,
    marginTop: -4,
  },
  segmented: {
    flexDirection: "row",
    borderWidth: 1,
    borderColor: theme.color.border,
    borderRadius: 8,
    overflow: "hidden",
  },
  segBtn: {
    paddingHorizontal: 10, paddingVertical: 6,
    backgroundColor: "transparent",
  },
  segBtnActive: {
    backgroundColor: theme.color.brand,
  },
  segBtnT: {
    color: theme.color.textMuted, fontSize: 11, fontWeight: "800", letterSpacing: 1.2,
  },
  segBtnTActive: {
    color: "#fff",
  },
  pill: {
    width: 42, height: 24,
    borderRadius: 12,
    backgroundColor: theme.color.surface3,
    justifyContent: "center",
    borderWidth: 1, borderColor: theme.color.border,
    padding: 2,
  },
  pillOn: {
    backgroundColor: theme.color.brand,
    borderColor: theme.color.brand,
  },
  pillKnob: {
    width: 18, height: 18, borderRadius: 9,
    backgroundColor: "#fff",
  },
  pillKnobOn: {
    alignSelf: "flex-end",
  },
});
