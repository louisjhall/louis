/**
 * Atlas Workout Player — Phase 1 rebuild
 * Swipeable tile carousel per exercise: IMAGE · HOW · VIDEO · SWAP · LOG
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput,
  ActivityIndicator, Dimensions, Image, FlatList, Vibration, Alert, Modal,
} from "react-native";
import { useLocalSearchParams, useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { ExerciseVideoPlayer, preloadExerciseVideos } from "@/src/components/ExerciseVideoPlayer";

const { width: SCREEN_W } = Dimensions.get("window");
const TILES = ["IMAGE", "HOW TO", "VIDEO", "SWAP", "LOG"] as const;

type Tile = typeof TILES[number];

/* -------------------------------------------------------------------------- */
/*  Screen                                                                    */
/* -------------------------------------------------------------------------- */
export default function AtlasPlayer() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [w, setW] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [idx, setIdx] = useState(0);
  const [tile, setTile] = useState<Tile>("IMAGE");
  const [sets, setSets] = useState<any[]>([]);
  const [prev, setPrev] = useState<any>(null);
  const [restLeft, setRestLeft] = useState(0);
  const restTimer = useRef<any>(null);
  const startedAt = useRef<number>(Date.now());
  const [now, setNow] = useState(Date.now());

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ww, s] = await Promise.all([
        api<any>(`/workouts/${id}`),
        api<any>(`/workouts/${id}/sets`).catch(() => ({ sets: [] })),
      ]);
      setW(ww); setSets(s.sets || []);
    } finally { setLoading(false); }
  }, [id]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const exercises = (w?.exercises || []) as any[];
  const total = exercises.length;
  const currentEx = exercises[idx];

  // Load previous performance when exercise changes
  useEffect(() => {
    if (!currentEx?.name) { setPrev(null); return; }
    api<any>(`/exercises/previous?name=${encodeURIComponent(currentEx.name)}`)
      .then(setPrev).catch(() => setPrev(null));
    setTile("IMAGE");
  }, [currentEx?.name]);

  // Preload videos
  useEffect(() => {
    const names = exercises.map((e) => e?.name).filter(Boolean);
    if (names.length) preloadExerciseVideos(names);
  }, [exercises]);

  // Elapsed / remaining tick
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  // Rest timer tick
  useEffect(() => {
    if (restLeft <= 0) { if (restTimer.current) clearInterval(restTimer.current); return; }
    restTimer.current = setInterval(() => {
      setRestLeft((s) => {
        if (s <= 1) {
          Vibration.vibrate([0, 300, 100, 300]);
          clearInterval(restTimer.current);
          return 0;
        }
        return s - 1;
      });
    }, 1000);
    return () => clearInterval(restTimer.current);
  }, [restLeft > 0]);

  const currentSets = useMemo(
    () => sets.filter((s) => s.exercise_index === idx).sort((a, b) => a.set_number - b.set_number),
    [sets, idx]
  );

  const completedCount = useMemo(() => {
    // count exercises with at least one logged set OR that are warmup and idx passed
    const doneIdx = new Set(sets.map((s) => s.exercise_index));
    return doneIdx.size;
  }, [sets]);
  const percent = total ? Math.round((completedCount / total) * 100) : 0;

  const elapsedMin = Math.floor((now - startedAt.current) / 60000);
  const avgMinPer = idx > 0 ? Math.max(3, Math.round(elapsedMin / Math.max(1, completedCount))) : 5;
  const remaining = avgMinPer * (total - completedCount);

  const goNext = () => { if (idx < total - 1) setIdx(idx + 1); };
  const goPrev = () => { if (idx > 0) setIdx(idx - 1); };
  const startRest = (sec: number) => setRestLeft(Math.max(0, sec));

  const finishWorkout = async () => {
    try { await api(`/workouts/${id}/complete`, { method: "POST", body: {} }); }
    catch { /* ignore */ }
    router.replace(`/workout/${id}` as any);
  };

  if (loading || !w) {
    return (
      <SafeAreaView style={styles.root} edges={["top"]}>
        <ActivityIndicator style={{ marginTop: 60 }} color={theme.color.brand} />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      {/* Top bar */}
      <View style={styles.top}>
        <Pressable onPress={() => router.back()} testID="atlas-back">
          <Ionicons name="close" size={24} color={theme.color.text} />
        </Pressable>
        <View style={{ flex: 1, alignItems: "center" }}>
          <Text style={styles.wName} numberOfLines={1}>{w.title}</Text>
          <Text style={styles.wMeta}>
            {w.location || "Home"} · {w.duration_min || 0}m · {elapsedMin}m elapsed
          </Text>
        </View>
        <View style={styles.progressCircle}>
          <Text style={styles.progressT}>{percent}%</Text>
        </View>
      </View>

      {/* Progress bar */}
      <View style={styles.pbarTrack}>
        <View style={[styles.pbarFill, { width: `${percent}%` }]} />
      </View>
      <Text style={styles.exCounter}>EXERCISE {idx + 1} OF {total} · ~{remaining} MIN REMAINING</Text>

      {/* Rest timer overlay */}
      {restLeft > 0 && (
        <View style={styles.restBar}>
          <Ionicons name="timer" size={16} color={theme.color.brand} />
          <Text style={styles.restBarT}>REST · {Math.floor(restLeft / 60)}:{String(restLeft % 60).padStart(2, "0")}</Text>
          <Pressable onPress={() => setRestLeft(restLeft + 30)} style={styles.restBtn}><Text style={styles.restBtnT}>+30</Text></Pressable>
          <Pressable onPress={() => setRestLeft(0)} style={styles.restBtn}><Text style={styles.restBtnT}>SKIP</Text></Pressable>
        </View>
      )}

      {/* Exercise name + tabs */}
      <View style={styles.exHead}>
        <Text style={styles.exName} numberOfLines={2}>{currentEx?.name || "—"}</Text>
        <Text style={styles.exTargets}>
          {currentEx?.sets ? `${currentEx.sets} × ` : ""}{currentEx?.reps || currentEx?.duration || ""}
        </Text>
      </View>

      <View style={styles.tabs}>
        {TILES.map((t) => (
          <Pressable key={t} onPress={() => setTile(t)} style={[styles.tab, tile === t && styles.tabOn]} testID={`tab-${t}`}>
            <Text style={[styles.tabT, tile === t && styles.tabTOn]}>{t}</Text>
          </Pressable>
        ))}
      </View>

      <ScrollView contentContainerStyle={styles.body}>
        {tile === "IMAGE" && <TileImage ex={currentEx} />}
        {tile === "HOW TO" && <TileHow ex={currentEx} />}
        {tile === "VIDEO" && <TileVideo ex={currentEx} />}
        {tile === "SWAP" && <TileSwap ex={currentEx} location={w.location} onPick={(n: string) => {
          // Persist as coach_notes so it's not lost
          Alert.alert("Swapped", `Atlas has swapped to: ${n}. Continue when ready.`);
        }} />}
        {tile === "LOG" && (
          <TileLog
            ex={currentEx}
            idx={idx}
            workoutId={String(id)}
            existing={currentSets}
            prev={prev}
            onLogged={(s: any) => { setSets((all) => [...all, s]); startRest(currentEx?.rest_sec || 90); }}
          />
        )}
      </ScrollView>

      {/* Bottom nav */}
      <View style={styles.bottomBar}>
        <Pressable onPress={goPrev} disabled={idx === 0} style={[styles.navBtn, idx === 0 && { opacity: 0.3 }]}>
          <Ionicons name="chevron-back" size={18} color={theme.color.text} />
          <Text style={styles.navT}>PREV</Text>
        </Pressable>
        {idx < total - 1 ? (
          <Pressable onPress={goNext} style={styles.nextBtn} testID="atlas-next">
            <Text style={styles.nextT}>NEXT EXERCISE</Text>
            <Ionicons name="chevron-forward" size={18} color="#fff" />
          </Pressable>
        ) : (
          <Pressable onPress={finishWorkout} style={styles.finishBtn} testID="atlas-finish">
            <Text style={styles.nextT}>FINISH WORKOUT</Text>
            <Ionicons name="checkmark" size={18} color="#fff" />
          </Pressable>
        )}
      </View>
    </SafeAreaView>
  );
}

/* -------------------------------------------------------------------------- */
/*  Tile 1 — Image                                                             */
/* -------------------------------------------------------------------------- */
function TileImage({ ex }: { ex: any }) {
  const [imgUrl, setImgUrl] = useState<string | null>(null);
  const [tried, setTried] = useState(false);
  useEffect(() => {
    if (!ex?.name) return;
    setImgUrl(null); setTried(false);
    api<any>(`/exercises/video?name=${encodeURIComponent(ex.name)}`)
      .then((v) => {
        setTried(true);
        setImgUrl(v?.thumbnail || v?.image || null);
      })
      .catch(() => setTried(true));
  }, [ex?.name]);

  return (
    <View style={styles.imgCard}>
      {imgUrl ? (
        <Image source={{ uri: imgUrl }} style={styles.imgHero} resizeMode="cover" />
      ) : (
        <View style={styles.imgFallback}>
          {tried ? (
            <>
              <Ionicons name="body" size={70} color={theme.color.brand} />
              <Text style={styles.imgFbT}>ATLAS IMAGE COMING SOON</Text>
              <Text style={styles.imgFbS}>Louis demos will be generated in a later update.</Text>
            </>
          ) : (
            <ActivityIndicator color={theme.color.brand} />
          )}
        </View>
      )}
      <View style={styles.imgOverlay}>
        <Text style={styles.imgOverlayT}>{ex?.name}</Text>
        <Text style={styles.imgOverlayS}>
          {ex?.sets ? `${ex.sets} sets × ${ex.reps || ex.duration || ""}` : ex?.reps || ex?.duration || ""}
        </Text>
      </View>
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/*  Tile 2 — How To                                                            */
/* -------------------------------------------------------------------------- */
function TileHow({ ex }: { ex: any }) {
  // Prefer coach-authored fields, else fall back to smart defaults
  const instructions: string[] = ex?.instructions?.length ? ex.instructions : defaultInstructions(ex);
  const cues: string[] = ex?.cues?.length ? ex.cues : defaultCues(ex);
  const mistakes: string[] = ex?.mistakes?.length ? ex.mistakes : defaultMistakes(ex);

  return (
    <View>
      <View style={styles.howCard}>
        <Text style={styles.howHead}>HOW TO PERFORM IT</Text>
        {instructions.map((s, i) => (
          <View key={i} style={styles.howStep}>
            <View style={styles.howNum}><Text style={styles.howNumT}>{i + 1}</Text></View>
            <Text style={styles.howT}>{s}</Text>
          </View>
        ))}
      </View>
      <View style={[styles.howCard, { borderColor: theme.color.green }]}>
        <Text style={[styles.howHead, { color: theme.color.green }]}>COACHING CUES</Text>
        {cues.map((c, i) => (
          <View key={i} style={styles.howRow}>
            <Ionicons name="checkmark" size={13} color={theme.color.green} />
            <Text style={styles.howT}>{c}</Text>
          </View>
        ))}
      </View>
      <View style={[styles.howCard, { borderColor: theme.color.amber }]}>
        <Text style={[styles.howHead, { color: theme.color.amber }]}>COMMON MISTAKES</Text>
        {mistakes.map((m, i) => (
          <View key={i} style={styles.howRow}>
            <Ionicons name="warning" size={13} color={theme.color.amber} />
            <Text style={styles.howT}>{m}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}

function defaultInstructions(ex: any): string[] {
  const n = String(ex?.name || "").toLowerCase();
  if (n.includes("squat")) return [
    "Start with feet shoulder-width apart, weight through mid-foot.",
    "Brace your core and keep your chest lifted throughout.",
    "Lower slowly under control — knees track over toes.",
    "Drive back up through the mid-foot, exhaling on the way up.",
  ];
  if (n.includes("deadlift") || n.includes("rdl")) return [
    "Hinge from the hips, weight over your mid-foot.",
    "Keep the bar/dumbbells close to your body throughout.",
    "Maintain a neutral spine — no rounding.",
    "Drive through your heels and squeeze glutes at the top.",
  ];
  if (n.includes("press") || n.includes("bench")) return [
    "Retract your shoulder blades and set your feet firmly.",
    "Lower the weight under control to the target line.",
    "Pause briefly, then press back up powerfully.",
    "Keep wrists stacked and elbows tracking naturally.",
  ];
  if (n.includes("row")) return [
    "Set a strong hinged position with a flat back.",
    "Pull with the elbows, not the hands.",
    "Squeeze shoulder blades together at the top.",
    "Lower under control — don't let it drop.",
  ];
  if (n.includes("plank")) return [
    "Line up shoulders directly over elbows or hands.",
    "Squeeze glutes and brace your core.",
    "Keep your hips level — don't sag or pike.",
    "Breathe steadily throughout the hold.",
  ];
  return [
    "Set up in a strong, stable position.",
    "Brace your core and control your breathing.",
    "Move slowly through the working range.",
    "Return under control — quality over speed.",
  ];
}

function defaultCues(ex: any): string[] {
  const n = String(ex?.name || "").toLowerCase();
  if (n.includes("squat")) return ["Ribs down", "Knees track toes", "Full depth", "Drive the floor away"];
  if (n.includes("deadlift")) return ["Neutral spine", "Bar close to body", "Push floor away", "Hips + shoulders rise together"];
  if (n.includes("press") || n.includes("bench")) return ["Shoulders back", "Feet planted", "Elbows tucked", "Bar-path straight"];
  if (n.includes("row")) return ["Elbows lead", "Squeeze shoulder blades", "No swinging", "Control the lower"];
  return ["Slow and controlled", "Brace your core", "Full range of motion", "Quality every rep"];
}

function defaultMistakes(ex: any): string[] {
  const n = String(ex?.name || "").toLowerCase();
  if (n.includes("squat")) return ["Rounding the back", "Knees caving in", "Rushing the descent", "Lifting too heavy"];
  if (n.includes("deadlift")) return ["Rounded lower back", "Bar drifting forward", "Hyperextending at the top", "Jerking the weight up"];
  if (n.includes("press") || n.includes("bench")) return ["Bouncing off the chest", "Flaring elbows too wide", "Feet lifting off ground", "Uneven bar path"];
  if (n.includes("row")) return ["Using momentum", "Rounding the back", "Pulling with hands", "Short range"];
  return ["Rushing the reps", "Poor form", "Lifting too heavy", "Losing tension"];
}

/* -------------------------------------------------------------------------- */
/*  Tile 3 — Video                                                             */
/* -------------------------------------------------------------------------- */
function TileVideo({ ex }: { ex: any }) {
  if (!ex?.name) return null;
  return (
    <View>
      <View style={styles.videoWrap}>
        <ExerciseVideoPlayer name={ex.name} />
      </View>
      <View style={styles.videoNote}>
        <Ionicons name="information-circle" size={14} color={theme.color.textMuted} />
        <Text style={styles.videoNoteT}>
          If video fails to play, swipe to the HOW TO tab for written coaching.
        </Text>
      </View>
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/*  Tile 4 — Swap                                                              */
/* -------------------------------------------------------------------------- */
function TileSwap({ ex, location, onPick }: { ex: any; location?: string; onPick: (name: string) => void }) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    if (!ex?.name) return;
    setLoading(true);
    api<any>(`/exercises/alternatives?name=${encodeURIComponent(ex.name)}${location ? `&location=${encodeURIComponent(location)}` : ""}`)
      .then(setData).catch(() => setData(null)).finally(() => setLoading(false));
  }, [ex?.name, location]);

  if (loading) return <ActivityIndicator color={theme.color.brand} style={{ marginTop: 40 }} />;
  const alts = data?.alternatives || [];

  return (
    <View>
      <View style={styles.atlasReco}>
        <View style={styles.atlasRecoHead}>
          <View style={styles.atlasIcon}>
            <Ionicons name="pulse" size={16} color={theme.color.brand} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.atlasRecoLbl}>ATLAS ALTERNATIVE RECOMMENDATION</Text>
            <Text style={styles.atlasRecoT}>I've identified {alts.length} equivalents that keep the same training objective.</Text>
          </View>
        </View>
        <Text style={styles.atlasRecoReason}>{data?.reason}</Text>
      </View>

      {alts.map((a: any, i: number) => (
        <View key={i} style={styles.altCard}>
          <View style={styles.altHead}>
            <View style={{ flex: 1 }}>
              <Text style={styles.altName}>{a.name}</Text>
              <View style={styles.altEqRow}>
                {(a.equipment || []).length === 0 ? (
                  <View style={styles.eqChip}><Text style={styles.eqChipT}>BODYWEIGHT</Text></View>
                ) : (
                  (a.equipment || []).map((e: string, j: number) => (
                    <View key={j} style={styles.eqChip}><Text style={styles.eqChipT}>{String(e).toUpperCase()}</Text></View>
                  ))
                )}
              </View>
            </View>
            <Pressable onPress={() => onPick(a.name)} style={styles.altPick} testID={`swap-pick-${i}`}>
              <Text style={styles.altPickT}>USE THIS</Text>
              <Ionicons name="arrow-forward" size={13} color="#fff" />
            </Pressable>
          </View>
          <Text style={styles.altWhy}>{a.why}</Text>
        </View>
      ))}
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/*  Tile 5 — Log                                                               */
/* -------------------------------------------------------------------------- */
function TileLog({ ex, idx, workoutId, existing, prev, onLogged }: {
  ex: any; idx: number; workoutId: string; existing: any[]; prev: any; onLogged: (s: any) => void;
}) {
  const targetSets = Math.max(1, parseInt(String(ex?.sets || 3), 10));
  const targetReps = ex?.reps || "10";
  const [current, setCurrent] = useState<{ reps: string; weight: string; rpe: string }>({
    reps: "", weight: prev?.suggested_load ? String(prev.suggested_load) : "", rpe: "",
  });

  const nextSet = existing.length + 1;

  const submit = async () => {
    if (nextSet > targetSets) return;
    try {
      const r = await api<any>(`/workouts/${workoutId}/sets`, {
        method: "POST",
        body: {
          workout_id: workoutId,
          exercise_index: idx,
          exercise_name: ex.name,
          set_number: nextSet,
          target_reps: String(targetReps),
          actual_reps: parseInt(current.reps, 10) || null,
          actual_weight: parseFloat(current.weight) || null,
          rpe: parseFloat(current.rpe) || null,
        },
      });
      onLogged(r.set);
      setCurrent({ reps: "", weight: current.weight, rpe: "" });
    } catch (e: any) {
      Alert.alert("Log failed", e?.message || "Please try again");
    }
  };

  return (
    <View>
      {/* Previous Performance */}
      {prev && (prev.last_session?.length > 0 || prev.personal_best) && (
        <View style={styles.prevCard}>
          <Text style={styles.prevHead}>PREVIOUS PERFORMANCE</Text>
          {prev.last_session?.length > 0 && (
            <Text style={styles.prevT}>
              Last time: {prev.last_session.map((s: any) =>
                `${s.actual_reps || "?"} × ${s.actual_weight ? s.actual_weight + "kg" : "BW"}${s.rpe ? " @" + s.rpe : ""}`
              ).join(" · ")}
            </Text>
          )}
          {prev.personal_best && (
            <Text style={styles.prevT}>PB: {prev.personal_best.actual_weight}kg × {prev.personal_best.actual_reps}</Text>
          )}
          {prev.suggested_load && (
            <View style={styles.suggested}>
              <Ionicons name="pulse" size={12} color={theme.color.brand} />
              <Text style={styles.suggestedT}>ATLAS SUGGESTS TODAY: {prev.suggested_load} kg × {targetReps}</Text>
            </View>
          )}
        </View>
      )}

      {/* Existing sets */}
      {existing.map((s) => (
        <View key={s.id} style={styles.setRowDone}>
          <View style={styles.setNum}><Text style={styles.setNumT}>{s.set_number}</Text></View>
          <Text style={styles.setDoneT}>
            {s.actual_reps || 0} reps × {s.actual_weight ? s.actual_weight + "kg" : "BW"}
            {s.rpe ? ` · RPE ${s.rpe}` : ""}
          </Text>
          <Ionicons name="checkmark-circle" size={18} color={theme.color.green} />
        </View>
      ))}

      {/* Active set */}
      {nextSet <= targetSets ? (
        <View style={styles.setActive}>
          <View style={styles.setActiveHead}>
            <View style={[styles.setNum, styles.setNumActive]}><Text style={[styles.setNumT, { color: "#fff" }]}>{nextSet}</Text></View>
            <Text style={styles.setActiveT}>SET {nextSet} of {targetSets} · TARGET: {targetReps}</Text>
          </View>
          <View style={styles.logRow}>
            <LogField label="REPS" value={current.reps} onChange={(v) => setCurrent({ ...current, reps: v })} placeholder={String(targetReps)} testID="log-reps" />
            <LogField label="WEIGHT" value={current.weight} onChange={(v) => setCurrent({ ...current, weight: v })} placeholder="kg" testID="log-weight" />
            <LogField label="RPE" value={current.rpe} onChange={(v) => setCurrent({ ...current, rpe: v })} placeholder="1-10" testID="log-rpe" />
          </View>
          <Pressable onPress={submit} disabled={!current.reps} style={[styles.completeBtn, !current.reps && { opacity: 0.35 }]} testID="log-complete-set">
            <Text style={styles.completeBtnT}>COMPLETE SET</Text>
            <Ionicons name="checkmark" size={16} color="#fff" />
          </Pressable>
        </View>
      ) : (
        <View style={styles.allDone}>
          <Ionicons name="trophy" size={30} color={theme.color.brand} />
          <Text style={styles.allDoneT}>ALL SETS COMPLETE</Text>
        </View>
      )}
    </View>
  );
}

function LogField({ label, value, onChange, placeholder, testID }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string; testID?: string;
}) {
  return (
    <View style={styles.logField}>
      <Text style={styles.logFieldLbl}>{label}</Text>
      <TextInput
        value={value} onChangeText={onChange} keyboardType="decimal-pad"
        placeholder={placeholder} placeholderTextColor={theme.color.textDim}
        style={styles.logInput} testID={testID}
      />
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/*  Styles                                                                     */
/* -------------------------------------------------------------------------- */
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  top: { flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 16, paddingTop: 4, paddingBottom: 8 },
  wName: { color: theme.color.text, fontSize: 13, fontWeight: "900", letterSpacing: 1.5 },
  wMeta: { color: theme.color.textDim, fontSize: 10, marginTop: 2, fontWeight: "700" },
  progressCircle: {
    width: 40, height: 40, borderRadius: 20,
    backgroundColor: theme.color.brandTint, borderWidth: 2, borderColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
  },
  progressT: { color: theme.color.brand, fontSize: 10, fontWeight: "900" },

  pbarTrack: { height: 3, marginHorizontal: 16, backgroundColor: theme.color.surface2, borderRadius: 2, overflow: "hidden" },
  pbarFill: { height: 3, backgroundColor: theme.color.brand },
  exCounter: { color: theme.color.brand, fontSize: 9, fontWeight: "900", letterSpacing: 2, paddingHorizontal: 16, paddingTop: 8 },

  restBar: {
    flexDirection: "row", alignItems: "center", gap: 8,
    marginHorizontal: 16, marginTop: 8, padding: 10, borderRadius: 10,
    backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand,
  },
  restBarT: { flex: 1, color: theme.color.brand, fontSize: 12, fontWeight: "900", letterSpacing: 1.5 },
  restBtn: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 4, borderWidth: 1, borderColor: theme.color.brand },
  restBtnT: { color: theme.color.brand, fontSize: 9, fontWeight: "900", letterSpacing: 1 },

  exHead: { paddingHorizontal: 16, paddingTop: 14, paddingBottom: 8 },
  exName: { color: theme.color.text, fontSize: 22, fontWeight: "900", lineHeight: 28 },
  exTargets: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5, marginTop: 4 },

  tabs: { flexDirection: "row", paddingHorizontal: 16, gap: 6, marginBottom: 6 },
  tab: { flex: 1, paddingVertical: 8, borderRadius: 6, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, alignItems: "center" },
  tabOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  tabT: { color: theme.color.textMuted, fontSize: 9, fontWeight: "900", letterSpacing: 1 },
  tabTOn: { color: "#fff" },

  body: { padding: 16, paddingBottom: 100 },

  imgCard: { borderRadius: 14, overflow: "hidden", backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  imgHero: { width: "100%", height: SCREEN_W * 0.65 },
  imgFallback: { height: SCREEN_W * 0.65, alignItems: "center", justifyContent: "center", padding: 20 },
  imgFbT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2, marginTop: 14 },
  imgFbS: { color: theme.color.textMuted, fontSize: 11, marginTop: 6, textAlign: "center" },
  imgOverlay: { padding: 12, backgroundColor: theme.color.surface },
  imgOverlayT: { color: theme.color.text, fontSize: 15, fontWeight: "900" },
  imgOverlayS: { color: theme.color.brand, fontSize: 11, marginTop: 3, fontWeight: "800", letterSpacing: 1 },

  howCard: {
    padding: 14, marginBottom: 10, borderRadius: 12,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.brand,
  },
  howHead: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 2, marginBottom: 10 },
  howStep: { flexDirection: "row", alignItems: "flex-start", gap: 10, marginBottom: 8 },
  howRow: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 6 },
  howNum: { width: 22, height: 22, borderRadius: 11, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand, alignItems: "center", justifyContent: "center" },
  howNumT: { color: theme.color.brand, fontSize: 10, fontWeight: "900" },
  howT: { flex: 1, color: theme.color.text, fontSize: 13, lineHeight: 19 },

  videoWrap: { borderRadius: 14, overflow: "hidden", marginBottom: 12 },
  videoNote: { flexDirection: "row", alignItems: "center", gap: 6, padding: 10 },
  videoNoteT: { flex: 1, color: theme.color.textMuted, fontSize: 11, lineHeight: 16 },

  atlasReco: {
    padding: 14, marginBottom: 12, borderRadius: 12,
    backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand,
  },
  atlasRecoHead: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 8 },
  atlasIcon: { width: 32, height: 32, borderRadius: 16, backgroundColor: theme.color.surface, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: theme.color.brand },
  atlasRecoLbl: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },
  atlasRecoT: { color: theme.color.text, fontSize: 12, marginTop: 3, lineHeight: 17 },
  atlasRecoReason: { color: theme.color.textMuted, fontSize: 11, lineHeight: 16 },

  altCard: {
    padding: 12, marginBottom: 8, borderRadius: 10,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  altHead: { flexDirection: "row", alignItems: "center", gap: 8 },
  altName: { color: theme.color.text, fontSize: 14, fontWeight: "800" },
  altEqRow: { flexDirection: "row", gap: 4, marginTop: 4, flexWrap: "wrap" },
  eqChip: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 3, backgroundColor: theme.color.surface3 },
  eqChipT: { color: theme.color.textMuted, fontSize: 8, fontWeight: "900", letterSpacing: 1 },
  altPick: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 5, backgroundColor: theme.color.brand },
  altPickT: { color: "#fff", fontSize: 9, fontWeight: "900", letterSpacing: 1 },
  altWhy: { color: theme.color.textMuted, fontSize: 11, marginTop: 6, lineHeight: 16 },

  prevCard: { padding: 12, marginBottom: 12, borderRadius: 10, backgroundColor: theme.color.surface2, borderLeftWidth: 3, borderLeftColor: theme.color.brand },
  prevHead: { color: theme.color.brand, fontSize: 9, fontWeight: "900", letterSpacing: 2, marginBottom: 6 },
  prevT: { color: theme.color.text, fontSize: 12, marginBottom: 3 },
  suggested: { flexDirection: "row", alignItems: "center", gap: 5, marginTop: 6, paddingTop: 6, borderTopWidth: 1, borderTopColor: theme.color.divider },
  suggestedT: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1 },

  setRowDone: { flexDirection: "row", alignItems: "center", gap: 10, padding: 10, marginBottom: 6, borderRadius: 8, backgroundColor: theme.color.surface2 },
  setNum: { width: 26, height: 26, borderRadius: 13, backgroundColor: theme.color.surface3, alignItems: "center", justifyContent: "center" },
  setNumActive: { backgroundColor: theme.color.brand },
  setNumT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900" },
  setDoneT: { flex: 1, color: theme.color.text, fontSize: 12, fontWeight: "700" },

  setActive: { padding: 14, borderRadius: 12, backgroundColor: theme.color.surface2, borderWidth: 2, borderColor: theme.color.brand, marginBottom: 8 },
  setActiveHead: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 12 },
  setActiveT: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },
  logRow: { flexDirection: "row", gap: 8 },
  logField: { flex: 1 },
  logFieldLbl: { color: theme.color.textMuted, fontSize: 9, fontWeight: "900", letterSpacing: 1.5, marginBottom: 4 },
  logInput: { color: theme.color.text, padding: 12, borderRadius: 8, backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border, fontSize: 15, textAlign: "center", fontWeight: "800" },
  completeBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, marginTop: 14, padding: 12, borderRadius: 10, backgroundColor: theme.color.brand },
  completeBtnT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 2 },

  allDone: { alignItems: "center", padding: 30, borderRadius: 12, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand },
  allDoneT: { color: theme.color.brand, fontSize: 13, fontWeight: "900", letterSpacing: 2, marginTop: 8 },

  bottomBar: {
    flexDirection: "row", gap: 10,
    padding: 12, borderTopWidth: 1, borderTopColor: theme.color.divider,
    backgroundColor: theme.color.surface,
  },
  navBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 14, paddingVertical: 12, borderRadius: 10, borderWidth: 1, borderColor: theme.color.border },
  navT: { color: theme.color.text, fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },
  nextBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingVertical: 12, borderRadius: 10, backgroundColor: theme.color.brand },
  finishBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingVertical: 12, borderRadius: 10, backgroundColor: theme.color.green },
  nextT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 1.5 },
});
