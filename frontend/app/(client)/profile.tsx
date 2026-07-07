import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { useAuth } from "@/src/lib/auth";
import { theme } from "@/src/lib/theme";

export default function Profile() {
  const { user, logout } = useAuth();
  const router = useRouter();
  const [prog, setProg] = useState<any[]>([]);
  const [checkins, setCheckins] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [p, c] = await Promise.all([api<any[]>("/progress"), api<any[]>("/checkins")]);
      setProg(p); setCheckins(c);
    } finally { setLoading(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const doLogout = async () => {
    await logout();
    router.replace("/(auth)/login");
  };

  const p = user?.profile || {};

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Text style={styles.title}>PROFILE</Text>
      </View>
      <ScrollView
        contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 60 }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}
      >
        <View style={styles.avatar}>
          <Text style={styles.avatarInitial}>{user?.name?.[0]?.toUpperCase()}</Text>
        </View>
        <Text style={styles.name}>{user?.name}</Text>
        <Text style={styles.email}>{user?.email}</Text>

        <View style={styles.card}>
          <Text style={styles.sectLabel}>PROFILE</Text>
          <Row label="Airline" value={p.airline || "—"} />
          <Row label="Position" value={p.position || "—"} />
          <Row label="Level" value={p.experience_level || "—"} />
          <Row label="Training days" value={String(p.training_days_per_week || "—")} />
          <Row label="Weight" value={p.weight_kg ? `${p.weight_kg} kg` : "—"} />
          <Row label="Calorie target" value={String(p.calorie_target || "—")} />
          <Row label="Protein target" value={p.protein_target ? `${p.protein_target}g` : "—"} />
        </View>

        <Pressable testID="btn-event" onPress={() => router.push("/event")} style={styles.linkRow}>
          <Ionicons name="trophy" size={18} color={theme.color.brand} />
          <Text style={styles.linkText}>EVENT TRAINING</Text>
          <Ionicons name="chevron-forward" size={16} color={theme.color.textDim} />
        </Pressable>
        <Pressable testID="btn-progress" onPress={() => router.push("/progress")} style={styles.linkRow}>
          <Ionicons name="trending-up" size={18} color={theme.color.brand} />
          <Text style={styles.linkText}>PROGRESS PHOTOS & WEIGHT</Text>
          <Text style={styles.count}>{prog.length}</Text>
        </Pressable>
        <Pressable testID="btn-checkin" onPress={() => router.push("/checkin")} style={styles.linkRow}>
          <Ionicons name="clipboard" size={18} color={theme.color.brand} />
          <Text style={styles.linkText}>WEEKLY CHECK-INS</Text>
          <Text style={styles.count}>{checkins.length}</Text>
        </Pressable>
        <Pressable testID="btn-onboarding" onPress={() => router.push("/(auth)/onboarding")} style={styles.linkRow}>
          <Ionicons name="settings" size={18} color={theme.color.brand} />
          <Text style={styles.linkText}>EDIT PROFILE</Text>
          <Ionicons name="chevron-forward" size={16} color={theme.color.textDim} />
        </Pressable>

        <View style={styles.card}>
          <Text style={styles.sectLabel}>INTEGRATIONS (COMING V2)</Text>
          {["Apple Health", "Google Health Connect", "Garmin", "Strava", "Oura"].map((i) => (
            <View key={i} style={styles.integRow}>
              <Text style={styles.integName}>{i}</Text>
              <Text style={styles.integStatus}>MANUAL</Text>
            </View>
          ))}
        </View>

        <Pressable testID="btn-logout" onPress={doLogout} style={styles.logout}>
          <Text style={styles.logoutText}>LOG OUT</Text>
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}

const Row = ({ label, value }: { label: string; value: string }) => (
  <View style={styles.row}>
    <Text style={styles.rowLabel}>{label}</Text>
    <Text style={styles.rowVal}>{value}</Text>
  </View>
);

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  title: { color: theme.color.text, fontSize: 20, letterSpacing: 2, fontWeight: "900" },
  avatar: { width: 72, height: 72, borderRadius: 36, backgroundColor: theme.color.brand, alignItems: "center", justifyContent: "center", alignSelf: "center", marginTop: theme.space.md },
  avatarInitial: { color: "#fff", fontSize: 32, fontWeight: "900" },
  name: { color: theme.color.text, textAlign: "center", fontSize: 20, fontWeight: "800", marginTop: theme.space.sm },
  email: { color: theme.color.textMuted, textAlign: "center", marginTop: 2 },
  card: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, marginTop: theme.space.lg, padding: theme.space.md },
  sectLabel: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 2, fontWeight: "800", marginBottom: theme.space.sm },
  row: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 8, borderTopWidth: 1, borderTopColor: theme.color.divider },
  rowLabel: { color: theme.color.textMuted, fontSize: 13 },
  rowVal: { color: theme.color.text, fontWeight: "700", fontSize: 13 },
  linkRow: { flexDirection: "row", alignItems: "center", gap: 12, padding: theme.space.md, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, marginTop: theme.space.sm, borderWidth: 1, borderColor: theme.color.border },
  linkText: { flex: 1, color: theme.color.text, letterSpacing: 1.5, fontWeight: "700", fontSize: 12 },
  count: { color: theme.color.brand, fontWeight: "800" },
  integRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 10, borderTopWidth: 1, borderTopColor: theme.color.divider },
  integName: { color: theme.color.text, fontSize: 13 },
  integStatus: { color: theme.color.textDim, fontSize: 10, letterSpacing: 2, fontWeight: "700" },
  logout: { marginTop: theme.space.xl, padding: theme.space.md, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.red, alignItems: "center" },
  logoutText: { color: theme.color.red, fontWeight: "800", letterSpacing: 2, fontSize: 12 },
});
