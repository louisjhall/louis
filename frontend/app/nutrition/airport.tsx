/**
 * Nutrition · Airport Survival Mode (Phase 4).
 */
import React, { useEffect, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast } from "@/src/lib/ux";
import { useBottomSafePad } from "@/src/lib/useBottomSafePad";
import {
  Screen, TravelHeader, LoadingBlock, ContextRibbon, ResultCard, ListBlock,
  Chips, travelStyles,
} from "@/src/components/nutrition/travel-shared";

type Context = { goal?: string; remaining?: { calories: number; protein_g: number; hydration_ml: number } };
type Plan = {
  headline: string; best_moves: string[]; ok_moves: string[]; avoid_if_possible: string[];
  snack_backup: string[]; hydration_reminder: string; if_time_is_short: string; confidence: string;
};

const TIMES = [
  { key: "20", label: "< 30 MIN" }, { key: "45", label: "30-60 MIN" },
  { key: "90", label: "1-2 HR" }, { key: "180", label: "2+ HR" },
];
const HUNGER = [{ key: "low", label: "LOW" }, { key: "medium", label: "MEDIUM" }, { key: "high", label: "HIGH" }];
const NEXT_CTX = [
  { key: "duty", label: "HEADING TO DUTY" }, { key: "sleep_soon", label: "SLEEP AFTER" },
  { key: "training", label: "TRAINING SOON" }, { key: "layover", label: "LAYOVER" }, { key: "free", label: "FREE" },
];

export default function AirportScreen() {
  const [ctx, setCtx] = useState<Context | null>(null);
  const bottomPad = useBottomSafePad(40);
  const [airport, setAirport] = useState("");
  const [time, setTime] = useState<string>("45");
  const [hunger, setHunger] = useState("medium");
  const [nextCtx, setNextCtx] = useState("duty");
  const [loading, setLoading] = useState(false);
  const [plan, setPlan] = useState<Plan | null>(null);

  useEffect(() => {
    api<{ context: Context }>("/nutrition/travel/context").then((r) => setCtx(r.context)).catch(() => {});
  }, []);

  const run = async () => {
    setLoading(true); setPlan(null);
    try {
      const r = await api<{ plan: Plan; context: Context }>("/nutrition/travel/airport", {
        method: "POST",
        body: {
          airport_code: airport.trim().toUpperCase().length === 3 ? airport.trim().toUpperCase() : undefined,
          airport_name: airport.trim().length && airport.trim().length !== 3 ? airport.trim() : undefined,
          time_available_min: parseInt(time, 10),
          hunger_level: hunger,
          next_context: nextCtx,
        },
      });
      setPlan(r.plan); setCtx(r.context);
    } catch (e: any) { toast(e?.message || "Atlas failed", "error"); }
    finally { setLoading(false); }
  };

  return (
    <Screen>
      <TravelHeader title="AIRPORT MODE" subtitle="BEST / OK / AVOID PLAYBOOK" />
      <ScrollView contentContainerStyle={{ padding: 16, gap: 14, paddingBottom: bottomPad }}>
        <ContextRibbon goal={ctx?.goal} remaining={ctx?.remaining} />

        <Text style={travelStyles.section}>AIRPORT (OPTIONAL)</Text>
        <TextInput value={airport} onChangeText={setAirport} style={travelStyles.input}
          placeholder="e.g. DXB or Dubai T3" placeholderTextColor={theme.color.textDim}
          autoCapitalize="characters" testID="airport-input" />

        <Text style={travelStyles.section}>TIME BEFORE BOARDING</Text>
        <Chips values={TIMES} selected={time} onSelect={setTime} />

        <Text style={travelStyles.section}>HUNGER</Text>
        <Chips values={HUNGER} selected={hunger} onSelect={setHunger} />

        <Text style={travelStyles.section}>NEXT CONTEXT</Text>
        <Chips values={NEXT_CTX} selected={nextCtx} onSelect={setNextCtx} />

        <Pressable onPress={run} disabled={loading}
          style={[travelStyles.primaryBtn, loading && { opacity: 0.5 }]}
          testID="airport-plan-btn">
          <Ionicons name="business" size={14} color="#fff" />
          <Text style={travelStyles.primaryBtnT}>{loading ? "BUILDING PLAYBOOK…" : "GET AIRPORT PLAN"}</Text>
        </Pressable>

        {loading ? <LoadingBlock text="Building your airport playbook…" /> : null}

        {plan ? (
          <View style={{ gap: 12 }}>
            <ResultCard headline={plan.headline} confidence={plan.confidence} />
            <ListBlock icon="checkmark-circle" color={theme.color.green} title="BEST MOVES" items={plan.best_moves} />
            <ListBlock icon="remove-circle" color={theme.color.amber} title="OK MOVES" items={plan.ok_moves} />
            <ListBlock icon="close-circle" color="#c94a4a" title="AVOID IF POSSIBLE" items={plan.avoid_if_possible} />
            <ListBlock icon="fast-food" color={theme.color.brand} title="SNACK BACKUP" items={plan.snack_backup} />
            {plan.hydration_reminder ? (
              <View style={styles.waterCard}>
                <Ionicons name="water" size={13} color="#3B82F6" />
                <Text style={styles.waterT}>{plan.hydration_reminder}</Text>
              </View>
            ) : null}
            {plan.if_time_is_short ? (
              <View style={styles.tsCard}>
                <Ionicons name="time" size={13} color={theme.color.brand} />
                <Text style={styles.tsT}>{plan.if_time_is_short}</Text>
              </View>
            ) : null}
            <Text style={travelStyles.disclaimer}>
              Guidance is based on general airport food logic. Restaurant availability varies by terminal.
            </Text>
          </View>
        ) : null}
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  waterCard: { flexDirection: "row", alignItems: "center", gap: 8, padding: 12, borderRadius: 10, backgroundColor: "#0A1420", borderWidth: 1, borderColor: "#183045" },
  waterT: { color: "#DBEAFE", fontSize: 12, flex: 1, fontFamily: theme.font.text, lineHeight: 18 },
  tsCard: { flexDirection: "row", alignItems: "center", gap: 8, padding: 12, borderRadius: 10, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand },
  tsT: { color: theme.color.text, fontSize: 12, flex: 1, fontFamily: theme.font.text, lineHeight: 18 },
});
