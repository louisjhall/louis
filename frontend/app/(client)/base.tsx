/**
 * Base — Coming Soon placeholder (Iter 122).
 *
 * The Base tab replaces the old Messages tab. Community functionality is not
 * built yet. This screen is intentionally lightweight: no backend, no data
 * fetches, no state — just static aspirational copy explaining what Base
 * will become. Messaging with Coach Louis now lives on the floating
 * <CoachChatBubble />.
 */
import React from "react";
import { View, Text, StyleSheet, ScrollView } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { theme } from "@/src/lib/theme";
import { BaseIcon } from "@/src/components/BaseIcon";

const FUTURE_FEATURES: { title: string; sub: string }[] = [
  { title: "Community posts & discussions",
    sub: "Share updates and reactions with other crew." },
  { title: "Questions & conversations",
    sub: "Ask the community about training, travel and recovery." },
  { title: "Training wins & progress",
    sub: "Celebrate PBs, streaks and milestones together." },
  { title: "Roster & travel experiences",
    sub: "Compare notes on routes, layovers and jet-lag strategy." },
  { title: "Hotel, airport & layover tips",
    sub: "Real recommendations from crew who have been there." },
  { title: "CrewFit announcements",
    sub: "New coach content, features and programme updates." },
  { title: "Community challenges & accountability",
    sub: "Opt-in group challenges to keep the crew moving." },
];

export default function BaseScreen() {
  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.iconWrap}>
          <BaseIcon size={56} color={theme.color.brand} filled />
        </View>

        <Text style={styles.h1} testID="base-h1">Base</Text>
        <Text style={styles.comingSoon} testID="base-coming-soon">Coming soon</Text>
        <View style={styles.divider} />

        <Text style={styles.lead}>Your CrewFit community.</Text>
        <Text style={styles.body}>
          Base will become a dedicated space for pilots and cabin crew to
          connect, share experiences, stay accountable and learn from others
          dealing with training around rosters, flights, layovers, hotels
          and life on the road.
        </Text>

        <Text style={styles.sectionLabel}>FUTURE FEATURES</Text>
        <View style={{ marginTop: 8 }}>
          {FUTURE_FEATURES.map((f) => (
            <View key={f.title} style={styles.featureRow}>
              <View style={styles.dot} />
              <View style={{ flex: 1 }}>
                <Text style={styles.featureTitle}>{f.title}</Text>
                <Text style={styles.featureSub}>{f.sub}</Text>
              </View>
            </View>
          ))}
        </View>

        <View style={styles.footerCard}>
          <Text style={styles.footerT}>
            In the meantime, reach out to Coach Louis anytime — tap the coach
            bubble on your home screen to open a conversation.
          </Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.color.bg },
  scroll: { padding: 20, paddingBottom: 140 },
  iconWrap: {
    alignSelf: "center",
    marginTop: 24, marginBottom: 12,
    width: 88, height: 88, borderRadius: 44,
    backgroundColor: theme.color.brandTint,
    alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: theme.color.brand,
  },
  h1: {
    color: theme.color.text, fontWeight: "900", fontSize: 28,
    textAlign: "center", letterSpacing: 0.5,
  },
  comingSoon: {
    color: theme.color.brand, fontWeight: "800", fontSize: 12,
    textAlign: "center", letterSpacing: 3.5,
    marginTop: 6, textTransform: "uppercase",
  },
  divider: {
    height: 1, backgroundColor: theme.color.border,
    marginVertical: 20, alignSelf: "stretch",
  },
  lead: {
    color: theme.color.text, fontSize: 16, fontWeight: "700",
    textAlign: "center", marginBottom: 12,
  },
  body: {
    color: theme.color.textMuted, fontSize: 14, lineHeight: 21,
    textAlign: "center", paddingHorizontal: 4,
  },
  sectionLabel: {
    color: theme.color.textMuted, fontSize: 10, fontWeight: "800",
    letterSpacing: 2.2, marginTop: 30, marginBottom: 4,
  },
  featureRow: {
    flexDirection: "row", alignItems: "flex-start",
    paddingVertical: 10, gap: 10,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: theme.color.border,
  },
  dot: {
    width: 6, height: 6, borderRadius: 3,
    backgroundColor: theme.color.brand,
    marginTop: 8,
  },
  featureTitle: { color: theme.color.text, fontSize: 14, fontWeight: "700" },
  featureSub:   { color: theme.color.textMuted, fontSize: 12, marginTop: 2 },
  footerCard: {
    marginTop: 24, padding: 14,
    backgroundColor: theme.color.surface2, borderRadius: 12,
    borderWidth: 1, borderColor: theme.color.border,
  },
  footerT: { color: theme.color.textMuted, fontSize: 13, lineHeight: 19, textAlign: "center" },
});
