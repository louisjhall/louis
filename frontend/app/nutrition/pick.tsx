/**
 * Nutrition · Log picker — Iter 95e regression fix.
 *
 * Previously the "LOG FIRST MEAL" / "LOG FOOD" buttons on the home card
 * routed straight to `/nutrition/log` (manual entry only). Clients
 * couldn't reach Photo Scan / Barcode / Food Search from that flow.
 *
 * This screen is the correct destination — a lightweight picker that
 * offers all four modalities. Each option only shows if the underlying
 * feature is enabled. No new backend. No duplicate systems — the
 * screens picked to are the ones that already existed at
 * /nutrition/photo-scan, /nutrition/barcode, /nutrition/food-search,
 * /nutrition/log.
 */
import React from "react";
import { View, Text, StyleSheet, Pressable, ScrollView } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Stack, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";
import { useFlag } from "@/src/lib/appConfig";

type Modality = {
  key: string;
  label: string;
  sub: string;
  icon: React.ComponentProps<typeof Ionicons>["name"];
  route: string;
  primary?: boolean;
  disabled?: boolean;
};

export default function LogFoodPicker() {
  const router = useRouter();
  const photoEnabled  = useFlag("nutrition_photo_enabled", true);
  const barcodeEnabled = useFlag("nutrition_barcode_enabled", true);

  const modalities: Modality[] = [
    { key: "photo",   label: "TAKE FOOD PHOTO", sub: "Scan a meal with your camera",
      icon: "camera",  route: "/nutrition/photo-scan", primary: true, disabled: !photoEnabled },
    { key: "barcode", label: "SCAN BARCODE",    sub: "Point at a wrapper or label",
      icon: "barcode-outline", route: "/nutrition/barcode", disabled: !barcodeEnabled },
    { key: "search",  label: "SEARCH FOOD",     sub: "Look up brands and common meals",
      icon: "search",  route: "/nutrition/food-search" },
    { key: "manual",  label: "MANUAL ENTRY",    sub: "Type the meal in yourself",
      icon: "create-outline", route: "/nutrition/log" },
  ];

  return (
    <SafeAreaView style={styles.wrap} edges={["top", "left", "right"]}>
      <Stack.Screen options={{ title: "Log Food" }} />
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 60 }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={10} testID="log-pick-back">
            <Ionicons name="chevron-back" size={24} color={theme.color.text} />
          </Pressable>
          <Text style={styles.headerT}>LOG FOOD</Text>
          <View style={{ width: 24 }} />
        </View>
        <Text style={styles.subHead}>Choose how you want to add this meal.</Text>

        {modalities.map((m) => (
          <Pressable
            key={m.key}
            testID={`log-pick-${m.key}`}
            disabled={m.disabled}
            onPress={() => router.push(m.route as any)}
            style={[
              styles.card,
              m.primary && !m.disabled ? styles.cardPrimary : null,
              m.disabled ? styles.cardDisabled : null,
            ]}
          >
            <View style={[styles.iconWrap, m.primary && !m.disabled ? styles.iconWrapPrimary : null]}>
              <Ionicons
                name={m.icon}
                size={20}
                color={m.primary && !m.disabled ? "#fff" : theme.color.brand}
              />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.title}>{m.label}</Text>
              <Text style={styles.sub}>
                {m.disabled ? "Louis unlocks this after your next check-in." : m.sub}
              </Text>
            </View>
            {!m.disabled ? (
              <Ionicons name="chevron-forward" size={18} color={theme.color.textMuted} />
            ) : null}
          </Pressable>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: theme.color.surface },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 8,
  },
  headerT: {
    color: theme.color.text,
    fontSize: 15,
    fontWeight: "900",
    letterSpacing: 2,
  },
  subHead: {
    color: theme.color.textMuted,
    fontSize: 13,
    marginBottom: 16,
    lineHeight: 18,
  },
  card: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    padding: 14,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: theme.color.border,
    backgroundColor: theme.color.surface2,
    marginBottom: 10,
  },
  cardPrimary: {
    borderColor: theme.color.brand,
  },
  cardDisabled: {
    opacity: 0.45,
  },
  iconWrap: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: theme.color.surface,
    borderWidth: 1,
    borderColor: theme.color.border,
  },
  iconWrapPrimary: {
    backgroundColor: theme.color.brand,
    borderColor: theme.color.brand,
  },
  title: {
    color: theme.color.text,
    fontSize: 13,
    fontWeight: "900",
    letterSpacing: 1.2,
    marginBottom: 2,
  },
  sub: {
    color: theme.color.textMuted,
    fontSize: 12,
    lineHeight: 16,
  },
});
