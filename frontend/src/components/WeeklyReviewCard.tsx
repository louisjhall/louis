/**
 * WeeklyReviewCard — Iter 94w
 *
 * Sunday weekly-review card shown on the client home. Presents Louis's
 * summary of the week plus the two required actions: Complete Check-In
 * and Update Progress. Once both are done a coach task fires server-side
 * and this card flips into "Weekly Review Ready" state.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, Image, Modal, ScrollView, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast } from "@/src/lib/ux";

const LOUIS_IMG = require("../../assets/louis/louis_avatar.png");

type Review = {
  week_start: string;
  week_end: string;
  message_lines: string[];
  training: { planned: number; completed: number; missed: number; adherence_pct: number | null; key_planned: number; key_completed: number };
  nutrition: { days_logged: number; avg_calories: number; avg_protein_g: number };
  habits: { pct: number | null };
  checkin_status: "complete" | "incomplete";
  progress_status: "complete" | "incomplete";
  review_ready_for_louis: boolean;
  video_review_status: string;
  has_progress: boolean;
};

export function WeeklyReviewCard({ refreshKey = 0 }: { refreshKey?: number }) {
  const router = useRouter();
  const [r, setR] = useState<Review | null>(null);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const doc = await api<Review>("/weekly-review/current");
      setR(doc);
    } catch { /* ignore */ }
  }, []);
  useEffect(() => { load(); }, [load, refreshKey]);

  // Louis's weekly review + progress-update prompt is a SUNDAY-only ritual.
  // We hide the card on every other day so crew aren't nagged mid-week.
  // If the client has already completed BOTH actions on Sunday, we keep the
  // "review ready" state visible until Monday end-of-day so they see the
  // outcome, then it disappears until next Sunday.
  const showCard = (() => {
    if (!r) return false;
    const dow = new Date().getDay(); // 0=Sun … 6=Sat
    if (dow === 0) return true; // Sunday
    const both = r.checkin_status === "complete" && r.progress_status === "complete";
    if (dow === 1 && both) return true; // Monday tail — only if already completed
    return false;
  })();
  if (!showCard || !r) return null;

  const both = r.checkin_status === "complete" && r.progress_status === "complete";
  const markCheckin = async () => {
    setSaving(true);
    try { const d = await api<any>("/weekly-review/checkin-complete", { method: "POST", body: {} }); setR(d.review); toast("Check-in complete.", "success"); }
    catch (e: any) { toast(e?.message || "Couldn't save.", "error"); }
    finally { setSaving(false); }
  };
  const markProgress = () => {
    setOpen(false);
    router.push("/progress" as any);
  };

  return (
    <>
      <View style={styles.card} testID="weekly-review-card">
        <View style={styles.headRow}>
          <Image source={LOUIS_IMG} style={styles.avatar} />
          <View style={{ flex: 1 }}>
            <Text style={styles.eyebrow}>{both ? "WEEKLY REVIEW READY" : "WEEKLY REVIEW"}</Text>
            <Text style={styles.body} numberOfLines={2}>
              {both
                ? "Thanks — Louis has what he needs to review your week. He'll come back with a short video."
                : "Louis has summarised your week so far. Complete your check-in and update your Progress tab so he can review it properly."}
            </Text>
          </View>
        </View>
        {!both ? (
          <View style={styles.actions}>
            <Pressable onPress={() => setOpen(true)} style={[styles.btn, styles.btnPrimary]} testID="wr-open">
              <Text style={styles.btnPrimaryT}>VIEW WEEKLY REVIEW</Text>
            </Pressable>
          </View>
        ) : null}
      </View>

      <Modal visible={open} transparent animationType="slide" onRequestClose={() => setOpen(false)}>
        <View style={styles.modalRoot}>
          <Pressable style={styles.modalBack} onPress={() => setOpen(false)} />
          <View style={styles.sheet}>
            <View style={styles.sheetHead}>
              <Image source={LOUIS_IMG} style={styles.avatar} />
              <View style={{ flex: 1 }}>
                <Text style={styles.coachName}>Louis Hall</Text>
                <Text style={styles.coachRole}>CrewFit Coach · Weekly Review</Text>
              </View>
              <Pressable onPress={() => setOpen(false)} hitSlop={12}><Ionicons name="close" size={22} color={theme.color.textMuted} /></Pressable>
            </View>
            <ScrollView style={{ maxHeight: 500 }}>
              {r.message_lines.map((l, i) => (
                <Text key={i} style={l === "" ? styles.spacer : /^(Training|Nutrition|Habits|Roster|Progress):$/.test(l) ? styles.h : styles.p}>{l}</Text>
              ))}
              <View style={styles.statuses}>
                <StatusPill label="CHECK-IN" done={r.checkin_status === "complete"} />
                <StatusPill label="PROGRESS" done={r.progress_status === "complete"} />
              </View>
            </ScrollView>
            <View style={styles.footerBtns}>
              <Pressable
                onPress={markCheckin}
                disabled={saving || r.checkin_status === "complete"}
                style={[styles.btn, r.checkin_status === "complete" ? styles.btnDone : styles.btnPrimary]}
                testID="wr-checkin"
              >
                {saving ? <ActivityIndicator color="#fff" /> : (
                  <Text style={styles.btnPrimaryT}>{r.checkin_status === "complete" ? "CHECK-IN DONE ✓" : "COMPLETE CHECK-IN"}</Text>
                )}
              </Pressable>
              <Pressable onPress={markProgress} style={[styles.btn, r.progress_status === "complete" ? styles.btnDone : styles.btnGhost]} testID="wr-progress">
                <Text style={r.progress_status === "complete" ? styles.btnPrimaryT : styles.btnGhostT}>
                  {r.progress_status === "complete" ? "PROGRESS DONE ✓" : "UPDATE PROGRESS"}
                </Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </>
  );
}

function StatusPill({ label, done }: { label: string; done: boolean }) {
  return (
    <View style={[styles.pill, { backgroundColor: done ? theme.color.green : theme.color.surface3 }]}>
      <Ionicons name={done ? "checkmark-circle" : "ellipse-outline"} size={12} color={done ? "#fff" : theme.color.textMuted} />
      <Text style={[styles.pillT, { color: done ? "#fff" : theme.color.textMuted }]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: theme.color.surface2, borderRadius: theme.radius.md,
    borderWidth: 1, borderColor: theme.color.brand,
    padding: 12, marginBottom: 12,
  },
  headRow: { flexDirection: "row", gap: 10, alignItems: "center" },
  avatar: { width: 40, height: 40, borderRadius: 20, backgroundColor: theme.color.surface3 },
  eyebrow: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 2 },
  body: { color: theme.color.text, fontSize: 12, marginTop: 4, lineHeight: 17 },
  actions: { marginTop: 10 },
  btn: { flexDirection: "row", justifyContent: "center", alignItems: "center", padding: 10, borderRadius: 8 },
  btnPrimary: { backgroundColor: theme.color.brand },
  btnPrimaryT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  btnGhost: { borderWidth: 1, borderColor: theme.color.border, backgroundColor: "transparent" },
  btnGhostT: { color: theme.color.text, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  btnDone: { backgroundColor: theme.color.green },

  modalRoot: { flex: 1, justifyContent: "flex-end" },
  modalBack: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.6)" },
  sheet: { backgroundColor: theme.color.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: 16, paddingBottom: 24, maxHeight: "90%" },
  sheetHead: { flexDirection: "row", gap: 10, alignItems: "center", marginBottom: 10 },
  coachName: { color: theme.color.text, fontSize: 14, fontWeight: "900" },
  coachRole: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 1.2, fontWeight: "800" },

  spacer: { height: 6 },
  h: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5, marginTop: 6 },
  p: { color: theme.color.text, fontSize: 13, lineHeight: 19 },

  statuses: { flexDirection: "row", gap: 8, marginTop: 12 },
  pill: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 12 },
  pillT: { fontSize: 10, fontWeight: "900", letterSpacing: 1 },

  footerBtns: { flexDirection: "row", gap: 8, marginTop: 12 },
});
