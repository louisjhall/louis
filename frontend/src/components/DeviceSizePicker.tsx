/**
 * DeviceSizePicker — web-only helper that renders 5 preset widths so a
 * coach can eyeball layouts at different screen sizes. Sets a CSS variable
 * on the <html> element which we read from ClientPreviewFrame.
 */
import React, { useEffect, useState } from "react";
import { View, Text, Pressable, StyleSheet, Platform } from "react-native";

const SIZES: { key: string; label: string; width: number }[] = [
  { key: "iphone-se", label: "375", width: 375 },
  { key: "iphone", label: "390", width: 390 },
  { key: "iphone-max", label: "414", width: 414 },
  { key: "tablet", label: "768", width: 768 },
  { key: "desktop", label: "1200", width: 1200 },
];

export function DeviceSizePicker() {
  const [current, setCurrent] = useState<number | null>(null);

  useEffect(() => {
    if (Platform.OS !== "web") return;
    // Read persisted preference
    try {
      const stored = window.localStorage.getItem("cf_preview_width");
      if (stored) {
        const w = parseInt(stored, 10);
        setCurrent(w);
        applyWidth(w);
      }
    } catch {}
  }, []);

  const applyWidth = (w: number | null) => {
    if (Platform.OS !== "web") return;
    try {
      if (w) {
        document.documentElement.style.setProperty("--cf-preview-width", `${w}px`);
        window.localStorage.setItem("cf_preview_width", String(w));
      } else {
        document.documentElement.style.removeProperty("--cf-preview-width");
        window.localStorage.removeItem("cf_preview_width");
      }
    } catch {}
  };

  const choose = (w: number | null) => {
    setCurrent(w);
    applyWidth(w);
  };

  if (Platform.OS !== "web") return null;

  return (
    <View style={styles.row}>
      {SIZES.map((s) => (
        <Pressable key={s.key} onPress={() => choose(s.width)} style={[styles.pill, current === s.width && styles.pillActive]} testID={`preview-size-${s.key}`}>
          <Text style={[styles.pillT, current === s.width && styles.pillTActive]}>{s.label}</Text>
        </Pressable>
      ))}
      <Pressable onPress={() => choose(null)} style={[styles.pill, current === null && styles.pillActive]} testID="preview-size-full">
        <Text style={[styles.pillT, current === null && styles.pillTActive]}>FULL</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", gap: 3 },
  pill: { paddingHorizontal: 6, paddingVertical: 3, borderRadius: 4, backgroundColor: "rgba(255,255,255,0.15)" },
  pillActive: { backgroundColor: "#fff" },
  pillT: { color: "#fff", fontSize: 11, fontWeight: "800", letterSpacing: 0.3 },
  pillTActive: { color: "#7f1d1d" },
});
