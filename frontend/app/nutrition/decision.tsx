/**
 * Nutrition · Atlas Meal Decision (Phase 4).
 *
 * Client picks a situation (airport / hotel buffet / layover / night flight /
 * only snacks / about to train / just landed / really hungry / stay on track),
 * optionally sets hunger + next context, and Atlas returns a one-call meal
 * decision tailored to their goal + remaining targets.
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
type Decision = {
  headline: string; reason: string;
  do_this: string[]; avoid: string[]; protein_led_options: string[];
  hydration_note: string; confidence: string;
};

const SITUATIONS = [
  { key: "airport", label: "AIRPORT", icon: "business" as const },
  { key: "hotel_breakfast", label: "HOTEL BREAKFAST", icon: "cafe" as const },
  { key: "hotel_buffet", label: "HOTEL BUFFET", icon: "restaurant" as const },
  { key: "layover", label: "LAYOVER", icon: "bed" as const },
  { key: "night_flight", label: "NIGHT FLIGHT", icon: "moon" as const },
  { key: "long_haul_flight", label: "LONG-HAUL", icon: "airplane" as const },
  { key: "only_snacks", label: "ONLY SNACKS", icon: "fast-food" as const },
  { key: "about_to_train", label: "ABOUT TO TRAIN", icon: "barbell" as const },
  { key: "just_landed", label: "JUST LANDED", icon: "airplane-outline" as const },
  { key: "really_hungry", label: "REALLY HUNGRY", icon: "flame" as const },
  { key: "stay_on_track", label: "STAY ON TRACK", icon: "checkmark-circle" as const },
];

const HUNGER = [{ key: "low", label: "LOW" }, { key: "medium", label: "MEDIUM" }, { key: "high", label: "HIGH" }];
const NEXT_CTX = [
  { key: "sleep_soon", label: "SLEEP SOON" }, { key: "training", label: "TRAINING" },
  { key: "duty", label: "ON DUTY" }, { key: "free", label: "FREE TIME" },
];

export default function DecisionScreen() {
  const [ctx, setCtx] = useState<Context | null>(null);
  const bottomPad = useBottomSafePad(40);
  const [situation, setSituation] = useState<string | null>(null);
  const [hunger, setHunger] = useState<string>("medium");
  const [nextCtx, setNextCtx] = useState<string>("duty");
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<Decision | null>(null);

  useEffect(() => {
    api<{ context: Context }>("/nutrition/travel/context").then((r) => setCtx(r.context)).catch(() => {});
  }, []);

  const run = async () => {
    if (!situation) { toast("Pick a situation first", "error"); return; }
    setLoading(true); setResult(null);
    try {
      const r = await api<{ decision: Decision; context: Context }>("/nutrition/travel/decision", {
        method: "POST",
        body: { situation, hunger_level: hunger, next_context: nextCtx, notes: notes || undefined },
      });
      setResult(r.decision); setCtx(r.context);
    } catch (e: any) { toast(e?.message || "Atlas failed", "error"); }
    finally { setLoading(false); }
  };

  return (
    <Screen>
      <TravelHeader title="ATLAS DECIDE" subtitle="ONE-CALL MEAL DECISION" />
      <ScrollView contentContainerStyle={{ padding: 16, gap: 14, paddingBottom: bottomPad }}>
        <ContextRibbon goal={ctx?.goal} remaining={ctx?.remaining} />

        <Text style={travelStyles.section}>SITUATION</Text>
        <Chips values={SITUATIONS} selected={situation} onSelect={setSituation} testIDPrefix="sit" />

        <Text style={travelStyles.section}>HUNGER</Text>
        <Chips values={HUNGER} selected={hunger} onSelect={setHunger} />

        <Text style={travelStyles.section}>NEXT CONTEXT</Text>
        <Chips values={NEXT_CTX} selected={nextCtx} onSelect={setNextCtx} />

        <Text style={travelStyles.section}>NOTES (OPTIONAL)</Text>
        <TextInput value={notes} onChangeText={setNotes} style={travelStyles.input}
          placeholder="e.g. skipped lunch, hotel gym in 2h" placeholderTextColor={theme.color.textDim} multiline />

        <Pressable onPress={run} disabled={loading || !situation}
          style={[travelStyles.primaryBtn, (!situation || loading) && { opacity: 0.5 }]}
          testID="atlas-decide-btn">
          <Ionicons name="sparkles" size={14} color="#fff" />
          <Text style={travelStyles.primaryBtnT}>{loading ? "ATLAS IS THINKING…" : "GET ATLAS DECISION"}</Text>
        </Pressable>

        {loading ? <LoadingBlock text="Analysing your situation & remaining targets…" /> : null}

        {result ? (
          <View style={{ gap: 12 }}>
            <ResultCard headline={result.headline} reason={result.reason} confidence={result.confidence} />
            <ListBlock icon="checkmark-circle" color={theme.color.green} title="DO THIS" items={result.do_this} />
            <ListBlock icon="barbell" color={theme.color.brand} title="PROTEIN-LED OPTIONS" items={result.protein_led_options} />
            <ListBlock icon="close-circle" color="#c94a4a" title="AVOID" items={result.avoid} />
            {result.hydration_note ? (
              <View style={styles.waterCard}>
                <Ionicons name="water" size={13} color="#3B82F6" />
                <Text style={styles.waterT}>{result.hydration_note}</Text>
              </View>
            ) : null}
            <Text style={travelStyles.disclaimer}>Atlas guidance, not medical advice. Adjust based on how you actually feel.</Text>
          </View>
        ) : null}
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  waterCard: { flexDirection: "row", alignItems: "center", gap: 8, padding: 12, borderRadius: 10, backgroundColor: "#0A1420", borderWidth: 1, borderColor: "#183045" },
  waterT: { color: "#DBEAFE", fontSize: 12, flex: 1, fontFamily: theme.font.text, lineHeight: 18 },
});
