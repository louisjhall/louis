/**
 * ProgrammeStatusCard — Phase 7B client-facing state card.
 *
 * Consumes GET /api/programme/status and renders the correct card for the
 * current programme_status + today_plan_state pairing. This card sits high
 * on the client home dashboard and replaces the generic "Start today's
 * session" hero when the client is:
 *   - waiting for Louis to approve the programme
 *   - on a rest / travel / layover day
 *   - waiting on a roster review (client- or coach-side)
 *
 * The 4-step timeline (uploaded → reviewed → approved → live) is always
 * rendered on the card while the programme isn't fully live, giving the
 * client a transparent sense of where their week is in the pipeline.
 *
 * Polls every 15s + refreshes on tab focus so the "waiting" card
 * transitions to the live state without a manual refresh once Louis
 * approves.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type TimelineStep = { key: string; label: string; state: "completed" | "in_progress" | "pending" };
type TodayPlan = { state: string; workout_id: string | null; label: string | null };
type ProgrammeStatus = {
  programme_status:
    | "no_roster_uploaded"
    | "roster_parsing"
    | "roster_needs_client_review"
    | "roster_needs_coach_review"
    | "waiting_for_programme_approval"
    | "programme_live"
    | "programme_needs_update";
  today_plan_state: TodayPlan;
  timeline: TimelineStep[];
  generated_at: string;
};

const HEADLINE: Record<string, { eyebrow: string; title: string; body: string; icon: any }> = {
  roster_parsing: {
    eyebrow: "ROSTER IN THE QUEUE",
    title: "Louis is reading your roster.",
    body: "Once it's parsed, Louis will build your training around your flights, layovers and rest days. You'll be notified the moment it's live.",
    icon: "hourglass",
  },
  roster_needs_client_review: {
    eyebrow: "QUICK ROSTER REVIEW",
    title: "Just double-check your duties.",
    body: "Your roster is uploaded — pop into Roster Review, confirm the days look right, and Louis will finalise your programme from there.",
    icon: "checkmark-done",
  },
  roster_needs_coach_review: {
    eyebrow: "LOUIS IS TAKING A CLOSER LOOK",
    title: "Louis wants a second look at this one.",
    body: "There are a few duties that need Louis to double-check them personally. He'll be in touch shortly — no action needed from you.",
    icon: "eye",
  },
  waiting_for_programme_approval: {
    eyebrow: "PROGRAMME UNDER FINAL REVIEW",
    title: "Louis is finalising your programme.",
    body: "Your roster is in and matched to your training plan. Louis is running a final check before it lands in your calendar. You'll get a message from him the moment it's live.",
    icon: "sparkles",
  },
  programme_needs_update: {
    eyebrow: "PROGRAMME REFRESH IN MOTION",
    title: "Louis is refreshing your plan.",
    body: "Something changed — a new roster, an event update, or a check-in — so Louis is adjusting the plan. Your current sessions still stand until the new ones drop.",
    icon: "refresh-circle",
  },
};

// Dynamic "today" card shown INSIDE the ProgrammeStatusCard when the
// programme is live but today is not a training day, OR after approval
// has just landed. Kept tight and confident — no automated language.
const TODAY_COPY: Record<string, { eyebrow: string; title: string; body: string; icon: any }> = {
  rest_day: {
    eyebrow: "TODAY · REST DAY",
    title: "Today is a rest day.",
    body: "No session scheduled — sleep, hydrate and let the training bank in. Your next session is in your calendar.",
    icon: "moon",
  },
  travel_day: {
    eyebrow: "TODAY · FLYING",
    title: "Today is built around your flying schedule.",
    body: "Nutrition, hydration and recovery are the focus today. If your day changes, tap Today's Reality below and Louis will re-plan.",
    icon: "airplane",
  },
  layover_day: {
    eyebrow: "TODAY · LAYOVER",
    title: "Layover day — hotel or bodyweight setup.",
    body: "Your plan for today is matched to hotel/gym equipment. If your hotel gym is closed, tap Today's Reality and Louis will adjust.",
    icon: "bed",
  },
  recovery_planned: {
    eyebrow: "TODAY · RECOVERY",
    title: "Recovery-focused day.",
    body: "Keep it light — mobility, walk, breath. Your calendar has the details.",
    icon: "leaf",
  },
  nutrition_focus: {
    eyebrow: "TODAY · NUTRITION FOCUS",
    title: "No workout today — focus on your fuel.",
    body: "Your calorie and protein targets are on your dashboard. Small, consistent wins today.",
    icon: "nutrition",
  },
  habit_focus: {
    eyebrow: "TODAY · HABIT FOCUS",
    title: "No workout today — habit day.",
    body: "Sleep, hydration and daily habits are the focus. Check your dashboard for what to log.",
    icon: "checkmark-circle",
  },
  no_session_planned: {
    eyebrow: "TODAY",
    title: "No session planned for today.",
    body: "Check your calendar for the next scheduled workout, or tap Today's Reality if something has changed.",
    icon: "calendar-clear",
  },
};

export function ProgrammeStatusCard({
  onStateChanged,
  hideOnLive = true,
}: {
  onStateChanged?: (status: ProgrammeStatus) => void;
  /** If true, the card renders NOTHING when programme_status == "programme_live"
   *  AND today_plan_state == "session_planned" (i.e. the default "just do
   *  today's workout" case). Home passes hideOnLive so the card can quietly
   *  vanish once everything is going. */
  hideOnLive?: boolean;
}) {
  const router = useRouter();
  const [state, setState] = useState<ProgrammeStatus | null>(null);
  const [hasManualWorkout, setHasManualWorkout] = useState<boolean>(false);
  const lastStateRef = useRef<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await api<ProgrammeStatus>("/programme/status");
      setState(r);
      onStateChanged?.(r);
      // Stage I — hide the "Louis is finalising your programme" card as soon
      // as the client has ANY visible workout. Only check when programme
      // status is still "waiting_for_programme_approval" — otherwise skip
      // the extra /workouts/week fetch to avoid unnecessary API traffic.
      // The card also re-loads on screen focus (useFocusEffect below), so
      // we don't need a fast poll to catch new workouts.
      if (r.programme_status === "waiting_for_programme_approval") {
        try {
          const wk = await api<{ workouts?: any[] } | any[]>("/workouts/week");
          const rows = Array.isArray(wk) ? wk : (wk?.workouts || []);
          setHasManualWorkout(rows.length > 0);
        } catch { /* non-fatal */ }
      } else {
        setHasManualWorkout(false);
      }
      if (lastStateRef.current && lastStateRef.current !== r.programme_status) {
        onStateChanged?.(r);
      }
      lastStateRef.current = r.programme_status;
    } catch {
      // Missing endpoint / offline — silently swallow so the home screen
      // still renders. We DON'T want to blank out the client's dashboard
      // just because status polling failed.
    }
  }, [onStateChanged]);

  // Poll every 15s while mounted + one immediate read.
  useEffect(() => {
    load();
    const t = setInterval(load, 15_000);
    return () => clearInterval(t);
  }, [load]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (!state) return null;

  const ps = state.programme_status;
  const today = state.today_plan_state?.state;

  // Suppress card entirely when everything is normal.
  if (hideOnLive && ps === "programme_live" && today === "session_planned") return null;

  // Stage I — Manual Mode dismissal. Once any workout is visible to the
  // client, drop the "Louis is finalising your programme" holding card so
  // the client sees their actual training instead of a stale approval banner.
  if (ps === "waiting_for_programme_approval" && hasManualWorkout) return null;

  // no_roster_uploaded is handled by the existing empty-state block on
  // home — no need to double up.
  if (ps === "no_roster_uploaded") return null;

  const isWaiting =
    ps === "roster_parsing" ||
    ps === "roster_needs_client_review" ||
    ps === "roster_needs_coach_review" ||
    ps === "waiting_for_programme_approval" ||
    ps === "programme_needs_update";

  const head = HEADLINE[ps];
  const todayCopy = today && today !== "session_planned" && today !== "programme_waiting_approval" && today !== "roster_needs_review"
    ? TODAY_COPY[today]
    : null;

  return (
    <View style={styles.card} testID="programme-status-card">
      {/* HEADLINE — waiting/needs-review state */}
      {isWaiting && head ? (
        <View style={styles.headline}>
          <View style={styles.headIconWrap}>
            {ps === "waiting_for_programme_approval" || ps === "roster_parsing" ? (
              <ActivityIndicator color={theme.color.brand} />
            ) : (
              <Ionicons name={head.icon} size={22} color={theme.color.brand} />
            )}
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.eyebrow}>{head.eyebrow}</Text>
            <Text style={styles.title}>{head.title}</Text>
            <Text style={styles.body}>{head.body}</Text>
          </View>
        </View>
      ) : null}

      {/* TODAY block — shown alongside a live programme when today is
          rest/travel/layover/etc. Also shown BELOW the waiting headline
          when meaningful. */}
      {todayCopy ? (
        <View style={[styles.todayRow, isWaiting && { marginTop: 14 }]}>
          <View style={styles.todayIconWrap}>
            <Ionicons name={todayCopy.icon} size={18} color={theme.color.brand} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.todayEyebrow}>{todayCopy.eyebrow}</Text>
            <Text style={styles.todayTitle}>{state.today_plan_state?.label || todayCopy.title}</Text>
            <Text style={styles.todayBody}>{todayCopy.body}</Text>
          </View>
        </View>
      ) : null}

      {/* TIMELINE — always rendered while not fully live */}
      {isWaiting ? (
        <View style={styles.timelineWrap}>
          {/* Iter 162c · Defensive array guards. Backend may briefly return
              partial state during migrations or when the coach hasn't
              published yet — never crash the dashboard on a missing key. */}
          {((state.timeline || []) as any[]).map((step, i) => {
            const tl = state.timeline || [];
            const isLast = i === tl.length - 1;
            const dotBg =
              step.state === "completed" ? theme.color.brand
              : step.state === "in_progress" ? theme.color.amber
              : "transparent";
            const lineBg = step.state === "completed" ? theme.color.brand : theme.color.border;
            return (
              <View key={step.key} style={styles.tlRow} testID={`ps-tl-${step.key}`}>
                <View style={styles.tlDotCol}>
                  <View style={[
                    styles.tlDot,
                    { backgroundColor: dotBg, borderColor: step.state === "pending" ? theme.color.border : theme.color.brand },
                  ]}>
                    {step.state === "completed" ? (
                      <Ionicons name="checkmark" size={10} color="#fff" />
                    ) : step.state === "in_progress" ? (
                      <View style={styles.tlPulse} />
                    ) : null}
                  </View>
                  {!isLast ? <View style={[styles.tlLine, { backgroundColor: lineBg }]} /> : null}
                </View>
                <View style={{ flex: 1, paddingBottom: isLast ? 0 : 10 }}>
                  <Text style={[
                    styles.tlLabel,
                    step.state === "in_progress" && { color: theme.color.brand, fontWeight: "800" },
                    step.state === "pending" && { color: theme.color.textMuted },
                  ]}>{step.label}</Text>
                  {step.state === "in_progress" ? (
                    <Text style={styles.tlHint}>In progress</Text>
                  ) : null}
                </View>
              </View>
            );
          })}
        </View>
      ) : null}

      {/* CTAs */}
      <View style={styles.ctaRow}>
        {ps === "roster_needs_client_review" ? (
          <Pressable
            testID="ps-cta-review-roster"
            onPress={() => router.push("/roster/manage" as any)}
            style={styles.ctaPrimary}
          >
            <Ionicons name="checkmark-done" size={14} color="#fff" />
            <Text style={styles.ctaPrimaryT}>REVIEW YOUR ROSTER</Text>
          </Pressable>
        ) : null}
        {(ps === "waiting_for_programme_approval" ||
          ps === "roster_needs_coach_review" ||
          ps === "programme_needs_update") ? (
          <Pressable
            testID="ps-cta-message-louis"
            onPress={() => router.push("/(client)/messages" as any)}
            style={styles.ctaSecondary}
          >
            <Ionicons name="chatbubble-ellipses" size={14} color={theme.color.brand} />
            <Text style={styles.ctaSecondaryT}>MESSAGE LOUIS</Text>
          </Pressable>
        ) : null}
        {ps === "roster_parsing" ? (
          <Pressable
            testID="ps-cta-see-progress"
            onPress={() => router.push("/roster-upload" as any)}
            style={styles.ctaSecondary}
          >
            <Ionicons name="pulse" size={14} color={theme.color.brand} />
            <Text style={styles.ctaSecondaryT}>SEE PROGRESS</Text>
          </Pressable>
        ) : null}
        {/* No workout to open on non-training days — offer the calendar. */}
        {ps === "programme_live" && todayCopy ? (
          <Pressable
            testID="ps-cta-open-calendar"
            onPress={() => router.push("/(client)/calendar" as any)}
            style={styles.ctaSecondary}
          >
            <Ionicons name="calendar" size={14} color={theme.color.brand} />
            <Text style={styles.ctaSecondaryT}>SEE UPCOMING</Text>
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    padding: 16,
    // Iter 162 · Premium V2 · larger radius, neutral surface + border.
    borderRadius: theme.radius.card,
    marginBottom: 0,
    backgroundColor: theme.color.surface2,
    borderWidth: 1,
    borderColor: theme.color.border,
  },
  headline: {
    flexDirection: "row",
    gap: 14,
    alignItems: "flex-start",
  },
  headIconWrap: {
    width: 40, height: 40, borderRadius: 20,
    backgroundColor: theme.color.surface,
    borderWidth: 1, borderColor: theme.color.border,
    alignItems: "center", justifyContent: "center",
  },
  eyebrow: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2, marginBottom: 4 },
  title: { color: theme.color.text, fontSize: 16, fontWeight: "800", letterSpacing: -0.2, marginBottom: 6 },
  body: { color: theme.color.text, fontSize: 12, lineHeight: 17 },

  todayRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 12,
    padding: 12,
    borderRadius: 10,
    backgroundColor: theme.color.surface,
    borderWidth: 1,
    borderColor: theme.color.border,
  },
  todayIconWrap: {
    width: 32, height: 32, borderRadius: 16,
    backgroundColor: theme.color.brandTint,
    borderWidth: 1, borderColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
  },
  todayEyebrow: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5, marginBottom: 3 },
  todayTitle: { color: theme.color.text, fontSize: 14, fontWeight: "800", marginBottom: 4 },
  todayBody: { color: theme.color.textMuted, fontSize: 12, lineHeight: 16 },

  timelineWrap: {
    marginTop: 14,
    paddingTop: 14,
    borderTopWidth: 1,
    borderTopColor: theme.color.border,
  },
  tlRow: { flexDirection: "row", gap: 12 },
  tlDotCol: { alignItems: "center", width: 18 },
  tlDot: {
    width: 18, height: 18, borderRadius: 9,
    borderWidth: 1,
    alignItems: "center", justifyContent: "center",
  },
  tlPulse: { width: 6, height: 6, borderRadius: 3, backgroundColor: theme.color.brand },
  tlLine: { width: 2, flex: 1, marginTop: 2, minHeight: 12 },
  tlLabel: { color: theme.color.text, fontSize: 12, fontWeight: "700" },
  tlHint: { color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 1, marginTop: 2 },

  ctaRow: { flexDirection: "row", gap: 8, marginTop: 14, flexWrap: "wrap" },
  ctaPrimary: {
    flex: 1,
    minWidth: 140,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 12,
    borderRadius: 10,
    backgroundColor: theme.color.brand,
  },
  ctaPrimaryT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  ctaSecondary: {
    flex: 1,
    minWidth: 140,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 12,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: theme.color.brand,
    backgroundColor: theme.color.surface,
  },
  ctaSecondaryT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
});

export default ProgrammeStatusCard;
