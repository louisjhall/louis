/**
 * Coach — Check-in review screen.
 * Shows Atlas summary + editable weekly video script + a Send Video action
 * (MVP records via a small textarea "mark as recorded"; teleprompter camera
 * recording is deferred to the next session).
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator, Alert,
} from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

export default function CoachCheckinReview() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [ci, setCi] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [script, setScript] = useState("");
  const [saving, setSaving] = useState(false);
  const [sending, setSending] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api<any>(`/coach/checkins/${id}`);
      setCi(r.check_in);
      setScript(r.check_in?.weekly_video_script || "");
    } catch (e: any) {
      Alert.alert("Could not load", e?.message || "");
    } finally { setLoading(false); }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const saveScript = async () => {
    setSaving(true);
    try {
      await api<any>(`/coach/checkins/${id}/script`, { method: "PUT", body: { weekly_video_script: script } });
    } catch (e: any) { Alert.alert("Save failed", e?.message || ""); } finally { setSaving(false); }
  };

  const createDraftAndSend = async () => {
    if (!script.trim()) { Alert.alert("Script required", "Write or edit the script first."); return; }
    setSending(true);
    try {
      // Save script first
      await api<any>(`/coach/checkins/${id}/script`, { method: "PUT", body: { weekly_video_script: script } });
      // MVP: create video metadata WITHOUT file (teleprompter recording next session)
      const v = await api<any>("/coach/videos", { method: "POST", body: {
        check_in_id: id, user_id: ci.user_id, script,
      }});
      // Send it
      await api<any>(`/coach/videos/${v.video.id}/send`, { method: "POST", body: {} });
      Alert.alert("Sent", `Weekly video record delivered to ${ci.user_name}. (Teleprompter recording coming next session — this MVP sends the script as an in-app message.)`);
      router.back();
    } catch (e: any) {
      Alert.alert("Send failed", e?.message || "");
    } finally { setSending(false); }
  };

  if (loading || !ci) {
    return (<SafeAreaView style={styles.root}><View style={styles.centre}><ActivityIndicator color={theme.color.brand} /></View></SafeAreaView>);
  }

  const summary = ci.atlas_coach_summary || {};
  const adjustments = ci.suggested_programme_adjustments || [];

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <View style={styles.topBar}>
        <Pressable onPress={() => router.back()} hitSlop={12}><Ionicons name="close" size={26} color={theme.color.text} /></Pressable>
        <View style={{ flex: 1, marginLeft: 12 }}>
          <Text style={styles.header}>{ci.user_name}</Text>
          <Text style={styles.headerSub}>Week {ci.week_start} — {ci.week_end}</Text>
        </View>
        {ci.urgent_safety_flag && (
          <View style={styles.urgent}><Text style={styles.urgentT}>URGENT</Text></View>
        )}
      </View>

      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 40 }}>
        {/* Atlas Coach Summary */}
        <View style={styles.block}>
          <Text style={styles.blockH}>ATLAS COACH SUMMARY</Text>
          {(["adherence_note","recovery_note","sleep_note","stress_note","nutrition_note","roster_note","motivation_note","suggested_focus_next_week"] as const).map((k) => (
            summary[k] ? (
              <View key={k} style={styles.summaryLine}>
                <Text style={styles.summaryKey}>{k.replace(/_/g, " ").toUpperCase()}</Text>
                <Text style={styles.summaryV}>{summary[k]}</Text>
              </View>
            ) : null
          ))}
          {summary.coach_review_required && (
            <View style={styles.reviewFlag}>
              <Ionicons name="warning" size={14} color="#c94a4a" />
              <Text style={styles.reviewFlagT}>REVIEW BEFORE PROGRESSING · {summary.reasoning_for_review || "Coach attention required"}</Text>
            </View>
          )}
        </View>

        {/* Suggested Adjustments */}
        {adjustments.length > 0 && (
          <View style={styles.block}>
            <Text style={styles.blockH}>SUGGESTED PROGRAMME CHANGES</Text>
            {adjustments.map((a: any, i: number) => (
              <View key={i} style={styles.adjustCard}>
                <Text style={styles.adjustArea}>{String(a.area || "").toUpperCase()}</Text>
                <Text style={styles.adjustChange}>{a.change}</Text>
                {a.rationale && <Text style={styles.adjustReason}>{a.rationale}</Text>}
              </View>
            ))}
          </View>
        )}

        {/* Answers */}
        <View style={styles.block}>
          <Text style={styles.blockH}>CLIENT ANSWERS</Text>
          {Object.entries(ci.answers || {}).map(([k, v]) => (
            <View key={k} style={styles.answerLine}>
              <Text style={styles.answerKey}>{k.replace(/_/g, " ")}</Text>
              <Text style={styles.answerV}>{String(v)}</Text>
            </View>
          ))}
        </View>

        {/* Editable Script */}
        <View style={styles.block}>
          <Text style={styles.blockH}>WEEKLY VIDEO SCRIPT</Text>
          <Text style={styles.hint}>Edit before recording. This is what you&apos;ll read on camera.</Text>
          <TextInput
            value={script}
            onChangeText={setScript}
            multiline
            style={styles.scriptInput}
            placeholder="Atlas will generate a script here after the client submits."
            placeholderTextColor={theme.color.textDim}
          />
          <View style={styles.scriptActions}>
            <Pressable onPress={saveScript} disabled={saving} style={styles.saveBtn}>
              {saving ? <ActivityIndicator color={theme.color.brand} size="small" /> : <Ionicons name="save" size={14} color={theme.color.brand} />}
              <Text style={styles.saveBtnT}>SAVE DRAFT</Text>
            </Pressable>
          </View>
        </View>

        {/* Send video / Teleprompter */}
        <View style={{ flexDirection: "row", gap: 10, marginTop: 8 }}>
          <Pressable
            onPress={() => router.push(`/coach/teleprompter/${id}` as any)}
            disabled={!script.trim()}
            style={[styles.sendBtn, !script.trim() && { opacity: 0.35 }, { flex: 1 }]}
            testID="open-teleprompter"
          >
            <Ionicons name="videocam" size={16} color="#fff" />
            <Text style={styles.sendBtnT}>RECORD VIDEO</Text>
          </Pressable>
          <Pressable
            onPress={createDraftAndSend}
            disabled={sending || !script.trim()}
            style={[styles.saveBtn, (sending || !script.trim()) && { opacity: 0.35 }, { flex: 1, paddingVertical: 16, borderRadius: 12 }]}
            testID="send-weekly-video"
          >
            {sending ? <ActivityIndicator color={theme.color.brand} /> : <Ionicons name="send" size={14} color={theme.color.brand} />}
            <Text style={styles.saveBtnT}>{sending ? "SENDING…" : "SEND TEXT ONLY"}</Text>
          </Pressable>
        </View>
        <Text style={styles.footHint}>
          RECORD VIDEO opens the teleprompter with your live camera. SEND TEXT ONLY delivers the script as a written coaching touchpoint.
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  centre: { flex: 1, alignItems: "center", justifyContent: "center" },
  topBar: { flexDirection: "row", alignItems: "center", padding: 16, borderBottomWidth: 1, borderBottomColor: theme.color.divider, gap: 12 },
  header: { color: theme.color.text, fontSize: 15, fontWeight: "900" },
  headerSub: { color: theme.color.textMuted, fontSize: 10, marginTop: 2, letterSpacing: 1 },
  urgent: { backgroundColor: "#c94a4a", paddingHorizontal: 8, paddingVertical: 4, borderRadius: 4 },
  urgentT: { color: "#fff", fontSize: 9, fontWeight: "900", letterSpacing: 1 },
  block: { padding: 14, marginBottom: 14, borderRadius: 12, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  blockH: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 2, marginBottom: 10 },
  hint: { color: theme.color.textMuted, fontSize: 11, fontStyle: "italic", marginBottom: 8 },
  summaryLine: { marginBottom: 8 },
  summaryKey: { color: theme.color.textDim, fontSize: 9, fontWeight: "900", letterSpacing: 1.2 },
  summaryV: { color: theme.color.text, fontSize: 13, lineHeight: 18, marginTop: 3 },
  reviewFlag: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 10, padding: 10, borderRadius: 8, backgroundColor: "rgba(201, 74, 74, 0.1)", borderWidth: 1, borderColor: "#c94a4a" },
  reviewFlagT: { color: "#c94a4a", fontSize: 11, fontWeight: "800", flex: 1 },
  adjustCard: { padding: 10, borderRadius: 8, backgroundColor: theme.color.surface3, borderLeftWidth: 3, borderLeftColor: theme.color.brand, marginBottom: 8 },
  adjustArea: { color: theme.color.brand, fontSize: 9, fontWeight: "900", letterSpacing: 1.5 },
  adjustChange: { color: theme.color.text, fontSize: 13, fontWeight: "700", marginTop: 4 },
  adjustReason: { color: theme.color.textMuted, fontSize: 11, marginTop: 4, fontStyle: "italic" },
  answerLine: { flexDirection: "row", gap: 8, marginBottom: 6 },
  answerKey: { color: theme.color.textDim, fontSize: 11, minWidth: 100, textTransform: "capitalize" },
  answerV: { color: theme.color.text, fontSize: 12, flex: 1 },
  scriptInput: { minHeight: 160, backgroundColor: theme.color.surface3, borderWidth: 1, borderColor: theme.color.border, borderRadius: 8, padding: 12, color: theme.color.text, fontSize: 14, lineHeight: 20, textAlignVertical: "top" },
  scriptActions: { flexDirection: "row", gap: 8, marginTop: 10 },
  saveBtn: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand },
  saveBtnT: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },
  sendBtn: { marginTop: 8, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, padding: 16, borderRadius: 12, backgroundColor: theme.color.brand },
  sendBtnT: { color: "#fff", fontSize: 13, fontWeight: "900", letterSpacing: 2 },
  footHint: { color: theme.color.textMuted, fontSize: 10, textAlign: "center", marginTop: 10, fontStyle: "italic", lineHeight: 14 },
});
