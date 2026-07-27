import { Tabs } from "expo-router";
import { View } from "react-native";
import { PremiumTabBar } from "@/src/components/PremiumTabBar";
import { LouisWelcomeVideoModal } from "@/src/components/LouisWelcomeVideoModal";

/**
 * Client tab layout — uses the bespoke <PremiumTabBar />. Each screen still
 * declares its title so accessibility labels remain meaningful; the visual
 * label + icon come from the custom bar.
 *
 * Iter 104 — `<LouisWelcomeVideoModal>` is mounted here so it fires the
 * first time any client lands on their tabbed home (new signups AND
 * existing / switching clients). It self-gates via AsyncStorage and only
 * shows once per user.
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
        <Tabs.Screen name="messages"  options={{ title: "Messages" }} />
        <Tabs.Screen name="profile"   options={{ title: "Profile" }} />
      </Tabs>
      <LouisWelcomeVideoModal />
    </View>
  );
}
