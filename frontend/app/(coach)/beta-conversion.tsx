/**
 * Coach — Beta Conversion & Survey Results (Iter202 · Phase 2A).
 * Simple read-only tables. No charts, no export, no analytics.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, ActivityIndicator, Pressable,
  RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type CohortRow = {
  id: string; name: string; email: string;
  current_membership_status: string | null;
  days_remaining: number | null;
  current_milestone: string | null;
  survey_completed: boolean;
  converted: boolean;
  converted_tier: string | null;
  founding_eligible: boolean;
  is_founding_member: boolean;
};

type SurveyRow = {
  id: string; user_id: string;
  client_name?: string; client_email?: string;
  submitted_at: string;
  experience_rating: number;
  recommendation_rating: number;
  most_valuable: string | null;
  could_be_better: string | null;
  continuation_blocker: string | null;
};

function status_pill(s: string | null): { bg: string; label: string } {
  switch (s) {
    case "beta": return { bg: "#5aa1ff", label: "BETA" };
    case "expired": return { bg: theme.color.textDim, label: "EXPIRED" };
    case "active": return { bg: "#3ecf8e", label: "ACTIVE" };
    case "cancellation_scheduled": return { bg: "#e0a34e", label: "CANCELLING" };
    case "past_due": return { bg: theme.color.brand, label: "PAST DUE" };
    case "cancelled": return { bg: theme.color.textDim, label: "CANCELLED" };
    default: return { bg: theme.color.textMuted, label: (s || "—").toUpperCase() };
  }
}

export default function BetaConversion() {
  const router = useRouter();
  const [cohort, setCohort] = useState<CohortRow[]>([]);
  const [surveys, setSurveys] = useState<SurveyRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const [c, s] = await Promise.all([
        api<{ cohort: CohortRow[] }>("/admin/beta/conversion-cohort"),
        api<{ responses: SurveyRow[] }>("/admin/beta/survey-results"),
      ]);
      setCohort(c.cohort || []);
      setSurveys(s.responses || []);
    } finally { setLoading(false); setRefreshing(false); }
  }, []);

  useEffect(() => { void load(); }, [load]);

  if (loading) {
    return (
      <View style={[styles.root, { justifyContent: "center", alignItems: "center" }]}>
        <ActivityIndicator color={theme.color.brand} />
      </View>
    );
  }

  const beta = cohort.filter((r) => r.current_membership_status === "beta").length;
  const expired = cohort.filter((r) => r.current_membership_status === "expired").length;
  const converted = cohort.filter((r) => r.converted).length;

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} style={{ padding: 4 }}>
          <Ionicons name="chevron-back" size={22} color={theme.color.text} />
        </Pressable>
        <Text style={styles.headerTitle}>Beta Conversion</Text>
        <View style={{ width: 32 }} />
      </View>

      <ScrollView
        contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 60 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
      >
        <View style={styles.stripWrap}>
          <StripCard n={beta}      label="CURRENT BETA" />
          <StripCard n={expired}   label="EXPIRED" />
          <StripCard n={converted} label="CONVERTED" />
        </View>

        <Text style={styles.sectionTitle}>Cohort</Text>
        {cohort.length === 0 ? (
          <Text style={styles.empty}>No beta cohort activity yet.</Text>
        ) : cohort.map((r) => {
          const pill = status_pill(r.current_membership_status);
          return (
            <View key={r.id} style={styles.row} testID={`cohort-row-${r.id}`}>
              <View style={{ flex: 1 }}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                  <Text style={styles.rowName}>{r.name || r.email}</Text>
                  <View style={[styles.pill, { backgroundColor: pill.bg + "22", borderColor: pill.bg }]}>
                    <Text style={[styles.pillText, { color: pill.bg }]}>{pill.label}</Text>
                  </View>
                  {r.founding_eligible ? (
                    <View style={[styles.pill, { backgroundColor: "#f7b95522", borderColor: "#f7b955" }]}>
                      <Text style={[styles.pillText, { color: "#f7b955" }]}>FOUNDING-ELIGIBLE</Text>
                    </View>
                  ) : null}
                  {r.is_founding_member ? (
                    <View style={[styles.pill, { backgroundColor: "#f7b955", borderColor: "#f7b955" }]}>
                      <Text style={[styles.pillText, { color: "#fff" }]}>FOUNDING</Text>
                    </View>
                  ) : null}
                  {r.converted ? (
                    <View style={[styles.pill, { backgroundColor: "#3ecf8e22", borderColor: "#3ecf8e" }]}>
                      <Text style={[styles.pillText, { color: "#3ecf8e" }]}>
                        CONVERTED{r.converted_tier ? ` · ${r.converted_tier.toUpperCase()}` : ""}
                      </Text>
                    </View>
                  ) : null}
                </View>
                <Text style={styles.rowEmail}>{r.email}</Text>
                <Text style={styles.rowSub}>
                  {r.days_remaining != null ? (
                    r.days_remaining > 0 ? `${r.days_remaining} days remaining` :
                      r.days_remaining === 0 ? "0 days — expiring today" :
                      `Expired ${Math.abs(r.days_remaining)}d ago`
                  ) : "No trial date"}
                  {r.current_milestone ? `   ·   Last milestone: ${r.current_milestone}` : ""}
                  {"   ·   Survey: "}{r.survey_completed ? "✓" : "—"}
                </Text>
              </View>
            </View>
          );
        })}

        <Text style={styles.sectionTitle}>Survey results</Text>
        {surveys.length === 0 ? (
          <Text style={styles.empty}>No survey responses yet.</Text>
        ) : surveys.map((s) => (
          <View key={s.id} style={styles.row} testID={`survey-row-${s.id}`}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
              <Text style={styles.rowName}>{s.client_name || s.client_email}</Text>
              <Text style={styles.rowSub}>{new Date(s.submitted_at).toLocaleDateString("en-GB")}</Text>
            </View>
            <View style={{ flexDirection: "row", gap: 12, marginTop: 4 }}>
              <Text style={styles.starLine}>Experience: {"★".repeat(s.experience_rating)}{"☆".repeat(5 - s.experience_rating)}</Text>
              <Text style={styles.starLine}>Recommend: {"★".repeat(s.recommendation_rating)}{"☆".repeat(5 - s.recommendation_rating)}</Text>
            </View>
            {s.most_valuable ? <Response label="Most valuable" text={s.most_valuable} /> : null}
            {s.could_be_better ? <Response label="Could be better" text={s.could_be_better} /> : null}
            {s.continuation_blocker ? <Response label="Continuation blocker" text={s.continuation_blocker} /> : null}
          </View>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

function StripCard({ n, label }: { n: number; label: string }) {
  return (
    <View style={styles.stripCard}>
      <Text style={styles.stripN}>{n}</Text>
      <Text style={styles.stripLabel}>{label}</Text>
    </View>
  );
}

function Response({ label, text }: { label: string; text: string }) {
  return (
    <View style={{ marginTop: 6 }}>
      <Text style={styles.rLabel}>{label.toUpperCase()}</Text>
      <Text style={styles.rText}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.bg },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: theme.space.lg, paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth, borderColor: theme.color.border,
  },
  headerTitle: { color: theme.color.text, fontSize: 16, fontWeight: "800", letterSpacing: 0.4 },
  stripWrap: { flexDirection: "row", gap: 8, marginBottom: theme.space.lg },
  stripCard: {
    flex: 1, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md,
    borderWidth: 1, borderColor: theme.color.border, padding: 12,
  },
  stripN: { color: theme.color.text, fontSize: 24, fontWeight: "800" },
  stripLabel: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 1.2, fontWeight: "700", marginTop: 4 },
  sectionTitle: { color: theme.color.text, fontWeight: "800", fontSize: 15, marginTop: theme.space.xl, marginBottom: theme.space.md },
  empty: { color: theme.color.textMuted, fontSize: 12, fontStyle: "italic" },
  row: {
    backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1,
    borderColor: theme.color.border, padding: 12, marginBottom: 8,
  },
  rowName: { color: theme.color.text, fontSize: 13, fontWeight: "800" },
  rowEmail: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },
  rowSub: { color: theme.color.textDim, fontSize: 10, marginTop: 4, lineHeight: 15 },
  pill: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 999, borderWidth: 1 },
  pillText: { fontSize: 9, fontWeight: "800", letterSpacing: 1 },
  starLine: { color: "#f7b955", fontSize: 12 },
  rLabel: { color: theme.color.textMuted, fontSize: 9, letterSpacing: 1.2, fontWeight: "800" },
  rText: { color: theme.color.text, fontSize: 12, lineHeight: 17, marginTop: 2 },
});
