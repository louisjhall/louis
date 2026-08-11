/**
 * V2ClientTabs — Non-Plan tab bodies for the V2 Coach Workspace.
 *
 * Priority: bring Check-ins / Messages / Progress / History / Goals INTO
 * the V2 workspace so the coach never has to bounce back to the V1
 * client page for context.
 *
 * Data sources (all existing endpoints, no new backend):
 *   Check-ins: /coach/clients/{id}   → { checkins }
 *   Messages:  /messages/{cid}       (list) + POST /messages (send)
 *   Progress:  /coach/clients/{id}   → { client.progression_pill }
 *              /coach/clients/{id}/programme-overview (adherence + PRs)
 *   History:   /coach/clients/{id}/programme/history → { programmes }
 *   Goals:     /coach/clients/{id}   → { client, event }
 *
 * Guardrails: no AI/bot/generated wording. Coach-only surface, so
 * "coach note" copy is fine.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, ScrollView, StyleSheet, ActivityIndicator, Pressable, TextInput,
} from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { confirm, toast } from "@/src/lib/ux";

/* -------------------------------------------------------- CHECKINS HELPERS */

// Iter170 · Score keys treated as numeric scale values (drawn as Metric).
// Anything NOT in this list is rendered as a text/choice "Note" in the card.
const SCALE_KEYS = new Set([
  "energy", "sleep", "stress", "recovery",
  // legacy daily-checkin field names
  "sleep_hours", "soreness", "mood",
]);

// Iter170 · Human labels for known text/choice answers. Falls back to
// key.replace(/_/g, " ") when a label is not in this map.
const ANSWER_LABELS: Record<string, string> = {
  overall: "Overall week",
  pain: "Pain / injury",
  pain_where: "Pain — where",
  pain_worse: "Pain — worse with",
  nutrition: "Nutrition consistency",
  biggest_win: "Biggest win",
  biggest_challenge: "Biggest challenge",
  for_louis: "For Louis",
  run_long_done: "Long run",
  run_mileage_feel: "Weekly mileage feel",
  run_pacing: "Pacing",
  legs_ready: "Legs ready for next key session",
  run_niggles: "Running niggles",
  shoe_check: "Running shoes",
  weight_trend: "Weight trend",
  hunger: "Hunger",
  protein: "Protein consistency",
  food_env: "Food environments",
  adjust_cals: "Calorie adjustment",
  strength_trend: "Strength trend",
  prs_hit: "PRs / top sets",
  exercise_difficulty: "Exercise difficulty",
  appetite: "Appetite",
  protein_hit: "Protein target",
  swim_consistency: "Swim consistency",
  bike_consistency: "Bike consistency",
  run_consistency: "Run consistency",
  biggest_limiter: "Biggest limiter",
  activity_days: "Active days",
  movement_notes: "Movement notes",
  flying_impact: "Flying impact",
  jetlag: "Jet-lag",
  post_duty_sleep: "Post-duty sleep",
  layover_gym: "Layover / hotel gym",
};

// Iter170 · Derive the display scale max dynamically from the score values.
// The weekly schema uses 1–5 but historical rows or free-text scales may go
// to 10, which caused the "7/5" bug. If ANY score exceeds 5, treat the row
// as a 10-point scale.
function deriveScaleMax(...values: any[]): number {
  let maxSeen = 0;
  for (const v of values) {
    const n = typeof v === "number" ? v : Number(v);
    if (Number.isFinite(n) && n > maxSeen) maxSeen = n;
  }
  return maxSeen > 5 ? 10 : 5;
}

// Iter170 · Grab a scale value with graceful fallbacks:
// weekly-schema top-level → nested `answers.<key>` → legacy daily field.
function pickScore(c: any, ...keys: string[]): number | undefined {
  for (const k of keys) {
    const top = c?.[k];
    if (top != null && top !== "") return Number(top);
    const nested = c?.answers?.[k];
    if (nested != null && nested !== "") return Number(nested);
  }
  return undefined;
}

// Iter170 · Return a de-duplicated list of {key, label, value} entries for
// every text/choice answer in the check-in — INCLUDING the free-text
// `notes` field and the AI-generated `next_week_focus` blurb.
function collectNotes(c: any): { key: string; label: string; value: string }[] {
  const out: { key: string; label: string; value: string }[] = [];
  const answers = c?.answers && typeof c.answers === "object" ? c.answers : {};
  for (const [k, v] of Object.entries(answers)) {
    if (SCALE_KEYS.has(k)) continue;                                // numeric — shown as Metric
    if (v == null) continue;
    const s = String(v).trim();
    if (!s) continue;
    out.push({ key: k, label: ANSWER_LABELS[k] || k.replace(/_/g, " "), value: s });
  }
  if (c?.notes && String(c.notes).trim()) {
    out.push({ key: "notes", label: "Notes", value: String(c.notes).trim() });
  }
  if (c?.next_week_focus && String(c.next_week_focus).trim()) {
    out.push({ key: "next_week_focus", label: "Next-week focus", value: String(c.next_week_focus).trim() });
  }
  return out;
}

export type V2Tab = "plan" | "checkins" | "messages" | "progress" | "history" | "summary" | "goals" | "habits";

export function V2ClientTabs({ clientId, tab }: { clientId: string; tab: V2Tab }) {
  if (tab === "checkins") return <CheckinsPanel clientId={clientId} />;
  if (tab === "messages") return <MessagesPanel clientId={clientId} />;
  if (tab === "progress") return <ProgressPanel clientId={clientId} />;
  if (tab === "history")  return <HistoryPanel  clientId={clientId} />;
  if (tab === "summary" || tab === "goals") return <SummaryPanel clientId={clientId} />;
  if (tab === "habits")   return <HabitsPanel   clientId={clientId} />;
  return null;
}

/* -------------------------------------------------------------- CHECK-INS */

function CheckinsPanel({ clientId }: { clientId: string }) {
  const router = useRouter();
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const detail = await api<any>(`/coach/clients/${clientId}`);
      setRows(detail?.checkins || []);
    } catch (e: any) { setErr(e?.message || String(e)); }
    finally { setLoading(false); }
  }, [clientId]);
  useEffect(() => { load(); }, [load]);

  if (loading) return <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>;
  if (err)     return <View style={styles.center}><Text style={styles.err}>{err}</Text></View>;
  if (!rows.length) return (
    <View style={styles.center}>
      <Ionicons name="heart-outline" size={32} color={theme.color.textDim} />
      <Text style={styles.emptyTitle}>No check-ins yet</Text>
      <Text style={styles.emptyBody}>{"The client hasn't submitted a wellness check-in. They'll appear here as they land."}</Text>
    </View>
  );

  return (
    <ScrollView contentContainerStyle={styles.body} testID="v2-checkins-panel">
      <Text style={styles.sectionTitle}>WEEKLY CHECK-INS · {rows.length}</Text>
      {rows.map((c, i) => {
        // Iter170 · Pull scores with layered fallbacks (top-level weekly
        // fields → nested answers → legacy daily fields) and derive the
        // scale max dynamically so old 1–10 data doesn't render as "7/5".
        const energy   = pickScore(c, "energy_score",   "energy");
        const sleep    = pickScore(c, "sleep_score",    "sleep", "sleep_hours");
        const stress   = pickScore(c, "stress_score",   "stress");
        const recovery = pickScore(c, "recovery_score", "recovery", "soreness");
        const maxScale = deriveScaleMax(energy, sleep, stress, recovery);
        const notes    = collectNotes(c);
        const hasReview = !!c.reviewed_at;
        return (
          <Pressable
            key={c.id || i}
            onPress={() => c.id && router.push(`/coach/checkin/${c.id}` as any)}
            style={({ pressed }) => [styles.card, pressed && { opacity: 0.7 }]}
            testID={`checkin-card-${i}`}
          >
            <View style={styles.cardHead}>
              {/* Iter169 · Prefer submitted_at (weekly schema) but fall back to
                  created_at so any legacy daily rows still render. */}
              <Text style={styles.cardHeadText}>{fmtDateTime(c.submitted_at || c.created_at)}</Text>
              <View style={{ flex: 1 }} />
              {c.coach_review_required && !hasReview && (
                <View style={styles.badge}><Text style={styles.badgeText}>REVIEW</Text></View>
              )}
              <Ionicons name="chevron-forward" size={16} color={theme.color.textDim} style={{ marginLeft: 6 }} />
            </View>
            <View style={styles.metricRow}>
              {/* Iter170 · Scores with fallbacks + dynamic scale max. */}
              <Metric label="Energy"   n={energy}   max={maxScale} />
              <Metric label="Sleep"    n={sleep}    max={maxScale} />
              <Metric label="Stress"   n={stress}   max={maxScale} />
              <Metric label="Recovery" n={recovery} max={maxScale} />
            </View>
            {/* Iter170 · Show every text/choice answer from `answers`, plus
                any `notes` field and the AI `next_week_focus`. */}
            {notes.length > 0 && (
              <View style={styles.notesBlock}>
                {notes.map((n) => (
                  <View key={n.key} style={styles.noteRow}>
                    <Text style={styles.noteLabel}>{n.label.toUpperCase()}</Text>
                    <Text style={styles.noteValue}>{n.value}</Text>
                  </View>
                ))}
              </View>
            )}
            {c.injury_flag && c.injury_flag !== "none" && (
              <View style={styles.injuryBadge}>
                <Ionicons name="warning" size={12} color="#ff6b6b" />
                <Text style={styles.injuryText}>Injury: {c.injury_flag}</Text>
              </View>
            )}
            <View style={styles.openReviewHint}>
              <Ionicons name="sparkles" size={11} color={theme.color.brand} />
              <Text style={styles.openReviewHintT}>TAP TO REVIEW · GENERATE SCRIPT · RECORD VIDEO</Text>
            </View>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

function Metric({ label, n, max, decimals }: { label: string; n?: number; max?: number; decimals?: number }) {
  if (n == null) return null;
  const v = decimals != null ? n.toFixed(decimals) : n;
  return (
    <View style={styles.metric}>
      <Text style={styles.metricN}>{v}{max != null ? <Text style={styles.metricMax}>/{max}</Text> : null}</Text>
      <Text style={styles.metricLabel}>{label}</Text>
    </View>
  );
}

/* --------------------------------------------------------------- MESSAGES */

function MessagesPanel({ clientId }: { clientId: string }) {
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const scrollRef = React.useRef<ScrollView>(null);

  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const res = await api<any>(`/messages/${clientId}`);
      setRows(Array.isArray(res) ? res : (res?.messages || []));
      setTimeout(() => scrollRef.current?.scrollToEnd({ animated: false }), 100);
    } catch (e: any) { setErr(e?.message || String(e)); }
    finally { setLoading(false); }
  }, [clientId]);
  useEffect(() => { load(); }, [load]);

  const send = useCallback(async () => {
    const txt = draft.trim();
    if (!txt) return;
    setSending(true);
    try {
      await api(`/messages`, {
        method: "POST",
        body: { to_user_id: clientId, text: txt },
      });
      setDraft("");
      await load();
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setSending(false);
    }
  }, [clientId, draft, load]);

  if (loading) return <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>;
  return (
    <View style={{ flex: 1 }} testID="v2-messages-panel">
      {err && <Text style={[styles.err, { padding: 12 }]}>{err}</Text>}
      <ScrollView ref={scrollRef} style={{ flex: 1 }} contentContainerStyle={styles.body}>
        {rows.length === 0 ? (
          <View style={styles.center}>
            <Ionicons name="chatbubble-ellipses-outline" size={32} color={theme.color.textDim} />
            <Text style={styles.emptyTitle}>No messages yet</Text>
            <Text style={styles.emptyBody}>Start the conversation below.</Text>
          </View>
        ) : rows.map((m: any, i: number) => (
          <MessageBubble key={m.id || i} m={m} coachId={m.from_user_id === clientId ? undefined : m.from_user_id} />
        ))}
      </ScrollView>
      <View style={styles.chatBar}>
        <TextInput
          style={styles.chatInput}
          value={draft}
          onChangeText={setDraft}
          placeholder="Send a message to your client…"
          placeholderTextColor={theme.color.textDim}
          multiline
          testID="v2-message-input"
        />
        <Pressable
          style={[styles.sendBtn, (!draft.trim() || sending) && { opacity: 0.5 }]}
          onPress={send}
          disabled={!draft.trim() || sending}
          testID="v2-message-send"
        >
          <Ionicons name="send" size={16} color="#000" />
        </Pressable>
      </View>
    </View>
  );
}

function MessageBubble({ m, coachId }: { m: any; coachId?: string }) {
  const fromCoach = !!coachId && m.from_user_id === coachId;
  return (
    <View style={[styles.bubble, fromCoach ? styles.bubbleCoach : styles.bubbleClient]}>
      <Text style={[styles.bubbleTxt, fromCoach && { color: "#000" }]}>{m.text || ""}</Text>
      <Text style={[styles.bubbleTime, fromCoach && { color: "#000000cc" }]}>{fmtDateTime(m.created_at)}</Text>
    </View>
  );
}

/* --------------------------------------------------------------- PROGRESS */

function ProgressPanel({ clientId }: { clientId: string }) {
  const [detail, setDetail] = useState<any>(null);
  const [overview, setOverview] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const [d, ov] = await Promise.all([
        api<any>(`/coach/clients/${clientId}`),
        api<any>(`/coach/clients/${clientId}/programme-overview`).catch(() => null),
      ]);
      setDetail(d);
      setOverview(ov);
    } catch (e: any) { setErr(e?.message || String(e)); }
    finally { setLoading(false); }
  }, [clientId]);
  useEffect(() => { load(); }, [load]);

  if (loading) return <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>;
  if (err)     return <View style={styles.center}><Text style={styles.err}>{err}</Text></View>;

  const pill = detail?.client?.progression_pill;
  const workouts: any[] = detail?.workouts || [];
  const completed = workouts.filter(w => w.completed).length;
  const total = workouts.length;
  const adherence = total ? Math.round((completed / total) * 100) : 0;

  return (
    <ScrollView contentContainerStyle={styles.body} testID="v2-progress-panel">
      {/* Progression pill */}
      {pill?.status ? (
        <View style={[styles.card, pillTintStyle(pill.status)]}>
          <Text style={styles.pillStatus}>{pill.status_label || humanise(pill.status)}</Text>
          {pill.reason && <Text style={styles.pillReason}>{pill.reason}</Text>}
          {pill.coach_note && <Text style={styles.notes}>{pill.coach_note}</Text>}
          {pill.week_key && <Text style={styles.metricLabel}>Week {pill.week_key}</Text>}
        </View>
      ) : (
        <View style={styles.card}>
          <Text style={styles.notes}>No weekly progression snapshot yet.</Text>
        </View>
      )}

      {/* Adherence */}
      <View style={styles.card}>
        <Text style={styles.sectionTitle}>ADHERENCE</Text>
        <View style={styles.metricRow}>
          <Metric label="Completed" n={completed} />
          <Metric label="Total"     n={total} />
          <Metric label="%"         n={adherence} />
        </View>
        <View style={styles.progressTrack}>
          <View style={[styles.progressFill, { width: `${adherence}%` }]} />
        </View>
      </View>

      {/* Programme overview */}
      {overview?.milestones?.length ? (
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>MILESTONES</Text>
          {overview.milestones.slice(0, 8).map((ms: any, i: number) => (
            <View key={i} style={styles.milestone}>
              <View style={[styles.milestoneDot, ms.reached && { backgroundColor: theme.color.brand }]} />
              <Text style={styles.milestoneText}>{ms.label || ms.title}</Text>
              {ms.date && <Text style={styles.milestoneDate}>{ms.date}</Text>}
            </View>
          ))}
        </View>
      ) : null}
    </ScrollView>
  );
}

function pillTintStyle(status: string) {
  const tint = {
    progressing_well: "#193b25",
    on_track:         "#193b25",
    reduce_load:      "#3b2d0d",
    off_track:        "#3b1414",
  }[status] || "#00000030";
  return { backgroundColor: tint, borderLeftWidth: 3, borderLeftColor: theme.color.brand };
}

/* --------------------------------------------------------------- HISTORY */

function HistoryPanel({ clientId }: { clientId: string }) {
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const res = await api<any>(`/coach/clients/${clientId}/programme/history`);
      setRows(res?.programmes || []);
    } catch (e: any) { setErr(e?.message || String(e)); }
    finally { setLoading(false); }
  }, [clientId]);
  useEffect(() => { load(); }, [load]);

  if (loading) return <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>;
  if (err)     return <View style={styles.center}><Text style={styles.err}>{err}</Text></View>;
  if (!rows.length) return (
    <View style={styles.center}>
      <Ionicons name="time-outline" size={32} color={theme.color.textDim} />
      <Text style={styles.emptyTitle}>No programme history</Text>
      <Text style={styles.emptyBody}>{"This client's programme history will appear here as it evolves."}</Text>
    </View>
  );

  return (
    <ScrollView contentContainerStyle={styles.body} testID="v2-history-panel">
      <Text style={styles.sectionTitle}>PROGRAMME HISTORY · {rows.length}</Text>
      {rows.map((p: any, i: number) => (
        <View key={p.id || i} style={styles.card}>
          <View style={styles.cardHead}>
            <Text style={styles.cardHeadText}>{p.title || p.primary_goal || "Programme"}</Text>
            <View style={styles.badge}>
              <Text style={styles.badgeText}>{(p.status || "archived").toUpperCase()}</Text>
            </View>
          </View>
          <Text style={styles.notes}>
            {p.start_date || "?"}  →  {p.end_date || "?"}
            {typeof p.duration_weeks === "number" ? ` · ${p.duration_weeks}w` : ""}
          </Text>
          {p.summary && <Text style={styles.notes}>{p.summary}</Text>}
          {typeof p.completion_rate === "number" && (
            <View style={styles.progressTrack}>
              <View style={[styles.progressFill, { width: `${Math.min(100, Math.round(p.completion_rate * 100))}%` }]} />
            </View>
          )}
        </View>
      ))}
    </ScrollView>
  );
}

/* ---------------------------------------------------------------- SUMMARY */
/* Detailed Client Summary — replaces the old Goals tab.
 * Data source: GET /coach/clients/{cid}/summary (aggregate) +
 *              POST /coach/clients/{cid}/summary/briefing (LLM narrative,
 *              cached server-side; button forces refresh).
 */

function SummaryPanel({ clientId }: { clientId: string }) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const [briefing, setBriefing] = useState<string | null>(null);
  const [briefingMeta, setBriefingMeta] = useState<any>(null);
  const [briefingLoading, setBriefingLoading] = useState(false);
  const [briefingErr, setBriefingErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const d = await api<any>(`/coach/clients/${clientId}/summary`);
      setData(d);
    } catch (e: any) { setErr(e?.message || String(e)); }
    finally { setLoading(false); }
  }, [clientId]);
  useEffect(() => { load(); }, [load]);

  const loadBriefing = useCallback(async (refresh: boolean) => {
    setBriefingLoading(true); setBriefingErr(null);
    try {
      const r = await api<any>(
        `/coach/clients/${clientId}/summary/briefing${refresh ? "?refresh=true" : ""}`,
        { method: "POST" },
      );
      setBriefing(r?.briefing || null);
      setBriefingMeta({ from_cache: r?.from_cache, generated_at: r?.generated_at });
    } catch (e: any) {
      setBriefingErr(e?.message || String(e));
    } finally { setBriefingLoading(false); }
  }, [clientId]);
  // Load cached briefing on first mount (cheap: server returns cache when signature unchanged)
  useEffect(() => { loadBriefing(false); }, [loadBriefing]);

  if (loading) return <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>;
  if (err)     return <View style={styles.center}><Text style={styles.err}>{err}</Text></View>;
  if (!data)   return <View style={styles.center}><Text style={styles.err}>No client data.</Text></View>;

  const c = data.client || {};
  const p = c.profile || {};
  const ev = data.event;
  const ad = data.adherence || {};
  const prog = c.progression_pill;
  const hb = data.habits || {};
  const dir = data.directives || [];
  const ck = data.checkins || [];

  const goalRaw =
    p.main_goal || p.primary_goal_id || p.primary_goal ||
    p.goal || p.event_type_pref || ev?.event_type || null;
  const goalLabel = goalRaw ? humanise(String(goalRaw)) : null;

  const identity = [
    p.age ? `${p.age} yr` : null,
    (p.sex || p.biological_sex) ? humanise(String(p.sex || p.biological_sex)) : null,
    p.height_cm ? `${p.height_cm} cm` : null,
    p.weight_kg ? `${p.weight_kg} kg` : null,
  ].filter(Boolean).join(" · ");

  return (
    <ScrollView contentContainerStyle={styles.body} testID="v2-summary-panel">
      {/* Identity header */}
      <View style={styles.card}>
        <View style={styles.cardHead}>
          <Text style={styles.cardHeadText}>{c.name || "Client"}</Text>
          {c.is_active === false ? (
            <View style={[styles.badge, { backgroundColor: "#ff6b6b" }]}>
              <Text style={styles.badgeText}>ARCHIVED</Text>
            </View>
          ) : null}
        </View>
        {c.email && <Text style={styles.notes}>{c.email}</Text>}
        {!!identity && <Text style={styles.notes}>{identity}</Text>}
        <View style={{ flexDirection: "row", gap: 12, marginTop: 6, flexWrap: "wrap" }}>
          {c.created_at && <Text style={styles.metricLabel}>Joined {fmtDate(c.created_at)}</Text>}
          {p.setup_completed_at && <Text style={styles.metricLabel}>Onboarded {fmtDate(p.setup_completed_at)}</Text>}
          {c.last_login_at && <Text style={styles.metricLabel}>Last seen {fmtDate(c.last_login_at)}</Text>}
        </View>
      </View>

      {/* COACH BRIEFING (LLM narrative) */}
      <View style={styles.card}>
        <View style={styles.cardHead}>
          <Text style={styles.cardHeadText}>COACH BRIEFING</Text>
          <Pressable
            style={styles.smallBtn}
            onPress={() => loadBriefing(true)}
            disabled={briefingLoading}
            testID="regenerate-briefing"
          >
            <Ionicons name="refresh-outline" size={12} color={theme.color.textHi} />
            <Text style={styles.smallBtnText}>
              {briefingLoading ? "…" : "Regenerate"}
            </Text>
          </Pressable>
        </View>
        {briefingLoading && !briefing ? (
          <ActivityIndicator color={theme.color.brand} style={{ marginTop: 8 }} />
        ) : briefingErr ? (
          <Text style={styles.err}>{briefingErr}</Text>
        ) : briefing ? (
          <>
            <Text style={styles.briefingText}>{briefing}</Text>
            {briefingMeta && (
              <Text style={styles.metricLabel}>
                {briefingMeta.from_cache ? "Cached" : "Freshly generated"}
                {briefingMeta.generated_at ? ` · ${fmtDate(briefingMeta.generated_at)}` : ""}
              </Text>
            )}
          </>
        ) : (
          <Text style={styles.notes}>Generating…</Text>
        )}
      </View>

      {/* PRIMARY GOAL */}
      <View style={styles.card}>
        <Text style={styles.sectionTitle}>PRIMARY GOAL</Text>
        {goalLabel ? (
          <Text style={styles.pillStatus}>{goalLabel}</Text>
        ) : (
          <Text style={styles.notes}>No primary goal captured in DNA yet.</Text>
        )}
        {(p.goal_notes || p.main_goal_notes) && (
          <Text style={styles.notes}>{p.goal_notes || p.main_goal_notes}</Text>
        )}
        {!!_toList(p.secondary_goals || p.secondary_goal_ids).length && (
          <Text style={styles.notes}>
            Secondary: {_toList(p.secondary_goals || p.secondary_goal_ids).map(humanise).join(", ")}
          </Text>
        )}
      </View>

      {/* TARGET EVENT */}
      {ev ? (
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>TARGET EVENT</Text>
          <Text style={styles.pillStatus}>
            {humanise(ev.event_type || ev.title || ev.name || "Event")}
          </Text>
          <Text style={styles.notes}>
            {ev.event_date || "?"}
            {ev.phase_info?.phase ? ` · ${humanise(ev.phase_info.phase)}` : ""}
            {typeof ev.phase_info?.weeks_out === "number" ? ` · ${ev.phase_info.weeks_out}w out` : ""}
            {ev.priority ? ` · Priority ${ev.priority}` : ""}
          </Text>
          {ev.distance && <Text style={styles.notes}>Distance: {ev.distance}</Text>}
          {ev.notes && <Text style={styles.notes}>{ev.notes}</Text>}
        </View>
      ) : null}

      {/* TRAINING DNA */}
      <View style={styles.card}>
        <Text style={styles.sectionTitle}>TRAINING DNA</Text>
        <DnaRow label="Days / week" val={p.training_days_per_week || p.days_per_week || _toList(p.training_days).length || null} />
        <DnaRow label="Session length" val={p.preferred_session_length || p.max_home_minutes} />
        <DnaRow label="Progression" val={p.progression_speed} />
        <DnaRow label="Experience" val={p.experience_level} />
        <DnaRow label="Preferred times" val={_toList(p.preferred_times).join(", ")} />
        <DnaRow label="Warmup style" val={p.warmup_style} />
      </View>

      {/* AVIATION / ROSTER PATTERN */}
      <View style={styles.card}>
        <Text style={styles.sectionTitle}>AVIATION & ROSTER</Text>
        <DnaRow label="Role" val={p.job_title || p.crew_role} />
        <DnaRow label="Airline" val={p.airline} />
        <DnaRow label="Home base" val={p.home_base} />
        <DnaRow label="Flying type" val={p.flying_type || p.haul_mix} />
        <DnaRow label="Route focus" val={p.route_focus} />
        <DnaRow label="Aircraft" val={p.aircraft_type} />
        <DnaRow label="Time at home" val={p.time_home_min || p.time_home} />
        <DnaRow label="Layover time" val={p.time_layover_min || p.time_layover} />
        <DnaRow label="Timezone" val={p.timezone} />
        <DnaRow label="Active roster" val={data.roster ? `${data.roster.days} days · exp ${data.roster.expiry || "?"}` : "None"} />
      </View>

      {/* EQUIPMENT */}
      <View style={styles.card}>
        <Text style={styles.sectionTitle}>EQUIPMENT</Text>
        <DnaRow label="Home" val={_toList(p.equipment_home || p.home_equipment || p.equipment).join(", ")} />
        <DnaRow label="Hotel gym reliability" val={p.hotel_gym_reliability || p.hotel_gym_frequency || p.hotel_gyms} />
      </View>

      {/* INJURIES & CONSTRAINTS */}
      {(_toList(p.injuries).length || p.injury_notes ||
        _toList(p.no_go_movements).length || _toList(p.disliked_exercises).length ||
        _toList(p.constraints).length || _toList(p.medical_flags).length) ? (
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>INJURIES & CONSTRAINTS</Text>
          <DnaRow label="Injuries" val={_toList(p.injuries).join(", ")} />
          <DnaRow label="Injury notes" val={p.injury_notes} />
          <DnaRow label="No-go movements" val={_toList(p.no_go_movements).join(", ")} />
          <DnaRow label="Dislikes" val={_toList(p.disliked_exercises).join(", ")} />
          <DnaRow label="Medical" val={_toList(p.medical_flags).join(", ")} />
          <DnaRow label="Constraints" val={_toList(p.constraints).join(", ")} />
        </View>
      ) : null}

      {/* ADHERENCE (last 28 days) */}
      <View style={styles.card}>
        <Text style={styles.sectionTitle}>ADHERENCE · LAST {ad.window_days || 28} DAYS</Text>
        <View style={styles.metricRow}>
          <View style={styles.metric}>
            <Text style={styles.metricN}>{ad.adherence_pct ?? "—"}%</Text>
            <Text style={styles.metricLabel}>completion</Text>
          </View>
          <View style={styles.metric}>
            <Text style={styles.metricN}>{ad.completed ?? 0}</Text>
            <Text style={styles.metricLabel}>completed</Text>
          </View>
          <View style={styles.metric}>
            <Text style={styles.metricN}>{ad.scheduled_past ?? 0}</Text>
            <Text style={styles.metricLabel}>scheduled</Text>
          </View>
          <View style={styles.metric}>
            <Text style={styles.metricN}>{ad.avg_rpe ?? "—"}</Text>
            <Text style={styles.metricLabel}>avg RPE</Text>
          </View>
        </View>
        <View style={{ flexDirection: "row", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
          {Object.entries(ad.load_mix || {}).map(([band, n]: any) => (
            n ? (
              <View key={band} style={[styles.loadPill, { backgroundColor: loadColour(band) + "33", borderColor: loadColour(band) }]}>
                <Text style={[styles.loadPillT, { color: loadColour(band) }]}>{band.toUpperCase()} · {n}</Text>
              </View>
            ) : null
          ))}
        </View>
      </View>

      {/* PROGRESSION PILL */}
      {prog ? (
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>PROGRESSION</Text>
          <Text style={styles.pillStatus}>
            {(prog.status_label || prog.status || "").toUpperCase()}
            {prog.week_key ? `  ·  ${prog.week_key}` : ""}
          </Text>
          {prog.reason && <Text style={styles.notes}>{prog.reason}</Text>}
          {prog.coach_note && <Text style={styles.notes}>Coach note: {prog.coach_note}</Text>}
        </View>
      ) : null}

      {/* RECENT CHECK-INS */}
      {ck.length ? (
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>RECENT CHECK-INS · {ck.length}</Text>
          {ck.slice(0, 3).map((c: any, i: number) => (
            <View key={c.id || i} style={styles.checkinRow}>
              <Text style={styles.metricLabel}>{fmtDate(c.created_at)}</Text>
              <Text style={styles.notes}>
                {c.rpe != null ? `RPE ${c.rpe}` : ""}{c.sleep != null ? ` · Sleep ${c.sleep}` : ""}
                {c.energy != null ? ` · Energy ${c.energy}` : ""}{c.mood ? ` · ${c.mood}` : ""}
              </Text>
              {c.notes && <Text style={styles.notes}>“{c.notes}”</Text>}
            </View>
          ))}
        </View>
      ) : null}

      {/* HABITS */}
      <View style={styles.card}>
        <Text style={styles.sectionTitle}>HABITS</Text>
        <View style={styles.metricRow}>
          <View style={styles.metric}>
            <Text style={styles.metricN}>{hb.active_count ?? 0}</Text>
            <Text style={styles.metricLabel}>active</Text>
          </View>
          <View style={styles.metric}>
            <Text style={styles.metricN}>{hb.paused_count ?? 0}</Text>
            <Text style={styles.metricLabel}>paused</Text>
          </View>
          <View style={styles.metric}>
            <Text style={styles.metricN}>{hb.archived_count ?? 0}</Text>
            <Text style={styles.metricLabel}>archived</Text>
          </View>
        </View>
        {(hb.top || []).map((h: any, i: number) => (
          <View key={h.id || i} style={{ marginTop: 6 }}>
            <Text style={styles.notes}>· {h.title}{h.frequency ? ` — ${h.frequency}` : ""}{h.streak ? `  🔥 ${h.streak}` : ""}</Text>
          </View>
        ))}
      </View>

      {/* COACH DIRECTIVES */}
      {dir.length ? (
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>COACH DIRECTIVES · {dir.length}</Text>
          {dir.slice(-5).reverse().map((d: any, i: number) => (
            <View key={d.id || i} style={{ marginTop: 4 }}>
              <Text style={styles.metricLabel}>
                {d.created_at ? fmtDate(d.created_at) : ""}{d.priority ? ` · ${String(d.priority).toUpperCase()}` : ""}
              </Text>
              <Text style={styles.notes}>{d.text || d.title || ""}</Text>
            </View>
          ))}
        </View>
      ) : null}

      {/* OPEN TASKS */}
      {data.open_coach_tasks ? (
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>OPEN COACH TASKS</Text>
          <Text style={styles.pillStatus}>{data.open_coach_tasks}</Text>
          <Text style={styles.notes}>See the tasks inbox for details.</Text>
        </View>
      ) : null}
    </ScrollView>
  );
}

function fmtDate(iso?: string): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso).slice(0, 10);
    return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  } catch { return String(iso).slice(0, 10); }
}

function loadColour(band: string): string {
  switch ((band || "").toLowerCase()) {
    case "green":  return "#4ade80";
    case "amber":  return "#f5b543";
    case "red":    return "#ff6b6b";
    case "blue":   return "#5aa9e6";
    case "purple": return "#a78bfa";
    default:       return "#8e8e93";
  }
}

/* ---------------------------------------------------------------- GOALS (legacy) */
/* Retained for any deep-link that still passes tab=goals — routed to SummaryPanel. */

function DnaRow({ label, val }: { label: string; val?: any }) {
  if (val == null || val === "" || (Array.isArray(val) && val.length === 0)) return null;
  return (
    <View style={styles.dnaRow}>
      <Text style={styles.dnaLabel}>{label}</Text>
      <Text style={styles.dnaVal} numberOfLines={2}>{String(val)}</Text>
    </View>
  );
}

/* ---------------------------------------------------------------- HABITS */
/* Stage H — Coach control of habits (CRUD).
 * Reuses:
 *   GET    /coach/clients/{cid}/habits
 *   POST   /coach/clients/{cid}/habits
 *   PATCH  /coach/habits/{hid}                     (pause / archive / edit)
 *   DELETE /coach/habits/{hid}?confirm=true
 *   POST   /coach/clients/{cid}/habits/reorder
 */

type HabitRow = {
  id: string; title: string; reason?: string;
  frequency?: string; target?: any; unit?: string;
  habit_type?: string; difficulty_level?: string;
  status?: string; sort_order?: number;
  streak?: number;
};

function HabitsPanel({ clientId }: { clientId: string }) {
  const [active, setActive] = useState<HabitRow[]>([]);
  const [paused, setPaused] = useState<HabitRow[]>([]);
  const [archived, setArchived] = useState<HabitRow[]>([]);
  const [completion, setCompletion] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newReason, setNewReason] = useState("");
  const [savingIds, setSavingIds] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const d = await api<any>(`/coach/clients/${clientId}/habits`);
      setActive(d?.active || []);
      setPaused(d?.paused || []);
      setArchived(d?.archived || []);
      setCompletion(d?.completion || {});
    } catch (e: any) { setErr(e?.message || String(e)); }
    finally { setLoading(false); }
  }, [clientId]);
  useEffect(() => { load(); }, [load]);

  const markSaving = (id: string, on: boolean) => {
    setSavingIds((prev) => {
      const next = new Set(prev);
      if (on) next.add(id); else next.delete(id);
      return next;
    });
  };

  const doCreate = async () => {
    const title = newTitle.trim();
    if (!title) return;
    try {
      await api(`/coach/clients/${clientId}/habits`, {
        method: "POST",
        body: { title, reason: newReason.trim() || undefined, frequency: "daily" },
      });
      setNewTitle(""); setNewReason(""); setAdding(false);
      toast("Habit added", "success");
      await load();
    } catch (e: any) {
      toast(`Couldn't add habit: ${String(e?.message || e)}`, "error");
    }
  };

  const setStatus = async (h: HabitRow, status: "active" | "paused" | "archived") => {
    markSaving(h.id, true);
    try {
      await api(`/coach/habits/${h.id}`, { method: "PATCH", body: { status } });
      await load();
    } catch (e: any) {
      toast(`Couldn't update habit: ${String(e?.message || e)}`, "error");
    } finally {
      markSaving(h.id, false);
    }
  };

  const doDelete = async (h: HabitRow) => {
    // React Native Web does NOT render Alert.alert buttons — use the
    // cross-platform confirm() helper so the destructive action actually
    // fires on preview + web.
    const ok = await confirm({
      title: "Delete habit?",
      message: `"${h.title}" will be permanently deleted along with its logs. This can't be undone.`,
      confirmLabel: "Delete", cancelLabel: "Cancel", destructive: true,
    });
    if (!ok) return;
    markSaving(h.id, true);
    try {
      await api(`/coach/habits/${h.id}?confirm=true`, { method: "DELETE" });
      toast(`Deleted "${h.title}"`, "success");
      await load();
    } catch (e: any) {
      toast(`Delete failed: ${String(e?.message || e)}`, "error");
    } finally {
      markSaving(h.id, false);
    }
  };

  const doRegenerate = async (h: HabitRow) => {
    const ok = await confirm({
      title: "Regenerate this habit?",
      message: `Atlas will suggest a fresh habit for "${h.title}" based on the client's goal. Streak and history are kept.`,
      confirmLabel: "Regenerate", cancelLabel: "Cancel",
    });
    if (!ok) return;
    markSaving(h.id, true);
    try {
      const r = await api<any>(`/coach/habits/${h.id}/regenerate`, { method: "POST" });
      const nt = r?.habit?.title || h.title;
      toast(nt === h.title ? "Regenerated (no change)" : `Now: "${nt}"`, "success");
      await load();
    } catch (e: any) {
      toast(`Regenerate failed: ${String(e?.message || e)}`, "error");
    } finally {
      markSaving(h.id, false);
    }
  };

  const reorder = async (idx: number, dir: -1 | 1) => {
    const next = idx + dir;
    if (next < 0 || next >= active.length) return;
    const ordered = [...active];
    const [item] = ordered.splice(idx, 1);
    ordered.splice(next, 0, item);
    setActive(ordered);   // optimistic
    try {
      await api(`/coach/clients/${clientId}/habits/reorder`, {
        method: "POST",
        body: { habit_ids: ordered.map((h) => h.id) },
      });
    } catch (e: any) {
      toast(`Couldn't reorder: ${String(e?.message || e)}`, "error");
      await load();
    }
  };

  if (loading) return <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>;
  if (err) return <View style={styles.center}><Text style={styles.err}>{err}</Text></View>;

  return (
    <ScrollView contentContainerStyle={styles.body} testID="v2-habits-panel">
      {/* Add new habit */}
      <View style={styles.card}>
        <View style={styles.cardHead}>
          <Text style={styles.cardHeadText}>ADD HABIT</Text>
          <Pressable onPress={() => setAdding((v) => !v)} testID="habit-add-toggle">
            <Ionicons name={adding ? "chevron-up" : "add"} size={18} color={theme.color.brand} />
          </Pressable>
        </View>
        {adding && (
          <View style={{ gap: 8, marginTop: 6 }}>
            <TextInput
              value={newTitle} onChangeText={setNewTitle}
              placeholder="Habit title (e.g. Sleep 7+ hrs)"
              placeholderTextColor={theme.color.textDim}
              style={hStyles.input} testID="habit-add-title"
            />
            <TextInput
              value={newReason} onChangeText={setNewReason}
              placeholder="Why (optional)"
              placeholderTextColor={theme.color.textDim}
              style={hStyles.input} testID="habit-add-reason"
              multiline
            />
            <Pressable
              onPress={doCreate}
              style={[hStyles.primary, !newTitle.trim() && { opacity: 0.4 }]}
              disabled={!newTitle.trim()}
              testID="habit-add-submit"
            >
              <Ionicons name="checkmark" size={14} color="#000" />
              <Text style={hStyles.primaryT}>ADD</Text>
            </Pressable>
          </View>
        )}
      </View>

      {/* Active habits */}
      <Text style={styles.sectionTitle}>ACTIVE · {active.length}</Text>
      {active.length === 0 && (
        <View style={styles.card}>
          <Text style={styles.notes}>No active habits. Tap ADD HABIT to create one.</Text>
        </View>
      )}
      {active.map((h, i) => {
        const c = completion?.[h.id] || {};
        const rate = typeof c.rate === "number" ? Math.round(c.rate * 100) : null;
        const saving = savingIds.has(h.id);
        return (
          <View key={h.id} style={styles.card} testID={`habit-row-${h.id}`}>
            <View style={styles.cardHead}>
              <Text style={styles.cardHeadText} numberOfLines={1}>{h.title}</Text>
              {h.streak && h.streak > 0 && (
                <View style={hStyles.streak}>
                  <Ionicons name="flame" size={10} color="#f5b543" />
                  <Text style={hStyles.streakT}>{h.streak}</Text>
                </View>
              )}
            </View>
            {h.reason && <Text style={styles.notes} numberOfLines={2}>{h.reason}</Text>}
            <View style={hStyles.metaRow}>
              {h.frequency && <Text style={hStyles.meta}>{h.frequency}</Text>}
              {h.target != null && <Text style={hStyles.meta}>· {String(h.target)}{h.unit ? " " + h.unit : ""}</Text>}
              {rate != null && <Text style={hStyles.meta}>· {rate}% 28d</Text>}
            </View>
            <View style={hStyles.actionRow}>
              <Pressable
                onPress={() => reorder(i, -1)}
                disabled={i === 0 || saving}
                style={[hStyles.iconBtn, (i === 0 || saving) && { opacity: 0.3 }]}
                testID={`habit-up-${h.id}`}
              >
                <Ionicons name="chevron-up" size={14} color={theme.color.textHi} />
              </Pressable>
              <Pressable
                onPress={() => reorder(i, 1)}
                disabled={i === active.length - 1 || saving}
                style={[hStyles.iconBtn, (i === active.length - 1 || saving) && { opacity: 0.3 }]}
                testID={`habit-down-${h.id}`}
              >
                <Ionicons name="chevron-down" size={14} color={theme.color.textHi} />
              </Pressable>
              <View style={{ flex: 1 }} />
              <Pressable
                onPress={() => doRegenerate(h)}
                disabled={saving}
                style={hStyles.iconBtn}
                testID={`habit-regen-${h.id}`}
              >
                <Ionicons name="sparkles-outline" size={13} color={theme.color.brand} />
                <Text style={[hStyles.iconBtnT, { color: theme.color.brand }]}>Regenerate</Text>
              </Pressable>
              <Pressable
                onPress={() => setStatus(h, "paused")}
                disabled={saving}
                style={hStyles.iconBtn}
                testID={`habit-pause-${h.id}`}
              >
                <Ionicons name="pause" size={13} color={theme.color.textHi} />
                <Text style={hStyles.iconBtnT}>Pause</Text>
              </Pressable>
              <Pressable
                onPress={() => setStatus(h, "archived")}
                disabled={saving}
                style={hStyles.iconBtn}
                testID={`habit-archive-${h.id}`}
              >
                <Ionicons name="archive-outline" size={13} color={theme.color.textHi} />
                <Text style={hStyles.iconBtnT}>Archive</Text>
              </Pressable>
              <Pressable
                onPress={() => doDelete(h)}
                disabled={saving}
                style={[hStyles.iconBtn, { borderColor: "#ff6b6b" }]}
                testID={`habit-delete-${h.id}`}
              >
                <Ionicons name="trash-outline" size={13} color="#ff6b6b" />
                <Text style={[hStyles.iconBtnT, { color: "#ff6b6b" }]}>Delete</Text>
              </Pressable>
            </View>
          </View>
        );
      })}

      {/* Paused */}
      {paused.length > 0 && (
        <>
          <Text style={[styles.sectionTitle, { marginTop: 16 }]}>PAUSED · {paused.length}</Text>
          {paused.map((h) => (
            <View key={h.id} style={[styles.card, { opacity: 0.7 }]}>
              <Text style={styles.cardHeadText}>{h.title}</Text>
              <View style={hStyles.actionRow}>
                <View style={{ flex: 1 }} />
                <Pressable
                  onPress={() => setStatus(h, "active")}
                  style={hStyles.iconBtn}
                  testID={`habit-resume-${h.id}`}
                >
                  <Ionicons name="play" size={13} color={theme.color.brand} />
                  <Text style={hStyles.iconBtnT}>Resume</Text>
                </Pressable>
                <Pressable
                  onPress={() => doDelete(h)}
                  style={[hStyles.iconBtn, { borderColor: "#ff6b6b" }]}
                  testID={`habit-delete-${h.id}`}
                >
                  <Ionicons name="trash-outline" size={13} color="#ff6b6b" />
                  <Text style={[hStyles.iconBtnT, { color: "#ff6b6b" }]}>Delete</Text>
                </Pressable>
              </View>
            </View>
          ))}
        </>
      )}

      {/* Archived */}
      {archived.length > 0 && (
        <>
          <Text style={[styles.sectionTitle, { marginTop: 16 }]}>ARCHIVED · {archived.length}</Text>
          {archived.map((h) => (
            <View key={h.id} style={[styles.card, { opacity: 0.5 }]}>
              <Text style={styles.cardHeadText}>{h.title}</Text>
              <View style={hStyles.actionRow}>
                <View style={{ flex: 1 }} />
                <Pressable
                  onPress={() => setStatus(h, "active")}
                  style={hStyles.iconBtn}
                  testID={`habit-restore-${h.id}`}
                >
                  <Ionicons name="refresh" size={13} color={theme.color.brand} />
                  <Text style={hStyles.iconBtnT}>Restore</Text>
                </Pressable>
                <Pressable
                  onPress={() => doDelete(h)}
                  style={[hStyles.iconBtn, { borderColor: "#ff6b6b" }]}
                  testID={`habit-delete-${h.id}`}
                >
                  <Ionicons name="trash-outline" size={13} color="#ff6b6b" />
                  <Text style={[hStyles.iconBtnT, { color: "#ff6b6b" }]}>Delete</Text>
                </Pressable>
              </View>
            </View>
          ))}
        </>
      )}
    </ScrollView>
  );
}

const hStyles = StyleSheet.create({
  input: {
    backgroundColor: theme.color.bg, borderWidth: 1, borderColor: theme.color.border,
    borderRadius: 6, paddingHorizontal: 10, paddingVertical: 8,
    color: theme.color.textHi, fontSize: 13, minHeight: 40,
  },
  primary: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, backgroundColor: theme.color.brand,
    paddingVertical: 10, borderRadius: 6,
  },
  primaryT: { color: "#000", fontWeight: "800", letterSpacing: 1.2, fontSize: 11 },
  metaRow: { flexDirection: "row", gap: 6, marginTop: 6, flexWrap: "wrap" },
  meta: { color: theme.color.textDim, fontSize: 11, fontWeight: "600" },
  streak: {
    flexDirection: "row", alignItems: "center", gap: 3,
    paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
    backgroundColor: "#3b2a14", borderWidth: 1, borderColor: "#f5b543",
  },
  streakT: { color: "#f5b543", fontSize: 11, fontWeight: "800" },
  actionRow: {
    flexDirection: "row", alignItems: "center", gap: 6, marginTop: 10,
    flexWrap: "wrap",
  },
  iconBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 8, paddingVertical: 6, borderRadius: 5,
    borderWidth: 1, borderColor: theme.color.border,
    backgroundColor: theme.color.bg,
  },
  iconBtnT: { color: theme.color.textHi, fontSize: 11, fontWeight: "700" },
});

/* ------------------------------------------------------------- utilities */

function fmtDateTime(iso?: string): string {
  if (!iso) return "";
  const dt = new Date(iso);
  if (isNaN(dt.getTime())) return iso;
  return dt.toLocaleString("en-GB", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

function humanise(s: string): string {
  return String(s || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// Defensive normaliser — coerces DNA fields that may be array, string,
// comma-separated string, null, or an object with a `.values` array into
// a flat string array. Prevents "join is not a function" crashes.
function _toList(v: any): string[] {
  if (v == null) return [];
  if (Array.isArray(v)) return v.map(String).filter(Boolean);
  if (typeof v === "string") {
    const t = v.trim();
    if (!t || /^(none|n\/a|no|null)$/i.test(t)) return [];
    return t.split(/[,;]/).map((s) => s.trim()).filter(Boolean);
  }
  if (typeof v === "object") {
    if (Array.isArray((v as any).values)) return (v as any).values.map(String);
    return Object.entries(v).filter(([, x]) => x).map(([k]) => k);
  }
  return [String(v)];
}

/* ---------------------------------------------------------------- STYLES */

const styles = StyleSheet.create({
  body: { padding: 16, paddingBottom: 40 },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24, gap: 6 },
  err: { color: "#ff6666" },
  emptyTitle: { color: theme.color.textHi, fontWeight: "800", fontSize: 15, marginTop: 8 },
  emptyBody: { color: theme.color.textDim, textAlign: "center", maxWidth: 340 },

  sectionTitle: {
    color: theme.color.textDim, fontSize: 11, letterSpacing: 1.5,
    fontWeight: "800", marginBottom: 8,
  },

  card: {
    backgroundColor: theme.color.surface2, borderRadius: 8,
    borderWidth: 1, borderColor: theme.color.border,
    padding: 12, marginBottom: 10,
  },
  cardHead: {
    flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 6,
  },
  cardHeadText: { color: theme.color.textHi, fontWeight: "700", fontSize: 13, flex: 1 },
  badge: {
    backgroundColor: theme.color.brand, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 3,
  },
  badgeText: { color: "#000", fontSize: 11, fontWeight: "800", letterSpacing: 0.5 },
  metricRow: { flexDirection: "row", gap: 12, marginTop: 6, flexWrap: "wrap" },
  metric: { alignItems: "center", minWidth: 60 },
  metricN: { color: theme.color.textHi, fontSize: 20, fontWeight: "800" },
  metricMax: { color: theme.color.textDim, fontSize: 12, fontWeight: "600" },
  metricLabel: { color: theme.color.textDim, fontSize: 11, letterSpacing: 0.5, fontWeight: "700" },
  notes: { color: theme.color.textHi, fontSize: 12, marginTop: 6, lineHeight: 18 },
  // Iter170 · Stacked "notes" block — one row per text/choice answer.
  notesBlock: {
    marginTop: 10, paddingTop: 10,
    borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.color.border,
    gap: 6,
  },
  noteRow: { gap: 2 },
  noteLabel: {
    color: theme.color.textDim, fontSize: 11, fontWeight: "800", letterSpacing: 1,
  },
  noteValue: { color: theme.color.textHi, fontSize: 13, lineHeight: 18 },
  openReviewHint: {
    flexDirection: "row", alignItems: "center", gap: 6, marginTop: 10,
    paddingTop: 8, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.color.border,
  },
  openReviewHintT: {
    color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 1.2,
  },
  injuryBadge: {
    flexDirection: "row", alignItems: "center", gap: 5, marginTop: 8,
    paddingHorizontal: 6, paddingVertical: 3, borderRadius: 4,
    backgroundColor: "#3b1414", borderWidth: 1, borderColor: "#ff6b6b", alignSelf: "flex-start",
  },
  injuryText: { color: "#ff6b6b", fontSize: 11, fontWeight: "800", letterSpacing: 0.5 },

  // Messages
  bubble: {
    maxWidth: "80%", padding: 10, borderRadius: 10, marginBottom: 8,
  },
  bubbleCoach: {
    backgroundColor: theme.color.brand, alignSelf: "flex-end",
  },
  bubbleClient: {
    backgroundColor: theme.color.surface2, alignSelf: "flex-start",
    borderWidth: 1, borderColor: theme.color.border,
  },
  bubbleTxt: { color: theme.color.textHi, fontSize: 13 },
  bubbleTime: { color: theme.color.textDim, fontSize: 11, marginTop: 4 },
  chatBar: {
    flexDirection: "row", alignItems: "flex-end", gap: 8,
    padding: 12, borderTopWidth: 1, borderTopColor: theme.color.border,
    backgroundColor: theme.color.surface2,
  },
  chatInput: {
    flex: 1, backgroundColor: theme.color.bg,
    borderWidth: 1, borderColor: theme.color.border, borderRadius: 6,
    paddingHorizontal: 12, paddingVertical: 8,
    color: theme.color.textHi, fontSize: 13, minHeight: 40, maxHeight: 120,
  },
  sendBtn: {
    backgroundColor: theme.color.brand, width: 40, height: 40, borderRadius: 6,
    alignItems: "center", justifyContent: "center",
  },

  // Progress
  pillStatus: { color: theme.color.textHi, fontSize: 14, fontWeight: "800", marginBottom: 4 },
  pillReason: { color: theme.color.textDim, fontSize: 12 },
  progressTrack: {
    height: 6, backgroundColor: "#00000060", borderRadius: 3, marginTop: 8, overflow: "hidden",
  },
  progressFill: { height: "100%", backgroundColor: theme.color.brand },
  milestone: {
    flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 5,
  },
  milestoneDot: {
    width: 10, height: 10, borderRadius: 5,
    borderWidth: 1, borderColor: theme.color.border, backgroundColor: "transparent",
  },
  milestoneText: { color: theme.color.textHi, fontSize: 12, flex: 1 },
  milestoneDate: { color: theme.color.textDim, fontSize: 11 },

  // Goals
  dnaRow: {
    flexDirection: "row", paddingVertical: 5, gap: 12,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: theme.color.border,
  },
  dnaLabel: { color: theme.color.textDim, fontSize: 11, width: 110 },
  dnaVal: { color: theme.color.textHi, fontSize: 12, flex: 1 },

  // Summary
  smallBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 8, paddingVertical: 4,
    borderRadius: 6, borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.color.border, backgroundColor: "#00000030",
  },
  smallBtnText: { color: theme.color.textHi, fontSize: 11, fontWeight: "700", letterSpacing: 0.4 },
  briefingText: {
    color: theme.color.textHi, fontSize: 13, lineHeight: 20,
    marginTop: 8, fontStyle: "italic",
  },
  loadPill: {
    paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999,
    borderWidth: StyleSheet.hairlineWidth,
  },
  loadPillT: { fontSize: 11, fontWeight: "800", letterSpacing: 0.5 },
  checkinRow: {
    paddingVertical: 6,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: theme.color.border,
  },
});
