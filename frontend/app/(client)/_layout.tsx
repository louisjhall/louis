import { Tabs } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";

export default function ClientLayout() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: theme.color.brand,
        tabBarInactiveTintColor: theme.color.textDim,
        tabBarStyle: {
          backgroundColor: theme.color.surface2,
          borderTopColor: theme.color.border,
          height: 82,
          paddingTop: 8,
          paddingBottom: 24,
        },
        tabBarLabelStyle: { fontSize: 10, letterSpacing: 1, fontWeight: "700" },
      }}
    >
      <Tabs.Screen name="home" options={{ title: "TODAY", tabBarIcon: ({ color }) => <Ionicons name="flash" size={22} color={color} /> }} />
      <Tabs.Screen name="calendar" options={{ title: "WEEK", tabBarIcon: ({ color }) => <Ionicons name="calendar" size={22} color={color} /> }} />
      <Tabs.Screen name="nutrition" options={{ title: "NUTRITION", tabBarIcon: ({ color }) => <Ionicons name="restaurant" size={22} color={color} /> }} />
      <Tabs.Screen name="messages" options={{ title: "MESSAGES", tabBarIcon: ({ color }) => <Ionicons name="chatbubble-ellipses" size={22} color={color} /> }} />
      <Tabs.Screen name="profile" options={{ title: "PROFILE", tabBarIcon: ({ color }) => <Ionicons name="person" size={22} color={color} /> }} />
    </Tabs>
  );
}
