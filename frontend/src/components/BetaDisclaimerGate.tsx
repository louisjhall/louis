/**
 * BetaDisclaimerGate — modal shown after login when the user hasn't yet
 * accepted the current beta disclaimer version. Blocks interaction until
 * they tap ACCEPT. Persists the acceptance server-side and locally.
 */
import React, { useEffect, useState } from "react";
import { View, Text, Modal, StyleSheet, Pressable, ActivityIndicator, ScrollView, Alert, Platform } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { useAuth } from "@/src/lib/auth";
import { theme } from "@/src/lib/theme";
import { usePreview } from "@/src/lib/preview";

const LOCAL_KEY = "cf_beta_accepted";

type BetaStatus = {
  required_version: string;
  accepted: boolean;
  disclaimer_text: string;
};

export function BetaDisclaimerGate() {
  const { user } = useAuth();
  const { preview } = usePreview();
  const [status, setStatus] = useState<BetaStatus | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!user) { setStatus(null); return; }
    // Never gate a preview session — that's a coach viewing a client.
    if (preview.active) { setStatus(null); return; }
    (async () => {
      try {
        // Fast local check first so we don't flash the modal for repeat users.
        const localKey = `${LOCAL_KEY}_${user.id}`;
        const localAccepted = await AsyncStorage.getItem(localKey);
        const r = await api<BetaStatus>("/beta/status");
        if (r.accepted || localAccepted === r.required_version) {
          if (localAccepted !== r.required_version) {
            await AsyncStorage.setItem(localKey, r.required_version);
          }
          setStatus(null);
        } else {
          setStatus(r);
        }
      } catch {
        setStatus(null); // fail-open: never block the app on a network hiccup
      }
    })();
  }, [user, preview.active]);

  const accept = async () => {
    if (!user || !status) return;
    setBusy(true);
    try {
      await api("/beta/accept", { method: "POST", body: { version: status.required_version } });
      await AsyncStorage.setItem(`${LOCAL_KEY}_${user.id}`, status.required_version);
      setStatus(null);
    } catch (e: any) {
      Alert.alert("Could not save", e?.message || "Please try again.");
    } finally { setBusy(false); }
  };

  if (!user || !status) return null;

  return (
    <Modal transparent animationType="fade">
      <View style={styles.backdrop}>
        <View style={styles.card}>
          <View style={styles.header}>
            <View style={styles.badge}>
              <Text style={styles.badgeT}>BETA</Text>
            </View>
            <Text style={styles.title}>Welcome to CrewFit</Text>
          </View>

          <ScrollView style={styles.body} contentContainerStyle={{ paddingBottom: 12 }}>
            <Text style={styles.p}>{status.disclaimer_text}</Text>
            <View style={styles.bullets}>
              <BulletRow icon="shield-checkmark" text="Your data is safe and encrypted in transit." />
              <BulletRow icon="bug" text="Bugs are expected. Report anything odd to louis@crewfit.net." />
              <BulletRow icon="refresh" text="Test data may be reset before public launch." />
              <BulletRow icon="trash" text="You can delete your account and export your data any time." />
            </View>
          </ScrollView>

          <Pressable onPress={accept} disabled={busy} style={[styles.cta, busy && { opacity: 0.5 }]} testID="beta-accept">
            {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.ctaT}>ACCEPT &amp; CONTINUE</Text>}
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

function BulletRow({ icon, text }: { icon: any; text: string }) {
  return (
    <View style={styles.bulletRow}>
      <Ionicons name={icon} size={14} color={theme.color.brand} />
      <Text style={styles.bulletT}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.85)", padding: 20, justifyContent: "center", alignItems: "center" },
  card: { backgroundColor: theme.color.surface, borderRadius: 14, padding: 22, borderWidth: 1, borderColor: theme.color.border, width: "100%", maxWidth: 520 },
  header: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 14 },
  badge: { backgroundColor: theme.color.brand, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 4 },
  badgeT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  title: { color: theme.color.text, fontSize: 20, fontWeight: "800", flex: 1 },
  body: { maxHeight: Platform.OS === "web" ? 320 : 260 },
  p: { color: theme.color.text, fontSize: 14, lineHeight: 22, marginBottom: 16 },
  bullets: { gap: 10 },
  bulletRow: { flexDirection: "row", alignItems: "flex-start", gap: 10 },
  bulletT: { color: theme.color.textMuted, fontSize: 13, lineHeight: 18, flex: 1 },
  cta: { backgroundColor: theme.color.brand, paddingVertical: 14, borderRadius: 8, alignItems: "center", marginTop: 16 },
  ctaT: { color: "#fff", fontWeight: "800", letterSpacing: 2, fontSize: 13 },
});
