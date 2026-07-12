import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Modal, Pressable, ScrollView, ActivityIndicator, TextInput, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";
import { api } from "@/src/lib/api";

/* -------------------------------------------------------------------------- */
/*  Reality Kinds + Icon Map                                                  */
/* -------------------------------------------------------------------------- */
type Kind = {
  key: string;
  label: string;
  emoji: string;
  icon: any;
  hint?: string;
};

export const REALITY_KINDS: Kind[] = [
  { key: "exhausted", label: "I'm exhausted", icon: "moon", hint: "Little sleep, low energy" },
  { key: "flight_delayed", label: "Flight delayed", icon: "airplane", hint: "Delay disrupts today" },
  { key: "roster_changed", label: "Roster changed", icon: "calendar", hint: "Duties shifted" },
  { key: "hotel_changed", label: "Hotel changed", icon: "business", hint: "Different equipment" },
  { key: "no_gym", label: "No gym available", icon: "barbell", hint: "Bodyweight only" },
  { key: "feeling_amazing", label: "Feeling amazing", icon: "flame", hint: "Add bonus quality" },
  { key: "less_time", label: "Less time today", icon: "hourglass", hint: "Squeeze it in" },
  { key: "more_time", label: "More time today", icon: "time", hint: "Extra window" },
  { key: "family_commitments", label: "Family commitments", icon: "people", hint: "Family first" },
  { key: "annual_leave", label: "Annual leave", icon: "sunny", hint: "Rest or travel" },
  { key: "feeling_ill", label: "Feeling ill", icon: "medkit", hint: "Illness" },
  { key: "injured", label: "Injured", icon: "bandage", hint: "Injury flag" },
  { key: "travelling", label: "Travelling", icon: "car", hint: "On the move" },
  { key: "bad_weather", label: "Bad weather", icon: "rainy", hint: "Storms / heat" },
  { key: "missed_yesterday", label: "Missed yesterday", icon: "close-circle", hint: "Recover safely" },
  { key: "want_to_move", label: "Move this workout", icon: "swap-horizontal", hint: "Reschedule" },
  { key: "other", label: "Something else", icon: "create", hint: "Tell CrewFit" },
];

/* -------------------------------------------------------------------------- */
/*  Component                                                                 */
/* -------------------------------------------------------------------------- */
type Stage = "pick" | "loading" | "review" | "applying" | "done";

export function RealityModal({
  visible, date, onClose, onApplied,
}: {
  visible: boolean;
  date: string | null;
  onClose: () => void;
  onApplied?: () => void;
}) {
  const [stage, setStage] = useState<Stage>("pick");
  const [selectedKind, setSelectedKind] = useState<Kind | null>(null);
  const [notes, setNotes] = useState("");
  const [timeMin, setTimeMin] = useState<string>("");
  const [result, setResult] = useState<any>(null);
  const [chosen, setChosen] = useState<string | null>(null);

  useEffect(() => {
    if (!visible) {
      // Reset after close animation
      setTimeout(() => {
        setStage("pick");
        setSelectedKind(null);
        setNotes("");
        setTimeMin("");
        setResult(null);
        setChosen(null);
      }, 250);
    }
  }, [visible]);

  const submit = async (k: Kind) => {
    if (!date) return;
    setSelectedKind(k);
    setStage("loading");
    try {
      const body: any = { date, reality_kind: k.key, notes: notes || undefined };
      const t = parseInt(timeMin, 10);
      if (!Number.isNaN(t) && t > 0) body.time_available_min = t;
      const r = await api<any>("/reality/submit", { method: "POST", body });
      setResult(r);
      setStage("review");
    } catch (e: any) {
      Alert.alert("CrewFit couldn't analyse this", e?.message || "Please try again");
      setStage("pick");
    }
  };

  const apply = async (optId: string) => {
    if (!result?.reality_event_id) return;
    setChosen(optId);
    setStage("applying");
    try {
      const r = await api<any>("/reality/apply", {
        method: "POST",
        body: { reality_event_id: result.reality_event_id, option_id: optId },
      });
      if (r.status === "ask_coach") {
        Alert.alert("Sent to your coach", "Your coach will review and get back to you.");
      } else {
        Alert.alert("Plan updated", "CrewFit has adapted your programme.");
      }
      onApplied?.();
      onClose();
    } catch (e: any) {
      Alert.alert("Couldn't apply", e?.message || "Please try again");
      setStage("review");
    }
  };

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View style={styles.root}>
        <Pressable style={styles.backdrop} onPress={onClose} />
        <View style={styles.card}>
          <View style={styles.header}>
            <View style={{ flex: 1 }}>
              <Text style={styles.title}>TODAY&apos;S REALITY</Text>
              <Text style={styles.sub}>
                {stage === "pick" && "What has changed today?"}
                {stage === "loading" && "Atlas is analysing your day..."}
                {stage === "review" && (result?.context_summary || "Atlas has prepared these options")}
                {stage === "applying" && "Applying..."}
              </Text>
            </View>
            <Pressable testID="reality-close" onPress={onClose} hitSlop={12}>
              <Ionicons name="close" size={22} color={theme.color.text} />
            </Pressable>
          </View>

          {stage === "pick" && (
            <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
              <Text style={styles.dateLine}>{date || ""}</Text>
              <View style={styles.grid}>
                {REALITY_KINDS.map((k) => (
                  <Pressable
                    key={k.key}
                    testID={`reality-kind-${k.key}`}
                    onPress={() => submit(k)}
                    style={({ pressed }) => [styles.kindCard, pressed && styles.kindPressed]}
                  >
                    <View style={styles.kindIconWrap}>
                      <Ionicons name={k.icon as any} size={22} color={theme.color.brand} />
                    </View>
                    <Text style={styles.kindLabel} numberOfLines={2}>{k.label}</Text>
                    {k.hint ? <Text style={styles.kindHint} numberOfLines={1}>{k.hint}</Text> : null}
                  </Pressable>
                ))}
              </View>

              <Text style={styles.optionalLabel}>OPTIONAL — TIME AVAILABLE (MIN)</Text>
              <TextInput
                testID="reality-time-input"
                value={timeMin}
                onChangeText={setTimeMin}
                keyboardType="number-pad"
                placeholder="e.g. 20"
                placeholderTextColor={theme.color.textDim}
                style={styles.input}
              />
              <Text style={styles.optionalLabel}>OPTIONAL — ANYTHING ELSE?</Text>
              <TextInput
                testID="reality-notes-input"
                value={notes}
                onChangeText={setNotes}
                multiline
                placeholder="Tell CrewFit about your day..."
                placeholderTextColor={theme.color.textDim}
                style={[styles.input, { minHeight: 70, textAlignVertical: "top" }]}
              />
            </ScrollView>
          )}

          {stage === "loading" && (
            <View style={styles.loadingWrap}>
              <View style={styles.spinCircle}>
                <ActivityIndicator size="large" color={theme.color.brand} />
              </View>
              <Text style={styles.thinkingT}>ATLAS</Text>
              <Text style={styles.thinkingS}>
                Analysing programme · recovery · roster · event · coach rules...
              </Text>
              {selectedKind && (
                <View style={styles.pickedRow}>
                  <Ionicons name={selectedKind.icon as any} size={18} color={theme.color.brand} />
                  <Text style={styles.pickedLabel}>{selectedKind.label}</Text>
                </View>
              )}
            </View>
          )}

          {stage === "review" && result && (
            <ScrollView contentContainerStyle={styles.body}>
              {typeof result.recovery_score === "number" && (
                <View style={styles.recoveryBanner}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.recoveryLabel}>RECOVERY SCORE</Text>
                    <Text style={styles.recoverySub}>
                      {result.recovery_score >= 75 ? "You're recovered well." :
                        result.recovery_score >= 50 ? "You're moderately recovered." :
                          "You're under-recovered."}
                    </Text>
                  </View>
                  <View style={[styles.recoveryDial, {
                    borderColor: result.recovery_score >= 75 ? theme.color.green :
                      result.recovery_score >= 50 ? theme.color.amber : theme.color.red,
                  }]}>
                    <Text style={styles.recoveryNum}>{result.recovery_score}</Text>
                  </View>
                </View>
              )}

              <Text style={styles.optHeader}>ATLAS RECOMMENDATION</Text>
              {(result.options || []).map((o: any) => (
                <View key={o.id} style={[
                  styles.optCard,
                  o.id === "A" && styles.optRecommended,
                  o.id === "C" && styles.optAsk,
                ]}>
                  <View style={styles.optHead}>
                    <View style={[styles.optIdPill, o.id === "A" && { backgroundColor: theme.color.brand }]}>
                      <Text style={[styles.optIdText, o.id === "A" && { color: "#fff" }]}>
                        {o.label?.toUpperCase() || o.id}
                      </Text>
                    </View>
                    {o.touches_locked && (
                      <View style={styles.lockedPill}>
                        <Ionicons name="lock-closed" size={10} color={theme.color.amber} />
                        <Text style={styles.lockedText}>TOUCHES LOCKED</Text>
                      </View>
                    )}
                    <View style={styles.riskPill}>
                      <Text style={styles.riskText}>{String(o.risk || "low").toUpperCase()} RISK</Text>
                    </View>
                  </View>
                  <Text style={styles.optTitle}>{o.title}</Text>
                  <Text style={styles.optWhy}>{o.why}</Text>
                  {(o.actions || []).length > 0 && (
                    <View style={styles.actionsList}>
                      {(o.actions || []).map((a: any, i: number) => (
                        <View key={i} style={styles.actionChip}>
                          <Ionicons name={actionIcon(a.kind)} size={11} color={theme.color.brand} />
                          <Text style={styles.actionText}>{describeAction(a)}</Text>
                        </View>
                      ))}
                    </View>
                  )}
                  <Pressable
                    testID={`reality-apply-${o.id}`}
                    onPress={() => apply(o.id)}
                    style={[styles.applyBtn, o.id === "A" && styles.applyBtnPrimary]}
                  >
                    <Text style={[styles.applyBtnText, o.id === "A" && { color: "#fff" }]}>
                      {o.id === "C" ? "SEND TO COACH" : `CHOOSE OPTION ${o.id}`}
                    </Text>
                    <Ionicons
                      name="arrow-forward"
                      size={14}
                      color={o.id === "A" ? "#fff" : theme.color.brand}
                    />
                  </Pressable>
                </View>
              ))}

              <Pressable onPress={() => setStage("pick")} style={styles.backBtn}>
                <Ionicons name="chevron-back" size={14} color={theme.color.textMuted} />
                <Text style={styles.backText}>PICK A DIFFERENT REALITY</Text>
              </Pressable>
            </ScrollView>
          )}

          {stage === "applying" && (
            <View style={styles.loadingWrap}>
              <ActivityIndicator size="large" color={theme.color.brand} />
              <Text style={styles.thinkingT}>APPLYING CHANGES</Text>
              <Text style={styles.thinkingS}>Option {chosen}</Text>
            </View>
          )}
        </View>
      </View>
    </Modal>
  );
}

/* -------------------------------------------------------------------------- */
/*  Helpers                                                                    */
/* -------------------------------------------------------------------------- */
function actionIcon(k: string): any {
  switch (k) {
    case "keep": return "checkmark";
    case "reduce": return "remove-circle";
    case "extend": return "add-circle";
    case "replace": return "swap-horizontal";
    case "convert_mobility": return "body";
    case "convert_recovery": return "leaf";
    case "convert_walk": return "walk";
    case "skip": return "close-circle";
    case "move": return "arrow-forward";
    case "bring_forward": return "arrow-back";
    case "push_back": return "arrow-forward";
    case "note": return "create";
    case "ask_coach": return "chatbubbles";
    default: return "flash";
  }
}

function describeAction(a: any): string {
  switch (a.kind) {
    case "keep": return "Keep session";
    case "reduce": return `Reduce to ${a.target_min || "target"} min`;
    case "extend": return `+${a.add_min || 15} min bonus`;
    case "replace": return `Replace → ${a.new_title || a.new_focus || "new session"}`;
    case "convert_mobility": return "Mobility only";
    case "convert_recovery": return "Easy recovery";
    case "convert_walk": return `${a.target_min || 30}m walk`;
    case "skip": return "Skip today";
    case "move": return `Move ${a.from_date} → ${a.to_date}`;
    case "bring_forward": return `Bring forward from ${a.from_date}`;
    case "push_back": return `Push to ${a.to_date}`;
    case "note": return "Coach note";
    case "ask_coach": return "Send to coach";
    default: return a.kind;
  }
}

/* -------------------------------------------------------------------------- */
/*  Styles                                                                     */
/* -------------------------------------------------------------------------- */
const styles = StyleSheet.create({
  root: { flex: 1, justifyContent: "flex-end" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.8)" },
  card: {
    maxHeight: "94%",
    backgroundColor: theme.color.surface,
    borderTopLeftRadius: 22,
    borderTopRightRadius: 22,
    borderWidth: 1,
    borderColor: theme.color.border,
  },
  header: {
    flexDirection: "row", alignItems: "center", padding: 16,
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  title: { color: theme.color.text, fontSize: 14, fontWeight: "900", letterSpacing: 2 },
  sub: { color: theme.color.textMuted, fontSize: 12, marginTop: 3 },
  body: { padding: 16, paddingBottom: 48 },
  dateLine: { color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 2, marginBottom: 12 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  kindCard: {
    width: "31%",
    minHeight: 110,
    padding: 10,
    borderRadius: 12,
    backgroundColor: theme.color.surface2,
    borderWidth: 1,
    borderColor: theme.color.border,
    alignItems: "center",
    justifyContent: "flex-start",
  },
  kindPressed: { backgroundColor: theme.color.brandTint, borderColor: theme.color.brand },
  kindEmoji: { fontSize: 26, marginBottom: 6 },
  kindIconWrap: { width: 40, height: 40, borderRadius: 20, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand, alignItems: "center", justifyContent: "center", marginBottom: 8 },
  kindLabel: { color: theme.color.text, fontSize: 11, fontWeight: "800", textAlign: "center", letterSpacing: 0.3 },
  kindHint: { color: theme.color.textDim, fontSize: 9, marginTop: 3, textAlign: "center" },
  optionalLabel: { color: theme.color.brand, fontSize: 10, fontWeight: "800", letterSpacing: 2, marginTop: 20, marginBottom: 6 },
  input: {
    color: theme.color.text, fontSize: 13, padding: 12,
    backgroundColor: theme.color.surface2,
    borderRadius: 8, borderWidth: 1, borderColor: theme.color.border,
  },
  loadingWrap: { alignItems: "center", padding: 48 },
  spinCircle: { marginBottom: 20 },
  thinkingT: { color: theme.color.brand, fontSize: 14, fontWeight: "900", letterSpacing: 2, marginTop: 8 },
  thinkingS: { color: theme.color.textMuted, fontSize: 12, marginTop: 8, textAlign: "center", lineHeight: 18 },
  pickedRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 20, padding: 10, backgroundColor: theme.color.surface2, borderRadius: 8 },
  pickedEmoji: { fontSize: 22 },
  pickedLabel: { color: theme.color.text, fontSize: 13, fontWeight: "700" },

  recoveryBanner: {
    flexDirection: "row", alignItems: "center", gap: 12,
    padding: 14, borderRadius: 12,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
    marginBottom: 16,
  },
  recoveryLabel: { color: theme.color.brand, fontSize: 10, fontWeight: "800", letterSpacing: 2 },
  recoverySub: { color: theme.color.text, fontSize: 12, marginTop: 4 },
  recoveryDial: {
    width: 60, height: 60, borderRadius: 30, borderWidth: 3,
    alignItems: "center", justifyContent: "center",
  },
  recoveryNum: { color: theme.color.text, fontSize: 18, fontWeight: "900" },

  optHeader: { color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 2, marginBottom: 10 },
  optCard: {
    marginBottom: 12, padding: 14, borderRadius: 12,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  optRecommended: { borderColor: theme.color.brand, borderWidth: 2 },
  optAsk: { backgroundColor: "rgba(245, 158, 11, 0.08)" },
  optHead: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 8, flexWrap: "wrap" },
  optIdPill: {
    paddingHorizontal: 8, paddingVertical: 3, borderRadius: 4,
    backgroundColor: theme.color.surface3, borderWidth: 1, borderColor: theme.color.border,
  },
  optIdText: { color: theme.color.text, fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },
  lockedPill: {
    flexDirection: "row", alignItems: "center", gap: 3,
    paddingHorizontal: 6, paddingVertical: 3, borderRadius: 4,
    backgroundColor: "rgba(245, 158, 11, 0.15)",
  },
  lockedText: { color: theme.color.amber, fontSize: 9, fontWeight: "900", letterSpacing: 1 },
  riskPill: {
    paddingHorizontal: 6, paddingVertical: 3, borderRadius: 4,
    backgroundColor: theme.color.surface3, marginLeft: "auto",
  },
  riskText: { color: theme.color.textDim, fontSize: 9, fontWeight: "800", letterSpacing: 1 },
  optTitle: { color: theme.color.text, fontSize: 15, fontWeight: "800", marginBottom: 6, lineHeight: 20 },
  optWhy: { color: theme.color.textMuted, fontSize: 12, lineHeight: 18, marginBottom: 10 },
  actionsList: { flexDirection: "row", flexWrap: "wrap", gap: 5, marginBottom: 10 },
  actionChip: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 7, paddingVertical: 4, borderRadius: 4,
    backgroundColor: theme.color.surface3, borderWidth: 1, borderColor: theme.color.border,
  },
  actionText: { color: theme.color.textMuted, fontSize: 10, fontWeight: "700" },
  applyBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    paddingVertical: 10, borderRadius: 8,
    backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.brand,
  },
  applyBtnPrimary: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  applyBtnText: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  backBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 4,
    marginTop: 4, paddingVertical: 10,
  },
  backText: { color: theme.color.textMuted, fontSize: 10, fontWeight: "800", letterSpacing: 1.5 },
});
