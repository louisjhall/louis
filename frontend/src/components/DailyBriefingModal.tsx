/**
 * DailyBriefingModal — Iter 94u
 *
 * "Today's Briefing" pop-up voiced by Louis. Shows once per local day when
 * the client opens the app (state persisted server-side via
 * /daily-briefing/dismiss and locally via AsyncStorage). All copy is
 * Louis-voiced — no AI / generated wording.
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, Modal, Pressable, ScrollView, Image, Linking,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

const LOUIS_IMG = require("../../assets/louis/louis_ref.png");

type Habit = { title: string; done?: boolean };
type Briefing = {
  id: string;
  title: string;
  greeting: string;
  body_lines: string[];
  workout_focus: string;
  nutrition_focus: string;
  recovery_focus: string;
  layover_focus?: string | null;
  main_action: { label: string; route: string };
  habits: Habit[];
  missed_yesterday?: { id: string; title?: string; date?: string } | null;
  timezone: string;
  city?: string | null;
  date_local: string;
  coach: { name: string; role: string; whatsapp_url?: string };
  dismissed_at?: string | null;
};

const STORAGE_KEY = "briefing_dismissed_local_date";

export function DailyBriefingModal() {
  const router = useRouter();
  const [b, setB] = useState<Briefing | null>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const r = await api<any>("/daily-briefing/today");
        if (!r?.briefing || !r?.enabled) return;
        if (r.briefing.dismissed_at) return;
        // Client-side idempotency — if we already showed it today, don't reopen.
        const last = await AsyncStorage.getItem(STORAGE_KEY);
        if (last === r.briefing.date_local) return;
        setB(r.briefing as Briefing);
        setVisible(true);
      } catch { /* silent */ }
    })();
  }, []);

  const dismiss = async () => {
    setVisible(false);
    if (b?.date_local) {
      try { await AsyncStorage.setItem(STORAGE_KEY, b.date_local); } catch {}
    }
    try { await api("/daily-briefing/dismiss", { method: "POST", body: {} }); } catch {}
  };

  const goAction = () => {
    if (!b) return;
    const route = b.main_action?.route || "/";
    dismiss();
    setTimeout(() => router.push(route as any), 220);
  };

  const messageLouis = () => {
    const url = b?.coach?.whatsapp_url || process.env.EXPO_PUBLIC_WHATSAPP_URL || "";
    if (url) Linking.openURL(url).catch(() => {});
  };

  const parts = useMemo(() => {
    if (!b) return { pre: "", extras: [] as string[] };
    // First line is the greeting; if the second non-empty line is not one of
    // the section labels ("Workout:" etc.), it's the layover/opener.
    const first = b.greeting;
    const nonEmpty = b.body_lines.filter((l) => l && l.trim() !== "");
    const opener = nonEmpty[1] && !/^(workout|nutrition|recovery):/i.test(nonEmpty[1])
      ? nonEmpty[1]
      : "";
    void first;
    return { pre: opener, extras: [] };
  }, [b]);

  if (!b || !visible) return null;

  return (
    <Modal visible transparent animationType="slide" onRequestClose={dismiss}>
      <View style={styles.root}>
        <Pressable style={styles.backdrop} onPress={dismiss} />
        <View style={styles.card}>
          <View style={styles.head}>
            <Image source={LOUIS_IMG} style={styles.avatar} />
            <View style={{ flex: 1 }}>
              <Text style={styles.coachName}>{b.coach?.name || "Louis"}</Text>
              <Text style={styles.coachRole}>{b.coach?.role || "CrewFit Coach"}</Text>
              <Text style={styles.briefTitle}>{b.title}</Text>
            </View>
            <Pressable onPress={dismiss} hitSlop={12} testID="briefing-close">
              <Ionicons name="close" size={22} color={theme.color.textMuted} />
            </Pressable>
          </View>

          <ScrollView style={{ maxHeight: 460 }}>
            <Text style={styles.greeting}>{b.greeting}</Text>
            {parts.pre ? <Text style={styles.opener}>{parts.pre}</Text> : null}

            <SectionRow icon="barbell" title="WORKOUT" body={b.workout_focus} />
            <SectionRow icon="restaurant" title="NUTRITION" body={b.nutrition_focus} />
            <SectionRow icon="leaf" title="RECOVERY" body={b.recovery_focus} />

            {b.habits && b.habits.length > 0 ? (
              <View style={styles.habitsCard}>
                <Text style={styles.habitsT}>TODAY&apos;S HABITS</Text>
                {b.habits.map((h, i) => (
                  <View key={i} style={styles.habitRow}>
                    <Ionicons
                      name={h.done ? "checkmark-circle" : "ellipse-outline"}
                      size={13}
                      color={h.done ? theme.color.green : theme.color.textMuted}
                    />
                    <Text style={styles.habitLine} numberOfLines={2}>{h.title}</Text>
                  </View>
                ))}
              </View>
            ) : null}

            {b.missed_yesterday ? (
              <View style={styles.missedCard}>
                <Ionicons name="alert-circle" size={14} color={theme.color.amber} />
                <Text style={styles.missedT} numberOfLines={3}>
                  You missed yesterday&apos;s {b.missed_yesterday.title || "session"} — recover it today if it fits.
                </Text>
              </View>
            ) : null}

            <Text style={styles.footerNote}>{b.timezone}{b.city ? ` · ${b.city}` : ""}</Text>
          </ScrollView>

          <View style={styles.actions}>
            <Pressable onPress={goAction} style={[styles.btn, styles.btnPrimary]} testID="briefing-action">
              <Text style={styles.btnPrimaryT}>{(b.main_action?.label || "VIEW TODAY").toUpperCase()}</Text>
            </Pressable>
            <Pressable onPress={messageLouis} style={[styles.btn, styles.btnGhost]} testID="briefing-message">
              <Ionicons name="chatbubble-ellipses" size={14} color={theme.color.brand} />
              <Text style={styles.btnGhostT}>MESSAGE LOUIS</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

function SectionRow({ icon, title, body }: { icon: any; title: string; body: string }) {
  return (
    <View style={styles.sectionRow}>
      <View style={styles.sectionIcon}>
        <Ionicons name={icon} size={13} color={theme.color.brand} />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.sectionT}>{title}</Text>
        <Text style={styles.sectionBody}>{body}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, justifyContent: "flex-end" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.65)" },
  card: {
    backgroundColor: theme.color.surface,
    borderTopLeftRadius: 20, borderTopRightRadius: 20,
    padding: 18, paddingBottom: 26, maxHeight: "88%",
  },
  head: { flexDirection: "row", alignItems: "center", gap: 12, marginBottom: 12 },
  avatar: { width: 48, height: 48, borderRadius: 24, backgroundColor: theme.color.surface3 },
  coachName: { color: theme.color.text, fontSize: 14, fontWeight: "900" },
  coachRole: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 1.2, fontWeight: "800", marginTop: 1 },
  briefTitle: { color: theme.color.brand, fontSize: 12, fontWeight: "900", letterSpacing: 1.5, marginTop: 3 },

  greeting: { color: theme.color.text, fontSize: 16, fontWeight: "800", marginBottom: 4 },
  opener: { color: theme.color.text, fontSize: 13, lineHeight: 19, marginBottom: 10 },

  sectionRow: { flexDirection: "row", gap: 10, alignItems: "flex-start", marginTop: 12 },
  sectionIcon: {
    width: 26, height: 26, borderRadius: 13, backgroundColor: theme.color.brandTint,
    alignItems: "center", justifyContent: "center",
  },
  sectionT: { color: theme.color.brand, fontSize: 10, letterSpacing: 2, fontWeight: "900" },
  sectionBody: { color: theme.color.text, fontSize: 13, lineHeight: 18, marginTop: 3 },

  habitsCard: {
    marginTop: 14, padding: 10, borderRadius: 10,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  habitsT: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 1.5, fontWeight: "800", marginBottom: 6 },
  habitRow: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 4 },
  habitLine: { color: theme.color.text, fontSize: 12, flex: 1 },

  missedCard: {
    marginTop: 12, flexDirection: "row", gap: 8, alignItems: "center",
    padding: 10, borderRadius: 10, backgroundColor: "rgba(245,158,11,0.10)",
    borderWidth: 1, borderColor: "rgba(245,158,11,0.4)",
  },
  missedT: { color: theme.color.text, fontSize: 12, flex: 1 },

  footerNote: { color: theme.color.textDim, fontSize: 10, letterSpacing: 1.2, marginTop: 12, textAlign: "center" },

  actions: { flexDirection: "row", gap: 8, marginTop: 14 },
  btn: { flex: 1, flexDirection: "row", justifyContent: "center", alignItems: "center", gap: 6, padding: 12, borderRadius: 10 },
  btnPrimary: { backgroundColor: theme.color.brand },
  btnPrimaryT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  btnGhost: { borderWidth: 1, borderColor: theme.color.border },
  btnGhostT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
});
