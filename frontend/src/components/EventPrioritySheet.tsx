/**
 * EventPrioritySheet — Task 1.7
 * Bottom sheet for changing an event's priority (A / B / C).
 */
import { useState } from "react";
import { View, Text, StyleSheet, Modal, Pressable, ActivityIndicator, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";
import { api } from "@/src/lib/api";

const PRIORITIES: { id: "A" | "B" | "C"; label: string; sub: string; color: string }[] = [
  { id: "A", label: "PRIMARY — Full periodisation", sub: "Long-run curve, phase-aware training, taper, race week. Only one can be A.", color: "#DC2626" },
  { id: "B", label: "SECONDARY — Mini-taper only",  sub: "A short taper the week before + 1 day rest after. Marathon block continues around it.", color: "#F59E0B" },
  { id: "C", label: "MAINTENANCE — For fun / display", sub: "No taper. Shows on your dashboard only. Training carries on as normal.", color: "#6B7280" },
];

export function EventPrioritySheet({
  event, onClose, onSaved,
}: { event: any | null; onClose: () => void; onSaved?: () => void }) {
  const [saving, setSaving] = useState(false);
  if (!event) return null;

  const save = async (newP: "A" | "B" | "C") => {
    if (saving) return;
    if (newP === "A" && event.priority !== "A") {
      Alert.alert(
        "Set as Primary?",
        "Any other Primary event will be moved to Secondary. You can change this any time.",
        [
          { text: "Cancel", style: "cancel" },
          { text: "Confirm", onPress: () => doSave(newP) },
        ],
      );
      return;
    }
    doSave(newP);
  };
  const doSave = async (newP: "A" | "B" | "C") => {
    setSaving(true);
    try {
      await api(`/events/${event.id}/priority`, { method: "PATCH", body: { priority: newP } });
      onSaved?.();
      onClose();
    } catch (e: any) {
      Alert.alert("Save failed", e?.message || "Try again.");
    } finally { setSaving(false); }
  };

  return (
    <Modal visible={!!event} animationType="slide" transparent onRequestClose={onClose}>
      <Pressable style={s.scrim} onPress={onClose}>
        <Pressable style={s.sheet} onPress={(e) => e.stopPropagation()}>
          <View style={s.handle} />
          <Text style={s.eyebrow}>EVENT PRIORITY</Text>
          <Text style={s.title} numberOfLines={2}>{event.event_name}</Text>
          <Text style={s.sub}>
            {(event.event_type || "").replace(/_/g, " ")} · {event.weeks_to_event ?? "?"} weeks away
          </Text>
          <View style={{ marginTop: theme.space.md, gap: 10 }}>
            {PRIORITIES.map((p) => {
              const active = (event.priority || "C") === p.id;
              return (
                <Pressable
                  key={p.id}
                  testID={`event-priority-${p.id}`}
                  onPress={() => save(p.id)}
                  disabled={saving}
                  style={[s.opt, active && { borderColor: p.color, backgroundColor: p.color + "22" }]}
                >
                  <View style={[s.badge, { backgroundColor: p.color }]}>
                    <Text style={s.badgeT}>{p.id}</Text>
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={s.optLabel}>{p.label}</Text>
                    <Text style={s.optSub}>{p.sub}</Text>
                  </View>
                  {active ? <Ionicons name="checkmark-circle" size={18} color={p.color} /> : null}
                </Pressable>
              );
            })}
          </View>
          {saving ? <ActivityIndicator style={{ marginTop: 10 }} color={theme.color.brand} /> : null}
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const s = StyleSheet.create({
  scrim: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  sheet: { backgroundColor: theme.color.surface, borderTopLeftRadius: 18, borderTopRightRadius: 18, padding: theme.space.lg, paddingBottom: theme.space.xl },
  handle: { alignSelf: "center", width: 42, height: 4, borderRadius: 2, backgroundColor: theme.color.border, marginBottom: theme.space.md },
  eyebrow: { color: theme.color.brand, fontSize: 10, letterSpacing: 2, fontWeight: "800" },
  title: { color: theme.color.text, fontSize: 18, fontWeight: "900", marginTop: 4 },
  sub: { color: theme.color.textMuted, fontSize: 12, marginTop: 4 },
  opt: { flexDirection: "row", alignItems: "center", gap: 12, padding: theme.space.md, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface2, minHeight: 60 },
  badge: { width: 32, height: 32, borderRadius: 16, alignItems: "center", justifyContent: "center" },
  badgeT: { color: "#fff", fontSize: 14, fontWeight: "900" },
  optLabel: { color: theme.color.text, fontSize: 12, fontWeight: "800", letterSpacing: 0.5 },
  optSub: { color: theme.color.textMuted, fontSize: 11, marginTop: 3, lineHeight: 15 },
});
