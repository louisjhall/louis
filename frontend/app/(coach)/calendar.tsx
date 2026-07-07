import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme, loadColor } from "@/src/lib/theme";

const DAY_ABBR = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];

function dowFromISO(iso: string): string {
  const d = new Date(iso + "T00:00:00Z");
  return DAY_ABBR[d.getUTCDay()];
}
function dayFromISO(iso: string): string {
  return iso.slice(8, 10);
}
function monthFromISO(iso: string): string {
  const m = parseInt(iso.slice(5, 7), 10);
  return ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"][m - 1] || "";
}

export default function CoachCalendar() {
  const router = useRouter();
  const [days, setDays] = useState(14);
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<any>({ clients: [], dates: [] });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api<any>(`/coach/calendar?days=${days}`));
    } finally {
      setLoading(false);
    }
  }, [days]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const dates: string[] = data.dates || [];
  const clients: any[] = data.clients || [];
  const today = new Date().toISOString().slice(0, 10);

  return (
    <ScrollView
      style={styles.root}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}
    >
      <View style={styles.header}>
        <View>
          <Text style={styles.h1}>CALENDAR</Text>
          <Text style={styles.sub}>All clients · next {days} days</Text>
        </View>
        <View style={styles.rangeRow}>
          {[7, 14, 28].map((n) => (
            <Pressable
              key={n}
              testID={`cal-range-${n}`}
              onPress={() => setDays(n)}
              style={[styles.rangeChip, days === n && styles.rangeChipActive]}
            >
              <Text style={[styles.rangeText, days === n && { color: "#fff" }]}>{n}D</Text>
            </Pressable>
          ))}
        </View>
      </View>

      <View style={styles.legend}>
        <LegendDot color={loadColor("green")} label="REST/GREEN" />
        <LegendDot color={loadColor("amber")} label="MODERATE" />
        <LegendDot color={loadColor("red")} label="HARD/KEY" />
        <LegendDot color={loadColor("blue")} label="CARDIO" />
        <LegendDot color={loadColor("purple")} label="EVENT" />
        <LegendDot color={loadColor("grey")} label="OFF/DUTY" />
      </View>

      {loading && !clients.length ? (
        <ActivityIndicator color={theme.color.brand} style={{ marginTop: 40 }} />
      ) : (
        <ScrollView horizontal showsHorizontalScrollIndicator style={styles.gridWrap}>
          <View>
            {/* Header row */}
            <View style={styles.headerRow}>
              <View style={styles.clientCol}>
                <Text style={styles.headerCellText}>CLIENT</Text>
              </View>
              {dates.map((d) => {
                const isToday = d === today;
                return (
                  <View key={d} style={[styles.dayHeaderCell, isToday && styles.todayCell]}>
                    <Text style={[styles.dowText, isToday && { color: theme.color.brand }]}>{dowFromISO(d)}</Text>
                    <Text style={[styles.dayNumText, isToday && { color: theme.color.brand }]}>{dayFromISO(d)}</Text>
                    <Text style={styles.monthText}>{monthFromISO(d)}</Text>
                  </View>
                );
              })}
            </View>

            {clients.length === 0 && (
              <Text style={styles.empty}>No clients found.</Text>
            )}

            {clients.map((cl: any) => (
              <View key={cl.client_id} style={styles.clientRow}>
                <Pressable
                  testID={`cal-client-${cl.client_id}`}
                  style={styles.clientCol}
                  onPress={() => router.push(`/coach/client/${cl.client_id}` as any)}
                >
                  <Text style={styles.clientName} numberOfLines={1}>{cl.client_name}</Text>
                  {!cl.has_roster && <Text style={styles.noRoster}>NO ROSTER</Text>}
                </Pressable>
                {cl.days.map((cell: any, i: number) => {
                  const isToday = cell.date === today;
                  return (
                    <Pressable
                      key={i}
                      testID={`cal-cell-${cl.client_id}-${cell.date}`}
                      onPress={() => cell.workout_id && router.push(`/workout/${cell.workout_id}` as any)}
                      disabled={!cell.workout_id}
                      style={[
                        styles.cell,
                        isToday && styles.todayCellBorder,
                        cell.workout_id && styles.cellClickable,
                      ]}
                    >
                      <View style={[styles.loadStripe, { backgroundColor: cell.load ? loadColor(cell.load) : "transparent" }]} />
                      {cell.duty_type && !cell.workout_id && (
                        <Text style={styles.dutyText} numberOfLines={2}>{cell.duty_type}</Text>
                      )}
                      {cell.workout_id && (
                        <>
                          <Text style={styles.workoutText} numberOfLines={2}>{cell.title || "Workout"}</Text>
                          <View style={styles.cellFoot}>
                            {cell.key_session && <Ionicons name="star" size={9} color={theme.color.brand} />}
                            {cell.completed && <Ionicons name="checkmark-circle" size={10} color={theme.color.green} />}
                            {!cell.approved && <View style={styles.notApprovedDot} />}
                            <Text style={styles.cellMeta}>{cell.duration_min ? `${cell.duration_min}m` : ""}</Text>
                          </View>
                        </>
                      )}
                    </Pressable>
                  );
                })}
              </View>
            ))}
          </View>
        </ScrollView>
      )}
    </ScrollView>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
      <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: color }} />
      <Text style={styles.legendText}>{label}</Text>
    </View>
  );
}

const CELL_W = 100;
const CELL_H = 74;
const CLIENT_W = 220;

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  content: { padding: 32, paddingBottom: 80 },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 20 },
  h1: { color: theme.color.text, fontSize: 28, fontWeight: "900", letterSpacing: 2 },
  sub: { color: theme.color.textMuted, marginTop: 4 },

  rangeRow: { flexDirection: "row", gap: 6 },
  rangeChip: { paddingHorizontal: 14, paddingVertical: 8, backgroundColor: theme.color.surface2, borderRadius: 6, borderWidth: 1, borderColor: theme.color.border },
  rangeChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  rangeText: { color: theme.color.textMuted, fontWeight: "800", letterSpacing: 1 },

  legend: { flexDirection: "row", gap: 16, marginBottom: 14, flexWrap: "wrap", padding: 10, backgroundColor: theme.color.surface2, borderRadius: 8 },
  legendText: { color: theme.color.textMuted, fontSize: 10, fontWeight: "700", letterSpacing: 1 },

  gridWrap: { backgroundColor: theme.color.surface2, borderRadius: 12, borderWidth: 1, borderColor: theme.color.border, padding: 4 },

  headerRow: { flexDirection: "row", borderBottomWidth: 1, borderBottomColor: theme.color.border, paddingBottom: 4 },
  clientCol: {
    width: CLIENT_W,
    padding: 10,
    justifyContent: "center",
    borderRightWidth: 1,
    borderRightColor: theme.color.border,
  },
  headerCellText: { color: theme.color.textDim, fontSize: 10, fontWeight: "800", letterSpacing: 2 },
  dayHeaderCell: {
    width: CELL_W,
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: 8,
  },
  todayCell: { backgroundColor: theme.color.brandTint, borderRadius: 6 },
  dowText: { color: theme.color.textDim, fontSize: 10, fontWeight: "800", letterSpacing: 1.5 },
  dayNumText: { color: theme.color.text, fontSize: 20, fontWeight: "900" },
  monthText: { color: theme.color.textDim, fontSize: 9, fontWeight: "700", letterSpacing: 1.5 },

  clientRow: { flexDirection: "row", borderBottomWidth: 1, borderBottomColor: theme.color.divider, alignItems: "stretch" },
  clientName: { color: theme.color.text, fontSize: 13, fontWeight: "700" },
  noRoster: { color: theme.color.red, fontSize: 9, fontWeight: "800", letterSpacing: 1, marginTop: 4 },

  cell: {
    width: CELL_W,
    height: CELL_H,
    padding: 6,
    borderRightWidth: 1,
    borderRightColor: theme.color.divider,
    backgroundColor: theme.color.surface3,
    justifyContent: "space-between",
  },
  cellClickable: {},
  todayCellBorder: { borderTopWidth: 2, borderTopColor: theme.color.brand },
  loadStripe: { height: 3, borderRadius: 2, marginBottom: 4 },
  workoutText: { color: theme.color.text, fontSize: 10, fontWeight: "700", lineHeight: 12 },
  dutyText: { color: theme.color.textMuted, fontSize: 9, fontStyle: "italic", lineHeight: 11 },
  cellFoot: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: "auto" },
  notApprovedDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: theme.color.amber },
  cellMeta: { color: theme.color.textDim, fontSize: 9, marginLeft: "auto", fontWeight: "700" },

  empty: { color: theme.color.textMuted, textAlign: "center", padding: 40 },
});
