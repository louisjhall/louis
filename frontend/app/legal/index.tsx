import React from "react";
import { View, Text, ScrollView, StyleSheet, Pressable, Linking } from "react-native";
import { Stack, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { theme } from "../../src/lib/theme";

export default function LegalIndex() {
  const router = useRouter();
  const items = [
    { key: "privacy", label: "Privacy Policy", desc: "How CrewFit collects, uses and protects your data." },
    { key: "terms", label: "Terms of Service", desc: "The rules for using CrewFit." },
    { key: "data-safety", label: "Data Safety Summary", desc: "A quick summary of what data we hold and why." },
    { key: "delete-account", label: "Delete My Account", desc: "Request permanent deletion of your CrewFit account." },
    { key: "contact", label: "Contact / Support", desc: "Get in touch with the CrewFit team." },
  ];
  return (
    <SafeAreaView style={styles.wrap} edges={["top", "left", "right"]}>
      <Stack.Screen options={{ title: "Legal & Privacy" }} />
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 40 }}>
        <Text style={styles.h1}>Legal &amp; Privacy</Text>
        <Text style={styles.p}>Your rights and our commitments. Read the sections below or contact us if you have any questions.</Text>
        {items.map((it) => (
          <Pressable key={it.key} onPress={() => router.push(`/legal/${it.key}` as any)} style={styles.row} testID={`legal-${it.key}`}>
            <Text style={styles.rowLabel}>{it.label}</Text>
            <Text style={styles.rowDesc}>{it.desc}</Text>
          </Pressable>
        ))}
        <View style={{ height: 24 }} />
        <Pressable onPress={() => Linking.openURL("mailto:louis@crewfit.net")} testID="legal-email">
          <Text style={styles.email}>louis@crewfit.net</Text>
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: theme.color.surface },
  h1: { color: theme.color.text, fontFamily: theme.font.display, fontSize: 28, marginBottom: 8 },
  p: { color: theme.color.textMuted, fontFamily: theme.font.text, fontSize: 15, marginBottom: 20, lineHeight: 22 },
  row: { padding: 16, backgroundColor: theme.color.surface2, borderRadius: 12, marginBottom: 10, borderWidth: 1, borderColor: theme.color.border },
  rowLabel: { color: theme.color.text, fontFamily: theme.font.textSemi, fontSize: 16, marginBottom: 2 },
  rowDesc: { color: theme.color.textMuted, fontFamily: theme.font.text, fontSize: 13 },
  email: { color: theme.color.brand, fontFamily: theme.font.textSemi, fontSize: 16, textAlign: "center", marginTop: 12 },
});
