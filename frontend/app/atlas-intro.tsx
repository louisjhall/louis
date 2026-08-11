import React, { useEffect, useRef } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, Animated, Easing, Dimensions } from "react-native";
import Svg, { Circle, Ellipse, Line, Defs, RadialGradient, Stop } from "react-native-svg";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { theme } from "@/src/lib/theme";

/* -------------------------------------------------------------------------- */
/*  Atlas Intro                                                                */
/* -------------------------------------------------------------------------- */
const PRINCIPLES = [
  "Consistency beats perfection.",
  "Recovery drives performance.",
  "Train around your roster, not against it.",
  "Protect long-term health.",
  "Progress gradually.",
  "Individualise everything.",
  "Prioritise sustainable habits.",
  "Flexibility is essential for airline crew.",
  "Real life always comes before the perfect programme.",
  "Every recommendation should have a reason.",
];

export default function AtlasIntro() {
  const router = useRouter();
  const proceed = async () => {
    await AsyncStorage.setItem("atlas_welcomed", "1").catch(() => {});
    router.replace("/(auth)/login" as any);
  };

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <ScrollView contentContainerStyle={styles.body}>
        <View style={styles.top}>
          <Text style={styles.eyebrow}>CREWFIT INTELLIGENCE™</Text>
          <Text style={styles.title}>Meet <Text style={styles.brandRed}>Atlas</Text></Text>
        </View>

        <OrbitalSphere />

        <View style={styles.attribution}>
          <Text style={styles.attrLabel}>TRAINED BY</Text>
          <Text style={styles.attrName}>LOUIS HALL</Text>
          <Text style={styles.attrRole}>FOUNDER · HEAD COACH</Text>
        </View>

        <View style={styles.messageCard}>
          <Text style={styles.messageT}>
            Atlas has been trained using the <Text style={styles.brandRed}>CrewFit Coaching System</Text>.
          </Text>
          <Text style={styles.messageS}>
            Everything Atlas recommends is guided by Louis Hall&apos;s coaching philosophy.
          </Text>
        </View>

        <Text style={styles.sectionHead}>PRINCIPLES ATLAS FOLLOWS</Text>
        <View style={styles.principles}>
          {PRINCIPLES.map((p, i) => (
            <View key={i} style={styles.principle}>
              <View style={styles.principleNum}>
                <Text style={styles.principleNumT}>{String(i + 1).padStart(2, "0")}</Text>
              </View>
              <Text style={styles.principleT}>{p}</Text>
            </View>
          ))}
        </View>

        <View style={styles.rule}>
          <Ionicons name="shield-checkmark" size={18} color={theme.color.brand} />
          <Text style={styles.ruleText}>
            Atlas cannot coach outside these principles. It always works within the coaching framework designed by Louis.
          </Text>
        </View>

        <Pressable testID="see-guard-rails" onPress={() => router.push("/guard-rails" as any)} style={styles.secondaryBtn}>
          <Ionicons name="shield-half" size={14} color={theme.color.brand} />
          <Text style={styles.secondaryText}>SEE THE GUARD RAILS</Text>
        </Pressable>

        <Pressable testID="continue-atlas" onPress={proceed} style={styles.cta}>
          <Text style={styles.ctaText}>CONTINUE</Text>
          <Ionicons name="arrow-forward" size={16} color="#fff" />
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}

/* -------------------------------------------------------------------------- */
/*  Orbital Sphere — pure SVG + Animated                                       */
/* -------------------------------------------------------------------------- */
function OrbitalSphere() {
  const rot1 = useRef(new Animated.Value(0)).current;
  const rot2 = useRef(new Animated.Value(0)).current;
  const rot3 = useRef(new Animated.Value(0)).current;
  const pulse = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.loop(Animated.timing(rot1, { toValue: 1, duration: 12000, easing: Easing.linear, useNativeDriver: true })).start();
    Animated.loop(Animated.timing(rot2, { toValue: 1, duration: 18000, easing: Easing.linear, useNativeDriver: true })).start();
    Animated.loop(Animated.timing(rot3, { toValue: 1, duration: 24000, easing: Easing.linear, useNativeDriver: true })).start();
    Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { toValue: 1, duration: 2400, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
        Animated.timing(pulse, { toValue: 0, duration: 2400, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
      ])
    ).start();
  }, [rot1, rot2, rot3, pulse]);

  const spin = (v: Animated.Value) => v.interpolate({ inputRange: [0, 1], outputRange: ["0deg", "360deg"] });
  const spinRev = (v: Animated.Value) => v.interpolate({ inputRange: [0, 1], outputRange: ["360deg", "0deg"] });
  const pulseScale = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.95, 1.05] });
  const pulseOpacity = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.6, 1] });

  const size = Math.min(300, Dimensions.get("window").width - 60);
  const cx = size / 2;
  const cy = size / 2;

  return (
    <View style={[styles.sphereWrap, { width: size, height: size, alignSelf: "center" }]}>
      {/* Aviation crosshair backdrop */}
      <Svg width={size} height={size} style={StyleSheet.absoluteFill}>
        <Defs>
          <RadialGradient id="glow" cx="50%" cy="50%" r="50%">
            <Stop offset="0%" stopColor={theme.color.brand} stopOpacity="0.25" />
            <Stop offset="60%" stopColor={theme.color.brand} stopOpacity="0.05" />
            <Stop offset="100%" stopColor={theme.color.brand} stopOpacity="0" />
          </RadialGradient>
        </Defs>
        <Circle cx={cx} cy={cy} r={size / 2 - 4} fill="url(#glow)" />
        <Line x1={0} y1={cy} x2={size} y2={cy} stroke={theme.color.border} strokeWidth={0.5} strokeDasharray="4,6" />
        <Line x1={cx} y1={0} x2={cx} y2={size} stroke={theme.color.border} strokeWidth={0.5} strokeDasharray="4,6" />
      </Svg>

      {/* Outer orbit (slow) */}
      <Animated.View style={[StyleSheet.absoluteFill, { transform: [{ rotate: spin(rot3) }] }]}>
        <Svg width={size} height={size}>
          <Ellipse cx={cx} cy={cy} rx={size * 0.42} ry={size * 0.42} stroke={theme.color.brand} strokeOpacity={0.4} strokeWidth={1} fill="none" />
          <Circle cx={cx + size * 0.42} cy={cy} r={3} fill={theme.color.brand} />
        </Svg>
      </Animated.View>

      {/* Middle orbit (medium) */}
      <Animated.View style={[StyleSheet.absoluteFill, { transform: [{ rotate: spinRev(rot2) }, { rotateX: "60deg" }] }]}>
        <Svg width={size} height={size}>
          <Ellipse cx={cx} cy={cy} rx={size * 0.36} ry={size * 0.36} stroke={theme.color.brand} strokeOpacity={0.6} strokeWidth={1} fill="none" />
          <Circle cx={cx + size * 0.36} cy={cy} r={4} fill={theme.color.brand} />
          <Circle cx={cx - size * 0.36} cy={cy} r={2} fill={theme.color.brand} opacity={0.6} />
        </Svg>
      </Animated.View>

      {/* Inner orbit (fast) */}
      <Animated.View style={[StyleSheet.absoluteFill, { transform: [{ rotate: spin(rot1) }, { rotateX: "70deg" }] }]}>
        <Svg width={size} height={size}>
          <Ellipse cx={cx} cy={cy} rx={size * 0.28} ry={size * 0.28} stroke={theme.color.text} strokeOpacity={0.35} strokeWidth={1} fill="none" />
          <Circle cx={cx + size * 0.28} cy={cy} r={3.5} fill={theme.color.text} opacity={0.95} />
        </Svg>
      </Animated.View>

      {/* Core (pulsing) */}
      <Animated.View
        style={[
          StyleSheet.absoluteFill,
          { alignItems: "center", justifyContent: "center", transform: [{ scale: pulseScale }], opacity: pulseOpacity },
        ]}
        pointerEvents="none"
      >
        <View style={styles.coreOuter}>
          <View style={styles.coreInner}>
            <Text style={styles.coreLabel}>ATLAS</Text>
          </View>
        </View>
      </Animated.View>
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/*  Styles                                                                     */
/* -------------------------------------------------------------------------- */
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  body: { padding: 22, paddingBottom: 60 },
  top: { alignItems: "center", marginBottom: 12 },
  eyebrow: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 3, marginBottom: 8 },
  title: { color: theme.color.text, fontSize: 30, fontWeight: "800", letterSpacing: 1 },
  brandRed: { color: theme.color.brand, fontWeight: "900" },

  sphereWrap: { alignItems: "center", justifyContent: "center", marginVertical: 20 },
  coreOuter: {
    width: 90, height: 90, borderRadius: 45,
    borderWidth: 2, borderColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
    backgroundColor: theme.color.surface,
    shadowColor: theme.color.brand, shadowOpacity: 0.8, shadowRadius: 30, elevation: 15,
  },
  coreInner: {
    width: 66, height: 66, borderRadius: 33,
    backgroundColor: theme.color.brandTint,
    alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: theme.color.brand,
  },
  coreLabel: { color: theme.color.brand, fontSize: 12, fontWeight: "900", letterSpacing: 3 },

  attribution: { alignItems: "center", marginTop: 8, marginBottom: 20 },
  attrLabel: { color: theme.color.textDim, fontSize: 11, fontWeight: "800", letterSpacing: 3 },
  attrName: { color: theme.color.text, fontSize: 16, fontWeight: "900", letterSpacing: 2, marginTop: 4 },
  attrRole: { color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 2, marginTop: 3 },

  messageCard: {
    padding: 16, borderRadius: 12, marginBottom: 22,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  messageT: { color: theme.color.text, fontSize: 15, fontWeight: "700", lineHeight: 22 },
  messageS: { color: theme.color.textMuted, fontSize: 13, marginTop: 6, lineHeight: 19 },

  sectionHead: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2.5, marginBottom: 12 },
  principles: { marginBottom: 16 },
  principle: {
    flexDirection: "row", alignItems: "center", gap: 12,
    padding: 12, marginBottom: 6, borderRadius: 8,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  principleNum: {
    width: 26, height: 26, borderRadius: 13,
    backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
  },
  principleNumT: { color: theme.color.brand, fontSize: 11, fontWeight: "900" },
  principleT: { color: theme.color.text, fontSize: 13, fontWeight: "600", flex: 1 },

  rule: {
    flexDirection: "row", alignItems: "center", gap: 10,
    padding: 14, borderRadius: 10, marginBottom: 20,
    backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand,
  },
  ruleText: { flex: 1, color: theme.color.text, fontSize: 12, lineHeight: 18 },

  secondaryBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    paddingVertical: 12, borderRadius: 10, marginBottom: 10,
    borderWidth: 1, borderColor: theme.color.brand,
  },
  secondaryText: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },

  cta: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10,
    marginTop: 4, paddingVertical: 15, borderRadius: 12,
    backgroundColor: theme.color.brand,
  },
  ctaText: { color: "#fff", fontSize: 13, fontWeight: "900", letterSpacing: 3 },
});
