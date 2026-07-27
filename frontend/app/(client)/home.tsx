import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { TimezoneCard } from "@/src/components/TimezoneCard";
import { MissedSessionsCard } from "@/src/components/MissedSessionsCard";
import { ClientCalendarPanel } from "@/src/components/ClientCalendarPanel";
import { NutritionTodayCard } from "@/src/components/NutritionTodayCard";
import { WeeklyReviewCard } from "@/src/components/WeeklyReviewCard";
import { DualSessionCard } from "@/src/components/DualSessionCard";
import { DailyBriefingModal } from "@/src/components/DailyBriefingModal";
import { RosterReviewBanner } from "@/src/components/RosterReviewBanner";
import { ProgrammeStatusCard } from "@/src/components/ProgrammeStatusCard";
import { RosterDayChip } from "@/src/components/RosterDayChip";
import { useFlag } from "@/src/lib/appConfig";
import { HabitTodayCard } from "@/src/components/HabitTodayCard";
import { NotificationBell } from "@/src/components/NotificationBell";
import { PushPermissionPrompt } from "@/src/components/PushPermissionPrompt";
import { StandbyStatusCard } from "@/src/components/StandbyStatusCard";
import { WhatsAppSupportButton } from "@/src/components/WhatsAppSupportButton";
import { TodayPersonalActivities } from "@/src/components/PersonalActivityCard";
import { AddActivityModal } from "@/src/components/AddActivityModal";
import { HotelSetupCard } from "@/src/components/HotelSetupCard";
import { ProgressCard } from "@/src/components/ProgressCard";
import { RosterDayPickerSheet, type RosterDayPickerTarget } from "@/src/components/RosterDayPickerSheet";
import { EventPrioritySheet } from "@/src/components/EventPrioritySheet";
import { toast as uxToast } from "@/src/lib/ux";

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
    case "roster_uploaded": return "NEW ROSTER · QUICK CHECK";
    case "injury_flagged": return "INJURY FLAGGED · RE-PLAN NEEDED";
    case "annual_leave": return "ANNUAL LEAVE · SWITCH BLOCK?";
    case "missed_workouts": return "MISSED SESSIONS · CHECK-IN";
    case "event_completed": return "EVENT COMPLETE · DEBRIEF";
    case "life_change": return "LIFE CHANGE · QUICK UPDATE";
    default: return "CREWFIT INTELLIGENCE";
  }
}

// Prompts that route to a SHORT micro-form (not the full assessment).
// The full `/assessment` flow is reserved for genuine goal shifts / fresh DNA.
const MICRO_FORM_KINDS = new Set([
  "missed_workouts",
  "life_change",
  "roster_uploaded",
  "roster_confirmed",
  "event_completed",
]);

function ctaLabelFor(kind: string): string {
  switch (kind) {
    case "missed_workouts": return "QUICK CHECK-IN";
    case "life_change":     return "QUICK UPDATE";
    case "roster_uploaded": return "QUICK CHECK";
    case "roster_confirmed": return "QUICK CHECK";
    case "event_completed": return "DEBRIEF";
    default:                return "QUICK UPDATE";
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
  // Iter 94t (Phase 1) — server-driven feature flags. Safe defaults if
  // /app-config isn't reachable.
  const tzFlag = useFlag("timezone_card_enabled");
  const missedFlag = useFlag("missed_workout_recovery_enabled");
  const nutritionFlag = useFlag("nutrition_dashboard_enabled");
  const dualSessionFlag = useFlag("dual_session_enabled");
  const calendarFlag = useFlag("calendar_scroll_enabled");
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
  // Plan C2 — Programme Overview card data (goal, phase, week, target, focus, next key session)
  const [programme, setProgramme] = useState<any>(null);
  // Iter 84 (Task 1.5) — Programme focus banner (event + primary goal reconciliation)
  const [programmeFocus, setProgrammeFocus] = useState<any>(null);
  // Iter 84 (Task 1.7) — multi-event stack + priority editor state
  const [eventsAll, setEventsAll] = useState<any[]>([]);
  const [priorityEvent, setPriorityEvent] = useState<any | null>(null);
  // Iter 92 (Phase 2, Task 2.5) — Living Profile receipt card
  const [liveStateReceipt, setLiveStateReceipt] = useState<any | null>(null);
  const [liveStateData, setLiveStateData] = useState<any | null>(null);
  // Long-press-to-correct roster day-picker sheet (iter 82).
  const [dayPickerTarget, setDayPickerTarget] = useState<RosterDayPickerTarget | null>(null);
  // Phase 7B — programme_status snapshot from /api/programme/status. Owned
  // by the ProgrammeStatusCard component, mirrored here so we can gate the
  // "Start today's session" hero and empty state on the correct value.
  const [progrStatus, setProgrStatus] = useState<string | null>(null);
  const [todayPlanState, setTodayPlanState] = useState<string | null>(null);
  // Iter 94o — Personal activities (sport/hobby) must show on the home week
  // list alongside workouts. Loaded on refresh; merged into next7.
  const [activities, setActivities] = useState<any[]>([]);
  // Iter 94s — scroll handling for calendar "Jump to Today"
  const scrollRef = useRef<ScrollView | null>(null);
  const calendarTopYRef = useRef<number>(0);
  const todayLocalYRef = useRef<number>(0);
  const jumpToToday = useCallback(() => {
    const y = Math.max(0, (calendarTopYRef.current || 0) + (todayLocalYRef.current || 0) - 40);
    scrollRef.current?.scrollTo({ y, animated: true });
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ws, r, ev, evAll, pr, sb, sd, rj, prog, focus, live, acts] = await Promise.all([
        api<any[]>("/workouts/week"),
        api<any>("/roster/current"),
        api<any>("/events/current"),
        api<any>("/events/active").catch(() => ({ events: [] })),
        api<any>("/reassessment/prompts").catch(() => ({ prompts: [] })),
        api<any>("/standby/today").catch(() => null),
        api<any>("/setup-day/status").catch(() => null),
        api<any>("/roster/jobs/active").catch(() => null),
        api<any>("/programme/current").catch(() => null),
        api<any>("/programme/focus").catch(() => null),
        api<any>("/profile/live-state").catch(() => null),
        api<any>("/personal-activities").catch(() => ({ activities: [] })),
      ]);
      setWorkouts(ws || []);
      setRoster(r && r.id ? r : null);
      setEvent(ev && ev.id ? ev : null);
      setEventsAll((evAll?.events || []) as any[]);
      setPrompts(pr.prompts || []);
      setScheduleMode(user?.profile?.schedule_mode || "normal");
      setStandbyToday(sb);
      setSetupDay(sd);
      setRosterJob(rj && rj.id ? rj : null);
      setProgramme(prog && (prog as any).id ? prog : null);
      setProgrammeFocus(focus);
      setLiveStateReceipt(live?.receipt || null);
      setLiveStateData(live?.live_state || null);
      setActivities((acts?.activities || []) as any[]);
      // Iter 94j — after a fresh load, if this brand-new client hasn't yet
      // answered the first-day-choice question, route them to the choice
      // screen. Only fires on Day 1 (needs_choice comes from the backend
      // which anchors on programme_start_date_local).
      if (prog && (prog as any).first_day_choice_needed && !(prog as any).first_day_choice) {
        try { router.replace("/first-day-choice" as any); } catch { /* ignore */ }
      }
    } finally { setLoading(false); }
  }, [user, router]);

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

  // Iter 94h — Live poll while a roster job is active OR failed. Without this
  // the client home was stale — if an upload failed 20s after the user landed
  // on the home page, they had no idea unless they pulled to refresh.
  const rosterJobPollRef = useRef<any>(null);
  useEffect(() => {
    if (rosterJobPollRef.current) {
      clearInterval(rosterJobPollRef.current);
      rosterJobPollRef.current = null;
    }
    const isActive = rosterJob && (rosterJob.status === "queued" || rosterJob.status === "processing");
    if (!isActive) return;
    rosterJobPollRef.current = setInterval(async () => {
      try {
        const j = await api<any>("/roster/jobs/active").catch(() => null);
        setRosterJob(j && j.id ? j : null);
        // If the job just finished successfully, reload the whole home so the
        // roster card + week list pick up the new data.
        if (j && (j.status === "complete" || j.status === "awaiting_confirmation")) {
          load();
        }
      } catch { /* ignore */ }
    }, 3000);
    return () => {
      if (rosterJobPollRef.current) {
        clearInterval(rosterJobPollRef.current);
        rosterJobPollRef.current = null;
      }
    };
    // We only want the polling loop to restart when the job identity/status
    // transitions — NOT on every progress/message tick (that would thrash the
    // interval every 3s and defeat the purpose).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rosterJob?.status, rosterJob?.id, load]);

  const openDayPicker = useCallback((dateStr: string) => {
    if (!roster?.id) return;
    // Only allow correcting dates the roster actually covers — otherwise the
    // backend returns 404 ("No roster day found") and the client sees a
    // confusing error. Fall back to a friendly toast in that case.
    const rd = (roster.days || []).find((d: any) => d.date === dateStr);
    if (!rd) {
      uxToast("This day isn't on your current roster yet.", "info");
      return;
    }
    setDayPickerTarget({
      rosterId: roster.id,
      date: dateStr,
      currentDayType: rd?.day_type || null,
      currentLayoverCity: rd?.layover_city || null,
    });
  }, [roster]);

  const today = localDateStr(new Date());
  const todaysWorkout = workouts.find((w) => w.date === today);
  const todaysDay = roster?.days?.find((d: any) => d.date === today);
  const load_color = loadColor(todaysWorkout?.day_load || todaysDay?.load);

  const next7 = useMemo(() => {
    const byDate = new Map<string, any>();
    (workouts || []).forEach((w: any) => { if (w?.date) byDate.set(w.date, w); });
    const rosterByDate = new Map<string, any>();
    (roster?.days || []).forEach((d: any) => { if (d?.date) rosterByDate.set(d.date, d); });
    // Iter 94o — merge personal activities (sport/hobby) by date so the
    // week list can render a small chip next to each day's workout/rest card.
    const actsByDate = new Map<string, any[]>();
    (activities || []).forEach((a: any) => {
      const d = a?.date_local;
      if (!d) return;
      const arr = actsByDate.get(d) || [];
      arr.push(a);
      actsByDate.set(d, arr);
    });
    const base = new Date();
    base.setHours(0, 0, 0, 0);
    const out: any[] = [];
    for (let i = 0; i < 7; i++) {
      const d = new Date(base);
      d.setDate(base.getDate() + i);
      const key = localDateStr(d);
      const w = byDate.get(key);
      const activitiesForDay = actsByDate.get(key) || [];
      if (w) {
        out.push({ ...w, __key: key, __rest: false, __activities: activitiesForDay });
      } else {
        const rd = rosterByDate.get(key);
        const isFlight = rd?.day_type === "flight" || (rd?.flights?.length || 0) > 0;
        out.push({
          __key: key,
          __rest: true,
          __activities: activitiesForDay,
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
  }, [workouts, roster, activities]);

  const expiry = roster?.expiry;
  const rDays = expiry?.days_remaining;
  const showBanner = expiry && (expiry.expired || (rDays !== null && rDays !== undefined && rDays <= 7));
  const bannerColor = expiry?.expired ? theme.color.red : rDays !== undefined && rDays <= 3 ? theme.color.red : theme.color.amber;

  return (
    <View style={styles.root}>
      <ScrollView
        ref={scrollRef}
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
                {/* Iter 106 — full CrewFit wordmark logo, small and slightly
                    transparent so it reads as a subtle brand watermark rather
                    than a hard header. */}
                <Image
                  source={require("@/assets/images/crewfit-logo-full.png")}
                  style={styles.topLogo}
                  contentFit="contain"
                  accessibilityLabel="CrewFit"
                />
                <NotificationBell testID="client-notif-bell" />
              </View>

              <ClientProfileHeader
                user={user as any}
                todayLoad={todaysWorkout?.day_load || todaysDay?.load || "grey"}
                dayType={todaysDay?.day_type || todaysDay?.type || null}
                dayTitle={todaysWorkout ? todaysWorkout.title : "REST & RECOVER"}
                isStandby={!!standbyToday?.is_standby}
              />

              {todaysDay?.layover_city || todaysDay?.flights?.[0] || todaysDay?.day_type ? (
                <View style={styles.dutyRow}>
                  <RosterDayChip
                    day={{
                      day_type: todaysDay?.day_type,
                      flights: todaysDay?.flights,
                      layover_city: todaysDay?.layover_city,
                    }}
                    size="md"
                    testID="hero-roster-chip-today"
                  />
                  {(todaysDay?.layover_city || todaysDay?.flights?.[0]) ? (
                    <Text style={styles.duty}>
                      {todaysDay?.flights?.[0] ? `${todaysDay.flights[0].from} → ${todaysDay.flights[0].to}` : ""}
                      {todaysDay?.layover_city && !todaysDay?.flights?.[0]
                        ? `Layover · ${String(todaysDay.layover_city)}` : ""}
                    </Text>
                  ) : null}
                </View>
              ) : null}
            </View>
          </SafeAreaView>
        </AIHeroImage>

        <View style={{ padding: theme.space.lg }}>
          {/* Iter 94r — Timezone card. Always at top so crew immediately see
              which timezone their day / workouts are being scheduled in. */}
          {tzFlag ? <TimezoneCard /> : null}
          {/* Iter 94w — Sunday weekly review card (Thu-Sun only). */}
          <WeeklyReviewCard refreshKey={activityRefreshKey} />
          {/* Iter 95a — Optional airport-activation card for short-haul dual-session days. */}
          {dualSessionFlag ? <DualSessionCard refreshKey={activityRefreshKey} /> : null}
          {/* Iter 94t Phase 1 — Nutrition (calories + protein) near top. */}
          {nutritionFlag ? <NutritionTodayCard refreshKey={activityRefreshKey} /> : null}
          {/* Iter 94s — Missed sessions banner (only renders if there are any
              recoverable missed sessions). Sits above the roster banners. */}
          {missedFlag ? <MissedSessionsCard refreshKey={activityRefreshKey} /> : null}
          {/* Iter 94h — TOP-OF-PAGE roster-job status banner. Impossible to miss
              when an upload has failed, is stuck, or is still processing. */}
          {rosterJob && rosterJob.status === "failed" ? (
            <View style={styles.jobFailedBanner} testID="home-roster-job-failed">
              <Pressable
                onPress={() => router.push("/roster-upload")}
                style={{ flexDirection: "row", alignItems: "center", gap: 12 }}
              >
                <View style={styles.jobFailedIconWrap}>
                  <Ionicons name="alert-circle" size={28} color="#fff" />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.jobFailedTitle}>ROSTER UPLOAD FAILED</Text>
                  <Text style={styles.jobFailedSub}>
                    {rosterJob.error || "We couldn't finish processing your last roster. Tap here to try again."}
                  </Text>
                  <Text style={styles.jobFailedCta}>TAP TO RETRY →</Text>
                </View>
              </Pressable>
              <View style={{ marginTop: 10 }}>
                <WhatsAppSupportButton
                  screen="home_roster_upload_failed"
                  context="roster_upload_failed"
                  rosterId={rosterJob.roster_id}
                  variant="outline"
                  showCaption={false}
                />
              </View>
            </View>
          ) : null}

          {/* Iter 95n — placeholder while Louis is "reviewing" a freshly
              uploaded roster. Auto-hides when the review window elapses. */}
          <RosterReviewBanner onReadyChanged={load} />

          {/* Iter 106 — Prominent, always-visible Upload Roster CTA.
              This is CrewFit's critical first-step feature: the whole app
              revolves around a valid roster. Keeping it as a dedicated
              full-width button above the fold means clients (and returning
              users uploading next month's roster) always know how to get
              their next roster in without hunting. */}
          <Pressable
            testID="home-upload-roster-cta"
            onPress={() => router.push("/roster-upload")}
            style={styles.uploadRosterCta}
            accessibilityLabel="Upload your roster"
            accessibilityRole="button"
          >
            <View style={styles.uploadRosterIconWrap}>
              <Ionicons name="cloud-upload" size={22} color={theme.color.brand} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.uploadRosterTitle}>UPLOAD YOUR ROSTER</Text>
              <Text style={styles.uploadRosterSub}>
                Drop your latest roster PDF and Louis will build the week around it.
              </Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color={theme.color.brand} />
          </Pressable>

          {/* Phase 7B — dynamic programme status + today state.
              Only renders when the client isn't in the default "programme
              live + session planned today" state. Handles rest/travel/
              layover days, roster review, and post-upload waiting UX. */}
          <ProgrammeStatusCard
            onStateChanged={(s) => {
              setProgrStatus(s.programme_status);
              setTodayPlanState(s.today_plan_state?.state || null);
              if (progrStatus && progrStatus !== s.programme_status && s.programme_status === "programme_live") {
                // The programme just went live — reload workouts/roster so
                // the "Start today's session" hero picks up the new plan.
                load();
              }
            }}
          />
          {rosterJob && (rosterJob.status === "needs_review" || rosterJob.status === "partial") ? (
            <View style={styles.jobReviewBanner} testID="home-roster-job-review">
              <Pressable
                onPress={() => router.push("/roster-upload")}
                style={{ flexDirection: "row", alignItems: "center", gap: 12 }}
              >
                <View style={styles.jobReviewIconWrap}>
                  <Ionicons name="warning" size={26} color="#fff" />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.jobReviewTitle}>ROSTER SAVED · PLAN NEEDS REVIEW</Text>
                  <Text style={styles.jobReviewSub}>
                    {rosterJob.error || "Your roster was saved but the training plan needs a retry. Louis has been notified."}
                  </Text>
                  <Text style={styles.jobReviewCta}>OPEN ROSTER UPLOAD →</Text>
                </View>
              </Pressable>
              <View style={{ marginTop: 10 }}>
                <WhatsAppSupportButton
                  screen="home_plan_needs_review"
                  context="plan_needs_review"
                  rosterId={rosterJob.roster_id}
                  variant="outline"
                  showCaption={false}
                />
              </View>
            </View>
          ) : null}
          {rosterJob && (rosterJob.status === "queued" || rosterJob.status === "processing") ? (
            <Pressable
              testID="home-roster-job-processing"
              onPress={() => router.push("/roster-upload")}
              style={styles.jobProcessingBanner}
            >
              <ActivityIndicator color={theme.color.brand} />
              <View style={{ flex: 1, marginLeft: 12 }}>
                <Text style={styles.jobProcessingTitle}>PREPARING YOUR TRAINING PLAN</Text>
                <Text style={styles.jobProcessingSub}>
                  {rosterJob.message || "CrewFit is building your calendar around your roster."} {rosterJob.progress ? `· ${rosterJob.progress}%` : ""}
                </Text>
                <Text style={styles.jobProcessingCta}>TAP TO SEE PROGRESS →</Text>
              </View>
            </Pressable>
          ) : null}

          {/* Iter 94j — Setup Day card. Appears when programme.first_day_choice=="setup_day"
              AND today == programme_start_date_local. Replaces the empty
              "no workout today" feeling with a clear checklist + CTAs. */}
          {programme?.is_setup_day_today && !programme?.first_day_choice_needed ? (
            <View style={styles.fdSetupCard} testID="home-setup-day-card">
              <View style={styles.fdSetupHeader}>
                <View style={styles.fdSetupIconWrap}>
                  <Ionicons name="clipboard" size={22} color={theme.color.brand} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.fdSetupTitle}>SETUP DAY</Text>
                  <Text style={styles.fdSetupSub}>
                    Today is for getting ready, not rushing into training.
                  </Text>
                </View>
              </View>
              <View style={styles.fdSetupChecklist}>
                {[
                  "Review your programme",
                  "Check your first workout",
                  "Confirm your equipment",
                  "Review your roster",
                  "Add hotel setup if needed",
                  "Message Louis with anything that looks wrong",
                ].map((t, i) => (
                  <View key={i} style={styles.fdSetupRow}>
                    <Ionicons name="ellipse-outline" size={14} color={theme.color.textMuted} />
                    <Text style={styles.fdSetupRowT}>{t}</Text>
                  </View>
                ))}
              </View>
              {programme.first_real_workout_date_local ? (
                <Text style={styles.fdSetupFirstReal}>
                  First proper session: <Text style={{ fontWeight: "800", color: theme.color.text }}>{programme.first_real_workout_date_local}</Text>
                </Text>
              ) : null}
              <View style={styles.fdSetupActions}>
                <Pressable style={styles.fdSetupBtn} onPress={() => {}} testID="setup-view-plan">
                  <Ionicons name="calendar" size={14} color={theme.color.brand} />
                  <Text style={styles.fdSetupBtnT}>VIEW MY PLAN</Text>
                </Pressable>
                <Pressable style={styles.fdSetupBtn} onPress={() => router.push("/(client)/profile" as any)} testID="setup-check-equipment">
                  <Ionicons name="barbell" size={14} color={theme.color.brand} />
                  <Text style={styles.fdSetupBtnT}>CHECK EQUIPMENT</Text>
                </Pressable>
                <Pressable style={styles.fdSetupBtn} onPress={() => router.push("/(client)/messages" as any)} testID="setup-message-louis">
                  <Ionicons name="chatbubble-ellipses" size={14} color={theme.color.brand} />
                  <Text style={styles.fdSetupBtnT}>MESSAGE LOUIS</Text>
                </Pressable>
              </View>
            </View>
          ) : null}

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

          {/* Phase 1: Hotel Setup — appears when upcoming layovers need a hotel/gym profile */}
          <HotelSetupCard />

          {/* Phase 3: Your Progress — appears when a weekly snapshot exists */}
          <ProgressCard />

          {event ? (
            <Pressable testID="event-card" onPress={() => router.push("/event")} onLongPress={() => setPriorityEvent(eventsAll.find(e => e.id === event.id) || event)}>
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

          {/* Iter 84 (Task 1.7) — additional registered events (beyond primary) */}
          {eventsAll.length > 1 ? (
            <View style={styles.otherEventsWrap} testID="events-secondary-stack">
              <Text style={styles.otherEventsTitle}>ALSO ON YOUR CALENDAR</Text>
              {eventsAll.filter((e) => e.id !== event?.id).slice(0, 3).map((e) => {
                const p = e.priority || "C";
                const color = p === "A" ? "#DC2626" : p === "B" ? "#F59E0B" : "#6B7280";
                return (
                  <Pressable
                    key={e.id}
                    testID={`event-row-${e.id}`}
                    onPress={() => setPriorityEvent(e)}
                    style={styles.otherEventRow}
                  >
                    <View style={[styles.priPill, { backgroundColor: color }]}>
                      <Text style={styles.priPillT}>{p}</Text>
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.otherEventName} numberOfLines={1}>{e.event_name}</Text>
                      <Text style={styles.otherEventMeta} numberOfLines={1}>
                        {(e.event_type || "").replace(/_/g, " ")} · {e.weeks_to_event ?? "?"} wk
                      </Text>
                    </View>
                    <Ionicons name="chevron-forward" size={14} color={theme.color.textMuted} />
                  </Pressable>
                );
              })}
              <Text style={styles.otherEventsHint}>Tap to change priority.</Text>
            </View>
          ) : null}

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
                              onPress={() => {
                                // Route to a SHORT micro-form for common signals;
                                // fall back to the full assessment only for
                                // unknown / genuine-goal-shift kinds.
                                if (MICRO_FORM_KINDS.has(p.kind)) {
                                  router.push(`/reassessment/${p.kind}?prompt_id=${p.id}` as any);
                                } else {
                                  router.push("/assessment" as any);
                                }
                              }}
                              style={styles.promptTakeBtn}
                            >
                              <Text style={styles.promptTakeText}>{ctaLabelFor(p.kind)}</Text>
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
            // Phase 7B — when the programme isn't live yet (waiting for
            // Louis, roster in review, etc.) OR today has a special
            // non-training state, the ProgrammeStatusCard at the top is
            // already telling the story. Rendering the generic "No workout
            // scheduled" empty box below it would be noisy and confusing.
            progrStatus && (progrStatus !== "programme_live" || (todayPlanState && todayPlanState !== "session_planned" && todayPlanState !== "no_session_planned")) ? null : (
            <View style={styles.emptyBox}>
              <Text style={styles.emptyTitle}>No workout scheduled for today</Text>
              <Text style={styles.emptySub}>Upload your roster so CrewFit can build your personalised training plan.</Text>
              <Pressable testID="upload-roster-cta" onPress={() => router.push("/roster-upload")} style={styles.uploadBtn}>
                <Text style={styles.startText}>UPLOAD ROSTER</Text>
              </Pressable>
            </View>
            )
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

          {/* Plan C2 — Programme Overview card */}
          {programme ? (
            (() => {
              const goal = programme.goal_label || programme.goal_key || "Your Plan";
              const phaseLbl = (programme.phase && (programme.phase.label || programme.phase.key)) || "Foundation Phase";
              // Iter 94j — Use `display_week` computed server-side from
              // `programme_start_date_local`. Fall back to the raw
              // `week_index` (already 1-indexed) for old programmes that
              // haven't been re-enriched. NEVER add +1 here — that was the
              // Day-1 shows-Week-2 bug.
              const wkIdx = programme.display_week
                ?? programme.week_index
                ?? 1;
              const target = programme.target_sessions_per_week || programme.progression?.target_sessions_per_week;
              const planned = programme.progression?.sessions_planned_this_week;
              const done = programme.progression?.sessions_completed_this_week;
              const nextKey = (next7 || []).find((w: any) => !w.__rest && w?.key_session && !w?.completed);
              const focus = programme.focus_copy || programme.session_style;
              return (
                <View style={styles.progCard}>
                  <View style={styles.progHeaderRow}>
                    <Text style={styles.progHeader}>YOUR CURRENT FOCUS</Text>
                    {programme.validation_status && programme.validation_status !== "ok" ? (
                      <View style={styles.progWarn}>
                        <Ionicons name="alert-circle" size={12} color={theme.color.amber} />
                        <Text style={styles.progWarnT}>NEEDS COACH REVIEW</Text>
                      </View>
                    ) : null}
                  </View>
                  <Text style={styles.progGoal}>{goal} · {phaseLbl}{wkIdx ? ` · Week ${wkIdx}` : ""}</Text>
                  {focus ? <Text style={styles.progFocus}>{focus}</Text> : null}
                  <View style={styles.progMetricsRow}>
                    {target !== undefined ? (
                      <View style={styles.progMetric}>
                        <Text style={styles.progMetricV}>{done ?? 0}/{target}</Text>
                        <Text style={styles.progMetricL}>this week</Text>
                      </View>
                    ) : null}
                    {planned !== undefined ? (
                      <View style={styles.progMetric}>
                        <Text style={styles.progMetricV}>{planned}</Text>
                        <Text style={styles.progMetricL}>planned</Text>
                      </View>
                    ) : null}
                    {programme.progression?.deload_status === "deload_week" ? (
                      <View style={styles.progMetric}>
                        <Text style={styles.progMetricV}>DELOAD</Text>
                        <Text style={styles.progMetricL}>this week</Text>
                      </View>
                    ) : null}
                  </View>
                  {nextKey ? (
                    <View style={styles.progNext}>
                      <Ionicons name="star" size={12} color={theme.color.brand} />
                      <Text style={styles.progNextL}>Next key session · {nextKey.title || "Session"}</Text>
                    </View>
                  ) : null}
                </View>
              );
            })()
          ) : null}

          <Text style={styles.sectionTitle}>YOUR SCHEDULE</Text>
          {programmeFocus?.banner_text ? (
            <View style={styles.focusBanner} testID="programme-focus-banner">
              <Ionicons name="flag" size={12} color={theme.color.brand} />
              <Text style={styles.focusBannerT} numberOfLines={2}>{programmeFocus.banner_text}</Text>
            </View>
          ) : null}
          {liveStateReceipt?.bullets?.length ? (
            <View style={styles.receiptCard} testID="live-state-receipt">
              <View style={styles.receiptHeader}>
                <Ionicons name="sparkles" size={12} color={theme.color.brand} />
                <Text style={styles.receiptTitle}>YOUR INPUT · NEXT WEEK</Text>
              </View>
              {liveStateReceipt.bullets.map((line: string, i: number) => (
                <View key={i} style={styles.receiptRow}>
                  <Text style={styles.receiptDot}>·</Text>
                  <Text style={styles.receiptBody} numberOfLines={3}>{line}</Text>
                </View>
              ))}
              {liveStateData?.auto_deload_trigger ? (
                <View style={styles.receiptChip} testID="live-state-deload-chip">
                  <Text style={styles.receiptChipT}>DELOAD · AUTO</Text>
                </View>
              ) : null}
            </View>
          ) : null}
          {roster?.id ? (
            <Text style={styles.sectionHint} testID="week-longpress-hint">
              Tip: scroll up or down to see past and future days. Long-press any day to change its duty type.
            </Text>
          ) : null}
          {/* Iter 94s — Scrollable calendar (±30 days initially, up to ±60). */}
          {calendarFlag ? (
            <View
              onLayout={(e) => { calendarTopYRef.current = e.nativeEvent.layout.y; }}
            >
              <ClientCalendarPanel
                refreshKey={activityRefreshKey}
                onLongPressDay={(d) => openDayPicker(d)}
                onTodayLayoutY={(y) => { todayLocalYRef.current = y; }}
                onJumpToToday={jumpToToday}
              />
            </View>
          ) : (
            <Text style={styles.sectionHint}>Calendar temporarily unavailable — message Louis if this persists.</Text>
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
      {/* Iter 94u — Louis's Daily Briefing (once per local day). */}
      <DailyBriefingModal />
      <AddActivityModal
        visible={addActivityOpen}
        onClose={() => setAddActivityOpen(false)}
        onCreated={() => { setActivityRefreshKey((k) => k + 1); load(); }}
        initialDate={today}
      />
      <RosterDayPickerSheet
        target={dayPickerTarget}
        onClose={() => setDayPickerTarget(null)}
        onSaved={() => load()}
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
  topLogo: { width: 96, height: 30, opacity: 0.82 },
  hello: { color: theme.color.brand, letterSpacing: 3, fontSize: 11, fontWeight: "800" },
  date: { color: theme.color.textMuted, marginTop: 4, letterSpacing: 2, fontSize: 11 },
  loadBadge: { flexDirection: "row", alignItems: "center", marginTop: theme.space.md, paddingHorizontal: 10, paddingVertical: 6, borderRadius: theme.radius.pill, borderWidth: 1, alignSelf: "flex-start", backgroundColor: "rgba(0,0,0,0.35)" },
  dot: { width: 8, height: 8, borderRadius: 4, marginRight: 6 },
  loadText: { color: theme.color.text, fontSize: 10, letterSpacing: 2, fontWeight: "800" },
  hTitle: { color: theme.color.text, marginTop: theme.space.md, fontSize: 32, fontWeight: "900", letterSpacing: -0.5 },
  dutyRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 8, flexWrap: "wrap" },
  duty: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1.5, fontWeight: "700" },

  // Iter 106 — Standalone Upload Roster button
  uploadRosterCta: {
    flexDirection: "row",
    alignItems: "center",
    gap: 14,
    padding: 16,
    borderRadius: 14,
    marginBottom: theme.space.md,
    backgroundColor: theme.color.surface,
    borderWidth: 1,
    borderColor: theme.color.brand,
  },
  uploadRosterIconWrap: {
    width: 44, height: 44, borderRadius: 22,
    backgroundColor: theme.color.brandTint,
    borderWidth: 1, borderColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
  },
  uploadRosterTitle: {
    color: theme.color.brand,
    fontSize: 12, fontWeight: "900", letterSpacing: 1.8,
  },
  uploadRosterSub: {
    color: theme.color.textMuted,
    fontSize: 11, marginTop: 3, lineHeight: 15,
  },

  // Iter 100 — Next 5 Days strip on home
  next5Wrap: {
    marginTop: 20,
    padding: 14,
    borderRadius: 12,
    backgroundColor: theme.color.surface2,
    borderWidth: 1,
    borderColor: theme.color.border,
  },
  next5Head: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 10 },
  next5Title: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  next5More: { color: theme.color.brand, fontSize: 10, fontWeight: "800", letterSpacing: 1.5 },
  next5Row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingVertical: 10,
    borderTopWidth: 1,
    borderTopColor: theme.color.divider,
  },
  next5DateCol: { width: 42, alignItems: "center" },
  next5Dow: { color: theme.color.textMuted, fontSize: 9, fontWeight: "800", letterSpacing: 1 },
  next5Dnum: { color: theme.color.text, fontSize: 18, fontWeight: "900", marginTop: 1 },
  next5WorkoutTitle: { color: theme.color.text, fontSize: 12, fontWeight: "800" },
  next5MetaRow: { flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" },
  next5Meta: { color: theme.color.textMuted, fontSize: 10, fontWeight: "700" },
  next5KeyPill: {
    flexDirection: "row", alignItems: "center", gap: 3,
    paddingHorizontal: 5, paddingVertical: 2,
    borderRadius: 3,
    backgroundColor: theme.color.brandTint,
    borderWidth: 1, borderColor: theme.color.brand,
  },
  next5KeyPillT: { color: theme.color.brand, fontSize: 8, fontWeight: "900", letterSpacing: 0.5 },
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
  // Iter 94h — Big, unmissable roster-job banners for the client home. These
  // sit ABOVE every other card because the earlier failure state was buried.
  jobFailedBanner: {
    flexDirection: "row", alignItems: "center", gap: 12,
    padding: 14, borderRadius: 12, marginBottom: theme.space.md,
    backgroundColor: "rgba(239,68,68,0.14)",
    borderWidth: 2, borderColor: theme.color.red,
  },
  jobFailedIconWrap: {
    width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center",
    backgroundColor: theme.color.red,
  },
  jobFailedTitle: { color: theme.color.red, fontSize: 13, fontWeight: "900", letterSpacing: 1.5 },
  jobFailedSub:   { color: theme.color.text, fontSize: 12, lineHeight: 17, marginTop: 4 },
  jobFailedCta:   { color: theme.color.red, fontSize: 11, fontWeight: "900", letterSpacing: 1.5, marginTop: 8 },
  jobReviewBanner: {
    flexDirection: "row", alignItems: "center", gap: 12,
    padding: 14, borderRadius: 12, marginBottom: theme.space.md,
    backgroundColor: "rgba(245,158,11,0.14)",
    borderWidth: 2, borderColor: theme.color.amber,
  },
  jobReviewIconWrap: {
    width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center",
    backgroundColor: theme.color.amber,
  },
  jobReviewTitle: { color: theme.color.amber, fontSize: 13, fontWeight: "900", letterSpacing: 1.5 },
  jobReviewSub:   { color: theme.color.text, fontSize: 12, lineHeight: 17, marginTop: 4 },
  jobReviewCta:   { color: theme.color.amber, fontSize: 11, fontWeight: "900", letterSpacing: 1.5, marginTop: 8 },
  jobProcessingBanner: {
    flexDirection: "row", alignItems: "center",
    padding: 14, borderRadius: 12, marginBottom: theme.space.md,
    backgroundColor: theme.color.brandTint,
    borderWidth: 1, borderColor: theme.color.brand,
  },
  jobProcessingTitle: { color: theme.color.brand, fontSize: 13, fontWeight: "900", letterSpacing: 1.5 },
  jobProcessingSub:   { color: theme.color.text, fontSize: 12, lineHeight: 17, marginTop: 4 },
  jobProcessingCta:   { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5, marginTop: 8 },
  // Iter 94j — Setup Day card styles (top-of-home mini card for the
  // first-day-choice=setup_day state). Distinct from the fuller `setupCard`
  // used lower down by the /setup-day/status flow.
  fdSetupCard: {
    padding: 16, borderRadius: 14, marginBottom: theme.space.md,
    backgroundColor: theme.color.brandTint,
    borderWidth: 1, borderColor: theme.color.brand,
  },
  fdSetupHeader: { flexDirection: "row", alignItems: "center", gap: 12, marginBottom: 12 },
  fdSetupIconWrap: {
    width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center",
    backgroundColor: theme.color.surfaceElev,
  },
  fdSetupTitle: { color: theme.color.brand, fontSize: 14, fontWeight: "900", letterSpacing: 2 },
  fdSetupSub:   { color: theme.color.text, fontSize: 12, lineHeight: 17, marginTop: 4 },
  fdSetupChecklist: { gap: 6, marginBottom: 10 },
  fdSetupRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  fdSetupRowT: { color: theme.color.text, fontSize: 12 },
  fdSetupFirstReal: { color: theme.color.textMuted, fontSize: 12, marginTop: 6, marginBottom: 10 },
  fdSetupActions: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  fdSetupBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingVertical: 8, paddingHorizontal: 10, borderRadius: 8,
    borderWidth: 1, borderColor: theme.color.brand,
    backgroundColor: theme.color.surface,
  },
  fdSetupBtnT: { color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 0.5 },
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
  sectionHint: { color: theme.color.textDim, fontSize: 11, fontStyle: "italic", marginBottom: theme.space.sm, marginTop: -6 },
  focusBanner: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: 12, paddingVertical: 10,
    marginBottom: theme.space.sm, marginTop: -4,
    backgroundColor: theme.color.brandTint,
    borderRadius: theme.radius.md,
    borderLeftWidth: 3, borderLeftColor: theme.color.brand,
  },
  focusBannerT: { color: theme.color.brand, fontSize: 11, fontWeight: "700", flex: 1, lineHeight: 15 },
  receiptCard: {
    paddingHorizontal: 12, paddingVertical: 10,
    marginBottom: theme.space.sm,
    backgroundColor: "rgba(59,130,246,0.06)",
    borderRadius: theme.radius.md,
    borderLeftWidth: 3, borderLeftColor: theme.color.brand,
  },
  receiptHeader: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 6 },
  receiptTitle: { color: theme.color.brand, fontSize: 10, letterSpacing: 1.4, fontWeight: "800" },
  receiptRow: { flexDirection: "row", alignItems: "flex-start", gap: 6, marginTop: 3 },
  receiptDot: { color: theme.color.brand, fontSize: 12, lineHeight: 15, fontWeight: "900", width: 8 },
  receiptBody: { color: theme.color.text, fontSize: 12, lineHeight: 16, flex: 1 },
  receiptChip: { alignSelf: "flex-start", marginTop: 6, paddingHorizontal: 8, paddingVertical: 3, borderRadius: theme.radius.pill, backgroundColor: theme.color.amber || "#e5a337" },
  receiptChipT: { color: "#111", fontSize: 9, fontWeight: "900", letterSpacing: 1.2 },
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
  // Plan C1 — split status pills — iter 82 fix: constrain to prevent
  // text column from being squeezed on narrow screens (Tue 21 Jul bug).
  statusPill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 8, paddingVertical: 4,
    borderRadius: theme.radius.sm,
    marginRight: theme.space.md,
    borderWidth: 1,
    flexShrink: 0,
    maxWidth: 92,
    alignSelf: "center",
  },
  statusPillText: { fontSize: 9, letterSpacing: 1.2, fontWeight: "800" },
  statusPlanned: { backgroundColor: "rgba(148,163,184,0.10)", borderColor: "rgba(148,163,184,0.30)" },
  statusReview: { backgroundColor: "rgba(239,68,68,0.10)", borderColor: "rgba(239,68,68,0.35)" },
  statusLocked: { backgroundColor: "rgba(245,158,11,0.10)", borderColor: "rgba(245,158,11,0.35)" },
  statusApproved: { backgroundColor: "rgba(34,197,94,0.10)", borderColor: "rgba(34,197,94,0.35)" },
  // Phase 2 — "Why this changed" reason pill
  reasonPill: {
    flexDirection: "row", alignItems: "flex-start", gap: 4,
    marginTop: 6, paddingHorizontal: 6, paddingVertical: 3,
    borderRadius: 4,
    backgroundColor: "rgba(163,24,46,0.08)",
    borderLeftWidth: 2, borderLeftColor: theme.color.brand,
    alignSelf: "flex-start", maxWidth: "100%",
  },
  reasonText: {
    fontSize: 10.5, color: theme.color.textMuted, flex: 1, lineHeight: 14,
  },
  // Iter 94o — personal-activity chip shown on the week list
  activityChip: {
    flexDirection: "row", alignItems: "center", gap: 4,
    marginTop: 6, paddingHorizontal: 6, paddingVertical: 3,
    borderRadius: 4,
    backgroundColor: theme.color.brandTint,
    borderLeftWidth: 2, borderLeftColor: theme.color.brand,
    alignSelf: "flex-start", maxWidth: "100%",
  },
  activityChipT: {
    color: theme.color.brand, fontSize: 10.5, fontWeight: "700",
  },
  // Iter 94p — duty summary line under each workout/rest card
  wDutyLine: {
    color: theme.color.textMuted, fontSize: 11, marginTop: 2,
    fontWeight: "600", letterSpacing: 0.2,
  },
  // Plan C2 — Programme Overview card
  progCard: { backgroundColor: theme.color.cardBg, borderWidth: 1, borderColor: theme.color.line, borderRadius: theme.radius.md, padding: theme.space.md, marginTop: theme.space.md, marginBottom: theme.space.sm },
  progHeaderRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  progHeader: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1.2, fontWeight: "800" },
  progWarn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 6, paddingVertical: 3, borderRadius: 4, backgroundColor: "rgba(245,158,11,0.10)", borderWidth: 1, borderColor: "rgba(245,158,11,0.35)" },
  progWarnT: { color: theme.color.amber, fontSize: 9, letterSpacing: 1.0, fontWeight: "800" },
  progGoal: { color: theme.color.text, fontSize: 15, fontWeight: "800", marginTop: 6 },
  progFocus: { color: theme.color.textMuted, fontSize: 12, marginTop: 4, lineHeight: 17 },
  progMetricsRow: { flexDirection: "row", gap: 16, marginTop: 12 },
  progMetric: { alignItems: "flex-start" },
  progMetricV: { color: theme.color.text, fontSize: 18, fontWeight: "900" },
  progMetricL: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 0.8, fontWeight: "700", marginTop: 2, textTransform: "uppercase" },
  progNext: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 10, paddingTop: 10, borderTopWidth: 1, borderTopColor: theme.color.line },
  progNextL: { color: theme.color.text, fontSize: 12, fontWeight: "700" },
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
