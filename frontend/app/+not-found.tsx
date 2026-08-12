/**
 * +not-found — Friendly 404 fallback screen (Iter171).
 *
 * Expo Router automatically renders this file whenever the user lands
 * on a URL / deeplink that doesn't match any registered route (e.g.
 * a stale push-notification deeplink, a mistyped path, or a screen
 * that has since been removed). We show a calm message with a single
 * primary action back to the home tab, so clients never end up
 * staring at a blank white bundle.
 */
import React from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Stack, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";

export default function NotFoundScreen() {
  const router = useRouter();
  const goHome = () => {
    // Prefer replace so the missing route doesn't linger in the stack.
    try {
      router.replace("/" as any);
    } catch {
      router.push("/" as any);
    }
  };

  return (
    <>
      <Stack.Screen options={{ title: "Not found", headerShown: false }} />
      <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
        <View style={styles.body} testID="not-found-screen">
          <View style={styles.iconWrap}>
            <Ionicons name="compass-outline" size={44} color={theme.color.brand} />
          </View>
          <Text style={styles.title}>This page didn&apos;t load</Text>
          <Text style={styles.subtitle}>
            The link you followed may be out of date, or the screen has moved.
            Head back to your dashboard and we&apos;ll pick things up from there.
          </Text>
          <Pressable style={styles.primaryBtn} onPress={goHome} testID="not-found-home">
            <Ionicons name="home" size={16} color="#000" />
            <Text style={styles.primaryBtnT}>BACK TO HOME</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    </>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  body: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 32,
    gap: 16,
  },
  iconWrap: {
    width: 88,
    height: 88,
    borderRadius: 44,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: theme.color.surface2,
    borderWidth: 1,
    borderColor: theme.color.border,
    marginBottom: 4,
  },
  title: {
    color: theme.color.text,
    fontSize: 20,
    fontWeight: "800",
    letterSpacing: 0.2,
    textAlign: "center",
  },
  subtitle: {
    color: theme.color.textMuted,
    fontSize: 14,
    lineHeight: 20,
    textAlign: "center",
    maxWidth: 320,
  },
  primaryBtn: {
    marginTop: 12,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 22,
    paddingVertical: 14,
    borderRadius: 999,
    backgroundColor: theme.color.brand,
  },
  primaryBtnT: {
    color: "#000",
    fontSize: 12,
    fontWeight: "900",
    letterSpacing: 1.5,
  },
});
