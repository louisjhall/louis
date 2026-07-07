import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl, Modal } from "react-native";
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
  const [event, setEvent] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [happenedOpen, setHappenedOpen] = useState(false);
  const [happenedSaving, setHappenedSaving] = useState(false);
  const [scheduleMode, setScheduleMode] = useState<string>("normal");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ws, r, ev] = await Promise.all([
        api<any[]>("/workouts/week"),
        api<any>("/roster/current"),
        api<any>("/events/current"),
      ]);
      setWorkouts(ws || []);
      setRoster(r && r.id ? r : null);
      setEvent(ev && ev.id ? ev : null);
      setScheduleMode(user?.profile?.schedule_mode || "normal");
    } finally { setLoading(false); }
  }, [user]);

  const submitHappened = async (tag: string) => {
    setHappenedSaving(true);
    try {
      await api("/schedule/daily-happened", { method: "POST", body: { tag } });
      if (["flight_delayed", "called_from_standby", "slept_badly", "less_time", "hotel_changed"].includes(tag)) {
        // Trigger smart replan for tomorrow
        const tomorrow = new Date(); tomorrow.setDate(tomorrow.getDate() + 1);
        api("/schedule/smart-replan", { method: "POST", body: { reason: `Daily pulse: ${tag}`, dates: [tomorrow.toISOString().slice(0, 10)], scope: "affected" } }).catch(() => {});
      }
      setHappenedOpen(false);
    } finally { setHappenedSaving(false); }
  };

  const toggleStandby = async () => {
    const active = scheduleMode !== "standby";
    const r = await api<any>("/schedule/standby", { method: "POST", body: { active } });
    setScheduleMode(r.schedule_mode);
  };
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const today = new Date().toISOString().slice(0, 10);
  const todaysWorkout = workouts.find((w) => w.date === today);
  const todaysDay = roster?.days?.find((d: any) => d.date === today);
  const load_color = loadColor(todaysWorkout?.day_load || todaysDay?.load);

  const expiry = roster?.expiry;
  const rDays = expiry?.days_remaining;
  const showBanner = expiry && (expiry.expired || (rDays !== null && rDays !== undefined && rDays <= 7));
  const bannerColor = expiry?.expired ? theme.color.red : rDays !== undefined && rDays <= 3 ? theme.color.red : theme.color.amber;

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
                <Text style={styles.loadText}>{(todaysWorkout?.day_load || todaysDay?.load || "green").toUpperCase()} DAY</Text>
              </View>
              <Text style={styles.hTitle}>{todaysWorkout ? todaysWorkout.title : "REST & RECOVER"}</Text>
              {todaysDay && (
                <Text style={styles.duty}>
                  <Ionicons name="airplane" size={12} color={theme.color.brand} />  {(todaysDay.day_type || todaysDay.type || "").toUpperCase()}
                  {todaysDay.layover_city ? `  ${String(todaysDay.layover_city).toUpperCase()}` : ""}
                  {todaysDay.flights?.[0] ? `  ${todaysDay.flights[0].from} → ${todaysDay.flights[0].to}` : ""}
                </Text>
              )}
            </View>
          </SafeAreaView>
        </View>

        <View style={{ padding: theme.space.lg }}>
          {showBanner && (
            <Pressable testID="roster-banner" onPress={() => router.push("/roster-upload")} style={[styles.banner, { borderLeftColor: bannerColor }]}>
              <Ionicons name={expiry.expired ? "warning" : "time"} size={18} color={bannerColor} />
              <View style={{ flex: 1, marginLeft: 10 }}>
                <Text style={styles.bannerTitle}>{expiry.expired ? "ROSTER EXPIRED" : `${rDays} DAY${rDays === 1 ? "" : "S"} REMAINING`}</Text>
                <Text style={styles.bannerSub}>
                  {expiry.expired ? "Upload your latest roster to keep training." : "Upload your next roster now to avoid interruption."}
                </Text>
              </View>
              <Text style={styles.bannerAction}>UPLOAD →</Text>
            </Pressable>
          )}

          {roster && !showBanner && (
            <View style={styles.rosterCard} testID="roster-remaining-card">
              <View style={{ flex: 1 }}>
                <Text style={styles.rTop}>ROSTER · {roster.start_date} → {roster.end_date}</Text>
                <Text style={styles.rBig}>{rDays}</Text>
                <Text style={styles.rBigLabel}>DAYS REMAINING · {String(expiry?.coverage || "").toUpperCase()} COVERAGE</Text>
              </View>
              <Pressable onPress={() => router.push("/roster-upload")} style={styles.rBtn} testID="roster-card-upload">
                <Ionicons name="cloud-upload" size={16} color={theme.color.brand} />
                <Text style={styles.rBtnText}>NEW</Text>
              </Pressable>
            </View>
          )}

          {event ? (
            <Pressable testID="event-card" onPress={() => router.push("/event")} style={styles.eventCard}>
              <View style={{ flex: 1 }}>
                <Text style={styles.eTop}>{String(event.event_type || "").toUpperCase()} · {String(event.phase_info?.phase || "").toUpperCase().replace("_", " ")}</Text>
                <Text style={styles.eName}>{event.event_name}</Text>
                <Text style={styles.eDate}>{event.event_date}{event.target_time ? ` · target ${event.target_time}` : ""}</Text>
              </View>
              <View style={{ alignItems: "flex-end" }}>
                <Text style={styles.eBig}>{event.phase_info?.days_to_race ?? "—"}</Text>
                <Text style={styles.eBigLbl}>DAYS TO RACE</Text>
              </View>
            </Pressable>
          ) : (
            <Pressable testID="add-event-card" onPress={() => router.push("/event")} style={styles.addEventBtn}>
              <Ionicons name="trophy" size={16} color={theme.color.brand} />
              <Text style={styles.addEventText}>ADD EVENT (5K, marathon, tri, HYROX…)</Text>
            </Pressable>
          )}

          {todaysWorkout ? (
            <Pressable testID="start-today-workout" onPress={() => router.push(`/workout/${todaysWorkout.id}`)} style={styles.startCta}>
              <Text style={styles.startText}>{`START TODAY'S WORKOUT`}</Text>
              <Ionicons name="arrow-forward" size={20} color="#fff" />
            </Pressable>
          ) : (
            <View style={styles.emptyBox}>
              <Text style={styles.emptyTitle}>No workout scheduled for today</Text>
              <Text style={styles.emptySub}>Upload your roster to get an AI-generated plan.</Text>
              <Pressable testID="upload-roster-cta" onPress={() => router.push("/roster-upload")} style={styles.uploadBtn}>
                <Text style={styles.startText}>UPLOAD ROSTER</Text>
              </Pressable>
            </View>
          )}

          <View style={styles.quickRow}>
            <QuickBtn icon="calendar" label="MONTHLY" onPress={() => router.push("/(client)/calendar")} testID="qs-month" />
            <QuickBtn icon="clipboard" label="CHECK-IN" onPress={() => router.push("/checkin")} testID="qs-checkin" />
            <QuickBtn icon="trending-up" label="PROGRESS" onPress={() => router.push("/progress")} testID="qs-progress" />
          </View>

          <Text style={styles.sectionTitle}>NEXT 7 DAYS</Text>
          {loading && !workouts.length ? (
            <ActivityIndicator color={theme.color.brand} />
          ) : workouts.length === 0 ? (
            <Text style={styles.emptySub}>No plan yet. Upload roster + generate.</Text>
          ) : (
            workouts.slice(0, 7).map((w) => (
              <Pressable key={w.id} onPress={() => router.push(`/workout/${w.id}`)} style={styles.wRow} testID={`week-workout-${w.id}`}>
                <View style={[styles.loadBar, { backgroundColor: loadColor(w.day_load) }]} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.wDate}>{w.date}</Text>
                  <Text style={styles.wTitle}>{w.title}</Text>
                  <Text style={styles.wMeta}>{w.location || "Home Workout"} · {w.duration_min}min</Text>
                </View>
                {w.completed && <Ionicons name="checkmark-circle" size={22} color={theme.color.green} style={{ marginRight: 10 }} />}
                {w.coach_locked && <Ionicons name="lock-closed" size={16} color={theme.color.amber} style={{ marginRight: 10 }} />}
                {!w.approved && !w.completed && <Text style={styles.pendPill}>PENDING</Text>}
              </Pressable>
            ))
          )}
        </View>
      </ScrollView>

      <Modal visible={happenedOpen} animationType="slide" transparent>
        <Pressable onPress={() => setHappenedOpen(false)} style={styles.modalBg}>
          <Pressable style={styles.sheet} onPress={(e) => e.stopPropagation()}>
            <View style={styles.sheetHandle} />
            <Text style={styles.sheetTitle}>DID TODAY GO TO PLAN?</Text>
            <Text style={styles.sheetSub}>We'll adjust tomorrow's plan based on your answer.</Text>
            {[
              ["yes_as_planned", "✅ Yes, exactly as planned"],
              ["workout_completed", "💪 Workout completed"],
              ["flight_delayed", "✈️ Flight delayed"],
              ["called_from_standby", "✈️ Called from standby"],
              ["slept_badly", "😴 Slept badly"],
              ["ill", "🤒 I'm ill"],
              ["family_plans", "👨‍👩‍👧 Family plans changed"],
              ["hotel_changed", "🏨 Hotel changed"],
              ["workout_missed", "❌ Workout missed"],
              ["less_time", "⏳ Had less time than expected"],
              ["other", "✍️ Something else"],
            ].map(([tag, label]) => (
              <Pressable
                key={tag}
                testID={`happened-${tag}`}
                onPress={() => submitHappened(tag)}
                disabled={happenedSaving}
                style={styles.sheetRow}
              >
                <Text style={styles.sheetRowText}>{label}</Text>
              </Pressable>
            ))}
          </Pressable>
        </Pressable>
      </Modal>
    </View>
  );
}

function QuickBtn({ icon, label, onPress, testID }: any) {
  return (
    <Pressable onPress={onPress} testID={testID} style={styles.qBtn}>
      <Ionicons name={icon} size={18} color={theme.color.brand} />
      <Text style={styles.qBtnText}>{label}</Text>
    </Pressable>
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
  hTitle: { color: theme.color.text, marginTop: theme.space.md, fontSize: 32, fontWeight: "900", letterSpacing: -0.5 },
  duty: { color: theme.color.textMuted, marginTop: theme.space.sm, fontSize: 12, letterSpacing: 1 },
  banner: { flexDirection: "row", alignItems: "center", padding: theme.space.md, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderLeftWidth: 3, marginBottom: theme.space.md },
  bannerTitle: { color: theme.color.text, fontSize: 12, letterSpacing: 1.5, fontWeight: "800" },
  bannerSub: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },
  bannerAction: { color: theme.color.brand, letterSpacing: 2, fontWeight: "800", fontSize: 11 },
  rosterCard: { flexDirection: "row", alignItems: "center", padding: theme.space.md, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, marginBottom: theme.space.md },
  rTop: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 1.5, fontWeight: "700" },
  rBig: { color: theme.color.text, fontSize: 36, fontWeight: "900", marginTop: 2 },
  rBigLabel: { color: theme.color.brand, fontSize: 10, letterSpacing: 1.5, fontWeight: "800" },
  rBtn: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: theme.color.surface3, borderRadius: theme.radius.pill, paddingHorizontal: 12, paddingVertical: 8, borderWidth: 1, borderColor: theme.color.border },
  rBtnText: { color: theme.color.brand, fontSize: 10, letterSpacing: 1.5, fontWeight: "800" },
  eventCard: { flexDirection: "row", alignItems: "center", padding: theme.space.md, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.brand, marginBottom: theme.space.md },
  eTop: { color: theme.color.brand, fontSize: 10, letterSpacing: 1.5, fontWeight: "800" },
  eName: { color: theme.color.text, fontSize: 15, fontWeight: "800", marginTop: 4 },
  eDate: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },
  eBig: { color: theme.color.text, fontSize: 28, fontWeight: "900" },
  eBigLbl: { color: theme.color.textMuted, fontSize: 9, letterSpacing: 1.5, fontWeight: "800" },
  addEventBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, padding: 14, borderRadius: theme.radius.md, borderStyle: "dashed", borderWidth: 1, borderColor: theme.color.brand, marginBottom: theme.space.md },
  addEventText: { color: theme.color.brand, fontWeight: "800", letterSpacing: 1.5, fontSize: 11 },
  startCta: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", backgroundColor: theme.color.brand, paddingVertical: 18, paddingHorizontal: theme.space.lg, borderRadius: theme.radius.md },
  startText: { color: "#fff", fontWeight: "800", letterSpacing: 2, fontSize: 13 },
  emptyBox: { padding: theme.space.lg, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface2 },
  emptyTitle: { color: theme.color.text, fontWeight: "700", fontSize: 15 },
  emptySub: { color: theme.color.textMuted, marginTop: 6, fontSize: 13 },
  uploadBtn: { backgroundColor: theme.color.brand, paddingVertical: 14, paddingHorizontal: theme.space.lg, borderRadius: theme.radius.md, alignSelf: "flex-start", marginTop: theme.space.md },
  quickRow: { flexDirection: "row", gap: theme.space.sm, marginTop: theme.space.md },
  qBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, paddingVertical: 12 },
  qBtnText: { color: theme.color.text, letterSpacing: 1.5, fontWeight: "700", fontSize: 10 },
  sectionTitle: { color: theme.color.textMuted, letterSpacing: 2, fontSize: 11, fontWeight: "800", marginTop: theme.space.lg, marginBottom: theme.space.sm },
  wRow: { flexDirection: "row", alignItems: "center", backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, marginBottom: theme.space.sm, overflow: "hidden", borderWidth: 1, borderColor: theme.color.border },
  loadBar: { width: 4, alignSelf: "stretch" },
  wDate: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 2, padding: theme.space.md, paddingBottom: 0, fontWeight: "700" },
  wTitle: { color: theme.color.text, fontSize: 15, fontWeight: "700", paddingHorizontal: theme.space.md, marginTop: 2 },
  wMeta: { color: theme.color.textDim, fontSize: 12, padding: theme.space.md, paddingTop: 2 },
  pendPill: { color: theme.color.amber, fontSize: 9, letterSpacing: 1.5, marginRight: theme.space.md, fontWeight: "800", backgroundColor: "rgba(245,158,11,0.15)", paddingHorizontal: 8, paddingVertical: 4, borderRadius: theme.radius.sm },
  pulseCard: { flexDirection: "row", alignItems: "center", padding: theme.space.md, backgroundColor: theme.color.brandTint, borderRadius: theme.radius.md, borderLeftWidth: 3, borderLeftColor: theme.color.brand, marginTop: theme.space.md },
  pulseTitle: { color: theme.color.text, fontSize: 12, letterSpacing: 1.5, fontWeight: "800" },
  pulseSub: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },
  modeRow: { flexDirection: "row", gap: 6, marginTop: theme.space.md, flexWrap: "wrap" },
  modeChip: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: theme.radius.pill, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, flexShrink: 0 },
  modeChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  modeText: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 1.5, fontWeight: "800" },
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  sheet: { backgroundColor: theme.color.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: theme.space.lg, paddingBottom: theme.space.xl, gap: 4 },
  sheetHandle: { alignSelf: "center", width: 40, height: 4, backgroundColor: theme.color.borderStrong, borderRadius: 2, marginBottom: theme.space.md },
  sheetTitle: { color: theme.color.text, fontSize: 16, letterSpacing: 1.5, fontWeight: "900" },
  sheetSub: { color: theme.color.textMuted, fontSize: 12, marginBottom: theme.space.md },
  sheetRow: { padding: theme.space.md, borderRadius: theme.radius.md, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, marginBottom: 6 },
  sheetRowText: { color: theme.color.text, fontSize: 14 },
});
