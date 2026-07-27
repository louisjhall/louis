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
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

export type V2Tab = "plan" | "checkins" | "messages" | "progress" | "history" | "goals";

export function V2ClientTabs({ clientId, tab }: { clientId: string; tab: V2Tab }) {
  if (tab === "checkins") return <CheckinsPanel clientId={clientId} />;
  if (tab === "messages") return <MessagesPanel clientId={clientId} />;
  if (tab === "progress") return <ProgressPanel clientId={clientId} />;
  if (tab === "history")  return <HistoryPanel  clientId={clientId} />;
  if (tab === "goals")    return <GoalsPanel    clientId={clientId} />;
  return null;
}

/* -------------------------------------------------------------- CHECK-INS */

function CheckinsPanel({ clientId }: { clientId: string }) {
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
      <Text style={styles.sectionTitle}>WELLNESS CHECK-INS · {rows.length}</Text>
      {rows.map((c, i) => (
        <View key={c.id || i} style={styles.card}>
          <View style={styles.cardHead}>
            <Text style={styles.cardHeadText}>{fmtDateTime(c.created_at || c.submitted_at)}</Text>
            {c.coach_review_required && !c.reviewed_at && (
              <View style={styles.badge}><Text style={styles.badgeText}>REVIEW</Text></View>
            )}
          </View>
          <View style={styles.metricRow}>
            <Metric label="Energy"   n={c.energy}   max={5} />
            <Metric label="Recovery" n={c.recovery_score ?? c.recovery} max={5} />
            <Metric label="Mood"     n={c.mood} max={5} />
            <Metric label="Sleep h"  n={c.sleep_hours} max={12} decimals={1} />
          </View>
          {c.notes && <Text style={styles.notes} numberOfLines={3}>{c.notes}</Text>}
          {c.injury_flag && c.injury_flag !== "none" && (
            <View style={styles.injuryBadge}>
              <Ionicons name="warning" size={12} color="#ff6b6b" />
              <Text style={styles.injuryText}>Injury: {c.injury_flag}</Text>
            </View>
          )}
        </View>
      ))}
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

/* ---------------------------------------------------------------- GOALS */

function GoalsPanel({ clientId }: { clientId: string }) {
  const [detail, setDetail] = useState<any>(null);
  const [dna, setDna] = useState<any>(null);
  const [event, setEvent] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      // Coach client detail (profile snapshot) + explicit DNA/events endpoints.
      // Everything the Goals panel shows must come from the client's DNA —
      // NOT from a coach-set V2 override.
      const [d, ev] = await Promise.all([
        api<any>(`/coach/clients/${clientId}`),
        api<any>(`/coach/clients/${clientId}/event`).catch(() => null),
      ]);
      setDetail(d);
      // The DNA record itself (assessments answers or dedicated dna doc)
      // — profile is a projection; assessments hold the raw source of truth.
      setDna(d?.client?.profile || {});
      setEvent(ev?.event || d?.event || null);
    } catch (e: any) { setErr(e?.message || String(e)); }
    finally { setLoading(false); }
  }, [clientId]);
  useEffect(() => { load(); }, [load]);

  if (loading) return <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>;
  if (err)     return <View style={styles.center}><Text style={styles.err}>{err}</Text></View>;

  const profile = dna || {};

  // Resolve the primary goal from DNA — same precedence as the V2 kickoff
  // engine: profile.main_goal → profile.primary_goal_id → profile.primary_goal
  // → profile.goal → profile.event_type_pref → event.event_type
  const goalRaw =
    profile.main_goal ||
    profile.primary_goal_id ||
    profile.primary_goal ||
    profile.goal ||
    profile.event_type_pref ||
    event?.event_type ||
    null;
  const goalLabel = goalRaw ? humanise(String(goalRaw)) : null;
  const goalNotes = profile.goal_notes || profile.main_goal_notes || detail?.client?.goal_notes;

  return (
    <ScrollView contentContainerStyle={styles.body} testID="v2-goals-panel">
      <View style={styles.card}>
        <Text style={styles.sectionTitle}>PRIMARY GOAL (FROM DNA)</Text>
        {goalLabel ? (
          <>
            <Text style={styles.pillStatus}>{goalLabel}</Text>
            <Text style={styles.metricLabel}>
              source: {profile.main_goal ? "profile.main_goal" :
                       profile.primary_goal_id ? "profile.primary_goal_id" :
                       profile.primary_goal ? "profile.primary_goal" :
                       profile.event_type_pref ? "profile.event_type_pref" :
                       "events collection"}
            </Text>
          </>
        ) : (
          <Text style={styles.notes}>No primary goal captured in DNA yet. Ask the client to complete onboarding.</Text>
        )}
        {goalNotes && <Text style={styles.notes}>{goalNotes}</Text>}
      </View>

      {event ? (
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>TARGET EVENT (FROM DNA)</Text>
          <Text style={styles.pillStatus}>{humanise(event.event_type || event.title || event.name || "Event")}</Text>
          <Text style={styles.notes}>
            {event.event_date || "?"}
            {event.phase_info?.phase ? ` · ${humanise(event.phase_info.phase)}` : ""}
            {typeof event.phase_info?.weeks_out === "number" ? ` · ${event.phase_info.weeks_out}w out` : ""}
            {event.priority ? ` · Priority ${event.priority}` : ""}
          </Text>
          {event.distance && <Text style={styles.notes}>Distance: {event.distance}</Text>}
          {event.notes && <Text style={styles.notes}>{event.notes}</Text>}
        </View>
      ) : (
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>TARGET EVENT (FROM DNA)</Text>
          <Text style={styles.notes}>No active target event in DNA.</Text>
        </View>
      )}

      {/* DNA fields the coach cares about */}
      <View style={styles.card}>
        <Text style={styles.sectionTitle}>TRAINING DNA</Text>
        <DnaRow label="Progression" val={profile.progression_speed} />
        <DnaRow label="Days / week" val={profile.days_per_week || profile.training_days_per_week} />
        <DnaRow label="Session length" val={profile.preferred_session_length || profile.max_home_minutes} />
        <DnaRow label="Home base" val={profile.home_base} />
        <DnaRow label="Airline" val={profile.airline} />
        <DnaRow label="Equipment" val={_toList(profile.equipment || profile.home_equipment).slice(0, 6).join(", ")} />
        <DnaRow label="Injuries" val={_toList(profile.injuries).join(", ")} />
        <DnaRow label="Constraints" val={_toList(profile.constraints).join(", ")} />
      </View>
    </ScrollView>
  );
}

function DnaRow({ label, val }: { label: string; val?: any }) {
  if (val == null || val === "" || (Array.isArray(val) && val.length === 0)) return null;
  return (
    <View style={styles.dnaRow}>
      <Text style={styles.dnaLabel}>{label}</Text>
      <Text style={styles.dnaVal} numberOfLines={2}>{String(val)}</Text>
    </View>
  );
}

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
    color: theme.color.textDim, fontSize: 10, letterSpacing: 1.5,
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
  badgeText: { color: "#000", fontSize: 9, fontWeight: "800", letterSpacing: 0.5 },
  metricRow: { flexDirection: "row", gap: 12, marginTop: 6, flexWrap: "wrap" },
  metric: { alignItems: "center", minWidth: 60 },
  metricN: { color: theme.color.textHi, fontSize: 20, fontWeight: "800" },
  metricMax: { color: theme.color.textDim, fontSize: 12, fontWeight: "600" },
  metricLabel: { color: theme.color.textDim, fontSize: 10, letterSpacing: 0.5, fontWeight: "700" },
  notes: { color: theme.color.textHi, fontSize: 12, marginTop: 6, lineHeight: 18 },
  injuryBadge: {
    flexDirection: "row", alignItems: "center", gap: 5, marginTop: 8,
    paddingHorizontal: 6, paddingVertical: 3, borderRadius: 4,
    backgroundColor: "#3b1414", borderWidth: 1, borderColor: "#ff6b6b", alignSelf: "flex-start",
  },
  injuryText: { color: "#ff6b6b", fontSize: 10, fontWeight: "800", letterSpacing: 0.5 },

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
  bubbleTime: { color: theme.color.textDim, fontSize: 9, marginTop: 4 },
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
});
