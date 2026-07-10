import React from "react";
import { View, Text, ScrollView, StyleSheet } from "react-native";
import { Stack } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { theme } from "../../src/lib/theme";

type Row = { data: string; collected: boolean; shared: boolean; purpose: string };

const ROWS: Row[] = [
  { data: "Name & email", collected: true, shared: false, purpose: "Account and support." },
  { data: "Encrypted password", collected: true, shared: false, purpose: "Login. Hashed with bcrypt — we never see the plaintext." },
  { data: "Fitness data (workouts, PRs, habits, check-ins)", collected: true, shared: false, purpose: "Provide the service and personalised guidance." },
  { data: "Nutrition logs & meal photos", collected: true, shared: false, purpose: "Meal logging and AI meal analysis. Photos are sent to Anthropic’s vision API for that single request only." },
  { data: "Roster / duty schedule", collected: true, shared: false, purpose: "Travel-aware guidance, workout timing." },
  { data: "Location (city / country)", collected: true, shared: false, purpose: "Only if you grant permission. Used for travel guidance and timezone." },
  { data: "Weekly check-ins & messages", collected: true, shared: true, purpose: "Shared with your assigned coach on coached plans." },
  { data: "Device model & OS", collected: true, shared: false, purpose: "Troubleshooting and crash reports." },
  { data: "Analytics identifiers", collected: false, shared: false, purpose: "We do not use third-party analytics at this time." },
  { data: "Advertising identifiers", collected: false, shared: false, purpose: "We do not run ads or track for advertising." },
];

export default function DataSafety() {
  return (
    <SafeAreaView style={styles.wrap} edges={["top", "left", "right"]}>
      <Stack.Screen options={{ title: "Data Safety" }} />
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 60 }}>
        <Text style={styles.h1}>Data Safety Summary</Text>
        <Text style={styles.p}>A quick, plain-English summary of what CrewFit does with your data. For full details, see the Privacy Policy.</Text>

        <View style={styles.tableHead}>
          <Text style={[styles.cell, styles.hCell, { flex: 3 }]}>Data</Text>
          <Text style={[styles.cell, styles.hCell, { flex: 1, textAlign: "center" }]}>Collect</Text>
          <Text style={[styles.cell, styles.hCell, { flex: 1, textAlign: "center" }]}>Share</Text>
        </View>
        {ROWS.map((r, i) => (
          <View key={i} style={styles.row}>
            <View style={{ flex: 3 }}>
              <Text style={styles.dataLabel}>{r.data}</Text>
              <Text style={styles.purpose}>{r.purpose}</Text>
            </View>
            <Text style={[styles.cell, { flex: 1, textAlign: "center", color: r.collected ? theme.color.brand : theme.color.textDim }]}>{r.collected ? "Yes" : "No"}</Text>
            <Text style={[styles.cell, { flex: 1, textAlign: "center", color: r.shared ? theme.color.amber : theme.color.textDim }]}>{r.shared ? "Yes" : "No"}</Text>
          </View>
        ))}

        <Text style={styles.h2}>Encryption</Text>
        <Text style={styles.p}>All data is encrypted in transit (HTTPS). Passwords are hashed. Cloud storage is private by default.</Text>

        <Text style={styles.h2}>Deletion</Text>
        <Text style={styles.p}>You can request permanent deletion of your account at any time from Legal &gt; Delete My Account. Data is purged after a 30-day grace period.</Text>

        <Text style={styles.h2}>AI processing</Text>
        <Text style={styles.p}>AI features send the content of your request (e.g. a photo, a prompt) to third-party AI providers via our processor Emergent. Providers do not store or train on your data.</Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: theme.color.surface },
  h1: { color: theme.color.text, fontFamily: theme.font.display, fontSize: 28, marginBottom: 8 },
  h2: { color: theme.color.text, fontFamily: theme.font.textBold, fontSize: 17, marginTop: 20, marginBottom: 6 },
  p: { color: theme.color.textMuted, fontFamily: theme.font.text, fontSize: 14, lineHeight: 22, marginBottom: 6 },
  tableHead: { flexDirection: "row", paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: theme.color.borderStrong, marginTop: 12 },
  row: { flexDirection: "row", paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: theme.color.divider, alignItems: "center" },
  cell: { color: theme.color.text, fontFamily: theme.font.text, fontSize: 13 },
  hCell: { color: theme.color.textMuted, fontFamily: theme.font.textSemi, fontSize: 12, textTransform: "uppercase", letterSpacing: 0.4 },
  dataLabel: { color: theme.color.text, fontFamily: theme.font.textSemi, fontSize: 14, marginBottom: 2 },
  purpose: { color: theme.color.textDim, fontFamily: theme.font.text, fontSize: 12, lineHeight: 16 },
});
