/**
 * SwapWorkoutPicker — Phase 5.
 *
 * Bottom-sheet modal that lets the coach choose between 2-5 alternative
 * session presets whose training focus is SAFE for the workout's date
 * (respects parser training_colour / blocked[] / equipment).
 *
 * Suggestions come from GET /api/coach/workouts/{wid}/swap-suggestions.
 * Apply hits POST /api/coach/workouts/{wid}/apply-swap.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Modal, ScrollView, Pressable,
  ActivityIndicator, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";


type Suggestion = {
  id: string;
  title: string;
  focus: string;
  duration_min: number;
  location: string;
  rationale: string;
  fit_score: number;
  exercises: { name: string; sets?: number; reps?: string }[];
};

type SwapPayload = {
  workout_id: string;
  date?: string;
  day: {
    training_colour?: string;
    client_label?: string;
    blocked?: string[];
    equipment_assumption?: string;
  };
  suggestions: Suggestion[];
};

const FIT_COLOUR = (score: number): string => {
  if (score >= 85) return "#3DBE6E";
  if (score >= 55) return "#E5A048";
  return "#E15A5A";
};


export function SwapWorkoutPicker({
  visible, workoutId, onClose, onApplied,
}: {
  visible: boolean;
  workoutId: string | null;
  onClose: () => void;
  onApplied?: () => void;
}) {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<SwapPayload | null>(null);
  const [applyingId, setApplyingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!workoutId) return;
    try {
      setLoading(true);
      const r = await api<SwapPayload>(`/coach/workouts/${workoutId}/swap-suggestions`);
      setData(r);
    } catch (e: any) {
      Alert.alert("Couldn't load suggestions", e?.message || "Please try again.");
    } finally {
      setLoading(false);
    }
  }, [workoutId]);

  useEffect(() => {
    if (visible) load();
  }, [visible, load]);

  const apply = async (presetId: string, presetTitle: string) => {
    if (!workoutId) return;
    try {
      setApplyingId(presetId);
      await api(`/coach/workouts/${workoutId}/apply-swap`, {
        method: "POST",
        body: { preset_id: presetId },
      });
      onClose();
      onApplied?.();
      Alert.alert("Swapped", `Louis switched this session to "${presetTitle}".`);
    } catch (e: any) {
      Alert.alert("Couldn't apply", e?.message || "Please try again.");
    } finally {
      setApplyingId(null);
    }
  };

  if (!workoutId) return null;

  const day = data?.day;

  return (
    <Modal
      transparent
      visible={visible}
      animationType="slide"
      onRequestClose={onClose}
    >
      <View style={styles.scrim}>
        <View style={styles.sheet}>
          <View style={styles.head}>
            <View style={{ flex: 1 }}>
              <Text style={styles.title}>SWAP WORKOUT</Text>
              <Text style={styles.sub}>
                {data?.date || "…"}
                {day?.client_label ? ` · ${day.client_label}` : ""}
                {day?.training_colour ? `  ·  ${day.training_colour.toUpperCase()}` : ""}
              </Text>
              {day?.blocked && day.blocked.length > 0 ? (
                <Text style={styles.blockedT} numberOfLines={1}>
                  Skipping: {day.blocked.map((b) => b.replace(/_/g, " ")).join(", ")}
                </Text>
              ) : null}
            </View>
            <Pressable onPress={onClose} hitSlop={12} testID="swp-close">
              <Ionicons name="close" size={26} color={theme.color.text} />
            </Pressable>
          </View>
          <View style={styles.grip} />
          {loading ? (
            <View style={{ padding: 32, alignItems: "center" }}>
              <ActivityIndicator color={theme.color.brand} />
            </View>
          ) : (
            <ScrollView contentContainerStyle={{ padding: theme.space.md, paddingBottom: 40 }}>
              {(data?.suggestions || []).length === 0 ? (
                <Text style={styles.emptyT}>
                  No safe alternatives for this day. Try the full editor.
                </Text>
              ) : (
                (data?.suggestions || []).map((s) => {
                  const fitColour = FIT_COLOUR(s.fit_score);
                  const applying = applyingId === s.id;
                  return (
                    <View key={s.id} style={styles.card} testID={`swp-preset-${s.id}`}>
                      <View style={styles.cardTop}>
                        <View style={{ flex: 1 }}>
                          <Text style={styles.cardTitle} numberOfLines={1}>{s.title}</Text>
                          <Text style={styles.cardMeta} numberOfLines={1}>
                            {s.focus.toUpperCase()} · {s.duration_min}m · {s.location}
                          </Text>
                        </View>
                        <View style={[styles.fitPill, { backgroundColor: fitColour }]}>
                          <Text style={styles.fitPillT}>{s.fit_score} fit</Text>
                        </View>
                      </View>
                      <Text style={styles.cardRat} numberOfLines={3}>{s.rationale}</Text>
                      <View style={styles.exList}>
                        {s.exercises.slice(0, 4).map((e, i) => (
                          <Text key={i} style={styles.exLine} numberOfLines={1}>
                            • {e.name}
                            {e.sets && e.reps ? ` — ${e.sets}×${e.reps}` : ""}
                          </Text>
                        ))}
                        {s.exercises.length > 4 ? (
                          <Text style={styles.exMore}>
                            +{s.exercises.length - 4} more
                          </Text>
                        ) : null}
                      </View>
                      <Pressable
                        testID={`swp-apply-${s.id}`}
                        onPress={() => apply(s.id, s.title)}
                        disabled={applying || applyingId !== null}
                        style={[styles.applyBtn, applying && { opacity: 0.6 }]}
                      >
                        {applying ? (
                          <ActivityIndicator size="small" color="#fff" />
                        ) : (
                          <>
                            <Ionicons name="swap-horizontal" size={14} color="#fff" />
                            <Text style={styles.applyBtnT}>APPLY THIS SESSION</Text>
                          </>
                        )}
                      </Pressable>
                    </View>
                  );
                })
              )}
            </ScrollView>
          )}
        </View>
      </View>
    </Modal>
  );
}


const styles = StyleSheet.create({
  scrim: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  sheet: {
    backgroundColor: theme.color.surface,
    borderTopLeftRadius: 18, borderTopRightRadius: 18,
    maxHeight: "90%",
  },
  head: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start",
    paddingHorizontal: theme.space.lg, paddingTop: theme.space.md,
  },
  title: { color: theme.color.text, fontSize: 12, fontWeight: "900", letterSpacing: 2 },
  sub: { color: theme.color.textMuted, fontSize: 11, marginTop: 4, letterSpacing: 0.5 },
  blockedT: { color: theme.color.textDim, fontSize: 10, marginTop: 4, fontStyle: "italic" },
  grip: {
    alignSelf: "center", marginVertical: 8,
    width: 40, height: 4, borderRadius: 2,
    backgroundColor: theme.color.border,
  },
  emptyT: { color: theme.color.textMuted, textAlign: "center", padding: 30 },
  card: {
    padding: theme.space.md,
    borderRadius: theme.radius.md,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
    marginBottom: theme.space.sm,
  },
  cardTop: { flexDirection: "row", alignItems: "flex-start", gap: 8 },
  cardTitle: { color: theme.color.text, fontSize: 15, fontWeight: "900" },
  cardMeta: { color: theme.color.textMuted, fontSize: 11, marginTop: 3, letterSpacing: 0.3 },
  cardRat: { color: theme.color.textDim, fontSize: 12, marginTop: 8, lineHeight: 17 },
  fitPill: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: theme.radius.pill },
  fitPillT: { color: "#fff", fontSize: 9, fontWeight: "900", letterSpacing: 0.8 },
  exList: { marginTop: 8, gap: 3 },
  exLine: { color: theme.color.text, fontSize: 12 },
  exMore: { color: theme.color.textMuted, fontSize: 11, marginTop: 3, fontStyle: "italic" },
  applyBtn: {
    marginTop: theme.space.md,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: theme.color.brand,
    paddingVertical: 12, borderRadius: theme.radius.sm,
  },
  applyBtnT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 1 },
});
