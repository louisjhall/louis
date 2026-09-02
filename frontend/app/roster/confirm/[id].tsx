import { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ScrollView, ActivityIndicator, Alert,
  TextInput, KeyboardAvoidingView, Platform, Modal,
} from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { useBottomSafePad } from "@/src/lib/useBottomSafePad";

// Duty types the client can pick from. Keys are what get persisted on
// day.day_type; labels are what the user sees.
const DUTY_TYPES: { key: string; label: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { key: "Flight",        label: "Flight (turnaround)",  icon: "airplane" },
  // Iter 94n — "Direct Flight" is a distinct duty type from a turnaround.
  // Turnaround = out & back the same day. Direct flight = one-way sector
  // that ends at a destination city (typically before a layover, or a
  // positioning leg). Coach/roster generator differentiates load & recovery
  // for these two.
  { key: "Direct Flight", label: "Direct flight",        icon: "paper-plane" },
  { key: "Layover",       label: "Layover",              icon: "bed" },
  { key: "Standby",       label: "Standby",              icon: "time" },
  { key: "Off",           label: "Off duty",             icon: "sunny" },
  { key: "Home",          label: "Home",                 icon: "home" },
  { key: "Sim / Training", label: "Sim / Training",      icon: "school" },
  { key: "Sick",          label: "Sick",                 icon: "medkit" },
  { key: "Annual Leave",  label: "Annual leave",         icon: "leaf" },
  { key: "Unknown/Needs Confirmation", label: "Not sure yet", icon: "help-circle" },
];

// Iter 83 · Tool 3 — the most-common duty types, shown inline on each card
// for a single-tap change without opening the full editor.
// Iter 94n — "Direct" added so a client can distinguish a one-way sector
// (typically before a layover) from a full turnaround, one tap on the card.
const QUICK_CHIPS: { key: string; label: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { key: "Flight",        label: "Flight",  icon: "airplane" },
  { key: "Direct Flight", label: "Direct",  icon: "paper-plane" },
  { key: "Layover",       label: "Layover", icon: "bed" },
  { key: "Standby",       label: "Standby", icon: "time" },
  { key: "Off",           label: "Off",     icon: "sunny" },
  { key: "Home",          label: "Home",    icon: "home" },
];

type Day = {
  date: string;
  day_type: string;
  layover_city?: string | null;
  layover_nights?: number | null;
  report_time?: string | null;
  duty_end_time?: string | null;
  notes?: string | null;
  confidence?: number;
  _confirmed_by_user?: boolean;
  _needs_review?: boolean;
  flights?: any[];
  load?: string;
  home_or_away?: string;
  // Parser-generated labels (Etihad / Emirates)
  client_label?: string | null;
  training_colour?: "green" | "amber" | "red" | "black" | null;
  blocked?: string[] | null;
  equipment_assumption?: string | null;
  label?: string | null;
  source?: string | null;
};

type Pending = {
  id: string;
  start_date?: string;
  end_date?: string;
  day_count: number;
  confidence_avg: number;
  source_filename?: string | null;
  days: Day[];
  review_flags?: { low_confidence_count: number };
  overlap?: { overlapping_dates: string[]; changes: { date: string; prev: any; new: any }[] } | null;
  overlap_mode?: "replace" | "merge" | "keep_both" | null;
  _queue?: {
    total: number;
    index: number;
    next_id?: string | null;
    next_range?: string | null;
    next_filename?: string | null;
  };
};

function fmtDate(iso?: string | null) {
  if (!iso) return "";
  try {
    const d = new Date(iso + "T00:00:00");
    return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  } catch {
    return iso;
  }
}

// Iter200 · Customer-friendly presenter fallback.
// The backend normalizer populates `client_label` for every day — but
// older rosters (or ones from a code path we haven't rewired) may still
// send raw internal day types. Map those to plain English so the
// customer never sees `midnight_crossing_flight` / `layover_full` /
// `flight_to_layover` etc.
const _DAY_TYPE_PRETTY: Record<string, string> = {
  day_off: "Day off",
  home_day: "Home day",
  rest_day: "Rest day",
  standby: "Standby",
  sim_training: "Simulator / training",
  annual_leave: "Annual leave",
  sickness: "Sick / off-sick",
  night_flight: "Night flight",
  turnaround: "Flying",
  flight: "Flying",
  multi_sector_flight: "Flying (multi-sector)",
  flight_to_layover: "Flying to layover",
  return_from_layover: "Return from layover",
  layover_day: "Layover day",
  overnight_flight: "Overnight flight",
  needs_review: "Needs your check",
  unknown: "Needs your check",
  "unknown/needs confirmation": "Needs your check",
  // legacy LLM types (map any that leak through)
  "layover arrival day": "Flying to layover",
  "layover full day": "Layover day",
  "layover departure day": "Return from layover",
  "turnaround duty": "Flying",
  "long-haul turnaround": "Flying (long-haul)",
  "short-haul turnaround": "Flying",
  "home day": "Home day",
};

function _prettyDayType(raw?: string | null): string {
  if (!raw) return "";
  const key = raw.toLowerCase().trim();
  if (_DAY_TYPE_PRETTY[key]) return _DAY_TYPE_PRETTY[key];
  // Snake_case → Title Case fallback so `some_new_type` reads as "Some new type"
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// Iter200 · Filter debug/parser notes out of the customer view.
const _DEBUG_NOTE_TOKENS = [
  "blank day inside", "out-of-base pairing", "arrow marker",
  "inferred layover", "started as overnight", "continuation block",
  "midnight_crossing", "not a layover.", "→ inferred",
  "blank column", "layover inference",
];
function _isDebugNote(text?: string | null): boolean {
  if (!text) return false;
  const lo = text.toLowerCase();
  return _DEBUG_NOTE_TOKENS.some((t) => lo.includes(t));
}

// Iter200-d · Map the chip labels the user picks in the Edit modal
// (title-case, legacy keys) to the internal type vocabulary the backend
// normalizer uses. Ensures the card icon + label update instantly.
function _chipKeyToInternal(raw?: string | null): string {
  const k = (raw || "").toLowerCase().trim();
  if (!k) return "unknown";
  if (k === "flight" || k === "flight (turnaround)") return "turnaround";
  if (k === "direct flight" || k === "direct") return "flight";
  if (k === "layover") return "flight_to_layover";
  if (k === "standby") return "standby";
  if (k === "off" || k === "off duty") return "day_off";
  if (k === "home") return "home_day";
  if (k === "sim / training" || k === "sim") return "sim_training";
  if (k === "sick" || k === "sickness") return "sickness";
  if (k === "annual leave") return "annual_leave";
  if (k === "unknown/needs confirmation" || k === "not sure yet") return "needs_review";
  // If already an internal type, pass through unchanged.
  return k.replace(/\s+/g, "_");
}

// Iter200-d · Client-side mirror of the backend `_customer_label` in
// parsers/roster_normalizer.py. Called after the user changes a day so
// the card updates instantly rather than after the next server sync.
function _regenerateClientLabel(d: Day): string {
  const internal = (d.day_type || "").toLowerCase();
  const flights = (d as any).flights || [];
  const parts: string[] = [];
  if (flights.length) {
    parts.push(flights[0].from);
    for (const f of flights) parts.push(f.to);
  }
  const route = parts.filter(Boolean).join(" → ");
  const city = d.layover_city || "";
  const win = (() => {
    const s = (d as any).standby_start_time || d.report_time || "";
    const e = (d as any).standby_end_time || d.duty_end_time || "";
    if (s && e) return `${s}–${e}`;
    if (s) return `from ${s}`;
    return "";
  })();

  if (internal === "day_off" || internal === "home_day" || internal === "rest_day") return "Rest day";
  if (internal === "standby") return win ? `Standby ${win}` : "Standby";
  if (internal === "sim_training") return "Simulator";
  if (internal === "annual_leave") return "Annual leave";
  if (internal === "sickness") return "Off sick";
  if (internal === "needs_review") return "Needs your check";
  if (internal === "night_flight" || internal === "overnight_flight")
    return route ? `Night flight — ${route}` : "Night flight";
  if (internal === "turnaround" || internal === "flight" || internal === "multi_sector_flight")
    return route ? `Flying day — ${route}` : "Flying day";
  if (internal === "flight_to_layover")
    return city ? `Layover — ${city}` : "Layover";
  if (internal === "return_from_layover")
    return city ? `Layover — ${city} → home` : "Return home";
  if (internal === "layover_day")
    return city ? `Layover — ${city}` : "Layover";
  return _prettyDayType(d.day_type) || "Duty";
}

// Iter200-b · Single-glance icon per day type. Simple, one colour,
// consistent size — driven by the day's internal `day_type`. Ionicons
// only (already imported), no external assets.
type IonName = React.ComponentProps<typeof Ionicons>["name"];
function _dayTypeIcon(rawType?: string | null): IonName {
  const dt = (rawType || "").toLowerCase();
  if (dt === "night_flight" || dt === "overnight_flight") return "moon-outline";
  if (dt === "turnaround" || dt === "flight" || dt === "multi_sector_flight")
    return "airplane-outline";
  if (dt === "flight_to_layover" || dt === "return_from_layover" || dt === "layover_day")
    return "bed-outline";
  if (dt === "day_off" || dt === "home_day" || dt === "rest_day")
    return "sunny-outline";
  if (dt === "standby") return "time-outline";
  if (dt === "sim_training") return "school-outline";
  if (dt === "annual_leave") return "briefcase-outline";
  if (dt === "sickness") return "medkit-outline";
  if (dt === "needs_review") return "alert-circle-outline";
  return "ellipsis-horizontal-circle-outline";
}

export default function RosterConfirm() {
  const { id, on_behalf_of } = useLocalSearchParams<{ id: string; on_behalf_of?: string }>();
  // When a coach opens this screen from the workspace, on_behalf_of=clientId.
  // Every API URL below appends `?on_behalf_of=` so backend endpoints scope
  // to the target client instead of the coach's own user_id.
  const qs = on_behalf_of ? `?on_behalf_of=${encodeURIComponent(String(on_behalf_of))}` : "";
  const qsAmp = on_behalf_of ? `&on_behalf_of=${encodeURIComponent(String(on_behalf_of))}` : "";
  const router = useRouter();
  const bottomPad = useBottomSafePad(140);
  const [pending, setPending] = useState<Pending | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [editorDate, setEditorDate] = useState<string | null>(null);
  // Iter 83 — bulk-shift + swap state
  const [shifting, setShifting] = useState(false);
  const [swapFromDate, setSwapFromDate] = useState<string | null>(null);
  const [quickChipBusy, setQuickChipBusy] = useState<string | null>(null);   // date being patched
  const [shiftBannerDismissed, setShiftBannerDismissed] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const p = await api<Pending>(`/roster/pending/${id}${qs}`);
      setPending(p);
    } catch (e: any) {
      Alert.alert("Could not load roster", e?.message || "Please try uploading again.");
      router.replace("/roster-upload");
    } finally {
      setLoading(false);
    }
  }, [id, router]);

  useEffect(() => { load(); }, [load]);

  // Phase 3 — Overlap resolution helper
  const resolveOverlap = useCallback(async (mode: "replace" | "merge" | "keep_both") => {
    if (!pending) return;
    try {
      setSaving(true);
      const r = await api<{ mode: string; merged?: boolean; message?: string }>(
        `/roster/pending/${id}/resolve-overlap`,
        { method: "POST", body: { mode } },
      );
      if (mode === "merge" && r?.merged) {
        Alert.alert(
          "Merged into your existing roster",
          "Your changes have been rolled into the current roster. Louis will re-check the affected days.",
          [{ text: "OK", onPress: () => router.replace("/(client)/calendar") }],
        );
        return;
      }
      // For replace/keep_both, just record the mode and continue to review.
      setPending((p) => p ? { ...p, overlap_mode: mode } : p);
    } catch (e: any) {
      Alert.alert("Couldn't save your choice", e?.message || "Please try again.");
    } finally {
      setSaving(false);
    }
  }, [pending, id, router]);

  const updateDay = (date: string, patch: Partial<Day>) => {
    setPending((p) => {
      if (!p) return p;
      return {
        ...p,
        days: p.days.map((d) => {
          if (d.date !== date) return d;
          const merged: Day = { ...d, ...patch, _confirmed_by_user: true, _needs_review: false } as Day;
          // Iter200-d · When the user changes the day_type via the Edit
          // modal, the incoming key is the chip label (e.g. "Layover",
          // "Flight", "Off"). Translate to the internal type the
          // normalizer would have emitted, and regenerate the customer
          // label so the card updates immediately without waiting for
          // a server round-trip.
          if (patch.day_type !== undefined) {
            const internal = _chipKeyToInternal(patch.day_type as string);
            merged.day_type = internal;
            merged.client_label = _regenerateClientLabel(merged);
          }
          return merged;
        }),
      };
    });
  };

  // ── Iter 83 · Tool 1: Bulk shift ±1 day ───────────────────────────────────
  const doShift = async (direction: "forward" | "back") => {
    if (!pending || shifting) return;
    setShifting(true);
    try {
      const updated = await api<Pending>(`/roster/pending/${pending.id}/shift${qs}`, {
        method: "POST", body: { direction },
      });
      setPending(updated);
      setSwapFromDate(null);
    } catch (e: any) {
      Alert.alert("Shift failed", e?.message || "Please try again.");
    } finally {
      setShifting(false);
    }
  };

  // ── Iter 83 · Tool 2: Two-tap swap ────────────────────────────────────────
  const onCardTap = async (date: string) => {
    if (!pending) return;
    if (swapFromDate) {
      // Second tap → perform the swap
      if (swapFromDate === date) {
        setSwapFromDate(null);   // cancel
        return;
      }
      try {
        const updated = await api<Pending>(`/roster/pending/${pending.id}/swap${qs}`, {
          method: "POST", body: { date_a: swapFromDate, date_b: date },
        });
        setPending(updated);
      } catch (e: any) {
        Alert.alert("Swap failed", e?.message || "Please try again.");
      } finally {
        setSwapFromDate(null);
      }
    } else {
      // Not in swap mode — open the full editor
      setEditorDate(date);
    }
  };

  // ── Iter 83 · Tool 3: Inline quick-chip day-type change ────────────────────
  const setDayTypeQuick = async (date: string, newType: string) => {
    if (!pending || quickChipBusy) return;
    setQuickChipBusy(date);
    // Optimistic local update
    updateDay(date, { day_type: newType });
    try {
      const days = pending.days.map((d) =>
        d.date === date
          ? { ...d, day_type: newType, _confirmed_by_user: true, _needs_review: false }
          : d,
      );
      const updated = await api<Pending>(`/roster/pending/${pending.id}${qs}`, {
        method: "PATCH",
        body: { days: days.map(({ _needs_review, ...d }) => d) },
      });
      setPending(updated);
    } catch (e: any) {
      Alert.alert("Save failed", e?.message || "Please try again.");
      // Reload to reset local optimistic edits
      await load();
    } finally {
      setQuickChipBusy(null);
    }
  };

  const confirmDayAsIs = async (date: string) => {
    if (!pending) return;
    try {
      await api(`/roster/pending/${pending.id}/confirm-day${qs}`, {
        method: "POST",
        body: { date },
      });
      setPending((p) => {
        if (!p) return p;
        return {
          ...p,
          days: p.days.map((d) => (d.date === date ? { ...d, _confirmed_by_user: true, _needs_review: false } : d)),
        };
      });
    } catch (e: any) {
      Alert.alert("Could not confirm", e?.message || "Please try again.");
    }
  };

  const save = async () => {
    if (!pending) return;
    setSaving(true);
    try {
      const updated = await api<Pending>(`/roster/pending/${pending.id}${qs}`, {
        method: "PATCH",
        body: {
          days: pending.days.map(({ _needs_review, ...d }) => d),
        },
      });
      setPending(updated);
    } catch (e: any) {
      Alert.alert("Save failed", e?.message || "Please try again.");
    } finally {
      setSaving(false);
    }
  };

  const submit = async () => {
    if (!pending) return;
    // Save any pending in-memory edits first.
    await save();
    setSubmitting(true);
    try {
      const res = await api<any>(`/roster/pending/${pending.id}/confirm${qs}`, { method: "POST" });
      // If there's another pending roster (e.g. batch upload July + August),
      // jump straight to it instead of going through the generation flow.
      const nextId = pending._queue?.next_id;
      if (nextId) {
        router.replace({ pathname: "/roster/confirm/[id]" as any, params: { id: nextId } } as any);
      } else {
        // Iter188 · Route directly to the dedicated full-screen success
        // page. This bypasses the /roster-upload progress bar entirely
        // so the client sees the "Roster Received" message immediately
        // — matches product requirement 2026-06.
        // `res.job_id` is now unused here, but the backend still creates
        // the confirm_build job for MANUAL_MODE bookkeeping.
        void res;
        router.replace("/roster/received");
      }
    } catch (e: any) {
      // Iter 84 (Task 1.4) — profile_incomplete 409 → route to /training-setup.
      const detail = e?.detail || e?.body?.detail;
      const code = detail?.code || e?.body?.code || e?.code;
      if (code === "profile_incomplete" || e?.status === 409) {
        const labels = (detail?.friendly_labels || [])
          .map((l: string) => `• ${l}`)
          .join("\n");
        Alert.alert(
          "One more step",
          `Louis needs a few more details before he can build your plan:\n\n${labels}\n\nTakes about 30 seconds.`,
          [
            { text: "Later", style: "cancel", onPress: () => setSubmitting(false) },
            {
              text: "Complete Setup",
              onPress: () => { setSubmitting(false); router.push("/training-setup" as any); },
            },
          ],
        );
        return;
      }
      Alert.alert("Could not build your plan", e?.message || "Please try again.");
      setSubmitting(false);
    }
  };

  const discard = () => {
    Alert.alert(
      "Discard this roster?",
      "The parsed roster will be deleted. You can upload again.",
      [
        { text: "Keep reviewing", style: "cancel" },
        {
          text: "Discard",
          style: "destructive",
          onPress: async () => {
            try {
              await api(`/roster/pending/${pending?.id}${qs}`, { method: "DELETE" });
            } catch {}
            router.replace("/roster-upload");
          },
        },
      ],
    );
  };

  const unreviewed = useMemo(() => {
    if (!pending) return 0;
    return pending.days.filter((d) => d._needs_review).length;
  }, [pending]);

  if (loading || !pending) {
    return (
      <SafeAreaView style={styles.root}>
        <View style={styles.centered}>
          <ActivityIndicator color={theme.color.brand} />
          <Text style={styles.subtle}>Loading your roster…</Text>
        </View>
      </SafeAreaView>
    );
  }

  const editorDay = pending.days.find((d) => d.date === editorDate) || null;

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable testID="rc-back" onPress={discard}>
          <Ionicons name="chevron-back" size={26} color={theme.color.text} />
        </Pressable>
        <Text style={styles.headerTitle}>REVIEW ROSTER</Text>
        <Pressable testID="rc-discard" onPress={discard}>
          <Text style={styles.discard}>DISCARD</Text>
        </Pressable>
      </View>

      <View style={styles.summary}>
        {pending._queue && pending._queue.total > 1 ? (
          <View style={styles.queueBar} testID="rc-queue-bar">
            <Ionicons name="layers" size={14} color={theme.color.brand} />
            <Text style={styles.queueT}>
              ROSTER {(pending._queue.index ?? 0) + 1} OF {pending._queue.total}
              {pending._queue.next_filename ? ` · NEXT: ${pending._queue.next_filename}` : ""}
            </Text>
          </View>
        ) : null}

        {/* Phase 3 — Overlap resolution prompt. Shown when the parser
             detected duty dates that already exist in an active roster and
             the client has NOT yet chosen a resolution mode. */}
        {pending.overlap && (pending.overlap.overlapping_dates?.length || 0) > 0 && !pending.overlap_mode ? (
          <View style={styles.overlapBanner} testID="rc-overlap-banner">
            <View style={styles.overlapHeaderRow}>
              <Ionicons name="alert-circle" size={18} color={theme.color.warn || "#e5a337"} />
              <Text style={styles.overlapTitle} numberOfLines={2}>
                You already have a roster for these dates
              </Text>
            </View>
            <Text style={styles.overlapSub}>
              What would you like to do?
            </Text>
            <View style={styles.overlapBtnCol}>
              <Pressable
                testID="rc-overlap-replace"
                onPress={() => resolveOverlap("replace")}
                style={[styles.overlapBtn, styles.overlapBtnPrimary]}
                disabled={saving}
              >
                <Ionicons name="swap-vertical" size={14} color="#fff" />
                <View style={{ flex: 1 }}>
                  <Text style={styles.overlapBtnT}>REPLACE EXISTING ROSTER</Text>
                  <Text style={styles.overlapBtnSub}>Use this new roster instead.</Text>
                </View>
              </Pressable>
              <Pressable
                testID="rc-overlap-merge"
                onPress={() => resolveOverlap("merge")}
                style={styles.overlapBtn}
                disabled={saving}
              >
                <Ionicons name="git-merge" size={14} color={theme.color.text} />
                <View style={{ flex: 1 }}>
                  <Text style={[styles.overlapBtnT, { color: theme.color.text }]}>
                    UPDATE CHANGED DAYS
                  </Text>
                  <Text style={[styles.overlapBtnSub, { color: theme.color.textMuted }]}>
                    Keep your current roster and update changes.
                  </Text>
                </View>
              </Pressable>
              <Pressable
                testID="rc-overlap-keep-both"
                onPress={() => resolveOverlap("keep_both")}
                style={styles.overlapBtn}
                disabled={saving}
              >
                <Ionicons name="albums" size={14} color={theme.color.text} />
                <View style={{ flex: 1 }}>
                  <Text style={[styles.overlapBtnT, { color: theme.color.text }]}>
                    KEEP BOTH FOR COACH REVIEW
                  </Text>
                  <Text style={[styles.overlapBtnSub, { color: theme.color.textMuted }]}>
                    Louis will check which version is correct.
                  </Text>
                </View>
              </Pressable>
            </View>
          </View>
        ) : null}

        {pending.overlap && pending.overlap_mode ? (
          <View style={styles.overlapChosen} testID="rc-overlap-chosen">
            <Ionicons name="checkmark-circle" size={14} color={theme.color.brand} />
            <Text style={styles.overlapChosenT}>
              CHOSEN: {pending.overlap_mode === "replace" ? "REPLACE OLDER ROSTER"
                     : pending.overlap_mode === "merge" ? "MERGE CHANGES"
                     : "KEEP BOTH · LOUIS TO REVIEW"}
            </Text>
            <Pressable
              testID="rc-overlap-change"
              onPress={() => setPending((p) => p ? { ...p, overlap_mode: null } : p)}
              hitSlop={10}
            >
              <Text style={styles.overlapChangeT}>CHANGE</Text>
            </Pressable>
          </View>
        ) : null}

        <View style={styles.summaryRow}>
          <Text style={styles.sumLabel}>DUTIES</Text>
          <Text style={styles.sumVal}>{pending.day_count} days</Text>
        </View>
        <View style={styles.summaryRow}>
          <Text style={styles.sumLabel}>PERIOD</Text>
          <Text style={styles.sumVal}>{fmtDate(pending.start_date)} → {fmtDate(pending.end_date)}</Text>
        </View>
        <View style={styles.summaryRow}>
          <Text style={styles.sumLabel}>NEEDS REVIEW</Text>
          <Text style={[styles.sumVal, unreviewed > 0 && { color: theme.color.warn || "#e5a337" }]}>
            {unreviewed} day{unreviewed === 1 ? "" : "s"}
          </Text>
        </View>
        {unreviewed > 0 && (
          <Text style={styles.summaryHint}>
            Tap the amber days to confirm or edit their duty type before we build your plan. Any other day can also be edited if something looks wrong — tap EDIT on the card.
          </Text>
        )}

        {/* Iter200-c · "THIS ROSTER" traffic-light summary removed per
            spec — the review screen now goes straight from the period
            and duties header into the day-by-day cards. */}
      </View>

      <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: bottomPad }}>
        {/* Iter200-c · "Whole roster off by a day?" bulk-shift banner
            removed per spec — bulk shifting can still be triggered
            programmatically via `doShift()` if needed, but it no
            longer appears on the customer review screen. */}

        {/* Iter 83 · Tool 2: Swap-mode active indicator */}
        {swapFromDate && (
          <View style={styles.swapBanner} testID="rc-swap-active-banner">
            <Ionicons name="swap-horizontal" size={16} color="#fff" />
            <View style={{ flex: 1 }}>
              <Text style={styles.swapBannerT}>SWAP MODE</Text>
              <Text style={styles.swapBannerSub}>
                Now tap the day you want to swap with {fmtDate(swapFromDate)}.
              </Text>
            </View>
            <Pressable testID="rc-swap-cancel" onPress={() => setSwapFromDate(null)} hitSlop={10}>
              <Text style={styles.swapCancelT}>CANCEL</Text>
            </Pressable>
          </View>
        )}

        {pending.days.map((d) => {
          const needs = d._needs_review;
          const isSwapSource = swapFromDate === d.date;
          const isSwapTarget = swapFromDate && swapFromDate !== d.date;
          const cardStyle = [
            styles.card,
            needs ? styles.cardAmber : d._confirmed_by_user ? styles.cardConfirmed : styles.cardDefault,
            isSwapSource && styles.cardSwapSource,
            isSwapTarget && styles.cardSwapTarget,
          ];
          return (
            <Pressable
              key={d.date}
              testID={`rc-day-${d.date}`}
              style={cardStyle}
              onPress={() => onCardTap(d.date)}
            >
              <View style={styles.cardTop}>
                <Text style={styles.cardDate}>{fmtDate(d.date)}</Text>
                {isSwapSource ? (
                  <View style={styles.badgeSwap}>
                    <Ionicons name="swap-horizontal" size={12} color="#fff" />
                    <Text style={styles.badgeText}>SWAPPING</Text>
                  </View>
                ) : needs ? (
                  <View style={styles.badgeAmber}>
                    <Ionicons name="alert-circle" size={12} color="#fff" />
                    <Text style={styles.badgeText}>REVIEW</Text>
                  </View>
                ) : d._confirmed_by_user ? (
                  <View style={styles.badgeConfirmed}>
                    <Ionicons name="checkmark-circle" size={12} color="#fff" />
                    <Text style={styles.badgeText}>CONFIRMED</Text>
                  </View>
                ) : null}
              </View>

              {/* Iter200-b · Icon + label + report time row. Single
                  icon on the left communicates the day type at a
                  glance; label and time sit to the right. */}
              <View style={styles.cardRow}>
                <View style={styles.cardIconWrap}>
                  <Ionicons
                    name={_dayTypeIcon(d.day_type)}
                    size={22}
                    color={theme.color.text}
                  />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.cardType} numberOfLines={1}>
                    {/* Always prefer the normalizer's customer-friendly label. */}
                    {d.client_label || _prettyDayType(d.day_type) || "Unknown"}
                  </Text>
                  {d.report_time ? (
                    <Text style={styles.cardReportTime} numberOfLines={1}>
                      Report {d.report_time}
                      {d.duty_end_time ? `  ·  Off ${d.duty_end_time}` : ""}
                    </Text>
                  ) : d.duty_end_time ? (
                    <Text style={styles.cardReportTime} numberOfLines={1}>
                      Off {d.duty_end_time}
                    </Text>
                  ) : null}
                </View>
                {d.training_colour ? (
                  <View style={[
                    styles.tlDot,
                    d.training_colour === "green" && styles.tlGreen,
                    d.training_colour === "amber" && styles.tlAmber,
                    d.training_colour === "red" && styles.tlRed,
                    d.training_colour === "black" && styles.tlBlack,
                  ]} />
                ) : null}
              </View>

              {/* Iter200 · Equipment pill ONLY shows for confirmed layovers
                  with a resolved city — never for standby, OFF, home, or
                  ambiguous days. */}
              {(() => {
                const eq = d.equipment_assumption || "";
                const dt = (d.day_type || "").toLowerCase();
                const isLayoverType = dt === "flight_to_layover" || dt === "return_from_layover" || dt === "layover_day";
                const hasCity = !!(d.layover_city && d.layover_city !== "None");
                const isHotel = eq === "hotel_or_bodyweight" || eq === "hotel_or_bodyweight_only";
                if (!isHotel || !isLayoverType || !hasCity) return null;
                return (
                  <View style={styles.eqPill}>
                    <Ionicons name="barbell-outline" size={10} color={theme.color.textMuted} />
                    <Text style={styles.eqPillT}>Hotel / bodyweight</Text>
                  </View>
                );
              })()}
              {/* Iter200 · Raw parser notes hidden from customer view.
                  The normalizer strips internal notes on the backend, but
                  we belt-and-brace here too. Only show notes that look
                  customer-friendly (short and no parser jargon). */}
              {d.notes && !_isDebugNote(d.notes) ? (
                <Text style={styles.cardNotes} numberOfLines={2}>{d.notes}</Text>
              ) : null}

              <View style={styles.cardActions}>
                {needs ? (
                  <Pressable
                    testID={`rc-quick-confirm-${d.date}`}
                    onPress={(e) => { e.stopPropagation(); confirmDayAsIs(d.date); }}
                    style={styles.confirmMini}
                  >
                    <Text style={styles.confirmMiniText}>CONFIRM AS-IS</Text>
                  </Pressable>
                ) : null}
                <Pressable
                  testID={`rc-edit-${d.date}`}
                  onPress={(e) => { e.stopPropagation(); setEditorDate(d.date); }}
                  style={[styles.editMini, { flex: 1 }]}
                >
                  <Ionicons name="create-outline" size={13} color={theme.color.text} />
                  <Text style={styles.editMiniText}>EDIT</Text>
                </Pressable>
              </View>
            </Pressable>
          );
        })}
      </ScrollView>

      <View style={styles.sticky}>
        <Pressable testID="rc-save" onPress={save} disabled={saving} style={[styles.ctaSecondary, saving && { opacity: 0.6 }]}>
          {saving ? <ActivityIndicator color={theme.color.brand} /> : <Text style={styles.ctaSecondaryText}>SAVE CHANGES</Text>}
        </Pressable>
        <Pressable
          testID="rc-confirm-build"
          onPress={submit}
          disabled={submitting || unreviewed > 0}
          style={[styles.cta, (submitting || unreviewed > 0) && { opacity: 0.55 }]}
        >
          {submitting ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={styles.ctaText}>
              {unreviewed > 0
                ? `${unreviewed} DAY${unreviewed === 1 ? "" : "S"} TO REVIEW`
                : pending._queue?.next_id
                  ? "CONFIRM & REVIEW NEXT ROSTER"
                  : "CONFIRM & BUILD PLAN"}
            </Text>
          )}
        </Pressable>
      </View>

      <DayEditor
        day={editorDay}
        onClose={() => setEditorDate(null)}
        onChange={(patch) => editorDay && updateDay(editorDay.date, patch)}
        onStartSwap={() => {
          if (editorDay) {
            setSwapFromDate(editorDay.date);
            setEditorDate(null);
          }
        }}
      />
    </SafeAreaView>
  );
}

function DayEditor({ day, onClose, onChange, onStartSwap }: { day: Day | null; onClose: () => void; onChange: (patch: Partial<Day>) => void; onStartSwap: () => void }) {
  return (
    <Modal visible={!!day} animationType="slide" transparent onRequestClose={onClose}>
      <View style={styles.modalScrim}>
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ width: "100%" }}>
          <View style={styles.modalSheet}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>{fmtDate(day?.date)}</Text>
              <Pressable testID="rc-editor-close" onPress={onClose}>
                <Ionicons name="close" size={24} color={theme.color.text} />
              </Pressable>
            </View>
            <ScrollView keyboardShouldPersistTaps="handled" style={{ maxHeight: 520 }}>
              {/* Iter200-d/e · Flight-details summary at the top of the
                  Edit modal so the member always sees exactly what's on
                  the day before choosing/confirming a new duty type.
                  Renders per-leg data from day.flights[]. */}
              {day ? (
                <View style={styles.editorSummary} testID="rc-editor-summary">
                  <View style={styles.editorSummaryRow}>
                    <Ionicons
                      name={_dayTypeIcon(day.day_type)}
                      size={18}
                      color={theme.color.text}
                    />
                    <Text style={styles.editorSummaryT} numberOfLines={2}>
                      {day.client_label || _prettyDayType(day.day_type) || "—"}
                    </Text>
                  </View>

                  {/* Per-leg flight breakdown — route, flight number, times. */}
                  {(day.flights || []).length > 0 ? (
                    <View style={styles.editorLegList}>
                      {(day.flights || []).map((f: any, i: number) => {
                        const num = f.flight_number || f.flight_no || f.number || f.fnum;
                        const dep = f.dep || f.departure_time;
                        const arr = f.arr || f.arrival_time;
                        return (
                          <View key={i} style={styles.editorLegRow}>
                            <Ionicons
                              name="airplane-outline"
                              size={13}
                              color={theme.color.textMuted}
                            />
                            <View style={{ flex: 1 }}>
                              <Text style={styles.editorLegRoute} numberOfLines={1}>
                                {f.from || "?"} → {f.to || "?"}
                                {num ? `   ·   ${num}` : ""}
                              </Text>
                              {(dep || arr) ? (
                                <Text style={styles.editorLegTimes} numberOfLines={1}>
                                  {dep ? `Dep ${dep}` : ""}
                                  {dep && arr ? "   ·   " : ""}
                                  {arr ? `Arr ${arr}` : ""}
                                </Text>
                              ) : null}
                            </View>
                          </View>
                        );
                      })}
                    </View>
                  ) : null}

                  {(day.report_time || day.duty_end_time || day.layover_city) ? (
                    <Text style={styles.editorSummarySub} numberOfLines={2}>
                      {day.report_time ? `Report ${day.report_time}` : ""}
                      {day.report_time && day.duty_end_time ? "  ·  " : ""}
                      {day.duty_end_time ? `Off ${day.duty_end_time}` : ""}
                      {(day.report_time || day.duty_end_time) && day.layover_city ? "  ·  " : ""}
                      {day.layover_city ? `Destination ${day.layover_city}` : ""}
                    </Text>
                  ) : null}
                </View>
              ) : null}

              <Text style={styles.editorLabel}>DUTY TYPE</Text>
              <View style={styles.dutyGrid}>
                {DUTY_TYPES.map((t) => {
                  // Iter200-d/e · Highlight the chip that matches the
                  // day's INTERNAL type (what the normalizer emits),
                  // not the raw chip key. Fixes the case where the
                  // backend now stores `flight_to_layover` but the
                  // chip key is "Layover" — the chip should still
                  // appear selected.
                  const cur = (day?.day_type || "").toLowerCase();
                  const internalForKey = _chipKeyToInternal(t.key).toLowerCase();
                  const active = cur === t.key.toLowerCase() || cur === internalForKey;
                  return (
                    <Pressable
                      key={t.key}
                      testID={`rc-duty-${t.key}`}
                      onPress={() => onChange({ day_type: t.key })}
                      style={[styles.dutyChip, active && styles.dutyChipActive]}
                    >
                      <Ionicons name={t.icon} size={13} color={active ? "#fff" : theme.color.textMuted} />
                      <Text style={[styles.dutyChipText, active && { color: "#fff" }]}>{t.label}</Text>
                    </Pressable>
                  );
                })}
              </View>

              <Text style={styles.editorLabel}>
                {(day?.day_type || "").toLowerCase() === "direct flight"
                  ? "DESTINATION CITY"
                  : "LAYOVER / DESTINATION CITY"}
              </Text>
              <TextInput
                testID="rc-layover-city"
                style={styles.input}
                value={day?.layover_city || ""}
                onChangeText={(v) => onChange({ layover_city: v })}
                placeholder={(day?.day_type || "").toLowerCase() === "direct flight" ? "e.g. Dubai" : "e.g. Bangkok"}
                placeholderTextColor={theme.color.textDim}
              />
              <View style={styles.row2}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.editorLabel}>LAYOVER NIGHTS</Text>
                  <TextInput
                    testID="rc-layover-nights"
                    style={styles.input}
                    value={day?.layover_nights != null ? String(day.layover_nights) : ""}
                    onChangeText={(v) => onChange({ layover_nights: parseInt(v) || 0 })}
                    placeholder="1"
                    placeholderTextColor={theme.color.textDim}
                    keyboardType="number-pad"
                  />
                </View>
                <View style={{ flex: 1 }} />
              </View>

              <View style={styles.row2}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.editorLabel}>REPORT TIME</Text>
                  <TextInput
                    testID="rc-report-time"
                    style={styles.input}
                    value={day?.report_time || ""}
                    onChangeText={(v) => onChange({ report_time: v })}
                    placeholder="e.g. 04:30"
                    placeholderTextColor={theme.color.textDim}
                  />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.editorLabel}>DUTY END</Text>
                  <TextInput
                    testID="rc-duty-end"
                    style={styles.input}
                    value={day?.duty_end_time || ""}
                    onChangeText={(v) => onChange({ duty_end_time: v })}
                    placeholder="e.g. 12:00"
                    placeholderTextColor={theme.color.textDim}
                  />
                </View>
              </View>

              <Text style={styles.editorLabel}>NOTES</Text>
              <TextInput
                testID="rc-notes"
                style={[styles.input, { minHeight: 70 }]}
                value={day?.notes || ""}
                onChangeText={(v) => onChange({ notes: v })}
                placeholder="Anything the coach should know about this day"
                placeholderTextColor={theme.color.textDim}
                multiline
              />

              {/* Iter200 · Swap-with-another-day tool, moved from the
                  default card into the Edit modal. The rare customer who
                  needs it can still swap two days' contents, but it no
                  longer clutters every card. */}
              <Pressable
                testID="rc-editor-swap"
                onPress={onStartSwap}
                style={styles.editorSwapBtn}
              >
                <Ionicons name="swap-horizontal" size={14} color={theme.color.brand} />
                <Text style={styles.editorSwapT}>SWAP WITH ANOTHER DAY</Text>
              </Pressable>
            </ScrollView>

            <Pressable testID="rc-editor-done" onPress={onClose} style={styles.editorDone}>
              <Text style={styles.editorDoneText}>DONE</Text>
            </Pressable>
          </View>
        </KeyboardAvoidingView>
      </View>
    </Modal>
  );
}

const AMBER = "#e5a337";
const CONFIRMED = "#2f9e6c";

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  centered: { flex: 1, alignItems: "center", justifyContent: "center" },
  subtle: { color: theme.color.textMuted, marginTop: 12 },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: theme.space.lg, paddingVertical: theme.space.md,
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  headerTitle: { color: theme.color.text, fontSize: 14, fontWeight: "800", letterSpacing: 2 },
  discard: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700", letterSpacing: 1.5 },
  summary: {
    paddingHorizontal: theme.space.lg, paddingVertical: theme.space.md,
    backgroundColor: theme.color.surface2, borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  summaryRow: { flexDirection: "row", justifyContent: "space-between", marginBottom: 4 },
  sumLabel: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1.5, fontWeight: "700" },
  sumVal: { color: theme.color.text, fontSize: 13, fontWeight: "700" },
  summaryHint: { color: AMBER, fontSize: 12, marginTop: 6, lineHeight: 16 },
  queueBar: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderRadius: 8,
    backgroundColor: theme.color.surface2,
    borderWidth: 1,
    borderColor: theme.color.brand,
    marginBottom: 10,
  },
  queueT: {
    color: theme.color.brand,
    fontSize: 11,
    fontWeight: "900",
    letterSpacing: 1.3,
    flex: 1,
  },
  card: {
    padding: theme.space.md, borderRadius: theme.radius.md,
    borderWidth: 1, marginBottom: theme.space.sm,
    backgroundColor: theme.color.surface2,
  },
  cardDefault: { borderColor: theme.color.border },
  cardAmber: { borderColor: AMBER, borderLeftWidth: 4 },
  cardConfirmed: { borderColor: theme.color.border, borderLeftWidth: 4, borderLeftColor: CONFIRMED },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 4 },
  cardDate: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1.5, fontWeight: "700" },
  cardType: { color: theme.color.text, fontSize: 15, fontWeight: "800", marginTop: 2 },
  cardRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    marginTop: 6,
  },
  cardIconWrap: {
    width: 40, height: 40, borderRadius: 20,
    alignItems: "center", justifyContent: "center",
    backgroundColor: theme.color.bgAlt || "rgba(255,255,255,0.06)",
  },
  cardReportTime: {
    color: theme.color.textMuted,
    fontSize: 12,
    marginTop: 2,
    fontWeight: "500",
  },
  cardSub: { color: theme.color.textMuted, fontSize: 12, marginTop: 2 },
  cardMeta: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },
  cardNotes: { color: theme.color.textMuted, fontSize: 11, marginTop: 4, fontStyle: "italic" },
  cardActions: { flexDirection: "row", gap: 8, marginTop: 10 },
  badgeAmber: { flexDirection: "row", alignItems: "center", backgroundColor: AMBER, paddingHorizontal: 8, paddingVertical: 3, borderRadius: theme.radius.pill, gap: 4 },
  badgeConfirmed: { flexDirection: "row", alignItems: "center", backgroundColor: CONFIRMED, paddingHorizontal: 8, paddingVertical: 3, borderRadius: theme.radius.pill, gap: 4 },
  badgeSwap: { flexDirection: "row", alignItems: "center", backgroundColor: theme.color.brand, paddingHorizontal: 8, paddingVertical: 3, borderRadius: theme.radius.pill, gap: 4 },
  badgeText: { color: "#fff", fontSize: 11, fontWeight: "800", letterSpacing: 1 },
  confirmMini: { flex: 1, backgroundColor: theme.color.brand, paddingVertical: 8, borderRadius: theme.radius.sm, alignItems: "center" },
  confirmMiniText: { color: "#fff", fontSize: 11, fontWeight: "800", letterSpacing: 1 },
  editMini: { flex: 1, backgroundColor: "transparent", borderWidth: 1, borderColor: theme.color.border, paddingVertical: 8, borderRadius: theme.radius.sm, alignItems: "center", justifyContent: "center", flexDirection: "row", gap: 6 },
  editMiniText: { color: theme.color.text, fontSize: 11, fontWeight: "800", letterSpacing: 1 },
  swapMini: {
    flex: 1, backgroundColor: "transparent",
    borderWidth: 1, borderColor: theme.color.brand,
    paddingVertical: 8, borderRadius: theme.radius.sm,
    alignItems: "center", justifyContent: "center",
    flexDirection: "row", gap: 6,
  },
  swapMiniText: { color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 1 },
  // Iter 83 · Tool 1 · Shift banner
  shiftBanner: {
    padding: theme.space.md, borderRadius: theme.radius.md,
    backgroundColor: theme.color.surface2,
    borderLeftWidth: 3, borderLeftColor: theme.color.brand,
    borderWidth: 1, borderColor: theme.color.border,
    marginBottom: theme.space.md,
  },
  shiftHeader: { flexDirection: "row", alignItems: "flex-start", gap: 8, marginBottom: 8 },
  shiftTitle: { color: theme.color.text, fontSize: 13, fontWeight: "800" },
  shiftSub: { color: theme.color.textMuted, fontSize: 11, marginTop: 2, lineHeight: 15 },
  shiftBtnRow: { flexDirection: "row", gap: 8 },
  shiftBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, paddingVertical: 10, paddingHorizontal: 8,
    borderRadius: theme.radius.sm,
    backgroundColor: "transparent",
    borderWidth: 1, borderColor: theme.color.brand,
    minHeight: 40,
  },
  shiftBtnT: { color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 1 },
  // Iter 83 · Tool 2 · Swap-mode banner + card highlight
  swapBanner: {
    flexDirection: "row", alignItems: "center", gap: 10,
    padding: theme.space.md, borderRadius: theme.radius.md,
    backgroundColor: theme.color.brand,
    marginBottom: theme.space.md,
  },
  swapBannerT: { color: "#fff", fontSize: 11, letterSpacing: 1.5, fontWeight: "900" },
  swapBannerSub: { color: "rgba(255,255,255,0.9)", fontSize: 11, marginTop: 2 },
  swapCancelT: { color: "#fff", fontSize: 11, fontWeight: "800", letterSpacing: 1 },
  cardSwapSource: {
    borderColor: theme.color.brand, borderWidth: 2,
    backgroundColor: theme.color.brandTint,
  },
  cardSwapTarget: {
    borderStyle: "dashed", borderColor: theme.color.brand, borderWidth: 1.5,
  },
  // Iter 83 · Tool 3 · Inline quick chips
  quickChipsRow: {
    flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 8,
  },
  quickChip: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 9, paddingVertical: 6,
    borderRadius: theme.radius.pill,
    backgroundColor: theme.color.surface,
    borderWidth: 1, borderColor: theme.color.border,
    minHeight: 28,
  },
  quickChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  quickChipT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700" },
  sticky: {
    position: "absolute", bottom: 0, left: 0, right: 0,
    padding: theme.space.lg, backgroundColor: theme.color.surface,
    borderTopWidth: 1, borderTopColor: theme.color.border,
    flexDirection: "row", gap: 8,
  },
  cta: { flex: 2, backgroundColor: theme.color.brand, paddingVertical: 16, borderRadius: theme.radius.md, alignItems: "center" },
  ctaText: { color: "#fff", fontWeight: "800", letterSpacing: 1.5, fontSize: 13 },
  ctaSecondary: { flex: 1, backgroundColor: "transparent", borderWidth: 1, borderColor: theme.color.border, paddingVertical: 16, borderRadius: theme.radius.md, alignItems: "center" },
  ctaSecondaryText: { color: theme.color.text, fontWeight: "800", letterSpacing: 1.5, fontSize: 12 },
  modalScrim: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  modalSheet: { backgroundColor: theme.color.surface, borderTopLeftRadius: 18, borderTopRightRadius: 18, padding: theme.space.lg, paddingBottom: theme.space.xl },
  modalHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: theme.space.md },
  modalTitle: { color: theme.color.text, fontSize: 18, fontWeight: "900" },
  editorLabel: { color: theme.color.brand, fontSize: 11, letterSpacing: 1.5, fontWeight: "800", marginTop: theme.space.md, marginBottom: 6 },
  dutyGrid: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  dutyChip: { flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: 12, paddingVertical: 8, borderRadius: theme.radius.pill, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  dutyChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  dutyChipText: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700" },
  input: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, color: theme.color.onRed, paddingHorizontal: theme.space.md, paddingVertical: 12, borderWidth: 1, borderColor: theme.color.border, fontSize: 14 },
  row2: { flexDirection: "row", gap: theme.space.md },
  editorDone: { marginTop: theme.space.md, backgroundColor: theme.color.brand, paddingVertical: 14, borderRadius: theme.radius.md, alignItems: "center" },
  editorDoneText: { color: "#fff", fontWeight: "800", letterSpacing: 1.5, fontSize: 13 },
  editorSummary: {
    padding: theme.space.md,
    borderRadius: theme.radius.md,
    backgroundColor: theme.color.surface2,
    borderWidth: 1,
    borderColor: theme.color.border,
    marginBottom: theme.space.md,
  },
  editorSummaryRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    marginBottom: 6,
  },
  editorSummaryT: {
    color: theme.color.text,
    fontSize: 14,
    fontWeight: "700",
    flex: 1,
  },
  editorSummarySub: {
    color: theme.color.textMuted,
    fontSize: 12,
    marginTop: 2,
  },
  editorLegList: {
    marginTop: 6,
    gap: 6,
  },
  editorLegRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  editorLegRoute: {
    color: theme.color.text,
    fontSize: 13,
    fontWeight: "600",
  },
  editorLegTimes: {
    color: theme.color.textMuted,
    fontSize: 11,
    marginTop: 1,
  },
  editorSwapBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    marginTop: theme.space.md, paddingVertical: 12, borderRadius: theme.radius.md,
    borderWidth: 1, borderColor: theme.color.brand, backgroundColor: "transparent",
  },
  editorSwapT: {
    color: theme.color.brand, fontWeight: "800", letterSpacing: 1.5, fontSize: 12,
  },
  // Parser client label + traffic light chip
  labelRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: 4,
  },
  tlDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: theme.color.textMuted,
  },
  tlGreen: { backgroundColor: "#3DBE6E" },
  tlAmber: { backgroundColor: "#E5A048" },
  tlRed:   { backgroundColor: "#E15A5A" },
  tlBlack: { backgroundColor: "#5A5A5A" },
  clientLabelT: {
    color: theme.color.text,
    fontSize: 12,
    fontWeight: "700",
    flexShrink: 1,
  },
  eqPill: {
    alignSelf: "flex-start",
    marginTop: 6,
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: theme.radius.pill,
    backgroundColor: theme.color.surface,
    borderWidth: 1,
    borderColor: theme.color.border,
  },
  eqPillT: {
    color: theme.color.textMuted,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.5,
  },
  // Phase 3 — Overlap banner
  overlapBanner: {
    padding: theme.space.md,
    borderRadius: theme.radius.md,
    backgroundColor: theme.color.surface2,
    borderLeftWidth: 4,
    borderLeftColor: AMBER,
    borderWidth: 1,
    borderColor: theme.color.border,
    marginBottom: theme.space.md,
  },
  overlapHeaderRow: {
    flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 6,
  },
  overlapTitle: {
    flex: 1, color: theme.color.text, fontSize: 14, fontWeight: "800", lineHeight: 18,
  },
  overlapSub: {
    color: theme.color.textMuted, fontSize: 12, marginBottom: 10, lineHeight: 16,
  },
  overlapBtnCol: { gap: 8 },
  overlapBtn: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 12, paddingVertical: 10,
    borderRadius: theme.radius.sm,
    backgroundColor: "transparent",
    borderWidth: 1, borderColor: theme.color.border,
  },
  overlapBtnPrimary: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  overlapBtnT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 1 },
  overlapBtnSub: { color: "rgba(255,255,255,0.85)", fontSize: 11, marginTop: 2, lineHeight: 13 },
  overlapChosen: {
    flexDirection: "row", alignItems: "center", gap: 6,
    padding: 10,
    borderRadius: theme.radius.sm,
    backgroundColor: theme.color.brandTint,
    borderWidth: 1, borderColor: theme.color.brand,
    marginBottom: theme.space.md,
  },
  overlapChosenT: { flex: 1, color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.2 },
  overlapChangeT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.2 },
  // Traffic-light overview strip
  tlOverview: {
    marginTop: 10,
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: theme.color.border,
  },
  tlOverviewLabel: {
    color: theme.color.textMuted,
    fontSize: 11,
    letterSpacing: 1.5,
    fontWeight: "700",
    marginBottom: 6,
  },
  tlOverviewRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
  },
  tlOverviewChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: theme.radius.pill,
    backgroundColor: theme.color.surface,
    borderWidth: 1,
    borderColor: theme.color.border,
  },
  tlOverviewT: {
    color: theme.color.text,
    fontSize: 11,
    fontWeight: "700",
  },
});
