import { View, Text, StyleSheet, Pressable, ScrollView, Alert } from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useAuth } from "@/src/lib/auth";
import { theme } from "@/src/lib/theme";

export default function CoachProfile() {
  const { user, logout } = useAuth();
  const router = useRouter();
  const doLogout = async () => { await logout(); router.replace("/(auth)/login"); };
  const confirmLogout = () => {
    Alert.alert(
      "Log out?",
      "Are you sure you want to log out?",
      [
        { text: "Cancel", style: "cancel" },
        { text: "Log Out", style: "destructive", onPress: doLogout },
      ],
    );
  };
  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}><Text style={styles.title}>COACH PROFILE</Text></View>
      <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 60 }}>
        <View style={styles.avatar}><Text style={styles.avatarText}>{user?.name?.[0]?.toUpperCase()}</Text></View>
        <Text style={styles.name}>{user?.name}</Text>
        <Text style={styles.email}>{user?.email}</Text>
        <View style={styles.roleBadge}><Ionicons name="shield-checkmark" size={12} color={theme.color.brand} /><Text style={styles.roleText}>HEAD COACH</Text></View>

        <View style={styles.card}>
          <Text style={styles.sectLabel}>ABOUT</Text>
          <Text style={styles.bio}>{user?.profile?.bio || "Aviation fitness specialist. Building programs that survive layovers, time zones, and 4am wake-ups."}</Text>
        </View>

        <Pressable testID="coach-logout" onPress={confirmLogout} style={styles.logout}>
          <Text style={styles.logoutText}>LOG OUT</Text>
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  title: { color: theme.color.text, fontSize: 20, letterSpacing: 2, fontWeight: "900" },
  avatar: { width: 80, height: 80, borderRadius: 40, backgroundColor: theme.color.brand, alignItems: "center", justifyContent: "center", alignSelf: "center", marginTop: theme.space.md },
  avatarText: { color: "#fff", fontSize: 36, fontWeight: "900" },
  name: { color: theme.color.text, textAlign: "center", fontSize: 22, fontWeight: "800", marginTop: theme.space.sm },
  email: { color: theme.color.textMuted, textAlign: "center", marginTop: 2 },
  roleBadge: { flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "center", marginTop: theme.space.sm, paddingHorizontal: 10, paddingVertical: 4, backgroundColor: theme.color.brandTint, borderRadius: theme.radius.pill },
  roleText: { color: theme.color.brand, fontWeight: "800", letterSpacing: 1.5, fontSize: 10 },
  card: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, padding: theme.space.md, marginTop: theme.space.lg },
  sectLabel: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 2, fontWeight: "800" },
  bio: { color: theme.color.text, marginTop: 8, fontSize: 14, lineHeight: 20 },
  logout: { marginTop: theme.space.xl, padding: theme.space.md, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.red, alignItems: "center" },
  logoutText: { color: theme.color.red, fontWeight: "800", letterSpacing: 2, fontSize: 12 },
});
