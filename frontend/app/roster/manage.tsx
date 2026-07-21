/**
 * Client Roster Management screen — Plan D4/D6.
 *
 * Actions:
 *   - Review or edit roster (opens the roster confirmation screen)
 *   - Upload updated roster (safer replacement — keeps current plan active)
 *   - Delete roster and start again (two modes)
 *
 * Copy rules:
 *   - Never mention "AI".
 *   - Use "CrewFit will rebuild your plan".
 */
import { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ScrollView, ActivityIndicator,
  Modal, TextInput,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter, Stack } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type MgmtData = {
  active_roster: any | null;
  programme: any | null;
  upcoming_workouts_count: number;
  coach_locked_upcoming_count: number;
  pending_replacement: any | null;
  versions_total: number;
};

export default function RosterManagement() {
  const router = useRouter();
  const [data, setData] = useState<MgmtData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Delete flow state
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [mode, setMode] = useState<"delete_and_future_plan" | "delete_only">("delete_and_future_plan");
  const [typedDelete, setTypedDelete] = useState("");
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [receipt, setReceipt] = useState<any | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await api<MgmtData>("/roster/management");
      setData(r);
    } catch (e: any) {
      setError(e?.message || "Could not load roster info");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const active = data?.active_roster;
  const coachLocked = data?.coach_locked_upcoming_count || 0;
  const upcoming = data?.upcoming_workouts_count || 0;

  const doDelete = async () => {
    if (!active) return;
    if (typedDelete !== "DELETE") {
      setError("Please type DELETE to confirm.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const r = await api<any>("/roster/delete-and-restart", {
        method: "POST",
        body: JSON.stringify({
          mode, reason: reason || null,
          confirm: true, typed_delete: typedDelete,
        }),
      });
      setReceipt(r);
      setDeleteOpen(false);
      setTypedDelete("");
      setReason("");
      // Reload state so the "no active roster" panel shows.
      await load();
    } catch (e: any) {
      setError(e?.message || "Could not remove roster. Try again.");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.wrap}>
        <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.wrap} edges={["top"]}>
      <Stack.Screen options={{ title: "Roster Management", headerShown: false }} />
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12} style={styles.backBtn}>
          <Ionicons name="chevron-back" size={22} color={theme.color.text} />
        </Pressable>
        <Text style={styles.title}>Roster Management</Text>
        <View style={{ width: 32 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 32 }}>
        {receipt && (
          <View style={[styles.card, styles.successCard]}>
            <View style={styles.rowCenter}>
              <Ionicons name="checkmark-circle" size={22} color={theme.color.green} />
              <Text style={styles.successTitle}>Roster removed</Text>
            </View>
            <Text style={styles.successBody}>{receipt.message}</Text>
            <View style={styles.detailBox}>
              <Text style={styles.detailLine}>Workouts deactivated: {receipt.cleanup_summary?.workouts_deactivated ?? 0}</Text>
              <Text style={styles.detailLine}>Coach-locked kept: {receipt.cleanup_summary?.coach_locked_preserved ?? 0}</Text>
              <Text style={styles.detailLine}>Pending jobs cancelled: {receipt.cleanup_summary?.jobs_cancelled ?? 0}</Text>
            </View>
            <Pressable onPress={() => router.replace("/roster-upload")} style={styles.primaryBtn}>
              <Text style={styles.primaryBtnT}>Upload New Roster</Text>
            </Pressable>
          </View>
        )}

        {error && (
          <View style={styles.errCard}>
            <Ionicons name="alert-circle" size={18} color={theme.color.red} />
            <Text style={styles.errTxt}>{error}</Text>
          </View>
        )}

        {/* Active roster summary */}
        {active ? (
          <View style={styles.card}>
            <Text style={styles.cardHeader}>YOUR ACTIVE ROSTER</Text>
            <View style={styles.rowBetween}>
              <Text style={styles.cardKey}>Period</Text>
              <Text style={styles.cardVal}>
                {active.week_start || active.start_date || "—"} → {active.week_end || active.end_date || "—"}
              </Text>
            </View>
            <View style={styles.rowBetween}>
              <Text style={styles.cardKey}>Uploaded</Text>
              <Text style={styles.cardVal}>{(active.created_at || "").slice(0, 10) || "—"}</Text>
            </View>
            <View style={styles.rowBetween}>
              <Text style={styles.cardKey}>Version</Text>
              <Text style={styles.cardVal}>#{data?.versions_total || 1}</Text>
            </View>
            <View style={styles.rowBetween}>
              <Text style={styles.cardKey}>Upcoming workouts</Text>
              <Text style={styles.cardVal}>{upcoming}</Text>
            </View>
            {coachLocked > 0 && (
              <View style={styles.warnBox}>
                <Ionicons name="lock-closed" size={14} color={theme.color.amber} />
                <Text style={styles.warnTxt}>
                  Louis has locked {coachLocked} upcoming session{coachLocked !== 1 ? "s" : ""}. These stay in place if you delete your roster.
                </Text>
              </View>
            )}
          </View>
        ) : (
          <View style={styles.card}>
            <Text style={styles.cardHeader}>NO ACTIVE ROSTER</Text>
            <Text style={styles.emptyTxt}>Upload your roster so CrewFit can build your training week.</Text>
            <Pressable onPress={() => router.replace("/roster-upload")} style={styles.primaryBtn}>
              <Text style={styles.primaryBtnT}>Upload Roster</Text>
            </Pressable>
          </View>
        )}

        {data?.pending_replacement && (
          <View style={[styles.card, { backgroundColor: "#20180a" }]}>
            <Text style={styles.cardHeader}>REPLACEMENT AWAITING CONFIRMATION</Text>
            <Text style={styles.emptyTxt}>You&apos;ve uploaded a new roster — review and confirm to activate it.</Text>
            <Pressable onPress={() => router.push("/roster-upload")} style={styles.primaryBtn}>
              <Text style={styles.primaryBtnT}>Review New Roster</Text>
            </Pressable>
          </View>
        )}

        {/* Actions */}
        {active && (
          <>
            <Text style={styles.sectionH}>ACTIONS</Text>

            <Pressable onPress={() => router.push("/roster/confirm")} style={styles.actionRow}>
              <Ionicons name="create-outline" size={20} color={theme.color.text} />
              <View style={{ flex: 1 }}>
                <Text style={styles.actionTitle}>Review or edit roster</Text>
                <Text style={styles.actionSub}>Fix a duty or update a layover — no plan changes needed.</Text>
              </View>
              <Ionicons name="chevron-forward" size={18} color={theme.color.textMuted} />
            </Pressable>

            <Pressable onPress={() => router.push("/roster-upload")} style={styles.actionRow}>
              <Ionicons name="cloud-upload-outline" size={20} color={theme.color.text} />
              <View style={{ flex: 1 }}>
                <Text style={styles.actionTitle}>Upload updated roster</Text>
                <Text style={styles.actionSub}>Recommended for a roster revision. Your current plan stays active until you confirm the new one.</Text>
              </View>
              <Ionicons name="chevron-forward" size={18} color={theme.color.textMuted} />
            </Pressable>

            <Pressable onPress={() => setDeleteOpen(true)} style={[styles.actionRow, { borderColor: theme.color.red + "44" }]}>
              <Ionicons name="trash-outline" size={20} color={theme.color.red} />
              <View style={{ flex: 1 }}>
                <Text style={[styles.actionTitle, { color: theme.color.red }]}>Delete roster and start again</Text>
                <Text style={styles.actionSub}>Removes this roster. Choose whether to remove your upcoming workouts too.</Text>
              </View>
              <Ionicons name="chevron-forward" size={18} color={theme.color.textMuted} />
            </Pressable>
          </>
        )}
      </ScrollView>

      {/* Delete confirmation modal */}
      <Modal visible={deleteOpen} animationType="slide" transparent onRequestClose={() => setDeleteOpen(false)}>
        <View style={styles.modalBg}>
          <View style={styles.sheet}>
            <View style={styles.sheetHandle} />
            <Text style={styles.sheetTitle}>Delete this roster and start again?</Text>
            <Text style={styles.sheetBody}>
              This will remove the current roster from your active calendar. Your completed workout history will not be deleted.
            </Text>

            <Pressable
              onPress={() => setMode("delete_and_future_plan")}
              style={[styles.modeRow, mode === "delete_and_future_plan" && styles.modeRowSelected]}
            >
              <Ionicons name={mode === "delete_and_future_plan" ? "radio-button-on" : "radio-button-off"} size={20} color={theme.color.brand} />
              <View style={{ flex: 1 }}>
                <Text style={styles.modeTitle}>Delete Roster And Future Plan · Recommended</Text>
                <Text style={styles.modeSub}>Removes upcoming workouts linked to this roster. Coach-locked and completed sessions stay.</Text>
              </View>
            </Pressable>

            <Pressable
              onPress={() => setMode("delete_only")}
              style={[styles.modeRow, mode === "delete_only" && styles.modeRowSelected]}
            >
              <Ionicons name={mode === "delete_only" ? "radio-button-on" : "radio-button-off"} size={20} color={theme.color.brand} />
              <View style={{ flex: 1 }}>
                <Text style={styles.modeTitle}>Delete Roster Only</Text>
                <Text style={styles.modeSub}>Keeps upcoming workouts temporarily — they may no longer match your flying schedule.</Text>
              </View>
            </Pressable>

            {coachLocked > 0 && (
              <View style={styles.warnBox}>
                <Ionicons name="lock-closed" size={14} color={theme.color.amber} />
                <Text style={styles.warnTxt}>
                  Louis has locked {coachLocked} upcoming session{coachLocked !== 1 ? "s" : ""}. These will NOT be removed automatically.
                </Text>
              </View>
            )}

            <Text style={styles.confirmLabel}>Type DELETE to confirm</Text>
            <TextInput
              value={typedDelete}
              onChangeText={setTypedDelete}
              placeholder="DELETE"
              placeholderTextColor={theme.color.textMuted}
              autoCapitalize="characters"
              autoCorrect={false}
              style={styles.confirmInput}
            />

            <TextInput
              value={reason}
              onChangeText={setReason}
              placeholder="Optional: tell Louis why (helps him understand)"
              placeholderTextColor={theme.color.textMuted}
              style={[styles.confirmInput, { marginTop: 8 }]}
              multiline
            />

            <View style={styles.sheetBtnRow}>
              <Pressable onPress={() => setDeleteOpen(false)} disabled={submitting} style={styles.secondaryBtn}>
                <Text style={styles.secondaryBtnT}>Cancel</Text>
              </Pressable>
              <Pressable
                onPress={doDelete}
                disabled={submitting || typedDelete !== "DELETE"}
                style={[styles.dangerBtn, (submitting || typedDelete !== "DELETE") && { opacity: 0.5 }]}
              >
                {submitting ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <Text style={styles.dangerBtnT}>{mode === "delete_and_future_plan" ? "Delete Roster + Future Plan" : "Delete Roster Only"}</Text>
                )}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: theme.color.bg },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 12, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: theme.color.line },
  backBtn: { width: 32, height: 32, alignItems: "center", justifyContent: "center" },
  title: { color: theme.color.text, fontSize: 16, fontWeight: "800", letterSpacing: 0.5 },
  card: { backgroundColor: theme.color.cardBg, borderWidth: 1, borderColor: theme.color.line, borderRadius: 10, padding: 14, marginBottom: 12 },
  successCard: { borderColor: theme.color.green, backgroundColor: "#0c1f16" },
  cardHeader: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1.2, fontWeight: "800", marginBottom: 10 },
  cardKey: { color: theme.color.textMuted, fontSize: 13 },
  cardVal: { color: theme.color.text, fontSize: 13, fontWeight: "700" },
  rowBetween: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: 6 },
  rowCenter: { flexDirection: "row", alignItems: "center", gap: 8 },
  emptyTxt: { color: theme.color.textMuted, fontSize: 13, marginBottom: 12 },
  primaryBtn: { backgroundColor: theme.color.brand, borderRadius: 8, paddingVertical: 12, alignItems: "center", marginTop: 12 },
  primaryBtnT: { color: "#fff", fontWeight: "800", letterSpacing: 0.5 },
  errCard: { flexDirection: "row", alignItems: "center", gap: 8, padding: 10, borderRadius: 8, backgroundColor: "#2a1010", marginBottom: 12 },
  errTxt: { color: theme.color.red, flex: 1, fontSize: 12 },
  warnBox: { flexDirection: "row", alignItems: "flex-start", gap: 8, padding: 10, borderRadius: 8, backgroundColor: "#1F1608", borderWidth: 1, borderColor: theme.color.amber, marginTop: 10 },
  warnTxt: { color: theme.color.amber, flex: 1, fontSize: 12, lineHeight: 16 },
  sectionH: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1.2, fontWeight: "800", marginTop: 6, marginBottom: 8 },
  actionRow: { flexDirection: "row", alignItems: "center", gap: 12, padding: 14, borderRadius: 10, backgroundColor: theme.color.cardBg, borderWidth: 1, borderColor: theme.color.line, marginBottom: 8 },
  actionTitle: { color: theme.color.text, fontSize: 14, fontWeight: "700" },
  actionSub: { color: theme.color.textMuted, fontSize: 12, marginTop: 2, lineHeight: 16 },
  detailBox: { backgroundColor: theme.color.bg, borderRadius: 8, padding: 10, marginTop: 10 },
  detailLine: { color: theme.color.text, fontSize: 12, marginVertical: 2 },
  // Modal
  modalBg: { flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(0,0,0,0.6)" },
  sheet: { backgroundColor: theme.color.bg, borderTopLeftRadius: 16, borderTopRightRadius: 16, padding: 20, maxHeight: "92%" },
  sheetHandle: { width: 44, height: 4, backgroundColor: theme.color.line, borderRadius: 2, alignSelf: "center", marginBottom: 14 },
  sheetTitle: { color: theme.color.text, fontSize: 18, fontWeight: "800", marginBottom: 8 },
  sheetBody: { color: theme.color.textMuted, fontSize: 13, lineHeight: 18, marginBottom: 14 },
  modeRow: { flexDirection: "row", alignItems: "flex-start", gap: 10, padding: 12, borderRadius: 10, borderWidth: 1, borderColor: theme.color.line, marginBottom: 8 },
  modeRowSelected: { borderColor: theme.color.brand, backgroundColor: theme.color.cardBg },
  modeTitle: { color: theme.color.text, fontSize: 13, fontWeight: "700" },
  modeSub: { color: theme.color.textMuted, fontSize: 12, marginTop: 3, lineHeight: 16 },
  confirmLabel: { color: theme.color.textMuted, fontSize: 12, letterSpacing: 0.8, fontWeight: "700", marginTop: 12, marginBottom: 6 },
  confirmInput: { backgroundColor: theme.color.cardBg, borderWidth: 1, borderColor: theme.color.line, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 10, color: theme.color.text, fontSize: 14 },
  sheetBtnRow: { flexDirection: "row", gap: 10, marginTop: 16 },
  secondaryBtn: { flex: 1, paddingVertical: 12, borderRadius: 8, borderWidth: 1, borderColor: theme.color.line, alignItems: "center" },
  secondaryBtnT: { color: theme.color.text, fontWeight: "700" },
  dangerBtn: { flex: 2, paddingVertical: 12, borderRadius: 8, backgroundColor: theme.color.red, alignItems: "center" },
  dangerBtnT: { color: "#fff", fontWeight: "800" },
  successTitle: { color: theme.color.green, fontSize: 15, fontWeight: "800" },
  successBody: { color: theme.color.text, fontSize: 13, marginTop: 6, lineHeight: 18 },
});
