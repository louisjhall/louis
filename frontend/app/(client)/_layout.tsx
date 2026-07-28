import { Tabs } from "expo-router";
import { View } from "react-native";
import { PremiumTabBar } from "@/src/components/PremiumTabBar";
import { LouisWelcomeVideoModal } from "@/src/components/LouisWelcomeVideoModal";
import { CoachChatBubble } from "@/src/components/CoachChatBubble";

/**
 * Client tab layout — uses the bespoke <PremiumTabBar />. Each screen still
 * declares its title so accessibility labels remain meaningful; the visual
 * label + icon come from the custom bar.
 *
 * Iter 104 — `<LouisWelcomeVideoModal>` is mounted here so it fires the
 * first time any client lands on their tabbed home.
 *
 * Iter 122 — MESSAGES tab removed from the bottom bar and replaced with
 * BASE (Coming Soon community placeholder). Messaging with Coach Louis is
 * still accessible via the floating <CoachChatBubble /> and the underlying
 * /messages route (kept hidden from the tab bar so navigation still works).
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
      <LouisWelcomeVideoModal />
      <CoachChatBubble />
    </View>
  );
}
