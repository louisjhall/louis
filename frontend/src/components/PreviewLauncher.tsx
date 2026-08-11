/**
 * PreviewLauncher — shown on the coach Overview page. Offers the 3 preview
 * modes: demo aviation client, real client by picker, and new-client
 * onboarding flow.
 *
 * PreviewClientButton — the small inline button used on each row of the
 * coach Clients list.
 */
import React, { useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator, Modal, TextInput, ScrollView, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { usePreview } from "@/src/lib/preview";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

export function PreviewLauncher() {
  const { enterDemo, enterSandbox, resetSandbox } = usePreview();
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);

  const doDemo = async () => {
    setBusy("demo");
    try {
      await enterDemo();
      router.replace("/(client)/home" as any);
    } catch (e: any) {
      Alert.alert("Preview failed", e?.message || "Try again.");
    } finally { setBusy(null); }
  };

  const doNewClient = async () => {
    setBusy("new");
    try {
      await enterSandbox();
      router.replace("/" as any);
    } catch (e: any) {
      Alert.alert("Preview failed", e?.message || "Try again.");
    } finally { setBusy(null); }
  };

  const doResetAndStart = async () => {
    setBusy("reset");
    try {
      await resetSandbox();
      await enterSandbox();
      router.replace("/" as any);
    } catch (e: any) {
      Alert.alert("Reset failed", e?.message || "Try again.");
    } finally { setBusy(null); }
  };

  return (
    <View style={styles.wrap}>
      <View style={styles.header}>
        <Ionicons name="eye" size={16} color={theme.color.brand} />
        <Text style={styles.title}>PREVIEW CLIENT APP</Text>
      </View>
      <Text style={styles.sub}>See exactly what a client sees. Sandbox writes are isolated — real client data is never touched.</Text>

      <View style={styles.grid}>
        <Pressable style={styles.tile} onPress={doDemo} disabled={busy !== null} testID="preview-launch-demo">
          {busy === "demo" ? <ActivityIndicator color={theme.color.brand} /> : <Ionicons name="airplane" size={22} color={theme.color.brand} />}
          <Text style={styles.tileT}>DEMO PILOT</Text>
          <Text style={styles.tileS}>Seeded BA long-haul crew with roster + habits + nutrition.</Text>
        </Pressable>

        <Pressable style={styles.tile} onPress={() => setPickerOpen(true)} disabled={busy !== null} testID="preview-launch-real">
          <Ionicons name="person" size={22} color={theme.color.brand} />
          <Text style={styles.tileT}>REAL CLIENT</Text>
          <Text style={styles.tileS}>Pick any of your clients and view their app.</Text>
        </Pressable>

        <Pressable style={styles.tile} onPress={doNewClient} disabled={busy !== null} testID="preview-launch-new">
          {busy === "new" ? <ActivityIndicator color={theme.color.brand} /> : <Ionicons name="person-add" size={22} color={theme.color.brand} />}
          <Text style={styles.tileT}>NEW CLIENT PREVIEW</Text>
          <Text style={styles.tileS}>Persistent sandbox — resettable, isolated from real clients.</Text>
        </Pressable>

        <Pressable style={[styles.tile, styles.tileAlt]} onPress={doResetAndStart} disabled={busy !== null} testID="preview-reset-and-start">
          {busy === "reset" ? <ActivityIndicator color={theme.color.brand} /> : <Ionicons name="refresh-circle" size={22} color={theme.color.brand} />}
          <Text style={styles.tileT}>RESET & START FRESH</Text>
          <Text style={styles.tileS}>Wipe sandbox data + start the journey from step 1.</Text>
        </Pressable>
      </View>

      {pickerOpen ? <RealClientPicker onClose={() => setPickerOpen(false)} /> : null}
    </View>
  );
}

export function PreviewClientButton({ clientId, clientName }: { clientId: string; clientName: string }) {
  const { enterReal } = usePreview();
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  const go = async (e: any) => {
    // Stop the parent Pressable from also navigating to /coach/client/[id].
    e?.stopPropagation?.();
    setBusy(true);
    try {
      await enterReal(clientId);
      router.replace("/(client)/home" as any);
    } catch (err: any) {
      Alert.alert("Preview failed", err?.message || "Try again.");
    } finally { setBusy(false); }
  };

  return (
    <Pressable onPress={go} disabled={busy} style={styles.rowBtn} testID={`preview-real-${clientId}`}>
      {busy ? <ActivityIndicator size="small" color={theme.color.brand} /> : (
        <>
          <Ionicons name="eye-outline" size={12} color={theme.color.brand} />
          <Text style={styles.rowBtnT}>PREVIEW</Text>
        </>
      )}
    </Pressable>
  );
}

function RealClientPicker({ onClose }: { onClose: () => void }) {
  const { enterReal } = usePreview();
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [clients, setClients] = useState<any[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  React.useEffect(() => {
    (async () => {
      try {
        const r = await api<{ clients: any[] }>("/coach/dashboard");
        setClients(r.clients || []);
      } catch { setClients([]); }
    })();
  }, []);

  const filtered = (clients || []).filter((c) => {
    if (!query.trim()) return true;
    const q = query.trim().toLowerCase();
    return (c.name || "").toLowerCase().includes(q) || (c.email || "").toLowerCase().includes(q);
  });

  const choose = async (id: string) => {
    setBusy(id);
    try {
      await enterReal(id);
      onClose();
      router.replace("/(client)/home" as any);
    } catch (e: any) {
      Alert.alert("Preview failed", e?.message || "Try again.");
    } finally { setBusy(null); }
  };

  return (
    <Modal transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.picker}>
          <View style={styles.pickerHead}>
            <Text style={styles.pickerTitle}>Pick a client to preview</Text>
            <Pressable onPress={onClose} testID="preview-picker-close">
              <Ionicons name="close" size={20} color={theme.color.textMuted} />
            </Pressable>
          </View>
          <TextInput
            value={query}
            onChangeText={setQuery}
            placeholder="Search name or email"
            placeholderTextColor={theme.color.textDim}
            style={styles.pickerInput}
            testID="preview-picker-search"
          />
          {clients === null ? (
            <ActivityIndicator color={theme.color.brand} style={{ marginTop: 40 }} />
          ) : filtered.length === 0 ? (
            <Text style={styles.emptyT}>No clients found.</Text>
          ) : (
            <ScrollView style={{ maxHeight: 400 }}>
              {filtered.map((c) => (
                <Pressable key={c.id} onPress={() => choose(c.id)} disabled={busy === c.id} style={styles.pickerRow} testID={`preview-picker-${c.id}`}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.pickerName}>{c.name}</Text>
                    <Text style={styles.pickerEmail}>{c.email}</Text>
                  </View>
                  {busy === c.id ? <ActivityIndicator color={theme.color.brand} /> : <Ionicons name="chevron-forward" size={16} color={theme.color.textMuted} />}
                </Pressable>
              ))}
            </ScrollView>
          )}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  wrap: { backgroundColor: theme.color.surface2, borderRadius: 12, padding: 16, marginBottom: 20, borderWidth: 1, borderColor: theme.color.border },
  header: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 6 },
  title: { color: theme.color.text, fontSize: 12, fontWeight: "800", letterSpacing: 2 },
  sub: { color: theme.color.textMuted, fontSize: 12, marginBottom: 14 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  tile: { flex: 1, minWidth: 140, backgroundColor: theme.color.surface, borderRadius: 10, padding: 12, borderWidth: 1, borderColor: theme.color.border },
  tileAlt: { borderColor: theme.color.brand, backgroundColor: theme.color.brandTint },
  tileT: { color: theme.color.text, fontSize: 12, fontWeight: "800", letterSpacing: 1, marginTop: 6, marginBottom: 4 },
  tileS: { color: theme.color.textMuted, fontSize: 11, lineHeight: 15 },
  rowBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 4, borderWidth: 1, borderColor: theme.color.brand },
  rowBtnT: { color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 0.6 },
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.7)", padding: 16, justifyContent: "center", alignItems: "center" },
  picker: { backgroundColor: theme.color.surface, borderRadius: 12, padding: 16, borderWidth: 1, borderColor: theme.color.border, width: "100%", maxWidth: 520 },
  pickerHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 12 },
  pickerTitle: { color: theme.color.text, fontSize: 14, fontWeight: "800", letterSpacing: 1 },
  pickerInput: { color: theme.color.text, backgroundColor: theme.color.surface2, borderRadius: 8, padding: 10, borderWidth: 1, borderColor: theme.color.border, marginBottom: 10 },
  pickerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 12, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  pickerName: { color: theme.color.text, fontSize: 14, fontWeight: "700" },
  pickerEmail: { color: theme.color.textDim, fontSize: 12 },
  emptyT: { color: theme.color.textDim, fontSize: 13, textAlign: "center", padding: 30 },
});
