import { Tabs } from "expo-router";
import { PremiumTabBar } from "@/src/components/PremiumTabBar";

/**
 * Client tab layout — uses the bespoke <PremiumTabBar />. Each screen still
 * declares its title so accessibility labels remain meaningful; the visual
 * label + icon come from the custom bar.
 */
export default function ClientLayout() {
  return (
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
  );
}
