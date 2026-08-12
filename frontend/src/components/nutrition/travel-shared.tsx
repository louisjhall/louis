/**
 * Shared premium travel-guidance components (Phase 4).
 */
import React from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { theme } from "@/src/lib/theme";

export function TravelHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  const router = useRouter();
  return (
    <View style={styles.header}>
      <Pressable onPress={() => router.back()} hitSlop={12}>
        <Ionicons name="chevron-back" size={24} color={theme.color.text} />
      </Pressable>
      <View style={{ flex: 1, alignItems: "center" }}>
        <Text style={styles.headerT}>{title}</Text>
        {subtitle ? <Text style={styles.headerSub}>{subtitle}</Text> : null}
      </View>
      <View style={{ width: 24 }} />
    </View>
  );
}

export function Screen({ children }: { children: React.ReactNode }) {
  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      {children}
    </SafeAreaView>
  );
}

export function LoadingBlock({ text = "Atlas is thinking…" }: { text?: string }) {
  return (
    <View style={styles.loading}>
      <ActivityIndicator color={theme.color.brand} size="large" />
      <Text style={styles.loadingT}>{text}</Text>
    </View>
  );
}

export function ContextRibbon({ goal, remaining }: { goal?: string; remaining?: { calories?: number; protein_g?: number; hydration_ml?: number } }) {
  if (!goal && !remaining) return null;
  return (
    <View style={styles.ribbon}>
      {goal ? (
        <View style={styles.ribbonPill}>
          <Ionicons name="flag" size={11} color={theme.color.brand} />
          <Text style={styles.ribbonT}>{goal.replace(/_/g, " ").toUpperCase()}</Text>
        </View>
      ) : null}
      {remaining ? (
        <View style={styles.ribbonPill}>
          <Ionicons name="flame" size={11} color={theme.color.brand} />
          <Text style={styles.ribbonT}>{remaining.calories}kcal LEFT</Text>
        </View>
      ) : null}
      {remaining && remaining.protein_g !== undefined ? (
        <View style={styles.ribbonPill}>
          <Ionicons name="barbell" size={11} color={theme.color.brand} />
          <Text style={styles.ribbonT}>{Math.round(remaining.protein_g)}g P LEFT</Text>
        </View>
      ) : null}
    </View>
  );
}

export function ResultCard({ headline, reason, confidence }: { headline: string; reason?: string; confidence?: string }) {
  return (
    <View style={styles.rCard}>
      <View style={styles.rHead}>
        <Ionicons name="sparkles" size={14} color={theme.color.brand} />
        <Text style={styles.rHeadT}>ATLAS CALL</Text>
        {confidence ? (
          <View style={[styles.confPill, confStyle(confidence)]}>
            <Text style={styles.confT}>{confidence.toUpperCase()}</Text>
          </View>
        ) : null}
      </View>
      <Text style={styles.rHeadline}>{headline}</Text>
      {reason ? <Text style={styles.rReason}>{reason}</Text> : null}
    </View>
  );
}

export function ListBlock({ icon, color, title, items }: {
  icon: any; color: string; title: string; items?: string[];
}) {
  if (!items?.length) return null;
  return (
    <View style={styles.lBlock}>
      <View style={styles.lHead}>
        <Ionicons name={icon} size={13} color={color} />
        <Text style={[styles.lHeadT, { color }]}>{title}</Text>
      </View>
      {items.map((t, i) => (
        <View key={i} style={styles.lRow}>
          <View style={[styles.lDot, { backgroundColor: color }]} />
          <Text style={styles.lRowT}>{t}</Text>
        </View>
      ))}
    </View>
  );
}

export function Chips({ values, selected, onSelect, testIDPrefix }: {
  values: { key: string; label: string; icon?: any }[]; selected: string | null; onSelect: (k: string) => void; testIDPrefix?: string;
}) {
  return (
    <View style={styles.chipsRow}>
      {values.map((v) => {
        const on = selected === v.key;
        return (
          <Pressable key={v.key} onPress={() => onSelect(v.key)}
            testID={testIDPrefix ? `${testIDPrefix}-${v.key}` : undefined}
            style={[styles.chip, on && styles.chipOn]}>
            {v.icon ? <Ionicons name={v.icon} size={11} color={on ? "#fff" : theme.color.brand} /> : null}
            <Text style={[styles.chipT, on && styles.chipTOn]}>{v.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

function confStyle(c: string) {
  if (c === "high") return { backgroundColor: theme.color.green };
  if (c === "low") return { backgroundColor: "#c94a4a" };
  return { backgroundColor: theme.color.amber };
}

export const travelStyles = StyleSheet.create({
  section: { color: theme.color.brand, fontSize: 11, letterSpacing: 2, fontWeight: "900", marginTop: 6, fontFamily: theme.font.textSemi },
  input: { color: theme.color.onRed, backgroundColor: theme.color.surface2, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 10, fontSize: 14, borderWidth: 1, borderColor: theme.color.border },
  primaryBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingVertical: 14, borderRadius: 10, backgroundColor: theme.color.brand },
  primaryBtnT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 1.5 },
  disclaimer: { color: theme.color.textDim, fontSize: 11, textAlign: "center", fontStyle: "italic", lineHeight: 15, paddingHorizontal: 8, marginTop: 6 },
});

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", padding: 14, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  headerT: { color: theme.color.text, fontSize: 14, letterSpacing: 3, fontWeight: "900", fontFamily: theme.font.display },
  headerSub: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1.5, marginTop: 2 },

  loading: { alignItems: "center", justifyContent: "center", padding: 40, gap: 10 },
  loadingT: { color: theme.color.textMuted, fontSize: 12, marginTop: 6 },

  ribbon: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 4 },
  ribbonPill: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand },
  ribbonT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 0.5 },

  rCard: { padding: 16, borderRadius: 12, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand, gap: 8 },
  rHead: { flexDirection: "row", alignItems: "center", gap: 6 },
  rHeadT: { color: theme.color.brand, fontSize: 11, letterSpacing: 2, fontWeight: "900", flex: 1 },
  confPill: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  confT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 0.7 },
  rHeadline: { color: theme.color.text, fontSize: 17, fontWeight: "900", fontFamily: theme.font.display, lineHeight: 22 },
  rReason: { color: theme.color.textMuted, fontSize: 13, lineHeight: 19, fontFamily: theme.font.text },

  lBlock: { padding: 14, borderRadius: 10, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, gap: 8 },
  lHead: { flexDirection: "row", alignItems: "center", gap: 6 },
  lHeadT: { fontSize: 11, letterSpacing: 2, fontWeight: "900" },
  lRow: { flexDirection: "row", alignItems: "flex-start", gap: 8 },
  lDot: { width: 5, height: 5, borderRadius: 3, marginTop: 8 },
  lRowT: { color: theme.color.text, fontSize: 13, flex: 1, lineHeight: 19, fontFamily: theme.font.text },

  chipsRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 7, borderRadius: 20, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  chipOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1 },
  chipTOn: { color: "#fff" },
});
