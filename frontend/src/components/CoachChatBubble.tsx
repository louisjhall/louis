/**
 * CoachChatBubble — Trainerize-style floating messaging button (Iter 122).
 *
 * A small circular button positioned bottom-right, just above the client
 * bottom tab bar. Displays Coach Louis' stored profile image (falls back to
 * initials via <LouisAvatar />). Tapping it opens the existing messages
 * route — no new messaging logic is introduced.
 *
 * Ships an unread-count badge (top-right of the bubble) fed by
 * /api/messages-unread/count, matching the previous MESSAGES-tab behaviour.
 *
 * Suppresses itself when the client is already on the messages screen so we
 * don't cover the composer.
 */
import React from "react";
import { Pressable, StyleSheet, View, Text, Image, AppState, Platform } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import Animated, { useSharedValue, useAnimatedStyle, withSpring } from "react-native-reanimated";
import { useRouter, usePathname } from "expo-router";
import { theme } from "@/src/lib/theme";
import { api } from "@/src/lib/api";

// Iter 122b — use the bundled local asset directly so the photo always
// resolves (matches DailyBriefingModal + WeeklyReviewCard). This avoids
// any dependency on remote CDN / CORS / user network for the coach bubble.
const LOUIS_IMG = require("../../assets/louis/louis_avatar.png");

const BUBBLE_SIZE = 56;
const TAB_BAR_APPROX = 62;


function useUnreadMessages() {
  const [count, setCount] = React.useState(0);
  const load = React.useCallback(async () => {
    try {
      const r = await api<{ count: number }>("/messages-unread/count");
      setCount(Number(r?.count || 0));
    } catch {
      /* offline / logged out — silent */
    }
  }, []);
  React.useEffect(() => {
    load();
    const iv = setInterval(load, 30_000);
    const sub = AppState.addEventListener("change", (s) => { if (s === "active") load(); });
    return () => { clearInterval(iv); sub.remove(); };
  }, [load]);
  return count;
}


export function CoachChatBubble() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const pathname = usePathname() || "";
  const unread = useUnreadMessages();
  const scale = useSharedValue(1);

  // Do not render the bubble on the messages screen itself (avoids overlap
  // with the composer and back navigation).
  const suppress = pathname.includes("/messages");

  const anim = useAnimatedStyle(() => ({ transform: [{ scale: scale.value }] }));

  if (suppress) return null;

  const bottom = Math.max(insets.bottom, 10) + TAB_BAR_APPROX + 10;

  return (
    <View
      pointerEvents="box-none"
      style={[styles.host, { bottom }]}
      testID="coach-chat-bubble-host"
    >
      <Animated.View style={[anim]}>
        <Pressable
          testID="coach-chat-bubble"
          onPress={() => router.push("/(client)/messages")}
          onPressIn={() => { scale.value = withSpring(0.92, { damping: 18, stiffness: 260 }); }}
          onPressOut={() => { scale.value = withSpring(1, { damping: 18, stiffness: 260 }); }}
          hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
          accessibilityRole="button"
          accessibilityLabel="Message Coach Louis"
          style={styles.pressable}
        >
          <View style={styles.avatarWrap}>
            <Image
              source={LOUIS_IMG}
              style={styles.avatarImg}
              resizeMode="cover"
            />
          </View>
          {unread > 0 ? (
            <View style={styles.badge} testID="coach-chat-bubble-badge">
              <Text style={styles.badgeT}>{unread > 99 ? "99+" : unread}</Text>
            </View>
          ) : null}
          {/* Tiny chat glyph anchor so it reads as "message coach" not just "coach" */}
          <View style={styles.chatDot}>
            <View style={styles.chatDotInner} />
          </View>
        </Pressable>
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  host: {
    position: "absolute",
    right: 16,
    // `bottom` is set dynamically to sit just above the tab bar
    zIndex: 40,
    elevation: 12,
  },
  pressable: {
    width: BUBBLE_SIZE, height: BUBBLE_SIZE,
    borderRadius: BUBBLE_SIZE / 2,
    backgroundColor: theme.color.surface2,
    borderWidth: 2, borderColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
    ...Platform.select({
      ios: {
        shadowColor: "#000",
        shadowOpacity: 0.35,
        shadowOffset: { width: 0, height: 4 },
        shadowRadius: 8,
      },
      default: {},
    }),
  },
  avatarWrap: {
    width: BUBBLE_SIZE - 6, height: BUBBLE_SIZE - 6,
    borderRadius: (BUBBLE_SIZE - 6) / 2,
    overflow: "hidden",
    alignItems: "center", justifyContent: "center",
    backgroundColor: theme.color.surface2,
  },
  avatarImg: { width: "100%", height: "100%" },
  badge: {
    position: "absolute", top: -4, right: -4,
    minWidth: 20, height: 20, paddingHorizontal: 5,
    borderRadius: 10, backgroundColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
    borderWidth: 2, borderColor: theme.color.bg,
  },
  badgeT: { color: "#fff", fontSize: 10, fontWeight: "900" },
  chatDot: {
    position: "absolute", bottom: -2, right: -2,
    width: 16, height: 16, borderRadius: 8,
    backgroundColor: theme.color.brand,
    borderWidth: 2, borderColor: theme.color.bg,
    alignItems: "center", justifyContent: "center",
  },
  chatDotInner: {
    width: 5, height: 5, borderRadius: 2.5,
    backgroundColor: "#fff",
  },
});

export default CoachChatBubble;
