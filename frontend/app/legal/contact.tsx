import React from "react";
import { View, Text, ScrollView, StyleSheet, Linking, Pressable } from "react-native";
import { Stack } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { theme } from "../../src/lib/theme";

export default function Contact() {
  return (
    <SafeAreaView style={styles.wrap} edges={["top", "left", "right"]}>
      <Stack.Screen options={{ title: "Contact" }} />
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 60 }}>
        <Text style={styles.h1}>Contact CrewFit</Text>
        <Text style={styles.p}>We aim to reply within 2 working days.</Text>

        <View style={styles.card}>
          <Text style={styles.label}>General support</Text>
          <Pressable onPress={() => Linking.openURL("mailto:support@crewfit.com")}>
            <Text style={styles.link}>support@crewfit.com</Text>
          </Pressable>
        </View>

        <View style={styles.card}>
          <Text style={styles.label}>Privacy & data requests</Text>
          <Pressable onPress={() => Linking.openURL("mailto:privacy@crewfit.com")}>
            <Text style={styles.link}>privacy@crewfit.com</Text>
          </Pressable>
        </View>

        <View style={styles.card}>
          <Text style={styles.label}>Security disclosures</Text>
          <Pressable onPress={() => Linking.openURL("mailto:security@crewfit.com")}>
            <Text style={styles.link}>security@crewfit.com</Text>
          </Pressable>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: theme.color.surface },
  h1: { color: theme.color.text, fontFamily: theme.font.display, fontSize: 28, marginBottom: 8 },
  p: { color: theme.color.textMuted, fontFamily: theme.font.text, fontSize: 14, lineHeight: 22, marginBottom: 20 },
  card: { backgroundColor: theme.color.surface2, borderRadius: 12, padding: 16, marginBottom: 10, borderWidth: 1, borderColor: theme.color.border },
  label: { color: theme.color.textMuted, fontFamily: theme.font.textSemi, fontSize: 12, textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 6 },
  link: { color: theme.color.brand, fontFamily: theme.font.textSemi, fontSize: 17 },
});
