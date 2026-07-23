import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter, useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme, loadColor } from "@/src/lib/theme";
import { useIsDesktop, useIsWide } from "@/src/lib/responsive";
import { CoachToDoFeed } from "@/src/components/CoachToDoFeed";
import { ExerciseMediaSummary } from "@/src/components/ExerciseMediaSummary";
import { useAuth } from "@/src/lib/auth";
import { NotificationBell } from "@/src/components/NotificationBell";
import { PreviewLauncher } from "@/src/components/PreviewLauncher";

type Client = any;

export default function CoachOverview() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const isDesktop = useIsDesktop();
  const isWide = useIsWide();
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<{ clients: Client[]; counts: any; total: number }>({ clients: [], counts: {}, total: 0 });
  const [pending, setPending] = useState<any[]>([]);
  const [analytics, setAnalytics] = useState<any | null>(null);

  const load = useCallback(async () => {
    // Don't fire authenticated calls until the auth bootstrap has finished
    // and we actually have a coach user. Prevents "Missing token" LogBox
    // crashes when the page mounts before AsyncStorage has resolved or the
    // user is opening the coach URL without a session.
    if (authLoading || !user) return;
    setLoading(true);
    try {
      const [dash, pend, an] = await Promise.all([
        api<any>(`/coach/dashboard`),
        api<any[]>(`/coach/pending-approvals`),
        api<any>(`/coach/analytics?days=30`),
      ]);
      setData(dash);
      setPending(pend);
      setAnalytics(an);
    } catch (e: any) {
      // 401 (Missing token / expired session) → send to login instead of
      // dumping the raw error onto the screen.
      const msg = String(e?.message || "");
      if (/missing token|not authenticated|invalid token/i.test(msg)) {
        router.replace("/(auth)/login" as any);
        return;
      }
      // eslint 'no-console' is disabled globally for warn/error paths.
      console.warn("coach overview load failed:", msg);
    } finally {
      setLoading(false);
    }
  }, [authLoading, user, router]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const counts = data.counts || {};
  const total = data.total || 0;
  const active = Math.max(0, total - Math.max(counts.no_roster || 0, counts.expired || 0));

  // Compute upcoming key sessions and next-3-day roster loads
  const clients: any[] = data.clients || [];
  const keyClients = clients.slice(0, 6);
  const alerts: any[] = [
    ...(counts.expired ? [{ tone: "red", label: `${counts.expired} client${counts.expired > 1 ? "s" : ""} have EXPIRED rosters` }] : []),
    ...(counts.expiring_soon ? [{ tone: "amber", label: `${counts.expiring_soon} roster${counts.expiring_soon > 1 ? "s" : ""} expiring within 7 days` }] : []),
    ...(pending.length ? [{ tone: "info", label: `${pending.length} workout${pending.length > 1 ? "s" : ""} awaiting approval` }] : []),
    ...(counts.needs_confirmation ? [{ tone: "info", label: `${counts.needs_confirmation} roster${counts.needs_confirmation > 1 ? "s" : ""} awaiting client confirmation` }] : []),
    ...(counts.hotels_pending_review ? [{ tone: "amber", label: `${counts.hotels_pending_review} hotel${counts.hotels_pending_review > 1 ? "s" : ""} awaiting your verification`, action: "/coach/hotels" }] : []),
  ];

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.color.surface }} edges={isDesktop ? [] : ["top"]}>
      <ScrollView
        style={styles.root}
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}
      >
      <View style={styles.header}>
        <View>
          <Text style={styles.h1}>OVERVIEW</Text>
          <Text style={styles.sub}>Fleet health at a glance · {total} client{total !== 1 ? "s" : ""}</Text>
        </View>
        <View style={{ flexDirection: "row", gap: 10, alignItems: "center" }}>
          <Pressable testID="ov-goto-calendar" onPress={() => router.push("/(coach)/calendar")} style={styles.headerBtn}>
            <Ionicons name="calendar-outline" size={16} color={theme.color.brand} />
            <Text style={styles.headerBtnText}>WEEKLY CALENDAR</Text>
          </Pressable>
          <Pressable testID="ov-goto-analytics" onPress={() => router.push("/(coach)/analytics")} style={styles.headerBtn}>
            <Ionicons name="bar-chart-outline" size={16} color={theme.color.brand} />
            <Text style={styles.headerBtnText}>ANALYTICS</Text>
          </Pressable>
          <Pressable testID="ov-goto-social" onPress={() => router.push("/social-studio" as any)} style={styles.headerBtn}>
            <Ionicons name="megaphone-outline" size={16} color={theme.color.brand} />
            <Text style={styles.headerBtnText}>SOCIAL</Text>
          </Pressable>
          <Pressable testID="ov-goto-brand" onPress={() => router.push("/coach/brand-images" as any)} style={styles.headerBtn}>
            <Ionicons name="images-outline" size={16} color={theme.color.brand} />
            <Text style={styles.headerBtnText}>IMAGES</Text>
          </Pressable>
          <Pressable testID="ov-goto-exercises" onPress={() => router.push("/coach/exercise-content" as any)} style={styles.headerBtn}>
            <Ionicons name="barbell-outline" size={16} color={theme.color.brand} />
            <Text style={styles.headerBtnText}>EXERCISES</Text>
          </Pressable>
          <Pressable testID="ov-goto-nutrition" onPress={() => router.push("/coach/nutrition" as any)} style={styles.headerBtn}>
            <Ionicons name="nutrition-outline" size={16} color={theme.color.brand} />
            <Text style={styles.headerBtnText}>NUTRITION</Text>
          </Pressable>
          <Pressable testID="ov-goto-hotels" onPress={() => router.push("/coach/hotels" as any)} style={styles.headerBtn}>
            <Ionicons name="bed-outline" size={16} color={theme.color.brand} />
            <Text style={styles.headerBtnText}>HOTELS</Text>
          </Pressable>
          {(user?.is_admin || (user as any)?.is_primary_coach || (user as any)?.coach_tier === "admin" || (user?.email || "").toLowerCase().endsWith("@crewfit.net")) ? (
            <>
              <Pressable testID="ov-goto-live-controls" onPress={() => router.push("/coach/admin/live-controls" as any)} style={[styles.headerBtn, { borderColor: theme.color.brand, backgroundColor: theme.color.brandTint }]}>
                <Ionicons name="options" size={16} color={theme.color.brand} />
                <Text style={styles.headerBtnText}>LIVE CONTROLS</Text>
              </Pressable>
              <Pressable testID="ov-goto-coaches" onPress={() => router.push("/coach/admin/coaches" as any)} style={[styles.headerBtn, { borderColor: theme.color.brand, backgroundColor: theme.color.brandTint }]}>
                <Ionicons name="people-circle-outline" size={16} color={theme.color.brand} />
                <Text style={styles.headerBtnText}>COACHES</Text>
              </Pressable>
            </>
          ) : null}
          <NotificationBell testID="coach-notif-bell" />
        </View>
      </View>

      {loading && !clients.length ? (
        <ActivityIndicator color={theme.color.brand} style={{ marginTop: 40 }} />
      ) : (
        <>
          <View style={styles.kpiRow}>
            <KPI icon="people" label="ACTIVE CLIENTS" value={active} sub={`${counts.no_roster || 0} without roster`} tint={theme.color.green} />
            <KPI icon="time" label="EXPIRING SOON" value={counts.expiring_soon || 0} sub="within 7 days" tint={theme.color.amber} />
            <KPI icon="warning" label="EXPIRED" value={counts.expired || 0} sub="needs new roster" tint={theme.color.red} />
            <KPI icon="flame" label="RED DAYS" value={clients.reduce((s: number, c: any) => s + (c.red_days || 0), 0)} sub="across all clients" tint={theme.color.red} />
            <KPI icon="checkmark-done" label="PENDING APPROVALS" value={pending.length} sub="workouts to review" tint={theme.color.brand} />
            <KPI icon="bed" label="HOTELS TO REVIEW" value={counts.hotels_pending_review || 0} sub="tap to open queue" tint={theme.color.amber} onPress={() => router.push("/coach/hotels" as any)} />
            <KPI icon="trending-up" label="COMPLIANCE" value={analytics ? `${analytics.global_compliance}%` : "—"} sub={`last ${analytics?.days || 30} days`} tint={theme.color.green} />
          </View>

          {alerts.length > 0 && (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>ATTENTION REQUIRED</Text>
              <View style={{ gap: 8 }}>
                {alerts.map((a, i) => {
                  const RowInner = (
                    <>
                      <Ionicons name="alert-circle" size={18} color={a.tone === "red" ? theme.color.red : a.tone === "amber" ? theme.color.amber : theme.color.brand} />
                      <Text style={styles.alertText}>{a.label}</Text>
                      {a.action ? <Ionicons name="chevron-forward" size={14} color={theme.color.textMuted} /> : null}
                    </>
                  );
                  const bar = a.tone === "red" ? theme.color.red : a.tone === "amber" ? theme.color.amber : theme.color.brand;
                  if (a.action) {
                    return (
                      <Pressable
                        key={i}
                        testID={`alert-action-${i}`}
                        onPress={() => router.push(a.action as any)}
                        style={[styles.alertRow, { borderLeftColor: bar }]}
                      >
                        {RowInner}
                      </Pressable>
                    );
                  }
                  return (
                    <View key={i} style={[styles.alertRow, { borderLeftColor: bar }]}>
                      {RowInner}
                    </View>
                  );
                })}
              </View>
            </View>
          )}

          <ExerciseMediaSummary />

          <CoachToDoFeed />

          <PreviewLauncher />

          <Pressable onPress={() => router.push("/coach/ui-issues" as any)} style={styles.uiIssuesLink} testID="link-ui-issues">
            <Ionicons name="bug-outline" size={14} color={theme.color.textMuted} />
            <Text style={styles.uiIssuesT}>UI ISSUES REPORTED FROM PREVIEW MODE →</Text>
          </Pressable>

          <View style={[styles.twoCol, !isWide && { flexDirection: "column" }]}>
            <View style={[styles.section, isWide ? { flex: 1 } : {}]}>
              <View style={styles.sectionHead}>
                <Text style={styles.sectionTitle}>CLIENTS — NEXT 14 DAYS</Text>
                <Pressable onPress={() => router.push("/(coach)/clients")}>
                  <Text style={styles.link}>ALL CLIENTS →</Text>
                </Pressable>
              </View>
              {keyClients.length === 0 ? (
                <Text style={styles.empty}>No clients yet.</Text>
              ) : (
                <View style={{ gap: 10 }}>
                  {keyClients.map((cl: any) => {
                    const days: any[] = cl.latest_roster?.days || [];
                    const exp = cl.roster_expiry || {};
                    return (
                      <Pressable
                        key={cl.id}
                        testID={`ov-client-${cl.id}`}
                        onPress={() => router.push(`/coach/client/${cl.id}` as any)}
                        style={styles.clientRow}
                      >
                        <View style={{ flex: 1 }}>
                          <Text style={styles.clientName}>{cl.name}</Text>
                          <View style={{ flexDirection: "row", gap: 3, marginTop: 6 }}>
                            {days.slice(0, 14).map((d: any, i: number) => (
                              <View key={i} style={[styles.miniBar, { backgroundColor: loadColor(d.load) }]} />
                            ))}
                            {days.length === 0 && <Text style={{ color: theme.color.textDim, fontSize: 11 }}>NO ROSTER</Text>}
                          </View>
                        </View>
                        <View style={{ alignItems: "flex-end", gap: 4, marginLeft: 12 }}>
                          {cl.progression_pill?.status ? (
                            <ProgressionPill status={cl.progression_pill.status} label={cl.progression_pill.status_label} />
                          ) : null}
                          {cl.pending_approvals > 0 && <Pill tint={theme.color.brand}>{cl.pending_approvals} PENDING</Pill>}
                          {exp.expired && <Pill tint={theme.color.red}>EXPIRED</Pill>}
                          {!exp.expired && exp.coverage === "critical" && <Pill tint={theme.color.amber}>{exp.days_remaining}D LEFT</Pill>}
                          {!exp.expired && exp.coverage === "good" && <Pill tint={theme.color.green}>{exp.days_remaining}D</Pill>}
                        </View>
                      </Pressable>
                    );
                  })}
                </View>
              )}
            </View>

            <View style={[styles.section, isWide ? { width: 380 } : {}]}>
              <View style={styles.sectionHead}>
                <Text style={styles.sectionTitle}>PENDING APPROVALS</Text>
                <Pressable onPress={() => router.push("/(coach)/approvals")}>
                  <Text style={styles.link}>REVIEW ALL →</Text>
                </Pressable>
              </View>
              {pending.length === 0 ? (
                <Text style={styles.empty}>All caught up – no pending items.</Text>
              ) : (
                <View style={{ gap: 8 }}>
                  {pending.slice(0, 6).map((w: any) => (
                    <Pressable
                      key={w.id}
                      testID={`ov-pending-${w.id}`}
                      onPress={() => router.push(`/workout/${w.id}` as any)}
                      style={styles.pendingRow}
                    >
                      <View style={[styles.loadDot, { backgroundColor: loadColor(w.day_load) }]} />
                      <View style={{ flex: 1 }}>
                        <Text style={styles.pendingClient}>{w.client_name}</Text>
                        <Text style={styles.pendingTitle} numberOfLines={1}>{w.title}</Text>
                      </View>
                      <Text style={styles.pendingDate}>{w.date?.slice(5) || ""}</Text>
                    </Pressable>
                  ))}
                  {pending.length > 6 && <Text style={styles.moreCount}>+{pending.length - 6} more</Text>}
                </View>
              )}
            </View>
          </View>

          {analytics && (
            <View style={styles.section}>
              <View style={styles.sectionHead}>
                <Text style={styles.sectionTitle}>TOP PERFORMERS — LAST 30 DAYS</Text>
                <Pressable onPress={() => router.push("/(coach)/analytics")}>
                  <Text style={styles.link}>FULL ANALYTICS →</Text>
                </Pressable>
              </View>
              <View style={{ gap: 8 }}>
                {(analytics.clients || []).slice(0, 5).map((c: any) => (
                  <View key={c.client_id} style={styles.leaderRow}>
                    <Text style={styles.leaderName}>{c.client_name}</Text>
                    <View style={styles.progressTrack}>
                      <View style={[styles.progressFill, { width: `${Math.max(2, c.compliance)}%` }]} />
                    </View>
                    <Text style={styles.leaderPct}>{c.compliance}%</Text>
                    <Text style={styles.leaderMeta}>{c.completed}/{c.scheduled} · RPE {c.avg_rpe ?? "—"}</Text>
                  </View>
                ))}
              </View>
            </View>
          )}
        </>
      )}
    </ScrollView>
    </SafeAreaView>
  );
}

function KPI({ icon, label, value, sub, tint, onPress }: any) {
  const Wrapper: any = onPress ? Pressable : View;
  return (
    <Wrapper style={styles.kpi} onPress={onPress}>
      <View style={styles.kpiTop}>
        <Ionicons name={icon} size={16} color={tint || theme.color.brand} />
        <Text style={styles.kpiLabel}>{label}</Text>
      </View>
      <Text style={[styles.kpiVal, tint && { color: tint }]}>{value}</Text>
      <Text style={styles.kpiSub}>{sub}</Text>
    </Wrapper>
  );
}

function Pill({ children, tint }: any) {
  return (
    <View style={[styles.pill, { backgroundColor: tint }]}>
      <Text style={styles.pillText}>{children}</Text>
    </View>
  );
}

// Iter 81 Phase 4 — small compact pill showing the client's latest weekly
// progression_status. Colour-coded to match the client-side Your Progress card.
function ProgressionPill({ status, label }: { status: string; label?: string }) {
  const color =
    status === "progressing_well" ? "#16A34A" :
    status === "reduce_load"      ? "#B45309" :
    status === "deload"           ? "#1D4ED8" : theme.color.brand;
  const bg =
    status === "progressing_well" ? "rgba(34,197,94,0.15)" :
    status === "reduce_load"      ? "rgba(245,158,11,0.18)" :
    status === "deload"           ? "rgba(59,130,246,0.15)" : "rgba(163,24,46,0.12)";
  return (
    <View style={[styles.pill, { backgroundColor: bg }]} testID={`prog-pill-${status}`}>
      <Text style={[styles.pillText, { color }]}>{label || status.toUpperCase()}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  content: { padding: 32, paddingBottom: 80, maxWidth: 1600 },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 24 },
  h1: { color: theme.color.text, fontSize: 28, fontWeight: "900", letterSpacing: 2 },
  sub: { color: theme.color.textMuted, marginTop: 4 },
  headerBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 14, paddingVertical: 10,
    backgroundColor: theme.color.surface2, borderRadius: 8,
    borderWidth: 1, borderColor: theme.color.border,
  },
  headerBtnText: { color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 1.5 },

  kpiRow: { flexDirection: "row", gap: 12, marginBottom: 24, flexWrap: "wrap" },
  kpi: {
    flex: 1, minWidth: 150, maxWidth: 260,
    padding: 18,
    backgroundColor: theme.color.surface2,
    borderRadius: 12,
    borderWidth: 1, borderColor: theme.color.border,
  },
  kpiTop: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 8 },
  kpiLabel: { color: theme.color.textDim, fontSize: 10, fontWeight: "800", letterSpacing: 1.5 },
  kpiVal: { color: theme.color.text, fontSize: 32, fontWeight: "900", letterSpacing: -1 },
  kpiSub: { color: theme.color.textMuted, fontSize: 11, marginTop: 4 },

  section: {
    backgroundColor: theme.color.surface2,
    padding: 20,
    borderRadius: 12,
    borderWidth: 1, borderColor: theme.color.border,
    marginBottom: 20,
  },
  sectionHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 14 },
  sectionTitle: { color: theme.color.text, fontSize: 12, fontWeight: "800", letterSpacing: 2 },
  link: { color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 1.5 },

  twoCol: { flexDirection: "row", gap: 20, alignItems: "flex-start" },

  uiIssuesLink: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 20, padding: 12, backgroundColor: theme.color.surface2, borderRadius: 8, borderWidth: 1, borderColor: theme.color.border },
  uiIssuesT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "800", letterSpacing: 1 },

  alertRow: {
    flexDirection: "row", alignItems: "center", gap: 12,
    padding: 12,
    borderLeftWidth: 3,
    backgroundColor: theme.color.surface3,
    borderRadius: 6,
  },
  alertText: { color: theme.color.text, fontSize: 13, flex: 1 },

  clientRow: {
    flexDirection: "row",
    alignItems: "center",
    padding: 12,
    backgroundColor: theme.color.surface3,
    borderRadius: 8,
  },
  clientName: { color: theme.color.text, fontWeight: "700", fontSize: 14 },
  miniBar: { flex: 1, height: 6, borderRadius: 2 },

  pill: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 4 },
  pillText: { color: "#fff", fontSize: 9, fontWeight: "800", letterSpacing: 1 },

  pendingRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    padding: 10, backgroundColor: theme.color.surface3, borderRadius: 6,
  },
  loadDot: { width: 8, height: 8, borderRadius: 4 },
  pendingClient: { color: theme.color.text, fontSize: 12, fontWeight: "700" },
  pendingTitle: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },
  pendingDate: { color: theme.color.textDim, fontSize: 10, letterSpacing: 1, fontWeight: "700" },
  moreCount: { color: theme.color.textMuted, textAlign: "center", fontSize: 11 },

  leaderRow: {
    flexDirection: "row", alignItems: "center", gap: 12, padding: 10,
    backgroundColor: theme.color.surface3, borderRadius: 6,
  },
  leaderName: { color: theme.color.text, fontSize: 13, fontWeight: "700", width: 180 },
  progressTrack: {
    flex: 1, height: 8, borderRadius: 4,
    backgroundColor: theme.color.border, overflow: "hidden",
  },
  progressFill: { height: "100%", backgroundColor: theme.color.green, borderRadius: 4 },
  leaderPct: { color: theme.color.text, fontSize: 13, fontWeight: "800", width: 45, textAlign: "right" },
  leaderMeta: { color: theme.color.textDim, fontSize: 11, width: 130, textAlign: "right" },

  empty: { color: theme.color.textMuted, textAlign: "center", padding: 20 },
});
