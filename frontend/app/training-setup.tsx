/**
 * training-setup.tsx — Task 1.3
 *
 * The mandatory "get to know your training" flow. Fires:
 *   - Right after signup (via redirect in /_layout.tsx)
 *   - For existing users missing any of the 8 essential fields (top-up)
 *
 * Design principles:
 *   - Only shows PAGES with missing fields. If only equipment is missing,
 *     users see 1 page. If everything is missing, they see 3.
 *   - Partial saves are OK — every page saves independently, so users can
 *     close the app between pages and resume where they left off.
 *   - Each field is required to advance to the next page. No skip.
 *   - On completion, routes to `/` (home).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ScrollView, ActivityIndicator, Alert,
  TextInput, KeyboardAvoidingView, Platform,
} from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";
import { theme } from "@/src/lib/theme";
import { api } from "@/src/lib/api";

// ---------------------------------------------------------------------------
// Static option catalogues (mirror backend)
// ---------------------------------------------------------------------------

const GOAL_OPTIONS: { id: string; label: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { id: "lose_fat",       label: "Lose body fat",   icon: "trending-down" },
  { id: "build_muscle",   label: "Build muscle",    icon: "barbell" },
  { id: "marathon",       label: "Marathon",        icon: "walk" },
  { id: "half_marathon",  label: "Half marathon",   icon: "walk-outline" },
  { id: "10k",            label: "10K",             icon: "footsteps" },
  { id: "5k",             label: "5K",              icon: "footsteps-outline" },
  { id: "hyrox",          label: "HYROX",           icon: "flame" },
  { id: "ironman",        label: "Ironman",         icon: "trophy" },
  { id: "olympic_tri",    label: "Olympic tri",     icon: "trophy-outline" },
  { id: "general_fitness", label: "General fitness", icon: "fitness" },
  { id: "improve_health", label: "Improve health",  icon: "medkit" },
  { id: "mobility",       label: "Improve mobility", icon: "body" },
  { id: "reduce_pain",    label: "Reduce pain",     icon: "bandage" },
  { id: "return_injury",  label: "Return from injury", icon: "medkit-outline" },
  { id: "airline_medical", label: "Pass airline medical", icon: "checkmark-done" },
];

const TRAINING_DAYS = [1, 2, 3, 4, 5, 6, 7];
const TIME_HOME     = [15, 30, 45, 60, 75, 90];
const TIME_LAYOVER  = [0, 15, 30, 45, 60];

const EQUIPMENT_OPTIONS: { id: string; label: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { id: "bodyweight_only",  label: "Bodyweight only",     icon: "body" },
  { id: "dumbbells",        label: "Dumbbells",           icon: "barbell" },
  { id: "kettlebells",      label: "Kettlebells",         icon: "barbell-outline" },
  { id: "barbell",          label: "Barbell + plates",    icon: "flash" },
  { id: "resistance_bands", label: "Resistance bands",    icon: "reload" },
  { id: "pullup_bar",       label: "Pull-up bar",         icon: "arrow-up" },
  { id: "bench",            label: "Bench",               icon: "layers" },
  { id: "treadmill",        label: "Treadmill",           icon: "speedometer" },
  { id: "bike",             label: "Bike / turbo",        icon: "bicycle" },
  { id: "rower",            label: "Rower",               icon: "boat" },
  { id: "cable",            label: "Cable machine",       icon: "git-network" },
  { id: "mat",              label: "Yoga / mobility mat", icon: "square-outline" },
];

const HOTEL_GYM_OPTIONS: { id: string; label: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { id: "always",    label: "Always",    icon: "checkmark-done" },
  { id: "often",     label: "Often",     icon: "checkmark-circle" },
  { id: "sometimes", label: "Sometimes", icon: "help-circle" },
  { id: "rare",      label: "Rarely",    icon: "remove-circle" },
  { id: "never",     label: "Never",     icon: "close-circle" },
];

const NO_GO_OPTIONS: { id: string; label: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { id: "none",              label: "None — I can do all movements", icon: "checkmark-done" },
  { id: "running",           label: "Running / impact",              icon: "walk" },
  { id: "jumping",           label: "Jumping",                       icon: "trending-up" },
  { id: "overhead_pressing", label: "Overhead pressing",             icon: "arrow-up" },
  { id: "deep_squatting",    label: "Deep squatting",                icon: "arrow-down" },
  { id: "deadlifts",         label: "Deadlifts",                     icon: "barbell" },
  { id: "heavy_lifting",     label: "Heavy lifting",                 icon: "barbell-outline" },
];

// ---------------------------------------------------------------------------
// Page config — each "page" collects a related group of fields
// ---------------------------------------------------------------------------

type PageId = "goals" | "time" | "environment";
type SetupStatus = { complete: boolean; missing_fields: string[] };

const PAGE_FIELDS: Record<PageId, string[]> = {
  goals:       ["primary_goal"],                                    // secondary_goals is not required
  time:        ["training_days", "time_home", "time_layover"],
  environment: ["equipment_home", "hotel_gyms", "injuries", "no_go_movements"],
};

export default function TrainingSetupScreen() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<SetupStatus>({ complete: false, missing_fields: [] });
  const [pageIdx, setPageIdx] = useState(0);

  // Local answer state
  const [primaryGoal, setPrimaryGoal] = useState<string>("");
  const [trainingDays, setTrainingDays] = useState<number | null>(null);
  const [timeHome, setTimeHome] = useState<number | null>(null);
  const [timeLayover, setTimeLayover] = useState<number | null>(null);
  const [equipment, setEquipment] = useState<string[]>([]);
  const [hotelGym, setHotelGym] = useState<string>("");
  const [injuries, setInjuries] = useState<string>("");
  const [noneInjuries, setNoneInjuries] = useState(false);
  const [noGoMovements, setNoGoMovements] = useState<string[]>([]);

  // ── Load current setup status ─────────────────────────────────────────────
  const load = useCallback(async () => {
    try {
      const r = await api<SetupStatus>("/profile/setup-status");
      setStatus(r);
      if (r.complete) {
        // Nothing to do — bounce to home.
        router.replace("/");
        return;
      }
    } catch (e: any) {
      Alert.alert("Could not load your setup", e?.message || "Please retry.");
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => { load(); }, [load]);

  // Compute which of the 3 pages actually need to be shown for THIS user.
  const activePages: PageId[] = useMemo(() => {
    if (!status.missing_fields?.length) return [];
    const pages: PageId[] = [];
    (Object.keys(PAGE_FIELDS) as PageId[]).forEach((pid) => {
      const has = PAGE_FIELDS[pid].some((f) => status.missing_fields.includes(f));
      if (has) pages.push(pid);
    });
    return pages;
  }, [status.missing_fields]);

  const currentPage = activePages[pageIdx];
  const isLastPage = pageIdx >= activePages.length - 1;

  // Fields required by the CURRENT page (based on what's missing)
  const requiredOnPage = useMemo(() => {
    if (!currentPage) return [];
    return PAGE_FIELDS[currentPage].filter((f) => status.missing_fields.includes(f));
  }, [currentPage, status.missing_fields]);

  // ── Validation per page ───────────────────────────────────────────────────
  const canAdvance = useMemo(() => {
    if (!currentPage) return false;
    if (currentPage === "goals") {
      return !requiredOnPage.includes("primary_goal") || !!primaryGoal;
    }
    if (currentPage === "time") {
      const daysOk = !requiredOnPage.includes("training_days") || trainingDays !== null;
      const homeOk = !requiredOnPage.includes("time_home") || timeHome !== null;
      const lyOk   = !requiredOnPage.includes("time_layover") || timeLayover !== null;
      return daysOk && homeOk && lyOk;
    }
    if (currentPage === "environment") {
      const eqOk = !requiredOnPage.includes("equipment_home") || equipment.length > 0;
      const hgOk = !requiredOnPage.includes("hotel_gyms") || !!hotelGym;
      const injOk = !requiredOnPage.includes("injuries") || noneInjuries || injuries.trim().length > 0;
      const ngOk = !requiredOnPage.includes("no_go_movements") || noGoMovements.length > 0;
      return eqOk && hgOk && injOk && ngOk;
    }
    return false;
  }, [currentPage, requiredOnPage, primaryGoal, trainingDays, timeHome, timeLayover, equipment, hotelGym, injuries, noneInjuries, noGoMovements]);

  // ── Advance / submit ──────────────────────────────────────────────────────
  const submitCurrentPage = useCallback(async () => {
    if (!canAdvance || saving) return;
    setSaving(true);
    try {
      const body: Record<string, any> = {};
      if (currentPage === "goals") {
        if (requiredOnPage.includes("primary_goal")) body.primary_goal = primaryGoal;
      }
      if (currentPage === "time") {
        if (requiredOnPage.includes("training_days")) body.training_days = trainingDays;
        if (requiredOnPage.includes("time_home"))     body.time_home = timeHome;
        if (requiredOnPage.includes("time_layover"))  body.time_layover = timeLayover;
      }
      if (currentPage === "environment") {
        if (requiredOnPage.includes("equipment_home"))    body.equipment_home = equipment;
        if (requiredOnPage.includes("hotel_gyms"))        body.hotel_gym_reliability = hotelGym;
        if (requiredOnPage.includes("injuries"))          body.injuries = noneInjuries ? "None" : injuries.trim();
        if (requiredOnPage.includes("no_go_movements"))   body.no_go_movements = noGoMovements;
      }
      const r = await api<SetupStatus>("/profile/training-setup", { method: "POST", body });
      setStatus(r);
      if (r.complete) {
        router.replace("/");
        return;
      }
      // Move to the next active page (index-safe)
      const nextPages = (Object.keys(PAGE_FIELDS) as PageId[]).filter((pid) =>
        PAGE_FIELDS[pid].some((f) => r.missing_fields.includes(f))
      );
      if (nextPages.length === 0) {
        router.replace("/");
      } else {
        setPageIdx(0);   // recalc active pages from scratch
      }
    } catch (e: any) {
      Alert.alert("Could not save", e?.message || "Please retry.");
    } finally {
      setSaving(false);
    }
  }, [canAdvance, saving, currentPage, requiredOnPage, primaryGoal, trainingDays, timeHome, timeLayover, equipment, hotelGym, injuries, noneInjuries, noGoMovements, router]);

  if (loading) {
    return (
      <SafeAreaView style={s.wrap}>
        <View style={s.centered}>
          <ActivityIndicator color={theme.color.brand} />
        </View>
      </SafeAreaView>
    );
  }

  if (activePages.length === 0) {
    // Shouldn't hit — load() would have bounced. Defensive.
    return null;
  }

  const stepLabel = `${pageIdx + 1} of ${activePages.length}`;

  return (
    <SafeAreaView style={s.wrap} edges={["top"]}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <View style={s.header}>
          <Text style={s.eyebrow}>TRAINING SETUP · {stepLabel}</Text>
          {currentPage === "goals"       && <Text style={s.title}>What&apos;s the ONE thing?</Text>}
          {currentPage === "time"        && <Text style={s.title}>How you&apos;ll actually train</Text>}
          {currentPage === "environment" && <Text style={s.title}>Your training environment</Text>}
        </View>

        <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 120 }}>
          {currentPage === "goals" && (
            <>
              <Text style={s.help}>
                Pick the goal that matters most right now. Louis will use this to plan every session — everything else (fat loss, general fitness, injury rehab) can happen alongside.
              </Text>
              <View style={s.grid}>
                {GOAL_OPTIONS.map((g) => {
                  const active = primaryGoal === g.id;
                  return (
                    <Pressable
                      key={g.id}
                      testID={`setup-goal-${g.id}`}
                      onPress={() => setPrimaryGoal(g.id)}
                      style={[s.chip, active && s.chipActive]}
                    >
                      <Ionicons name={g.icon} size={14} color={active ? "#fff" : theme.color.textMuted} />
                      <Text style={[s.chipT, active && { color: "#fff" }]}>{g.label}</Text>
                    </Pressable>
                  );
                })}
              </View>
            </>
          )}

          {currentPage === "time" && (
            <>
              {requiredOnPage.includes("training_days") && (
                <>
                  <Text style={s.qLabel}>How many days per week can you realistically train?</Text>
                  <View style={s.rowChips}>
                    {TRAINING_DAYS.map((d) => {
                      const active = trainingDays === d;
                      return (
                        <Pressable
                          key={d} testID={`setup-days-${d}`}
                          onPress={() => setTrainingDays(d)}
                          style={[s.pill, active && s.pillActive]}
                        >
                          <Text style={[s.pillT, active && { color: "#fff" }]}>{d}</Text>
                        </Pressable>
                      );
                    })}
                  </View>
                </>
              )}
              {requiredOnPage.includes("time_home") && (
                <>
                  <Text style={s.qLabel}>How much time do you have per session at home?</Text>
                  <View style={s.rowChips}>
                    {TIME_HOME.map((m) => {
                      const active = timeHome === m;
                      return (
                        <Pressable
                          key={m} testID={`setup-tHome-${m}`}
                          onPress={() => setTimeHome(m)}
                          style={[s.pill, active && s.pillActive]}
                        >
                          <Text style={[s.pillT, active && { color: "#fff" }]}>{m} min</Text>
                        </Pressable>
                      );
                    })}
                  </View>
                </>
              )}
              {requiredOnPage.includes("time_layover") && (
                <>
                  <Text style={s.qLabel}>Time per session on a layover?</Text>
                  <View style={s.rowChips}>
                    {TIME_LAYOVER.map((m) => {
                      const active = timeLayover === m;
                      const label = m === 0 ? "None" : `${m} min`;
                      return (
                        <Pressable
                          key={m} testID={`setup-tLy-${m}`}
                          onPress={() => setTimeLayover(m)}
                          style={[s.pill, active && s.pillActive]}
                        >
                          <Text style={[s.pillT, active && { color: "#fff" }]}>{label}</Text>
                        </Pressable>
                      );
                    })}
                  </View>
                </>
              )}
            </>
          )}

          {currentPage === "environment" && (
            <>
              {requiredOnPage.includes("equipment_home") && (
                <>
                  <Text style={s.qLabel}>What equipment do you have at home? (pick all that apply)</Text>
                  <View style={s.grid}>
                    {EQUIPMENT_OPTIONS.map((eq) => {
                      const active = equipment.includes(eq.id);
                      return (
                        <Pressable
                          key={eq.id} testID={`setup-eq-${eq.id}`}
                          onPress={() => {
                            if (eq.id === "bodyweight_only") {
                              // Selecting bodyweight-only clears everything else
                              setEquipment(active ? [] : ["bodyweight_only"]);
                            } else {
                              setEquipment((cur) => {
                                const stripped = cur.filter((x) => x !== "bodyweight_only");
                                return active ? stripped.filter((x) => x !== eq.id) : [...stripped, eq.id];
                              });
                            }
                          }}
                          style={[s.chip, active && s.chipActive]}
                        >
                          <Ionicons name={eq.icon} size={14} color={active ? "#fff" : theme.color.textMuted} />
                          <Text style={[s.chipT, active && { color: "#fff" }]}>{eq.label}</Text>
                        </Pressable>
                      );
                    })}
                  </View>
                </>
              )}
              {requiredOnPage.includes("hotel_gyms") && (
                <>
                  <Text style={s.qLabel}>How reliable are hotel gyms on your typical layovers?</Text>
                  <View style={{ gap: 8 }}>
                    {HOTEL_GYM_OPTIONS.map((o) => {
                      const active = hotelGym === o.id;
                      return (
                        <Pressable
                          key={o.id} testID={`setup-hg-${o.id}`}
                          onPress={() => setHotelGym(o.id)}
                          style={[s.rowOpt, active && s.rowOptActive]}
                        >
                          <Ionicons name={o.icon} size={16} color={active ? "#fff" : theme.color.brand} />
                          <Text style={[s.rowOptT, active && { color: "#fff" }]}>{o.label}</Text>
                        </Pressable>
                      );
                    })}
                  </View>
                </>
              )}
              {requiredOnPage.includes("injuries") && (
                <>
                  <Text style={s.qLabel}>Any current injuries or things to avoid?</Text>
                  <TextInput
                    testID="setup-injuries"
                    value={injuries}
                    onChangeText={(t) => { setInjuries(t); if (t.trim()) setNoneInjuries(false); }}
                    placeholder="e.g. Slight knee pain when running downhill"
                    placeholderTextColor={theme.color.textDim}
                    multiline
                    style={s.textArea}
                  />
                  <Pressable
                    testID="setup-injuries-none"
                    onPress={() => { setNoneInjuries((v) => !v); if (!noneInjuries) setInjuries(""); }}
                    style={[s.noneChip, noneInjuries && s.chipActive]}
                  >
                    <Ionicons name="checkmark-circle" size={14} color={noneInjuries ? "#fff" : theme.color.brand} />
                    <Text style={[s.noneChipT, noneInjuries && { color: "#fff" }]}>NO INJURIES CURRENTLY</Text>
                  </Pressable>
                </>
              )}
              {requiredOnPage.includes("no_go_movements") && (
                <>
                  <Text style={s.qLabel}>Any movements you must avoid?</Text>
                  <View style={s.grid}>
                    {NO_GO_OPTIONS.map((o) => {
                      const active = noGoMovements.includes(o.id);
                      return (
                        <Pressable
                          key={o.id} testID={`setup-ng-${o.id}`}
                          onPress={() => {
                            if (o.id === "none") {
                              setNoGoMovements(active ? [] : ["none"]);
                            } else {
                              setNoGoMovements((cur) => {
                                const stripped = cur.filter((x) => x !== "none");
                                return active ? stripped.filter((x) => x !== o.id) : [...stripped, o.id];
                              });
                            }
                          }}
                          style={[s.chip, active && s.chipActive]}
                        >
                          <Ionicons name={o.icon} size={14} color={active ? "#fff" : theme.color.textMuted} />
                          <Text style={[s.chipT, active && { color: "#fff" }]}>{o.label}</Text>
                        </Pressable>
                      );
                    })}
                  </View>
                </>
              )}
            </>
          )}
        </ScrollView>

        <View style={s.footer}>
          <Pressable
            testID="setup-continue"
            onPress={submitCurrentPage}
            disabled={!canAdvance || saving}
            style={[s.cta, (!canAdvance || saving) && { opacity: 0.55 }]}
          >
            {saving ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <Text style={s.ctaT}>{isLastPage ? "FINISH SETUP" : "CONTINUE →"}</Text>
            )}
          </Pressable>
          <Text style={s.footerHelp}>
            Louis needs these to plan properly. All fields required.
          </Text>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: theme.color.background },
  centered: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: { paddingHorizontal: theme.space.lg, paddingTop: theme.space.md, paddingBottom: theme.space.sm },
  eyebrow: { color: theme.color.brand, fontSize: 10, letterSpacing: 2, fontWeight: "800" },
  title: { color: theme.color.text, fontSize: 22, fontWeight: "900", marginTop: 6 },
  help: { color: theme.color.textMuted, fontSize: 12, lineHeight: 18, marginBottom: theme.space.md },
  qLabel: { color: theme.color.text, fontSize: 13, fontWeight: "700", marginTop: theme.space.md, marginBottom: 8 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  rowChips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 12, paddingVertical: 10,
    borderRadius: theme.radius.pill,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
    minHeight: 40,
  },
  chipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipT: { color: theme.color.textMuted, fontSize: 12, fontWeight: "700" },
  pill: {
    paddingHorizontal: 14, paddingVertical: 10,
    borderRadius: theme.radius.pill,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
    minHeight: 40, minWidth: 54, alignItems: "center", justifyContent: "center",
  },
  pillActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  pillT: { color: theme.color.text, fontSize: 12, fontWeight: "700" },
  rowOpt: {
    flexDirection: "row", alignItems: "center", gap: 10,
    padding: theme.space.md, borderRadius: theme.radius.md,
    backgroundColor: theme.color.surface,
    borderWidth: 1, borderColor: theme.color.border,
    minHeight: 48,
  },
  rowOptActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  rowOptT: { color: theme.color.text, fontSize: 13, fontWeight: "700" },
  textArea: {
    backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.md,
    color: theme.color.text,
    padding: theme.space.md,
    borderWidth: 1, borderColor: theme.color.border,
    minHeight: 80, fontSize: 13,
    textAlignVertical: "top",
  },
  noneChip: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    marginTop: 10, paddingVertical: 12,
    borderRadius: theme.radius.md,
    borderWidth: 1, borderColor: theme.color.brand,
    backgroundColor: "transparent",
  },
  noneChipT: { color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 1.5 },
  footer: {
    padding: theme.space.lg, borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: theme.color.border, backgroundColor: theme.color.background,
  },
  cta: {
    backgroundColor: theme.color.brand,
    paddingVertical: 15, borderRadius: theme.radius.md,
    alignItems: "center", justifyContent: "center",
    minHeight: 50,
  },
  ctaT: { color: "#fff", fontSize: 13, fontWeight: "900", letterSpacing: 1.5 },
  footerHelp: { color: theme.color.textMuted, fontSize: 11, textAlign: "center", marginTop: 8 },
});
