/**
 * On Demand — Client tab (Stage 1 placeholder).
 *
 * The full member-facing browse / player UI lands in Stage 2. This tab
 * exists now so the bottom navigation is stable and can be enabled the
 * moment we have items to show. Keeping the placeholder here (rather
 * than an empty file) makes the tab feel intentional instead of broken.
 *
 * Route: /(client)/on-demand
 */
import React from "react";
import { View, Text, StyleSheet, ScrollView } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";
import { useBottomSafePad } from "@/src/lib/useBottomSafePad";

export default function OnDemandClientScreen() {
  const bottomPad = useBottomSafePad();

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <Text style={styles.title}>ON DEMAND</Text>
        <Text style={styles.subtitle}>Workouts · Videos · Audio</Text>
      </View>

      <ScrollView
        contentContainerStyle={[styles.body, { paddingBottom: bottomPad + 24 }]}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.hero} testID="on-demand-placeholder">
          <View style={styles.heroIconWrap}>
            <Ionicons name="library-outline" size={44} color={theme.color.brand} />
          </View>
          <Text style={styles.heroTitle}>Coming Soon</Text>
          <Text style={styles.heroBody}>
            Your coach is curating a library of on-demand workouts,
            coaching videos and mindset audio for you. Check back shortly
            — everything will show up here the moment it&apos;s published.
          </Text>
        </View>

        <View style={styles.tilesRow}>
          <PlaceholderTile icon="barbell-outline" label="Workouts" />
          <PlaceholderTile icon="videocam-outline" label="Videos" />
          <PlaceholderTile icon="headset-outline" label="Audio" />
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function PlaceholderTile({ icon, label }: { icon: any; label: string }) {
  return (
    <View style={styles.tile}>
      <Ionicons name={icon} size={26} color={theme.color.brand} />
      <Text style={styles.tileLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.color.surface },
  header: {
    paddingHorizontal: 20,
    paddingTop: 16,
    paddingBottom: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: theme.color.border,
  },
  title: {
    color: theme.color.text,
    fontSize: 22,
    fontWeight: "800",
    letterSpacing: 1.5,
  },
  subtitle: {
    color: theme.color.textDim,
    fontSize: 12,
    letterSpacing: 1,
    marginTop: 2,
  },
  body: {
    paddingHorizontal: 20,
    paddingTop: 20,
  },
  hero: {
    alignItems: "center",
    padding: 24,
    borderRadius: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.color.border,
    backgroundColor: theme.color.surface2,
  },
  heroIconWrap: {
    width: 76,
    height: 76,
    borderRadius: 38,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: theme.color.brandTint,
    borderWidth: 1,
    borderColor: theme.color.brand,
    marginBottom: 14,
  },
  heroTitle: {
    color: theme.color.text,
    fontSize: 20,
    fontWeight: "800",
    letterSpacing: 0.5,
    marginBottom: 8,
  },
  heroBody: {
    color: theme.color.text,
    fontSize: 14,
    lineHeight: 21,
    textAlign: "center",
    opacity: 0.85,
  },
  tilesRow: {
    flexDirection: "row",
    marginTop: 20,
    gap: 12,
  },
  tile: {
    flex: 1,
    padding: 16,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 14,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.color.border,
    backgroundColor: theme.color.surface2,
    gap: 8,
  },
  tileLabel: {
    color: theme.color.text,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 0.8,
  },
});
