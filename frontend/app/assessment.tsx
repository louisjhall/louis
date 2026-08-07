import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator,
  Animated, Easing, Alert, KeyboardAvoidingView, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { useAuth } from "@/src/lib/auth";
import { theme } from "@/src/lib/theme";
import { queueIntroForNextMount } from "@/src/components/CrewFitIntroAnimation";
import { DateField } from "@/src/components/DateField";

/* -------------------------------------------------------------------------- */
/*  Types                                                                     */
/* -------------------------------------------------------------------------- */
type Option = { id: string; label: string; emoji?: string; icon?: any };
type Question = {
  id: string;
  section: string;
  text: string;
  help_text?: string;
  type:
    | "single_select" | "multi_select" | "short_text" | "long_text"
    | "number" | "date" | "range" | "event_builder" | "equipment_picker";
  options?: Option[];
  meta?: { min?: number; max?: number; step?: number; unit?: string; left_label?: string; right_label?: string; location?: string };
  allow_skip?: boolean;
};

type FinaliseStage = { text: string; duration: number };

/* -------------------------------------------------------------------------- */
/*  Screen                                                                    */
/* -------------------------------------------------------------------------- */
export default function Assessment() {
  const router = useRouter();
  const { refresh, user, loading: authLoading } = useAuth();
  const [assessmentId, setAssessmentId] = useState<string | null>(null);
  const [question, setQuestion] = useState<Question | null>(null);
  const [progress, setProgress] = useState(0);
  const [sectionCtx, setSectionCtx] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [answered, setAnswered] = useState<any[]>([]);
  const [finalising, setFinalising] = useState(false);
  const [dna, setDna] = useState<any | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<any>("/assessment/start", { method: "POST", body: { seed_from_profile: true } });
      setAssessmentId(r.assessment_id);
      setProgress(r.progress || 0);
      setSectionCtx(r.section_context || r.next_question?.section || "");
      setQuestion(r.next_question || null);
      if (r.should_end) await finalise(r.assessment_id);
    } catch (e: any) {
      Alert.alert("Couldn't start", e?.message || "Please try again");
    } finally { setLoading(false); }
  }, []);

  // Iter 154 — Data-ready gate.
  // Do NOT call /assessment/start until the auth context has finished
  // resolving the current user. On Android, coming straight from signup /
  // training-setup the AuthProvider is still refetching /me when this
  // screen mounts. Firing /assessment/start before the JWT and user id
  // are stable used to produce a blank Android screen while the API
  // returned 401 / retried silently.
  useEffect(() => {
    if (authLoading) return;      // wait for auth
    if (!user) return;             // waiting for /me
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authLoading, user?.id, load]);

  const submitAnswer = async (answer: any) => {
    if (!question || !assessmentId) return;
    setSubmitting(true);
    setAnswered((a) => [...a, { q: question, a: answer }]);
    try {
      const r = await api<any>("/assessment/answer", {
        method: "POST",
        body: { assessment_id: assessmentId, question_id: question.id, answer },
      });
      setProgress(r.progress || progress);
      setSectionCtx(r.section_context || r.next_question?.section || "");
      if (r.should_end) {
        await finalise(assessmentId);
      } else {
        setQuestion(r.next_question || null);
      }
    } catch (e: any) {
      Alert.alert("Couldn't submit", e?.message || "Please try again");
    } finally { setSubmitting(false); }
  };

  const finalise = async (aid: string) => {
    setFinalising(true);
    try {
      const r = await api<any>("/assessment/finalize", { method: "POST", body: { assessment_id: aid } });
      setDna(r.dna);
      // refresh auth so onboarded=true
      try { await refresh(); } catch {}
    } catch (e: any) {
      Alert.alert("Finalise failed", e?.message || "Please try again");
    } finally { setFinalising(false); }
  };

  /* --------- Render states --------- */
  // Iter 154 — Explicit background on every early-exit branch so Android
  // never flashes the OS window background (black) during transitions
  // from signup / training-setup into the assessment.
  if (authLoading || !user || loading) {
    const label =
      authLoading || !user ? "PREPARING YOUR ACCOUNT" : "PREPARING YOUR ASSESSMENT";
    return (
      <SafeAreaView
        style={[styles.rootDark, { backgroundColor: theme.color.bg }]}
        edges={["top", "bottom"]}
      >
        <View style={styles.loadingWrap}>
          <ActivityIndicator size="large" color={theme.color.brand} />
          <Text style={styles.loadingT}>{label}</Text>
        </View>
      </SafeAreaView>
    );
  }

  if (dna) return <DNAReveal dna={dna} onContinue={async () => {
    // Iter 105 — Queue the CrewFit brand animation to fire ONCE right as
    // the user lands on their personalised dashboard for the first time.
    // This replaces the normal 12-hour cold-launch play for this session.
    try { await queueIntroForNextMount("onboarded"); } catch { /* ignore */ }
    router.replace("/(client)/home" as any);
  }} />;
  if (finalising) return <FinalisingAnimation />;

  return (
    <SafeAreaView style={styles.rootDark} edges={["top", "bottom"]}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <View style={styles.headerBar}>
          <Text style={styles.brand}>ATLAS · <Text style={styles.brandRed}>CREWFIT</Text> ASSESSMENT</Text>
          <Text style={styles.progressLabel}>{progress}%</Text>
        </View>
        <View style={styles.progressTrack}>
          <View style={[styles.progressFill, { width: `${progress}%` }]} />
        </View>
        <View style={styles.sectionBar}>
          <Text style={styles.sectionText}>{sectionCtx?.toUpperCase() || question?.section?.toUpperCase() || "ASSESSMENT"}</Text>
          <Text style={styles.questionsAnswered}>{answered.length} ANSWERED</Text>
        </View>

        <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
          {question ? (
            <QuestionCard
              q={question}
              submitting={submitting}
              onSubmit={submitAnswer}
              onSkip={question.allow_skip ? () => submitAnswer(null) : undefined}
            />
          ) : (
            <ActivityIndicator color={theme.color.brand} />
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

/* -------------------------------------------------------------------------- */
/*  Question Card — routes to type-specific input                             */
/* -------------------------------------------------------------------------- */
function QuestionCard({ q, onSubmit, onSkip, submitting }: {
  q: Question; onSubmit: (a: any) => void; onSkip?: () => void; submitting: boolean;
}) {
  const anim = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    anim.setValue(0);
    Animated.timing(anim, { toValue: 1, duration: 350, useNativeDriver: true, easing: Easing.out(Easing.cubic) }).start();
  }, [q.id, anim]);

  const style = {
    opacity: anim,
    transform: [{ translateY: anim.interpolate({ inputRange: [0, 1], outputRange: [16, 0] }) }],
  };

  return (
    <Animated.View style={[styles.qCard, style]}>
      <View style={styles.qHead}>
        <Ionicons name="chatbubble-ellipses" size={18} color={theme.color.brand} />
        <Text style={styles.qSection}>{q.section}</Text>
      </View>
      <Text style={styles.qText}>{q.text}</Text>
      {q.help_text ? <Text style={styles.qHelp}>{q.help_text}</Text> : null}

      <View style={{ height: 20 }} />

      {q.type === "single_select" && <SingleSelect q={q} onSubmit={onSubmit} submitting={submitting} />}
      {q.type === "multi_select" && <MultiSelect q={q} onSubmit={onSubmit} submitting={submitting} />}
      {q.type === "short_text" && <TextAnswer q={q} onSubmit={onSubmit} submitting={submitting} multiline={false} />}
      {q.type === "long_text" && <TextAnswer q={q} onSubmit={onSubmit} submitting={submitting} multiline={true} />}
      {q.type === "number" && <NumberAnswer q={q} onSubmit={onSubmit} submitting={submitting} />}
      {q.type === "date" && <DateAnswer q={q} onSubmit={onSubmit} submitting={submitting} />}
      {q.type === "range" && <RangeAnswer q={q} onSubmit={onSubmit} submitting={submitting} />}
      {q.type === "event_builder" && <EventBuilder q={q} onSubmit={onSubmit} submitting={submitting} />}
      {q.type === "equipment_picker" && <EquipmentPicker q={q} onSubmit={onSubmit} submitting={submitting} />}

      {onSkip ? (
        <Pressable onPress={onSkip} disabled={submitting} style={styles.skipBtn}>
          <Text style={styles.skipTxt}>SKIP THIS QUESTION</Text>
        </Pressable>
      ) : null}
    </Animated.View>
  );
}

/* -------------------------------------------------------------------------- */
/*  Answer Inputs                                                             */
/* -------------------------------------------------------------------------- */
function SingleSelect({ q, onSubmit, submitting }: any) {
  return (
    <View style={{ gap: 8 }}>
      {(q.options || []).map((o: Option) => (
        <Pressable
          key={o.id}
          disabled={submitting}
          testID={`ans-${q.id}-${o.id}`}
          onPress={() => onSubmit(o.id)}
          style={({ pressed }) => [styles.selectRow, pressed && styles.selectRowPressed]}
        >
          {o.icon ? <Ionicons name={o.icon} size={16} color={theme.color.brand} /> :
            o.emoji ? <Text style={styles.selEmoji}>{o.emoji}</Text> : null}
          <Text style={styles.selLabel}>{o.label}</Text>
          <Ionicons name="chevron-forward" size={16} color={theme.color.brand} />
        </Pressable>
      ))}
    </View>
  );
}

function MultiSelect({ q, onSubmit, submitting }: any) {
  const [selected, setSelected] = useState<string[]>([]);
  const toggle = (id: string) =>
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  return (
    <View>
      <View style={styles.multiWrap}>
        {(q.options || []).map((o: Option) => {
          const on = selected.includes(o.id);
          return (
            <Pressable
              key={o.id}
              disabled={submitting}
              testID={`ans-${q.id}-${o.id}`}
              onPress={() => toggle(o.id)}
              style={[styles.multiChip, on && styles.multiChipOn]}
            >
              {o.icon ? <Ionicons name={o.icon} size={14} color={on ? "#fff" : theme.color.brand} /> :
                o.emoji ? <Text style={styles.multiEmoji}>{o.emoji}</Text> : null}
              <Text style={[styles.multiLbl, on && { color: "#fff" }]}>{o.label}</Text>
            </Pressable>
          );
        })}
      </View>
      <ContinueBtn onPress={() => onSubmit(selected)} disabled={submitting || selected.length === 0} />
    </View>
  );
}

function TextAnswer({ q, onSubmit, submitting, multiline }: any) {
  const [v, setV] = useState("");
  // Iter 84 (Task 1.2) — For questions like "any injuries?" the meta can
  // include `explicit_none_label` so users tick "No injuries currently" as
  // an affirmative answer instead of being forced to type something.
  const explicitNoneLabel: string | undefined = q?.meta?.explicit_none_label;
  return (
    <View>
      <TextInput
        value={v}
        onChangeText={setV}
        multiline={multiline}
        placeholder={multiline ? "Type your answer..." : "Your answer..."}
        placeholderTextColor={theme.color.textDim}
        style={[styles.textInput, multiline && styles.textArea]}
        editable={!submitting}
      />
      <ContinueBtn onPress={() => onSubmit(v.trim())} disabled={submitting || !v.trim()} />
      {explicitNoneLabel ? (
        <Pressable
          testID="assessment-explicit-none"
          onPress={() => onSubmit({ __explicit_none: true, text: "" })}
          disabled={submitting}
          style={styles.noneBtn}
        >
          <Ionicons name="checkmark-circle" size={14} color={theme.color.brand} />
          <Text style={styles.noneBtnT}>{explicitNoneLabel.toUpperCase()}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

function NumberAnswer({ q, onSubmit, submitting }: any) {
  const [v, setV] = useState("");
  const meta = q.meta || {};
  return (
    <View>
      <View style={styles.numberRow}>
        <TextInput
          value={v} onChangeText={setV} keyboardType="number-pad"
          placeholder={String(meta.min ?? 0)}
          placeholderTextColor={theme.color.textDim}
          style={[styles.textInput, { flex: 1 }]}
          editable={!submitting}
        />
        {meta.unit ? <Text style={styles.unit}>{meta.unit}</Text> : null}
      </View>
      <ContinueBtn onPress={() => onSubmit(parseInt(v, 10))} disabled={submitting || !v} />
    </View>
  );
}

function RangeAnswer({ q, onSubmit, submitting }: any) {
  const meta = q.meta || {};
  const min = meta.min ?? 0, max = meta.max ?? 100, step = meta.step ?? 1;
  const [v, setV] = useState(Math.round((min + max) / 2));
  const dec = () => setV((x) => Math.max(min, x - step));
  const inc = () => setV((x) => Math.min(max, x + step));
  return (
    <View>
      <View style={styles.rangeRow}>
        <Pressable onPress={dec} disabled={submitting} style={styles.rangeBtn}>
          <Ionicons name="remove" size={22} color={theme.color.brand} />
        </Pressable>
        <View style={{ flex: 1, alignItems: "center" }}>
          <Text style={styles.rangeVal}>
            {v}<Text style={styles.rangeUnit}>{meta.unit ? ` ${meta.unit}` : ""}</Text>
          </Text>
          <View style={styles.rangeTrack}>
            <View style={[styles.rangeFill, { width: `${((v - min) / (max - min)) * 100}%` }]} />
          </View>
          <View style={styles.rangeLabelRow}>
            <Text style={styles.rangeLabelLeft}>{meta.left_label || String(min)}</Text>
            <Text style={styles.rangeLabelRight}>{meta.right_label || String(max)}</Text>
          </View>
        </View>
        <Pressable onPress={inc} disabled={submitting} style={styles.rangeBtn}>
          <Ionicons name="add" size={22} color={theme.color.brand} />
        </Pressable>
      </View>
      <ContinueBtn onPress={() => onSubmit(v)} disabled={submitting} />
    </View>
  );
}

function DateAnswer({ q, onSubmit, submitting }: any) {
  const [v, setV] = useState("");
  const valid = /^\d{4}-\d{2}-\d{2}$/.test(v);
  return (
    <View>
      <DateField value={v} onChange={setV} testID={`ans-${q.id}-date`} />
      <View style={{ height: 12 }} />
      <ContinueBtn onPress={() => onSubmit(v)} disabled={submitting || !valid} />
    </View>
  );
}

function EventBuilder({ q, onSubmit, submitting }: any) {
  const [events, setEvents] = useState<any[]>([]);
  const [name, setName] = useState("");
  const [date, setDate] = useState("");
  const [priority, setPriority] = useState("B");
  const add = () => {
    if (!name || !/^\d{4}-\d{2}-\d{2}$/.test(date)) return;
    setEvents([...events, { name, date, priority }]);
    setName(""); setDate(""); setPriority("B");
  };
  return (
    <View>
      {events.map((e, i) => (
        <View key={i} style={styles.evPill}>
          <Ionicons name="flag" size={16} color={theme.color.brand} />
          <View style={{ flex: 1 }}>
            <Text style={styles.evName}>{e.name}</Text>
            <Text style={styles.evMeta}>{e.date} · Priority {e.priority}</Text>
          </View>
          <Pressable onPress={() => setEvents(events.filter((_, j) => j !== i))}>
            <Ionicons name="close-circle" size={18} color={theme.color.textDim} />
          </Pressable>
        </View>
      ))}
      <View style={styles.evForm}>
        <TextInput
          value={name} onChangeText={setName}
          placeholder="Event name (e.g. Berlin Marathon)"
          placeholderTextColor={theme.color.textDim}
          style={styles.textInput} editable={!submitting}
        />
        <DateField value={date} onChange={setDate} testID="event-date-picker" />
        <View style={{ height: 12 }} />
        <View style={styles.prioRow}>
          {["A", "B", "C"].map((p) => (
            <Pressable
              key={p} onPress={() => setPriority(p)}
              style={[styles.prioChip, priority === p && styles.prioChipOn]}
            >
              <Text style={[styles.prioTxt, priority === p && { color: "#fff" }]}>PRIORITY {p}</Text>
            </Pressable>
          ))}
        </View>
        <Pressable onPress={add} disabled={submitting || !name || !date} style={styles.evAdd}>
          <Ionicons name="add" size={16} color={theme.color.brand} />
          <Text style={styles.evAddT}>ADD EVENT</Text>
        </Pressable>
      </View>
      <ContinueBtn onPress={() => onSubmit(events)} disabled={submitting} label={events.length === 0 ? "CONTINUE — NO EVENTS" : "CONTINUE"} />
    </View>
  );
}

const HOME_EQ: Option[] = [
  { id: "no_equipment", label: "None", icon: "remove-circle-outline" },
  // Iter 128m — Full Commercial Gym preset (permanent HOME setup).
  // Represents typical commercial gym inventory. Conservative — does NOT
  // imply specialist machines (hack squat / GHD / hip thrust machine / sled
  // / SkiErg / safety bar). Client can still add specific items on top.
  { id: "commercial_gym_standard", label: "Full Commercial Gym", icon: "business-outline" },
  { id: "yoga_mat", label: "Yoga mat", icon: "grid-outline" },
  { id: "resistance_bands", label: "Bands", icon: "infinite" },
  { id: "pull_up_bar", label: "Pull-up bar", icon: "reorder-two" },
  { id: "dumbbells", label: "Dumbbells", icon: "barbell" },
  { id: "kettlebells", label: "Kettlebells", icon: "fitness" },
  { id: "barbell", label: "Barbell", icon: "barbell-outline" },
  { id: "squat_rack", label: "Squat rack", icon: "construct" },
  { id: "bench", label: "Bench", icon: "bed-outline" },
  { id: "treadmill", label: "Treadmill", icon: "walk" },
  { id: "bike", label: "Bike/turbo", icon: "bicycle" },
  { id: "rower", label: "Rower", icon: "boat" },
  { id: "assault_bike", label: "Assault bike", icon: "flash" },
  { id: "trx", label: "TRX", icon: "link" },
  { id: "medicine_ball", label: "Med ball", icon: "ellipse" },
  { id: "skipping_rope", label: "Rope", icon: "trending-up" },
  { id: "foam_roller", label: "Foam roller", icon: "swap-horizontal" },
  { id: "mobility_tools", label: "Mobility tools", icon: "hand-left" },
];

// Descriptive helper text shown under the equipment options (used only when
// the "Full Commercial Gym" chip is currently selected, to explain what the
// preset means without listing every implied piece of equipment).
const COMMERCIAL_GYM_HINT =
  "Typical commercial gym with free weights, machines, cables and cardio equipment. Add specific items below if your gym also has them.";

function EquipmentPicker({ q, onSubmit, submitting }: any) {
  const [sel, setSel] = useState<string[]>([]);
  const list = useMemo(() => (q.options && q.options.length ? q.options : HOME_EQ) as Option[], [q.options]);
  const toggle = (id: string) => setSel((s) => {
    if (s.includes(id)) return s.filter((x) => x !== id);
    // "None" and "Full Commercial Gym" are mutually exclusive with each other.
    if (id === "no_equipment") return ["no_equipment"];
    if (id === "commercial_gym_standard") return [...s.filter((x) => x !== "no_equipment"), id];
    return [...s.filter((x) => x !== "no_equipment"), id];
  });
  const location = q.meta?.location || "home";
  const showCommercialHint = sel.includes("commercial_gym_standard") && location === "home";
  return (
    <View>
      <Text style={styles.equipLoc}>{location.toUpperCase()} EQUIPMENT</Text>
      <View style={styles.multiWrap}>
        {list.map((o) => {
          const on = sel.includes(o.id);
          return (
            <Pressable key={o.id} onPress={() => toggle(o.id)} disabled={submitting} style={[styles.multiChip, on && styles.multiChipOn]}>
              {o.icon ? <Ionicons name={o.icon} size={14} color={on ? "#fff" : theme.color.brand} /> :
                o.emoji ? <Text style={styles.multiEmoji}>{o.emoji}</Text> : null}
              <Text style={[styles.multiLbl, on && { color: "#fff" }]}>{o.label}</Text>
            </Pressable>
          );
        })}
      </View>
      {showCommercialHint ? (
        <Text style={styles.equipHint}>{COMMERCIAL_GYM_HINT}</Text>
      ) : null}
      <ContinueBtn onPress={() => onSubmit({ location, equipment: sel })} disabled={submitting} />
    </View>
  );
}

function ContinueBtn({ onPress, disabled, label = "CONTINUE" }: { onPress: () => void; disabled?: boolean; label?: string }) {
  return (
    <Pressable onPress={onPress} disabled={disabled} style={[styles.continueBtn, disabled && styles.continueBtnDisabled]}>
      <Text style={styles.continueTxt}>{label}</Text>
      <Ionicons name="arrow-forward" size={16} color="#fff" />
    </Pressable>
  );
}

/* -------------------------------------------------------------------------- */
/*  Finalising animation                                                       */
/* -------------------------------------------------------------------------- */
function FinalisingAnimation() {
  const stages: FinaliseStage[] = [
    { text: "Learning your goals...", duration: 1500 },
    { text: "Understanding your flying...", duration: 1500 },
    { text: "Analysing your lifestyle...", duration: 1500 },
    { text: "Building your Coaching DNA...", duration: 1500 },
    { text: "Generating your roadmap...", duration: 1500 },
    { text: "Creating your first programme...", duration: 1500 },
  ];
  const [idx, setIdx] = useState(0);
  useEffect(() => {
    if (idx >= stages.length - 1) return;
    const t = setTimeout(() => setIdx((i) => i + 1), stages[idx].duration);
    return () => clearTimeout(t);
  }, [idx]);

  return (
    <SafeAreaView style={styles.rootDark} edges={["top", "bottom"]}>
      <View style={styles.finaliseWrap}>
        <View style={styles.pulseCircle}>
          <ActivityIndicator size="large" color={theme.color.brand} />
        </View>
        <Text style={styles.finaliseBrand}>ATLAS · <Text style={styles.brandRed}>CREWFIT</Text></Text>
        <View style={styles.stageList}>
          {stages.map((s, i) => (
            <View key={i} style={styles.stageRow}>
              <Ionicons
                name={i < idx ? "checkmark-circle" : i === idx ? "sync" : "ellipse-outline"}
                size={16}
                color={i <= idx ? theme.color.brand : theme.color.textDim}
              />
              <Text style={[styles.stageTxt, i === idx && styles.stageTxtActive, i > idx && styles.stageTxtPending]}>
                {s.text}
              </Text>
            </View>
          ))}
        </View>
      </View>
    </SafeAreaView>
  );
}

/* -------------------------------------------------------------------------- */
/*  DNA Reveal                                                                */
/* -------------------------------------------------------------------------- */
function DNAReveal({ dna, onContinue }: { dna: any; onContinue: () => void }) {
  return (
    <SafeAreaView style={styles.rootDark} edges={["top", "bottom"]}>
      <ScrollView contentContainerStyle={{ padding: 20, paddingBottom: 40 }}>
        <View style={styles.dnaHead}>
          <Text style={styles.brand}>YOUR COACHING <Text style={styles.brandRed}>DNA</Text></Text>
          <Text style={styles.dnaSub}>The blueprint that guides every future CrewFit decision.</Text>
        </View>

        <View style={styles.dnaConfCard}>
          <View style={{ flex: 1 }}>
            <Text style={styles.dnaConfLabel}>PROFILE CONFIDENCE</Text>
            <Text style={styles.dnaConfSub}>Will rise as CrewFit learns more.</Text>
          </View>
          <Text style={styles.dnaConfNum}>{dna.ai_confidence_score ?? "—"}</Text>
        </View>

        <DNARow label="PRIMARY GOAL" value={dna.primary_goal} highlight />
        <DNARow label="WHY IT MATTERS" value={dna.why_it_matters} multiline />
        {Array.isArray(dna.secondary_goals) && dna.secondary_goals.length > 0 && (
          <DNARow label="SECONDARY GOALS" value={dna.secondary_goals.join(" · ")} />
        )}
        {dna.next_event && dna.next_event.name && (
          <DNARow label="NEXT MAJOR EVENT" value={`${dna.next_event.name} · ${dna.next_event.date}`} />
        )}
        {dna.aviation_profile && (
          <DNARow
            label="AVIATION PROFILE"
            value={`${dna.aviation_profile.role || "—"} · ${dna.aviation_profile.haul_mix || "—"} · hotel gyms: ${dna.aviation_profile.hotel_gym_frequency || "—"}`}
          />
        )}
        <DNARow label="FLYING STYLE" value={dna.flying_style} multiline />
        <DNARow label="RECOVERY RISK" value={String(dna.recovery_risk || "").toUpperCase()} />
        <DNARow label="TRAINING EXPERIENCE" value={String(dna.training_experience || "").toUpperCase()} />
        <DNARow label="MOTIVATION STYLE" value={dna.motivation_style} />
        <DNARow label="COACHING STYLE" value={dna.coaching_style} />
        <DNARow label="LIFESTYLE" value={dna.lifestyle_summary} multiline />
        <DNARow label="INJURIES" value={dna.injury_summary} multiline />
        <DNARow label="NUTRITION" value={dna.nutrition_summary} multiline />
        <DNARow label="STRENGTH" value={dna.biggest_strength} multiline />
        <DNARow label="WEAKNESS" value={dna.biggest_weakness} multiline />
        <DNARow label="OPPORTUNITY" value={dna.biggest_opportunity} multiline />

        <View style={styles.recoBlock}>
          <Text style={styles.recoHead}>CREWFIT'S RECOMMENDED APPROACH</Text>
          <DNARow label="WEEKLY TRAINING" value={dna.recommended_weekly_training} multiline dim />
          <DNARow label="RECOVERY STRATEGY" value={dna.recommended_recovery_strategy} multiline dim />
          <DNARow label="NUTRITION STRATEGY" value={dna.recommended_nutrition_strategy} multiline dim />
          <DNARow label="COACHING STYLE" value={dna.recommended_coaching_style} multiline dim />
        </View>

        {dna.summary ? (
          <View style={styles.summaryCard}>
            <Text style={styles.summaryLabel}>ATLAS INTELLIGENCE SUMMARY</Text>
            <Text style={styles.summaryText}>{dna.summary}</Text>
          </View>
        ) : null}

        <Pressable onPress={onContinue} style={[styles.continueBtn, { marginTop: 24 }]} testID="dna-continue">
          <Text style={styles.continueTxt}>ENTER CREWFIT</Text>
          <Ionicons name="arrow-forward" size={16} color="#fff" />
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}

function DNARow({ label, value, multiline, highlight, dim }: { label: string; value?: any; multiline?: boolean; highlight?: boolean; dim?: boolean }) {
  if (value === undefined || value === null || value === "") return null;
  return (
    <View style={[styles.dnaRow, highlight && styles.dnaRowHighlight, dim && styles.dnaRowDim]}>
      <Text style={[styles.dnaLbl, highlight && { color: theme.color.brand }]}>{label}</Text>
      <Text style={[styles.dnaVal, multiline && { fontSize: 13, lineHeight: 19 }, highlight && { fontSize: 18, fontWeight: "900" }]} numberOfLines={multiline ? 6 : 2}>
        {String(value)}
      </Text>
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/*  Styles                                                                     */
/* -------------------------------------------------------------------------- */
const styles = StyleSheet.create({
  rootDark: { flex: 1, backgroundColor: theme.color.bg },
  loadingWrap: { flex: 1, alignItems: "center", justifyContent: "center", gap: 14 },
  loadingT: { color: theme.color.brand, letterSpacing: 2, fontSize: 11, fontWeight: "900" },

  headerBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 20, paddingTop: 14, paddingBottom: 8 },
  brand: { color: theme.color.text, fontWeight: "900", fontSize: 14, letterSpacing: 2.5 },
  brandRed: { color: theme.color.brand },
  progressLabel: { color: theme.color.brand, fontWeight: "900", fontSize: 12, letterSpacing: 2 },

  progressTrack: { height: 3, marginHorizontal: 20, backgroundColor: theme.color.surface2, borderRadius: 2, overflow: "hidden" },
  progressFill: { height: 3, backgroundColor: theme.color.brand },
  sectionBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 20 },
  sectionText: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 2.5 },
  questionsAnswered: { color: theme.color.textDim, fontSize: 10, fontWeight: "800", letterSpacing: 1.5 },

  body: { padding: 20, paddingBottom: 60 },

  qCard: {
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
    borderRadius: 16, padding: 20,
  },
  qHead: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 10 },
  qSection: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 2 },
  qText: { color: theme.color.text, fontSize: 20, fontWeight: "700", lineHeight: 27 },
  qHelp: { color: theme.color.textMuted, fontSize: 12, marginTop: 8, lineHeight: 18 },

  selectRow: {
    flexDirection: "row", alignItems: "center", gap: 12,
    padding: 14, borderRadius: 10,
    backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border,
  },
  selectRowPressed: { borderColor: theme.color.brand, backgroundColor: theme.color.brandTint },
  selEmoji: { fontSize: 22 },
  selLabel: { flex: 1, color: theme.color.text, fontSize: 14, fontWeight: "700" },

  multiWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 12 },
  multiChip: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 12, paddingVertical: 9, borderRadius: 20,
    backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border,
  },
  multiChipOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  multiEmoji: { fontSize: 14 },
  multiLbl: { color: theme.color.text, fontSize: 12, fontWeight: "700" },

  textInput: {
    color: theme.color.text, fontSize: 14, padding: 14,
    borderRadius: 10, backgroundColor: theme.color.surface,
    borderWidth: 1, borderColor: theme.color.border, marginBottom: 12,
  },
  textArea: { minHeight: 90, textAlignVertical: "top" },

  numberRow: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 12 },
  unit: { color: theme.color.textMuted, fontSize: 13, fontWeight: "700" },

  rangeRow: { flexDirection: "row", alignItems: "center", gap: 12, marginBottom: 12 },
  rangeBtn: {
    width: 44, height: 44, borderRadius: 22,
    backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border,
    alignItems: "center", justifyContent: "center",
  },
  rangeVal: { color: theme.color.text, fontSize: 32, fontWeight: "900" },
  rangeUnit: { color: theme.color.textMuted, fontSize: 14, fontWeight: "700" },
  rangeTrack: { width: "80%", height: 4, backgroundColor: theme.color.surface, borderRadius: 2, marginTop: 8, overflow: "hidden" },
  rangeFill: { height: 4, backgroundColor: theme.color.brand },
  rangeLabelRow: { flexDirection: "row", justifyContent: "space-between", width: "80%", marginTop: 4 },
  rangeLabelLeft: { color: theme.color.textDim, fontSize: 10, fontWeight: "700" },
  rangeLabelRight: { color: theme.color.textDim, fontSize: 10, fontWeight: "700" },

  evPill: {
    flexDirection: "row", alignItems: "center", gap: 10,
    padding: 12, marginBottom: 8, borderRadius: 10,
    backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border,
  },
  evEmoji: { fontSize: 20 },
  evName: { color: theme.color.text, fontSize: 13, fontWeight: "800" },
  evMeta: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },
  evForm: { marginTop: 8 },
  prioRow: { flexDirection: "row", gap: 6, marginBottom: 8 },
  prioChip: {
    flex: 1, paddingVertical: 8, borderRadius: 6,
    backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border,
    alignItems: "center",
  },
  prioChipOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  prioTxt: { color: theme.color.text, fontSize: 9, fontWeight: "900", letterSpacing: 1.5 },
  evAdd: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    paddingVertical: 12, borderRadius: 8,
    borderWidth: 1, borderColor: theme.color.brand, borderStyle: "dashed",
  },
  evAddT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },

  equipLoc: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 2, marginBottom: 10 },
  equipHint: {
    color: theme.color.textDim, fontSize: 11, fontStyle: "italic",
    marginTop: 12, marginBottom: 6, lineHeight: 16,
  },

  continueBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    paddingVertical: 14, borderRadius: 10, marginTop: 8,
    backgroundColor: theme.color.brand,
  },
  continueBtnDisabled: { opacity: 0.35 },
  continueTxt: { color: "#fff", fontSize: 13, fontWeight: "900", letterSpacing: 2 },
  skipBtn: { alignItems: "center", paddingVertical: 12, marginTop: 6 },
  skipTxt: { color: theme.color.textMuted, fontSize: 10, fontWeight: "800", letterSpacing: 2 },
  noneBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 8, paddingVertical: 12, marginTop: 8,
    borderRadius: theme.radius.md,
    borderWidth: 1, borderColor: theme.color.brand,
    backgroundColor: "transparent",
  },
  noneBtnT: { color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 1.2 },

  finaliseWrap: { flex: 1, alignItems: "center", justifyContent: "center", padding: 40 },
  pulseCircle: {
    width: 120, height: 120, borderRadius: 60, marginBottom: 24,
    borderWidth: 2, borderColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
  },
  finaliseBrand: { color: theme.color.text, fontSize: 16, fontWeight: "900", letterSpacing: 3, marginBottom: 30 },
  stageList: { gap: 12, alignSelf: "stretch" },
  stageRow: { flexDirection: "row", alignItems: "center", gap: 12 },
  stageTxt: { color: theme.color.text, fontSize: 13, fontWeight: "700" },
  stageTxtActive: { color: theme.color.brand },
  stageTxtPending: { color: theme.color.textDim },

  dnaHead: { marginBottom: 20 },
  dnaSub: { color: theme.color.textMuted, fontSize: 12, marginTop: 6, lineHeight: 18 },
  dnaConfCard: {
    flexDirection: "row", alignItems: "center", gap: 12,
    padding: 16, borderRadius: 12, marginBottom: 20,
    backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand,
  },
  dnaConfLabel: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  dnaConfSub: { color: theme.color.textMuted, fontSize: 11, marginTop: 4 },
  dnaConfNum: { color: theme.color.brand, fontSize: 36, fontWeight: "900" },
  dnaRow: {
    padding: 12, marginBottom: 8, borderRadius: 8,
    backgroundColor: theme.color.surface2, borderLeftWidth: 2, borderLeftColor: theme.color.border,
  },
  dnaRowHighlight: { borderLeftColor: theme.color.brand, backgroundColor: theme.color.brandTint },
  dnaRowDim: { backgroundColor: "transparent", borderLeftColor: theme.color.textDim },
  dnaLbl: { color: theme.color.textMuted, fontSize: 9, fontWeight: "900", letterSpacing: 2, marginBottom: 4 },
  dnaVal: { color: theme.color.text, fontSize: 14, fontWeight: "700" },

  recoBlock: { marginTop: 20 },
  recoHead: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2, marginBottom: 12 },

  summaryCard: {
    marginTop: 20, padding: 16, borderRadius: 12,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.brand,
  },
  summaryLabel: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 2, marginBottom: 8 },
  summaryText: { color: theme.color.text, fontSize: 13, lineHeight: 20 },
});
