import React, { useEffect } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, Dimensions } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { theme } from "@/src/lib/theme";

/* -------------------------------------------------------------------------- */
/*  Welcome — Louis Hall introduction                                          */
/* -------------------------------------------------------------------------- */
export default function Welcome() {
  const router = useRouter();
  const { width } = Dimensions.get("window");

  useEffect(() => {
    // Prefetch — mark that user reached welcome
    AsyncStorage.setItem("atlas_welcomed_started", "1").catch(() => {});
  }, []);

  const proceed = async () => {
    await AsyncStorage.setItem("atlas_welcomed", "1").catch(() => {});
    router.replace("/atlas-intro" as any);
  };

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <ScrollView contentContainerStyle={styles.body}>
        {/* Brand */}
        <View style={styles.brandRow}>
          <Text style={styles.brand}>CREW<Text style={styles.brandRed}>FIT</Text></Text>
          <Text style={styles.brandSub}>WELCOME</Text>
        </View>

        {/* Video placeholder */}
        <View style={[styles.videoCard, { height: width * 0.6 }]}>
          <View style={styles.videoGrid} pointerEvents="none">
            {Array.from({ length: 16 }).map((_, i) => (
              <View key={i} style={styles.videoGridDot} />
            ))}
          </View>
          <View style={styles.videoInner}>
            <View style={styles.playRing}>
              <Ionicons name="play" size={26} color="#fff" />
            </View>
            <Text style={styles.videoName}>LOUIS HALL</Text>
            <Text style={styles.videoRole}>FOUNDER · HEAD COACH</Text>
            <View style={styles.videoBadge}>
              <Ionicons name="film" size={10} color={theme.color.brand} />
              <Text style={styles.videoBadgeT}>WELCOME VIDEO · COMING SOON</Text>
            </View>
          </View>
        </View>

        <View style={styles.divider} />

        {/* Main copy */}
        <Text style={styles.headline}>Welcome to CrewFit.</Text>

        <Text style={styles.paragraph}>
          Hi, I&apos;m Louis Hall, Founder and Head Coach. I&apos;m genuinely excited you&apos;ve decided to trust CrewFit with your goals.
        </Text>
        <Text style={styles.paragraph}>
          Before we begin, I want to explain something that&apos;s central to how we coach.
        </Text>
        <Text style={styles.paragraph}>
          You&apos;ll see <Text style={styles.atlasWord}>Atlas</Text> mentioned throughout the app.
        </Text>

        <View style={styles.emphasis}>
          <Text style={styles.emphasisTop}>Atlas isn&apos;t your coach.</Text>
          <Text style={styles.emphasisBig}>I am.</Text>
        </View>

        <Text style={styles.paragraph}>
          Atlas is the intelligence engine I built to apply my coaching philosophy every single day.
        </Text>
        <Text style={styles.paragraph}>
          Over the years I&apos;ve coached people from complete beginners through to endurance athletes and airline professionals. I&apos;ve learned what works. I&apos;ve learned what doesn&apos;t.
        </Text>
        <Text style={styles.paragraph}>
          I&apos;ve developed principles, systems and coaching standards that I believe produce long-term results. Atlas has been built around those principles.
        </Text>
        <Text style={styles.paragraph}>
          I&apos;ve spent countless hours teaching Atlas how I make coaching decisions.
        </Text>

        <View style={styles.pillGrid}>
          {[
            "When to push",
            "When to recover",
            "How to programme around rosters",
            "How to manage fatigue",
            "How to progress safely",
            "How to prioritise consistency over perfection",
          ].map((s, i) => (
            <View key={i} style={styles.pill}><Text style={styles.pillT}>{s}</Text></View>
          ))}
        </View>

        <Text style={styles.paragraph}>
          Atlas follows the guard rails I&apos;ve created. It analyses information far quicker than I ever could on my own, but it always works within my coaching philosophy.
        </Text>

        <View style={styles.card}>
          <Text style={styles.cardHead}>THINK OF ATLAS AS MY COACHING PARTNER</Text>
          <View style={styles.cardRow}>
            <View style={{ flex: 1 }}>
              <Text style={styles.cardLbl}>ATLAS</Text>
              {["Handles the analysis", "Spots patterns", "Prepares recommendations", "Personalises programmes"].map((s, i) => (
                <View key={i} style={styles.cardBullet}>
                  <Ionicons name="ellipse" size={5} color={theme.color.brand} />
                  <Text style={styles.cardBulletT}>{s}</Text>
                </View>
              ))}
            </View>
            <View style={styles.cardDivider} />
            <View style={{ flex: 1 }}>
              <Text style={styles.cardLbl}>LOUIS</Text>
              {["Responsible for the coaching", "Reviews important decisions", "Refines your programme", "Supports your journey"].map((s, i) => (
                <View key={i} style={styles.cardBullet}>
                  <Ionicons name="ellipse" size={5} color={theme.color.text} />
                  <Text style={styles.cardBulletT}>{s}</Text>
                </View>
              ))}
            </View>
          </View>
        </View>

        <Text style={styles.paragraph}>
          Together we combine human coaching with intelligent technology to create something that&apos;s simply not possible with either one alone.
        </Text>
        <Text style={styles.paragraph}>
          That&apos;s what makes CrewFit different.
        </Text>

        <Text style={styles.close}>Let&apos;s build something you&apos;re proud of.</Text>
        <Text style={styles.signature}>— Louis</Text>

        <Pressable testID="meet-atlas" onPress={proceed} style={styles.cta}>
          <Text style={styles.ctaText}>MEET ATLAS</Text>
          <Ionicons name="arrow-forward" size={16} color="#fff" />
        </Pressable>
        <Pressable testID="welcome-skip" onPress={proceed} style={styles.skipBtn}>
          <Text style={styles.skipText}>SKIP INTRO</Text>
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}

/* -------------------------------------------------------------------------- */
/*  Styles                                                                     */
/* -------------------------------------------------------------------------- */
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  body: { padding: 22, paddingBottom: 60 },

  brandRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 20 },
  brand: { color: theme.color.text, fontSize: 20, fontWeight: "900", letterSpacing: 3 },
  brandRed: { color: theme.color.brand },
  brandSub: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 3 },

  videoCard: {
    borderRadius: 14, overflow: "hidden",
    backgroundColor: "#0a0a0a", borderWidth: 1, borderColor: theme.color.border,
    marginBottom: 24, position: "relative",
    alignItems: "center", justifyContent: "center",
  },
  videoGrid: { ...StyleSheet.absoluteFillObject, flexDirection: "row", flexWrap: "wrap", opacity: 0.25 },
  videoGridDot: { width: "25%", height: "25%", borderRightWidth: 1, borderBottomWidth: 1, borderColor: "rgba(255,255,255,0.03)" },
  videoInner: { alignItems: "center", padding: 20 },
  playRing: {
    width: 70, height: 70, borderRadius: 35,
    backgroundColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
    marginBottom: 16,
    borderWidth: 2, borderColor: "#fff",
    shadowColor: theme.color.brand, shadowOpacity: 0.6, shadowRadius: 20, elevation: 10,
  },
  videoName: { color: "#fff", fontSize: 18, fontWeight: "900", letterSpacing: 3, marginTop: 4 },
  videoRole: { color: theme.color.brand, fontSize: 10, fontWeight: "800", letterSpacing: 2.5, marginTop: 3 },
  videoBadge: {
    flexDirection: "row", alignItems: "center", gap: 6,
    marginTop: 14, paddingHorizontal: 10, paddingVertical: 4, borderRadius: 4,
    backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand,
  },
  videoBadgeT: { color: theme.color.brand, fontSize: 8, fontWeight: "900", letterSpacing: 1.5 },

  divider: { height: 1, backgroundColor: theme.color.border, marginBottom: 22 },

  headline: { color: theme.color.text, fontSize: 26, fontWeight: "800", marginBottom: 14, lineHeight: 32 },
  paragraph: { color: theme.color.text, fontSize: 15, lineHeight: 24, marginBottom: 14, fontWeight: "400" },
  atlasWord: { color: theme.color.brand, fontWeight: "900", letterSpacing: 0.5 },

  emphasis: {
    marginVertical: 20, padding: 20, borderRadius: 12,
    backgroundColor: theme.color.brandTint, borderLeftWidth: 3, borderLeftColor: theme.color.brand,
  },
  emphasisTop: { color: theme.color.textMuted, fontSize: 16, fontWeight: "600" },
  emphasisBig: { color: theme.color.brand, fontSize: 40, fontWeight: "900", letterSpacing: 1, marginTop: 4 },

  pillGrid: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginVertical: 10, marginBottom: 18 },
  pill: {
    paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  pillT: { color: theme.color.text, fontSize: 11, fontWeight: "700" },

  card: {
    marginVertical: 14, padding: 16, borderRadius: 12,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.brand,
  },
  cardHead: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 2, marginBottom: 14 },
  cardRow: { flexDirection: "row", gap: 14 },
  cardDivider: { width: 1, backgroundColor: theme.color.border },
  cardLbl: { color: theme.color.text, fontSize: 12, fontWeight: "900", letterSpacing: 2, marginBottom: 8 },
  cardBullet: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 6 },
  cardBulletT: { color: theme.color.textMuted, fontSize: 11, flex: 1, lineHeight: 15 },

  close: { color: theme.color.text, fontSize: 17, fontWeight: "700", marginTop: 8, lineHeight: 24 },
  signature: { color: theme.color.brand, fontSize: 15, fontWeight: "900", marginTop: 8, letterSpacing: 1 },

  cta: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10,
    marginTop: 30, paddingVertical: 16, borderRadius: 12,
    backgroundColor: theme.color.brand,
  },
  ctaText: { color: "#fff", fontSize: 14, fontWeight: "900", letterSpacing: 3 },
  skipBtn: { alignItems: "center", paddingVertical: 14 },
  skipText: { color: theme.color.textMuted, fontSize: 10, fontWeight: "800", letterSpacing: 2 },
});
