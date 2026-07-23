/**
 * RosterDayPickerSheet
 * ---------------------
 * Bottom-sheet modal that lets a client quickly correct a roster day's
 * `day_type` (e.g. when the parser flagged a Layover as a Turnaround, or
 * an off-by-one shifted duties by a day).
 *
 * Wired to `PATCH /api/roster/{rid}/day` (see server.py iter 82).
 *
 * UX (per user request):
 *   - Triggered by a LONG-PRESS on any day row in the "Next 7 Days" list.
 *   - Presents the same duty-type chips as the roster/confirm review screen
 *     so the vocabulary stays consistent.
 *   - Shows an "on layover" city input for layover selections.
 *   - Fires a toast on success + calls the passed `onSaved` callback so the
 *     parent can refresh its data.
 */
import { useEffect, useState } from "react";
import {
  Modal, View, Text, StyleSheet, Pressable, KeyboardAvoidingView, Platform,
  ScrollView, ActivityIndicator, TextInput,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import { theme } from "@/src/lib/theme";
import { api } from "@/src/lib/api";
import { toast } from "@/src/lib/ux";

// Keep these keys in sync with roster/confirm/[id].tsx so users see the same
// vocabulary in both places.
const DUTY_TYPES: { key: string; label: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { key: "Flight",         label: "Flight (turnaround)", icon: "airplane" },
  { key: "Direct Flight",  label: "Direct flight",       icon: "paper-plane" },
  { key: "Layover",        label: "Layover",             icon: "bed" },
  { key: "Standby",        label: "Standby",             icon: "time" },
  { key: "Off",            label: "Off duty",            icon: "sunny" },
  { key: "Home",           label: "Home",                icon: "home" },
  { key: "Sim / Training", label: "Sim / Training",      icon: "school" },
  { key: "Sick",           label: "Sick",                icon: "medkit" },
  { key: "Annual Leave",   label: "Annual leave",        icon: "leaf" },
];

export type RosterDayPickerTarget = {
  rosterId: string;
  date: string;               // YYYY-MM-DD
  currentDayType?: string | null;
  currentLayoverCity?: string | null;
};

type Props = {
  target: RosterDayPickerTarget | null;
  onClose: () => void;
  onSaved?: () => void;       // fires on successful PATCH
};

function fmtDate(iso?: string | null): string {
  if (!iso) return "";
  try {
    const d = new Date(iso + "T00:00:00");
    return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
  } catch {
    return iso;
  }
}

export function RosterDayPickerSheet({ target, onClose, onSaved }: Props) {
  const [dayType, setDayType] = useState<string>("");
  const [city, setCity] = useState<string>("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (target) {
      setDayType(target.currentDayType || "");
      setCity(target.currentLayoverCity || "");
    }
  }, [target]);

  const save = async (nextType?: string) => {
    if (!target) return;
    const finalType = (nextType ?? dayType).trim();
    if (!finalType) return;
    setSaving(true);
    try {
      await api(`/roster/${target.rosterId}/day`, {
        method: "PATCH",
        body: {
          date: target.date,
          day_type: finalType,
          layover_city: finalType.toLowerCase() === "layover" ? (city || null) : null,
        },
      });
      try { await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success); } catch {}
      // Iter 94p — Reworded from "Louis will re-check" so the client sees this
      // as their own control, not a coach-review deferral. Workout is re-placed
      // immediately based on the new duty type.
      toast(`${fmtDate(target.date)} updated — your workout has been adjusted to fit.`, "success");
      onSaved?.();
      onClose();
    } catch (e: any) {
      toast(e?.message || "Could not update this day.", "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      visible={!!target}
      animationType="slide"
      transparent
      onRequestClose={onClose}
    >
      <Pressable style={styles.scrim} onPress={onClose}>
        <Pressable style={styles.sheetWrap} onPress={(e) => e.stopPropagation()}>
          <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined}>
            <View style={styles.sheet}>
              <View style={styles.handle} />

              <View style={styles.headerRow}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.eyebrow}>CORRECT YOUR ROSTER</Text>
                  <Text style={styles.title}>{fmtDate(target?.date)}</Text>
                  {target?.currentDayType ? (
                    <Text style={styles.sub}>Currently: {target.currentDayType}</Text>
                  ) : null}
                </View>
                <Pressable
                  testID="roster-day-picker-close"
                  onPress={onClose}
                  hitSlop={12}
                >
                  <Ionicons name="close" size={22} color={theme.color.text} />
                </Pressable>
              </View>

              <Text style={styles.helpText}>
                Tap the correct duty type for this day. Your workout will be
                re-placed to fit — no coach approval needed.
              </Text>

              <ScrollView
                style={{ maxHeight: 340 }}
                contentContainerStyle={styles.grid}
                keyboardShouldPersistTaps="handled"
              >
                {DUTY_TYPES.map((t) => {
                  const active = (dayType || "").toLowerCase() === t.key.toLowerCase();
                  const isLayover = t.key.toLowerCase() === "layover";
                  return (
                    <Pressable
                      key={t.key}
                      testID={`roster-day-picker-${t.key}`}
                      onPress={() => {
                        if (isLayover) {
                          // Layover requires an optional city — reveal the input
                          // and let the user tap SAVE LAYOVER explicitly instead
                          // of auto-firing the PATCH.
                          setDayType(t.key);
                        } else {
                          setDayType(t.key);
                          save(t.key);
                        }
                      }}
                      disabled={saving}
                      style={[styles.chip, active && styles.chipActive, saving && { opacity: 0.6 }]}
                    >
                      <Ionicons
                        name={t.icon}
                        size={14}
                        color={active ? "#fff" : theme.color.textMuted}
                      />
                      <Text style={[styles.chipText, active && { color: "#fff" }]}>{t.label}</Text>
                    </Pressable>
                  );
                })}
              </ScrollView>

              {(dayType || "").toLowerCase() === "layover" ? (
                <View style={{ marginTop: theme.space.md }}>
                  <Text style={styles.editorLabel}>LAYOVER CITY (optional)</Text>
                  <TextInput
                    testID="roster-day-picker-city"
                    style={styles.input}
                    value={city}
                    onChangeText={setCity}
                    placeholder="e.g. Bangkok"
                    placeholderTextColor={theme.color.textDim}
                    autoCapitalize="words"
                  />
                  <Pressable
                    testID="roster-day-picker-save-layover"
                    onPress={() => save()}
                    disabled={saving}
                    style={[styles.saveBtn, saving && { opacity: 0.6 }]}
                  >
                    {saving ? (
                      <ActivityIndicator color="#fff" />
                    ) : (
                      <Text style={styles.saveBtnText}>SAVE LAYOVER</Text>
                    )}
                  </Pressable>
                </View>
              ) : null}

              {saving ? (
                <View style={styles.savingBar}>
                  <ActivityIndicator color={theme.color.brand} />
                  <Text style={styles.savingText}>Updating…</Text>
                </View>
              ) : null}
            </View>
          </KeyboardAvoidingView>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  scrim: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.55)",
    justifyContent: "flex-end",
  },
  sheetWrap: { width: "100%" },
  sheet: {
    backgroundColor: theme.color.surface,
    borderTopLeftRadius: 18,
    borderTopRightRadius: 18,
    padding: theme.space.lg,
    paddingBottom: theme.space.xl,
  },
  handle: {
    alignSelf: "center",
    width: 42,
    height: 4,
    borderRadius: 2,
    backgroundColor: theme.color.border,
    marginBottom: theme.space.md,
  },
  headerRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    marginBottom: theme.space.sm,
  },
  eyebrow: {
    color: theme.color.brand,
    fontSize: 10,
    letterSpacing: 1.5,
    fontWeight: "800",
    marginBottom: 2,
  },
  title: {
    color: theme.color.text,
    fontSize: 18,
    fontWeight: "900",
  },
  sub: {
    color: theme.color.textMuted,
    fontSize: 12,
    marginTop: 2,
  },
  helpText: {
    color: theme.color.textMuted,
    fontSize: 12,
    lineHeight: 17,
    marginBottom: theme.space.md,
  },
  grid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  chip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: theme.radius.pill,
    backgroundColor: theme.color.surface2,
    borderWidth: 1,
    borderColor: theme.color.border,
    minHeight: 44,
  },
  chipActive: {
    backgroundColor: theme.color.brand,
    borderColor: theme.color.brand,
  },
  chipText: {
    color: theme.color.textMuted,
    fontSize: 12,
    fontWeight: "700",
  },
  editorLabel: {
    color: theme.color.brand,
    fontSize: 10,
    letterSpacing: 1.5,
    fontWeight: "800",
    marginBottom: 6,
  },
  input: {
    backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.md,
    color: theme.color.text,
    paddingHorizontal: theme.space.md,
    paddingVertical: 12,
    borderWidth: 1,
    borderColor: theme.color.border,
    fontSize: 14,
  },
  saveBtn: {
    marginTop: theme.space.md,
    backgroundColor: theme.color.brand,
    paddingVertical: 14,
    borderRadius: theme.radius.md,
    alignItems: "center",
    minHeight: 48,
    justifyContent: "center",
  },
  saveBtnText: {
    color: "#fff",
    fontSize: 13,
    fontWeight: "800",
    letterSpacing: 1.5,
  },
  savingBar: {
    marginTop: theme.space.md,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    justifyContent: "center",
  },
  savingText: {
    color: theme.color.textMuted,
    fontSize: 12,
  },
});
