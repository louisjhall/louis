import React from "react";
import { View, Text, Pressable, StyleSheet, ScrollView } from "react-native";
import { useRouter, usePathname } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";
import { useAuth } from "@/src/lib/auth";
import { CrewFitLogo } from "@/src/components/Logo";
import { LouisAvatar } from "@/src/components/LouisAvatar";
import { LOUIS, isLouis } from "@/src/lib/coachProfile";

const NAV: { path: string; label: string; icon: any; testId: string; adminOnly?: boolean }[] = [
  // Iter 128h — Coach nav consolidated further. Videos + Approvals are gone
  // from the primary sidebar. Approvals surface via the Home Action Queue
  // and deep-link straight into the workspace review flow. Videos had no
  // useful coach-facing purpose. Underlying routes remain reachable by
  // direct URL / testing agents, but are no longer part of daily coaching.
  { path: "/(coach)/v2-home",   label: "Home",             icon: "home-outline",         testId: "desktop-nav-home" },
  { path: "/(coach)/clients",   label: "Clients",          icon: "people-outline",       testId: "desktop-nav-clients" },
  { path: "/(coach)/calendar",  label: "Calendar",         icon: "calendar-outline",     testId: "desktop-nav-calendar" },
  { path: "/(coach)/library",   label: "Library",          icon: "barbell-outline",      testId: "desktop-nav-library" },
  // Iter184 · Auto-Media pinned in primary sidebar — surfaces the Bulk
  // Primary-Image + YouTube Video Finder actions from any coach screen
  // without requiring the coach to first navigate into Library. Fixes the
  // long-standing "the button is missing on Desktop" complaint by making
  // the tools reachable from every route.
  { path: "/coach/admin/auto-media", label: "Auto-Media", icon: "sparkles-outline", testId: "desktop-nav-auto-media" },
  { path: "/(coach)/messages",  label: "Messages",         icon: "chatbubble-ellipses-outline", testId: "desktop-nav-messages" },
  { path: "/(coach)/crew-base", label: "Crew Base",        icon: "people-circle-outline", testId: "desktop-nav-crew-base" },
  { path: "/(coach)/analytics", label: "Analytics",        icon: "bar-chart-outline",    testId: "desktop-nav-analytics" },
  { path: "/(coach)/changelog", label: "Change Log",       icon: "time-outline",         testId: "desktop-nav-changelog" },
  { path: "/coach/admin/coaches", label: "Coaches (Admin)", icon: "people-circle-outline", testId: "desktop-nav-admin-coaches", adminOnly: true },
  { path: "/(coach)/profile",   label: "Profile",          icon: "person-outline",       testId: "desktop-nav-profile" },
];

function isActive(pathname: string, target: string): boolean {
  // Iter184 · Two target shapes now:
  //   1) grouped:      "/(coach)/library"      → match segment "library"
  //   2) non-grouped:  "/coach/admin/auto-media" → match full literal
  if (target.includes(")/")) {
    const seg = target.split(")/")[1] || target;
    if (!seg) return false;
    return pathname.endsWith("/" + seg) || pathname === "/" + seg;
  }
  // Non-grouped literal path — exact match or prefix (for nested subroutes).
  return pathname === target || pathname.startsWith(target + "/");
}

export function DesktopShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { user, logout } = useAuth();

  // Iter 130a — desktop SIGN OUT previously called `logout` directly, which
  // cleared the token + user state but never navigated. The only
  // `!user → login` guard lives at `/app/index.tsx`, so on any nested route
  // the sidebar looked unresponsive. Mirror the mobile profile screens by
  // routing to /(auth)/login explicitly after logout completes.
  const handleLogout = async () => {
    try { await logout(); } catch {}
    router.replace("/(auth)/login" as any);
  };

  return (
    <View style={styles.root} testID="desktop-shell">
      <View style={styles.sidebar}>
        <View style={styles.brandRow}>
          <CrewFitLogo size={44} style={{ marginRight: 4 }} />
          <View style={{ flex: 1 }}>
            <Text style={styles.brand}>CREWFIT</Text>
            <Text style={styles.tagline}>COACH DESKTOP · v1.0.24</Text>
          </View>
        </View>

        <View style={styles.userBlock} testID="desktop-coach-identity">
          {isLouis(user) ? (
            <>
              <LouisAvatar size={44} showRing />
              <View style={{ flex: 1 }}>
                <Text style={styles.userName} numberOfLines={1}>{LOUIS.fullName}</Text>
                <Text style={styles.userTitle} numberOfLines={1}>Head Coach</Text>
                <Text style={styles.userEmail} numberOfLines={1}>{user?.email || LOUIS.email}</Text>
              </View>
            </>
          ) : (
            <>
              <View style={styles.avatar}>
                <Text style={styles.avatarText}>
                  {(user?.name || "C").split(" ").map((p) => p.charAt(0)).slice(0, 2).join("").toUpperCase()}
                </Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.userName} numberOfLines={1}>{user?.name || "Coach"}</Text>
                <Text style={styles.userEmail} numberOfLines={1}>{user?.email || ""}</Text>
              </View>
            </>
          )}
        </View>

        <ScrollView style={{ flex: 1 }} contentContainerStyle={{ paddingVertical: 8 }} showsVerticalScrollIndicator={false}>
          {NAV.map((item) => {
            if (item.adminOnly && !(user?.is_admin || (user as any)?.is_primary_coach || (user as any)?.coach_tier === "admin" || isLouis(user))) return null;
            const active = isActive(pathname, item.path);
            return (
              <Pressable
                key={item.path}
                testID={item.testId}
                onPress={() => router.push(item.path as any)}
                style={[styles.navItem, active && styles.navItemActive]}
              >
                <Ionicons
                  name={item.icon}
                  size={20}
                  color={active ? theme.color.brand : theme.color.textMuted}
                />
                <Text style={[styles.navLabel, active && styles.navLabelActive]}>{item.label}</Text>
                {active && <View style={styles.activeBar} />}
              </Pressable>
            );
          })}
        </ScrollView>

        <Pressable testID="desktop-logout" onPress={handleLogout} style={styles.logout}>
          <Ionicons name="log-out-outline" size={18} color={theme.color.textMuted} />
          <Text style={styles.logoutText}>SIGN OUT</Text>
        </Pressable>
      </View>
      <View style={styles.content}>{children}</View>
    </View>
  );
}

const SIDEBAR_WIDTH = 260;

const styles = StyleSheet.create({
  root: { flex: 1, flexDirection: "row", backgroundColor: theme.color.surface },
  sidebar: {
    width: SIDEBAR_WIDTH,
    backgroundColor: theme.color.surface2,
    borderRightWidth: 1,
    borderRightColor: theme.color.border,
    paddingVertical: 20,
  },
  brandRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 20,
    paddingBottom: 20,
    borderBottomWidth: 1,
    borderBottomColor: theme.color.border,
  },
  brand: { color: theme.color.text, fontSize: 20, fontWeight: "900", letterSpacing: 3 },
  tagline: { color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 2, marginTop: 2 },
  userBlock: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingHorizontal: 20,
    paddingVertical: 16,
    borderBottomWidth: 1,
    borderBottomColor: theme.color.border,
  },
  avatar: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: theme.color.brandTint,
    alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: theme.color.brand,
  },
  avatarText: { color: theme.color.brand, fontWeight: "900", fontSize: 15 },
  userName: { color: theme.color.text, fontWeight: "800", fontSize: 14 },
  userTitle: { color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 1.4, marginTop: 2 },
  userEmail: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },
  navItem: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingHorizontal: 20,
    paddingVertical: 12,
    marginHorizontal: 8,
    borderRadius: 8,
    position: "relative",
  },
  navItemActive: { backgroundColor: theme.color.brandTint },
  navLabel: { color: theme.color.textMuted, fontSize: 13, fontWeight: "600", letterSpacing: 0.5 },
  navLabelActive: { color: theme.color.text, fontWeight: "800" },
  activeBar: {
    position: "absolute", left: 0, top: 8, bottom: 8, width: 3,
    backgroundColor: theme.color.brand, borderRadius: 2,
  },
  logout: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 20, paddingVertical: 14,
    borderTopWidth: 1, borderTopColor: theme.color.border,
  },
  logoutText: { color: theme.color.textMuted, fontSize: 11, fontWeight: "800", letterSpacing: 1.5 },
  content: { flex: 1, backgroundColor: theme.color.surface },
});
