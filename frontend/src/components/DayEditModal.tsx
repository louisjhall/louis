import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Modal, Pressable, ScrollView, TextInput, ActivityIndicator, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";
import { api } from "@/src/lib/api";

const TAG_OPTIONS: { k: string; l: string; icon: any }[] = [
  { k: "annual_leave", l: "Annual Leave", icon: "airplane" },
  { k: "holiday", l: "Holiday", icon: "sunny" },
  { k: "sick", l: "Sick", icon: "medkit" },
  { k: "injured", l: "Injured", icon: "bandage" },
  { k: "poor_sleep", l: "Poor Sleep", icon: "moon" },
  { k: "high_stress", l: "High Stress", icon: "flash" },
  { k: "family_commitment", l: "Family", icon: "people" },
  { k: "childcare", l: "Childcare", icon: "happy" },
  { k: "travel_day", l: "Travel Day", icon: "car" },
  { k: "no_gym", l: "No Gym", icon: "close-circle" },
  { k: "hotel_gym", l: "Hotel Gym", icon: "barbell" },
  { k: "outdoor_run_possible", l: "Outdoor Run", icon: "walk" },
  { k: "limited_time", l: "Less Time", icon: "hourglass" },
  { k: "extra_time", l: "More Time", icon: "time" },
  { k: "standby", l: "Standby", icon: "call" },
  { k: "called_out", l: "Called Out", icon: "megaphone" },
  { k: "duty_cancelled", l: "Duty Cancelled", icon: "close" },
  { k: "flight_delayed", l: "Flight Delayed", icon: "warning" },
  { k: "flight_extended", l: "Flight Extended", icon: "add-circle" },
  { k: "need_rest", l: "Need Rest", icon: "bed" },
  { k: "feeling_good", l: "Feeling Good", icon: "flame" },
];

const DAY_TYPES = [
  ["home_day", "Home Day"], ["turnaround", "Turnaround"], ["layover_arrival", "Layover Arrival"],
  ["layover_full", "Layover Full Day"], ["layover_departure", "Layover Departure"], ["standby", "Standby"],
  ["reserve", "Reserve"], ["simulator", "Simulator / Training"], ["annual_leave", "Annual Leave"],
  ["holiday", "Holiday"], ["sick", "Sick Day"], ["injury", "Injury Day"], ["family", "Family"],
  ["busy", "Busy Day"], ["rest", "Rest Day"], ["custom", "Custom"],
];

const AVAILABILITY_OPTIONS = [
  ["0", "No time"], ["10", "10 min"], ["20", "20 min"], ["30", "30 min"],
  ["45", "45 min"], ["60", "60 min"], ["90", "90 min"],
];

const EQUIPMENT_OPTIONS = [
  ["home_equipment", "Home Equipment"], ["gym", "Commercial Gym"], ["hotel_gym", "Hotel Gym"],
  ["bodyweight", "Bodyweight"], ["dumbbells", "Dumbbells"], ["outdoor_run", "Outdoor Run"],
  ["pool", "Pool"], ["bike", "Bike"], ["unknown", "Unknown"],
];

const PREF_OPTIONS = [
  ["normal", "Train normally"], ["reduce", "Reduce intensity"], ["mobility", "Mobility only"],
  ["rest", "Rest"], ["ask_coach", "Ask coach"], ["auto", "Let CrewFit decide"],
];

const APPLY_OPTIONS = [
  ["day", "This day only"], ["week", "This week"], ["forward", "From today onward"], ["note_only", "Save note only"],
];

export function DayEditModal({
  visible, date, onClose, onSaved,
}: {
  visible: boolean;
  date: string | null;
  onClose: () => void;
  onSaved?: () => void;
}) {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dayType, setDayType] = useState<string | null>(null);
  const [availability, setAvailability] = useState<string | null>(null);
  const [equipment, setEquipment] = useState<string[]>([]);
  const [pref, setPref] = useState<string | null>(null);
  const [tags, setTags] = useState<string[]>([]);
  const [notes, setNotes] = useState("");
  const [applyTo, setApplyTo] = useState("day");
  const [history, setHistory] = useState<any[]>([]);
  const [coachLocked, setCoachLocked] = useState(false);

  useEffect(() => {
    if (!visible || !date) return;
    setLoading(true);
    (async () => {
      try {
        const res = await api<any>(`/calendar/day-override?date=${encodeURIComponent(date)}`);
        const o = res.override;
        setDayType(o?.day_type || null);
        setAvailability(o?.availability_min != null ? String(o.availability_min) : null);
        setEquipment(o?.equipment || []);
        setPref(o?.training_preference || null);
        setTags(o?.tags || []);
        setNotes(o?.notes || "");
        setApplyTo(o?.apply_to || "day");
        setHistory(res.history || []);
      } catch { /* ignore */ }
      finally { setLoading(false); }
    })();
  }, [visible, date]);

  const toggleTag = (k: string) => setTags((t) => t.includes(k) ? t.filter((x) => x !== k) : [...t, k]);
  const toggleEquip = (k: string) => setEquipment((e) => e.includes(k) ? e.filter((x) => x !== k) : [...e, k]);

  const save = async () => {
    if (!date) return;
    setSaving(true);
    try {
      const res = await api<any>(`/calendar/day-override`, {
        method: "POST",
        body: {
          date, day_type: dayType,
          availability_min: availability != null ? parseInt(availability, 10) : null,
          equipment, training_preference: pref, tags, notes,
          apply_to: applyTo,
        },
      });
      const adj = res.adjustment || {};
      if (res.coach_locked) {
        Alert.alert(
          "Coach locked",
          "This workout has been locked by your coach. Your update has been sent to them for review."
        );
      } else if (adj.changed && adj.action && adj.action !== "noop") {
        const map: any = {
          rest: "Rest day scheduled",
          off: "Marked as off day",
          mobility: "Swapped to light mobility",
          reduce: "Session intensity reduced",
          location_only: "Session location updated",
        };
        Alert.alert(
          map[adj.action] || "Plan updated",
          (adj.reason || "") + (adj.new_title ? `\n\nNow: ${adj.new_title}${adj.new_duration ? ` · ${adj.new_duration}m` : ""}` : "")
        );
      }
      onSaved?.();
      onClose();
    } catch (e: any) {
      Alert.alert("Save failed", e?.message || "Please try again");
    } finally { setSaving(false); }
  };

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View style={styles.root}>
        <Pressable style={styles.backdrop} onPress={onClose} />
        <View style={styles.card}>
          <View style={styles.header}>
            <View style={{ flex: 1 }}>
              <Text style={styles.title}>EDIT DAY</Text>
              <Text style={styles.sub}>{date}</Text>
            </View>
            <Pressable testID="dayedit-close" onPress={onClose} hitSlop={12}>
              <Ionicons name="close" size={22} color={theme.color.text} />
            </Pressable>
          </View>

          {loading ? (
            <ActivityIndicator color={theme.color.brand} style={{ marginTop: 40 }} />
          ) : (
            <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 40 }}>
              <Section title="QUICK TAGS">
                <View style={styles.chipRow}>
                  {TAG_OPTIONS.map((t) => {
                    const on = tags.includes(t.k);
                    return (
                      <Pressable key={t.k} testID={`tag-${t.k}`} onPress={() => toggleTag(t.k)} style={[styles.chip, on && styles.chipActive]}>
                        <Ionicons name={t.icon} size={11} color={on ? "#fff" : theme.color.brand} />
                        <Text style={[styles.chipText, on && { color: "#fff" }]}>{t.l}</Text>
                      </Pressable>
                    );
                  })}
                </View>
              </Section>

              <Section title="DAY TYPE">
                <View style={styles.chipRow}>
                  {DAY_TYPES.map(([k, l]) => {
                    const on = dayType === k;
                    return (
                      <Pressable key={k} testID={`dt-${k}`} onPress={() => setDayType(on ? null : k)} style={[styles.chip, on && styles.chipActive]}>
                        <Text style={[styles.chipText, on && { color: "#fff" }]}>{l}</Text>
                      </Pressable>
                    );
                  })}
                </View>
              </Section>

              <Section title="TIME AVAILABLE">
                <View style={styles.chipRow}>
                  {AVAILABILITY_OPTIONS.map(([k, l]) => {
                    const on = availability === k;
                    return (
                      <Pressable key={k} testID={`av-${k}`} onPress={() => setAvailability(on ? null : k)} style={[styles.chip, on && styles.chipActive]}>
                        <Text style={[styles.chipText, on && { color: "#fff" }]}>{l}</Text>
                      </Pressable>
                    );
                  })}
                </View>
              </Section>

              <Section title="EQUIPMENT">
                <View style={styles.chipRow}>
                  {EQUIPMENT_OPTIONS.map(([k, l]) => {
                    const on = equipment.includes(k);
                    return (
                      <Pressable key={k} testID={`eq-${k}`} onPress={() => toggleEquip(k)} style={[styles.chip, on && styles.chipActive]}>
                        <Text style={[styles.chipText, on && { color: "#fff" }]}>{l}</Text>
                      </Pressable>
                    );
                  })}
                </View>
              </Section>

              <Section title="TRAINING PREFERENCE">
                <View style={styles.chipRow}>
                  {PREF_OPTIONS.map(([k, l]) => {
                    const on = pref === k;
                    return (
                      <Pressable key={k} testID={`pref-${k}`} onPress={() => setPref(on ? null : k)} style={[styles.chip, on && styles.chipActive]}>
                        <Text style={[styles.chipText, on && { color: "#fff" }]}>{l}</Text>
                      </Pressable>
                    );
                  })}
                </View>
              </Section>

              <Section title="NOTES">
                <TextInput
                  testID="dayedit-notes"
                  multiline
                  value={notes}
                  onChangeText={setNotes}
                  placeholder="Anything else CrewFit should know? e.g. 'Wedding all day', 'No hotel gym', 'Feeling ill'..."
                  placeholderTextColor={theme.color.textDim}
                  style={styles.notes}
                />
              </Section>

              <Section title="APPLY TO">
                <View style={styles.chipRow}>
                  {APPLY_OPTIONS.map(([k, l]) => {
                    const on = applyTo === k;
                    return (
                      <Pressable key={k} testID={`apply-${k}`} onPress={() => setApplyTo(k)} style={[styles.chip, on && styles.chipActive]}>
                        <Text style={[styles.chipText, on && { color: "#fff" }]}>{l}</Text>
                      </Pressable>
                    );
                  })}
                </View>
              </Section>

              {history.length > 0 && (
                <Section title="CHANGE HISTORY">
                  {history.slice(0, 5).map((h) => (
                    <View key={h.id} style={styles.histRow}>
                      <View style={[styles.histDot, { backgroundColor: h.actor_role === "coach" ? theme.color.brand : theme.color.green }]} />
                      <View style={{ flex: 1 }}>
                        <Text style={styles.histTitle}>{(h.actor_role || "client").toUpperCase()} · {(h.new?.tags || []).slice(0, 3).join(", ") || h.action || "edited"}</Text>
                        <Text style={styles.histSub}>{h.created_at?.slice(0, 16).replace("T", " ")}</Text>
                      </View>
                    </View>
                  ))}
                </Section>
              )}

              <Pressable testID="dayedit-save" onPress={save} disabled={saving} style={[styles.saveBtn, saving && { opacity: 0.6 }]}>
                {saving ? <ActivityIndicator color="#fff" /> : <Text style={styles.saveBtnText}>SAVE CHANGES</Text>}
              </Pressable>
            </ScrollView>
          )}
        </View>
      </View>
    </Modal>
  );
}

function Section({ title, children }: any) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, justifyContent: "flex-end" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.75)" },
  card: { maxHeight: "92%", backgroundColor: theme.color.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20, borderWidth: 1, borderColor: theme.color.border },
  header: { flexDirection: "row", alignItems: "center", padding: 16, borderBottomWidth: 1, borderBottomColor: theme.color.border },
  title: { color: theme.color.text, fontSize: 14, fontWeight: "900", letterSpacing: 2 },
  sub: { color: theme.color.textMuted, fontSize: 12, marginTop: 3 },
  section: { marginBottom: 18 },
  sectionTitle: { color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 2, marginBottom: 8 },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  chipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipText: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700" },
  notes: { color: theme.color.onRed, fontSize: 13, padding: 12, backgroundColor: theme.color.surface2, borderRadius: 8, borderWidth: 1, borderColor: theme.color.border, minHeight: 80, textAlignVertical: "top" },
  histRow: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 6 },
  histDot: { width: 8, height: 8, borderRadius: 4 },
  histTitle: { color: theme.color.text, fontSize: 12, fontWeight: "700" },
  histSub: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },
  saveBtn: { backgroundColor: theme.color.brand, paddingVertical: 14, borderRadius: 10, alignItems: "center", marginTop: 10 },
  saveBtnText: { color: "#fff", fontSize: 12, fontWeight: "800", letterSpacing: 2 },
});
