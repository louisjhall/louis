/**
 * NotificationPreferencesCard — client's notification settings.
 * 7 category toggles + quiet hours + preferred reminder time + travel-tz.
 * Also prompts the OS-level push permission when the user asks to enable coach messages.
 */
import { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, Switch, TextInput, Alert, Platform, Linking } from "react-native";
import * as Notifications from "expo-notifications";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { useAuth } from "@/src/lib/auth";
import { promptAndRegisterPush } from "@/src/lib/push";

type Settings = {
  check_ins: boolean;
  habits: boolean;
  workouts: boolean;
  coach_messages: boolean;
  weekly_videos: boolean;
  roster: boolean;
  programme_updates: boolean;
  flight_support: boolean;
  quiet_hours_start: string;
  quiet_hours_end: string;
  preferred_reminder_time: string;
  travel_use_current_tz: boolean;
  permission_status: "granted" | "denied" | "not_requested";
};

// Iter 123 — Notification categories grouped for the client-facing UI.
// Underlying preference keys are unchanged (server-side gating is identical).
// Iter 127 — Added AVIATION group for the Flight Support push toggle.
type Row = { key: keyof Settings; label: string; description: string };
const GROUPS: { title: string; rows: Row[] }[] = [
  {
    title: "COACH",
    rows: [
      { key: "coach_messages",    label: "Coach messages",    description: "When Louis replies" },
      { key: "programme_updates", label: "Programme updates", description: "When your plan is adjusted" },
      { key: "weekly_videos",     label: "Weekly reviews",    description: "When Louis sends your review" },
    ],
  },
  {
    title: "MY PLAN",
    rows: [
      { key: "workouts",  label: "Workouts",  description: "Session-of-the-day reminder" },
      { key: "habits",    label: "Habits",    description: "One kind nudge per day" },
      { key: "check_ins", label: "Check-ins", description: "Sunday reminders + missed follow-ups" },
      { key: "roster",    label: "Roster",    description: "7 / 3 / 1 days before it runs out + standby prompts" },
    ],
  },
  {
    title: "AVIATION",
    rows: [
      { key: "flight_support", label: "Flight Support", description: "Pre-flight, post-flight and layover support" },
    ],
  },
];

function validTime(s: string): boolean {
  return /^([01]?\d|2[0-3]):[0-5]\d$/.test(s || "");
}

export function NotificationPreferencesCard() {
  const { user } = useAuth();
  const [s, setS] = useState<Settings | null>(null);
  const [saving, setSaving] = useState(false);
  const [permStatus, setPermStatus] = useState<string>("not_requested");

  const load = useCallback(async () => {
    try {
      const r = await api<{ settings: Settings }>("/notifications/settings");
      setS(r.settings);
      setPermStatus(r.settings.permission_status || "not_requested");
    } catch { /* ignore */ }
  }, []);
  useEffect(() => { load(); }, [load]);

  // Iter 123 — Refresh permission status when the user returns from device
  // Settings so the banner updates without needing a full restart.
  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      if (Platform.OS === "web") return;
      try {
        const { status } = await Notifications.getPermissionsAsync();
        if (cancelled) return;
        const mapped = status === "granted" ? "granted" : (permStatus === "not_requested" ? "not_requested" : "denied");
        if (mapped !== permStatus) setPermStatus(mapped);
      } catch { /* ignore */ }
    };
    check();
    return () => { cancelled = true; };
  }, [permStatus]);

  const save = async (patch: Partial<Settings>) => {
    if (!s) return;
    const optimistic = { ...s, ...patch };
    setS(optimistic);
    setSaving(true);
    try {
      const r = await api<{ settings: Settings }>("/notifications/settings", { method: "PUT", body: patch });
      setS(r.settings);
    } catch (e: any) {
      Alert.alert("Couldn't save", e?.message || "Try again");
      load();
    } finally { setSaving(false); }
  };

  // Iter 123 — Contextual permission ask. Native re-prompt is blocked by the
  // OS after denial, so on `denied` we route directly to app settings via
  // Linking.openSettings() rather than firing another native prompt.
  const requestPushPermission = async () => {
    if (Platform.OS === "web") {
      try {
        const { status } = await Notifications.requestPermissionsAsync();
        await api("/notifications/permission", { method: "POST", body: { status: status === "granted" ? "granted" : "denied", platform: "web" } });
        setPermStatus(status === "granted" ? "granted" : "denied");
      } catch {
        Alert.alert("Push isn't available on the web preview", "Push notifications work after the app is deployed and installed on your device.");
      }
      return;
    }
    if (!user?.id) return;
    // If already denied, opening native settings is the ONLY way forward.
    if (permStatus === "denied") {
      try { await Linking.openSettings(); } catch {
        Alert.alert("Open Settings", "Please open your device Settings → CrewFit → Notifications to enable push.");
      }
      return;
    }
    const status = await promptAndRegisterPush(user.id);
    setPermStatus(status);
    if (status === "denied") {
      Alert.alert(
        "Push permission denied",
        "You can enable push later from your device settings. In-app notifications will still work.",
        [
          { text: "Not now", style: "cancel" },
          { text: "Open Settings", onPress: () => Linking.openSettings().catch(() => {}) },
        ],
      );
    }
  };

  if (!s) return null;

  return (
    <View style={styles.wrap}>
      <View style={styles.headRow}>
        <View>
          <Text style={styles.head}>NOTIFICATIONS</Text>
          <Text style={styles.sub}>
            These settings control which CrewFit updates can send push notifications.
            Important information stays available inside the app either way.
          </Text>
        </View>
        {saving ? <Text style={styles.savingT}>SAVING…</Text> : null}
      </View>

      {/* Iter 123 — Permission banner. Distinct states for granted / denied /
          not_requested. Denied routes straight to native Settings. */}
      {permStatus === "granted" ? (
        <View style={styles.permOnCard}>
          <Ionicons name="checkmark-circle" size={18} color={theme.color.green} />
          <Text style={styles.permOnT}>Push notifications enabled</Text>
        </View>
      ) : permStatus === "denied" ? (
        <Pressable testID="perm-open-settings" onPress={requestPushPermission} style={styles.permDeniedCard}>
          <Ionicons name="notifications-off" size={20} color={theme.color.textMuted} />
          <View style={{ flex: 1 }}>
            <Text style={styles.permTitle}>Push notifications are disabled by your device</Text>
            <Text style={styles.permBody}>
              Enable them in device Settings → CrewFit → Notifications. In-app updates keep working either way.
            </Text>
          </View>
          <View style={styles.openSettingsBtn}>
            <Text style={styles.openSettingsT}>OPEN SETTINGS</Text>
          </View>
        </Pressable>
      ) : (
        <Pressable testID="perm-request" onPress={requestPushPermission} style={styles.permCard}>
          <Ionicons name="notifications" size={20} color={theme.color.brand} />
          <View style={{ flex: 1 }}>
            <Text style={styles.permTitle}>Allow CrewFit to send push notifications</Text>
            <Text style={styles.permBody}>
              For check-ins, workouts, habits and coach updates. In-app notifications will still work either way.
            </Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color={theme.color.brand} />
        </Pressable>
      )}

      {/* Iter 123 — Category toggles grouped by intent. Preference keys are unchanged. */}
      {GROUPS.map((group) => (
        <View key={group.title}>
          <Text style={styles.sect}>{group.title}</Text>
          <View style={{ gap: 4 }}>
            {group.rows.map((row) => (
              <View key={row.key} style={styles.row}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowLabel}>{row.label}</Text>
                  <Text style={styles.rowDesc}>{row.description}</Text>
                </View>
                <Switch
                  testID={`notif-toggle-${row.key}`}
                  value={Boolean(s[row.key])}
                  onValueChange={(v) => save({ [row.key]: v } as any)}
                  trackColor={{ true: theme.color.brand, false: theme.color.borderStrong }}
                  thumbColor="#fff"
                />
              </View>
            ))}
          </View>
        </View>
      ))}

      {/* Timing group */}
      <Text style={styles.sect}>TIMING</Text>
      <TimeInput testID="pref-time" label="Preferred reminder time" value={s.preferred_reminder_time} onSave={(v) => save({ preferred_reminder_time: v })} />
      <View style={styles.rowInline}>
        <TimeInput testID="quiet-start" label="Quiet start" value={s.quiet_hours_start} onSave={(v) => save({ quiet_hours_start: v })} />
        <TimeInput testID="quiet-end" label="Quiet end" value={s.quiet_hours_end} onSave={(v) => save({ quiet_hours_end: v })} />
      </View>

      <View style={styles.row}>
        <View style={{ flex: 1 }}>
          <Text style={styles.rowLabel}>Use my current time zone while travelling</Text>
          <Text style={styles.rowDesc}>Reminders follow your device time zone.</Text>
        </View>
        <Switch
          testID="notif-travel-tz"
          value={Boolean(s.travel_use_current_tz)}
          onValueChange={(v) => save({ travel_use_current_tz: v })}
          trackColor={{ true: theme.color.brand, false: theme.color.borderStrong }}
          thumbColor="#fff"
        />
      </View>
    </View>
  );
}

function TimeInput({ label, value, onSave, testID }: { label: string; value: string; onSave: (v: string) => void; testID?: string }) {
  const [local, setLocal] = useState(value || "");
  useEffect(() => { setLocal(value || ""); }, [value]);
  const commit = () => {
    if (!validTime(local)) {
      Alert.alert("Use HH:MM", "Example: 07:30 or 21:00");
      setLocal(value);
      return;
    }
    if (local !== value) onSave(local);
  };
  return (
    <View style={{ flex: 1 }}>
      <Text style={styles.rowDesc}>{label}</Text>
      <TextInput
        testID={testID}
        value={local}
        onChangeText={setLocal}
        onBlur={commit}
        onSubmitEditing={commit}
        placeholder="HH:MM"
        placeholderTextColor={theme.color.textDim}
        keyboardType="numbers-and-punctuation"
        maxLength={5}
        style={styles.timeInput}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { marginTop: 24, marginHorizontal: 20 },
  headRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 },
  head: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  sub: { color: theme.color.textMuted, fontSize: 11, marginTop: 3, maxWidth: 280 },
  savingT: { color: theme.color.textDim, fontSize: 9, fontWeight: "800", letterSpacing: 1.5 },
  permCard: { flexDirection: "row", alignItems: "center", gap: 10, padding: 12, marginTop: 4, borderRadius: 10, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand },
  permDeniedCard: { flexDirection: "row", alignItems: "center", gap: 10, padding: 12, marginTop: 4, borderRadius: 10, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.borderStrong },
  openSettingsBtn: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8, backgroundColor: theme.color.brand },
  openSettingsT: { color: "#000", fontSize: 10, fontWeight: "900", letterSpacing: 1.2 },
  permTitle: { color: theme.color.text, fontSize: 12, fontWeight: "800" },
  permBody: { color: theme.color.textMuted, fontSize: 11, marginTop: 2, lineHeight: 15 },
  permOnCard: { flexDirection: "row", alignItems: "center", gap: 8, padding: 10, marginTop: 4, borderRadius: 10, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  permOnT: { color: theme.color.green, fontSize: 11, fontWeight: "800" },
  row: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  rowInline: { flexDirection: "row", gap: 10 },
  rowLabel: { color: theme.color.text, fontSize: 13, fontWeight: "700" },
  rowDesc: { color: theme.color.textMuted, fontSize: 11, marginTop: 2, lineHeight: 15 },
  sect: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 2, marginTop: 20, marginBottom: 8 },
  timeInput: { marginTop: 6, padding: 10, borderRadius: 8, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, color: theme.color.text, fontSize: 14, fontWeight: "700" },
});
