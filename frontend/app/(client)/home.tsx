import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl } from "react-native";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { useAuth } from "@/src/lib/auth";
import { theme, loadColor } from "@/src/lib/theme";

const HERO = "https://images.unsplash.com/photo-1605296867304-46d5465a13f1?crop=entropy&cs=srgb&fm=jpg&q=85";

export default function Home() {
  const { user } = useAuth();
  const router = useRouter();
  const [workouts, setWorkouts] = useState<any[]>([]);
  const [roster, setRoster] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ws, r] = await Promise.all([
        api<any[]>("/workouts/week"),
        api<any>("/roster/current"),
      ]);
      setWorkouts(ws || []);
      setRoster(r && r.id ? r : null);
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const today = new Date().toISOString().slice(0, 10);
  const todaysWorkout = workouts.find((w) => w.date === today);
  const todaysDuty = roster?.days?.find((d: any) => d.date === today);
  const load_color = loadColor(todaysWorkout?.day_load || todaysDuty?.load);

  return (
    <View style={styles.root}>
      <ScrollView
        contentContainerStyle={{ paddingBottom: 40 }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}
      >
        <View style={styles.heroWrap}>
          <Image source={HERO} style={StyleSheet.absoluteFill} contentFit="cover" />
          <LinearGradient colors={["rgba(15,15,19,0.2)", "rgba(15,15,19,0.85)", "#0F0F13"]} locations={[0, 0.6, 1]} style={StyleSheet.absoluteFill} />
          <SafeAreaView edges={["top"]}>
            <View style={styles.heroContent}>
              <Text style={styles.hello}>HELLO {user?.name?.toUpperCase().split(" ")[0]}</Text>
              <Text style={styles.date}>{new Date().toDateString().toUpperCase()}</Text>
              <View style={[styles.loadBadge, { borderColor: load_color }]} testID="today-load-badge">
                <View style={[styles.dot, { backgroundColor: load_color }]} />
                <Text style={styles.loadText}>{(todaysWorkout?.day_load || todaysDuty?.load || "green").toUpperCase()} DAY</Text>
              </View>
              <Text style={styles.hTitle}>{todaysWorkout ? todaysWorkout.title : "REST & RECOVER"}</Text>
              {todaysDuty && (
                <Text style={styles.duty}>
                  <Ionicons name="airplane" size={12} color={theme.color.brand} /> {todaysDuty.type.toUpperCase()}
                  {todaysDuty.flights?.[0] ? `  ${todaysDuty.flights[0].from} → ${todaysDuty.flights[0].to}` : ""}
                </Text>
              )}
            </View>
          </SafeAreaView>
        </View>

        {loading && !workouts.length ? (
          <ActivityIndicator color={theme.color.brand} style={{ marginTop: 40 }} />
        ) : (
          <View style={{ padding: theme.space.lg }}>
            {todaysWorkout ? (
              <Pressable
                testID="start-today-workout"
                onPress={() => router.push(`/workout/${todaysWorkout.id}`)}
                style={styles.startCta}
              >
                <Text style={styles.startText}>{`START TODAY'S WORKOUT`}</Text>
                <Ionicons name="arrow-forward" size={20} color="#fff" />
              </Pressable>
            ) : (
              <View style={styles.emptyBox}>
                <Text style={styles.emptyTitle}>No workout scheduled for today</Text>
                <Text style={styles.emptySub}>Upload your roster to get an AI-generated plan.</Text>
                <Pressable
                  testID="upload-roster-cta"
                  onPress={() => router.push("/roster-upload")}
                  style={styles.uploadBtn}
                >
                  <Text style={styles.startText}>UPLOAD ROSTER</Text>
                </Pressable>
              </View>
            )}

            <Text style={styles.sectionTitle}>THIS WEEK</Text>
            {workouts.length === 0 ? (
              <Text style={styles.emptySub}>No plan yet.</Text>
            ) : (
              workouts.map((w) => (
                <Pressable
                  key={w.id}
                  onPress={() => router.push(`/workout/${w.id}`)}
                  style={styles.wRow}
                  testID={`week-workout-${w.id}`}
                >
                  <View style={[styles.loadBar, { backgroundColor: loadColor(w.day_load) }]} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.wDate}>{w.date}</Text>
                    <Text style={styles.wTitle}>{w.title}</Text>
                    <Text style={styles.wMeta}>{w.duration_min}min · {w.exercises?.length || 0} exercises</Text>
                  </View>
                  {w.completed && <Ionicons name="checkmark-circle" size={22} color={theme.color.green} />}
                  {!w.approved && !w.completed && <Text style={styles.pendPill}>PENDING</Text>}
                </Pressable>
              ))
            )}

            <Pressable style={styles.rosterBtn} onPress={() => router.push("/roster-upload")} testID="reupload-roster">
              <Ionicons name="cloud-upload" color={theme.color.brand} size={18} />
              <Text style={styles.rosterBtnText}>UPLOAD NEW ROSTER</Text>
            </Pressable>
            <Pressable style={styles.rosterBtn} onPress={() => router.push("/checkin")} testID="weekly-checkin-btn">
              <Ionicons name="clipboard" color={theme.color.brand} size={18} />
              <Text style={styles.rosterBtnText}>WEEKLY CHECK-IN</Text>
            </Pressable>
            <Pressable style={styles.rosterBtn} onPress={() => router.push("/progress")} testID="progress-btn">
              <Ionicons name="trending-up" color={theme.color.brand} size={18} />
              <Text style={styles.rosterBtnText}>LOG PROGRESS</Text>
            </Pressable>
          </View>
        )}
      </ScrollView>
    </View>
  );
}
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  heroWrap: { height: 320, backgroundColor: theme.color.surface2 },
  heroContent: { padding: theme.space.lg, marginTop: theme.space.md },
  hello: { color: theme.color.brand, letterSpacing: 3, fontSize: 11, fontWeight: "800" },
  date: { color: theme.color.textMuted, marginTop: 4, letterSpacing: 2, fontSize: 11 },
  loadBadge: { flexDirection: "row", alignItems: "center", marginTop: theme.space.md, paddingHorizontal: 10, paddingVertical: 6, borderRadius: theme.radius.pill, borderWidth: 1, alignSelf: "flex-start", backgroundColor: "rgba(0,0,0,0.35)" },
  dot: { width: 8, height: 8, borderRadius: 4, marginRight: 6 },
  loadText: { color: theme.color.text, fontSize: 10, letterSpacing: 2, fontWeight: "800" },
  hTitle: { color: theme.color.text, marginTop: theme.space.md, fontSize: 34, fontWeight: "900", letterSpacing: -0.5 },
  duty: { color: theme.color.textMuted, marginTop: theme.space.sm, fontSize: 12, letterSpacing: 1 },
  startCta: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", backgroundColor: theme.color.brand, paddingVertical: 18, paddingHorizontal: theme.space.lg, borderRadius: theme.radius.md, marginBottom: theme.space.lg },
  startText: { color: "#fff", fontWeight: "800", letterSpacing: 2, fontSize: 13 },
  emptyBox: { padding: theme.space.lg, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface2, marginBottom: theme.space.lg },
  emptyTitle: { color: theme.color.text, fontWeight: "700", fontSize: 15 },
  emptySub: { color: theme.color.textMuted, marginTop: 6, fontSize: 13 },
  uploadBtn: { backgroundColor: theme.color.brand, paddingVertical: 14, paddingHorizontal: theme.space.lg, borderRadius: theme.radius.md, alignSelf: "flex-start", marginTop: theme.space.md },
  sectionTitle: { color: theme.color.textMuted, letterSpacing: 2, fontSize: 11, fontWeight: "800", marginTop: theme.space.md, marginBottom: theme.space.sm },
  wRow: { flexDirection: "row", alignItems: "center", backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, marginBottom: theme.space.sm, overflow: "hidden", borderWidth: 1, borderColor: theme.color.border },
  loadBar: { width: 4, alignSelf: "stretch" },
  wDate: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 2, padding: theme.space.md, paddingBottom: 0, fontWeight: "700" },
  wTitle: { color: theme.color.text, fontSize: 15, fontWeight: "700", paddingHorizontal: theme.space.md, marginTop: 2 },
  wMeta: { color: theme.color.textDim, fontSize: 12, padding: theme.space.md, paddingTop: 2 },
  pendPill: { color: theme.color.amber, fontSize: 9, letterSpacing: 1.5, marginRight: theme.space.md, fontWeight: "800", backgroundColor: "rgba(245,158,11,0.15)", paddingHorizontal: 8, paddingVertical: 4, borderRadius: theme.radius.sm },
  rosterBtn: { flexDirection: "row", alignItems: "center", gap: theme.space.sm, paddingVertical: 14, paddingHorizontal: theme.space.md, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, marginTop: theme.space.sm, borderWidth: 1, borderColor: theme.color.border },
  rosterBtnText: { color: theme.color.text, letterSpacing: 1.5, fontWeight: "700", fontSize: 12 },
});
