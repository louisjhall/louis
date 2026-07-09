/**
 * TimeZoneConfirmModal — one-time prompt on first client launch that detects the device
 * IANA time zone and asks the client to confirm or override. Persisted to /user/timezone-prefs
 * so we never ask again.
 */
import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, Modal, Pressable, TextInput, Alert, ScrollView } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

const ASKED_KEY = "crewfit.timezone.asked";

const COMMON_TZ = [
  "Europe/London", "Europe/Amsterdam", "Europe/Paris", "Europe/Madrid",
  "Asia/Dubai", "Asia/Qatar", "Asia/Riyadh", "Asia/Singapore",
  "Asia/Tokyo", "Asia/Hong_Kong", "Australia/Sydney",
  "America/New_York", "America/Chicago", "America/Los_Angeles",
];

export function TimeZoneConfirmModal({ user }: { user: any }) {
  const [visible, setVisible] = useState(false);
  const [detected, setDetected] = useState<string>("Europe/London");
  const [manual, setManual] = useState<string>("");
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    (async () => {
      if (!user || user.home_time_zone) return; // already set
      const asked = await AsyncStorage.getItem(ASKED_KEY);
      if (asked === "1") return;
      let tz = "Europe/London";
      try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone || tz; } catch { /* ignore */ }
      setDetected(tz); setManual(tz); setVisible(true);
    })();
  }, [user]);

  const save = async (tz: string) => {
    try {
      await api<any>("/user/timezone-prefs", { method: "PUT", body: { home_time_zone: tz, current_time_zone: tz } });
      await AsyncStorage.setItem(ASKED_KEY, "1");
      setVisible(false);
    } catch (e: any) {
      Alert.alert("Could not save", e?.message || "");
    }
  };

  if (!visible) return null;
  return (
    <Modal visible transparent animationType="slide" onRequestClose={() => setVisible(false)}>
      <View style={styles.root}>
        <Pressable style={styles.backdrop} onPress={() => setVisible(false)} />
        <View style={styles.sheet}>
          <View style={styles.head}>
            <Ionicons name="globe" size={22} color={theme.color.brand} />
            <Text style={styles.eyebrow}>YOUR TIME ZONE</Text>
          </View>
          <Text style={styles.q}>Your time zone appears to be</Text>
          <Text style={styles.tzDetected}>{detected}</Text>
          <Text style={styles.hint}>
            We use this to schedule your Sunday check-in and reminders at the right local time.
            You can change this later in your profile.
          </Text>

          {!editing ? (
            <>
              <Pressable onPress={() => save(detected)} style={styles.primary} testID="tz-confirm">
                <Text style={styles.primaryT}>YES, USE THIS</Text>
              </Pressable>
              <Pressable onPress={() => setEditing(true)} style={styles.secondary} testID="tz-change">
                <Text style={styles.secondaryT}>CHANGE TIME ZONE</Text>
              </Pressable>
            </>
          ) : (
            <>
              <ScrollView style={styles.pickerList}>
                {COMMON_TZ.map((tz) => (
                  <Pressable key={tz} onPress={() => setManual(tz)} style={[styles.tzRow, manual === tz && styles.tzRowOn]}>
                    <Text style={[styles.tzRowT, manual === tz && { color: theme.color.brand, fontWeight: "900" }]}>{tz}</Text>
                    {manual === tz && <Ionicons name="checkmark" size={16} color={theme.color.brand} />}
                  </Pressable>
                ))}
              </ScrollView>
              <TextInput
                value={manual}
                onChangeText={setManual}
                placeholder="Or type an IANA name (e.g. Europe/Zurich)"
                placeholderTextColor={theme.color.textDim}
                style={styles.tzInput}
              />
              <Pressable onPress={() => save(manual)} style={styles.primary} testID="tz-save">
                <Text style={styles.primaryT}>SAVE</Text>
              </Pressable>
            </>
          )}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, justifyContent: "flex-end" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.55)" },
  sheet: { backgroundColor: theme.color.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: 20 },
  head: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 14 },
  eyebrow: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  q: { color: theme.color.textMuted, fontSize: 13, marginBottom: 6 },
  tzDetected: { color: theme.color.text, fontSize: 22, fontWeight: "900", marginBottom: 10 },
  hint: { color: theme.color.textMuted, fontSize: 12, marginBottom: 20, lineHeight: 17 },
  primary: { padding: 14, borderRadius: 12, backgroundColor: theme.color.brand, alignItems: "center", marginBottom: 8 },
  primaryT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 2 },
  secondary: { padding: 12, borderRadius: 12, alignItems: "center", borderWidth: 1, borderColor: theme.color.border },
  secondaryT: { color: theme.color.text, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  pickerList: { maxHeight: 260, marginBottom: 10 },
  tzRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 12, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  tzRowOn: { backgroundColor: theme.color.brandTint },
  tzRowT: { color: theme.color.text, fontSize: 13 },
  tzInput: { padding: 12, borderRadius: 8, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, color: theme.color.text, marginBottom: 12 },
});
