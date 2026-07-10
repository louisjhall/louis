import { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator, RefreshControl,
} from "react-native";
import * as Clipboard from "expo-clipboard";
import { useLocalSearchParams, useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

const STYLES = ["professional", "friendly", "high_performance", "military", "encouraging", "direct", "humorous"];

export default function ClientScripts() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [client, setClient] = useState<any>(null);
  const [scripts, setScripts] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [style, setStyle] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [active, setActive] = useState<any>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [detail, list] = await Promise.all([
        api<any>(`/coach/clients/${id}`),
        api<any[]>(`/coach/scripts?client_id=${id}`),
      ]);
      setClient(detail.client);
      setScripts(list);
      if (list[0]) setActive(list[0]);
    } finally { setLoading(false); }
  }, [id]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const generate = async () => {
    setBusy(true); setErr(null);
    try {
      const s = await api<any>("/coach/scripts/generate", {
        method: "POST", body: { client_id: id, style: style || undefined },
      });
      setActive(s);
      await load();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  const save = async (patch: any) => {
    if (!active) return;
    setBusy(true);
    try {
      const s = await api<any>(`/coach/scripts/${active.id}`, { method: "PATCH", body: patch });
      setActive(s);
      await load();
    } finally { setBusy(false); }
  };

  const approveAndSend = async () => save({ approved: true, script: active.script });

  const copy = async (text: string) => { await Clipboard.setStringAsync(text); };

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()}><Ionicons name="chevron-back" size={26} color={theme.color.text} /></Pressable>
        <Text style={styles.title}>WEEKLY SCRIPT</Text>
        <View style={{ width: 26 }} />
      </View>
      <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 140 }} refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}>
        {client && (
          <View style={styles.clientPill}>
            <Text style={styles.clientName}>{client.name}</Text>
            <Text style={styles.clientEmail}>{client.email}</Text>
          </View>
        )}

        <Text style={styles.sect}>COACH STYLE</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipsScroll}>
          {STYLES.map((s) => (
            <Pressable key={s} testID={`style-${s}`} onPress={() => setStyle(s)} style={[styles.chip, style === s && styles.chipActive]}>
              <Text style={[styles.chipText, style === s && { color: "#fff" }]}>{s.replace("_", " ")}</Text>
            </Pressable>
          ))}
        </ScrollView>

        <Pressable testID="script-generate" onPress={generate} disabled={busy} style={[styles.generateBtn, busy && { opacity: 0.6 }]}>
          {busy ? <ActivityIndicator color="#fff" /> : (
            <><Ionicons name="sparkles" size={16} color="#fff" /><Text style={styles.generateText}>  GENERATE NEW SCRIPT</Text></>
          )}
        </Pressable>

        {err && <Text style={{ color: theme.color.red, marginTop: 10 }}>{err}</Text>}

        {active ? (
          <>
            <Text style={styles.sect}>SCRIPT · {active.style?.toUpperCase()}  <Text style={styles.est}>· ~{Math.max(40, Math.min(120, Math.round((active.script?.split(" ").length || 0) / 2.4)))}s</Text></Text>
            <TextInput
              testID="script-text"
              style={styles.scriptInput}
              multiline
              value={active.script}
              onChangeText={(t) => setActive({ ...active, script: t })}
              placeholderTextColor={theme.color.textDim}
            />
            <View style={styles.actionsRow}>
              <Pressable testID="script-copy" onPress={() => copy(active.script)} style={styles.smallBtn}>
                <Ionicons name="copy" size={14} color={theme.color.brand} />
                <Text style={styles.smallBtnText}>COPY</Text>
              </Pressable>
              <Pressable testID="script-save-edits" onPress={() => save({ script: active.script })} disabled={busy} style={styles.smallBtn}>
                <Ionicons name="save" size={14} color={theme.color.brand} />
                <Text style={styles.smallBtnText}>SAVE EDIT</Text>
              </Pressable>
            </View>

            <Text style={styles.sect}>COACH SUMMARY</Text>
            <View style={styles.summaryBox}>
              {(active.summary_bullets || []).map((b: string, i: number) => (
                <View key={i} style={styles.bulletRow}>
                  <Text style={styles.bulletDot}>•</Text>
                  <Text style={styles.bulletText}>{b}</Text>
                </View>
              ))}
            </View>

            <Text style={styles.sect}>WHATSAPP VERSION</Text>
            <View style={styles.softBox}>
              <Text style={styles.softText}>{active.whatsapp}</Text>
              <Pressable testID="wa-copy" onPress={() => copy(active.whatsapp)} style={styles.softBtn}>
                <Ionicons name="copy" size={12} color={theme.color.brand} />
                <Text style={styles.softBtnText}>COPY</Text>
              </Pressable>
            </View>

            <Text style={styles.sect}>PUSH NOTIFICATION</Text>
            <View style={styles.softBox}>
              <Text style={styles.softText}>{active.push_text}</Text>
              <Pressable testID="push-copy" onPress={() => copy(active.push_text)} style={styles.softBtn}>
                <Ionicons name="copy" size={12} color={theme.color.brand} />
                <Text style={styles.softBtnText}>COPY</Text>
              </Pressable>
            </View>

            {scripts.length > 1 && (
              <>
                <Text style={styles.sect}>PREVIOUS SCRIPTS</Text>
                {scripts.slice(1, 6).map((s) => (
                  <Pressable key={s.id} testID={`prev-${s.id}`} onPress={() => setActive(s)} style={styles.prevRow}>
                    <Text style={styles.prevDate}>{new Date(s.created_at).toDateString()}</Text>
                    <Text style={styles.prevSnip} numberOfLines={1}>{s.script}</Text>
                    {s.sent_at && <Ionicons name="checkmark-circle" size={14} color={theme.color.green} />}
                  </Pressable>
                ))}
              </>
            )}
          </>
        ) : loading ? (
          <ActivityIndicator color={theme.color.brand} style={{ marginTop: 40 }} />
        ) : (
          <View style={styles.empty}>
            <Ionicons name="videocam" size={40} color={theme.color.brand} />
            <Text style={styles.emptyTitle}>No script yet</Text>
            <Text style={styles.emptySub}>Tap Generate to create a personalised weekly script.</Text>
          </View>
        )}
      </ScrollView>

      {active && (
        <View style={styles.sticky}>
          <Pressable testID="script-approve" onPress={approveAndSend} disabled={busy || active.sent_at} style={[styles.cta, (busy || active.sent_at) && { opacity: 0.6 }, active.sent_at && { backgroundColor: theme.color.green }]}>
            {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.ctaText}>{active.sent_at ? "SENT" : "APPROVE · RECORD · SEND"}</Text>}
          </Pressable>
        </View>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  title: { color: theme.color.text, fontSize: 15, letterSpacing: 2, fontWeight: "900" },
  clientPill: { padding: theme.space.md, borderRadius: theme.radius.md, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, marginBottom: theme.space.md },
  clientName: { color: theme.color.text, fontSize: 16, fontWeight: "800" },
  clientEmail: { color: theme.color.textMuted, fontSize: 12, marginTop: 2 },
  sect: { color: theme.color.textMuted, letterSpacing: 2, fontSize: 10, fontWeight: "800", marginTop: theme.space.lg, marginBottom: theme.space.sm },
  est: { color: theme.color.brand, fontWeight: "700", fontSize: 10 },
  chipsScroll: { gap: 6, paddingBottom: 4 },
  chip: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: theme.radius.pill, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, flexShrink: 0 },
  chipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipText: { color: theme.color.textMuted, fontSize: 10, fontWeight: "800", letterSpacing: 1 },
  generateBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", backgroundColor: theme.color.brand, padding: 14, borderRadius: theme.radius.md, marginTop: theme.space.md },
  generateText: { color: "#fff", fontWeight: "800", letterSpacing: 2, fontSize: 12 },
  scriptInput: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, padding: theme.space.md, color: theme.color.text, fontSize: 14, minHeight: 200, textAlignVertical: "top" },
  actionsRow: { flexDirection: "row", gap: 8, marginTop: 8 },
  smallBtn: { flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 8, paddingHorizontal: 12, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.brand },
  smallBtnText: { color: theme.color.brand, fontSize: 10, letterSpacing: 1.5, fontWeight: "800" },
  summaryBox: { padding: theme.space.md, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border },
  bulletRow: { flexDirection: "row", marginBottom: 4 },
  bulletDot: { color: theme.color.brand, fontSize: 14, width: 14, fontWeight: "900" },
  bulletText: { color: theme.color.text, fontSize: 13, flex: 1, lineHeight: 18 },
  softBox: { padding: theme.space.md, backgroundColor: theme.color.brandTint, borderRadius: theme.radius.md, borderLeftWidth: 3, borderLeftColor: theme.color.brand },
  softText: { color: theme.color.text, fontSize: 13, lineHeight: 19 },
  softBtn: { flexDirection: "row", alignItems: "center", gap: 4, alignSelf: "flex-start", marginTop: 6, paddingVertical: 4, paddingHorizontal: 8, borderRadius: theme.radius.sm, backgroundColor: theme.color.surface2 },
  softBtnText: { color: theme.color.brand, fontSize: 9, letterSpacing: 1, fontWeight: "800" },
  prevRow: { flexDirection: "row", alignItems: "center", gap: 8, padding: theme.space.md, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, marginBottom: theme.space.sm },
  prevDate: { color: theme.color.textDim, fontSize: 10, letterSpacing: 1, fontWeight: "700" },
  prevSnip: { flex: 1, color: theme.color.textMuted, fontSize: 12 },
  empty: { alignItems: "center", padding: theme.space.xxl, borderWidth: 1, borderColor: theme.color.border, borderRadius: theme.radius.md, backgroundColor: theme.color.surface2, marginTop: theme.space.md },
  emptyTitle: { color: theme.color.text, marginTop: theme.space.md, fontWeight: "800" },
  emptySub: { color: theme.color.textMuted, marginTop: 4, textAlign: "center" },
  sticky: { position: "absolute", left: 0, right: 0, bottom: 0, padding: theme.space.lg, backgroundColor: theme.color.surface, borderTopWidth: 1, borderTopColor: theme.color.border },
  cta: { backgroundColor: theme.color.brand, paddingVertical: 16, borderRadius: theme.radius.md, alignItems: "center" },
  ctaText: { color: "#fff", fontWeight: "800", letterSpacing: 2, fontSize: 13 },
});
