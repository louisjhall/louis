/**
 * Shared ComingSoon shell used by Nutrition Phase-2–51 placeholders.
 * Aviation-premium dark, same brand tokens as the main screens.
 */
import React from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { theme } from "@/src/lib/theme";

export default function ComingSoon({
  title, subtitle, description, bullets, icon, disclaimer,
}: {
  title: string; subtitle?: string; description: string;
  bullets?: string[]; icon?: any; disclaimer?: string;
}) {
  const router = useRouter();
  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="chevron-back" size={24} color={theme.color.text} />
        </Pressable>
        <Text style={styles.headerT}>{title}</Text>
        <View style={{ width: 24 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: 20, gap: 20 }}>
        <View style={styles.hero}>
          <View style={styles.iconWrap}>
            <Ionicons name={icon || "sparkles"} size={40} color={theme.color.brand} />
          </View>
          <Text style={styles.title}>{title}</Text>
          {subtitle ? (
            <View style={styles.phasePill}><Text style={styles.phaseT}>{subtitle.toUpperCase()}</Text></View>
          ) : null}
        </View>

        <Text style={styles.desc}>{description}</Text>

        {bullets?.length ? (
          <View style={styles.list}>
            {bullets.map((b) => (
              <View key={b} style={styles.row}>
                <Ionicons name="checkmark-circle" size={14} color={theme.color.brand} />
                <Text style={styles.rowT}>{b}</Text>
              </View>
            ))}
          </View>
        ) : null}

        {disclaimer ? <Text style={styles.disclaimer}>{disclaimer}</Text> : null}

        <Pressable onPress={() => router.back()} style={styles.btn}>
          <Text style={styles.btnT}>BACK TO NUTRITION</Text>
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 14, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  headerT: { color: theme.color.text, fontSize: 14, letterSpacing: 3, fontWeight: "900", fontFamily: theme.font.display },
  hero: { alignItems: "center", gap: 12, marginTop: 20 },
  iconWrap: { width: 80, height: 80, borderRadius: 40, backgroundColor: theme.color.brandTint, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: theme.color.brand },
  title: { color: theme.color.text, fontSize: 22, fontWeight: "900", letterSpacing: 1, fontFamily: theme.font.display, textAlign: "center" },
  phasePill: { paddingHorizontal: 10, paddingVertical: 5, borderRadius: 20, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  phaseT: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 2, fontWeight: "900" },
  desc: { color: theme.color.text, fontSize: 14, lineHeight: 22, textAlign: "center", fontFamily: theme.font.text, paddingHorizontal: 10 },
  list: { gap: 8, padding: 16, borderRadius: 12, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  rowT: { color: theme.color.text, fontSize: 13, fontFamily: theme.font.text, flex: 1 },
  disclaimer: { color: theme.color.textDim, fontSize: 11, textAlign: "center", fontStyle: "italic", lineHeight: 17, paddingHorizontal: 20 },
  btn: { paddingVertical: 14, borderRadius: 10, backgroundColor: theme.color.brand, alignItems: "center", marginTop: 8 },
  btnT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 1.5 },
});
