import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, RefreshControl, ActivityIndicator } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme, loadColor } from "@/src/lib/theme";
import { DayEditModal } from "@/src/components/DayEditModal";
import { AddActivityModal } from "@/src/components/AddActivityModal";
import { listActivities, type PersonalActivity } from "@/src/lib/personalActivities";
import { RosterDayChip } from "@/src/components/RosterDayChip";

const WEEKDAYS = ["S", "M", "T", "W", "T", "F", "S"];

function firstWeekdayOffset(iso: string): number {
  const d = new Date(iso + "T00:00:00Z");
  return d.getUTCDay(); // 0=Sun
}

export default function CalendarScreen() {
  const router = useRouter();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [activeJob, setActiveJob] = useState<any>(null);
  const [monthsBack, setMonthsBack] = useState(2);
  const [monthsAhead, setMonthsAhead] = useState(4);
  const [selectedIsoMonth, setSelectedIsoMonth] = useState<string | null>(null);
  const [editDate, setEditDate] = useState<string | null>(null);
  const [addActivityDate, setAddActivityDate] = useState<string | null>(null);
  const [activities, setActivities] = useState<PersonalActivity[]>([]);
  const scrollRef = useRef<ScrollView>(null);
  const monthOffsetsRef = useRef<Record<string, number>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [tl, aj, acts] = await Promise.all([
        api<any>(`/calendar/timeline?months_back=${monthsBack}&months_ahead=${monthsAhead}`),
        api<any>(`/roster/jobs/active`).catch(() => ({})),
        listActivities().catch(() => [] as PersonalActivity[]),
      ]);
      setData(tl);
      setActiveJob(aj && aj.id ? aj : null);
      setActivities(acts);
      if (!selectedIsoMonth) {
        // Iter172 · Prefer the client's ACTUAL current month over
        // `tl.today` (which can be stale if the server clock or the
        // roster timeline lags). Compute YYYY-MM locally, then look for
        // a matching timeline row; fall back to `tl.today`'s month, and
        // finally to the newest timeline row so we never crash.
        const now = new Date();
        const localMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
        const currentMonth = localMonth || (tl.today || "").slice(0, 7);
        const m =
          (tl.months || []).find((mm: any) => mm.iso.slice(0, 7) === currentMonth) ||
          (tl.months || []).find((mm: any) => mm.iso.slice(0, 7) === (tl.today || "").slice(0, 7)) ||
          tl.months?.[0];
        if (m) setSelectedIsoMonth(m.iso);
      }
    } finally { setLoading(false); }
  }, [monthsBack, monthsAhead, selectedIsoMonth]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  // Poll active job for banner updates
  useEffect(() => {
    if (!activeJob) return;
    const interval = setInterval(async () => {
      try {
        const j = await api<any>(`/roster/jobs/${activeJob.id}`);
        setActiveJob(j);
        if (j.status === "complete" || j.status === "failed" || j.status === "partial") {
          clearInterval(interval);
          if (j.status === "complete") load();
        }
      } catch { clearInterval(interval); }
    }, 3000);
    return () => clearInterval(interval);
  }, [activeJob?.id, load]);

  // Iter 162 · Reverse-chronological — the latest/current month sits at
  // the top of the list so returning clients land on the current month
  // without scrolling. Older months are pushed downward.
  const months: any[] = useMemo(() => {
    const src = (data?.months || []) as any[];
    return [...src].sort((a, b) => (b?.iso || "").localeCompare(a?.iso || ""));
  }, [data?.months]);
  const today = data?.today;

  const scrollToMonth = (iso: string) => {
    setSelectedIsoMonth(iso);
    const y = monthOffsetsRef.current[iso];
    if (typeof y === "number") {
      scrollRef.current?.scrollTo({ y, animated: true });
    }
  };
  const goToday = () => {
    if (!today) return;
    const m = today.slice(0, 7);
    const found = months.find((mm) => mm.iso.slice(0, 7) === m);
    if (found) scrollToMonth(found.iso);
  };
  const prevMonth = () => {
    // Iter 162 · list is reverse-chronological — older months live at
    // HIGHER indices. "Prev" (go back in time) therefore = idx + 1.
    const idx = months.findIndex((m) => m.iso === selectedIsoMonth);
    if (idx >= 0 && idx < months.length - 1) scrollToMonth(months[idx + 1].iso);
    else setMonthsBack(monthsBack + 3);
  };
  const nextMonth = () => {
    // "Next" (go forward in time) = idx - 1 under the reverse sort.
    const idx = months.findIndex((m) => m.iso === selectedIsoMonth);
    if (idx > 0) scrollToMonth(months[idx - 1].iso);
    else setMonthsAhead(monthsAhead + 3);
  };
  const jumpToDate = () => {
    // Simple: jump forward or back by prompting via alert alternative — placeholder for MVP
    // Users can already use prev/next; jump-to-date UI can be a future enhancement.
    goToday();
  };

  const selectedMonth = useMemo(() => months.find((m) => m.iso === selectedIsoMonth) || months[0], [months, selectedIsoMonth]);

  if (loading && !data) {
    return <View style={styles.centered}><ActivityIndicator color={theme.color.brand} /></View>;
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.color.surface }} edges={["top"]}>
      <View style={styles.header}>
        <Text style={styles.title}>CALENDAR</Text>
        <View style={styles.toolbar}>
          <Pressable testID="cal-prev" onPress={prevMonth} style={styles.iconBtn}><Ionicons name="chevron-back" size={18} color={theme.color.brand} /></Pressable>
          <Pressable testID="cal-today" onPress={goToday} style={styles.todayBtn}><Text style={styles.todayBtnText}>TODAY</Text></Pressable>
          <Pressable testID="cal-next" onPress={nextMonth} style={styles.iconBtn}><Ionicons name="chevron-forward" size={18} color={theme.color.brand} /></Pressable>
          <Pressable testID="cal-history" onPress={() => router.push("/reality-history" as any)} style={styles.iconBtn}>
            <Ionicons name="time" size={16} color={theme.color.brand} />
          </Pressable>
          <Pressable testID="cal-upload" onPress={() => router.push("/roster-upload")} style={styles.uploadBtn}>
            <Ionicons name="cloud-upload-outline" size={14} color="#fff" />
            <Text style={styles.uploadBtnText}>UPLOAD</Text>
          </Pressable>
        </View>
      </View>

      {activeJob ? (
        <Pressable testID="cal-job-banner" onPress={() => router.push("/roster-upload")} style={styles.banner}>
          <ActivityIndicator size="small" color={theme.color.brand} />
          <View style={{ flex: 1 }}>
            <Text style={styles.bannerTitle}>{activeJob.message || "Your roster is being processed..."}</Text>
            <Text style={styles.bannerSub}>{activeJob.progress || 0}% · Tap to view progress</Text>
          </View>
          <Ionicons name="chevron-forward" size={16} color={theme.color.brand} />
        </Pressable>
      ) : null}

      <ScrollView
        ref={scrollRef}
        contentContainerStyle={{ padding: 16, paddingBottom: 60 }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}
        stickyHeaderIndices={[]}
      >
        {selectedMonth ? (
          <View style={styles.jumpRow}>
            <Text style={styles.selectedMonthLabel}>{selectedMonth.label.toUpperCase()}</Text>
            <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap" }}>
              {months.map((m) => (
                <Pressable
                  key={m.iso}
                  testID={`cal-month-chip-${m.iso.slice(0,7)}`}
                  onPress={() => scrollToMonth(m.iso)}
                  style={[styles.monthChip, selectedIsoMonth === m.iso && styles.monthChipActive, !m.has_data && styles.monthChipEmpty]}
                >
                  <Text style={[styles.monthChipText, selectedIsoMonth === m.iso && { color: "#fff" }]}>
                    {m.label.slice(0, 3).toUpperCase()}
                  </Text>
                </Pressable>
              ))}
            </View>
          </View>
        ) : null}

        {months.map((m: any) => (
          <View
            key={m.iso}
            onLayout={(e) => { monthOffsetsRef.current[m.iso] = e.nativeEvent.layout.y; }}
            style={styles.monthBlock}
          >
            <View style={styles.monthHeader}>
              <Text style={styles.monthLabel}>{m.label}</Text>
              {!m.has_data ? <Text style={styles.emptyBadge}>NO DATA · UPLOAD ROSTER</Text> : null}
            </View>
            <View style={styles.weekdayRow}>
              {WEEKDAYS.map((w, i) => <Text key={i} style={styles.weekday}>{w}</Text>)}
            </View>
            <View style={styles.grid}>
              {Array.from({ length: firstWeekdayOffset(m.iso) }).map((_, i) => (
                <View key={`pad-${i}`} style={styles.dayCellEmpty} />
              ))}
              {m.days.map((d: any) => {
                const isToday = d.date === today;
                const hasActivity = activities.some((a) => a.date_local === d.date);
                return (
                  <Pressable
                    key={d.date}
                    testID={`cal-day-${d.date}`}
                    onPress={() => d.workout_id ? router.push(`/workout/${d.workout_id}`) : setEditDate(d.date)}
                    onLongPress={() => setAddActivityDate(d.date)}
                    style={[styles.dayCell, isToday && styles.todayCell]}
                  >
                    <Text style={[styles.dayNum, isToday && { color: theme.color.brand, fontWeight: "800" }]}>{d.day}</Text>
                    {/* Iter 100 — glanceable roster-context chip: flight
                        number / layover city / STBY / OFF. Icon-only in
                        the tight monthly grid; the code chips render on
                        the week strip / hero card instead. */}
                    <RosterDayChip
                      day={{ day_type: d.duty_type, flights: d.flights, layover_city: d.layover_city }}
                      size="sm"
                      showCode={false}
                      testID={`cal-day-chip-${d.date}`}
                    />
                    {d.load ? <View style={[styles.loadDot, { backgroundColor: loadColor(d.load) }]} /> : null}
                    {hasActivity ? <View style={styles.activityDot} /> : null}
                    {d.completed ? <Ionicons name="checkmark" size={9} color={theme.color.green} /> : null}
                    {d.key_session ? <Ionicons name="star" size={9} color={theme.color.brand} /> : null}
                  </Pressable>
                );
              })}
            </View>
          </View>
        ))}

        {data?.rosters?.length ? (
          <View style={styles.historyBlock}>
            <Text style={styles.sectionTitle}>ROSTER HISTORY</Text>
            {data.rosters.map((r: any) => (
              <View key={r.id} style={styles.historyRow} testID={`cal-history-${r.id}`}>
                <View style={[styles.historyDot, { backgroundColor: r.is_active ? theme.color.green : theme.color.textDim }]} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.historyDate}>{r.start_date} → {r.end_date}</Text>
                  <Text style={styles.historySub}>
                    {r.day_count} days · {(r.confidence_avg || 0.5).toFixed(2)} conf ·{" "}
                    {r.is_active ? "ACTIVE" : "archived"}{r.source_filename ? ` · ${r.source_filename}` : ""}
                  </Text>
                </View>
              </View>
            ))}
          </View>
        ) : null}
      </ScrollView>

      <Pressable testID="cal-fab-activity" onPress={() => setAddActivityDate(today || new Date().toISOString().slice(0,10))} style={styles.fabActivity}>
        <Ionicons name="tennisball" size={18} color="#fff" />
      </Pressable>
      <Pressable testID="cal-fab-add" onPress={() => setEditDate(today || new Date().toISOString().slice(0,10))} style={styles.fab}>
        <Ionicons name="add" size={22} color="#fff" />
      </Pressable>

      <DayEditModal
        visible={!!editDate}
        date={editDate}
        onClose={() => setEditDate(null)}
        onSaved={load}
      />
      <AddActivityModal
        visible={!!addActivityDate}
        initialDate={addActivityDate || undefined}
        onClose={() => setAddActivityDate(null)}
        onCreated={() => { setAddActivityDate(null); load(); }}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  centered: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: theme.color.surface },
  header: { paddingHorizontal: 16, paddingTop: 12, paddingBottom: 8, borderBottomWidth: 1, borderBottomColor: theme.color.border },
  title: { color: theme.color.text, fontSize: 20, fontWeight: "900", letterSpacing: 2, marginBottom: 8 },
  toolbar: { flexDirection: "row", alignItems: "center", gap: 8 },
  iconBtn: { width: 34, height: 34, borderRadius: 6, alignItems: "center", justifyContent: "center", backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  todayBtn: { paddingHorizontal: 14, paddingVertical: 8, backgroundColor: theme.color.surface2, borderRadius: 6, borderWidth: 1, borderColor: theme.color.brand },
  todayBtnText: { color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 1.5 },
  uploadBtn: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 8, backgroundColor: theme.color.brand, borderRadius: 6, marginLeft: "auto" },
  uploadBtnText: { color: "#fff", fontSize: 11, fontWeight: "800", letterSpacing: 1.5 },

  banner: { flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 16, paddingVertical: 12, backgroundColor: theme.color.brandTint, borderBottomWidth: 1, borderBottomColor: theme.color.brand },
  bannerTitle: { color: theme.color.text, fontSize: 13, fontWeight: "700" },
  bannerSub: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },

  jumpRow: { marginBottom: 14, gap: 10 },
  selectedMonthLabel: { color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 2 },
  monthChip: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  monthChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  // Iter181 · Empty-month chips were fading to 0.55 which combined with a
  // textMuted (black in Light) label made them read as barely-legible
  // dark-grey on pink. Ease the opacity and switch label to WHITE on the
  // red chip surface for consistent Pure-Rule contrast.
  monthChipEmpty: { opacity: 0.75 },
  monthChipText: { color: theme.color.onRed, fontSize: 11, fontWeight: "800", letterSpacing: 1 },

  monthBlock: { marginBottom: 20, backgroundColor: theme.color.surface2, borderRadius: 10, borderWidth: 1, borderColor: theme.color.border, padding: 12 },
  monthHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 8 },
  monthLabel: { color: theme.color.onRed, fontSize: 14, fontWeight: "800", letterSpacing: 1 },
  emptyBadge: { color: theme.color.onRed, fontSize: 11, fontWeight: "800", letterSpacing: 1.5 },
  weekdayRow: { flexDirection: "row", marginBottom: 4 },
  weekday: { flex: 1, textAlign: "center", color: theme.color.onRed, fontSize: 11, fontWeight: "800", letterSpacing: 1 },
  grid: { flexDirection: "row", flexWrap: "wrap" },
  dayCell: { width: "14.28%", aspectRatio: 1, alignItems: "center", justifyContent: "center", padding: 2, gap: 2 },
  dayCellEmpty: { width: "14.28%", aspectRatio: 1 },
  todayCell: { backgroundColor: theme.color.brandTint, borderRadius: 6 },
  dayNum: { color: theme.color.onRed, fontSize: 12 },
  loadDot: { width: 6, height: 6, borderRadius: 3 },
  activityDot: { width: 5, height: 5, borderRadius: 2.5, backgroundColor: theme.color.brand, borderWidth: 1, borderColor: theme.color.surface },

  historyBlock: { marginTop: 10, padding: 14, backgroundColor: theme.color.surface2, borderRadius: 10, borderWidth: 1, borderColor: theme.color.border },
  sectionTitle: { color: theme.color.onRed, fontSize: 11, fontWeight: "800", letterSpacing: 2, marginBottom: 10 },
  historyRow: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  historyDot: { width: 8, height: 8, borderRadius: 4 },
  historyDate: { color: theme.color.onRed, fontSize: 12, fontWeight: "700" },
  historySub: { color: theme.color.onRed, fontSize: 11, marginTop: 2, letterSpacing: 0.5 },
  fab: {
    position: "absolute", right: 20, bottom: 24,
    width: 52, height: 52, borderRadius: 26,
    backgroundColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
    shadowColor: "#000", shadowOpacity: 0.35, shadowRadius: 6, elevation: 6,
  },
  fabActivity: {
    position: "absolute", right: 20, bottom: 88,
    width: 46, height: 46, borderRadius: 23,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
    shadowColor: "#000", shadowOpacity: 0.35, shadowRadius: 6, elevation: 6,
  },
});
