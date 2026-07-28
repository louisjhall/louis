/**
 * ChangeSetupModal — Iter 119
 *
 * HOW-only adaptation of a V2 Live workout. Two steps:
 *   1) Where are you training? (env)
 *   2) What equipment is available? (chips, filtered by env & session type)
 * Then POST /v2/client/plan/adapt-live and close.
 *
 * Preserves ObjectiveExposure identity — backend refuses to mutate WHAT/WHEN.
 *
 * Iter 119 updates:
 * - Expanded hotel-gym chip set (Cable Machine, Smith Machine, Leg Press,
 *   Lat Pulldown, Bike…) and fixed the band chip key so band-compatible
 *   exercises actually reach the constructor pool.
 * - Added Dumbbells to Hotel Room chips.
 * - Added a one-tap "Bodyweight Only" quick submit inside hotel_room /
 *   hotel_gym so clients can strip equipment without extra taps.
 * - Scope hard-coded to `this_session` per PRD. Today / this_layover /
 *   persistent preference remain backlog.
 */
import React, { useState } from "react";
import { View, Text, Modal, Pressable, ScrollView, StyleSheet, ActivityIndicator, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";
import { api } from "@/src/lib/api";

type Env = "hotel_room" | "hotel_gym" | "outdoor" | "treadmill" | "bodyweight_only";

const CARDIO_HINTS = ["running", "cycling", "swimming", "brick", "run_", "cycle_"];

function isCardioKind(sessionKind: string): boolean {
  const k = (sessionKind || "").toLowerCase();
  return CARDIO_HINTS.some((c) => k.includes(c));
}

function envOptions(sessionKind: string): { key: Env; label: string; icon: string }[] {
  if (isCardioKind(sessionKind)) {
    return [
      { key: "outdoor",   label: "Outdoors",   icon: "sunny-outline" },
      { key: "treadmill", label: "Treadmill",  icon: "walk-outline" },
    ];
  }
  // Strength / mobility / activation: hotel-first
  return [
    { key: "hotel_room",       label: "Hotel Room", icon: "bed-outline" },
    { key: "hotel_gym",        label: "Hotel Gym",  icon: "barbell-outline" },
    { key: "bodyweight_only",  label: "Bodyweight", icon: "body-outline" },
  ];
}

// Iter 119 — Chip catalogues.
// Keys must match backend `_EQUIPMENT_ALIASES` in feature_v2_plan_live_adapt.py.
function equipmentOptions(env: Env, sessionKind: string): { key: string; label: string }[] {
  const cardio = isCardioKind(sessionKind);
  if (env === "hotel_gym") {
    if (cardio) {
      return [
        { key: "treadmill", label: "Treadmill" },
        { key: "bike",      label: "Bike" },
        { key: "mat",       label: "Mat" },
      ];
    }
    // Strength / mobility hotel-gym chips
    return [
      { key: "dumbbells",      label: "Dumbbells" },
      { key: "bench",          label: "Bench" },
      { key: "cable_machine",  label: "Cable Machine" },
      { key: "barbell",        label: "Barbell" },
      { key: "smith_machine",  label: "Smith Machine" },
      { key: "leg_press",      label: "Leg Press" },
      { key: "lat_pulldown",   label: "Lat Pulldown" },
      { key: "kettlebell",     label: "Kettlebell" },
      { key: "band",           label: "Bands" },
      { key: "mat",            label: "Mat" },
      { key: "treadmill",      label: "Treadmill" },
      { key: "bike",           label: "Bike" },
    ];
  }
  if (env === "hotel_room") {
    return [
      { key: "band",       label: "Bands" },
      { key: "dumbbells",  label: "Dumbbells" },
      { key: "mat",        label: "Mat" },
    ];
  }
  // outdoor / treadmill / bodyweight_only — no equipment picker
  return [];
}

export function ChangeSetupModal({
  visible, onClose, date, sessionKind, workoutId, onDone,
}: {
  visible: boolean;
  onClose: () => void;
  date: string;                 // ISO placement date
  sessionKind: string;          // e.g. "run_easy" / "strength_full_body"
  workoutId?: string;
  onDone?: () => void;
}) {
  const [step, setStep] = useState<"env" | "equipment">("env");
  const [env, setEnv] = useState<Env | null>(null);
  const [equipment, setEquipment] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);

  const reset = () => { setStep("env"); setEnv(null); setEquipment(new Set()); };

  const submit = async (finalEnv: Env, finalEquipment: string[]) => {
    setBusy(true);
    try {
      await api("/v2/client/plan/adapt-live", {
        method: "POST",
        body: {
          date,
          environment: finalEnv,
          equipment: finalEquipment,
          scope: "this_session",
        },
      });
      Alert.alert("Setup updated", "Your workout has been adapted for this setup.");
      reset(); onClose(); if (onDone) onDone();
    } catch (e: any) {
      Alert.alert("Couldn't update", String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const envOpts = envOptions(sessionKind);
  const equipOpts = env ? equipmentOptions(env, sessionKind) : [];

  return (
    <Modal transparent visible={visible} animationType="fade" onRequestClose={() => { reset(); onClose(); }}>
      <Pressable style={s.backdrop} onPress={() => { reset(); onClose(); }}>
        <Pressable style={s.sheet} onPress={(e) => e.stopPropagation()}>
          <View style={s.header}>
            <Text style={s.headerT}>{step === "env" ? "WHERE ARE YOU TRAINING?" : "WHAT'S AVAILABLE?"}</Text>
            <Pressable onPress={() => { reset(); onClose(); }} testID="change-setup-close">
              <Ionicons name="close" size={22} color={theme.color.textMuted} />
            </Pressable>
          </View>

          <ScrollView style={{ maxHeight: 520 }}>
            {step === "env" ? (
              <View style={{ padding: 12, gap: 10 }}>
                {envOpts.map((o) => (
                  <Pressable
                    key={o.key} style={s.optRow}
                    testID={`change-setup-env-${o.key}`}
                    onPress={() => {
                      setEnv(o.key);
                      // Envs that need no equipment picker submit immediately.
                      if (o.key === "outdoor") {
                        submit("outdoor", []);
                      } else if (o.key === "treadmill") {
                        submit("treadmill", ["treadmill"]);
                      } else if (o.key === "bodyweight_only") {
                        submit("bodyweight_only", []);
                      } else {
                        setStep("equipment");
                      }
                    }}
                  >
                    <Ionicons name={o.icon as any} size={18} color={theme.color.brand} />
                    <Text style={s.optT}>{o.label}</Text>
                    <Ionicons name="chevron-forward" size={14} color={theme.color.textMuted} />
                  </Pressable>
                ))}
                <Text style={s.hint}>Only HOW changes. Your programme, exposure and date stay the same.</Text>
              </View>
            ) : (
              <View style={{ padding: 12 }}>
                <Text style={s.subHead}>{envOpts.find((o) => o.key === env)?.label}</Text>

                {/* Iter 119 — one-tap "Bodyweight Only" quick submit */}
                <Pressable
                  testID="change-setup-eq-bodyweight_only"
                  style={s.bwRow}
                  onPress={() => submit(env!, [])}
                >
                  <Ionicons name="body" size={16} color={theme.color.brand} />
                  <Text style={s.bwT}>BODYWEIGHT ONLY</Text>
                  <Ionicons name="flash" size={12} color={theme.color.textMuted} />
                </Pressable>
                <Text style={[s.hint, { marginTop: 4, marginBottom: 8 }]}>
                  Or pick what&apos;s available:
                </Text>

                <View style={s.chips}>
                  {equipOpts.length === 0 ? (
                    <Text style={s.hint}>No equipment picker needed.</Text>
                  ) : equipOpts.map((c) => {
                    const selected = equipment.has(c.key);
                    return (
                      <Pressable
                        key={c.key}
                        testID={`change-setup-eq-${c.key}`}
                        onPress={() => {
                          const next = new Set(equipment);
                          if (selected) next.delete(c.key); else next.add(c.key);
                          setEquipment(next);
                        }}
                        style={[s.chip, selected && s.chipOn]}
                      >
                        <Text style={[s.chipT, selected && s.chipTOn]}>{c.label}</Text>
                      </Pressable>
                    );
                  })}
                </View>

                <Pressable
                  disabled={busy}
                  testID="change-setup-submit"
                  style={[s.primary, busy && { opacity: 0.5 }]}
                  onPress={() => submit(env!, Array.from(equipment))}
                >
                  {busy ? <ActivityIndicator color="#000" /> : (
                    <>
                      <Ionicons name="checkmark" size={16} color="#000" />
                      <Text style={s.primaryT}>UPDATE WORKOUT</Text>
                    </>
                  )}
                </Pressable>
              </View>
            )}
          </ScrollView>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const s = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "#000000cc", justifyContent: "flex-end" },
  sheet: {
    backgroundColor: theme.color.surface, borderTopLeftRadius: 16, borderTopRightRadius: 16,
    paddingBottom: 20, borderWidth: 1, borderColor: theme.color.border,
  },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    padding: 14, borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  headerT: { color: theme.color.text, fontWeight: "800", fontSize: 12, letterSpacing: 1.4 },
  optRow: {
    flexDirection: "row", alignItems: "center", gap: 12,
    paddingVertical: 12, paddingHorizontal: 12,
    backgroundColor: theme.color.surface2, borderRadius: 10,
    borderWidth: 1, borderColor: theme.color.border,
  },
  optT: { flex: 1, color: theme.color.text, fontSize: 14, fontWeight: "700" },
  hint: { color: theme.color.textMuted, fontSize: 11, fontStyle: "italic", marginTop: 6 },
  subHead: { color: theme.color.textMuted, fontSize: 10, fontWeight: "800", letterSpacing: 1.4, marginBottom: 8 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 14, borderWidth: 1, borderColor: theme.color.border },
  chipOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipT: { color: theme.color.text, fontSize: 11, fontWeight: "700" },
  chipTOn: { color: "#000" },
  bwRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingVertical: 10, paddingHorizontal: 12,
    backgroundColor: theme.color.brandTint,
    borderRadius: 10, borderWidth: 1, borderColor: theme.color.brand,
    marginBottom: 4,
  },
  bwT: { flex: 1, color: theme.color.text, fontSize: 12, fontWeight: "800", letterSpacing: 1.2 },
  primary: {
    marginTop: 14, backgroundColor: theme.color.brand,
    borderRadius: 10, paddingVertical: 12,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
  },
  primaryT: { color: "#000", fontWeight: "800", letterSpacing: 1.2, fontSize: 12 },
});
