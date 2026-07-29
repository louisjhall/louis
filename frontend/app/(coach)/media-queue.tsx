/**
 * Coach Flight Support Media Queue — Persona × Slot matrix
 *
 * Coach-facing screen that surfaces every exercise flagged by the Flight
 * Support media resolver, together with the exact (persona × slot) cells
 * still missing.  Rows are sorted so PILOT-missing entries surface first
 * (see Msg 679 · Phase 2 · Coach Media Queue UI Matrix).
 *
 * Backend endpoint: GET /api/coach/flight-support/media-queue
 *   query: status=all|needs_media|complete,
 *          persona_missing=any|pilot|louis|female,
 *          search=<substring>, limit=<int>
 *
 * Coach can click a row → deep-link to /(coach)/exercises for that exercise
 * so they can upload/generate the missing frames.
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput,
  ActivityIndicator, RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Persona = "pilot" | "louis" | "female";
type Slot = "start" | "mid" | "end";

type MatrixRow = {
  exercise_id: string;
  exercise_name: string;
  status: "needs_media" | "complete";
  preferred_persona: Persona;
  matrix: Record<Persona, Record<Slot, boolean>>;
  missing: Record<Persona, Slot[]>;
  covered: number;
  total_cells: number;
  flight_support_contexts: string[];
  updated_at?: string;
};

type Stats = {
  total: number;
  needs_media: number;
  complete: number;
  pilot_missing_count: number;
  louis_missing_count: number;
  female_missing_count: number;
};

const PERSONAS: Persona[] = ["pilot", "louis", "female"];
const SLOTS: Slot[] = ["start", "mid", "end"];

type StatusFilter = "all" | "needs_media" | "complete";
type PersonaFilter = "any" | Persona;

export default function CoachMediaQueue() {
  const router = useRouter();
  const [rows, setRows] = useState<MatrixRow[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<StatusFilter>("needs_media");
  const [personaFilter, setPersonaFilter] = useState<PersonaFilter>("pilot");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams({
        status,
        persona_missing: personaFilter,
        search,
        limit: "300",
      }).toString();
      const r = await api<{ items: MatrixRow[]; stats: Stats }>(
        `/coach/flight-support/media-queue?${qs}`
      );
      setRows(r.items || []);
      setStats(r.stats || null);
    } catch {
      /* silent */
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [status, personaFilter, search]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    load();
  }, [load]);

  const openExercise = useCallback((row: MatrixRow) => {
    // Deep link to the coach exercise editor, which already handles image
    // upload / Atlas generation.  We pass the exercise name in the pathname.
    router.push({
      pathname: "/(coach)/exercises",
      params: { focus: row.exercise_name },
    });
  }, [router]);

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <View style={{ flex: 1 }}>
          <Text style={styles.eyebrow}>FLIGHT SUPPORT · MEDIA QUEUE</Text>
          <Text style={styles.title}>
            Persona <Text style={styles.brandRed}>Coverage</Text>
          </Text>
        </View>
      </View>

      {/* Stats strip */}
      <View style={styles.statsRow}>
        <StatPill label="TOTAL" value={stats?.total ?? 0} tone="neutral" />
        <StatPill label="NEEDS MEDIA" value={stats?.needs_media ?? 0} tone="warn" />
        <StatPill label="COMPLETE" value={stats?.complete ?? 0} tone="ok" />
        <StatPill label="PILOT ✕" value={stats?.pilot_missing_count ?? 0} tone="danger" />
        <StatPill label="LOUIS ✕" value={stats?.louis_missing_count ?? 0} tone="warn" />
        <StatPill label="FEMALE ✕" value={stats?.female_missing_count ?? 0} tone="warn" />
      </View>

      {/* Filters */}
      <View style={styles.filtersRow}>
        <View style={styles.searchWrap}>
          <Ionicons name="search" size={14} color={theme.color.textDim} />
          <TextInput
            value={search}
            onChangeText={setSearch}
            onSubmitEditing={load}
            returnKeyType="search"
            placeholder="Search exercise name…"
            placeholderTextColor={theme.color.textDim}
            style={styles.searchInput}
            testID="mq-search"
          />
        </View>
        <ChipGroup
          value={status}
          onChange={(v) => setStatus(v as StatusFilter)}
          options={[
            { key: "all", label: "ALL" },
            { key: "needs_media", label: "NEEDS MEDIA" },
            { key: "complete", label: "COMPLETE" },
          ]}
          testIDPrefix="mq-status"
        />
        <ChipGroup
          value={personaFilter}
          onChange={(v) => setPersonaFilter(v as PersonaFilter)}
          options={[
            { key: "any", label: "ANY MISSING" },
            { key: "pilot", label: "PILOT ✕" },
            { key: "louis", label: "LOUIS ✕" },
            { key: "female", label: "FEMALE ✕" },
          ]}
          testIDPrefix="mq-persona"
        />
      </View>

      <ScrollView
        contentContainerStyle={styles.body}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={theme.color.brand}
          />
        }
      >
        {loading && rows.length === 0 ? (
          <View style={styles.centered}>
            <ActivityIndicator color={theme.color.brand} />
          </View>
        ) : rows.length === 0 ? (
          <View style={styles.centered}>
            <Ionicons name="checkmark-done-circle" size={40} color={theme.color.textDim} />
            <Text style={styles.emptyT}>Nothing in the queue.</Text>
            <Text style={styles.emptyDim}>
              Every exercise touched by Flight Support has its {personaFilter === "any" ? "personas" : personaFilter.toUpperCase()} frames.
            </Text>
          </View>
        ) : (
          rows.map((r) => (
            <Pressable
              key={r.exercise_id}
              onPress={() => openExercise(r)}
              style={styles.card}
              testID={`mq-row-${r.exercise_id}`}
            >
              <View style={styles.cardHeader}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.name}>{r.exercise_name || "Untitled"}</Text>
                  <Text style={styles.sub}>
                    {r.covered}/{r.total_cells} cells · preferred {r.preferred_persona.toUpperCase()}
                  </Text>
                </View>
                {r.status === "complete" ? (
                  <View style={[styles.statusPill, { backgroundColor: "rgba(34,197,94,0.14)" }]}>
                    <Ionicons name="checkmark-circle" size={12} color="#22C55E" />
                    <Text style={[styles.statusPillT, { color: "#22C55E" }]}>COMPLETE</Text>
                  </View>
                ) : (
                  <View style={[styles.statusPill, { backgroundColor: "rgba(245,158,11,0.14)" }]}>
                    <Ionicons name="alert-circle" size={12} color={theme.color.amber} />
                    <Text style={[styles.statusPillT, { color: theme.color.amber }]}>NEEDS MEDIA</Text>
                  </View>
                )}
              </View>

              {/* Matrix */}
              <View style={styles.matrix}>
                <View style={styles.matrixHeaderRow}>
                  <Text style={styles.matrixHeaderCell}> </Text>
                  {SLOTS.map((s) => (
                    <Text key={s} style={styles.matrixHeaderCell}>
                      {s.toUpperCase()}
                    </Text>
                  ))}
                </View>
                {PERSONAS.map((p) => (
                  <View key={p} style={styles.matrixRow}>
                    <Text
                      style={[
                        styles.matrixRowLabel,
                        p === r.preferred_persona && { color: theme.color.brand },
                      ]}
                    >
                      {p.toUpperCase()}
                    </Text>
                    {SLOTS.map((s) => {
                      const ok = r.matrix?.[p]?.[s];
                      return (
                        <View
                          key={s}
                          style={[
                            styles.cell,
                            ok ? styles.cellOk : styles.cellMissing,
                          ]}
                        >
                          <Ionicons
                            name={ok ? "checkmark" : "close"}
                            size={14}
                            color={ok ? "#22C55E" : theme.color.textDim}
                          />
                        </View>
                      );
                    })}
                  </View>
                ))}
              </View>

              <View style={styles.footerRow}>
                <Text style={styles.footerHint}>
                  Tap to open exercise editor & upload the missing frames.
                </Text>
                <Ionicons name="chevron-forward" size={16} color={theme.color.textDim} />
              </View>
            </Pressable>
          ))
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

/* -------------------------------------------------------------------------
 * Sub-components
 * ---------------------------------------------------------------------- */

function StatPill({ label, value, tone }: {
  label: string;
  value: number;
  tone: "neutral" | "ok" | "warn" | "danger";
}) {
  const color =
    tone === "ok" ? "#22C55E" :
    tone === "warn" ? theme.color.amber :
    tone === "danger" ? theme.color.brand :
    theme.color.text;
  return (
    <View style={statStyles.pill}>
      <Text style={statStyles.label}>{label}</Text>
      <Text style={[statStyles.value, { color }]}>{value}</Text>
    </View>
  );
}

function ChipGroup<T extends string>({ value, onChange, options, testIDPrefix }: {
  value: T;
  onChange: (v: T) => void;
  options: { key: T; label: string }[];
  testIDPrefix?: string;
}) {
  return (
    <View style={chipStyles.wrap}>
      {options.map((o) => (
        <Pressable
          key={o.key}
          onPress={() => onChange(o.key)}
          style={[
            chipStyles.chip,
            value === o.key && chipStyles.chipActive,
          ]}
          testID={testIDPrefix ? `${testIDPrefix}-${o.key}` : undefined}
        >
          <Text style={[
            chipStyles.chipT,
            value === o.key && chipStyles.chipActiveT,
          ]}>
            {o.label}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: theme.space.xl,
    paddingTop: theme.space.md,
    paddingBottom: theme.space.sm,
  },
  eyebrow: {
    color: theme.color.textDim,
    fontSize: 10,
    letterSpacing: 1.4,
    fontWeight: "700",
  },
  title: { color: theme.color.text, fontSize: 24, fontWeight: "800", marginTop: 2 },
  brandRed: { color: theme.color.brand },

  statsRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: theme.space.sm,
    paddingHorizontal: theme.space.xl,
    paddingBottom: theme.space.sm,
  },

  filtersRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: theme.space.sm,
    paddingHorizontal: theme.space.xl,
    paddingBottom: theme.space.md,
    alignItems: "center",
  },
  searchWrap: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.md,
    paddingHorizontal: theme.space.md,
    height: 36,
    minWidth: 220,
    flex: 1,
    borderWidth: 1,
    borderColor: theme.color.border,
  },
  searchInput: {
    flex: 1,
    color: theme.color.text,
    fontSize: 13,
    marginLeft: theme.space.sm,
    paddingVertical: 0,
  },

  body: {
    paddingHorizontal: theme.space.xl,
    paddingBottom: theme.space.xxl,
    gap: theme.space.md,
  },

  centered: {
    alignItems: "center",
    justifyContent: "center",
    padding: theme.space.xxl,
    gap: theme.space.sm,
  },
  emptyT: {
    color: theme.color.text,
    fontSize: 15,
    fontWeight: "700",
    marginTop: theme.space.sm,
  },
  emptyDim: {
    color: theme.color.textDim,
    fontSize: 12,
    textAlign: "center",
    maxWidth: 320,
  },

  card: {
    backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.lg,
    borderWidth: 1,
    borderColor: theme.color.border,
    padding: theme.space.lg,
    gap: theme.space.md,
  },
  cardHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: theme.space.md,
  },
  name: { color: theme.color.text, fontSize: 16, fontWeight: "700" },
  sub: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },

  statusPill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: theme.space.sm,
    paddingVertical: 4,
    borderRadius: theme.radius.pill,
  },
  statusPillT: { fontSize: 10, fontWeight: "800", letterSpacing: 0.8 },

  matrix: {
    backgroundColor: theme.color.surface3,
    borderRadius: theme.radius.md,
    padding: theme.space.sm,
  },
  matrixHeaderRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: theme.space.sm,
    paddingBottom: theme.space.xs,
  },
  matrixHeaderCell: {
    flex: 1,
    color: theme.color.textDim,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 1,
    textAlign: "center",
  },
  matrixRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: theme.space.sm,
    paddingVertical: 4,
  },
  matrixRowLabel: {
    flex: 1,
    color: theme.color.text,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 1,
  },
  cell: {
    flex: 1,
    height: 30,
    marginHorizontal: 2,
    borderRadius: theme.radius.sm,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
  },
  cellOk: {
    backgroundColor: "rgba(34,197,94,0.10)",
    borderColor: "rgba(34,197,94,0.35)",
  },
  cellMissing: {
    backgroundColor: theme.color.surface,
    borderColor: theme.color.border,
    borderStyle: "dashed",
  },

  footerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  footerHint: {
    color: theme.color.textDim,
    fontSize: 11,
  },
});

const statStyles = StyleSheet.create({
  pill: {
    backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.color.border,
    paddingHorizontal: theme.space.md,
    paddingVertical: 6,
    minWidth: 84,
  },
  label: {
    color: theme.color.textDim,
    fontSize: 9,
    letterSpacing: 1.2,
    fontWeight: "700",
  },
  value: {
    fontSize: 18,
    fontWeight: "800",
    marginTop: 2,
  },
});

const chipStyles = StyleSheet.create({
  wrap: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
  },
  chip: {
    paddingHorizontal: theme.space.md,
    paddingVertical: 6,
    borderRadius: theme.radius.pill,
    backgroundColor: theme.color.surface2,
    borderWidth: 1,
    borderColor: theme.color.border,
  },
  chipActive: {
    backgroundColor: theme.color.brandTint,
    borderColor: theme.color.brand,
  },
  chipT: {
    color: theme.color.textDim,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 1,
  },
  chipActiveT: { color: theme.color.text },
});
