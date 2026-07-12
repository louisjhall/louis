/**
 * PersonalActivityCard — used on the client Today/Home screen (today's activity
 * with Atlas suggestion + inline actions) and inside the Add Activity flow list.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";
import {
  todayActivities, completeActivity, applySuggestion, deleteActivity,
  type PersonalActivity, INTENSITY_LABEL,
} from "@/src/lib/personalActivities";

const CONFLICT_TINT: Record<string, { bg: string; border: string; icon: any; label: string }> = {
  high: { bg: "rgba(220, 38, 38, 0.12)", border: theme.color.red, icon: "warning", label: "SAME-DAY CONFLICT" },
  medium: { bg: "rgba(245, 158, 11, 0.12)", border: theme.color.amber, icon: "alert-circle", label: "SUGGESTED ADJUSTMENT" },
  review: { bg: theme.color.brandTint, border: theme.color.brand, icon: "chatbubble-ellipses", label: "COACH REVIEW" },
  none: { bg: theme.color.surface2, border: theme.color.border, icon: "leaf", label: "" },
};

export function TodayPersonalActivities() {
  const [rows, setRows] = useState<PersonalActivity[]>([]);
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await todayActivities();
      setRows(r);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const doAction = async (row: PersonalActivity, kind: string, target_date?: string) => {
    setApplying(row.id);
    try {
      const r = await applySuggestion(row.id, kind, { target_date });
      if (r?.applied === false) {
        Alert.alert("No change", r.reason || "Nothing to do.");
      } else {
        Alert.alert("Done", kindMessage(kind, r));
      }
      await load();
    } catch (e: any) {
      Alert.alert("Couldn't apply", e?.message || "Please try again");
    } finally {
      setApplying(null);
    }
  };

  const markComplete = async (row: PersonalActivity, status: "completed" | "skipped", effort?: string) => {
    try {
      await completeActivity(row.id, status, effort);
      await load();
    } catch (e: any) {
      Alert.alert("Couldn't save", e?.message || "Please try again");
    }
  };

  const remove = async (row: PersonalActivity) => {
    Alert.alert(
      "Remove activity?",
      row.recurrence !== "once"
        ? "This is a recurring activity. Delete just this occurrence?"
        : "This will remove this activity from your schedule.",
      [
        { text: "Cancel", style: "cancel" },
        { text: "Delete", style: "destructive", onPress: async () => { await deleteActivity(row.id, "one"); await load(); } },
        ...(row.recurrence !== "once" ? [{ text: "Delete series", style: "destructive" as const, onPress: async () => { await deleteActivity(row.id, "series"); await load(); } }] : []),
      ],
    );
  };

  if (loading) return null;
  if (!rows.length) return null;

  return (
    <View style={styles.wrap}>
      <Text style={styles.sectionTitle}>TODAY&apos;S ACTIVITY</Text>
      {rows.map((row) => {
        const sug = row.atlas_suggestion;
        const tint = CONFLICT_TINT[sug?.conflict_level || "none"] || CONFLICT_TINT.none;
        const isPast = row.status !== "planned";
        return (
          <View key={row.id} style={[styles.card, { borderColor: tint.border, backgroundColor: tint.bg }]} testID={`personal-activity-${row.id}`}>
            <View style={styles.headRow}>
              <View style={styles.headIcon}>
                <Ionicons name="fitness" size={16} color={theme.color.brand} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.name}>{row.activity_name}</Text>
                <Text style={styles.meta}>
                  Personal Activity · {row.duration_minutes} min · {INTENSITY_LABEL[row.intensity as keyof typeof INTENSITY_LABEL] || row.intensity}
                  {row.start_time ? ` · ${row.start_time}` : ""}
                </Text>
              </View>
              <Pressable onPress={() => remove(row)} hitSlop={8} testID={`personal-activity-remove-${row.id}`}>
                <Ionicons name="trash-outline" size={16} color={theme.color.textDim} />
              </Pressable>
            </View>

            {sug ? (
              <View style={styles.sugBox}>
                {tint.label ? (
                  <View style={styles.sugTagRow}>
                    <Ionicons name={tint.icon} size={11} color={tint.border} />
                    <Text style={[styles.sugTag, { color: tint.border }]}>{tint.label}</Text>
                  </View>
                ) : null}
                <Text style={styles.sugBody}>{sug.body}</Text>
                {!isPast && sug.actions?.length ? (
                  <View style={styles.actionsRow}>
                    {sug.actions.map((a) => {
                      const primary = a.kind === sug.recommended_action;
                      const busy = applying === row.id;
                      return (
                        <Pressable
                          key={a.id}
                          onPress={() => doAction(row, a.kind, a.target_date)}
                          disabled={busy}
                          style={[styles.actionBtn, primary && styles.actionBtnPrimary, busy && { opacity: 0.4 }]}
                          testID={`personal-activity-action-${row.id}-${a.kind}`}
                        >
                          {busy && primary ? (
                            <ActivityIndicator size="small" color={primary ? "#fff" : theme.color.brand} />
                          ) : (
                            <Text style={[styles.actionT, primary && styles.actionTPrimary]}>{a.label}</Text>
                          )}
                        </Pressable>
                      );
                    })}
                  </View>
                ) : null}
              </View>
            ) : null}

            {isPast ? (
              <Text style={styles.doneT}>
                <Ionicons name="checkmark-circle" size={12} color={theme.color.green} /> {row.status.toUpperCase()}{row.perceived_effort ? ` · ${row.perceived_effort}` : ""}
              </Text>
            ) : (
              <View style={styles.completeRow}>
                <Pressable onPress={() => markComplete(row, "completed", "moderate")} style={styles.completeBtn} testID={`personal-activity-complete-${row.id}`}>
                  <Ionicons name="checkmark" size={12} color={theme.color.green} />
                  <Text style={styles.completeT}>MARK COMPLETE</Text>
                </Pressable>
                <Pressable onPress={() => markComplete(row, "skipped")} style={styles.skipBtn} testID={`personal-activity-skip-${row.id}`}>
                  <Text style={styles.skipT}>SKIP</Text>
                </Pressable>
              </View>
            )}
          </View>
        );
      })}
    </View>
  );
}

function kindMessage(kind: string, r: any): string {
  if (kind === "move_workout") return `Workout moved to ${r?.moved_to}.`;
  if (kind === "reduce_workout") return "Workout switched to mobility.";
  if (kind === "ask_coach") return "Louis has been asked to review.";
  if (kind === "replace_workout") return "Workout replaced with your activity.";
  return "Saved.";
}

const styles = StyleSheet.create({
  wrap: { marginTop: theme.space.lg, gap: 8 },
  sectionTitle: { color: theme.color.textMuted, letterSpacing: 2, fontSize: 11, fontWeight: "800", marginBottom: 8 },
  card: {
    borderRadius: 12, borderWidth: 1, padding: 14, gap: 10,
  },
  headRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  headIcon: {
    width: 32, height: 32, borderRadius: 16, backgroundColor: theme.color.surface2,
    alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: theme.color.brand,
  },
  name: { color: theme.color.text, fontSize: 15, fontWeight: "800" },
  meta: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },
  sugBox: { gap: 6 },
  sugTagRow: { flexDirection: "row", alignItems: "center", gap: 4 },
  sugTag: { fontSize: 9, letterSpacing: 1.5, fontWeight: "900" },
  sugBody: { color: theme.color.text, fontSize: 12, lineHeight: 17 },
  actionsRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 4 },
  actionBtn: {
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  actionBtnPrimary: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  actionT: { color: theme.color.text, fontSize: 11, fontWeight: "800", letterSpacing: 0.5 },
  actionTPrimary: { color: "#fff" },
  completeRow: { flexDirection: "row", gap: 8, marginTop: 2 },
  completeBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    paddingVertical: 8, borderRadius: 8,
    backgroundColor: "rgba(34,197,94,0.10)", borderWidth: 1, borderColor: theme.color.green,
  },
  completeT: { color: theme.color.green, fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },
  skipBtn: {
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: 8,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  skipT: { color: theme.color.textMuted, fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },
  doneT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700" },
});
