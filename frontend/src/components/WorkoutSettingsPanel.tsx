/**
 * Compact workout preferences panel — used inside the client profile screen.
 * Reads and writes 4 settings (sound, haptics, auto rest, auto continue) via AsyncStorage.
 */
import React from "react";
import { View, Text, Pressable, StyleSheet, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";
import { useWorkoutSettings } from "@/src/lib/workoutMode";
import { hapticSelection } from "@/src/lib/haptics";

export function WorkoutSettingsPanel() {
  const { settings, update, loading } = useWorkoutSettings();

  if (loading) {
    return (
      <View style={styles.card}>
        <ActivityIndicator color={theme.color.brand} />
      </View>
    );
  }

  const rows: Array<{ key: keyof typeof settings; label: string; hint: string; icon: any }> = [
    { key: "sound", label: "Workout Sounds", hint: "Soft cues at rest end and set complete.", icon: "volume-medium" },
    { key: "haptics", label: "Haptics", hint: "Vibration on 3-2-1 and set complete (mobile only).", icon: "phone-portrait" },
    { key: "autoRest", label: "Auto Rest Timer", hint: "Start the rest timer automatically after each set.", icon: "timer" },
    { key: "autoContinue", label: "Auto Continue After Rest", hint: "Jump straight to the next set when rest ends.", icon: "play-forward" },
  ];

  return (
    <View style={styles.wrap}>
      <Text style={styles.eyebrow}>WORKOUT PREFERENCES</Text>
      <View style={styles.card}>
        {rows.map((r, i) => {
          const on = settings[r.key];
          return (
            <Pressable
              key={r.key}
              onPress={async () => { hapticSelection(); await update({ [r.key]: !on } as any); }}
              style={[styles.row, i < rows.length - 1 && styles.rowBorder]}
              testID={`setting-${r.key}`}
            >
              <View style={styles.rowIcon}>
                <Ionicons name={r.icon} size={16} color={theme.color.brand} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.rowLabel}>{r.label}</Text>
                <Text style={styles.rowHint}>{r.hint}</Text>
              </View>
              <Switch value={on} />
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

function Switch({ value }: { value: boolean }) {
  return (
    <View style={[styles.switch, value && styles.switchOn]}>
      <View style={[styles.knob, value && styles.knobOn]} />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { marginTop: 16 },
  eyebrow: { color: theme.color.brand, fontSize: 9, fontWeight: "900", letterSpacing: 2, marginBottom: 8, marginLeft: 4 },
  card: {
    backgroundColor: theme.color.surface2,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: theme.color.border,
    overflow: "hidden",
  },
  row: { flexDirection: "row", alignItems: "center", gap: 12, padding: 14 },
  rowBorder: { borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  rowIcon: {
    width: 34, height: 34, borderRadius: 17,
    backgroundColor: theme.color.brandTint,
    borderWidth: 1, borderColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
  },
  rowLabel: { color: theme.color.text, fontSize: 13, fontWeight: "800" },
  rowHint: { color: theme.color.textMuted, fontSize: 11, marginTop: 2, lineHeight: 15 },
  switch: {
    width: 44, height: 26, borderRadius: 13,
    backgroundColor: theme.color.surface3,
    borderWidth: 1, borderColor: theme.color.border,
    padding: 2, justifyContent: "center",
  },
  switchOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  knob: { width: 20, height: 20, borderRadius: 10, backgroundColor: "#fff" },
  knobOn: { marginLeft: "auto" },
});
