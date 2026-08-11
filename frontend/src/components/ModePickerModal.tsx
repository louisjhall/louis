/**
 * ModePickerModal — asks the client how they want to complete this workout.
 * Manual Mode = train at own pace, log manually.
 * Guided Flow = step-by-step with timers, rest, prompts, logging.
 * Includes "Remember my choice" toggle.
 */
import { useState } from "react";
import { View, Text, StyleSheet, Pressable, Modal } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";
import { WorkoutMode, setPreferredMode } from "@/src/lib/workoutMode";

export function ModePickerModal({
  visible,
  onClose,
  onChoose,
  initialMode = "manual",
}: {
  visible: boolean;
  onClose: () => void;
  onChoose: (mode: WorkoutMode) => void;
  initialMode?: WorkoutMode;
}) {
  const [selected, setSelected] = useState<WorkoutMode>(initialMode);
  const [remember, setRemember] = useState(false);

  const confirm = async () => {
    await setPreferredMode(selected, remember);
    onChoose(selected);
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.root}>
        <Pressable style={styles.backdrop} onPress={onClose} />
        <View style={styles.sheet}>
          <View style={styles.head}>
            <View style={{ flex: 1 }}>
              <Text style={styles.eyebrow}>ATLAS</Text>
              <Text style={styles.title}>How would you like to complete this workout?</Text>
            </View>
            <Pressable onPress={onClose} hitSlop={12}>
              <Ionicons name="close" size={22} color={theme.color.text} />
            </Pressable>
          </View>

          <View style={styles.body}>
            <ModeCard
              icon="barbell"
              label="START MANUAL SESSION"
              hint="Vertical list — see every set, log at your own pace."
              active={selected === "manual"}
              onPress={() => setSelected("manual")}
              testID="mode-manual"
            />
            <ModeCard
              icon="play-circle"
              label="START GUIDED SESSION"
              hint="Follow step-by-step with timers, rest periods and coaching prompts."
              active={selected === "guided"}
              onPress={() => setSelected("guided")}
              testID="mode-guided"
            />

            <Pressable style={styles.rememberRow} onPress={() => setRemember((v) => !v)} testID="mode-remember">
              <View style={[styles.check, remember && styles.checkOn]}>
                {remember && <Ionicons name="checkmark" size={14} color="#fff" />}
              </View>
              <Text style={styles.rememberT}>Remember my choice for future workouts</Text>
            </Pressable>

            <Pressable onPress={confirm} style={styles.startBtn} testID="mode-start">
              <Text style={styles.startBtnT}>START WORKOUT</Text>
              <Ionicons name="arrow-forward" size={14} color="#fff" />
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

function ModeCard({
  icon, label, hint, active, onPress, testID,
}: {
  icon: any; label: string; hint: string; active: boolean; onPress: () => void; testID?: string;
}) {
  return (
    <Pressable onPress={onPress} style={[styles.card, active && styles.cardActive]} testID={testID}>
      <View style={[styles.cardIcon, active && styles.cardIconActive]}>
        <Ionicons name={icon} size={22} color={active ? "#fff" : theme.color.brand} />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={[styles.cardLabel, active && styles.cardLabelActive]}>{label}</Text>
        <Text style={styles.cardHint}>{hint}</Text>
      </View>
      <Ionicons
        name={active ? "radio-button-on" : "radio-button-off"}
        size={20}
        color={active ? theme.color.brand : theme.color.textDim}
      />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, justifyContent: "flex-end" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.5)" },
  sheet: { backgroundColor: theme.color.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20 },
  head: { flexDirection: "row", alignItems: "flex-start", padding: 20, gap: 12 },
  eyebrow: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  title: { color: theme.color.text, fontSize: 18, fontWeight: "800", marginTop: 6, lineHeight: 24 },
  body: { padding: 20, paddingTop: 0, gap: 12 },
  card: {
    flexDirection: "row", alignItems: "center", gap: 14,
    padding: 16, borderRadius: 14, backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
  },
  cardActive: { borderColor: theme.color.brand, backgroundColor: theme.color.brandTint },
  cardIcon: {
    width: 44, height: 44, borderRadius: 22,
    backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
  },
  cardIconActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  cardLabel: { color: theme.color.text, fontSize: 13, fontWeight: "900", letterSpacing: 1.5 },
  cardLabelActive: { color: theme.color.brand },
  cardHint: { color: theme.color.textMuted, fontSize: 11, marginTop: 4, lineHeight: 15 },
  rememberRow: { flexDirection: "row", alignItems: "center", gap: 10, marginTop: 6, paddingVertical: 6 },
  check: {
    width: 22, height: 22, borderRadius: 6,
    borderWidth: 1.5, borderColor: theme.color.border,
    alignItems: "center", justifyContent: "center",
  },
  checkOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  rememberT: { color: theme.color.text, fontSize: 12, fontWeight: "600" },
  startBtn: {
    marginTop: 10, padding: 16, borderRadius: 12, backgroundColor: theme.color.brand,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
  },
  startBtnT: { color: "#fff", fontSize: 13, fontWeight: "900", letterSpacing: 2 },
});
