import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter, useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

export default function CoachingDnaScreen() {
  const router = useRouter();
  const [dna, setDna] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<any>("/coaching-dna");
      setDna(r.dna || null);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (loading && !dna) {
    return (
      <SafeAreaView style={styles.root} edges={["top"]}>
        <ActivityIndicator style={{ marginTop: 40 }} color={theme.color.brand} />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} testID="dna-back">
          <Ionicons name="chevron-back" size={24} color={theme.color.text} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>COACHING <Text style={styles.brandRed}>DNA</Text></Text>
          <Text style={styles.sub}>Your permanent CrewFit blueprint</Text>
        </View>
        <Pressable testID="dna-retake" onPress={() => router.push("/assessment" as any)} style={styles.retakeBtn}>
          <Ionicons name="refresh" size={12} color={theme.color.brand} />
          <Text style={styles.retakeTxt}>RETAKE</Text>
        </Pressable>
      </View>

      <ScrollView
        contentContainerStyle={styles.body}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}
      >
        {!dna ? (
          <View style={styles.empty}>
            <Ionicons name="pulse" size={40} color={theme.color.textDim} />
            <Text style={styles.emptyT}>No Coaching DNA yet</Text>
            <Text style={styles.emptyS}>Complete the Atlas Assessment to generate your permanent coaching blueprint.</Text>
            <Pressable testID="dna-take" onPress={() => router.push("/assessment" as any)} style={styles.takeBtn}>
              <Text style={styles.takeTxt}>START ASSESSMENT</Text>
              <Ionicons name="arrow-forward" size={14} color="#fff" />
            </Pressable>
          </View>
        ) : (
          <>
            <View style={styles.confCard}>
              <View style={{ flex: 1 }}>
                <Text style={styles.confLabel}>AI CONFIDENCE</Text>
                <Text style={styles.confSub}>Version {dna.version || 1} · rises as CrewFit learns more.</Text>
              </View>
              <Text style={styles.confNum}>{dna.ai_confidence_score ?? "—"}</Text>
            </View>

            <Row label="PRIMARY GOAL" value={dna.primary_goal} highlight />
            <Row label="WHY IT MATTERS" value={dna.why_it_matters} multiline />
            {Array.isArray(dna.secondary_goals) && dna.secondary_goals.length > 0 && (
              <Row label="SECONDARY GOALS" value={dna.secondary_goals.join(" · ")} />
            )}
            {dna.next_event?.name && (
              <Row label="NEXT MAJOR EVENT" value={`${dna.next_event.name} · ${dna.next_event.date}`} />
            )}
            {Array.isArray(dna.event_timeline) && dna.event_timeline.length > 0 && (
              <View style={styles.timelineCard}>
                <Text style={styles.timelineLbl}>EVENT TIMELINE</Text>
                {dna.event_timeline.slice(0, 8).map((e: any, i: number) => (
                  <View key={i} style={styles.timelineRow}>
                    <Ionicons name="flag" size={16} color={theme.color.brand} />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.timelineName}>{e.name || "Event"}</Text>
                      <Text style={styles.timelineMeta}>{e.date} · Priority {e.priority || "B"}</Text>
                    </View>
                  </View>
                ))}
              </View>
            )}
            {dna.aviation_profile && (
              <Row label="AVIATION PROFILE" value={
                `${dna.aviation_profile.role || "—"} · ${dna.aviation_profile.haul_mix || "—"} · hotel gyms: ${dna.aviation_profile.hotel_gym_frequency || "—"}`
              } />
            )}
            <Row label="FLYING STYLE" value={dna.flying_style} multiline />
            <Row label="RECOVERY RISK" value={String(dna.recovery_risk || "").toUpperCase()} />
            <Row label="TRAINING EXPERIENCE" value={String(dna.training_experience || "").toUpperCase()} />
            <Row label="MOTIVATION STYLE" value={dna.motivation_style} />
            <Row label="COACHING STYLE" value={dna.coaching_style} />
            <Row label="LIFESTYLE" value={dna.lifestyle_summary} multiline />
            <Row label="INJURIES" value={dna.injury_summary} multiline />
            <Row label="NUTRITION" value={dna.nutrition_summary} multiline />
            <Row label="STRENGTH" value={dna.biggest_strength} multiline />
            <Row label="WEAKNESS" value={dna.biggest_weakness} multiline />
            <Row label="OPPORTUNITY" value={dna.biggest_opportunity} multiline />

            <View style={styles.recoBlock}>
              <Text style={styles.recoHead}>RECOMMENDED APPROACH</Text>
              <Row label="WEEKLY TRAINING" value={dna.recommended_weekly_training} multiline dim />
              <Row label="RECOVERY STRATEGY" value={dna.recommended_recovery_strategy} multiline dim />
              <Row label="NUTRITION STRATEGY" value={dna.recommended_nutrition_strategy} multiline dim />
              <Row label="COACHING STYLE" value={dna.recommended_coaching_style} multiline dim />
            </View>

            {dna.summary ? (
              <View style={styles.summaryCard}>
                <Text style={styles.summaryLabel}>ATLAS INTELLIGENCE SUMMARY</Text>
                <Text style={styles.summaryText}>{dna.summary}</Text>
              </View>
            ) : null}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function Row({ label, value, multiline, highlight, dim }: { label: string; value?: any; multiline?: boolean; highlight?: boolean; dim?: boolean }) {
  if (value === undefined || value === null || value === "") return null;
  return (
    <View style={[styles.row, highlight && styles.rowHighlight, dim && styles.rowDim]}>
      <Text style={[styles.rowLbl, highlight && { color: theme.color.brand }]}>{label}</Text>
      <Text style={[styles.rowVal, multiline && { fontSize: 13, lineHeight: 19 }, highlight && { fontSize: 18, fontWeight: "900" }]}>
        {String(value)}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: {
    flexDirection: "row", alignItems: "center", gap: 12,
    padding: 20, borderBottomWidth: 1, borderBottomColor: theme.color.divider,
  },
  title: { color: theme.color.text, fontSize: 14, fontWeight: "900", letterSpacing: 2 },
  brandRed: { color: theme.color.brand },
  sub: { color: theme.color.textMuted, fontSize: 11, marginTop: 3 },
  retakeBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6,
    borderWidth: 1, borderColor: theme.color.brand,
  },
  retakeTxt: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },
  body: { padding: 20, paddingBottom: 40 },

  empty: { alignItems: "center", padding: 40 },
  emptyT: { color: theme.color.text, fontSize: 14, fontWeight: "900", letterSpacing: 1.5, marginTop: 10 },
  emptyS: { color: theme.color.textMuted, fontSize: 12, textAlign: "center", marginTop: 8, lineHeight: 18 },
  takeBtn: {
    flexDirection: "row", alignItems: "center", gap: 8, marginTop: 20,
    paddingVertical: 12, paddingHorizontal: 20, borderRadius: 10,
    backgroundColor: theme.color.brand,
  },
  takeTxt: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 2 },

  confCard: {
    flexDirection: "row", alignItems: "center", gap: 12,
    padding: 16, borderRadius: 12, marginBottom: 20,
    backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand,
  },
  confLabel: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  confSub: { color: theme.color.textMuted, fontSize: 11, marginTop: 4 },
  confNum: { color: theme.color.brand, fontSize: 36, fontWeight: "900" },

  row: {
    padding: 12, marginBottom: 8, borderRadius: 8,
    backgroundColor: theme.color.surface2, borderLeftWidth: 2, borderLeftColor: theme.color.border,
  },
  rowHighlight: { borderLeftColor: theme.color.brand, backgroundColor: theme.color.brandTint },
  rowDim: { backgroundColor: "transparent", borderLeftColor: theme.color.textDim },
  rowLbl: { color: theme.color.textMuted, fontSize: 9, fontWeight: "900", letterSpacing: 2, marginBottom: 4 },
  rowVal: { color: theme.color.text, fontSize: 14, fontWeight: "700" },

  timelineCard: {
    padding: 14, borderRadius: 10, marginBottom: 12,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  timelineLbl: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 2, marginBottom: 10 },
  timelineRow: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 6, borderTopWidth: 1, borderTopColor: theme.color.divider },
  timelineEmoji: { fontSize: 18 },
  timelineName: { color: theme.color.text, fontSize: 13, fontWeight: "800" },
  timelineMeta: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },

  recoBlock: { marginTop: 20 },
  recoHead: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2, marginBottom: 12 },

  summaryCard: {
    marginTop: 20, padding: 16, borderRadius: 12,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.brand,
  },
  summaryLabel: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 2, marginBottom: 8 },
  summaryText: { color: theme.color.text, fontSize: 13, lineHeight: 20 },
});
