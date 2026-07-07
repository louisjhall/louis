import { Tabs } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";

export default function CoachLayout() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: theme.color.brand,
        tabBarInactiveTintColor: theme.color.textDim,
        tabBarStyle: { backgroundColor: theme.color.surface2, borderTopColor: theme.color.border, height: 82, paddingTop: 8, paddingBottom: 24 },
        tabBarLabelStyle: { fontSize: 10, letterSpacing: 1, fontWeight: "700" },
      }}
    >
      <Tabs.Screen name="clients" options={{ title: "CLIENTS", tabBarIcon: ({ color }) => <Ionicons name="people" size={22} color={color} /> }} />
      <Tabs.Screen name="approvals" options={{ title: "APPROVALS", tabBarIcon: ({ color }) => <Ionicons name="checkmark-circle" size={22} color={color} /> }} />
      <Tabs.Screen name="library" options={{ title: "LIBRARY", tabBarIcon: ({ color }) => <Ionicons name="barbell" size={22} color={color} /> }} />
      <Tabs.Screen name="messages" options={{ title: "MESSAGES", tabBarIcon: ({ color }) => <Ionicons name="chatbubble-ellipses" size={22} color={color} /> }} />
      <Tabs.Screen name="profile" options={{ title: "PROFILE", tabBarIcon: ({ color }) => <Ionicons name="person" size={22} color={color} /> }} />
    </Tabs>
  );
}
