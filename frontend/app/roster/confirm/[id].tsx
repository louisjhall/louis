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

// Duty types the client can pick from. Keys are what get persisted on
// day.day_type; labels are what the user sees.
const DUTY_TYPES: { key: string; label: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { key: "Flight",        label: "Flight (turnaround)", icon: "airplane" },
  { key: "Layover",       label: "Layover",             icon: "bed" },
  { key: "Standby",       label: "Standby",             icon: "time" },
  { key: "Off",           label: "Off duty",            icon: "sunny" },
  { key: "Home",          label: "Home",                icon: "home" },
  { key: "Sim / Training", label: "Sim / Training",     icon: "school" },
  { key: "Sick",          label: "Sick",                icon: "medkit" },
  { key: "Annual Leave",  label: "Annual leave",        icon: "leaf" },
  { key: "Unknown/Needs Confirmation", label: "Not sure yet", icon: "help-circle" },
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
};

type Pending = {
  id: string;
  start_date?: string;
  end_date?: string;
  day_count: number;
  confidence_avg: number;
  days: Day[];
  review_flags?: { low_confidence_count: number };
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

export default function RosterConfirm() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [pending, setPending] = useState<Pending | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [editorDate, setEditorDate] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const p = await api<Pending>(`/roster/pending/${id}`);
      setPending(p);
    } catch (e: any) {
      Alert.alert("Could not load roster", e?.message || "Please try uploading again.");
      router.replace("/roster-upload");
    } finally {
      setLoading(false);
    }
  }, [id, router]);

  useEffect(() => { load(); }, [load]);

  const updateDay = (date: string, patch: Partial<Day>) => {
    setPending((p) => {
      if (!p) return p;
      return {
        ...p,
        days: p.days.map((d) =>
          d.date === date
            ? { ...d, ...patch, _confirmed_by_user: true, _needs_review: false }
            : d,
        ),
      };
    });
  };

  const confirmDayAsIs = async (date: string) => {
    if (!pending) return;
    try {
      await api(`/roster/pending/${pending.id}/confirm-day`, {
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
      const updated = await api<Pending>(`/roster/pending/${pending.id}`, {
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
      const res = await api<any>(`/roster/pending/${pending.id}/confirm`, { method: "POST" });
      router.replace({ pathname: "/roster-upload" as any, params: { resume: res.job_id } } as any);
    } catch (e: any) {
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
              await api(`/roster/pending/${pending?.id}`, { method: "DELETE" });
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
            Tap the amber days to confirm or edit their duty type before we build your plan.
          </Text>
        )}
      </View>

      <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 140 }}>
        {pending.days.map((d) => {
          const needs = d._needs_review;
          const cardStyle = [
            styles.card,
            needs ? styles.cardAmber : d._confirmed_by_user ? styles.cardConfirmed : styles.cardDefault,
          ];
          return (
            <Pressable
              key={d.date}
              testID={`rc-day-${d.date}`}
              style={cardStyle}
              onPress={() => setEditorDate(d.date)}
            >
              <View style={styles.cardTop}>
                <Text style={styles.cardDate}>{fmtDate(d.date)}</Text>
                {needs ? (
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
              <Text style={styles.cardType} numberOfLines={1}>{d.day_type || "Unknown"}</Text>
              {d.layover_city ? (
                <Text style={styles.cardSub} numberOfLines={1}>
                  {d.layover_city}
                  {typeof d.layover_nights === "number" && d.layover_nights > 0 ? ` · ${d.layover_nights}n` : ""}
                </Text>
              ) : null}
              {(d.report_time || d.duty_end_time) ? (
                <Text style={styles.cardMeta} numberOfLines={1}>
                  {d.report_time ? `Report ${d.report_time}` : ""}
                  {d.report_time && d.duty_end_time ? " · " : ""}
                  {d.duty_end_time ? `Off ${d.duty_end_time}` : ""}
                </Text>
              ) : null}
              {d.notes ? <Text style={styles.cardNotes} numberOfLines={2}>{d.notes}</Text> : null}
              {needs && (
                <View style={styles.cardActions}>
                  <Pressable
                    testID={`rc-quick-confirm-${d.date}`}
                    onPress={(e) => { e.stopPropagation(); confirmDayAsIs(d.date); }}
                    style={styles.confirmMini}
                  >
                    <Text style={styles.confirmMiniText}>CONFIRM AS-IS</Text>
                  </Pressable>
                  <Pressable
                    testID={`rc-edit-${d.date}`}
                    onPress={() => setEditorDate(d.date)}
                    style={styles.editMini}
                  >
                    <Text style={styles.editMiniText}>EDIT</Text>
                  </Pressable>
                </View>
              )}
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
              {unreviewed > 0 ? `${unreviewed} DAY${unreviewed === 1 ? "" : "S"} TO REVIEW` : "CONFIRM & BUILD PLAN"}
            </Text>
          )}
        </Pressable>
      </View>

      <DayEditor
        day={editorDay}
        onClose={() => setEditorDate(null)}
        onChange={(patch) => editorDay && updateDay(editorDay.date, patch)}
      />
    </SafeAreaView>
  );
}

function DayEditor({ day, onClose, onChange }: { day: Day | null; onClose: () => void; onChange: (patch: Partial<Day>) => void }) {
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
              <Text style={styles.editorLabel}>DUTY TYPE</Text>
              <View style={styles.dutyGrid}>
                {DUTY_TYPES.map((t) => {
                  const active = (day?.day_type || "").toLowerCase() === t.key.toLowerCase();
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

              <Text style={styles.editorLabel}>LAYOVER CITY</Text>
              <TextInput
                testID="rc-layover-city"
                style={styles.input}
                value={day?.layover_city || ""}
                onChangeText={(v) => onChange({ layover_city: v })}
                placeholder="e.g. Bangkok"
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
  sumLabel: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 1.5, fontWeight: "700" },
  sumVal: { color: theme.color.text, fontSize: 13, fontWeight: "700" },
  summaryHint: { color: AMBER, fontSize: 12, marginTop: 6, lineHeight: 16 },
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
  cardSub: { color: theme.color.textMuted, fontSize: 12, marginTop: 2 },
  cardMeta: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },
  cardNotes: { color: theme.color.textMuted, fontSize: 11, marginTop: 4, fontStyle: "italic" },
  cardActions: { flexDirection: "row", gap: 8, marginTop: 10 },
  badgeAmber: { flexDirection: "row", alignItems: "center", backgroundColor: AMBER, paddingHorizontal: 8, paddingVertical: 3, borderRadius: theme.radius.pill, gap: 4 },
  badgeConfirmed: { flexDirection: "row", alignItems: "center", backgroundColor: CONFIRMED, paddingHorizontal: 8, paddingVertical: 3, borderRadius: theme.radius.pill, gap: 4 },
  badgeText: { color: "#fff", fontSize: 9, fontWeight: "800", letterSpacing: 1 },
  confirmMini: { flex: 1, backgroundColor: theme.color.brand, paddingVertical: 8, borderRadius: theme.radius.sm, alignItems: "center" },
  confirmMiniText: { color: "#fff", fontSize: 11, fontWeight: "800", letterSpacing: 1 },
  editMini: { flex: 1, backgroundColor: "transparent", borderWidth: 1, borderColor: theme.color.border, paddingVertical: 8, borderRadius: theme.radius.sm, alignItems: "center" },
  editMiniText: { color: theme.color.text, fontSize: 11, fontWeight: "800", letterSpacing: 1 },
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
  editorLabel: { color: theme.color.brand, fontSize: 10, letterSpacing: 1.5, fontWeight: "800", marginTop: theme.space.md, marginBottom: 6 },
  dutyGrid: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  dutyChip: { flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: 12, paddingVertical: 8, borderRadius: theme.radius.pill, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  dutyChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  dutyChipText: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700" },
  input: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, color: theme.color.text, paddingHorizontal: theme.space.md, paddingVertical: 12, borderWidth: 1, borderColor: theme.color.border, fontSize: 14 },
  row2: { flexDirection: "row", gap: theme.space.md },
  editorDone: { marginTop: theme.space.md, backgroundColor: theme.color.brand, paddingVertical: 14, borderRadius: theme.radius.md, alignItems: "center" },
  editorDoneText: { color: "#fff", fontWeight: "800", letterSpacing: 1.5, fontSize: 13 },
});
