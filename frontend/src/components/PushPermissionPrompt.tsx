/**
 * PushPermissionPrompt — a one-time gentle prompt shown on the client home,
 * only if the user hasn't yet chosen granted/denied. Non-blocking; can be
 * dismissed and won't appear again in the same session.
 */
import { useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, Modal, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { useAuth } from "@/src/lib/auth";
import { promptAndRegisterPush } from "@/src/lib/push";

// Session-scoped guard so we don't nag the same user twice per open
let sessionShown = false;

export function PushPermissionPrompt() {
  const { user } = useAuth();
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (sessionShown || !user) return;
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const r = await api<{ settings: any }>("/notifications/settings");
        if (cancelled) return;
        if (r?.settings?.permission_status === "not_requested") {
          sessionShown = true;
          setVisible(true);
        }
      } catch { /* ignore */ }
    }, 2500);
    return () => { cancelled = true; clearTimeout(t); };
  }, [user]);

  const allow = async () => {
    if (!user?.id) { setVisible(false); return; }
    if (Platform.OS === "web") {
      await api("/notifications/permission", { method: "POST", body: { status: "denied", platform: "web" } }).catch(() => null);
      setVisible(false);
      return;
    }
    await promptAndRegisterPush(user.id);
    setVisible(false);
  };

  const notNow = async () => {
    // Only save 'denied' if the user explicitly says no thanks.
    // 'not_requested' would prompt again; we prefer not to nag, so we mark as 'denied'
    // but the Preferences card lets them turn it back on any time.
    await api("/notifications/permission", { method: "POST", body: { status: "denied", platform: Platform.OS } }).catch(() => null);
    setVisible(false);
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={() => setVisible(false)}>
      <View style={styles.bg}>
        <View style={styles.card}>
          <View style={styles.iconWrap}>
            <Ionicons name="notifications" size={28} color={theme.color.brand} />
          </View>
          <Text style={styles.title}>Stay in touch with Louis</Text>
          <Text style={styles.body}>
            Allow CrewFit to send reminders for check-ins, workouts, habits and coach updates.
            Quiet by default — nothing during quiet hours or flight duty.
          </Text>
          <View style={styles.actionRow}>
            <Pressable testID="perm-later" onPress={notNow} style={styles.laterBtn}>
              <Text style={styles.laterT}>NOT NOW</Text>
            </Pressable>
            <Pressable testID="perm-allow" onPress={allow} style={styles.allowBtn}>
              <Text style={styles.allowT}>ALLOW</Text>
            </Pressable>
          </View>
          <Text style={styles.hint}>You can change this any time in Profile → Notifications.</Text>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  bg: { flex: 1, backgroundColor: "rgba(0,0,0,0.65)", alignItems: "center", justifyContent: "center", padding: 24 },
  card: { backgroundColor: theme.color.surface, borderRadius: 16, padding: 22, borderWidth: 1, borderColor: theme.color.border, maxWidth: 360, width: "100%" },
  iconWrap: { alignSelf: "flex-start", padding: 12, borderRadius: 100, backgroundColor: theme.color.brandTint, marginBottom: 14 },
  title: { color: theme.color.text, fontSize: 18, fontWeight: "900", marginBottom: 8 },
  body: { color: theme.color.textMuted, fontSize: 13, lineHeight: 19, marginBottom: 20 },
  actionRow: { flexDirection: "row", gap: 10 },
  laterBtn: { flex: 1, alignItems: "center", justifyContent: "center", paddingVertical: 13, borderRadius: 10, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  laterT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "800", letterSpacing: 1.5 },
  allowBtn: { flex: 1, alignItems: "center", justifyContent: "center", paddingVertical: 13, borderRadius: 10, backgroundColor: theme.color.brand },
  allowT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  hint: { color: theme.color.textDim, fontSize: 10, marginTop: 12, textAlign: "center" },
});
