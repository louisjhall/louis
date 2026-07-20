/**
 * Admin · Coach Management
 *
 * Louis-only screen to invite, list, and manage coaches. Displays workload
 * counts and lets Louis promote/demote tiers, activate/deactivate coaches.
 */
import { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Alert,
  Modal, TextInput, KeyboardAvoidingView, Platform, RefreshControl,
} from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Coach = {
  id: string;
  email: string;
  name: string;
  role: string;
  is_admin: boolean;
  coach_tier: "admin" | "full" | "assistant";
  status: string;
  assigned_clients: number;
  phone?: string;
  created_at?: string;
  last_login?: string;
};

const TIER_LABEL: Record<Coach["coach_tier"], { label: string; color: string }> = {
  admin:     { label: "ADMIN",     color: theme.color.brand },
  full:      { label: "COACH",     color: theme.color.text },
  assistant: { label: "ASSISTANT", color: theme.color.textMuted },
};

export default function AdminCoaches() {
  const router = useRouter();
  const [coaches, setCoaches] = useState<Coach[]>([]);
  const [loading, setLoading] = useState(true);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteName, setInviteName] = useState("");
  const [inviteTier, setInviteTier] = useState<"full" | "assistant">("full");
  const [invitePhone, setInvitePhone] = useState("");
  const [inviting, setInviting] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<{ coaches: Coach[] }>(`/admin/coaches`);
      setCoaches(r.coaches || []);
    } catch (e: any) {
      Alert.alert("Load failed", e?.message || "Could not load coach list.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const doInvite = async () => {
    if (!inviteEmail.trim() || !inviteName.trim()) {
      Alert.alert("Missing info", "Please enter both name and email.");
      return;
    }
    setInviting(true);
    try {
      const r = await api<any>(`/admin/coaches/invite`, {
        method: "POST",
        body: { email: inviteEmail.trim(), name: inviteName.trim(), tier: inviteTier, phone: invitePhone.trim() || null },
      });
      setInviteOpen(false);
      setInviteEmail(""); setInviteName(""); setInvitePhone(""); setInviteTier("full");
      Alert.alert(
        "Coach invited",
        `Temporary password: ${r.temp_password}\n\nShare this with ${r.email}. They will be prompted to change it on first login.`,
      );
      load();
    } catch (e: any) {
      Alert.alert("Invite failed", e?.message || "Try again.");
    } finally {
      setInviting(false);
    }
  };

  const toggleActive = async (c: Coach) => {
    setBusyId(c.id);
    try {
      const path = c.status === "active" ? "deactivate" : "activate";
      await api(`/admin/coaches/${c.id}/${path}`, { method: "POST" });
      load();
    } catch (e: any) {
      Alert.alert("Update failed", e?.message || "Try again.");
    } finally {
      setBusyId(null);
    }
  };

  const changeTier = (c: Coach) => {
    if (c.is_admin) {
      Alert.alert("Admin locked", "Admins can only be demoted with an API call — deliberate safeguard.");
      return;
    }
    Alert.alert(
      `Change tier for ${c.name}?`,
      "Current tier: " + TIER_LABEL[c.coach_tier].label,
      [
        { text: "Cancel", style: "cancel" },
        { text: "Set to Coach",     onPress: () => setTier(c.id, "full") },
        { text: "Set to Assistant", onPress: () => setTier(c.id, "assistant") },
      ],
    );
  };

  const setTier = async (coach_id: string, tier: "full" | "assistant") => {
    setBusyId(coach_id);
    try {
      await api(`/admin/coaches/${coach_id}`, { method: "PATCH", body: { tier } });
      load();
    } catch (e: any) {
      Alert.alert("Update failed", e?.message || "Try again.");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.top}>
        <Pressable onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="chevron-back" size={24} color={theme.color.text} />
        </Pressable>
        <Text style={styles.topT}>COACHES</Text>
        <Pressable testID="coach-invite-btn" onPress={() => setInviteOpen(true)} hitSlop={12}>
          <Ionicons name="add-circle" size={22} color={theme.color.brand} />
        </Pressable>
      </View>

      <ScrollView
        contentContainerStyle={{ padding: 12, paddingBottom: 32 }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}
      >
        {loading && coaches.length === 0 ? (
          <ActivityIndicator color={theme.color.brand} style={{ marginTop: 40 }} />
        ) : null}

        {coaches.map((c) => {
          const tier = TIER_LABEL[c.coach_tier] || TIER_LABEL.full;
          const isPaused = c.status !== "active";
          return (
            <View key={c.id} style={[styles.card, isPaused && { opacity: 0.55 }]}>
              <View style={styles.cardTop}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.name} numberOfLines={1}>{c.name}</Text>
                  <Text style={styles.email} numberOfLines={1}>{c.email}</Text>
                </View>
                <View style={[styles.tierPill, { borderColor: tier.color }]}>
                  <Text style={[styles.tierPillText, { color: tier.color }]}>{tier.label}</Text>
                </View>
              </View>
              <View style={styles.metaRow}>
                <Text style={styles.metaChip}>{c.assigned_clients} CLIENTS</Text>
                <Text style={[styles.metaChip, { color: isPaused ? "#c85450" : theme.color.green }]}>
                  {isPaused ? "PAUSED" : "ACTIVE"}
                </Text>
              </View>
              <View style={styles.actionsRow}>
                <Pressable
                  testID={`coach-tier-${c.id}`}
                  onPress={() => changeTier(c)}
                  disabled={busyId === c.id || c.is_admin}
                  style={[styles.actionGhost, c.is_admin && { opacity: 0.4 }]}
                >
                  <Ionicons name="swap-vertical" size={12} color={theme.color.text} />
                  <Text style={styles.actionGhostText}>CHANGE TIER</Text>
                </Pressable>
                <Pressable
                  testID={`coach-toggle-${c.id}`}
                  onPress={() => toggleActive(c)}
                  disabled={busyId === c.id || c.is_admin}
                  style={[styles.actionGhost, c.is_admin && { opacity: 0.4 }]}
                >
                  {busyId === c.id ? <ActivityIndicator color={theme.color.brand} size="small" /> : (
                    <>
                      <Ionicons name={isPaused ? "play" : "pause"} size={12} color={theme.color.text} />
                      <Text style={styles.actionGhostText}>{isPaused ? "ACTIVATE" : "DEACTIVATE"}</Text>
                    </>
                  )}
                </Pressable>
              </View>
            </View>
          );
        })}
      </ScrollView>

      <Modal visible={inviteOpen} transparent animationType="slide" onRequestClose={() => setInviteOpen(false)}>
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={styles.modalScrim}>
          <View style={styles.modalSheet}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>INVITE COACH</Text>
              <Pressable onPress={() => setInviteOpen(false)} hitSlop={10}>
                <Ionicons name="close" size={22} color={theme.color.text} />
              </Pressable>
            </View>
            <ScrollView keyboardShouldPersistTaps="handled">
              <Text style={styles.field}>NAME</Text>
              <TextInput testID="invite-name" value={inviteName} onChangeText={setInviteName} style={styles.input} placeholder="Jane Coach" placeholderTextColor={theme.color.textDim} />
              <Text style={styles.field}>EMAIL</Text>
              <TextInput testID="invite-email" value={inviteEmail} onChangeText={setInviteEmail} style={styles.input} placeholder="jane@example.com" placeholderTextColor={theme.color.textDim} autoCapitalize="none" keyboardType="email-address" />
              <Text style={styles.field}>PHONE (OPTIONAL)</Text>
              <TextInput testID="invite-phone" value={invitePhone} onChangeText={setInvitePhone} style={styles.input} placeholder="+44 7700 900000" placeholderTextColor={theme.color.textDim} keyboardType="phone-pad" />
              <Text style={styles.field}>TIER</Text>
              <View style={{ flexDirection: "row", gap: 8 }}>
                <Pressable testID="invite-tier-full" onPress={() => setInviteTier("full")} style={[styles.tierBtn, inviteTier === "full" && styles.tierBtnActive]}>
                  <Text style={[styles.tierBtnText, inviteTier === "full" && { color: "#fff" }]}>COACH</Text>
                </Pressable>
                <Pressable testID="invite-tier-assistant" onPress={() => setInviteTier("assistant")} style={[styles.tierBtn, inviteTier === "assistant" && styles.tierBtnActive]}>
                  <Text style={[styles.tierBtnText, inviteTier === "assistant" && { color: "#fff" }]}>ASSISTANT</Text>
                </Pressable>
              </View>
              <Text style={styles.helper}>
                Coach: full permissions on assigned clients. Assistant: view + notes only, cannot delete or add coaches.
              </Text>
              <Pressable
                testID="invite-submit"
                onPress={doInvite}
                disabled={inviting}
                style={[styles.actionPrimary, { marginTop: 16 }, inviting && { opacity: 0.6 }]}
              >
                {inviting ? <ActivityIndicator color="#fff" /> : <Text style={styles.actionPrimaryText}>SEND INVITE</Text>}
              </Pressable>
            </ScrollView>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  top: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 14, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: theme.color.border },
  topT: { color: theme.color.text, fontSize: 14, letterSpacing: 2, fontWeight: "800" },
  card: { padding: 14, borderRadius: theme.radius.md, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, marginBottom: 10 },
  cardTop: { flexDirection: "row", alignItems: "center", gap: 12 },
  name: { color: theme.color.text, fontSize: 15, fontWeight: "800" },
  email: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  tierPill: { borderWidth: 1, paddingHorizontal: 8, paddingVertical: 3, borderRadius: theme.radius.pill },
  tierPillText: { fontSize: 9, fontWeight: "800", letterSpacing: 1 },
  metaRow: { flexDirection: "row", gap: 8, marginTop: 8 },
  metaChip: { color: theme.color.textMuted, fontSize: 9, fontWeight: "800", letterSpacing: 1, borderWidth: 1, borderColor: theme.color.border, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  actionsRow: { flexDirection: "row", gap: 8, marginTop: 12 },
  actionGhost: { flex: 1, flexDirection: "row", justifyContent: "center", alignItems: "center", gap: 6, paddingVertical: 8, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, backgroundColor: "transparent" },
  actionGhostText: { color: theme.color.text, fontWeight: "800", letterSpacing: 1, fontSize: 10 },
  actionPrimary: { backgroundColor: theme.color.brand, paddingVertical: 12, borderRadius: theme.radius.md, alignItems: "center" },
  actionPrimaryText: { color: "#fff", fontWeight: "800", letterSpacing: 1.5, fontSize: 12 },
  modalScrim: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  modalSheet: { backgroundColor: theme.color.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: 16, paddingBottom: 24 },
  modalHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 12 },
  modalTitle: { color: theme.color.text, fontSize: 14, fontWeight: "900", letterSpacing: 2 },
  field: { color: theme.color.textDim, fontSize: 9, letterSpacing: 1.5, fontWeight: "800", marginTop: 12, marginBottom: 4 },
  input: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, color: theme.color.text, padding: 12, borderWidth: 1, borderColor: theme.color.border, fontSize: 14 },
  tierBtn: { flex: 1, paddingVertical: 10, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface2, alignItems: "center" },
  tierBtnActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  tierBtnText: { color: theme.color.text, fontSize: 11, fontWeight: "800", letterSpacing: 1.2 },
  helper: { color: theme.color.textDim, fontSize: 11, marginTop: 8, lineHeight: 14 },
});
