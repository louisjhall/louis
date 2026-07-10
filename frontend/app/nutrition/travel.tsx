/**
 * Nutrition · Travel Food Guidance hub (Phase 4).
 *
 * A grid of goal-personalised guides. Tap a card, Atlas returns
 * the guide for the client's current goal (cached daily).
 */
import React, { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast } from "@/src/lib/ux";
import {
  Screen, TravelHeader, ContextRibbon, ListBlock, travelStyles,
} from "@/src/components/nutrition/travel-shared";

type Context = { goal?: string; remaining?: { calories: number; protein_g: number; hydration_ml: number } };
type Guide = {
  topic: string; title: string; one_liner: string;
  steps: string[]; watchouts: string[];
  if_goal_is_fat_loss: string; if_goal_is_muscle_gain: string; if_goal_is_endurance: string;
};

const TOPICS = [
  { key: "airport_strategy", label: "AIRPORT STRATEGY", icon: "business" as const },
  { key: "hotel_breakfast", label: "HOTEL BREAKFAST", icon: "cafe" as const },
  { key: "hotel_buffet", label: "HOTEL BUFFET", icon: "restaurant" as const },
  { key: "crew_meal", label: "CREW MEAL", icon: "people" as const },
  { key: "long_haul", label: "LONG-HAUL", icon: "airplane" as const },
  { key: "night_flight", label: "NIGHT FLIGHT", icon: "moon" as const },
  { key: "early_start", label: "EARLY START", icon: "alarm" as const },
  { key: "fat_loss_layover", label: "FAT LOSS · LAYOVER", icon: "trending-down" as const },
  { key: "muscle_gain_travel", label: "MUSCLE GAIN · TRAVEL", icon: "barbell" as const },
  { key: "endurance_fuelling", label: "ENDURANCE FUELLING", icon: "pulse" as const },
  { key: "hydration_caffeine", label: "HYDRATION & CAFFEINE", icon: "water" as const },
];

export default function TravelGuidesScreen() {
  const [ctx, setCtx] = useState<Context | null>(null);
  const [loadingTopic, setLoadingTopic] = useState<string | null>(null);
  const [openGuide, setOpenGuide] = useState<Guide | null>(null);

  useEffect(() => {
    api<{ context: Context }>("/nutrition/travel/context").then((r) => setCtx(r.context)).catch(() => {});
  }, []);

  const open = useCallback(async (topic: string) => {
    setLoadingTopic(topic);
    try {
      const r = await api<{ guide: Guide; context: Context }>("/nutrition/travel/guide", {
        method: "POST", body: { topic },
      });
      setOpenGuide(r.guide); setCtx(r.context);
    } catch (e: any) { toast(e?.message || "Atlas failed", "error"); }
    finally { setLoadingTopic(null); }
  }, []);

  const goalTip = (g?: Guide) => {
    if (!g || !ctx?.goal) return null;
    const map: Record<string, string> = {
      fat_loss: g.if_goal_is_fat_loss,
      muscle_gain: g.if_goal_is_muscle_gain,
      endurance: g.if_goal_is_endurance,
    };
    return map[ctx.goal];
  };

  return (
    <Screen>
      <TravelHeader title="TRAVEL FOOD" subtitle="GOAL-PERSONALISED GUIDES" />
      <ScrollView contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: 40 }}>
        <ContextRibbon goal={ctx?.goal} remaining={ctx?.remaining} />
        <Text style={travelStyles.section}>PICK A TOPIC</Text>

        <View style={styles.grid}>
          {TOPICS.map((t) => (
            <Pressable key={t.key} onPress={() => open(t.key)}
              disabled={loadingTopic !== null}
              style={[styles.card, loadingTopic === t.key && styles.cardBusy]}
              testID={`guide-${t.key}`}>
              <Ionicons name={t.icon} size={20} color={theme.color.brand} />
              <Text style={styles.cardT}>{t.label}</Text>
              {loadingTopic === t.key ? (
                <ActivityIndicator color={theme.color.brand} size="small" />
              ) : (
                <Ionicons name="chevron-forward" size={14} color={theme.color.textDim} />
              )}
            </Pressable>
          ))}
        </View>

        <Text style={travelStyles.disclaimer}>
          These guides are Atlas coaching guidance, personalised to your current goal. Always adjust for how you feel.
        </Text>
      </ScrollView>

      {/* Guide modal */}
      <Modal visible={!!openGuide} animationType="slide" onRequestClose={() => setOpenGuide(null)} presentationStyle="pageSheet">
        <Screen>
          <View style={styles.modalHead}>
            <Pressable onPress={() => setOpenGuide(null)} hitSlop={12}>
              <Ionicons name="close" size={24} color={theme.color.text} />
            </Pressable>
            <Text style={styles.modalHeadT}>{openGuide?.title.toUpperCase()}</Text>
            <View style={{ width: 24 }} />
          </View>
          <ScrollView contentContainerStyle={{ padding: 16, gap: 14, paddingBottom: 40 }}>
            {openGuide?.one_liner ? (
              <View style={styles.oneLiner}>
                <Ionicons name="sparkles" size={13} color={theme.color.brand} />
                <Text style={styles.oneLinerT}>{openGuide.one_liner}</Text>
              </View>
            ) : null}
            <ListBlock icon="checkmark-circle" color={theme.color.brand} title="STEPS" items={openGuide?.steps} />
            <ListBlock icon="warning" color={theme.color.amber} title="WATCH-OUTS" items={openGuide?.watchouts} />
            {goalTip(openGuide) ? (
              <View style={styles.goalCard}>
                <View style={styles.goalHead}>
                  <Ionicons name="flag" size={12} color="#fff" />
                  <Text style={styles.goalHeadT}>FOR YOUR GOAL: {(ctx?.goal || "").replace(/_/g, " ").toUpperCase()}</Text>
                </View>
                <Text style={styles.goalT}>{goalTip(openGuide)}</Text>
              </View>
            ) : null}
          </ScrollView>
        </Screen>
      </Modal>
    </Screen>
  );
}

const styles = StyleSheet.create({
  grid: { gap: 8 },
  card: { flexDirection: "row", alignItems: "center", gap: 10, padding: 14, borderRadius: 10, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  cardBusy: { opacity: 0.7 },
  cardT: { color: theme.color.text, fontSize: 12, fontWeight: "900", letterSpacing: 1, flex: 1, fontFamily: theme.font.textSemi },

  modalHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 14, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  modalHeadT: { color: theme.color.text, fontSize: 13, letterSpacing: 2.5, fontWeight: "900", fontFamily: theme.font.display, textAlign: "center", flex: 1 },
  oneLiner: { flexDirection: "row", alignItems: "center", gap: 8, padding: 12, borderRadius: 10, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand },
  oneLinerT: { color: theme.color.text, fontSize: 13, flex: 1, lineHeight: 18, fontFamily: theme.font.text },

  goalCard: { padding: 14, borderRadius: 10, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.brand },
  goalHead: { flexDirection: "row", alignItems: "center", gap: 5, alignSelf: "flex-start", paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6, backgroundColor: theme.color.brand },
  goalHeadT: { color: "#fff", fontSize: 9, fontWeight: "900", letterSpacing: 0.8 },
  goalT: { color: theme.color.text, fontSize: 13, marginTop: 8, lineHeight: 19, fontFamily: theme.font.text },
});
