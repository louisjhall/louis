import { Tabs } from "expo-router";
import { View } from "react-native";
import { PremiumTabBar } from "@/src/components/PremiumTabBar";
import { CoachChatBubble } from "@/src/components/CoachChatBubble";

/**
 * Client tab layout — uses the bespoke <PremiumTabBar />.
 *
 * Iter 122 — MESSAGES tab replaced with BASE (Coming Soon community
 * placeholder). Messaging with Coach Louis is now on the floating
 * <CoachChatBubble />; the underlying /messages route is kept hidden
 * from the bar so navigation still works.
 *
 * Iter 122d — Removed the standalone <LouisWelcomeVideoModal>. Louis'
 * welcome video is hosted inside the /welcome introduction page's video
 * card. Mounting it here caused the video player to autoplay in the
 * background (audio without a visible frame) on the client home. If we
 * ever need a modal replay, we can re-mount it later gated on visibility.
 */
export default function ClientLayout() {
  return (
    <View style={{ flex: 1 }}>
      <Tabs
        tabBar={(props) => <PremiumTabBar {...props} />}
        screenOptions={{ headerShown: false }}
      >
        <Tabs.Screen name="home"      options={{ title: "Today" }} />
        <Tabs.Screen name="calendar"  options={{ title: "Calendar" }} />
        <Tabs.Screen name="nutrition" options={{ title: "Nutrition" }} />
        <Tabs.Screen name="base"      options={{ title: "Base" }} />
        <Tabs.Screen name="profile"   options={{ title: "Profile" }} />
        {/* Messages route still exists — hidden from the bar, opened via CoachChatBubble */}
        <Tabs.Screen name="messages"  options={{ title: "Messages", href: null }} />
      </Tabs>
      <CoachChatBubble />
    </View>
  );
}
