/**
 * DirectiveEditor — structured coach-directive composer.
 *
 * A modal for the Coach Dashboard V2 workspace. Coach picks a kind,
 * scope and parameters instead of typing free text. The result is a
 * `coach_directives` row that Training Intelligence V2 will honour.
 *
 * §33-35 of the build brief.
 */
import React, { useState, useCallback } from "react";
import {
  View, Text, TextInput, Pressable, StyleSheet, Modal, ScrollView, ActivityIndicator, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Kind =
  | "avoid_movement" | "require_movement" | "limit_frequency"
  | "limit_volume"   | "limit_intensity"  | "note_only";

const KIND_ROWS: { id: Kind; label: string; hint: string; icon: any }[] = [
  { id: "avoid_movement",   label: "Avoid movement",    hint: "e.g. no running, avoid deep squats", icon: "hand-left-outline" },
  { id: "require_movement", label: "Require movement",  hint: "e.g. must include hinge patterns",   icon: "checkmark-circle-outline" },
  { id: "limit_frequency",  label: "Limit frequency",   hint: "e.g. max 2 runs per week",           icon: "repeat-outline" },
  { id: "limit_volume",     label: "Limit volume",      hint: "e.g. reduce weekly volume 20%",      icon: "trending-down-outline" },
  { id: "limit_intensity",  label: "Limit intensity",   hint: "e.g. keep RPE ≤ 7",                  icon: "speedometer-outline" },
  { id: "note_only",        label: "Note only",         hint: "for your reference — engine ignores",icon: "chatbubble-ellipses-outline" },
];

const SCOPE_OPTIONS: { id: string; label: string }[] = [
  { id: "today",         label: "Today" },
  { id: "this_week",     label: "This week" },
  { id: "this_trip",     label: "This trip" },
  { id: "phase",         label: "Current phase" },
  { id: "custom",        label: "Custom range" },
  { id: "until_changed", label: "Until changed" },
];

export function DirectiveEditor({
  clientId, visible, onClose, onSaved,
}: {
  clientId: string;
  visible: boolean;
  onClose: () => void;
  onSaved?: () => void;
}) {
  const [kind, setKind] = useState<Kind>("avoid_movement");
  const [scopeKind, setScopeKind] = useState("until_changed");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [pattern, setPattern] = useState("");
  const [amount, setAmount] = useState("");
  const [freeText, setFreeText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = useCallback(() => {
    setKind("avoid_movement"); setScopeKind("until_changed");
    setFromDate(""); setToDate(""); setPattern(""); setAmount(""); setFreeText("");
    setError(null);
  }, []);

  const submit = useCallback(async () => {
    setBusy(true); setError(null);
    try {
      const parameters: any = {};
      if (kind === "avoid_movement" || kind === "require_movement") {
        if (pattern) parameters.pattern = pattern;
      }
      if (kind === "limit_frequency" || kind === "limit_volume" || kind === "limit_intensity") {
        if (amount) parameters.amount = amount;
      }
      await api(`/v2/coach/clients/${clientId}/dashboard-directives`, {
        method: "POST",
        body: {
          kind,
          scope: {
            scope_kind: scopeKind,
            ...(scopeKind === "custom" ? { from_date: fromDate || null, to_date: toDate || null } : {}),
          },
          parameters,
          free_text: freeText.trim(),
        },
      });
      reset();
      onClose();
      onSaved?.();
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally { setBusy(false); }
  }, [clientId, kind, scopeKind, fromDate, toDate, pattern, amount, freeText, onClose, onSaved, reset]);

  return (
    <Modal transparent visible={visible} animationType="fade" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.card}>
          <View style={styles.head}>
            <Text style={styles.title}>Add directive</Text>
            <Pressable onPress={onClose} testID="directive-close">
              <Ionicons name="close" size={22} color={theme.color.textHi} />
            </Pressable>
          </View>
          <ScrollView contentContainerStyle={{ padding: 16 }}>
            <Text style={styles.section}>KIND</Text>
            {KIND_ROWS.map((k) => (
              <Pressable
                key={k.id}
                onPress={() => setKind(k.id)}
                style={[styles.kindRow, kind === k.id && styles.kindRowActive]}
                testID={`kind-${k.id}`}
              >
                <Ionicons name={k.icon} size={18} color={kind === k.id ? theme.color.brand : theme.color.textDim} />
                <View style={{ flex: 1, marginLeft: 8 }}>
                  <Text style={[styles.kindLabel, kind === k.id && { color: theme.color.textHi }]}>{k.label}</Text>
                  <Text style={styles.kindHint}>{k.hint}</Text>
                </View>
                {kind === k.id && <Ionicons name="checkmark" size={16} color={theme.color.brand} />}
              </Pressable>
            ))}

            {/* Kind-specific parameters */}
            {(kind === "avoid_movement" || kind === "require_movement") && (
              <>
                <Text style={styles.section}>PATTERN (optional)</Text>
                <TextInput
                  style={styles.input}
                  placeholder="e.g. gait_run_tempo · deep_squat · overhead_press"
                  placeholderTextColor={theme.color.textDim}
                  value={pattern}
                  onChangeText={setPattern}
                  testID="directive-pattern"
                />
              </>
            )}
            {(kind === "limit_frequency" || kind === "limit_volume" || kind === "limit_intensity") && (
              <>
                <Text style={styles.section}>AMOUNT (optional)</Text>
                <TextInput
                  style={styles.input}
                  placeholder={
                    kind === "limit_frequency" ? "e.g. max 2 per week" :
                    kind === "limit_volume"    ? "e.g. -20%" :
                                                  "e.g. max RPE 7"
                  }
                  placeholderTextColor={theme.color.textDim}
                  value={amount}
                  onChangeText={setAmount}
                  testID="directive-amount"
                />
              </>
            )}

            <Text style={styles.section}>SCOPE</Text>
            <View style={styles.scopeRow}>
              {SCOPE_OPTIONS.map((s) => (
                <Pressable
                  key={s.id}
                  onPress={() => setScopeKind(s.id)}
                  style={[styles.scopeChip, scopeKind === s.id && styles.scopeChipActive]}
                  testID={`scope-${s.id}`}
                >
                  <Text style={[styles.scopeChipText, scopeKind === s.id && { color: "#000" }]}>{s.label}</Text>
                </Pressable>
              ))}
            </View>
            {scopeKind === "custom" && (
              <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
                <TextInput
                  style={[styles.input, { flex: 1 }]}
                  placeholder="From (YYYY-MM-DD)"
                  placeholderTextColor={theme.color.textDim}
                  value={fromDate} onChangeText={setFromDate} testID="directive-from"
                />
                <TextInput
                  style={[styles.input, { flex: 1 }]}
                  placeholder="To (YYYY-MM-DD)"
                  placeholderTextColor={theme.color.textDim}
                  value={toDate} onChangeText={setToDate} testID="directive-to"
                />
              </View>
            )}

            <Text style={styles.section}>REASON / NOTES</Text>
            <TextInput
              style={[styles.input, { minHeight: 60 }]}
              placeholder="e.g. Knee soreness — allow rest until Sunday"
              placeholderTextColor={theme.color.textDim}
              value={freeText}
              onChangeText={setFreeText}
              multiline
              testID="directive-free-text"
            />

            {error && <Text style={styles.errorText}>{error}</Text>}

            <View style={styles.actions}>
              <Pressable style={styles.primaryBtn} onPress={submit} disabled={busy} testID="directive-save">
                {busy ? <ActivityIndicator color="#000" /> : <Text style={styles.primaryBtnText}>Save directive</Text>}
              </Pressable>
              <Pressable style={styles.cancelBtn} onPress={onClose} disabled={busy}>
                <Text style={styles.cancelBtnText}>Cancel</Text>
              </Pressable>
            </View>
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1, backgroundColor: "rgba(0,0,0,0.55)", alignItems: "center", justifyContent: "center",
    padding: Platform.OS === "web" ? 20 : 12,
  },
  card: {
    width: Platform.OS === "web" ? 560 : "94%",
    maxHeight: "94%",
    backgroundColor: theme.color.bg,
    borderRadius: 12,
    borderWidth: 1, borderColor: theme.color.border,
    overflow: "hidden",
  },
  head: {
    flexDirection: "row", alignItems: "center", padding: 14,
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  title: { flex: 1, color: theme.color.textHi, fontSize: 17, fontWeight: "800" },
  section: {
    color: theme.color.textDim, fontSize: 11, letterSpacing: 1.5, fontWeight: "800",
    marginTop: 14, marginBottom: 6,
  },
  kindRow: {
    flexDirection: "row", alignItems: "center", padding: 10, borderRadius: 6,
    borderWidth: 1, borderColor: theme.color.border, marginBottom: 6,
  },
  kindRowActive: { borderColor: theme.color.brand, backgroundColor: "#00000030" },
  kindLabel: { color: theme.color.textDim, fontWeight: "700", fontSize: 13 },
  kindHint: { color: theme.color.textDim, fontSize: 11, marginTop: 1 },
  input: {
    backgroundColor: "#00000030", borderWidth: 1, borderColor: theme.color.border, borderRadius: 6,
    paddingHorizontal: 10, paddingVertical: 8, color: theme.color.textHi, fontSize: 13,
  },
  scopeRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  scopeChip: {
    borderWidth: 1, borderColor: theme.color.border, borderRadius: 12,
    paddingHorizontal: 10, paddingVertical: 5, backgroundColor: "#00000030",
  },
  scopeChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  scopeChipText: { color: theme.color.textDim, fontSize: 11, fontWeight: "700" },
  errorText: { color: "#ff6666", fontSize: 12, marginTop: 8 },
  actions: { flexDirection: "row", gap: 8, marginTop: 18 },
  primaryBtn: {
    backgroundColor: theme.color.brand, paddingHorizontal: 16, paddingVertical: 10, borderRadius: 6,
  },
  primaryBtnText: { color: "#000", fontWeight: "800", letterSpacing: 0.5 },
  cancelBtn: {
    borderWidth: 1, borderColor: theme.color.border,
    paddingHorizontal: 16, paddingVertical: 10, borderRadius: 6,
  },
  cancelBtnText: { color: theme.color.textDim, fontWeight: "700" },
});
