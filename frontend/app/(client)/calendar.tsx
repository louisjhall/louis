import { useCallback, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, RefreshControl, ActivityIndicator } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme, loadColor } from "@/src/lib/theme";

type ViewMode = "month" | "week" | "day";

export default function Calendar() {
  const router = useRouter();
  const [roster, setRoster] = useState<any>(null);
  const [workouts, setWorkouts] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [mode, setMode] = useState<ViewMode>("month");
  const [selectedDate, setSelectedDate] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [r, w] = await Promise.all([api<any>("/roster/current"), api<any[]>("/workouts/week")]);
      setRoster(r && r.id ? r : null);
      setWorkouts(w || []);
    } finally { setLoading(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const workoutMap = useMemo(() => new Map(workouts.map((w) => [w.date, w])), [workouts]);
  const rosterMap = useMemo(() => new Map((roster?.days || []).map((d: any) => [d.date, d])), [roster]);

  const generate = async () => {
    if (!roster) return;
    setBusy(true); setErr(null);
    try {
      const start = await api<{ job_id: string; status: string; total: number }>("/workouts/generate-month", { method: "POST", body: { roster_id: roster.id } });
      // Poll job status
      const poll = async (): Promise<void> => {
        for (let i = 0; i < 90; i++) { // up to ~3 min
          await new Promise((r) => setTimeout(r, 2000));
          const j = await api<any>(`/workouts/job/${start.job_id}`);
          if (j.status === "done") {
            setWorkouts(j.workouts || []);
            return;
          }
          if (j.status === "failed") {
            setErr(j.error || "Generation failed");
            return;
          }
        }
        setErr("Generation timed out — try refreshing.");
      };
      await poll();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  const regenerate = async (opts: { dates?: string[]; week_start?: string; all?: boolean }) => {
    if (!roster) return;
    setBusy(true); setErr(null);
    try {
      const r = await api<{ workouts: any[] }>("/workouts/regenerate", { method: "POST", body: { roster_id: roster.id, ...opts } });
      // merge into workouts
      const map = new Map(workouts.map((w) => [w.id, w]));
      r.workouts.forEach((w) => map.set(w.id, w));
      setWorkouts(Array.from(map.values()).sort((a, b) => a.date.localeCompare(b.date)));
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  // Build the month grid from roster start_date's month (or current month)
  const monthAnchor = roster?.start_date || new Date().toISOString().slice(0, 10);
  const anchor = new Date(monthAnchor);
  const year = anchor.getUTCFullYear();
  const month = anchor.getUTCMonth();
  const firstDay = new Date(Date.UTC(year, month, 1));
  const startDow = firstDay.getUTCDay(); // 0 Sun
  const daysInMonth = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const cells: { date: string | null }[] = [];
  for (let i = 0; i < startDow; i++) cells.push({ date: null });
  for (let d = 1; d <= daysInMonth; d++) {
    const iso = new Date(Date.UTC(year, month, d)).toISOString().slice(0, 10);
    cells.push({ date: iso });
  }
  const monthName = anchor.toLocaleString("en-US", { month: "long", year: "numeric" });

  const sel = selectedDate;
  const selRosterDay: any = sel ? rosterMap.get(sel) : null;
  const selWorkout: any = sel ? workoutMap.get(sel) : null;

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Text style={styles.title}>{monthName.toUpperCase()}</Text>
        <View style={styles.modeRow}>
          {(["month", "week", "day"] as ViewMode[]).map((m) => (
            <Pressable key={m} testID={`mode-${m}`} onPress={() => setMode(m)} style={[styles.modeChip, mode === m && styles.modeChipActive]}>
              <Text style={[styles.modeText, mode === m && { color: "#fff" }]}>{m.toUpperCase()}</Text>
            </Pressable>
          ))}
        </View>
      </View>

      <ScrollView
        contentContainerStyle={{ padding: theme.space.md, paddingBottom: 120 }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}
      >
        {!roster ? (
          <View style={styles.empty}>
            <Ionicons name="airplane" size={40} color={theme.color.brand} />
            <Text style={styles.eTitle}>No roster uploaded</Text>
            <Text style={styles.eSub}>Upload your monthly schedule to build the plan.</Text>
            <Pressable onPress={() => router.push("/roster-upload")} style={styles.cta} testID="cal-upload-cta">
              <Text style={styles.ctaText}>UPLOAD ROSTER</Text>
            </Pressable>
          </View>
        ) : (
          <>
            {mode === "month" && (
              <>
                <View style={styles.dowRow}>
                  {["S", "M", "T", "W", "T", "F", "S"].map((d, i) => (
                    <Text key={i} style={styles.dowText}>{d}</Text>
                  ))}
                </View>
                <View style={styles.grid}>
                  {cells.map((c, i) => {
                    if (!c.date) return <View key={i} style={styles.cell} />;
                    const rd: any = rosterMap.get(c.date);
                    const wk: any = workoutMap.get(c.date);
                    const color = loadColor(wk?.day_load || rd?.load || "grey");
                    const dn = new Date(c.date).getUTCDate();
                    const isToday = c.date === new Date().toISOString().slice(0, 10);
                    return (
                      <Pressable
                        key={i}
                        testID={`cal-cell-${c.date}`}
                        onPress={() => { setSelectedDate(c.date); setMode("day"); }}
                        style={[styles.cell, styles.cellFilled, isToday && styles.cellToday]}
                      >
                        <Text style={styles.cellDate}>{dn}</Text>
                        <View style={[styles.cellDot, { backgroundColor: color }]} />
                        {wk?.coach_locked && <Ionicons name="lock-closed" size={9} color={theme.color.amber} style={styles.cellLock} />}
                        {wk?.completed && <Ionicons name="checkmark-circle" size={10} color={theme.color.green} style={styles.cellLock} />}
                      </Pressable>
                    );
                  })}
                </View>
                <View style={styles.legendRow}>
                  {[["green", "Train"], ["amber", "Reduce"], ["red", "Recover"], ["blue", "Duty"], ["purple", "Layover"], ["grey", "Unknown"]].map(([c, l]) => (
                    <View key={c} style={styles.legendItem}>
                      <View style={[styles.legendDot, { backgroundColor: loadColor(c) }]} />
                      <Text style={styles.legendText}>{l}</Text>
                    </View>
                  ))}
                </View>
              </>
            )}

            {mode === "week" && (
              <View style={{ gap: 6 }}>
                {(roster.days || []).slice(0, 14).map((d: any) => {
                  const wk = workoutMap.get(d.date);
                  return (
                    <Pressable key={d.date} testID={`week-day-${d.date}`} onPress={() => { setSelectedDate(d.date); setMode("day"); }} style={styles.dayLine}>
                      <View style={[styles.dayBar, { backgroundColor: loadColor(d.load) }]} />
                      <View style={{ flex: 1, padding: theme.space.md }}>
                        <Text style={styles.dLineDate}>{d.date} · {d.day_type}</Text>
                        {d.flights?.[0] && <Text style={styles.dLineFlight}>{d.flights.map((f: any) => `${f.from}→${f.to}`).join("  ")}</Text>}
                        <Text style={styles.dLineW}>{wk ? `${wk.title} · ${wk.location}` : "— no workout"}</Text>
                      </View>
                      <Ionicons name="chevron-forward" size={16} color={theme.color.textDim} style={{ marginRight: 12 }} />
                    </Pressable>
                  );
                })}
              </View>
            )}

            {mode === "day" && sel && (
              <View style={styles.dayCard}>
                <Pressable onPress={() => setMode("month")} testID="day-back">
                  <Text style={{ color: theme.color.brand, fontWeight: "700", letterSpacing: 1.5 }}>← MONTH</Text>
                </Pressable>
                <Text style={styles.dayHeader}>{sel}</Text>
                {selRosterDay ? (
                  <View style={styles.dayInfo}>
                    <Row label="TYPE" value={selRosterDay.day_type} />
                    <Row label="LOCATION" value={selRosterDay.home_or_away === "away" ? `Away · ${selRosterDay.layover_city || "?"}` : "Home"} />
                    {selRosterDay.report_time && <Row label="REPORT" value={selRosterDay.report_time} />}
                    {selRosterDay.duty_end_time && <Row label="OFF DUTY" value={selRosterDay.duty_end_time} />}
                    {selRosterDay.flights?.[0] && <Row label="FLIGHTS" value={selRosterDay.flights.map((f: any) => `${f.from}→${f.to}`).join("  ")} />}
                    {selRosterDay.hotel_name && <Row label="HOTEL" value={selRosterDay.hotel_name} />}
                    <View style={styles.loadPill}>
                      <View style={[styles.dotSm, { backgroundColor: loadColor(selRosterDay.load) }]} />
                      <Text style={styles.loadPillText}>{String(selRosterDay.load || "grey").toUpperCase()} DAY</Text>
                    </View>
                  </View>
                ) : <Text style={{ color: theme.color.textMuted }}>No roster entry.</Text>}
                {selWorkout ? (
                  <Pressable testID="day-open-workout" onPress={() => router.push(`/workout/${selWorkout.id}`)} style={styles.wOpen}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.wOpenTitle}>{selWorkout.title}</Text>
                      <Text style={styles.wOpenMeta}>{selWorkout.location} · {selWorkout.duration_min}min · {selWorkout.exercises?.length || 0} exercises</Text>
                    </View>
                    <Ionicons name="arrow-forward" size={18} color={theme.color.brand} />
                  </Pressable>
                ) : <Text style={{ color: theme.color.textMuted, marginTop: 12 }}>No workout for this day.</Text>}
                <Pressable testID="regen-day" onPress={() => regenerate({ dates: [sel] })} disabled={busy} style={[styles.regenBtn, busy && { opacity: 0.5 }]}>
                  <Ionicons name="refresh" size={14} color={theme.color.brand} />
                  <Text style={styles.regenText}>REGENERATE THIS DAY</Text>
                </Pressable>
              </View>
            )}

            {err && <Text style={{ color: theme.color.red, marginTop: 12 }}>{err}</Text>}
          </>
        )}
      </ScrollView>

      {roster && (
        <View style={styles.sticky}>
          <Pressable testID="generate-month" onPress={workouts.length ? () => regenerate({ all: true }) : generate} disabled={busy} style={[styles.cta, busy && { opacity: 0.6 }]}>
            {busy ? (
              <><ActivityIndicator color="#fff" /><Text style={styles.ctaText}>  BUILDING…</Text></>
            ) : (
              <><Ionicons name="sparkles" size={16} color="#fff" /><Text style={styles.ctaText}>  {workouts.length ? "REGENERATE MONTH" : "GENERATE MONTH"}</Text></>
            )}
          </Pressable>
        </View>
      )}
    </SafeAreaView>
  );
}

function Row({ label, value }: any) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={styles.rowValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  title: { color: theme.color.text, fontSize: 20, letterSpacing: 2, fontWeight: "900" },
  modeRow: { flexDirection: "row", gap: 6, marginTop: 10 },
  modeChip: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: theme.radius.pill, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  modeChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  modeText: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 1.5, fontWeight: "800" },
  dowRow: { flexDirection: "row" },
  dowText: { flex: 1, textAlign: "center", color: theme.color.textDim, fontSize: 10, letterSpacing: 2, fontWeight: "800", paddingBottom: 8 },
  grid: { flexDirection: "row", flexWrap: "wrap" },
  cell: { width: `${100 / 7}%`, aspectRatio: 1, padding: 2 },
  cellFilled: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.sm, borderWidth: 1, borderColor: theme.color.border, alignItems: "center", justifyContent: "center", padding: 4 },
  cellToday: { borderColor: theme.color.brand },
  cellDate: { color: theme.color.text, fontSize: 13, fontWeight: "700" },
  cellDot: { width: 8, height: 8, borderRadius: 4, marginTop: 4 },
  cellLock: { position: "absolute", top: 3, right: 3 },
  legendRow: { flexDirection: "row", flexWrap: "wrap", gap: 10, marginTop: theme.space.md },
  legendItem: { flexDirection: "row", alignItems: "center", gap: 4 },
  legendDot: { width: 8, height: 8, borderRadius: 4 },
  legendText: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 1.5, fontWeight: "700" },
  empty: { alignItems: "center", padding: theme.space.xxl, borderWidth: 1, borderColor: theme.color.border, borderRadius: theme.radius.md, backgroundColor: theme.color.surface2 },
  eTitle: { color: theme.color.text, fontSize: 18, fontWeight: "800", marginTop: theme.space.md },
  eSub: { color: theme.color.textMuted, marginTop: 4, textAlign: "center" },
  dayLine: { flexDirection: "row", alignItems: "center", backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, overflow: "hidden" },
  dayBar: { width: 4, alignSelf: "stretch" },
  dLineDate: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 1.5, fontWeight: "800" },
  dLineFlight: { color: theme.color.brand, fontSize: 12, fontWeight: "600", marginTop: 2 },
  dLineW: { color: theme.color.text, fontSize: 14, fontWeight: "700", marginTop: 3 },
  dayCard: { padding: theme.space.md, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border },
  dayHeader: { color: theme.color.text, fontSize: 22, fontWeight: "900", marginTop: theme.space.sm, letterSpacing: -0.5 },
  dayInfo: { marginTop: theme.space.md, gap: 4 },
  row: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 4, borderTopWidth: 1, borderTopColor: theme.color.divider },
  rowLabel: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1.5, fontWeight: "800" },
  rowValue: { color: theme.color.text, fontSize: 12, fontWeight: "600" },
  loadPill: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: theme.color.surface3, borderRadius: theme.radius.pill, paddingHorizontal: 10, paddingVertical: 4, alignSelf: "flex-start", marginTop: 8 },
  dotSm: { width: 6, height: 6, borderRadius: 3 },
  loadPillText: { color: theme.color.text, fontSize: 10, letterSpacing: 1.5, fontWeight: "800" },
  wOpen: { flexDirection: "row", alignItems: "center", padding: theme.space.md, borderTopWidth: 1, borderTopColor: theme.color.divider, marginTop: theme.space.md },
  wOpenTitle: { color: theme.color.text, fontSize: 15, fontWeight: "800" },
  wOpenMeta: { color: theme.color.textMuted, fontSize: 12, marginTop: 2 },
  regenBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, marginTop: theme.space.md, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.brand, paddingVertical: 10 },
  regenText: { color: theme.color.brand, fontWeight: "800", fontSize: 11, letterSpacing: 1.5 },
  sticky: { position: "absolute", left: 0, right: 0, bottom: 0, padding: theme.space.md, backgroundColor: theme.color.surface, borderTopWidth: 1, borderTopColor: theme.color.border },
  cta: { flexDirection: "row", alignItems: "center", justifyContent: "center", backgroundColor: theme.color.brand, paddingVertical: 14, borderRadius: theme.radius.md },
  ctaText: { color: "#fff", fontWeight: "800", letterSpacing: 2, fontSize: 13 },
});
