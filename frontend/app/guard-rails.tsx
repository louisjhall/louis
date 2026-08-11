import { View, Text, StyleSheet, ScrollView, Pressable } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";

const NEVER = [
  "Ignore injuries.",
  "Recommend unsafe progressions.",
  "Schedule unrealistic workloads.",
  "Ignore recovery.",
  "Override coach locked sessions.",
  "Ignore important life events.",
  "Ignore client feedback.",
  "Replace coach judgement.",
];

const ALWAYS = [
  "Explain why recommendations are made.",
  "Protect recovery.",
  "Respect programme structure.",
  "Adapt to roster changes.",
  "Learn from your progress.",
  "Work within Louis' coaching methodology.",
];

export default function GuardRails() {
  const router = useRouter();

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} testID="rails-back">
          <Ionicons name="chevron-back" size={24} color={theme.color.text} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.eyebrow}>CREWFIT COACHING SYSTEM</Text>
          <Text style={styles.title}>Atlas <Text style={styles.brandRed}>Guard Rails</Text></Text>
        </View>
      </View>

      <ScrollView contentContainerStyle={styles.body}>
        <Text style={styles.intro}>
          Throughout the app Atlas operates inside strict coaching rules designed by Louis Hall.
        </Text>

        <View style={[styles.card, styles.cardNever]}>
          <View style={styles.cardHeadRow}>
            <View style={[styles.iconWrap, { backgroundColor: "rgba(220, 38, 38, 0.15)" }]}>
              <Ionicons name="close-circle" size={20} color={theme.color.red} />
            </View>
            <Text style={styles.cardHead}>ATLAS WILL NEVER</Text>
          </View>
          {NEVER.map((n, i) => (
            <View key={i} style={styles.row}>
              <Ionicons name="close" size={14} color={theme.color.red} />
              <Text style={styles.rowT}>{n}</Text>
            </View>
          ))}
        </View>

        <View style={[styles.card, styles.cardAlways]}>
          <View style={styles.cardHeadRow}>
            <View style={[styles.iconWrap, { backgroundColor: theme.color.brandTint }]}>
              <Ionicons name="checkmark-circle" size={20} color={theme.color.brand} />
            </View>
            <Text style={styles.cardHead}>ATLAS WILL ALWAYS</Text>
          </View>
          {ALWAYS.map((n, i) => (
            <View key={i} style={styles.row}>
              <Ionicons name="checkmark" size={14} color={theme.color.brand} />
              <Text style={styles.rowT}>{n}</Text>
            </View>
          ))}
        </View>

        <View style={styles.footNote}>
          <Ionicons name="shield-checkmark" size={16} color={theme.color.brand} />
          <Text style={styles.footNoteT}>
            These rules are non-negotiable. Louis reviews every important coaching decision and can override any Atlas recommendation.
          </Text>
        </View>

        <Pressable onPress={() => router.back()} style={styles.cta} testID="rails-got-it">
          <Text style={styles.ctaText}>GOT IT</Text>
          <Ionicons name="arrow-forward" size={14} color="#fff" />
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: {
    flexDirection: "row", alignItems: "center", gap: 12,
    padding: 18, borderBottomWidth: 1, borderBottomColor: theme.color.divider,
  },
  eyebrow: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2.5 },
  title: { color: theme.color.text, fontSize: 18, fontWeight: "800", marginTop: 3 },
  brandRed: { color: theme.color.brand, fontWeight: "900" },
  body: { padding: 20, paddingBottom: 40 },
  intro: { color: theme.color.textMuted, fontSize: 13, lineHeight: 20, marginBottom: 20 },

  card: {
    padding: 16, borderRadius: 14, marginBottom: 16,
    backgroundColor: theme.color.surface2, borderWidth: 1,
  },
  cardNever: { borderColor: "rgba(220, 38, 38, 0.35)" },
  cardAlways: { borderColor: theme.color.brand },
  cardHeadRow: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 14 },
  iconWrap: {
    width: 36, height: 36, borderRadius: 18,
    alignItems: "center", justifyContent: "center",
  },
  cardHead: { color: theme.color.text, fontSize: 12, fontWeight: "900", letterSpacing: 2 },

  row: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 6 },
  rowT: { color: theme.color.text, fontSize: 13, flex: 1, lineHeight: 19 },

  footNote: {
    flexDirection: "row", alignItems: "flex-start", gap: 10,
    padding: 14, borderRadius: 10,
    backgroundColor: theme.color.brandTint, borderLeftWidth: 3, borderLeftColor: theme.color.brand,
    marginBottom: 24,
  },
  footNoteT: { flex: 1, color: theme.color.text, fontSize: 12, lineHeight: 18 },

  cta: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    paddingVertical: 14, borderRadius: 12,
    backgroundColor: theme.color.brand,
  },
  ctaText: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 3 },
});
