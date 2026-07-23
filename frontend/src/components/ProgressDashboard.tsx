/**
 * ProgressDashboard — Iter 94t (Phase 3)
 *
 * Goal-adaptive Progress screen. Reads /api/progress/dashboard and renders
 * cards + charts tailored to the client's main goal:
 *   fat_loss  → weight + waist trend + photos + nutrition avg
 *   running   → long-run duration + adherence
 *   strength  → key lifts (est. 1RM) + adherence
 *   health    → consistency + habits + recovery
 *
 * Charts via react-native-gifted-charts (widely used, expo-compatible).
 * Empty states are explicit ("Not enough data yet") — never a broken chart.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, RefreshControl,
  ActivityIndicator, TextInput, Alert,
} from "react-native";
import { Image } from "expo-image";
import { LineChart, BarChart } from "react-native-gifted-charts";
import * as ImagePicker from "expo-image-picker";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useFocusEffect } from "expo-router";
import { api, API_BASE, getToken } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast } from "@/src/lib/ux";

type Series = { date: string; value: number };
type Photo = { id: string; date: string; angle: string; url: string; expires_at_epoch: number };
type Dashboard = {
  goal_class: "fat_loss" | "running" | "strength" | "health";
  goal_label?: string;
  phase?: string;
  adherence: { weeks: number; workouts_planned: number; workouts_completed: number; workouts_missed: number; adherence_pct: number | null };
  nutrition_last_14d: { days: number; days_logged: number; avg_calories: number; avg_protein_g: number };
  habits_last_7d: { days: number; completed: number; planned: number; pct: number | null };
  body: {
    latest?: any; starting?: any;
    weight_change_kg?: number | null; waist_change_cm?: number | null;
    series_weight: Series[]; series_waist: Series[];
  };
  running: { count: number; long_run_min: number; total_min: number; series: Series[] };
  strength: {
    sessions: number;
    key_lifts: { exercise: string; sessions: number; first_1rm: number; latest_1rm: number; best_1rm: number; series: Series[] }[];
  };
  photos: Photo[];
};

function sparkFrom(series: Series[]): { value: number; label?: string }[] {
  return series.map((s, i) => ({
    value: Number(s.value) || 0,
    label: i === 0 || i === series.length - 1 ? s.date.slice(5) : undefined,
  }));
}
function fmtN(n: number | null | undefined, unit = ""): string {
  if (n === null || n === undefined || isNaN(n as any)) return "—";
  return `${Math.round(Number(n) * 10) / 10}${unit}`;
}
function fmtDelta(n: number | null | undefined, unit = ""): { text: string; positive: boolean } {
  if (n === null || n === undefined || isNaN(n as any)) return { text: "—", positive: true };
  const val = Number(n);
  const sign = val > 0 ? "+" : "";
  return { text: `${sign}${Math.round(val * 10) / 10}${unit}`, positive: val <= 0 };
}

export function ProgressDashboard() {
  const router = useRouter();
  const [d, setD] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [showLogSheet, setShowLogSheet] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api<Dashboard>("/progress/dashboard");
      setD(r);
    } catch (e: any) {
      toast(e?.message || "Couldn't load progress.", "error");
    } finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (loading && !d) {
    return (
      <SafeAreaView style={styles.root}>
        <ActivityIndicator color={theme.color.brand} style={{ marginTop: 60 }} />
      </SafeAreaView>
    );
  }
  if (!d) return null;

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={10}><Ionicons name="chevron-back" size={24} color={theme.color.text} /></Pressable>
        <Text style={styles.headerTitle}>PROGRESS</Text>
        <Pressable onPress={() => setShowLogSheet(true)} hitSlop={10} testID="prog-log-open">
          <Ionicons name="add-circle" size={26} color={theme.color.brand} />
        </Pressable>
      </View>
      <ScrollView
        contentContainerStyle={{ padding: 16, paddingBottom: 60 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={theme.color.brand} />}
      >
        <SummaryCard d={d} />
        <AdherenceCard d={d} />

        {d.goal_class === "fat_loss" ? <FatLossPanel d={d} onReload={load} /> : null}
        {d.goal_class === "running" ? <RunningPanel d={d} /> : null}
        {d.goal_class === "strength" ? <StrengthPanel d={d} /> : null}
        {d.goal_class === "health" ? <HealthPanel d={d} /> : null}

        {/* Progress photos always available */}
        <PhotosCard photos={d.photos} onReload={load} />
      </ScrollView>

      {showLogSheet ? (
        <LogSheet
          goalClass={d.goal_class}
          onClose={() => setShowLogSheet(false)}
          onSaved={() => { setShowLogSheet(false); load(); }}
        />
      ) : null}
    </SafeAreaView>
  );
}

/* -------------------------------------------------------------------------- */
/*  Reusable cards                                                             */
/* -------------------------------------------------------------------------- */

function SummaryCard({ d }: { d: Dashboard }) {
  return (
    <View style={styles.card}>
      <Text style={styles.eyebrow}>YOUR GOAL</Text>
      <Text style={styles.goalT}>{(d.goal_label || d.goal_class).toString().replace(/_/g, " ").toUpperCase()}</Text>
      {d.phase ? <Text style={styles.phaseT}>Phase: {d.phase}</Text> : null}
    </View>
  );
}

function AdherenceCard({ d }: { d: Dashboard }) {
  const a = d.adherence;
  return (
    <View style={styles.card}>
      <Text style={styles.eyebrow}>ADHERENCE · LAST {a.weeks} WEEKS</Text>
      <View style={styles.row3}>
        <Metric label="COMPLETED" value={a.workouts_completed} />
        <Metric label="MISSED" value={a.workouts_missed} />
        <Metric label="OVERALL" value={a.adherence_pct != null ? `${a.adherence_pct}%` : "—"} />
      </View>
      <View style={styles.habitRow}>
        <Ionicons name="checkmark-circle" size={13} color={theme.color.brand} />
        <Text style={styles.habitT}>
          {d.habits_last_7d.pct != null ? `${d.habits_last_7d.pct}% habits · last 7d` : "No habit data yet"}
        </Text>
      </View>
    </View>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <View style={styles.metric}>
      <Text style={styles.metricLbl}>{label}</Text>
      <Text style={styles.metricV}>{String(value)}</Text>
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/*  Fat-loss panel                                                             */
/* -------------------------------------------------------------------------- */

function FatLossPanel({ d, onReload }: { d: Dashboard; onReload: () => void }) {
  const w = d.body.series_weight;
  const wa = d.body.series_waist;
  return (
    <>
      <View style={styles.card}>
        <Text style={styles.eyebrow}>BODY · WEIGHT</Text>
        {w.length === 0 ? (
          <EmptyState label="No weight logs yet. Tap + to add your first entry." />
        ) : (
          <>
            <View style={styles.row3}>
              <Metric label="LATEST" value={fmtN(d.body.latest?.weight_kg, "kg")} />
              <Metric label="STARTING" value={fmtN(d.body.starting?.weight_kg, "kg")} />
              <ChangeMetric label="CHANGE" delta={d.body.weight_change_kg} unit="kg" />
            </View>
            <ChartHolder>
              <LineChart
                data={sparkFrom(w)}
                thickness={2.5}
                color={theme.color.brand}
                dataPointsColor={theme.color.brand}
                xAxisColor={theme.color.divider}
                yAxisColor={theme.color.divider}
                yAxisTextStyle={{ color: theme.color.textMuted, fontSize: 10 }}
                xAxisLabelTextStyle={{ color: theme.color.textMuted, fontSize: 9 }}
                hideRules
                spacing={Math.max(24, Math.min(60, 320 / Math.max(2, w.length)))}
                initialSpacing={12}
                curved
              />
            </ChartHolder>
          </>
        )}
      </View>

      <View style={styles.card}>
        <Text style={styles.eyebrow}>BODY · WAIST</Text>
        {wa.length === 0 ? (
          <EmptyState label="Not enough data yet. Log a waist measurement to start tracking." />
        ) : (
          <>
            <View style={styles.row3}>
              <Metric label="LATEST" value={fmtN(d.body.latest?.waist_cm, "cm")} />
              <Metric label="STARTING" value={fmtN(d.body.starting?.waist_cm, "cm")} />
              <ChangeMetric label="CHANGE" delta={d.body.waist_change_cm} unit="cm" />
            </View>
            <ChartHolder>
              <LineChart
                data={sparkFrom(wa)}
                thickness={2.5}
                color={theme.color.green}
                dataPointsColor={theme.color.green}
                xAxisColor={theme.color.divider}
                yAxisColor={theme.color.divider}
                yAxisTextStyle={{ color: theme.color.textMuted, fontSize: 10 }}
                xAxisLabelTextStyle={{ color: theme.color.textMuted, fontSize: 9 }}
                hideRules
                spacing={Math.max(24, Math.min(60, 320 / Math.max(2, wa.length)))}
                initialSpacing={12}
                curved
              />
            </ChartHolder>
          </>
        )}
      </View>

      <View style={styles.card}>
        <Text style={styles.eyebrow}>NUTRITION · 14 DAYS AVG</Text>
        {d.nutrition_last_14d.days_logged === 0 ? (
          <EmptyState label="Log meals to see your averages." />
        ) : (
          <View style={styles.row3}>
            <Metric label="CAL/DAY" value={d.nutrition_last_14d.avg_calories} />
            <Metric label="PROTEIN/DAY" value={`${d.nutrition_last_14d.avg_protein_g}g`} />
            <Metric label="DAYS LOGGED" value={`${d.nutrition_last_14d.days_logged}/14`} />
          </View>
        )}
      </View>
      {/* Reload hook usage prevents unused param warning */}
      {void onReload}
    </>
  );
}

/* -------------------------------------------------------------------------- */
/*  Running panel                                                              */
/* -------------------------------------------------------------------------- */

function RunningPanel({ d }: { d: Dashboard }) {
  return (
    <View style={styles.card}>
      <Text style={styles.eyebrow}>RUNNING · LAST 12 WEEKS</Text>
      {d.running.count === 0 ? (
        <EmptyState label="No runs logged yet. Complete a run session or tap + to log one." />
      ) : (
        <>
          <View style={styles.row3}>
            <Metric label="SESSIONS" value={d.running.count} />
            <Metric label="LONGEST" value={`${d.running.long_run_min}m`} />
            <Metric label="TOTAL" value={`${Math.round(d.running.total_min / 60)}h`} />
          </View>
          {d.running.series.length >= 2 ? (
            <ChartHolder>
              <LineChart
                data={sparkFrom(d.running.series)}
                thickness={2.5}
                color={theme.color.brand}
                dataPointsColor={theme.color.brand}
                xAxisColor={theme.color.divider}
                yAxisColor={theme.color.divider}
                yAxisTextStyle={{ color: theme.color.textMuted, fontSize: 10 }}
                xAxisLabelTextStyle={{ color: theme.color.textMuted, fontSize: 9 }}
                hideRules
                spacing={40}
                initialSpacing={12}
                curved
              />
            </ChartHolder>
          ) : (
            <Text style={styles.emptySub}>Long-run trend appears after 2+ long runs.</Text>
          )}
        </>
      )}
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/*  Strength panel                                                             */
/* -------------------------------------------------------------------------- */

function StrengthPanel({ d }: { d: Dashboard }) {
  if (d.strength.key_lifts.length === 0) {
    return (
      <View style={styles.card}>
        <Text style={styles.eyebrow}>STRENGTH · KEY LIFTS</Text>
        <EmptyState label="No lifts logged yet. Log a set to start tracking your key movements." />
      </View>
    );
  }
  return (
    <>
      {d.strength.key_lifts.map((lift) => (
        <View key={lift.exercise} style={styles.card}>
          <Text style={styles.eyebrow}>KEY LIFT · {lift.exercise.toUpperCase()}</Text>
          <View style={styles.row3}>
            <Metric label="LATEST 1RM" value={`${fmtN(lift.latest_1rm)}kg`} />
            <Metric label="BEST 1RM" value={`${fmtN(lift.best_1rm)}kg`} />
            <Metric label="SESSIONS" value={lift.sessions} />
          </View>
          {lift.series.length >= 2 ? (
            <ChartHolder>
              <BarChart
                data={sparkFrom(lift.series).map((s, i) => ({
                  value: s.value,
                  label: i === 0 || i === lift.series.length - 1 ? s.label : undefined,
                  frontColor: theme.color.brand,
                }))}
                barWidth={16}
                spacing={12}
                initialSpacing={12}
                xAxisColor={theme.color.divider}
                yAxisColor={theme.color.divider}
                yAxisTextStyle={{ color: theme.color.textMuted, fontSize: 10 }}
                xAxisLabelTextStyle={{ color: theme.color.textMuted, fontSize: 9 }}
                hideRules
              />
            </ChartHolder>
          ) : null}
        </View>
      ))}
    </>
  );
}

/* -------------------------------------------------------------------------- */
/*  Health / general panel                                                     */
/* -------------------------------------------------------------------------- */

function HealthPanel({ d }: { d: Dashboard }) {
  return (
    <View style={styles.card}>
      <Text style={styles.eyebrow}>CONSISTENCY & RECOVERY</Text>
      <View style={styles.row3}>
        <Metric label="COMPLETED" value={d.adherence.workouts_completed} />
        <Metric label="MISSED" value={d.adherence.workouts_missed} />
        <Metric label="HABITS 7d" value={d.habits_last_7d.pct != null ? `${d.habits_last_7d.pct}%` : "—"} />
      </View>
      {d.nutrition_last_14d.days_logged > 0 ? (
        <Text style={styles.smallNote}>
          Averaging {d.nutrition_last_14d.avg_calories} kcal · {d.nutrition_last_14d.avg_protein_g}g protein over the last {d.nutrition_last_14d.days_logged} days.
        </Text>
      ) : (
        <EmptyState label="Log meals to see nutrition consistency." />
      )}
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/*  Photos                                                                     */
/* -------------------------------------------------------------------------- */

function PhotosCard({ photos, onReload }: { photos: Photo[]; onReload: () => void }) {
  const pick = async () => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) return;
    const r = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images, base64: true, quality: 0.7,
    });
    if (r.canceled || !r.assets[0]?.base64) return;
    try {
      await api("/progress/photo/base64", {
        method: "POST",
        body: { angle: "front", photo_b64: r.assets[0].base64!, mime: r.assets[0].mimeType || "image/jpeg" },
      });
      toast("Photo added to your progress.", "success");
      onReload();
    } catch (e: any) {
      toast(e?.message || "Couldn't upload photo.", "error");
    }
  };
  const remove = async (id: string) => {
    Alert.alert("Delete photo?", "This can't be undone.", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Delete", style: "destructive", onPress: async () => {
          try { await api(`/progress/photo/${id}`, { method: "DELETE" }); onReload(); }
          catch (e: any) { toast(e?.message || "Delete failed.", "error"); }
        },
      },
    ]);
  };
  const [token, setToken] = useState<string>("");
  useEffect(() => { getToken().then((t) => setToken(t || "")); }, []);
  return (
    <View style={styles.card}>
      <View style={{ flexDirection: "row", alignItems: "center" }}>
        <Text style={[styles.eyebrow, { flex: 1 }]}>PROGRESS PHOTOS</Text>
        <Pressable onPress={pick} testID="prog-photo-add" style={styles.chipBtn}>
          <Ionicons name="camera" size={12} color={theme.color.brand} />
          <Text style={styles.chipBtnT}>ADD</Text>
        </Pressable>
      </View>
      <Text style={styles.smallNote}>Photos are private — only you and Louis can see them.</Text>
      {photos.length === 0 ? (
        <EmptyState label="No photos yet. Optional but great for tracking change over time." />
      ) : (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 8 }}>
          {photos.map((p) => (
            <Pressable
              key={p.id}
              onLongPress={() => remove(p.id)}
              style={styles.photo}
            >
              <Image
                source={{ uri: `${API_BASE}${p.url}` }}
                style={{ width: 110, height: 150, borderRadius: 8 }}
                contentFit="cover"
                cachePolicy="memory-disk"
              />
              <Text style={styles.photoDate}>{p.date.slice(5)}</Text>
              <Text style={styles.photoAngle}>{p.angle.toUpperCase()}</Text>
            </Pressable>
          ))}
        </ScrollView>
      )}
      {token ? null : null}
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/*  Log sheet — bottom sheet to add a body / running / strength entry          */
/* -------------------------------------------------------------------------- */

function LogSheet({
  goalClass, onClose, onSaved,
}: { goalClass: string; onClose: () => void; onSaved: () => void }) {
  const [kind, setKind] = useState<"body" | "running" | "strength">(
    goalClass === "running" ? "running" : goalClass === "strength" ? "strength" : "body"
  );
  const [weight, setWeight] = useState("");
  const [waist, setWaist] = useState("");
  const [runMin, setRunMin] = useState("");
  const [runType, setRunType] = useState("long_run");
  const [exName, setExName] = useState("");
  const [sets, setSets] = useState("3");
  const [reps, setReps] = useState("5");
  const [load, setLoad] = useState("");
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      if (kind === "body") {
        await api("/progress/body", { method: "POST", body: {
          weight_kg: weight ? parseFloat(weight) : null,
          waist_cm: waist ? parseFloat(waist) : null,
        }});
      } else if (kind === "running") {
        await api("/progress/running", { method: "POST", body: {
          duration_min: parseFloat(runMin), session_type: runType,
        }});
      } else {
        await api("/progress/strength", { method: "POST", body: {
          exercise_name: exName, sets: parseInt(sets), reps: parseInt(reps), load_kg: parseFloat(load),
        }});
      }
      onSaved();
    } catch (e: any) {
      toast(e?.message || "Save failed.", "error");
    } finally { setSaving(false); }
  };

  const canSave = kind === "body"
    ? !!(weight || waist)
    : kind === "running"
      ? !!(runMin && parseFloat(runMin) > 0)
      : !!(exName && load);

  return (
    <View style={styles.sheetRoot}>
      <Pressable style={styles.sheetBackdrop} onPress={onClose} />
      <View style={styles.sheet}>
        <View style={styles.sheetHead}>
          <Text style={styles.sheetTitle}>ADD PROGRESS ENTRY</Text>
          <Pressable onPress={onClose} hitSlop={12}><Ionicons name="close" size={22} color={theme.color.text} /></Pressable>
        </View>
        <View style={styles.tabRow}>
          {(["body", "running", "strength"] as const).map((t) => (
            <Pressable key={t} onPress={() => setKind(t)} style={[styles.tab, kind === t && styles.tabActive]} testID={`prog-tab-${t}`}>
              <Text style={[styles.tabT, kind === t && { color: "#fff" }]}>{t.toUpperCase()}</Text>
            </Pressable>
          ))}
        </View>
        {kind === "body" ? (
          <>
            <Field label="WEIGHT (kg)"><TextInput style={styles.input} value={weight} onChangeText={setWeight} keyboardType="decimal-pad" placeholder="82" placeholderTextColor={theme.color.textDim} testID="prog-weight" /></Field>
            <Field label="WAIST (cm) — optional"><TextInput style={styles.input} value={waist} onChangeText={setWaist} keyboardType="decimal-pad" placeholder="86" placeholderTextColor={theme.color.textDim} testID="prog-waist" /></Field>
          </>
        ) : kind === "running" ? (
          <>
            <Field label="DURATION (min)"><TextInput style={styles.input} value={runMin} onChangeText={setRunMin} keyboardType="decimal-pad" placeholder="45" placeholderTextColor={theme.color.textDim} testID="prog-run-min" /></Field>
            <View style={styles.tabRow}>
              {(["long_run", "easy_run", "tempo", "intervals"] as const).map((t) => (
                <Pressable key={t} onPress={() => setRunType(t)} style={[styles.tab, runType === t && styles.tabActive]}>
                  <Text style={[styles.tabT, runType === t && { color: "#fff" }]}>{t.replace(/_/g, " ").toUpperCase()}</Text>
                </Pressable>
              ))}
            </View>
          </>
        ) : (
          <>
            <Field label="EXERCISE"><TextInput style={styles.input} value={exName} onChangeText={setExName} placeholder="Back Squat" placeholderTextColor={theme.color.textDim} testID="prog-ex-name" /></Field>
            <View style={{ flexDirection: "row", gap: 8 }}>
              <View style={{ flex: 1 }}><Field label="SETS"><TextInput style={styles.input} value={sets} onChangeText={setSets} keyboardType="number-pad" placeholderTextColor={theme.color.textDim} /></Field></View>
              <View style={{ flex: 1 }}><Field label="REPS"><TextInput style={styles.input} value={reps} onChangeText={setReps} keyboardType="number-pad" placeholderTextColor={theme.color.textDim} /></Field></View>
              <View style={{ flex: 1 }}><Field label="LOAD (kg)"><TextInput style={styles.input} value={load} onChangeText={setLoad} keyboardType="decimal-pad" placeholder="100" placeholderTextColor={theme.color.textDim} testID="prog-load" /></Field></View>
            </View>
          </>
        )}
        <Pressable
          onPress={save}
          disabled={!canSave || saving}
          style={[styles.saveBtn, (!canSave || saving) && { opacity: 0.4 }]}
          testID="prog-save"
        >
          {saving ? <ActivityIndicator color="#fff" /> : <Text style={styles.saveBtnT}>SAVE ENTRY</Text>}
        </Pressable>
      </View>
    </View>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <View style={{ marginTop: 12 }}>
      <Text style={styles.fieldLbl}>{label}</Text>
      {children}
    </View>
  );
}

function EmptyState({ label }: { label: string }) {
  return (
    <View style={styles.emptyBox}>
      <Ionicons name="analytics-outline" size={22} color={theme.color.textMuted} />
      <Text style={styles.emptyT}>{label}</Text>
    </View>
  );
}

function ChartHolder({ children }: { children: React.ReactNode }) {
  return <View style={{ marginTop: 12, alignItems: "center" }}>{children}</View>;
}

function ChangeMetric({ label, delta, unit }: { label: string; delta?: number | null; unit: string }) {
  const d = fmtDelta(delta, unit);
  return (
    <View style={styles.metric}>
      <Text style={styles.metricLbl}>{label}</Text>
      <Text style={[styles.metricV, { color: delta == null ? theme.color.text : d.positive ? theme.color.green : theme.color.red }]}>
        {d.text}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    padding: 16, borderBottomWidth: 1, borderBottomColor: theme.color.divider,
  },
  headerTitle: { color: theme.color.text, fontSize: 14, letterSpacing: 2, fontWeight: "900" },

  card: {
    backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.md,
    borderWidth: 1, borderColor: theme.color.border,
    padding: 14, marginBottom: 12,
  },
  eyebrow: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 2, marginBottom: 8 },
  goalT: { color: theme.color.text, fontSize: 18, fontWeight: "900", letterSpacing: 1 },
  phaseT: { color: theme.color.textMuted, fontSize: 12, marginTop: 4 },

  row3: { flexDirection: "row", gap: 8 },
  metric: { flex: 1, backgroundColor: theme.color.surface3, borderRadius: 8, padding: 10 },
  metricLbl: { color: theme.color.textMuted, fontSize: 9, letterSpacing: 1.5, fontWeight: "800", marginBottom: 4 },
  metricV: { color: theme.color.text, fontSize: 15, fontWeight: "900" },

  habitRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 10 },
  habitT: { color: theme.color.textMuted, fontSize: 12 },
  smallNote: { color: theme.color.textMuted, fontSize: 11, marginTop: 6, lineHeight: 15 },

  emptyBox: { flexDirection: "row", alignItems: "center", gap: 10, padding: 12, borderRadius: 8, backgroundColor: theme.color.surface3, marginTop: 4 },
  emptyT: { color: theme.color.textMuted, fontSize: 12, flex: 1, lineHeight: 16 },
  emptySub: { color: theme.color.textMuted, fontSize: 11, marginTop: 8 },

  chipBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 8, borderWidth: 1, borderColor: theme.color.border },
  chipBtnT: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },

  photo: { marginRight: 8, alignItems: "center" },
  photoDate: { color: theme.color.text, fontSize: 10, marginTop: 4, fontWeight: "800" },
  photoAngle: { color: theme.color.textMuted, fontSize: 9, marginTop: 1, letterSpacing: 1 },

  sheetRoot: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0, justifyContent: "flex-end" },
  sheetBackdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.55)" },
  sheet: {
    backgroundColor: theme.color.surface,
    borderTopLeftRadius: 20, borderTopRightRadius: 20,
    padding: 16, paddingBottom: 32,
  },
  sheetHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 10 },
  sheetTitle: { color: theme.color.text, fontSize: 12, fontWeight: "900", letterSpacing: 2 },

  tabRow: { flexDirection: "row", gap: 6, marginTop: 6, flexWrap: "wrap" },
  tab: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8, borderWidth: 1, borderColor: theme.color.border },
  tabActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  tabT: { color: theme.color.textMuted, fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },

  fieldLbl: { color: theme.color.textMuted, fontSize: 10, fontWeight: "800", letterSpacing: 1.5, marginBottom: 4 },
  input: { backgroundColor: theme.color.surface3, borderRadius: 8, color: theme.color.text, padding: 10, borderWidth: 1, borderColor: theme.color.border },

  saveBtn: { marginTop: 16, padding: 14, borderRadius: 10, backgroundColor: theme.color.brand, alignItems: "center" },
  saveBtnT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 1.5 },
});
