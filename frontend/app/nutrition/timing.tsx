/**
 * Nutrition · Time-Zone Meal Timing (Phase 4).
 */
import React, { useEffect, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast } from "@/src/lib/ux";
import { useBottomSafePad } from "@/src/lib/useBottomSafePad";
import {
  Screen, TravelHeader, LoadingBlock, ContextRibbon, ResultCard,
  Chips, travelStyles,
} from "@/src/components/nutrition/travel-shared";

type Context = { goal?: string; remaining?: { calories: number; protein_g: number; hydration_ml: number } };
type Timing = {
  headline: string;
  meal_plan: { when: string; what: string }[];
  caffeine_cutoff: string;
  hydration_focus: string;
  post_flight_recovery_meal: string;
  confidence: string;
};

const FLIGHT_CTX = [
  { key: "long_haul", label: "LONG-HAUL" }, { key: "short_haul", label: "SHORT-HAUL" },
  { key: "turnaround", label: "TURNAROUND" }, { key: "layover_arrival", label: "LAYOVER ARRIVAL" },
  { key: "just_landed", label: "JUST LANDED" },
];

const NEXT_WK = [
  { key: "tomorrow_am", label: "TOMORROW AM" }, { key: "today_pm", label: "TODAY PM" },
  { key: "none", label: "NONE" },
];

const TZ_HINTS = [
  { key: "Europe/London", label: "LONDON" }, { key: "Asia/Dubai", label: "DUBAI" },
  { key: "Asia/Singapore", label: "SINGAPORE" }, { key: "America/New_York", label: "NEW YORK" },
  { key: "Asia/Tokyo", label: "TOKYO" }, { key: "Australia/Sydney", label: "SYDNEY" },
];

export default function TimingScreen() {
  const [ctx, setCtx] = useState<Context | null>(null);
  const bottomPad = useBottomSafePad(40);
  const [homeTz, setHomeTz] = useState<string | null>(null);
  const [currentTz, setCurrentTz] = useState<string | null>(null);
  const [flightCtx, setFlightCtx] = useState<string | null>(null);
  const [sleep, setSleep] = useState("");
  const [wk, setWk] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<Timing | null>(null);

  useEffect(() => {
    // Auto-detect current tz on client
    try {
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (tz) setCurrentTz(tz);
    } catch { /* ignore */ }
    api<{ context: Context }>("/nutrition/travel/context").then((r) => setCtx(r.context)).catch(() => {});
  }, []);

  const run = async () => {
    setLoading(true); setResult(null);
    try {
      const r = await api<{ timing: Timing; context: Context }>("/nutrition/travel/timing", {
        method: "POST",
        body: {
          home_tz: homeTz || undefined,
          current_tz: currentTz || undefined,
          flight_context: flightCtx || undefined,
          planned_sleep_local: sleep || undefined,
          next_workout_context: wk || undefined,
        },
      });
      setResult(r.timing); setCtx(r.context);
    } catch (e: any) { toast(e?.message || "Atlas failed", "error"); }
    finally { setLoading(false); }
  };

  return (
    <Screen>
      <TravelHeader title="MEAL TIMING" subtitle="TIME-ZONE COACHING" />
      <ScrollView contentContainerStyle={{ padding: 16, gap: 14, paddingBottom: bottomPad }}>
        <ContextRibbon goal={ctx?.goal} remaining={ctx?.remaining} />

        <Text style={travelStyles.section}>HOME TIME ZONE</Text>
        <Chips values={TZ_HINTS} selected={homeTz} onSelect={setHomeTz} />

        <Text style={travelStyles.section}>CURRENT TIME ZONE</Text>
        <Chips values={TZ_HINTS} selected={currentTz} onSelect={setCurrentTz} />
        {currentTz ? <Text style={styles.hint}>Detected: {currentTz}</Text> : null}

        <Text style={travelStyles.section}>FLIGHT CONTEXT</Text>
        <Chips values={FLIGHT_CTX} selected={flightCtx} onSelect={setFlightCtx} />

        <Text style={travelStyles.section}>PLANNED SLEEP (LOCAL HH:MM)</Text>
        <TextInput value={sleep} onChangeText={(v) => setSleep(v.replace(/[^0-9:]/g, ""))}
          style={travelStyles.input} placeholder="e.g. 22:30"
          placeholderTextColor={theme.color.textDim} maxLength={5} />

        <Text style={travelStyles.section}>NEXT WORKOUT</Text>
        <Chips values={NEXT_WK} selected={wk} onSelect={setWk} />

        <Pressable onPress={run} disabled={loading}
          style={[travelStyles.primaryBtn, loading && { opacity: 0.5 }]}
          testID="timing-plan-btn">
          <Ionicons name="time" size={14} color="#fff" />
          <Text style={travelStyles.primaryBtnT}>{loading ? "BUILDING TIMING PLAN…" : "GET MEAL TIMING"}</Text>
        </Pressable>

        {loading ? <LoadingBlock text="Mapping your window…" /> : null}

        {result ? (
          <View style={{ gap: 12 }}>
            <ResultCard headline={result.headline} confidence={result.confidence} />
            <View style={styles.planCard}>
              <View style={styles.planHead}>
                <Ionicons name="list" size={13} color={theme.color.brand} />
                <Text style={styles.planHeadT}>MEAL PLAN</Text>
              </View>
              {result.meal_plan.map((m, i) => (
                <View key={i} style={styles.mealRow}>
                  <View style={styles.mealWhen}>
                    <Text style={styles.mealWhenT}>{m.when}</Text>
                  </View>
                  <Text style={styles.mealWhat}>{m.what}</Text>
                </View>
              ))}
            </View>
            {result.caffeine_cutoff ? (
              <TinyCard icon="cafe" color="#8B5CF6" label="CAFFEINE" text={result.caffeine_cutoff} />
            ) : null}
            {result.hydration_focus ? (
              <TinyCard icon="water" color="#3B82F6" label="HYDRATION" text={result.hydration_focus} />
            ) : null}
            {result.post_flight_recovery_meal ? (
              <TinyCard icon="leaf" color={theme.color.green} label="POST-FLIGHT MEAL" text={result.post_flight_recovery_meal} />
            ) : null}
            <Text style={travelStyles.disclaimer}>
              Timing guidance, not medical sleep advice. Adjust based on how you feel.
            </Text>
          </View>
        ) : null}
      </ScrollView>
    </Screen>
  );
}

function TinyCard({ icon, color, label, text }: { icon: any; color: string; label: string; text: string }) {
  return (
    <View style={styles.tinyCard}>
      <View style={styles.tinyIcon}>
        <Ionicons name={icon} size={13} color={color} />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={[styles.tinyLabel, { color }]}>{label}</Text>
        <Text style={styles.tinyText}>{text}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  hint: { color: theme.color.textDim, fontSize: 11, fontStyle: "italic", marginTop: -8 },
  planCard: { padding: 14, borderRadius: 12, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, gap: 10 },
  planHead: { flexDirection: "row", alignItems: "center", gap: 6 },
  planHeadT: { color: theme.color.brand, fontSize: 11, letterSpacing: 2, fontWeight: "900" },
  mealRow: { flexDirection: "row", gap: 10, alignItems: "flex-start" },
  mealWhen: { minWidth: 100, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6, backgroundColor: theme.color.brand },
  mealWhenT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 0.8, textAlign: "center" },
  mealWhat: { color: theme.color.text, fontSize: 13, flex: 1, lineHeight: 18, fontFamily: theme.font.text },
  tinyCard: { flexDirection: "row", gap: 10, padding: 12, borderRadius: 10, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  tinyIcon: { width: 28, height: 28, borderRadius: 14, backgroundColor: theme.color.surface3, alignItems: "center", justifyContent: "center" },
  tinyLabel: { fontSize: 11, letterSpacing: 1.5, fontWeight: "900" },
  tinyText: { color: theme.color.text, fontSize: 12, marginTop: 2, lineHeight: 17, fontFamily: theme.font.text },
});
