import { useCallback, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl, Modal } from "react-native";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { useAuth } from "@/src/lib/auth";
import { theme, loadColor } from "@/src/lib/theme";
import { CrewFitWings } from "@/src/components/Logo";
import { ClientProfileHeader } from "@/src/components/ClientProfileHeader";
import { AIHeroImage } from "@/src/components/AIHeroImage";
import { RealityModal } from "@/src/components/RealityModal";
import { WeeklyCheckinCard } from "@/src/components/WeeklyCheckinCard";
import { TimeZoneConfirmModal } from "@/src/components/TimeZoneConfirmModal";
import { HabitTodayCard } from "@/src/components/HabitTodayCard";
import { NotificationBell } from "@/src/components/NotificationBell";
import { PushPermissionPrompt } from "@/src/components/PushPermissionPrompt";
import { StandbyStatusCard } from "@/src/components/StandbyStatusCard";
import { TodayPersonalActivities } from "@/src/components/PersonalActivityCard";
import { AddActivityModal } from "@/src/components/AddActivityModal";

function iconFor(kind: string): keyof typeof Ionicons.glyphMap {
  switch (kind) {
    case "roster_uploaded": return "calendar";
    case "injury_flagged": return "medkit";
    case "annual_leave": return "sunny";
    case "missed_workouts": return "alarm";
    case "event_completed": return "flag";
    case "life_change": return "swap-horizontal";
    default: return "pulse";
  }
}

function titleFor(kind: string): string {
  switch (kind) {
    case "roster_uploaded": return "NEW ROSTER · REFRESH YOUR DNA";
    case "injury_flagged": return "INJURY FLAGGED · RE-PLAN NEEDED";
    case "annual_leave": return "ANNUAL LEAVE · SWITCH BLOCK?";
    case "missed_workouts": return "MISSED SESSIONS · REVIEW";
    case "event_completed": return "EVENT COMPLETE · WHAT'S NEXT?";
    case "life_change": return "LIFE CHANGE · REFRESH DNA";
    default: return "CREWFIT INTELLIGENCE";
  }
}

const HERO = "https://images.unsplash.com/photo-1605296867304-46d5465a13f1?crop=entropy&cs=srgb&fm=jpg&q=85";

function localDateStr(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function todayPlusOne(todayIso: string): string {
  try {
    const d = new Date(`${todayIso}T00:00:00`);
    d.setDate(d.getDate() + 1);
    return localDateStr(d);
  } catch {
    return todayIso;
  }
}

function dayLabel(dateStr: string, todayStr: string, tomorrowStr: string): { primary: string; secondary?: string } {
  // Format like "Wed 1 Jul" (or "Wed 1 Jul 2027" if not current year).
  // Uses en-GB to guarantee day-before-month ordering regardless of the device locale,
  // so pilots/cabin crew on US phones don't see ambiguous 01/07/2026.
  let short = dateStr;
  try {
    const d = new Date(`${dateStr}T00:00:00`);
    const weekday = d.toLocaleDateString("en-GB", { weekday: "short" }); // Wed
    const day = d.getDate();
    const month = d.toLocaleDateString("en-GB", { month: "short" }); // Jul
    const now = new Date();
    const includeYear = d.getFullYear() !== now.getFullYear();
    short = includeYear ? `${weekday} ${day} ${month} ${d.getFullYear()}` : `${weekday} ${day} ${month}`;
  } catch {
    /* keep raw dateStr */
  }
  if (dateStr === todayStr) return { primary: "Today", secondary: short };
  if (dateStr === tomorrowStr) return { primary: "Tomorrow", secondary: short };
  return { primary: short };
}

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
  const [realityOpen, setRealityOpen] = useState(false);
  const [prompts, setPrompts] = useState<any[]>([]);
  const [standbyToday, setStandbyToday] = useState<any>(null);
  const [addActivityOpen, setAddActivityOpen] = useState(false);
  const [activityRefreshKey, setActivityRefreshKey] = useState(0);
  const [setupDay, setSetupDay] = useState<{ is_setup_day: boolean; first_workout_date?: string | null; reason?: string | null } | null>(null);
  const [rosterJob, setRosterJob] = useState<{ id: string; status?: string; stage?: string; progress?: number; message?: string; error?: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ws, r, ev, pr, sb, sd, rj] = await Promise.all([
        api<any[]>("/workouts/week"),
        api<any>("/roster/current"),
        api<any>("/events/current"),
        api<any>("/reassessment/prompts").catch(() => ({ prompts: [] })),
        api<any>("/standby/today").catch(() => null),
        api<any>("/setup-day/status").catch(() => null),
        api<any>("/roster/jobs/active").catch(() => null),
      ]);
      setWorkouts(ws || []);
      setRoster(r && r.id ? r : null);
      setEvent(ev && ev.id ? ev : null);
      setPrompts(pr.prompts || []);
      setScheduleMode(user?.profile?.schedule_mode || "normal");
      setStandbyToday(sb);
      setSetupDay(sd);
      setRosterJob(rj && rj.id ? rj : null);
    } finally { setLoading(false); }
  }, [user]);

  const dismissPrompt = async (p: any) => {
    setPrompts((s) => s.filter((x) => x.id !== p.id));
    try { await api("/reassessment/dismiss", { method: "POST", body: { prompt_id: p.id } }); } catch { /* ignore */ }
  };

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

  const today = localDateStr(new Date());
  const todaysWorkout = workouts.find((w) => w.date === today);
  const todaysDay = roster?.days?.find((d: any) => d.date === today);
  const load_color = loadColor(todaysWorkout?.day_load || todaysDay?.load);

  const next7 = useMemo(() => {
    const byDate = new Map<string, any>();
    (workouts || []).forEach((w: any) => { if (w?.date) byDate.set(w.date, w); });
    const rosterByDate = new Map<string, any>();
    (roster?.days || []).forEach((d: any) => { if (d?.date) rosterByDate.set(d.date, d); });
    const base = new Date();
    base.setHours(0, 0, 0, 0);
    const out: any[] = [];
    for (let i = 0; i < 7; i++) {
      const d = new Date(base);
      d.setDate(base.getDate() + i);
      const key = localDateStr(d);
      const w = byDate.get(key);
      if (w) {
        out.push({ ...w, __key: key, __rest: false });
      } else {
        const rd = rosterByDate.get(key);
        const isFlight = rd?.day_type === "flight" || (rd?.flights?.length || 0) > 0;
        out.push({
          __key: key,
          __rest: true,
          id: `rest-${key}`,
          date: key,
          title: isFlight ? "FLIGHT · RECOVERY" : "REST DAY",
          location: rd?.layover_city || null,
          duration_min: 0,
          day_load: rd?.load || "grey",
          day_type: rd?.day_type || "rest",
        });
      }
    }
    return out;
  }, [workouts, roster]);

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
        <AIHeroImage
          ctx={{
            role: user?.profile?.job_title?.toLowerCase().includes("crew") ? "cabin_crew" : "pilot",
            gender: user?.profile?.preferred_visual_gender || undefined,
            workout_type: todaysWorkout?.focus?.toLowerCase() || undefined,
            context: standbyToday?.is_standby ? "standby" : undefined,
            day_type: todaysDay?.day_type || undefined,
          }}
          style={styles.heroWrap}
        >
          <SafeAreaView edges={["top"]}>
            <View style={styles.heroContent}>
              <View style={styles.topBar}>
                <CrewFitWings size={40} />
                <NotificationBell testID="client-notif-bell" />
              </View>

              <ClientProfileHeader
                user={user as any}
                todayLoad={todaysWorkout?.day_load || todaysDay?.load || "grey"}
                dayType={todaysDay?.day_type || todaysDay?.type || null}
                dayTitle={todaysWorkout ? todaysWorkout.title : "REST & RECOVER"}
                isStandby={!!standbyToday?.is_standby}
              />

              {todaysDay?.layover_city || todaysDay?.flights?.[0] ? (
                <Text style={styles.duty}>
                  {todaysDay?.layover_city ? `${String(todaysDay.layover_city).toUpperCase()}` : ""}
                  {todaysDay?.flights?.[0] ? `  ${todaysDay.flights[0].from} → ${todaysDay.flights[0].to}` : ""}
                </Text>
              ) : null}
            </View>
          </SafeAreaView>
        </AIHeroImage>

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
            <Pressable testID="event-card" onPress={() => router.push("/event")}>
              <AIHeroImage
                ctx={{ context: "event", goal: (event.event_type || "").toLowerCase(), phase: event.phase_info?.phase || "peak" }}
                style={styles.eventCardWrap}
                gradient
              >
                <View style={styles.eventCardInner}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.eTop}>{(event.category_label || String(event.event_type || "")).toUpperCase()}{event.category === "race" && event.phase_info?.phase ? ` · ${String(event.phase_info.phase).toUpperCase().replace("_", " ")}` : ""}</Text>
                    <Text style={styles.eName}>{event.event_name}</Text>
                    <Text style={styles.eDate}>{event.event_date}{event.target_time ? ` · target ${event.target_time}` : ""}</Text>
                  </View>
                  <View style={{ alignItems: "flex-end" }}>
                    <Text style={styles.eBig}>{(event.days_value ?? event.phase_info?.days_to_race) ?? "—"}</Text>
                    <Text style={styles.eBigLbl}>{(event.days_label || "days to event").toUpperCase()}</Text>
                  </View>
                </View>
              </AIHeroImage>
            </Pressable>
          ) : (
            <Pressable testID="add-event-card" onPress={() => router.push("/event")} style={styles.addEventBtn}>
              <Ionicons name="trophy" size={16} color={theme.color.brand} />
              <Text style={styles.addEventText}>ADD EVENT (5K, marathon, tri, HYROX…)</Text>
            </Pressable>
          )}

          {todaysWorkout ? (
            <>
              {prompts.length > 0 && (
                <View style={styles.promptWrap}>
                  {prompts.slice(0, 3).map((p) => (
                    <View key={p.id} style={styles.promptCard}>
                      <View style={styles.promptLeft}>
                        <View style={styles.promptIconWrap}>
                          <Ionicons name={iconFor(p.kind)} size={20} color={theme.color.brand} />
                        </View>
                        <View style={{ flex: 1 }}>
                          <Text style={styles.promptTitle}>{titleFor(p.kind)}</Text>
                          <Text style={styles.promptReason} numberOfLines={3}>{p.reason}</Text>
                          <View style={styles.promptCtaRow}>
                            <Pressable
                              testID={`prompt-take-${p.id}`}
                              onPress={() => router.push("/assessment" as any)}
                              style={styles.promptTakeBtn}
                            >
                              <Text style={styles.promptTakeText}>UPDATE DNA</Text>
                              <Ionicons name="arrow-forward" size={11} color={theme.color.brand} />
                            </Pressable>
                            <Pressable testID={`prompt-dismiss-${p.id}`} onPress={() => dismissPrompt(p)} style={styles.promptDismissBtn}>
                              <Text style={styles.promptDismissText}>NOT NOW</Text>
                            </Pressable>
                          </View>
                        </View>
                      </View>
                    </View>
                  ))}
                </View>
              )}
              <Pressable
                testID="reality-btn-home"
                onPress={() => setRealityOpen(true)}
                style={styles.realityBtn}
              >
                <View style={styles.realityBtnLeft}>
                  <View style={styles.realityIconWrap}>
                    <Ionicons name="compass" size={20} color={theme.color.brand} />
                  </View>
                  <View>
                    <Text style={styles.realityTitle}>TODAY&apos;S REALITY</Text>
                    <Text style={styles.realitySub}>Tell CrewFit what has changed</Text>
                  </View>
                </View>
                <Ionicons name="arrow-forward" size={16} color={theme.color.brand} />
              </Pressable>
              <Pressable testID="start-today-workout" onPress={() => router.push(`/workout/${todaysWorkout.id}`)} style={styles.startCta}>
                <Text style={styles.startText}>{`START TODAY'S WORKOUT`}</Text>
                <Ionicons name="arrow-forward" size={20} color="#fff" />
              </Pressable>
            </>
          ) : setupDay?.is_setup_day ? (
            <View style={styles.setupCard} testID="setup-day-card">
              <View style={styles.setupIconWrap}>
                <Ionicons name="rocket" size={22} color={theme.color.brand} />
              </View>
              <Text style={styles.setupTitle}>YOUR CREWFIT SETUP DAY</Text>
              <Text style={styles.setupBody}>
                Today is about setting up your profile, uploading your roster and getting familiar with CrewFit. Your first workout starts {setupDay?.first_workout_date && setupDay.first_workout_date !== todayPlusOne(today) ? `on ${setupDay.first_workout_date}` : "tomorrow"}.
              </Text>
              {setupDay?.reason ? (
                <Text style={styles.setupReason}>Note: {setupDay.reason}.</Text>
              ) : null}
              <View style={styles.setupActionsRow}>
                <Pressable testID="setup-upload-roster" onPress={() => router.push("/roster-upload")} style={styles.setupBtnPrimary}>
                  <Ionicons name="cloud-upload" size={14} color="#fff" />
                  <Text style={styles.setupBtnPrimaryT}>UPLOAD ROSTER</Text>
                </Pressable>
                <Pressable testID="setup-message-louis" onPress={() => router.push("/(client)/messages")} style={styles.setupBtnSecondary}>
                  <Ionicons name="chatbubble-ellipses" size={14} color={theme.color.brand} />
                  <Text style={styles.setupBtnSecondaryT}>MESSAGE LOUIS</Text>
                </Pressable>
              </View>
              <Pressable testID="setup-review-plan" onPress={() => router.push("/(client)/calendar")} style={styles.setupBtnGhost}>
                <Ionicons name="calendar" size={13} color={theme.color.brand} />
                <Text style={styles.setupBtnGhostT}>REVIEW YOUR PLAN</Text>
              </Pressable>
            </View>
          ) : (
            <View style={styles.emptyBox}>
              <Text style={styles.emptyTitle}>No workout scheduled for today</Text>
              <Text style={styles.emptySub}>Upload your roster so CrewFit can build your personalised training plan.</Text>
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

          <HabitTodayCard />

          <TodayPersonalActivities key={activityRefreshKey} />

          <Pressable
            testID="home-add-activity"
            onPress={() => setAddActivityOpen(true)}
            style={styles.addActivityBtn}
          >
            <Ionicons name="add-circle" size={16} color={theme.color.brand} />
            <Text style={styles.addActivityT}>ADD SPORT OR HOBBY</Text>
          </Pressable>

          <StandbyStatusCard />

          <WeeklyCheckinCard />
          <PushPermissionPrompt />

          <Text style={styles.sectionTitle}>NEXT 7 DAYS</Text>
          {rosterJob && (rosterJob.status === "queued" || rosterJob.status === "processing") ? (
            <View style={styles.planBanner} testID="plan-preparing-banner">
              <Ionicons name="hourglass" size={14} color={theme.color.brand} />
              <Text style={styles.planBannerT}>CrewFit is preparing your training plan around your roster.</Text>
            </View>
          ) : null}
          {rosterJob && (rosterJob.status === "needs_review" || rosterJob.status === "partial" || rosterJob.status === "failed") ? (
            <View style={styles.planBannerAmber} testID="plan-needs-review-banner">
              <Ionicons name="alert-circle" size={14} color={theme.color.amber} />
              <View style={{ flex: 1 }}>
                <Text style={styles.planBannerT}>{rosterJob.error || "Your roster uploaded successfully, but your training plan needs review. Louis has been notified."}</Text>
                <Pressable onPress={() => router.push({ pathname: "/roster-upload" })} testID="plan-review-open">
                  <Text style={styles.planBannerLink}>OPEN ROSTER UPLOAD →</Text>
                </Pressable>
              </View>
            </View>
          ) : null}
          {loading && !workouts.length ? (
            <ActivityIndicator color={theme.color.brand} />
          ) : (
            (() => {
              const tomorrow = new Date();
              tomorrow.setDate(tomorrow.getDate() + 1);
              const tomorrowStr = localDateStr(tomorrow);
              return next7.map((w) => {
                const isTodayRow = w.__key === today;
                if (isTodayRow && setupDay?.is_setup_day) {
                  return (
                    <View key={w.__key} style={[styles.wRow, styles.wRowSetup]} testID="week-setup-today">
                      <View style={[styles.loadBar, { backgroundColor: theme.color.brand }]} />
                      <View style={{ flex: 1 }}>
                        <Text style={styles.wDate}>Today</Text>
                        <Text style={styles.wDateSub}>{dayLabel(w.__key, today, tomorrowStr).secondary || w.__key}</Text>
                        <Text style={[styles.wTitle, { color: theme.color.brand }]}>SETUP DAY</Text>
                        <Text style={styles.wMeta}>Your first workout starts tomorrow</Text>
                      </View>
                      <Ionicons name="rocket" size={16} color={theme.color.brand} style={{ marginRight: theme.space.md }} />
                    </View>
                  );
                }
                if (w.__rest) {
                  const dl = dayLabel(w.__key, today, tomorrowStr);
                  return (
                    <View key={w.__key} style={[styles.wRow, styles.wRowRest]} testID={`week-rest-${w.__key}`}>
                      <View style={[styles.loadBar, { backgroundColor: loadColor(w.day_load) }]} />
                      <View style={{ flex: 1 }}>
                        <Text style={styles.wDate}>{dl.primary}</Text>
                        {dl.secondary ? <Text style={styles.wDateSub}>{dl.secondary}</Text> : null}
                        <Text style={[styles.wTitle, styles.wTitleRest]}>{w.title}</Text>
                        <Text style={styles.wMeta}>{w.location ? `${w.location} · ` : ""}No session scheduled</Text>
                      </View>
                      <Ionicons name="moon" size={16} color={theme.color.textMuted} style={{ marginRight: theme.space.md }} />
                    </View>
                  );
                }
                const dl = dayLabel(w.__key, today, tomorrowStr);
                return (
                  <Pressable key={w.id} onPress={() => router.push(`/workout/${w.id}`)} style={styles.wRow} testID={`week-workout-${w.id}`}>
                    <View style={[styles.loadBar, { backgroundColor: loadColor(w.day_load) }]} />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.wDate}>{dl.primary}</Text>
                      {dl.secondary ? <Text style={styles.wDateSub}>{dl.secondary}</Text> : null}
                      <Text style={styles.wTitle}>{w.title}</Text>
                      <Text style={styles.wMeta}>{w.location || "Home Workout"} · {w.duration_min}min</Text>
                    </View>
                    {w.completed && <Ionicons name="checkmark-circle" size={22} color={theme.color.green} style={{ marginRight: 10 }} />}
                    {w.coach_locked && <Ionicons name="lock-closed" size={16} color={theme.color.amber} style={{ marginRight: 10 }} />}
                    {!w.approved && !w.completed && <Text style={styles.pendPill}>PENDING</Text>}
                  </Pressable>
                );
              });
            })()
          )}
        </View>
      </ScrollView>

      <Modal visible={happenedOpen} animationType="slide" transparent>
        <Pressable onPress={() => setHappenedOpen(false)} style={styles.modalBg}>
          <Pressable style={styles.sheet} onPress={(e) => e.stopPropagation()}>
            <View style={styles.sheetHandle} />
            <Text style={styles.sheetTitle}>DID TODAY GO TO PLAN?</Text>
            <Text style={styles.sheetSub}>We&apos;ll adjust tomorrow&apos;s plan based on your answer.</Text>
            {[
              ["yes_as_planned", "Yes, exactly as planned", "checkmark-circle"],
              ["workout_completed", "Workout completed", "barbell"],
              ["flight_delayed", "Flight delayed", "airplane"],
              ["called_from_standby", "Called from standby", "radio"],
              ["slept_badly", "Slept badly", "moon"],
              ["ill", "I'm ill", "medkit"],
              ["family_plans", "Family plans changed", "people"],
              ["hotel_changed", "Hotel changed", "business"],
              ["workout_missed", "Workout missed", "close-circle"],
              ["less_time", "Had less time than expected", "hourglass"],
              ["other", "Something else", "create"],
            ].map(([tag, label, icon]) => (
              <Pressable
                key={tag}
                testID={`happened-${tag}`}
                onPress={() => submitHappened(tag)}
                disabled={happenedSaving}
                style={styles.sheetRow}
              >
                <Ionicons name={icon as any} size={16} color={theme.color.brand} />
                <Text style={styles.sheetRowText}>{label}</Text>
              </Pressable>
            ))}
          </Pressable>
        </Pressable>
      </Modal>

      <RealityModal
        visible={realityOpen}
        date={today}
        onClose={() => setRealityOpen(false)}
        onApplied={() => { setRealityOpen(false); load(); }}
      />
      <TimeZoneConfirmModal user={user} />
      <AddActivityModal
        visible={addActivityOpen}
        onClose={() => setAddActivityOpen(false)}
        onCreated={() => { setActivityRefreshKey((k) => k + 1); load(); }}
        initialDate={today}
      />
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
  heroWrap: { minHeight: 360, backgroundColor: theme.color.surface2 },
  heroContent: { padding: theme.space.lg, marginTop: theme.space.md, gap: theme.space.md },
  topBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 2 },
  hello: { color: theme.color.brand, letterSpacing: 3, fontSize: 11, fontWeight: "800" },
  date: { color: theme.color.textMuted, marginTop: 4, letterSpacing: 2, fontSize: 11 },
  loadBadge: { flexDirection: "row", alignItems: "center", marginTop: theme.space.md, paddingHorizontal: 10, paddingVertical: 6, borderRadius: theme.radius.pill, borderWidth: 1, alignSelf: "flex-start", backgroundColor: "rgba(0,0,0,0.35)" },
  dot: { width: 8, height: 8, borderRadius: 4, marginRight: 6 },
  loadText: { color: theme.color.text, fontSize: 10, letterSpacing: 2, fontWeight: "800" },
  hTitle: { color: theme.color.text, marginTop: theme.space.md, fontSize: 32, fontWeight: "900", letterSpacing: -0.5 },
  duty: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1.5, fontWeight: "700", marginTop: 4 },
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
  eventCardWrap: { borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.brand, marginBottom: theme.space.md, overflow: "hidden", minHeight: 128 },
  eventCardInner: { flexDirection: "row", alignItems: "center", padding: theme.space.md },
  eTop: { color: theme.color.brand, fontSize: 10, letterSpacing: 1.5, fontWeight: "800" },
  eName: { color: theme.color.text, fontSize: 15, fontWeight: "800", marginTop: 4 },
  eDate: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },
  eBig: { color: theme.color.text, fontSize: 28, fontWeight: "900" },
  eBigLbl: { color: theme.color.textMuted, fontSize: 9, letterSpacing: 1.5, fontWeight: "800" },
  addEventBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, padding: 14, borderRadius: theme.radius.md, borderStyle: "dashed", borderWidth: 1, borderColor: theme.color.brand, marginBottom: theme.space.md },
  addEventText: { color: theme.color.brand, fontWeight: "800", letterSpacing: 1.5, fontSize: 11 },
  startCta: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", backgroundColor: theme.color.brand, paddingVertical: 18, paddingHorizontal: theme.space.lg, borderRadius: theme.radius.md },
  realityBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingVertical: 14, paddingHorizontal: theme.space.lg,
    borderRadius: theme.radius.md, marginBottom: theme.space.md,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.brand,
  },
  realityBtnLeft: { flexDirection: "row", alignItems: "center", gap: 12 },
  realityEmoji: { fontSize: 22 },
  realityIconWrap: { width: 36, height: 36, borderRadius: 18, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand, alignItems: "center", justifyContent: "center" },
  promptIconWrap: { width: 36, height: 36, borderRadius: 18, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand, alignItems: "center", justifyContent: "center" },
  realityTitle: { color: theme.color.text, fontSize: 12, fontWeight: "900", letterSpacing: 2 },
  realitySub: { color: theme.color.textMuted, fontSize: 10, marginTop: 2 },
  promptWrap: { marginBottom: theme.space.md, gap: 8 },
  promptCard: {
    padding: 12, borderRadius: 10,
    backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand,
  },
  promptLeft: { flexDirection: "row", alignItems: "flex-start", gap: 10 },
  promptEmoji: { fontSize: 22, marginTop: 2 },
  promptTitle: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },
  promptReason: { color: theme.color.text, fontSize: 12, marginTop: 4, lineHeight: 17 },
  promptCtaRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 8 },
  promptTakeBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingVertical: 6, paddingHorizontal: 10, borderRadius: 6,
    backgroundColor: theme.color.surface,
    borderWidth: 1, borderColor: theme.color.brand,
  },
  promptTakeText: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },
  promptDismissBtn: { paddingVertical: 6, paddingHorizontal: 8 },
  promptDismissText: { color: theme.color.textMuted, fontSize: 9, fontWeight: "800", letterSpacing: 1.5 },
  startText: { color: "#fff", fontWeight: "800", letterSpacing: 2, fontSize: 13 },
  emptyBox: { padding: theme.space.lg, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface2 },
  planBanner: {
    flexDirection: "row", alignItems: "center", gap: 8,
    padding: 12, borderRadius: 10, marginBottom: theme.space.sm,
    backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand,
  },
  planBannerAmber: {
    flexDirection: "row", alignItems: "flex-start", gap: 8,
    padding: 12, borderRadius: 10, marginBottom: theme.space.sm,
    backgroundColor: "rgba(245,158,11,0.10)", borderWidth: 1, borderColor: theme.color.amber,
  },
  planBannerT: { color: theme.color.text, fontSize: 12, lineHeight: 17, flex: 1 },
  planBannerLink: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5, marginTop: 6 },
  setupCard: {
    padding: theme.space.lg, borderRadius: theme.radius.md,
    borderWidth: 1, borderColor: theme.color.brand,
    backgroundColor: theme.color.brandTint,
    gap: 8, marginBottom: theme.space.md,
  },
  setupIconWrap: {
    width: 44, height: 44, borderRadius: 22, alignSelf: "flex-start",
    backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
  },
  setupTitle: { color: theme.color.brand, fontSize: 12, fontWeight: "900", letterSpacing: 2, marginTop: 4 },
  setupBody: { color: theme.color.text, fontSize: 14, lineHeight: 20 },
  setupReason: { color: theme.color.textMuted, fontSize: 12, fontStyle: "italic" },
  setupActionsRow: { flexDirection: "row", gap: 8, marginTop: 6 },
  setupBtnPrimary: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    paddingVertical: 12, borderRadius: 10, backgroundColor: theme.color.brand,
  },
  setupBtnPrimaryT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  setupBtnSecondary: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    paddingVertical: 12, borderRadius: 10,
    backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.brand,
  },
  setupBtnSecondaryT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  setupBtnGhost: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    paddingVertical: 10, borderRadius: 10, marginTop: 4,
    backgroundColor: "transparent", borderWidth: 1, borderStyle: "dashed", borderColor: theme.color.brand,
  },
  setupBtnGhostT: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },
  emptyTitle: { color: theme.color.text, fontWeight: "700", fontSize: 15 },
  emptySub: { color: theme.color.textMuted, marginTop: 6, fontSize: 13 },
  uploadBtn: { backgroundColor: theme.color.brand, paddingVertical: 14, paddingHorizontal: theme.space.lg, borderRadius: theme.radius.md, alignSelf: "flex-start", marginTop: theme.space.md },
  quickRow: { flexDirection: "row", gap: theme.space.sm, marginTop: theme.space.md },
  addActivityBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    paddingVertical: 12, marginTop: theme.space.md,
    borderRadius: theme.radius.md, borderWidth: 1, borderStyle: "dashed", borderColor: theme.color.brand,
    backgroundColor: theme.color.brandTint,
  },
  addActivityT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  qBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, paddingVertical: 12 },
  qBtnText: { color: theme.color.text, letterSpacing: 1.5, fontWeight: "700", fontSize: 10 },
  sectionTitle: { color: theme.color.textMuted, letterSpacing: 2, fontSize: 11, fontWeight: "800", marginTop: theme.space.lg, marginBottom: theme.space.sm },
  wRow: { flexDirection: "row", alignItems: "center", backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, marginBottom: theme.space.sm, overflow: "hidden", borderWidth: 1, borderColor: theme.color.border },
  wRowRest: { opacity: 0.75 },
  wRowSetup: { borderColor: theme.color.brand, backgroundColor: theme.color.brandTint },
  wTitleRest: { color: theme.color.textMuted, fontWeight: "800", letterSpacing: 1 },
  loadBar: { width: 4, alignSelf: "stretch" },
  wDate: { color: theme.color.brand, fontSize: 12, letterSpacing: 0.5, padding: theme.space.md, paddingBottom: 0, fontWeight: "800" },
  wDateSub: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 0.5, paddingHorizontal: theme.space.md, paddingTop: 2, fontWeight: "600" },
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
  sheetRow: { flexDirection: "row", alignItems: "center", gap: 10, padding: theme.space.md, borderRadius: theme.radius.md, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, marginBottom: 6 },
  sheetRowText: { color: theme.color.text, fontSize: 14, fontFamily: theme.font.text },
});
