/**
 * CoachNotesTab — Phase 6 Tier 1.
 *
 * Rendered inside the coach client screen. Lets Louis type structured
 * per-client overrides that are injected into every future workout
 * generation.
 *
 * Slots:
 *  - preferences   (loves/hates/equipment access)
 *  - cautions      (injuries, restrictions — LLM must never violate)
 *  - goal_override (actual goal, overrides profile.goal_type)
 *  - weekly_shape  (desired day-by-day pattern)
 *  - notes         (free-form catch-all)
 *
 * Small edits take effect on the client's NEXT workout generation
 * automatically. Coach can trigger an immediate regen via the existing
 * programme actions.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, TextInput, Pressable, ActivityIndicator, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";


type Notes = {
  preferences: string;
  cautions: string;
  goal_override: string;
  weekly_shape: string;
  notes: string;
  updated_at?: string | null;
  updated_by_name?: string | null;
};

type SlotSpec = {
  key: keyof Notes;
  label: string;
  helper: string;
  placeholder: string;
  icon: any;
  tint: string;
  multiline?: boolean;
  minHeight?: number;
  softCap?: number;
};

const SLOTS: SlotSpec[] = [
  {
    key: "preferences",
    label: "PREFERENCES",
    helper: "What they love, hate, or have access to. Louis will bias exercise selection to match.",
    placeholder: "e.g. Loves kettlebells and hotel gyms. Dislikes burpees. Hates barbells first thing in the morning.",
    icon: "heart-outline",
    tint: "#3DBE6E",
    multiline: true, minHeight: 90, softCap: 700,
  },
  {
    key: "cautions",
    label: "CAUTIONS & INJURIES",
    helper: "Anything the plan MUST NOT violate. Louis will never program movements that break these rules.",
    placeholder: "e.g. Left shoulder — no overhead press until September. Lower back tightness — avoid heavy deadlifts.",
    icon: "shield-checkmark-outline",
    tint: "#E15A5A",
    multiline: true, minHeight: 90, softCap: 700,
  },
  {
    key: "goal_override",
    label: "GOAL OVERRIDE",
    helper: "The client's ACTUAL goal — takes priority over whatever was set during onboarding.",
    placeholder: "e.g. Marathon in November — 42km. Currently building base + long runs.",
    icon: "flag-outline",
    tint: "#E5A048",
    multiline: true, minHeight: 70, softCap: 700,
  },
  {
    key: "weekly_shape",
    label: "PREFERRED WEEKLY SHAPE",
    helper: "How Louis should shape the week when the roster allows it.",
    placeholder: "e.g. Strength Mon/Wed/Fri, easy run Tue, long run Sat, mobility Sun.",
    icon: "calendar-outline",
    tint: "#7d5cb3",
    multiline: true, minHeight: 70, softCap: 700,
  },
  {
    key: "notes",
    label: "FREE NOTES",
    helper: "Everything else. Context, quirks, upcoming events, family constraints.",
    placeholder: "e.g. Prefers 45-min sessions. Travels most Fridays. Wife had a baby — evenings hard until October.",
    icon: "document-text-outline",
    tint: "#4a6b7d",
    multiline: true, minHeight: 110, softCap: 1500,
  },
];


export function CoachNotesTab({ clientId }: { clientId: string }) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notes, setNotes] = useState<Notes>({
    preferences: "", cautions: "", goal_override: "", weekly_shape: "", notes: "",
  });
  const [initial, setInitial] = useState<Notes | null>(null);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const r = await api<{ notes: Notes }>(`/coach/clients/${clientId}/coach-notes`);
      const n: Notes = {
        preferences: r.notes.preferences || "",
        cautions: r.notes.cautions || "",
        goal_override: r.notes.goal_override || "",
        weekly_shape: r.notes.weekly_shape || "",
        notes: r.notes.notes || "",
        updated_at: r.notes.updated_at || null,
        updated_by_name: r.notes.updated_by_name || null,
      };
      setNotes(n);
      setInitial(n);
    } catch (e: any) {
      Alert.alert("Couldn't load notes", e?.message || "Please try again.");
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  const dirty = !!initial && (
    initial.preferences !== notes.preferences
    || initial.cautions !== notes.cautions
    || initial.goal_override !== notes.goal_override
    || initial.weekly_shape !== notes.weekly_shape
    || initial.notes !== notes.notes
  );

  const save = async () => {
    try {
      setSaving(true);
      const r = await api<{ notes: Notes }>(
        `/coach/clients/${clientId}/coach-notes`,
        { method: "PUT", body: {
          preferences: notes.preferences,
          cautions: notes.cautions,
          goal_override: notes.goal_override,
          weekly_shape: notes.weekly_shape,
          notes: notes.notes,
        } },
      );
      const n: Notes = {
        preferences: r.notes.preferences || "",
        cautions: r.notes.cautions || "",
        goal_override: r.notes.goal_override || "",
        weekly_shape: r.notes.weekly_shape || "",
        notes: r.notes.notes || "",
        updated_at: r.notes.updated_at || null,
        updated_by_name: r.notes.updated_by_name || null,
      };
      setNotes(n);
      setInitial(n);
      Alert.alert(
        "Notes saved",
        "These will be applied on the next workout generation.\n\nTo apply immediately, use REGENERATE FROM SCRATCH on the workout kebab menu, or the Regenerate Programme action.",
      );
    } catch (e: any) {
      Alert.alert("Couldn't save", e?.message || "Please try again.");
    } finally {
      setSaving(false);
    }
  };

  const clearSlot = (key: keyof Notes) => setNotes((n) => ({ ...n, [key]: "" }));

  if (loading) {
    return (
      <View style={styles.loadingWrap}>
        <ActivityIndicator color={theme.color.brand} />
      </View>
    );
  }

  return (
    <View testID="coach-notes-tab" style={styles.wrap}>
      <View style={styles.header}>
        <Text style={styles.h1}>COACH NOTES</Text>
        <Text style={styles.sub}>
          Structured overrides Louis types for THIS client. Takes precedence over
          the coaching DNA. Applied on every future workout generation.
        </Text>
        {notes.updated_at ? (
          <Text style={styles.updatedT}>
            Last saved {new Date(notes.updated_at).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
            {notes.updated_by_name ? ` by ${notes.updated_by_name}` : ""}
          </Text>
        ) : (
          <Text style={styles.updatedT}>Not saved yet.</Text>
        )}
      </View>

      {SLOTS.map((s) => (
        <View key={s.key} style={styles.card} testID={`cn-slot-${s.key}`}>
          <View style={styles.cardHead}>
            <View style={[styles.cardIcon, { backgroundColor: s.tint + "22" }]}>
              <Ionicons name={s.icon} size={14} color={s.tint} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.cardLabel}>{s.label}</Text>
              <Text style={styles.cardHelper}>{s.helper}</Text>
            </View>
            {(notes[s.key] as string).length > 0 ? (
              <Pressable testID={`cn-clear-${s.key}`} onPress={() => clearSlot(s.key)} hitSlop={10}>
                <Ionicons name="close-circle" size={16} color={theme.color.textMuted} />
              </Pressable>
            ) : null}
          </View>
          <TextInput
            testID={`cn-input-${s.key}`}
            multiline
            placeholder={s.placeholder}
            placeholderTextColor={theme.color.textDim}
            value={notes[s.key] as string}
            onChangeText={(v) => setNotes((n) => ({ ...n, [s.key]: v }))}
            maxLength={s.softCap || 700}
            style={[styles.input, { minHeight: s.minHeight || 80 }]}
          />
          <Text style={styles.counter}>
            {(notes[s.key] as string).length} / {s.softCap || 700}
          </Text>
        </View>
      ))}

      <View style={styles.saveRow}>
        <Pressable
          testID="cn-save"
          onPress={save}
          disabled={!dirty || saving}
          style={[styles.saveBtn, (!dirty || saving) && { opacity: 0.5 }]}
        >
          {saving ? (
            <ActivityIndicator size="small" color="#fff" />
          ) : (
            <>
              <Ionicons name="save" size={16} color="#fff" />
              <Text style={styles.saveT}>
                {dirty ? "SAVE COACH NOTES" : "NO UNSAVED CHANGES"}
              </Text>
            </>
          )}
        </Pressable>
      </View>

      <View style={styles.tipCard}>
        <Ionicons name="information-circle-outline" size={14} color={theme.color.textMuted} />
        <Text style={styles.tipT}>
          Small changes take effect on the next auto-regeneration. For big
          changes (goal shift, weekly shape rewrite), open the Programme tab
          and hit Regenerate to see the impact today.
        </Text>
      </View>
    </View>
  );
}


const styles = StyleSheet.create({
  wrap: { paddingVertical: 8 },
  loadingWrap: { padding: 40, alignItems: "center" },
  header: {
    marginBottom: theme.space.md,
  },
  h1: { color: theme.color.text, fontSize: 12, fontWeight: "900", letterSpacing: 2 },
  sub: { color: theme.color.textMuted, fontSize: 12, marginTop: 6, lineHeight: 16 },
  updatedT: { color: theme.color.textDim, fontSize: 10, marginTop: 8, letterSpacing: 0.5, fontStyle: "italic" },
  card: {
    padding: theme.space.md,
    borderRadius: theme.radius.md,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
    marginBottom: theme.space.sm,
  },
  cardHead: {
    flexDirection: "row", alignItems: "flex-start", gap: 10, marginBottom: 8,
  },
  cardIcon: {
    width: 28, height: 28, borderRadius: 14,
    alignItems: "center", justifyContent: "center",
  },
  cardLabel: { color: theme.color.text, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  cardHelper: { color: theme.color.textMuted, fontSize: 11, marginTop: 3, lineHeight: 14 },
  input: {
    color: theme.color.text,
    backgroundColor: theme.color.surface,
    borderWidth: 1, borderColor: theme.color.border,
    borderRadius: theme.radius.sm,
    padding: 10,
    fontSize: 13,
    lineHeight: 18,
    textAlignVertical: "top",
  },
  counter: {
    color: theme.color.textDim, fontSize: 10, marginTop: 4, textAlign: "right",
  },
  saveRow: { marginTop: 8 },
  saveBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: theme.color.brand,
    paddingVertical: 14, borderRadius: theme.radius.md,
  },
  saveT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 1.5 },
  tipCard: {
    flexDirection: "row", gap: 8, alignItems: "flex-start",
    padding: 10,
    marginTop: theme.space.md,
    borderRadius: theme.radius.sm,
    backgroundColor: theme.color.surface,
    borderWidth: 1, borderColor: theme.color.border,
    borderLeftWidth: 3, borderLeftColor: theme.color.brand,
  },
  tipT: { flex: 1, color: theme.color.textMuted, fontSize: 11, lineHeight: 14 },
});
