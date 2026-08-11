import React, { useCallback, useEffect, useMemo, useState } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl,
  Modal, TextInput, Alert, KeyboardAvoidingView, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter, useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { useAuth } from "@/src/lib/auth";
import { usePreview } from "@/src/lib/preview";
import { theme } from "@/src/lib/theme";
import { confirm as uxConfirm } from "@/src/lib/ux";
import { DateField } from "@/src/components/DateField";
import { WorkoutSettingsPanel } from "@/src/components/WorkoutSettingsPanel";
import { NotificationPreferencesCard } from "@/src/components/NotificationPreferencesCard";
import { ProfilePhotoRow } from "@/src/components/ProfilePhotoRow";
import { PersonalImageryCard } from "@/src/components/PersonalImageryCard";
import { ChangePasswordModal } from "@/src/components/ChangePasswordModal";

/* -------------------------------------------------------------------------- */
/*  Types                                                                     */
/* -------------------------------------------------------------------------- */
type EditField = {
  key: string; label: string;
  type: "text" | "multi_text" | "number" | "chips";
  value?: any;
  options?: string[];   // for chips (multi)
  unit?: string;
};
type EditSpec = {
  title: string;
  scope: "user_profile" | "coaching_dna";
  fields: EditField[];
};

/* -------------------------------------------------------------------------- */
/*  Screen                                                                    */
/* -------------------------------------------------------------------------- */
export default function ProfileScreen() {
  const router = useRouter();
  const { user, logout, refresh } = useAuth();
  const { preview, exit: exitPreview, resetSandbox } = usePreview();

  const [dna, setDna] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [checkins, setCheckins] = useState<any[]>([]);
  const [assessments, setAssessments] = useState<any[]>([]);
  const [achievements, setAchievements] = useState<any>({ stats: {}, badges: [] });
  const [prs, setPrs] = useState<any[]>([]);
  const [coachNotes, setCoachNotes] = useState<any>({ workout_notes: [], reality_reviews: [], messages: [] });
  const [aiNotes, setAiNotes] = useState<any>({ dna_history: [], reality_context: [], move_rationales: [] });
  const [loading, setLoading] = useState(true);

  const [expanded, setExpanded] = useState<Record<string, boolean>>({
    profile: true, coaching_dna: true,
  });
  const [editing, setEditing] = useState<EditSpec | null>(null);
  const [prModalOpen, setPrModalOpen] = useState(false);
  const [changePasswordOpen, setChangePasswordOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [d, ev, ck, ah, ach, pr, cn, an] = await Promise.all([
        api<any>("/coaching-dna").catch(() => ({ dna: null })),
        api<any>("/events/history").catch(() => []),
        api<any>("/checkins?limit=5").catch(() => []),
        api<any>("/assessment/history").catch(() => ({ assessments: [] })),
        api<any>("/achievements").catch(() => ({ stats: {}, badges: [] })),
        api<any>("/personal-records").catch(() => ({ records: [] })),
        api<any>("/notes/coach").catch(() => ({ workout_notes: [], reality_reviews: [], messages: [] })),
        api<any>("/notes/ai").catch(() => ({ dna_history: [], reality_context: [], move_rationales: [] })),
      ]);
      setDna(d.dna || null);
      setEvents(Array.isArray(ev) ? ev : []);
      setCheckins(Array.isArray(ck) ? ck : []);
      setAssessments(ah.assessments || []);
      setAchievements(ach || { stats: {}, badges: [] });
      setPrs(pr.records || []);
      setCoachNotes(cn || { workout_notes: [], reality_reviews: [], messages: [] });
      setAiNotes(an || { dna_history: [], reality_context: [], move_rationales: [] });
    } catch { /* ignore */ } finally { setLoading(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const toggle = (id: string) => setExpanded((e) => ({ ...e, [id]: !e[id] }));

  const openEdit = (spec: EditSpec) => setEditing(spec);

  const saveEdit = async (values: Record<string, any>) => {
    if (!editing) return;
    try {
      if (editing.scope === "user_profile") {
        await api("/user/profile", { method: "PATCH", body: values });
        await refresh();
      } else {
        await api("/coaching-dna", { method: "PATCH", body: { updates: values, reason: "Profile page inline edit" } });
      }
      setEditing(null);
      await load();
    } catch (e: any) {
      Alert.alert("Save failed", e?.message || "Please try again");
    }
  };

  const upcomingEvents = useMemo(
    () => events.filter((e) => new Date((e.event_date || "") + "T00:00:00") > new Date(Date.now() - 86400000)).slice(0, 6),
    [events]
  );
  const av = (dna || {}).aviation_profile || {};
  const ta = (dna || {}).training_availability || {};
  const eqLocs = (dna || {}).equipment_locations || [];
  const stats = achievements?.stats || {};

  if (loading && !dna && !user) {
    return (
      <SafeAreaView style={styles.root} edges={["top"]}>
        <ActivityIndicator style={{ marginTop: 40 }} color={theme.color.brand} />
      </SafeAreaView>
    );
  }

  const confirmLogout = async () => {
    // Preview mode: never log the coach out of their real session. Instead
    // offer to reset the sandbox and exit back to the coach dashboard.
    if (preview.active) {
      const isSandbox = preview.mode === "sandbox" || preview.mode === "new_client";
      if (isSandbox) {
        const resetFirst = await uxConfirm({
          title: "Exit preview?",
          message: "You're in the New Client Preview sandbox. Reset it back to a brand-new client before exiting?",
          confirmLabel: "Reset & Exit",
          cancelLabel: "Exit (keep progress)",
          destructive: true,
        });
        if (resetFirst) {
          try { await resetSandbox(); } catch {}
        }
      }
      await exitPreview();
      router.replace("/(coach)/overview" as any);
      return;
    }

    // Real client logout — cross-platform confirm (Alert.alert with buttons
    // silently no-ops on React Native Web, which is why the button appeared
    // "broken" in the browser preview).
    const ok = await uxConfirm({
      title: "Log out?",
      message: "Are you sure you want to log out?",
      confirmLabel: "Log Out",
      cancelLabel: "Cancel",
      destructive: true,
    });
    if (!ok) return;
    try {
      await logout();
    } catch {}
    // AuthProvider clears the token; explicitly bounce to /login so the
    // route guards don't have to fight a stale state.
    router.replace("/(auth)/login" as any);
  };

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>COACHING <Text style={styles.brandRed}>HEADQUARTERS</Text></Text>
          <Text style={styles.sub}>{user?.name || user?.email}</Text>
        </View>
        <Pressable testID="hq-logout" onPress={confirmLogout} style={styles.iconBtn}>
          <Ionicons name="log-out" size={18} color={theme.color.text} />
        </Pressable>
      </View>

      <ScrollView
        contentContainerStyle={styles.body}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}
      >
        {/* NEW: CrewFit Coaching System banner */}
        <View style={styles.systemBanner}>
          <View style={styles.systemHead}>
            <View style={styles.systemIcon}>
              <Ionicons name="shield-checkmark" size={22} color={theme.color.brand} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.systemEyebrow}>THE CREWFIT COACHING SYSTEM</Text>
              <Text style={styles.systemTitle}>Louis Hall · Atlas</Text>
            </View>
          </View>
          <Text style={styles.systemBody}>
            Your coaching is built on a combination of real human coaching and intelligent analysis.
            {"\n\n"}Louis Hall designed the coaching philosophy. Atlas applies that philosophy consistently across your programme.
            {"\n\n"}As Atlas learns more about you, your coaching becomes increasingly personalised while remaining within the same proven coaching framework.
          </Text>
          <View style={styles.systemActions}>
            <Pressable
              testID="hq-meet-atlas"
              onPress={() => router.push("/atlas-intro" as any)}
              style={styles.systemBtnPrimary}
            >
              <Ionicons name="pulse" size={12} color="#fff" />
              <Text style={styles.systemBtnPrimaryT}>MEET ATLAS</Text>
            </Pressable>
            <Pressable
              testID="hq-guard-rails"
              onPress={() => router.push("/guard-rails" as any)}
              style={styles.systemBtnSecondary}
            >
              <Ionicons name="shield-half" size={12} color={theme.color.brand} />
              <Text style={styles.systemBtnSecondaryT}>GUARD RAILS</Text>
            </Pressable>
            <Pressable
              testID="hq-welcome"
              onPress={() => router.push("/welcome" as any)}
              style={styles.systemBtnSecondary}
            >
              <Ionicons name="play-circle" size={12} color={theme.color.brand} />
              <Text style={styles.systemBtnSecondaryT}>MEET LOUIS</Text>
            </Pressable>
          </View>
        </View>

        {/* Iter168 · Profile Accordions — 18 sections + CTAs reorganised
            into 4 top-level groups. All groups collapsed by default. */}

        {/* ═══════════ GROUP 1 · ME & GOALS ═══════════════════════════════ */}
        <SectionGroup id="me_goals" title="ME & GOALS" icon="person"
          subtitle="Who you are, where you're headed">

          {/* 1. PROFILE */}
          <Section id="profile" title="PROFILE" icon="person" expanded={expanded} onToggle={toggle}
            onEdit={() => openEdit({
              title: "Profile", scope: "user_profile", fields: [
                { key: "name", label: "Name", type: "text", value: user?.name },
                { key: "job_title", label: "Job Title (Captain, First Officer, Cabin Crew, Purser, …)", type: "text", value: user?.profile?.job_title },
                { key: "airline", label: "Airline", type: "text", value: user?.profile?.airline },
                { key: "home_base", label: "Home Base (e.g. Dubai (DXB))", type: "text", value: user?.profile?.home_base },
                { key: "aircraft_type", label: "Aircraft Type", type: "text", value: user?.profile?.aircraft_type },
                { key: "route_focus", label: "Route Focus (long-haul | short-haul | mixed)", type: "text", value: user?.profile?.route_focus },
                { key: "height_cm", label: "Height", type: "number", value: user?.profile?.height_cm, unit: "cm" },
                { key: "weight_kg", label: "Weight", type: "number", value: user?.profile?.weight_kg, unit: "kg" },
                { key: "dob", label: "Date of Birth", type: "text", value: user?.profile?.dob },
              ],
            })}
          >
            <ProfilePhotoRow user={user} onChanged={async () => { await refresh(); }} />
            <KV label="EMAIL" value={user?.email} />
            <KV label="JOB TITLE" value={user?.profile?.job_title || "—"} />
            <KV label="AIRLINE" value={user?.profile?.airline || "—"} />
            <KV label="HOME BASE" value={user?.profile?.home_base || "—"} />
            <KV label="AIRCRAFT" value={user?.profile?.aircraft_type || "—"} />
            <KV label="ROUTE FOCUS" value={user?.profile?.route_focus ? user.profile.route_focus.toUpperCase() : "—"} />
            <KV label="ROLE" value={String(user?.role || "").toUpperCase()} />
            <KV label="HEIGHT" value={user?.profile?.height_cm ? `${user.profile.height_cm} cm` : "—"} />
            <KV label="WEIGHT" value={user?.profile?.weight_kg ? `${user.profile.weight_kg} kg` : "—"} />
            <KV label="DOB" value={user?.profile?.dob || "—"} />
            <PersonalImageryCard />
          </Section>

          {/* AVIATION PROFILE */}
          <Section id="aviation" title="AVIATION PROFILE" icon="airplane" expanded={expanded} onToggle={toggle}
            disabled={!dna}
            onEdit={dna ? () => openEdit({
              title: "Aviation Profile", scope: "coaching_dna", fields: [
                { key: "aviation_profile", label: "Aviation Profile JSON", type: "multi_text", value: JSON.stringify(dna.aviation_profile || {}, null, 2) },
                { key: "flying_style", label: "Flying Style", type: "multi_text", value: dna.flying_style },
              ],
            }) : undefined}
          >
            <KV label="ROLE" value={av.role} />
            <KV label="HAUL MIX" value={av.haul_mix} />
            <KV label="AVG SECTORS / MONTH" value={av.avg_sectors_month} />
            <KV label="TYPICAL LAYOVER" value={av.typical_layover_hours ? `${av.typical_layover_hours} h` : undefined} />
            <KV label="HOTEL GYMS" value={av.hotel_gym_frequency} />
            <KV label="FLYING STYLE" value={dna?.flying_style} multiline />
          </Section>

          {/* LIFESTYLE */}
          <Section id="lifestyle" title="LIFESTYLE" icon="home" expanded={expanded} onToggle={toggle}
            disabled={!dna}
            onEdit={dna ? () => openEdit({
              title: "Lifestyle", scope: "coaching_dna", fields: [
                { key: "lifestyle_summary", label: "Lifestyle Summary", type: "multi_text", value: dna.lifestyle_summary },
              ],
            }) : undefined}
          >
            <KV label="SUMMARY" value={dna?.lifestyle_summary} multiline />
          </Section>

          {/* GOALS */}
          <Section id="goals" title="GOALS" icon="flag" expanded={expanded} onToggle={toggle}
            disabled={!dna}
            onEdit={dna ? () => openEdit({
              title: "Goals", scope: "coaching_dna", fields: [
                { key: "primary_goal", label: "Primary Goal", type: "text", value: dna.primary_goal },
                { key: "secondary_goals", label: "Secondary Goals (comma-separated)", type: "multi_text", value: (dna.secondary_goals || []).join(", ") },
                { key: "why_it_matters", label: "Why This Matters", type: "multi_text", value: dna.why_it_matters },
              ],
            }) : undefined}
          >
            <KV label="PRIMARY" value={dna?.primary_goal} highlight />
            {(dna?.secondary_goals || []).length > 0 && (
              <View style={styles.chipRow}>
                {dna.secondary_goals.map((g: string, i: number) => (
                  <View key={i} style={styles.chip}><Text style={styles.chipT}>{g}</Text></View>
                ))}
              </View>
            )}
            <KV label="WHY IT MATTERS" value={dna?.why_it_matters} multiline />
          </Section>

          {/* EVENT TIMELINE */}
          <Section id="event_timeline" title="EVENT TIMELINE" icon="calendar" expanded={expanded} onToggle={toggle}
            rightSlot={<CountPill n={events.length} />}
          >
            {events.length === 0 ? (
              <EmptyRow text="No events on the timeline yet." />
            ) : (
              events.slice(0, 12).map((e) => (
                <View key={e.id} style={styles.evRow}>
                  <Ionicons name="flag" size={16} color={theme.color.brand} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.evName}>{e.event_name || e.event_type}</Text>
                    <Text style={styles.evMeta}>{e.event_date} · {String(e.priority || "B").toUpperCase()}</Text>
                  </View>
                  {e.is_active && <View style={styles.activeDot} />}
                </View>
              ))
            )}
          </Section>

          {/* UPCOMING EVENTS */}
          <Section id="upcoming" title="UPCOMING EVENTS" icon="star" expanded={expanded} onToggle={toggle}
            rightSlot={<CountPill n={upcomingEvents.length} />}
          >
            {upcomingEvents.length === 0 ? (
              <EmptyRow text="No upcoming events." />
            ) : (
              upcomingEvents.map((e) => (
                <View key={e.id} style={styles.evRow}>
                  <Ionicons name="flag" size={16} color={theme.color.brand} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.evName}>{e.event_name || e.event_type}</Text>
                    <Text style={styles.evMeta}>{e.event_date} · Priority {String(e.priority || "B").toUpperCase()}</Text>
                  </View>
                  {e.phase_info?.phase ? (
                    <View style={styles.phasePill}><Text style={styles.phasePillT}>{String(e.phase_info.phase).toUpperCase()}</Text></View>
                  ) : null}
                </View>
              ))
            )}
          </Section>

          {/* MOTIVATION */}
          <Section id="motivation" title="MOTIVATION" icon="flame" expanded={expanded} onToggle={toggle}
            disabled={!dna}
            onEdit={dna ? () => openEdit({
              title: "Motivation", scope: "coaching_dna", fields: [
                { key: "motivation_style", label: "Motivation Style", type: "text", value: dna.motivation_style },
                { key: "coaching_style", label: "Preferred Coaching Style", type: "text", value: dna.coaching_style },
                { key: "biggest_strength", label: "Biggest Strength", type: "text", value: dna.biggest_strength },
                { key: "biggest_weakness", label: "Biggest Weakness", type: "text", value: dna.biggest_weakness },
                { key: "biggest_opportunity", label: "Biggest Opportunity", type: "text", value: dna.biggest_opportunity },
              ],
            }) : undefined}
          >
            <KV label="STYLE" value={dna?.motivation_style} />
            <KV label="COACH STYLE" value={dna?.coaching_style} />
            <KV label="STRENGTH" value={dna?.biggest_strength} multiline />
            <KV label="WEAKNESS" value={dna?.biggest_weakness} multiline />
            <KV label="OPPORTUNITY" value={dna?.biggest_opportunity} multiline />
          </Section>
        </SectionGroup>

        {/* ═══════════ GROUP 2 · COACHING INTELLIGENCE ════════════════════ */}
        <SectionGroup id="coaching_intel" title="COACHING INTELLIGENCE" icon="pulse"
          subtitle="Your DNA, records, notes and evolution">

          {/* COACHING DNA */}
          <Section id="coaching_dna" title="COACHING DNA" icon="pulse" expanded={expanded} onToggle={toggle}
            rightSlot={dna?.ai_confidence_score !== undefined ? (
              <View style={styles.dnaPill}>
                <Text style={styles.dnaPillLabel}>CONF</Text>
                <Text style={styles.dnaPillNum}>{dna.ai_confidence_score}</Text>
              </View>
            ) : null}
            onOpen={() => router.push("/coaching-dna" as any)}
          >
            {dna ? (
              <>
                <KV label="VERSION" value={`v${dna.version || 1}`} />
                <KV label="SUMMARY" value={dna.summary} multiline />
                <Pressable onPress={() => router.push("/coaching-dna" as any)} style={styles.linkTile}>
                  <Text style={styles.linkTileT}>VIEW FULL DNA</Text>
                  <Ionicons name="arrow-forward" size={14} color={theme.color.brand} />
                </Pressable>
              </>
            ) : (
              <EmptyRow
                text="No Coaching DNA yet. Complete the CrewFit Intelligence Assessment to generate yours."
                actionLabel="START ASSESSMENT"
                onAction={() => router.push("/assessment" as any)}
              />
            )}
          </Section>

          {/* ACHIEVEMENTS */}
          <Section id="achievements" title="ACHIEVEMENTS" icon="trophy" expanded={expanded} onToggle={toggle}
            rightSlot={<CountPill n={(achievements.badges || []).filter((b: any) => b.unlocked).length} />}
          >
            <View style={styles.statsGrid}>
              <StatTile label="COMPLETED" value={stats.workouts_completed || 0} />
              <StatTile label="STREAK" value={`${stats.current_streak || 0}d`} />
              <StatTile label="EVENTS" value={stats.events_planned || 0} />
              <StatTile label="ADAPTATIONS" value={stats.reality_adaptations || 0} />
            </View>
            <View style={styles.badgeGrid}>
              {(achievements.badges || []).map((b: any) => (
                <View key={b.id} style={[styles.badge, !b.unlocked && styles.badgeLocked]}>
                  <Text style={styles.badgeEmoji}>{b.emoji}</Text>
                  <Text style={[styles.badgeTitle, !b.unlocked && styles.badgeTitleLocked]} numberOfLines={2}>{b.title}</Text>
                  <Text style={styles.badgeSub} numberOfLines={2}>{b.sub}</Text>
                </View>
              ))}
            </View>
          </Section>

          {/* PERSONAL RECORDS */}
          <Section id="prs" title="PERSONAL RECORDS" icon="trending-up" expanded={expanded} onToggle={toggle}
            rightSlot={<CountPill n={prs.length} />}
            onEdit={() => setPrModalOpen(true)}
            editLabel="+ ADD"
          >
            {prs.length === 0 ? (
              <EmptyRow text="No personal records yet. Log your first PR."
                actionLabel="ADD PR" onAction={() => setPrModalOpen(true)} />
            ) : (
              prs.slice(0, 12).map((p) => (
                <View key={p.id} style={styles.prRow}>
                  <View style={styles.prCat}><Text style={styles.prCatT}>{String(p.category || "?").slice(0, 3).toUpperCase()}</Text></View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.prName}>{p.name}</Text>
                    <Text style={styles.prMeta}>{p.date}</Text>
                  </View>
                  <Text style={styles.prValue}>{p.value}<Text style={styles.prUnit}> {p.unit}</Text></Text>
                </View>
              ))
            )}
          </Section>

          {/* LOUIS' NOTES */}
          <Section id="coach_notes" title="LOUIS' NOTES" icon="chatbubbles" expanded={expanded} onToggle={toggle}
            rightSlot={<CountPill n={(coachNotes.workout_notes || []).length + (coachNotes.reality_reviews || []).length} />}
          >
            {(coachNotes.workout_notes || []).slice(0, 5).map((w: any) => (
              <View key={w.id} style={styles.noteRow}>
                <Text style={styles.noteDate}>{w.date} · {w.title || "Workout"}</Text>
                <Text style={styles.noteText}>{w.coach_notes}</Text>
              </View>
            ))}
            {(coachNotes.reality_reviews || []).slice(0, 5).map((r: any) => (
              <View key={r.id} style={styles.noteRow}>
                <Text style={styles.noteDate}>{r.date} · {r.reality_label} · {r.status?.replace("_", " ").toUpperCase()}</Text>
                <Text style={styles.noteText}>{r.coach_note}</Text>
              </View>
            ))}
            {(coachNotes.workout_notes || []).length === 0 && (coachNotes.reality_reviews || []).length === 0 && (
              <EmptyRow text="No notes from Louis yet." />
            )}
          </Section>

          {/* CREWFIT NOTES */}
          <Section id="ai_notes" title="CREWFIT NOTES" icon="pulse" expanded={expanded} onToggle={toggle}
            rightSlot={<CountPill n={(aiNotes.reality_context || []).length + (aiNotes.move_rationales || []).length} />}
          >
            {(aiNotes.reality_context || []).slice(0, 5).map((r: any) => (
              <View key={r.id} style={styles.noteRow}>
                <Text style={styles.noteDate}>{r.date} · {r.reality_label} {r.recovery_score ? `· recovery ${r.recovery_score}` : ""}</Text>
                <Text style={styles.noteText}>{r.context_summary}</Text>
              </View>
            ))}
            {(aiNotes.move_rationales || []).slice(0, 5).map((m: any) => (
              <View key={m.id} style={styles.noteRow}>
                <Text style={styles.noteDate}>{m.date} · {m.reality_label} · {m.option_title}</Text>
                <Text style={styles.noteText}>{m.option_why}</Text>
              </View>
            ))}
            {(aiNotes.reality_context || []).length === 0 && (aiNotes.move_rationales || []).length === 0 && (
              <EmptyRow text="No notes yet. Use Today's Reality to add context." />
            )}
          </Section>

          {/* ASSESSMENT HISTORY */}
          <Section id="assess_hist" title="ASSESSMENT HISTORY" icon="time" expanded={expanded} onToggle={toggle}
            rightSlot={<CountPill n={assessments.length} />}
          >
            {assessments.length === 0 ? (
              <EmptyRow text="No assessments yet." actionLabel="TAKE ASSESSMENT" onAction={() => router.push("/assessment" as any)} />
            ) : (
              assessments.slice(0, 8).map((a) => (
                <View key={a.id} style={styles.evRow}>
                  <Ionicons name="sparkles" size={16} color={theme.color.brand} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.evName}>DNA v{a.dna_version || "—"}</Text>
                    <Text style={styles.evMeta}>{(a.completed_at || a.created_at || "").slice(0, 10)} · {(a.answers || []).length} answers · {a.status?.toUpperCase()}</Text>
                  </View>
                </View>
              ))
            )}
          </Section>

          {/* LIFE CHANGES */}
          <Section id="life_changes" title="LIFE CHANGES" icon="git-branch" expanded={expanded} onToggle={toggle}
            rightSlot={<CountPill n={(aiNotes.dna_history || []).length} />}
          >
            {(aiNotes.dna_history || []).length === 0 ? (
              <EmptyRow text="No life changes tracked yet." />
            ) : (
              (aiNotes.dna_history || []).slice(0, 10).map((h: any) => (
                <View key={h.id} style={styles.noteRow}>
                  <Text style={styles.noteDate}>{(h.created_at || "").slice(0, 10)} · {h.kind?.toUpperCase()}</Text>
                  <Text style={styles.noteText}>{h.reason || "(no reason)"} · {(h.changes || []).join(", ")}</Text>
                </View>
              ))
            )}
          </Section>
        </SectionGroup>

        {/* ═══════════ GROUP 3 · PREFERENCES & ACCOUNT ════════════════════ */}
        <SectionGroup id="prefs_account" title="PREFERENCES & ACCOUNT" icon="options"
          subtitle="How you train, eat, recover, notify">

          {/* EQUIPMENT */}
          <Section id="equipment" title="EQUIPMENT" icon="barbell" expanded={expanded} onToggle={toggle}
            onEdit={() => openEdit({
              title: "Equipment", scope: "user_profile", fields: [
                { key: "home_equipment", label: "Home equipment (comma-separated)", type: "multi_text", value: (user?.profile?.home_equipment || user?.profile?.equipment || []).join(", ") },
                { key: "max_home_minutes", label: "Max minutes at home", type: "number", value: user?.profile?.max_home_minutes },
              ],
            })}
          >
            {eqLocs.length > 0 ? (
              eqLocs.map((loc: any, i: number) => (
                <View key={i} style={{ marginBottom: 8 }}>
                  <Text style={styles.subLbl}>{String(loc.location || "home").toUpperCase()}</Text>
                  <View style={styles.chipRow}>
                    {(loc.equipment || []).map((eq: string, j: number) => (
                      <View key={j} style={styles.chip}><Text style={styles.chipT}>{eq}</Text></View>
                    ))}
                  </View>
                </View>
              ))
            ) : (
              <View style={styles.chipRow}>
                {(user?.profile?.home_equipment || user?.profile?.equipment || []).map((eq: string, i: number) => (
                  <View key={i} style={styles.chip}><Text style={styles.chipT}>{eq}</Text></View>
                ))}
                {(user?.profile?.home_equipment || user?.profile?.equipment || []).length === 0 && (
                  <EmptyRow text="No equipment saved yet." />
                )}
              </View>
            )}
          </Section>

          {/* RECOVERY */}
          <Section id="recovery" title="RECOVERY" icon="leaf" expanded={expanded} onToggle={toggle}>
            <KV label="RECOVERY RISK" value={String(dna?.recovery_risk || "unknown").toUpperCase()} highlight={dna?.recovery_risk === "high"} />
            <KV label="STRATEGY" value={dna?.recommended_recovery_strategy} multiline />
            {checkins.length > 0 ? (
              <>
                <Text style={styles.subLbl}>RECENT CHECK-INS</Text>
                {checkins.slice(0, 5).map((c: any) => (
                  <View key={c.id} style={styles.ciRow}>
                    <Text style={styles.ciDate}>{c.date}</Text>
                    <View style={styles.ciStats}>
                      <View style={styles.ciChip}><Ionicons name="moon" size={11} color={theme.color.textMuted} /><Text style={styles.ciStat}>{c.sleep ?? "—"}</Text></View>
                      <View style={styles.ciChip}><Ionicons name="flash" size={11} color={theme.color.amber} /><Text style={styles.ciStat}>{c.energy ?? "—"}</Text></View>
                      <View style={styles.ciChip}><Ionicons name="pulse" size={11} color={theme.color.brand} /><Text style={styles.ciStat}>{c.stress ?? "—"}</Text></View>
                    </View>
                  </View>
                ))}
              </>
            ) : null}
          </Section>

          {/* NUTRITION */}
          <Section id="nutrition" title="NUTRITION" icon="restaurant" expanded={expanded} onToggle={toggle}
            disabled={!dna}
            onEdit={dna ? () => openEdit({
              title: "Nutrition", scope: "coaching_dna", fields: [
                { key: "nutrition_summary", label: "Nutrition Summary", type: "multi_text", value: dna.nutrition_summary },
              ],
            }) : undefined}
          >
            <KV label="EATING PATTERN" value={dna?.nutrition_summary} multiline />
            <KV label="STRATEGY" value={dna?.recommended_nutrition_strategy} multiline />
          </Section>

          {/* TRAINING PREFERENCES */}
          <Section id="training_prefs" title="TRAINING PREFERENCES" icon="options" expanded={expanded} onToggle={toggle}
            disabled={!dna}
            onEdit={dna ? () => openEdit({
              title: "Training Preferences", scope: "coaching_dna", fields: [
                { key: "training_availability", label: "Training Availability JSON", type: "multi_text", value: JSON.stringify(dna.training_availability || {}, null, 2) },
                { key: "training_experience", label: "Experience Level", type: "text", value: dna.training_experience },
              ],
            }) : undefined}
          >
            <KV label="EXPERIENCE" value={dna?.training_experience} />
            <KV label="HOME" value={ta.home ? `${ta.home} min` : undefined} />
            <KV label="LAYOVERS" value={ta.layovers ? `${ta.layovers} min` : undefined} />
            <KV label="DAYS OFF" value={ta.days_off ? `${ta.days_off} min` : undefined} />
            <KV label="STANDBY" value={ta.standby ? `${ta.standby} min` : undefined} />
            <KV label="PREFERRED TIME" value={ta.preferred_time} />
            <KV label="WEEKLY TEMPLATE" value={dna?.recommended_weekly_training} multiline />
          </Section>

          {/* Legacy panels — habits, notifications, workout settings */}
          <HabitsProfileSection />
          <NotificationPreferencesCard />
          <WorkoutSettingsPanel />

          <View style={{ height: 8 }} />
          <Pressable testID="hq-take-assessment" onPress={() => router.push("/assessment" as any)} style={styles.retakeCta}>
            <Ionicons name="sparkles" size={16} color={theme.color.brand} />
            <Text style={styles.retakeText}>RE-TAKE ASSESSMENT · EVOLVE YOUR DNA</Text>
          </Pressable>
          <Pressable testID="hq-legacy-onboarding" onPress={() => router.push("/(auth)/onboarding")} style={styles.legacyCta}>
            <Text style={styles.legacyText}>EDIT LEGACY PROFILE</Text>
          </Pressable>
          <Pressable
            testID="hq-change-password"
            onPress={() => setChangePasswordOpen(true)}
            style={[styles.legacyCta, { marginTop: 8 }]}
          >
            <Text style={styles.legacyText}>CHANGE PASSWORD</Text>
          </Pressable>
        </SectionGroup>

        {/* ═══════════ GROUP 4 · SUPPORT & LEGAL ═════════════════════════ */}
        <SectionGroup id="support_legal" title="SUPPORT & LEGAL" icon="shield-checkmark"
          subtitle="Help, terms, account controls">
          <Pressable testID="hq-legal" onPress={() => router.push("/legal" as any)} style={styles.legacyCta}>
            <Text style={styles.legacyText}>LEGAL &amp; PRIVACY</Text>
          </Pressable>
          <Pressable
            testID="hq-support"
            onPress={() => router.push("/legal/contact" as any)}
            style={[styles.legacyCta, { marginTop: 8 }]}
          >
            <Text style={styles.legacyText}>SUPPORT</Text>
          </Pressable>
          <Pressable testID="hq-delete-account" onPress={() => router.push("/legal/delete-account" as any)} style={[styles.legacyCta, { borderColor: theme.color.brand, marginTop: 8 }]}>
            <Text style={[styles.legacyText, { color: theme.color.brand }]}>DELETE MY ACCOUNT</Text>
          </Pressable>
          <Pressable
            testID="hq-logout-primary"
            onPress={confirmLogout}
            style={[styles.legacyCta, { borderColor: theme.color.red || "#c85450", marginTop: 8 }]}
          >
            <Text style={[styles.legacyText, { color: theme.color.red || "#c85450" }]}>
              {preview.active ? "EXIT PREVIEW" : "LOG OUT"}
            </Text>
          </Pressable>
        </SectionGroup>

        <View style={{ height: 32 }} />
      </ScrollView>

      {/* Edit sheet */}
      {editing && (
        <EditSheet
          spec={editing}
          onClose={() => setEditing(null)}
          onSave={saveEdit}
        />
      )}

      {/* Add PR modal */}
      <PRAddModal
        visible={prModalOpen}
        onClose={() => setPrModalOpen(false)}
        onSaved={() => { setPrModalOpen(false); load(); }}
      />

      {/* Change password modal */}
      <ChangePasswordModal
        visible={changePasswordOpen}
        onClose={() => setChangePasswordOpen(false)}
      />
    </SafeAreaView>
  );
}

/* -------------------------------------------------------------------------- */
/*  Section Component                                                         */
/* -------------------------------------------------------------------------- */
/* -------------------------------------------------------------------------- */
/*  SectionGroup — Iter168 Profile Accordions                                 */
/* -------------------------------------------------------------------------- */
/**
 * Groups a set of <Section /> elements behind one top-level accordion.
 * Collapsed by default; state persisted to AsyncStorage per group id
 * so the user's last choice survives app relaunches.
 */
function SectionGroup({
  id, title, icon, subtitle, children,
}: {
  id: string; title: string; icon: any; subtitle?: string;
  children: React.ReactNode;
}) {
  const storageKey = `crewfit.profile.group.${id}`;
  const [open, setOpen] = React.useState(false);

  React.useEffect(() => {
    AsyncStorage.getItem(storageKey)
      .then((v) => setOpen(v === "1"))
      .catch(() => {});
  }, [storageKey]);

  const toggle = () => {
    setOpen((prev) => {
      const next = !prev;
      AsyncStorage.setItem(storageKey, next ? "1" : "0").catch(() => {});
      return next;
    });
  };

  return (
    <View style={styles.groupCard}>
      <Pressable style={styles.groupHead} onPress={toggle} testID={`profile-group-${id}`}>
        <View style={styles.groupHeadIcon}>
          <Ionicons name={icon} size={18} color={theme.color.brand} />
        </View>
        <View style={{ flex: 1, minWidth: 0 }}>
          <Text style={styles.groupHeadT}>{title}</Text>
          {subtitle ? <Text style={styles.groupHeadSub} numberOfLines={1}>{subtitle}</Text> : null}
        </View>
        <Ionicons
          name={open ? "chevron-up" : "chevron-down"}
          size={18}
          color={theme.color.textMuted}
        />
      </Pressable>
      {open ? <View style={styles.groupBody}>{children}</View> : null}
    </View>
  );
}

function Section({
  id, title, icon, children, expanded, onToggle, onEdit, editLabel, onOpen, rightSlot, disabled,
}: {
  id: string; title: string; icon?: any;
  children: React.ReactNode;
  expanded: Record<string, boolean>;
  onToggle: (id: string) => void;
  onEdit?: () => void;
  editLabel?: string;
  onOpen?: () => void;
  rightSlot?: React.ReactNode;
  disabled?: boolean;
}) {
  const on = !!expanded[id];
  return (
    <View style={styles.section}>
      <Pressable style={styles.secHeader} onPress={() => !disabled && onToggle(id)} disabled={disabled}>
        <Ionicons name={icon || "ellipse-outline"} size={16} color={theme.color.brand} />
        <Text style={[styles.secTitle, disabled && { opacity: 0.4 }]}>{title}</Text>
        {rightSlot ? <View>{rightSlot}</View> : null}
        {onEdit && !disabled ? (
          <Pressable onPress={onEdit} testID={`edit-${id}`} style={styles.editBtn} hitSlop={8}>
            <Text style={styles.editBtnT}>{editLabel || "EDIT"}</Text>
          </Pressable>
        ) : null}
        {onOpen ? (
          <Pressable onPress={onOpen} testID={`open-${id}`} hitSlop={8}>
            <Ionicons name="open-outline" size={16} color={theme.color.brand} />
          </Pressable>
        ) : null}
        <Ionicons name={on ? "chevron-up" : "chevron-down"} size={16} color={theme.color.textDim} />
      </Pressable>
      {on && !disabled && <View style={styles.secBody}>{children}</View>}
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/*  Small UI helpers                                                          */
/* -------------------------------------------------------------------------- */
function KV({ label, value, multiline, highlight }: { label: string; value?: any; multiline?: boolean; highlight?: boolean }) {
  if (value === undefined || value === null || value === "") return null;
  return (
    <View style={styles.kv}>
      <Text style={styles.kvLbl}>{label}</Text>
      <Text
        style={[styles.kvVal, multiline && styles.kvValMulti, highlight && styles.kvValHi]}
        numberOfLines={multiline ? 8 : 2}
      >
        {String(value)}
      </Text>
    </View>
  );
}

function CountPill({ n }: { n: number }) {
  return <View style={styles.countPill}><Text style={styles.countPillT}>{n}</Text></View>;
}

function StatTile({ label, value }: { label: string; value: any }) {
  return (
    <View style={styles.statTile}>
      <Text style={styles.statNum}>{String(value)}</Text>
      <Text style={styles.statLbl}>{label}</Text>
    </View>
  );
}

function EmptyRow({ text, actionLabel, onAction }: { text: string; actionLabel?: string; onAction?: () => void }) {
  return (
    <View style={styles.emptyBox}>
      <Text style={styles.emptyT}>{text}</Text>
      {actionLabel && onAction ? (
        <Pressable onPress={onAction} style={styles.emptyBtn}>
          <Text style={styles.emptyBtnT}>{actionLabel}</Text>
          <Ionicons name="arrow-forward" size={12} color={theme.color.brand} />
        </Pressable>
      ) : null}
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/*  Edit Sheet                                                                */
/* -------------------------------------------------------------------------- */
function EditSheet({ spec, onClose, onSave }: { spec: EditSpec; onClose: () => void; onSave: (v: Record<string, any>) => void }) {
  const [vals, setVals] = useState<Record<string, any>>(() =>
    Object.fromEntries(spec.fields.map((f) => [f.key, f.value ?? ""]))
  );
  const setV = (k: string, v: any) => setVals((s) => ({ ...s, [k]: v }));

  const build = () => {
    const out: Record<string, any> = {};
    for (const f of spec.fields) {
      const raw = vals[f.key];
      if (f.type === "number") {
        const n = parseFloat(raw);
        if (!Number.isNaN(n)) out[f.key] = n;
        continue;
      }
      if (typeof raw === "string" && raw.trim().startsWith("{")) {
        try { out[f.key] = JSON.parse(raw); continue; } catch { /* ignore */ }
      }
      if (f.type === "multi_text" && f.key.endsWith("_goals")) {
        out[f.key] = String(raw || "").split(",").map((x) => x.trim()).filter(Boolean);
        continue;
      }
      if (f.key === "home_equipment") {
        out[f.key] = String(raw || "").split(",").map((x) => x.trim()).filter(Boolean);
        continue;
      }
      if (raw === "") continue;
      out[f.key] = raw;
    }
    return out;
  };

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.editRoot}>
        <Pressable style={styles.editBackdrop} onPress={onClose} />
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={styles.editCard}>
            <View style={styles.editHead}>
              <Text style={styles.editTitle}>{spec.title.toUpperCase()}</Text>
              <Pressable onPress={onClose} hitSlop={12}>
                <Ionicons name="close" size={20} color={theme.color.text} />
              </Pressable>
            </View>
            <ScrollView contentContainerStyle={{ padding: 16 }} keyboardShouldPersistTaps="handled">
              {spec.fields.map((f) => (
                <View key={f.key} style={{ marginBottom: 12 }}>
                  <Text style={styles.editLbl}>{f.label.toUpperCase()}</Text>
                  <TextInput
                    value={String(vals[f.key] ?? "")}
                    onChangeText={(t) => setV(f.key, t)}
                    keyboardType={f.type === "number" ? "decimal-pad" : "default"}
                    multiline={f.type === "multi_text"}
                    placeholder={f.unit || (f.type === "multi_text" ? "..." : "")}
                    placeholderTextColor={theme.color.textDim}
                    style={[styles.editInput, f.type === "multi_text" && styles.editInputMulti]}
                  />
                  {f.unit ? <Text style={styles.editUnit}>{f.unit}</Text> : null}
                </View>
              ))}
              <Pressable onPress={() => onSave(build())} style={styles.saveBtn}>
                <Text style={styles.saveBtnT}>SAVE</Text>
                <Ionicons name="checkmark" size={16} color="#fff" />
              </Pressable>
            </ScrollView>
          </View>
        </KeyboardAvoidingView>
      </View>
    </Modal>
  );
}

/* -------------------------------------------------------------------------- */
/*  Add PR Modal                                                              */
/* -------------------------------------------------------------------------- */
function PRAddModal({ visible, onClose, onSaved }: { visible: boolean; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState("kg");
  const [category, setCategory] = useState("strength");
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));

  useEffect(() => {
    if (!visible) { setName(""); setValue(""); setUnit("kg"); setCategory("strength"); setDate(new Date().toISOString().slice(0, 10)); }
  }, [visible]);

  const save = async () => {
    if (!name.trim() || !value) { Alert.alert("Missing", "Please enter a name and value."); return; }
    try {
      await api("/personal-records", {
        method: "POST",
        body: { name: name.trim(), value: parseFloat(value), unit, category, date },
      });
      onSaved();
    } catch (e: any) {
      Alert.alert("Save failed", e?.message || "Please try again");
    }
  };

  const cats = ["strength", "run", "swim", "bike", "other"];
  const units = ["kg", "lb", "km", "mi", "min", "sec"];

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.editRoot}>
        <Pressable style={styles.editBackdrop} onPress={onClose} />
        <View style={styles.editCard}>
          <View style={styles.editHead}>
            <Text style={styles.editTitle}>ADD PERSONAL RECORD</Text>
            <Pressable onPress={onClose} hitSlop={12}>
              <Ionicons name="close" size={20} color={theme.color.text} />
            </Pressable>
          </View>
          <ScrollView contentContainerStyle={{ padding: 16 }} keyboardShouldPersistTaps="handled">
            <Text style={styles.editLbl}>NAME</Text>
            <TextInput value={name} onChangeText={setName} placeholder="e.g. Back Squat 1RM"
              placeholderTextColor={theme.color.textDim} style={styles.editInput} />
            <Text style={styles.editLbl}>CATEGORY</Text>
            <View style={styles.chipRow}>
              {cats.map((c) => (
                <Pressable key={c} onPress={() => setCategory(c)} style={[styles.chip, category === c && styles.chipOn]}>
                  <Text style={[styles.chipT, category === c && { color: "#fff" }]}>{c.toUpperCase()}</Text>
                </Pressable>
              ))}
            </View>
            <View style={styles.rowGap}>
              <View style={{ flex: 2 }}>
                <Text style={styles.editLbl}>VALUE</Text>
                <TextInput value={value} onChangeText={setValue} keyboardType="decimal-pad"
                  placeholderTextColor={theme.color.textDim} placeholder="0" style={styles.editInput} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.editLbl}>UNIT</Text>
                <View style={styles.chipRow}>
                  {units.map((u) => (
                    <Pressable key={u} onPress={() => setUnit(u)} style={[styles.chip, unit === u && styles.chipOn]}>
                      <Text style={[styles.chipT, unit === u && { color: "#fff" }]}>{u}</Text>
                    </Pressable>
                  ))}
                </View>
              </View>
            </View>
            <Text style={styles.editLbl}>DATE</Text>
            <DateField value={date} onChange={setDate} testID="pr-date-picker" />
            <View style={{ height: 8 }} />
            <Pressable onPress={save} style={styles.saveBtn} testID="pr-save">
              <Text style={styles.saveBtnT}>SAVE PR</Text>
              <Ionicons name="checkmark" size={16} color="#fff" />
            </Pressable>
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

/* -------------------------------------------------------------------------- */
/*  Styles                                                                    */
/* -------------------------------------------------------------------------- */
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: {
    flexDirection: "row", alignItems: "center", padding: 20,
    borderBottomWidth: 1, borderBottomColor: theme.color.divider,
  },
  title: { color: theme.color.text, fontSize: 14, fontWeight: "900", letterSpacing: 2 },
  brandRed: { color: theme.color.brand },
  sub: { color: theme.color.textMuted, fontSize: 11, marginTop: 3 },
  iconBtn: { padding: 6 },
  body: { padding: 16, paddingBottom: 60 },

  section: {
    marginBottom: 10, borderRadius: 12,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
    overflow: "hidden",
  },
  /* Iter168 · Profile group (top-level accordion). Wraps 4-7 Sections
     inside a single collapsible surface, styled distinct from the inner
     section cards. */
  groupCard: {
    marginTop: 14,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: theme.color.border,
    backgroundColor: theme.color.surface,
    overflow: "hidden",
  },
  groupHead: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingHorizontal: 14,
    paddingVertical: 16,
  },
  groupHeadIcon: {
    width: 34, height: 34, borderRadius: 17,
    backgroundColor: theme.color.brandTint,
    borderWidth: 1, borderColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
  },
  groupHeadT: {
    color: theme.color.text, fontSize: 14, fontWeight: "800",
    letterSpacing: 1.6, fontFamily: theme.font.textSemi,
  },
  groupHeadSub: {
    color: theme.color.textMuted, fontSize: 11, fontWeight: "600",
    marginTop: 2, letterSpacing: 0.4,
  },
  groupBody: {
    paddingHorizontal: 10,
    paddingTop: 4,
    paddingBottom: 12,
    gap: 6,
    borderTopWidth: 1,
    borderTopColor: theme.color.divider,
  },
  secHeader: {
    flexDirection: "row", alignItems: "center", gap: 8,
    padding: 14,
  },
  secEmoji: { fontSize: 18 },
  secTitle: { flex: 1, color: theme.color.text, fontSize: 12, fontWeight: "900", letterSpacing: 2 },
  editBtn: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 4, borderWidth: 1, borderColor: theme.color.brand },
  editBtnT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  secBody: { paddingHorizontal: 14, paddingBottom: 14, gap: 6 },

  kv: { padding: 8, borderRadius: 6, backgroundColor: theme.color.surface, borderLeftWidth: 2, borderLeftColor: theme.color.border },
  kvLbl: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1.5, marginBottom: 3 },
  kvVal: { color: theme.color.text, fontSize: 13, fontWeight: "700" },
  kvValMulti: { fontSize: 12, lineHeight: 18, fontWeight: "500" },
  kvValHi: { color: theme.color.brand, fontSize: 15, fontWeight: "900" },
  subLbl: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5, marginTop: 6, marginBottom: 4 },

  linkTile: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    padding: 10, marginTop: 6, borderRadius: 8,
    backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand,
  },
  linkTileT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },

  dnaPill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 8, paddingVertical: 4, borderRadius: 4,
    backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand,
  },
  dnaPillLabel: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1 },
  dnaPillNum: { color: theme.color.brand, fontSize: 12, fontWeight: "900" },

  countPill: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 4, backgroundColor: theme.color.surface3 },
  countPillT: { color: theme.color.text, fontSize: 11, fontWeight: "900" },

  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 4 },
  chip: { paddingHorizontal: 10, paddingVertical: 5, borderRadius: 12, backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border },
  chipOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipT: { color: theme.color.text, fontSize: 11, fontWeight: "700" },

  evRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    padding: 10, borderRadius: 8, marginBottom: 6,
    backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border,
  },
  evEmoji: { fontSize: 18 },
  evName: { color: theme.color.text, fontSize: 12, fontWeight: "800" },
  evMeta: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },
  activeDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: theme.color.green },
  phasePill: { paddingHorizontal: 6, paddingVertical: 3, borderRadius: 4, backgroundColor: theme.color.brandTint },
  phasePillT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1 },

  ciRow: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    paddingVertical: 6, borderTopWidth: 1, borderTopColor: theme.color.divider,
  },
  ciDate: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700" },
  ciStats: { flexDirection: "row", gap: 6 },
  ciChip: { flexDirection: "row", alignItems: "center", gap: 3, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 10, backgroundColor: theme.color.surface3 },
  ciStat: { color: theme.color.text, fontSize: 11, fontWeight: "700" },

  statsGrid: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 8 },
  statTile: {
    flex: 1, minWidth: "22%", padding: 10, borderRadius: 8,
    backgroundColor: theme.color.surface, alignItems: "center",
    borderWidth: 1, borderColor: theme.color.border,
  },
  statNum: { color: theme.color.brand, fontSize: 18, fontWeight: "900" },
  statLbl: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1.5, marginTop: 3 },

  badgeGrid: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  badge: {
    width: "31%", padding: 8, borderRadius: 8,
    backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border,
    alignItems: "center",
  },
  badgeLocked: { opacity: 0.35 },
  badgeEmoji: { fontSize: 22 },
  badgeTitle: { color: theme.color.text, fontSize: 11, fontWeight: "900", textAlign: "center", marginTop: 3 },
  badgeTitleLocked: { color: theme.color.textDim },
  badgeSub: { color: theme.color.textDim, fontSize: 11, textAlign: "center", marginTop: 2 },

  prRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    padding: 8, borderRadius: 6, marginBottom: 4,
    backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border,
  },
  prCat: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: theme.color.brandTint,
    alignItems: "center", justifyContent: "center",
  },
  prCatT: { color: theme.color.brand, fontSize: 11, fontWeight: "900" },
  prName: { color: theme.color.text, fontSize: 12, fontWeight: "800" },
  prMeta: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },
  prValue: { color: theme.color.text, fontSize: 15, fontWeight: "900" },
  prUnit: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700" },

  noteRow: {
    padding: 8, borderRadius: 6, marginBottom: 4,
    backgroundColor: theme.color.surface, borderLeftWidth: 2, borderLeftColor: theme.color.brand,
  },
  noteDate: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1, marginBottom: 3 },
  noteText: { color: theme.color.text, fontSize: 12, lineHeight: 18 },

  emptyBox: { padding: 14, alignItems: "center", justifyContent: "center" },
  emptyT: { color: theme.color.textMuted, fontSize: 12, textAlign: "center", lineHeight: 18 },
  emptyBtn: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 8 },
  emptyBtnT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },

  retakeCta: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    paddingVertical: 14, borderRadius: 10,
    backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand,
    marginBottom: 8,
  },
  retakeText: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  legacyCta: { alignItems: "center", paddingVertical: 10 },
  legacyText: { color: theme.color.textMuted, fontSize: 11, fontWeight: "800", letterSpacing: 2 },

  editRoot: { flex: 1, justifyContent: "flex-end" },
  editBackdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.7)" },
  editCard: {
    maxHeight: "90%", backgroundColor: theme.color.surface,
    borderTopLeftRadius: 20, borderTopRightRadius: 20,
    borderWidth: 1, borderColor: theme.color.border,
  },
  editHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 14, borderBottomWidth: 1, borderBottomColor: theme.color.border },
  editTitle: { color: theme.color.text, fontSize: 12, fontWeight: "900", letterSpacing: 2 },
  editLbl: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2, marginTop: 8, marginBottom: 6 },
  editInput: {
    color: theme.color.text, fontSize: 13, padding: 10,
    borderRadius: 8, backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
  },
  editInputMulti: { minHeight: 80, textAlignVertical: "top" },
  editUnit: { color: theme.color.textDim, fontSize: 11, marginTop: 2, fontWeight: "700" },
  saveBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    padding: 14, borderRadius: 10, marginTop: 20,
    backgroundColor: theme.color.brand,
  },
  saveBtnT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 2 },
  rowGap: { flexDirection: "row", gap: 10 },
  systemBanner: {
    padding: 16, borderRadius: 14, marginBottom: 14,
    backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand,
  },
  systemHead: { flexDirection: "row", alignItems: "center", gap: 12, marginBottom: 12 },
  systemIcon: {
    width: 44, height: 44, borderRadius: 22,
    backgroundColor: theme.color.surface,
    borderWidth: 1, borderColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
  },
  systemEyebrow: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  systemTitle: { color: theme.color.text, fontSize: 16, fontWeight: "900", letterSpacing: 1, marginTop: 3 },
  systemBody: { color: theme.color.text, fontSize: 12, lineHeight: 18, marginBottom: 14 },
  systemActions: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  systemBtnPrimary: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingVertical: 8, paddingHorizontal: 12, borderRadius: 6,
    backgroundColor: theme.color.brand,
  },
  systemBtnPrimaryT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  systemBtnSecondary: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingVertical: 8, paddingHorizontal: 12, borderRadius: 6,
    borderWidth: 1, borderColor: theme.color.brand,
  },
  systemBtnSecondaryT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
});

/* -------------------------------------------------------------------------- */
/*  Habits section — Coaching Headquarters                                    */
/* -------------------------------------------------------------------------- */
function HabitsProfileSection() {
  const [active, setActive] = useState<any[]>([]);
  const [paused, setPaused] = useState<any[]>([]);
  const [remindersOn, setRemindersOn] = useState(true);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<{ active: any[]; paused: any[] }>("/habits/mine");
      setActive(r.active || []);
      setPaused(r.paused || []);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const toggle = async () => {
    const next = !remindersOn;
    setRemindersOn(next);
    try {
      await api("/habits/reminders/toggle", { method: "POST", body: { enabled: next } });
    } catch {
      setRemindersOn(!next);
    }
  };

  const seed = async () => {
    setBusy(true);
    try {
      await api("/habits/seed", { method: "POST" });
      await load();
    } catch (e: any) {
      Alert.alert("Couldn't seed habits", e?.message || "Try again");
    } finally { setBusy(false); }
  };

  if (loading) return null;

  return (
    <View style={hstyles.wrap}>
      <View style={hstyles.headRow}>
        <Text style={hstyles.head}>HABITS</Text>
        <Pressable onPress={toggle} testID="habit-reminders-toggle" style={[hstyles.toggle, remindersOn && hstyles.toggleOn]}>
          <Text style={[hstyles.toggleT, remindersOn && { color: "#fff" }]}>REMINDERS {remindersOn ? "ON" : "OFF"}</Text>
        </Pressable>
      </View>
      {active.length === 0 && paused.length === 0 ? (
        <Pressable onPress={seed} disabled={busy} style={hstyles.emptyCta}>
          {busy ? <ActivityIndicator color={theme.color.brand} /> : (
            <>
              <Ionicons name="sparkles" size={16} color={theme.color.brand} />
              <Text style={hstyles.emptyCtaT}>ATLAS · SEED MY STARTER HABITS</Text>
            </>
          )}
        </Pressable>
      ) : null}
      {active.length > 0 ? (
        <>
          <Text style={hstyles.sub}>ACTIVE · {active.length}</Text>
          <View style={{ gap: 8 }}>
            {active.map((h) => (
              <View key={h.id} style={hstyles.card}>
                <Text style={hstyles.hTitle}>{h.title}</Text>
                {h.reason ? <Text style={hstyles.hReason}>{h.reason}</Text> : null}
                <View style={hstyles.metaRow}>
                  {h.linked_goal ? <Text style={hstyles.metaChip}>{String(h.linked_goal).toUpperCase().replace(/_/g, " ")}</Text> : null}
                  <Text style={hstyles.metaChip}>{String(h.habit_type).toUpperCase().replace(/-/g, " ")}</Text>
                  {typeof h.streak === "number" && h.streak > 0 ? (
                    <Text style={[hstyles.metaChip, { color: theme.color.brand }]}>{h.streak}d</Text>
                  ) : null}
                </View>
              </View>
            ))}
          </View>
        </>
      ) : null}
      {paused.length > 0 ? (
        <>
          <Text style={hstyles.sub}>PAUSED · {paused.length}</Text>
          <View style={{ gap: 8 }}>
            {paused.map((h) => (
              <View key={h.id} style={[hstyles.card, { opacity: 0.6 }]}>
                <Text style={hstyles.hTitle}>{h.title}</Text>
                {h.reason ? <Text style={hstyles.hReason}>{h.reason}</Text> : null}
              </View>
            ))}
          </View>
        </>
      ) : null}
    </View>
  );
}

const hstyles = StyleSheet.create({
  wrap: { marginTop: 24, marginHorizontal: 20 },
  headRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 10 },
  head: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  toggle: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 4, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  toggleOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  toggleT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  sub: { color: theme.color.textDim, fontSize: 11, fontWeight: "800", letterSpacing: 1.5, marginTop: 12, marginBottom: 6 },
  card: { padding: 12, backgroundColor: theme.color.surface2, borderRadius: 10, borderWidth: 1, borderColor: theme.color.border },
  hTitle: { color: theme.color.text, fontSize: 13, fontWeight: "800" },
  hReason: { color: theme.color.textMuted, fontSize: 11, marginTop: 3, lineHeight: 15 },
  metaRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 6 },
  metaChip: { color: theme.color.textDim, fontSize: 11, fontWeight: "800", letterSpacing: 1 },
  emptyCta: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, padding: 14, borderRadius: 10, borderWidth: 1, borderStyle: "dashed", borderColor: theme.color.brand, backgroundColor: theme.color.brandTint },
  emptyCtaT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
});
