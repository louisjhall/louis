/**
 * RecoverySheet — Iter 94s
 *
 * Bottom-sheet modal that walks a client through recovering a missed workout.
 * Backed by:
 *   POST /workouts/{id}/recovery/suggestions  → suggested slots + rating
 *   POST /workouts/{id}/recover               → move / replace_today
 *   POST /workouts/{id}/skip                  → mark skipped
 *
 * All copy is client-safe (no AI wording). Safety checks are enforced
 * server-side; the sheet just surfaces the ratings + reasons.
 */
import React, { useEffect, useState, useCallback } from "react";
import {
  View, Text, StyleSheet, Modal, Pressable, ScrollView, ActivityIndicator, Linking,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast as uxToast } from "@/src/lib/ux";

type Missed = {
  id: string;
  title?: string;
  date: string;
  days_ago?: number;
  priority?: string;
  key_session?: boolean;
  recommendation?: string;
};

type Suggestion = {
  date: string;
  days_from_today: number;
  rating: "good" | "okay" | "not_ideal" | "blocked";
  reason: string;
  existing_workout?: { title?: string; hard?: boolean; completed?: boolean } | null;
  roster?: { day_type?: string; layover_city?: string } | null;
  blocked?: boolean;
};

const WHATSAPP_NUMBER = process.env.EXPO_PUBLIC_WHATSAPP_NUMBER || "";

function ratingLabel(r: string): string {
  switch (r) {
    case "good":       return "GOOD OPTION";
    case "okay":       return "OKAY";
    case "not_ideal":  return "NOT IDEAL";
    case "blocked":    return "NOT AVAILABLE";
    default:           return String(r).toUpperCase();
  }
}
function ratingColor(r: string): string {
  switch (r) {
    case "good":       return theme.color.green;
    case "okay":       return theme.color.amber;
    case "not_ideal":  return theme.color.red;
    case "blocked":    return theme.color.textDim;
    default:           return theme.color.textMuted;
  }
}

function niceDate(iso: string): string {
  try {
    const d = new Date(`${iso}T00:00:00`);
    return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
  } catch { return iso; }
}

export function RecoverySheet({
  workout,
  visible,
  onClose,
  onDone,
}: {
  workout: Missed | null;
  visible: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  const [loading, setLoading] = useState(true);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [globalReco, setGlobalReco] = useState<{ recommendation: string; copy: string } | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!workout) return;
    setLoading(true);
    try {
      const r = await api<any>(`/recovery/${workout.id}/suggestions`, { method: "POST", body: {} });
      setSuggestions(r?.suggestions || []);
      setGlobalReco({
        recommendation: r?.recommendation || "recover",
        copy: r?.recommendation_copy || "",
      });
    } catch (e: any) {
      uxToast(e?.message || "Couldn't load recovery options.", "error");
    } finally { setLoading(false); }
  }, [workout]);

  useEffect(() => {
    if (visible && workout) load();
  }, [visible, workout, load]);

  const doRecover = useCallback(async (target_date: string, action: string) => {
    if (!workout || saving) return;
    setSaving(true);
    try {
      const r = await api<any>(`/recovery/${workout.id}/recover`, {
        method: "POST",
        body: { target_date, action },
      });
      uxToast(r?.message || "Workout moved.", "success");
      onDone();
      onClose();
    } catch (e: any) {
      uxToast(e?.message || "Couldn't move the workout.", "error");
    } finally { setSaving(false); }
  }, [workout, saving, onDone, onClose]);

  const doSkip = useCallback(async () => {
    if (!workout || saving) return;
    setSaving(true);
    try {
      await api(`/recovery/${workout.id}/skip`, { method: "POST", body: { reason: "Client chose to skip." } });
      uxToast("Session skipped — your plan continues.", "success");
      onDone();
      onClose();
    } catch (e: any) {
      uxToast(e?.message || "Couldn't skip this session.", "error");
    } finally { setSaving(false); }
  }, [workout, saving, onDone, onClose]);

  const askLouis = useCallback(() => {
    const msg = encodeURIComponent(
      `Hi Louis, I missed my session (${workout?.title || ""}) on ${workout?.date || ""} — can you help me decide what to do?`,
    );
    if (WHATSAPP_NUMBER) {
      Linking.openURL(`https://wa.me/${WHATSAPP_NUMBER.replace(/[^\d]/g, "")}?text=${msg}`).catch(() => {});
    } else {
      uxToast("Support link isn't configured on this build.", "info");
    }
  }, [workout]);

  if (!visible || !workout) return null;

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.root}>
        <Pressable style={styles.backdrop} onPress={onClose} />
        <View style={styles.sheet}>
          <View style={styles.handle} />
          <View style={styles.head}>
            <View style={{ flex: 1 }}>
              <Text style={styles.eyebrow}>RECOVER WORKOUT</Text>
              <Text style={styles.title} numberOfLines={2}>{workout.title || "Missed session"}</Text>
              <Text style={styles.sub}>
                Originally {niceDate(workout.date)}
                {workout.days_ago ? ` · ${workout.days_ago} day${workout.days_ago === 1 ? "" : "s"} ago` : ""}
                {workout.key_session ? "  ·  KEY SESSION" : ""}
              </Text>
            </View>
            <Pressable onPress={onClose} testID="rec-close" hitSlop={12}>
              <Ionicons name="close" size={22} color={theme.color.textMuted} />
            </Pressable>
          </View>

          {loading ? (
            <View style={{ padding: 30, alignItems: "center" }}>
              <ActivityIndicator color={theme.color.brand} />
            </View>
          ) : (
            <ScrollView style={{ maxHeight: 520 }}>
              {globalReco?.copy ? (
                <View style={styles.recoCard} testID="rec-global">
                  <Ionicons
                    name={
                      globalReco.recommendation === "skip" ? "close-circle" :
                      globalReco.recommendation === "ask_louis" ? "chatbubble-ellipses" : "checkmark-circle"
                    }
                    size={16}
                    color={theme.color.brand}
                  />
                  <Text style={styles.recoT} numberOfLines={4}>{globalReco.copy}</Text>
                </View>
              ) : null}

              <Text style={styles.sectLbl}>SUITABLE DAYS</Text>
              {suggestions.length === 0 ? (
                <Text style={styles.empty}>No suitable days in the next three weeks.</Text>
              ) : (
                suggestions.map((s) => {
                  const disabled = s.blocked;
                  const isToday = s.days_from_today === 0;
                  const hasExistingHardToday = isToday && !!s.existing_workout && s.existing_workout.hard === true;
                  return (
                    <View
                      key={s.date}
                      style={[styles.slot, disabled && { opacity: 0.5 }]}
                      testID={`rec-slot-${s.date}`}
                    >
                      <View style={styles.slotHead}>
                        <View style={{ flex: 1 }}>
                          <Text style={styles.slotDate}>
                            {isToday ? "Today · " : ""}{niceDate(s.date)}
                          </Text>
                          <Text style={styles.slotReason} numberOfLines={2}>{s.reason}</Text>
                          {s.roster?.day_type ? (
                            <Text style={styles.slotMeta}>
                              Roster: {String(s.roster.day_type).replace(/_/g, " ")}
                              {s.roster.layover_city ? ` · ${s.roster.layover_city}` : ""}
                            </Text>
                          ) : null}
                          {s.existing_workout?.title ? (
                            <Text style={styles.slotMeta}>
                              Existing: {s.existing_workout.title}
                              {s.existing_workout.hard ? " (hard)" : ""}
                            </Text>
                          ) : null}
                        </View>
                        <View style={[styles.ratePill, { backgroundColor: ratingColor(s.rating) }]}>
                          <Text style={styles.ratePillT}>{ratingLabel(s.rating)}</Text>
                        </View>
                      </View>
                      {!disabled ? (
                        <View style={styles.slotActions}>
                          {hasExistingHardToday ? (
                            <Pressable
                              onPress={() => doRecover(s.date, "replace_today")}
                              disabled={saving}
                              style={[styles.slotBtn, styles.slotBtnPrimary]}
                              testID={`rec-replace-${s.date}`}
                            >
                              <Text style={styles.slotBtnPrimaryT}>REPLACE TODAY&apos;S SESSION</Text>
                            </Pressable>
                          ) : (
                            <Pressable
                              onPress={() => doRecover(s.date, isToday ? "add_today" : "move")}
                              disabled={saving}
                              style={[styles.slotBtn, styles.slotBtnPrimary]}
                              testID={`rec-move-${s.date}`}
                            >
                              <Text style={styles.slotBtnPrimaryT}>
                                {isToday ? "DO THIS TODAY" : "MOVE TO THIS DAY"}
                              </Text>
                            </Pressable>
                          )}
                        </View>
                      ) : null}
                    </View>
                  );
                })
              )}
            </ScrollView>
          )}

          <View style={styles.footer}>
            <Pressable
              onPress={doSkip}
              disabled={saving}
              style={styles.footerBtn}
              testID="rec-skip"
            >
              <Ionicons name="close-circle-outline" size={16} color={theme.color.textMuted} />
              <Text style={styles.footerBtnT}>SKIP AND CONTINUE</Text>
            </Pressable>
            <Pressable
              onPress={askLouis}
              disabled={saving}
              style={styles.footerBtn}
              testID="rec-ask"
            >
              <Ionicons name="chatbubble-ellipses" size={16} color={theme.color.brand} />
              <Text style={[styles.footerBtnT, { color: theme.color.brand }]}>MESSAGE LOUIS</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, justifyContent: "flex-end" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.6)" },
  sheet: {
    backgroundColor: theme.color.surface,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingHorizontal: 18,
    paddingTop: 12,
    paddingBottom: 24,
    maxHeight: "88%",
  },
  handle: { alignSelf: "center", width: 44, height: 4, borderRadius: 2, backgroundColor: theme.color.border, marginBottom: 10 },
  head: { flexDirection: "row", alignItems: "flex-start", marginBottom: 12, gap: 12 },
  eyebrow: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 2 },
  title: { color: theme.color.text, fontSize: 18, fontWeight: "900", marginTop: 4 },
  sub: { color: theme.color.textMuted, fontSize: 12, marginTop: 4 },

  recoCard: {
    flexDirection: "row", gap: 10, alignItems: "flex-start",
    padding: 12, marginBottom: 12, borderRadius: 10,
    backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand,
  },
  recoT: { color: theme.color.text, fontSize: 13, lineHeight: 18, flex: 1 },

  sectLbl: { color: theme.color.textMuted, fontSize: 10, fontWeight: "900", letterSpacing: 2, marginBottom: 8, marginTop: 4 },
  empty: { color: theme.color.textMuted, fontSize: 12, marginBottom: 10 },

  slot: { padding: 12, borderRadius: 10, borderWidth: 1, borderColor: theme.color.border, marginBottom: 8, backgroundColor: theme.color.surface2 },
  slotHead: { flexDirection: "row", alignItems: "flex-start", gap: 10 },
  slotDate: { color: theme.color.text, fontSize: 14, fontWeight: "900" },
  slotReason: { color: theme.color.textMuted, fontSize: 12, marginTop: 3, lineHeight: 17 },
  slotMeta: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },
  ratePill: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 10 },
  ratePillT: { color: "#fff", fontSize: 9, fontWeight: "900", letterSpacing: 1.5 },

  slotActions: { marginTop: 10, flexDirection: "row", gap: 8 },
  slotBtn: { flex: 1, padding: 10, borderRadius: 8, alignItems: "center" },
  slotBtnPrimary: { backgroundColor: theme.color.brand },
  slotBtnPrimaryT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },

  footer: { flexDirection: "row", gap: 10, marginTop: 12 },
  footerBtn: {
    flex: 1, flexDirection: "row", gap: 6, alignItems: "center", justifyContent: "center",
    padding: 12, borderRadius: 10, borderWidth: 1, borderColor: theme.color.border,
  },
  footerBtnT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
});
