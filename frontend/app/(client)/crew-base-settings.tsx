/**
 * Iter 129 — Crew Base client settings.
 *
 * Two independent preferences, kept intentionally simple (§7 + §11):
 *   1. Community identity — Initials (default) or Full name
 *   2. Crew Base notifications — On (default) or Off
 *
 * Both are stored server-side; the identity choice affects the public
 * name resolution used across every Crew Base endpoint.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, ScrollView, ActivityIndicator, Switch } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast } from "@/src/lib/ux";

type Settings = {
  crew_base_identity_mode: "initials" | "full_name";
  crew_base_notifications_enabled: boolean;
  public_preview: { public_name: string; avatar_initials: string };
};

export default function CrewBaseSettingsScreen() {
  const router = useRouter();
  const [s, setS] = useState<Settings | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await api<Settings>("/crew-base/settings");
      setS(res);
    } catch (_e) {
      /* ignore */
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const patch = async (body: any) => {
    setBusy(true);
    try {
      const res = await api<Settings>("/crew-base/settings", { method: "PATCH", body });
      setS(res as any);
      toast("Saved.", "success");
    } catch (e: any) {
      toast(e?.message || "Save failed.", "error");
    } finally {
      setBusy(false);
    }
  };

  if (!s) {
    return (
      <SafeAreaView style={styles.safe} edges={["top"]}>
        <View style={{ padding: 40, alignItems: "center" }}><ActivityIndicator /></View>
      </SafeAreaView>
    );
  }

  const preview = s.public_preview?.public_name || s.public_preview?.avatar_initials || "??";

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} testID="cb-settings-back">
          <Ionicons name="chevron-back" size={22} color={theme.color.text} />
        </Pressable>
        <Text style={styles.h1}>Crew Base Settings</Text>
        <View style={{ width: 22 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 60 }}>
        {/* Community identity */}
        <Text style={styles.sect}>COMMUNITY IDENTITY</Text>
        <Text style={styles.body}>Choose how your name appears to other CrewFit members.</Text>

        <IdentityRow
          selected={s.crew_base_identity_mode === "initials"}
          label="Initials"
          hint="Your initials will be shown instead of your name. Your profile photo is hidden."
          testID="cb-mode-initials"
          onPress={() => patch({ crew_base_identity_mode: "initials" })}
        />
        <IdentityRow
          selected={s.crew_base_identity_mode === "full_name"}
          label="Full name"
          hint="Your name will be visible to other CrewFit members."
          testID="cb-mode-full-name"
          onPress={() => patch({ crew_base_identity_mode: "full_name" })}
        />

        {/* Preview */}
        <View style={styles.previewBox}>
          <View style={styles.previewAvatar}>
            <Text style={styles.previewInitials}>{s.public_preview?.avatar_initials}</Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.previewName}>{preview}</Text>
            <Text style={styles.previewSub}>Your comments will appear as {preview} to other members.</Text>
          </View>
        </View>

        {/* Notifications */}
        <Text style={[styles.sect, { marginTop: theme.space.xl }]}>NOTIFICATIONS</Text>
        <View style={styles.rowSwitch}>
          <View style={{ flex: 1 }}>
            <Text style={styles.rowLabel}>Crew Base notifications</Text>
            <Text style={styles.rowHint}>Community posts, replies and Crew Base activity. Turning this off won&apos;t affect Messages, Flight Support, or Training notifications.</Text>
          </View>
          <Switch
            value={s.crew_base_notifications_enabled}
            onValueChange={(v) => patch({ crew_base_notifications_enabled: v })}
            testID="cb-notif-switch"
            disabled={busy}
          />
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function IdentityRow({
  selected, label, hint, onPress, testID,
}: { selected: boolean; label: string; hint: string; onPress: () => void; testID?: string }) {
  return (
    <Pressable onPress={onPress} style={[styles.identRow, selected && styles.identRowActive]} testID={testID}>
      <View style={[styles.radio, selected && styles.radioActive]}>
        {selected ? <View style={styles.radioInner} /> : null}
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.identLabel}>{label}</Text>
        <Text style={styles.identHint}>{hint}</Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.color.bg },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: theme.space.lg, paddingVertical: theme.space.md,
    borderBottomWidth: 1, borderBottomColor: theme.color.divider,
  },
  h1: { color: theme.color.text, fontSize: 16, fontWeight: "900" },
  sect: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 2, marginBottom: theme.space.sm },
  body: { color: theme.color.textMuted, fontSize: 13, lineHeight: 18, marginBottom: theme.space.md },
  identRow: {
    flexDirection: "row", alignItems: "flex-start", gap: 12,
    padding: 14, borderRadius: 10, marginBottom: 8,
    borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface,
  },
  identRowActive: { borderColor: theme.color.brand, backgroundColor: theme.color.brandTint },
  radio: { width: 20, height: 20, borderRadius: 10, borderWidth: 2, borderColor: theme.color.border, alignItems: "center", justifyContent: "center", marginTop: 2 },
  radioActive: { borderColor: theme.color.brand },
  radioInner: { width: 10, height: 10, borderRadius: 5, backgroundColor: theme.color.brand },
  identLabel: { color: theme.color.text, fontSize: 14, fontWeight: "800" },
  identHint: { color: theme.color.textMuted, fontSize: 12, lineHeight: 16, marginTop: 3 },

  previewBox: {
    flexDirection: "row", alignItems: "center", gap: 12,
    padding: 12, marginTop: 12, borderRadius: 10,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  previewAvatar: { width: 44, height: 44, borderRadius: 22, backgroundColor: theme.color.surface3, borderWidth: 1, borderColor: theme.color.border, alignItems: "center", justifyContent: "center" },
  previewInitials: { color: theme.color.text, fontWeight: "900", fontSize: 14, letterSpacing: 0.5 },
  previewName: { color: theme.color.text, fontWeight: "800", fontSize: 14 },
  previewSub: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },

  rowSwitch: {
    flexDirection: "row", alignItems: "center", gap: 10,
    padding: 14, borderRadius: 10, backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border,
  },
  rowLabel: { color: theme.color.text, fontSize: 14, fontWeight: "800" },
  rowHint: { color: theme.color.textMuted, fontSize: 12, lineHeight: 16, marginTop: 3 },
});
