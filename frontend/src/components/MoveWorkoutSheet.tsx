/**
 * MoveWorkoutSheet
 * ----------------
 * Bottom-sheet modal that lets a client move a session to a different day
 * on their calendar (up to +14 days from today).
 *
 * Design principles (per Louis's brief):
 *   • Framed as "you're rearranging YOUR week" — never mentions AI.
 *   • Duty-aware: flight / standby days are visually marked as risky.
 *   • Existing workout on target date → shows the swap partner so it's clear.
 *   • Louis is auto-notified via the coach change log (server-side).
 *
 * Backed by:
 *   GET  /api/calendar/range?from=&to=   (for target-day roster + workouts)
 *   POST /api/workouts/{id}/move         (executes the swap)
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Modal, Pressable, ScrollView, ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast as uxToast } from "@/src/lib/ux";

type Duty = "flight" | "standby" | "layover" | "training" | "rest" | "home" | "unknown";

type TargetDay = {
  date: string;
  is_today: boolean;
  is_past: boolean;
  duty: Duty;
  duty_label: string;
  layover_city?: string | null;
  existing_workout?: { title?: string; completed?: boolean; key?: boolean } | null;
  rating: "good" | "okay" | "risky" | "blocked";
  reason: string;
};

type Source = {
  workoutId: string;
  fromDate: string;
  title?: string | null;
  key_session?: boolean | null;
};

function localToday(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

function niceDate(iso: string): string {
  try {
    const d = new Date(`${iso}T00:00:00`);
    return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
  } catch { return iso; }
}

function classifyDuty(dayType?: string | null): { duty: Duty; label: string } {
  const t = String(dayType || "").toLowerCase();
  if (!t || t === "home_day" || t === "home") return { duty: "home", label: "Home" };
  if (t === "rest" || t === "off" || t === "day_off" || t === "annual_leave") return { duty: "rest", label: "Rest / Off" };
  if (t.includes("layover")) return { duty: "layover", label: "Layover" };
  if (t === "standby" || t === "airport_standby") return { duty: "standby", label: "Standby" };
  if (t === "sim" || t === "training" || t === "ground_school") return { duty: "training", label: "Training" };
  if (t.includes("flight") || t === "long_haul" || t === "short_haul" || t === "flying" || t === "night_flight" || t === "long-haul") {
    return { duty: "flight", label: "Flying" };
  }
  return { duty: "unknown", label: t.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) };
}

function ratingFor(day: {
  duty: Duty;
  existing_workout?: TargetDay["existing_workout"];
  isSource?: boolean;
  isPast?: boolean;
}): { rating: TargetDay["rating"]; reason: string } {
  if (day.isSource) return { rating: "blocked", reason: "This is where the session is now" };
  if (day.isPast)   return { rating: "blocked", reason: "Can't move to a past date" };
  if (day.existing_workout?.completed) return { rating: "blocked", reason: "Already completed" };
  if (day.duty === "flight") return { rating: "risky",  reason: "You're flying — heavy training not ideal" };
  if (day.duty === "standby") return { rating: "okay", reason: "On standby — session may need to move again" };
  if (day.existing_workout?.key) return { rating: "risky", reason: "Would swap with a key session" };
  if (day.existing_workout)      return { rating: "okay",  reason: "Will swap with the session on this day" };
  if (day.duty === "layover")    return { rating: "good",  reason: "Layover — good training window" };
  if (day.duty === "rest" || day.duty === "home") return { rating: "good", reason: "Free day" };
  return { rating: "good", reason: "Open" };
}

function ratingColor(r: TargetDay["rating"]): string {
  switch (r) {
    case "good":    return theme.color.green;
    case "okay":    return theme.color.amber;
    case "risky":   return theme.color.red;
    case "blocked": return theme.color.textDim;
    default:        return theme.color.textMuted;
  }
}

function ratingLabel(r: TargetDay["rating"]): string {
  switch (r) {
    case "good":    return "GOOD";
    case "okay":    return "OKAY";
    case "risky":   return "RISKY";
    case "blocked": return "BLOCKED";
    default:        return String(r).toUpperCase();
  }
}


export function MoveWorkoutSheet({
  visible,
  source,
  onClose,
  onMoved,
}: {
  visible: boolean;
  source: Source | null;
  onClose: () => void;
  onMoved?: (toDate: string) => void;
}) {
  const [days, setDays] = useState<TargetDay[]>([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState<string | null>(null);

  const today = localToday();

  const load = useCallback(async () => {
    if (!source) return;
    setLoading(true);
    try {
      const from = today;
      const to = addDays(today, 14);
      const r = await api<any>(`/calendar/range?from=${from}&to=${to}`);
      const rawDays = Array.isArray(r?.days) ? r.days : [];
      const mapped: TargetDay[] = rawDays.map((c: any) => {
        const { duty, label } = classifyDuty(c?.roster_day?.day_type);
        const isSource = c.date === source.fromDate;
        const isPast = c.date < today;
        const existing = c?.workout
          ? { title: c.workout.title, completed: !!c.workout.completed, key: !!c.workout.key_session }
          : null;
        const { rating, reason } = ratingFor({ duty, existing_workout: existing, isSource, isPast });
        return {
          date: c.date,
          is_today: !!c.is_today,
          is_past: isPast,
          duty,
          duty_label: label,
          layover_city: c?.roster_day?.layover_city || null,
          existing_workout: existing,
          rating,
          reason,
        };
      });
      setDays(mapped);
    } catch {
      setDays([]);
    } finally {
      setLoading(false);
    }
  }, [source, today]);

  useEffect(() => {
    if (visible && source) load();
    else setDays([]);
  }, [visible, source, load]);

  const submit = async (toDate: string) => {
    if (!source) return;
    try {
      setSubmitting(toDate);
      Haptics.selectionAsync().catch(() => {});
      await api(`/workouts/${source.workoutId}/move`, {
        method: "POST",
        body: JSON.stringify({ to_date: toDate }),
      });
      uxToast(`Moved to ${niceDate(toDate)} — Louis has been notified`);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      onMoved?.(toDate);
      onClose();
    } catch (e: any) {
      const msg = String(e?.message || e || "Couldn't move — try another day");
      uxToast(msg.length > 90 ? "Couldn't move — try another day" : msg);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error).catch(() => {});
    } finally {
      setSubmitting(null);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <View style={styles.header}>
            <View style={{ flex: 1 }}>
              <Text style={styles.title}>MOVE SESSION</Text>
              <Text style={styles.sub} numberOfLines={2}>
                {source?.title || "Session"} · currently {source?.fromDate ? niceDate(source.fromDate) : ""}
              </Text>
            </View>
            <Pressable onPress={onClose} hitSlop={10} style={styles.close} testID="move-close">
              <Ionicons name="close" size={20} color={theme.color.text} />
            </Pressable>
          </View>

          <Text style={styles.help}>
            Pick a new day. Flight days show as{" "}
            <Text style={{ color: theme.color.red, fontWeight: "800" }}>RISKY</Text>. If the target has a session it will swap with yours.
          </Text>

          {loading ? (
            <View style={{ paddingVertical: 40 }}>
              <ActivityIndicator color={theme.color.brand} />
            </View>
          ) : (
            <ScrollView style={{ maxHeight: 460 }} contentContainerStyle={{ paddingBottom: 20 }}>
              {days.map((d) => {
                const disabled = d.rating === "blocked" || submitting !== null;
                const isBusy = submitting === d.date;
                return (
                  <Pressable
                    key={d.date}
                    disabled={disabled}
                    onPress={() => submit(d.date)}
                    style={[
                      styles.dayRow,
                      d.is_today && styles.dayRowToday,
                      d.rating === "blocked" && { opacity: 0.5 },
                    ]}
                    testID={`move-target-${d.date}`}
                  >
                    <View style={{ flex: 1, minWidth: 0 }}>
                      <View style={styles.dayHead}>
                        <Text style={styles.dayDate}>
                          {d.is_today ? "TODAY · " : ""}{niceDate(d.date).toUpperCase()}
                        </Text>
                        <View style={[styles.badge, { backgroundColor: ratingColor(d.rating) }]}>
                          <Text style={styles.badgeT}>{ratingLabel(d.rating)}</Text>
                        </View>
                      </View>
                      <Text style={styles.dayMeta} numberOfLines={1}>
                        {d.duty_label}
                        {d.layover_city ? ` · ${d.layover_city}` : ""}
                        {d.existing_workout ? `  ·  swap with "${d.existing_workout.title || "session"}"` : ""}
                      </Text>
                      <Text style={styles.dayReason} numberOfLines={1}>{d.reason}</Text>
                    </View>
                    {isBusy ? (
                      <ActivityIndicator color={theme.color.brand} size="small" />
                    ) : (
                      <Ionicons
                        name={d.rating === "blocked" ? "close-circle-outline" : "chevron-forward"}
                        size={18}
                        color={d.rating === "blocked" ? theme.color.textDim : theme.color.brand}
                      />
                    )}
                  </Pressable>
                );
              })}
            </ScrollView>
          )}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.55)",
    justifyContent: "flex-end",
  },
  sheet: {
    backgroundColor: theme.color.surface,
    borderTopLeftRadius: 18,
    borderTopRightRadius: 18,
    paddingHorizontal: 16,
    paddingTop: 14,
    paddingBottom: 24,
    borderTopWidth: 1,
    borderColor: theme.color.border,
  },
  header: {
    flexDirection: "row",
    alignItems: "flex-start",
    marginBottom: 8,
  },
  title: {
    color: theme.color.brand,
    fontSize: 11,
    fontWeight: "900",
    letterSpacing: 2,
  },
  sub: {
    color: theme.color.textMuted,
    fontSize: 12,
    fontWeight: "700",
    marginTop: 3,
  },
  close: {
    padding: 6,
    borderRadius: 8,
    backgroundColor: theme.color.surface2,
    borderWidth: 1,
    borderColor: theme.color.border,
  },
  help: {
    color: theme.color.textMuted,
    fontSize: 12,
    lineHeight: 17,
    marginBottom: 12,
  },
  dayRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingVertical: 12,
    paddingHorizontal: 12,
    borderRadius: 10,
    backgroundColor: theme.color.surface2,
    borderWidth: 1,
    borderColor: theme.color.border,
    marginBottom: 8,
  },
  dayRowToday: {
    borderColor: theme.color.brand,
    backgroundColor: theme.color.brandTint,
  },
  dayHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 4,
  },
  dayDate: {
    color: theme.color.text,
    fontSize: 12,
    fontWeight: "900",
    letterSpacing: 1.5,
    flex: 1,
  },
  dayMeta: {
    color: theme.color.textMuted,
    fontSize: 11,
    marginTop: 1,
  },
  dayReason: {
    color: theme.color.textDim,
    fontSize: 11,
    marginTop: 3,
    fontStyle: "italic",
  },
  badge: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 8,
  },
  badgeT: {
    color: "#fff",
    fontSize: 9,
    fontWeight: "900",
    letterSpacing: 1,
  },
});
