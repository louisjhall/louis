/**
 * Coach Message Draft Review screen.
 * Louis reviews Atlas's drafted reply. He can Edit, ask for Shorter/Warmer/Clearer,
 * Send, or Dismiss. Atlas NEVER auto-sends.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput,
  ActivityIndicator, KeyboardAvoidingView, Platform, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Draft = {
  id: string;
  client_id: string;
  client_name?: string;
  atlas_draft: string;
  coach_edited_text?: string | null;
  risk_level: "low" | "medium" | "high";
  risk_reason?: string;
  action_hint?: string;
  tone_used?: string;
  status: string;
  source_message_text?: string | null;
  source_message_at?: string | null;
  summary?: string;
};

type ThreadMsg = { id: string; from_user_id: string; to_user_id: string; text: string; created_at: string };

const RISK_STYLES: Record<string, { color: string; label: string }> = {
  high:   { color: "#c94a4a", label: "HIGH RISK · ESCALATE" },
  medium: { color: theme.color.amber, label: "REVIEW NEEDED" },
  low:    { color: theme.color.green, label: "ROUTINE" },
};

export default function DraftReview() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<null | "shorter" | "warmer" | "clearer" | "send" | "dismiss">(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [thread, setThread] = useState<ThreadMsg[]>([]);
  const [text, setText] = useState("");
  const [edited, setEdited] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<{ draft: Draft; thread: ThreadMsg[] }>(`/coach/messages/drafts/${id}`);
      setDraft(r.draft);
      setThread(r.thread || []);
      setText(r.draft.coach_edited_text ?? r.draft.atlas_draft ?? "");
      setEdited(!!r.draft.coach_edited_text);
    } catch (e: any) {
      Alert.alert("Couldn't load draft", e?.message || "Unknown error");
    } finally { setLoading(false); }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const regen = async (tone: "shorter" | "warmer" | "clearer") => {
    if (!draft) return;
    setBusy(tone);
    try {
      const r = await api<{ draft: Draft }>(`/coach/messages/${draft.id}/regenerate`, {
        method: "POST", body: { tone },
      });
      setDraft(r.draft);
      setText(r.draft.atlas_draft);
      setEdited(false);
    } catch (e: any) {
      Alert.alert("Regenerate failed", e?.message || "Unknown error");
    } finally { setBusy(null); }
  };

  const saveEdit = async () => {
    if (!draft) return;
    await api(`/coach/messages/${draft.id}`, { method: "PATCH", body: { coach_edited_text: text } });
    setEdited(true);
  };

  const send = async () => {
    if (!draft) return;
    if (!text.trim()) { Alert.alert("Empty message"); return; }
    setBusy("send");
    try {
      await api(`/coach/messages/${draft.id}/approve`, { method: "POST", body: { coach_edited_text: text } });
      router.back();
    } catch (e: any) {
      Alert.alert("Send failed", e?.message || "Unknown error");
    } finally { setBusy(null); }
  };

  const dismiss = async () => {
    if (!draft) return;
    setBusy("dismiss");
    try {
      await api(`/coach/messages/${draft.id}/dismiss`, { method: "POST" });
      router.back();
    } catch (e: any) {
      Alert.alert("Dismiss failed", e?.message || "Unknown error");
    } finally { setBusy(null); }
  };

  const riskStyle = useMemo(() => draft ? (RISK_STYLES[draft.risk_level] || RISK_STYLES.medium) : RISK_STYLES.medium, [draft]);

  if (loading || !draft) {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: theme.color.surface }}>
        <ActivityIndicator color={theme.color.brand} />
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={8}>
          <Ionicons name="chevron-back" size={26} color={theme.color.text} />
        </Pressable>
        <Text style={styles.headerT}>REPLY DRAFT</Text>
        <View style={{ width: 26 }} />
      </View>

      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 140 }}>
          <Text style={styles.clientName}>{draft.client_name}</Text>

          <View style={[styles.riskPill, { backgroundColor: riskStyle.color }]}>
            <Text style={styles.riskPillT}>{riskStyle.label}</Text>
          </View>
          {draft.risk_reason ? <Text style={styles.riskReason}>{draft.risk_reason}</Text> : null}

          {draft.source_message_text ? (
            <View style={styles.originalCard}>
              <Text style={styles.originalHead}>CLIENT WROTE</Text>
              <Text style={styles.originalText}>{draft.source_message_text}</Text>
            </View>
          ) : null}

          <Text style={styles.sect}>ATLAS DRAFT</Text>
          <TextInput
            testID="draft-editor"
            style={styles.editor}
            value={text}
            onChangeText={(t) => { setText(t); setEdited(true); }}
            onBlur={() => { if (edited) saveEdit().catch(() => null); }}
            multiline
            placeholder="Atlas hasn't drafted yet…"
            placeholderTextColor={theme.color.textDim}
          />
          {edited ? <Text style={styles.editedNote}>Edited — will send your version.</Text> : null}

          <Text style={styles.sect}>ADJUST TONE</Text>
          <View style={styles.toneRow}>
            <ToneBtn label="SHORTER" icon="contract" onPress={() => regen("shorter")} busy={busy === "shorter"} />
            <ToneBtn label="WARMER" icon="heart" onPress={() => regen("warmer")} busy={busy === "warmer"} />
            <ToneBtn label="CLEARER" icon="sparkles" onPress={() => regen("clearer")} busy={busy === "clearer"} />
          </View>

          {thread.length > 0 ? (
            <>
              <Text style={styles.sect}>THREAD HISTORY</Text>
              <View style={styles.threadWrap}>
                {thread.slice(-8).map((m) => (
                  <View key={m.id} style={[styles.threadRow, m.from_user_id === draft.client_id ? styles.rowClient : styles.rowCoach]}>
                    <Text style={styles.threadWho}>{m.from_user_id === draft.client_id ? "CLIENT" : "COACH"}</Text>
                    <Text style={styles.threadText}>{m.text}</Text>
                  </View>
                ))}
              </View>
            </>
          ) : null}
        </ScrollView>

        <View style={styles.actionBar}>
          <Pressable testID="draft-dismiss" onPress={dismiss} disabled={!!busy} style={[styles.dismissBtn, busy && { opacity: 0.5 }]}>
            <Ionicons name="close" size={16} color={theme.color.textMuted} />
            <Text style={styles.dismissT}>DISMISS</Text>
          </Pressable>
          <Pressable testID="draft-send" onPress={send} disabled={!!busy} style={[styles.sendBtn, busy && { opacity: 0.5 }]}>
            {busy === "send" ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <>
                <Ionicons name="paper-plane" size={16} color="#fff" />
                <Text style={styles.sendT}>APPROVE &amp; SEND</Text>
              </>
            )}
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function ToneBtn({ label, icon, onPress, busy }: any) {
  return (
    <Pressable testID={`tone-${label.toLowerCase()}`} onPress={onPress} disabled={busy} style={[styles.toneBtn, busy && { opacity: 0.5 }]}>
      {busy ? <ActivityIndicator size="small" color={theme.color.brand} /> : <Ionicons name={icon} size={14} color={theme.color.brand} />}
      <Text style={styles.toneT}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  headerT: { color: theme.color.text, fontSize: 14, letterSpacing: 2, fontWeight: "900" },
  clientName: { color: theme.color.text, fontSize: 22, fontWeight: "900" },
  riskPill: { alignSelf: "flex-start", marginTop: 10, paddingHorizontal: 10, paddingVertical: 4, borderRadius: 4 },
  riskPillT: { color: "#fff", fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },
  riskReason: { color: theme.color.textMuted, fontSize: 12, marginTop: 6, fontStyle: "italic" },
  originalCard: { marginTop: 18, padding: 14, backgroundColor: theme.color.surface2, borderRadius: 10, borderWidth: 1, borderColor: theme.color.border, borderLeftWidth: 3, borderLeftColor: theme.color.textDim },
  originalHead: { color: theme.color.textDim, fontSize: 9, fontWeight: "800", letterSpacing: 1.5, marginBottom: 6 },
  originalText: { color: theme.color.text, fontSize: 14, lineHeight: 20 },
  sect: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 2, marginTop: 22, marginBottom: 8 },
  editor: { minHeight: 130, backgroundColor: theme.color.surface2, borderRadius: 10, padding: 14, color: theme.color.text, fontSize: 14, lineHeight: 20, borderWidth: 1, borderColor: theme.color.border, textAlignVertical: "top" },
  editedNote: { color: theme.color.amber, fontSize: 11, marginTop: 6, fontWeight: "700" },
  toneRow: { flexDirection: "row", gap: 8 },
  toneBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: 12, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.brand, borderRadius: 8 },
  toneT: { color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 1.5 },
  threadWrap: { gap: 8 },
  threadRow: { padding: 10, backgroundColor: theme.color.surface2, borderRadius: 8, borderWidth: 1, borderColor: theme.color.border },
  rowClient: { borderLeftWidth: 3, borderLeftColor: theme.color.brand },
  rowCoach: { borderLeftWidth: 3, borderLeftColor: theme.color.textDim },
  threadWho: { color: theme.color.textDim, fontSize: 9, fontWeight: "800", letterSpacing: 1.5, marginBottom: 3 },
  threadText: { color: theme.color.text, fontSize: 13 },
  actionBar: { position: "absolute", left: 0, right: 0, bottom: 0, flexDirection: "row", gap: 10, padding: 14, backgroundColor: theme.color.surface, borderTopWidth: 1, borderTopColor: theme.color.divider },
  dismissBtn: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 16, paddingVertical: 14, backgroundColor: theme.color.surface2, borderRadius: 10, borderWidth: 1, borderColor: theme.color.border },
  dismissT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "800", letterSpacing: 1.5 },
  sendBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingVertical: 14, backgroundColor: theme.color.brand, borderRadius: 10 },
  sendT: { color: "#fff", fontSize: 13, fontWeight: "900", letterSpacing: 1.5 },
});
