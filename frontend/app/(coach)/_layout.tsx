import { Tabs, Slot } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";
import { useIsDesktop } from "@/src/lib/responsive";
import { DesktopShell } from "@/src/desktop/DesktopShell";

export default function CoachLayout() {
  const isDesktop = useIsDesktop();

  if (isDesktop) {
    return (
      <DesktopShell>
        <Slot />
      </DesktopShell>
    );
  }

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
      <Tabs.Screen name="v2-home" options={{ title: "HOME", tabBarIcon: ({ color }) => <Ionicons name="home" size={22} color={color} /> }} />
      <Tabs.Screen name="clients" options={{ title: "CLIENTS", tabBarIcon: ({ color }) => <Ionicons name="people" size={22} color={color} /> }} />
      <Tabs.Screen name="approvals" options={{ title: "APPROVALS", tabBarIcon: ({ color }) => <Ionicons name="checkmark-circle" size={22} color={color} /> }} />
      <Tabs.Screen name="library" options={{ title: "LIBRARY", tabBarIcon: ({ color }) => <Ionicons name="barbell" size={22} color={color} /> }} />
      <Tabs.Screen name="exercises" options={{ title: "CONTENT", tabBarIcon: ({ color }) => <Ionicons name="library" size={22} color={color} /> }} />
      <Tabs.Screen name="messages" options={{ title: "MESSAGES", tabBarIcon: ({ color }) => <Ionicons name="chatbubble-ellipses" size={22} color={color} /> }} />
      <Tabs.Screen name="profile" options={{ title: "PROFILE", tabBarIcon: ({ color }) => <Ionicons name="person" size={22} color={color} /> }} />
      {/* Desktop-only screens hidden from mobile tabs */}
      <Tabs.Screen name="overview" options={{ href: null }} />
      <Tabs.Screen name="calendar" options={{ href: null }} />
      <Tabs.Screen name="analytics" options={{ href: null }} />
      <Tabs.Screen name="videos" options={{ href: null }} />
      <Tabs.Screen name="checkins" options={{ href: null }} />
      <Tabs.Screen name="changelog" options={{ href: null }} />
      <Tabs.Screen name="library-legacy" options={{ href: null }} />
    </Tabs>
  );
}
