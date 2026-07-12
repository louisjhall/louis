/**
 * Messages screen \u2014 shared between client + coach roles, but the visible
 * copy, avatars and empty state are role-aware so that clients feel like
 * they are messaging Louis directly. Coach view says "Replying as Louis"
 * to make it obvious clients see messages under his name.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput, ActivityIndicator,
  KeyboardAvoidingView, Platform, FlatList,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import { api } from "@/src/lib/api";
import { useAuth } from "@/src/lib/auth";
import { theme } from "@/src/lib/theme";
import { LOUIS } from "@/src/lib/coachProfile";
import { LouisAvatar } from "@/src/components/LouisAvatar";

export default function Messages() {
  const { user } = useAuth();
  const isClient = user?.role === "client";
  const [partners, setPartners] = useState<any[]>([]);
  const [active, setActive] = useState<any>(null);
  const [thread, setThread] = useState<any[]>([]);
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(true);

  const loadPartners = useCallback(async () => {
    setLoading(true);
    try {
      const p = await api<any[]>("/messages");
      setPartners(p);
      if (p[0] && !active) setActive(p[0]);
    } finally { setLoading(false); }
  }, [active]);

  const loadThread = useCallback(async () => {
    if (!active) return;
    const t = await api<any[]>(`/messages/${active.id}`);
    setThread(t);
  }, [active]);

  useFocusEffect(useCallback(() => { loadPartners(); }, [loadPartners]));
  useEffect(() => { loadThread(); }, [active, loadThread]);

  const send = async () => {
    if (!text.trim() || !active) return;
    const t = text.trim();
    setText("");
    const m = await api<any>("/messages", { method: "POST", body: { to_user_id: active.id, text: t } });
    setThread((prev) => [...prev, m]);
  };

  const composerPlaceholder = useMemo(
    () => (isClient
      ? `Message ${LOUIS.displayName} about your training, roster, nutrition or recovery\u2026`
      : "Reply to your client\u2026"),
    [isClient],
  );

  // Client header shows Louis identity even before partners load.
  const renderClientHeader = () => (
    <View style={styles.clientHeader}>
      <LouisAvatar size={52} showRing />
      <View style={{ flex: 1 }}>
        <View style={styles.headerTitleRow}>
          <Text style={styles.clientHeaderTitle}>Message {LOUIS.displayName}</Text>
          <View style={styles.onlineDot} />
        </View>
        <Text style={styles.clientHeaderSubtitle}>Your CrewFit coach \u00b7 replies personally</Text>
      </View>
    </View>
  );

  const renderCoachHeader = () => (
    <View style={styles.coachHeader}>
      <View>
        <Text style={styles.title}>MESSAGES</Text>
        <View style={styles.replyingAsRow}>
          <LouisAvatar size={22} />
          <Text style={styles.replyingAsText}>
            Replying as <Text style={styles.replyingAsName}>{LOUIS.displayName}</Text>
          </Text>
        </View>
      </View>
    </View>
  );

  // Client empty state \u2014 premium, Louis-branded.
  const renderClientEmpty = () => (
    <View style={styles.emptyWrap} testID="messages-empty-client">
      <LouisAvatar size={84} showRing />
      <Text style={styles.emptyTitle}>Message {LOUIS.displayName} Directly</Text>
      <Text style={styles.emptyCopy}>
        Ask {LOUIS.displayName} about your workouts, roster, nutrition, recovery or
        anything you\u2019re unsure about inside CrewFit. He\u2019ll review your
        message and reply as soon as possible.
      </Text>
      <Pressable
        testID="messages-empty-cta"
        onPress={() => {
          // Seed a soft opener so the composer becomes usable even before
          // partners load \u2014 in practice the client always has Louis as their
          // assigned coach so `active` will populate on next tick.
          setText(`Hi ${LOUIS.displayName}, `);
        }}
        style={styles.emptyBtn}
      >
        <Ionicons name="paper-plane" size={14} color="#fff" />
        <Text style={styles.emptyBtnText}>SEND {LOUIS.displayName.toUpperCase()} A MESSAGE</Text>
      </Pressable>
    </View>
  );

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      {isClient ? renderClientHeader() : renderCoachHeader()}

      {loading ? (
        <ActivityIndicator color={theme.color.brand} style={{ marginTop: 40 }} />
      ) : partners.length === 0 ? (
        isClient ? renderClientEmpty() : (
          <Text style={styles.empty}>No conversations yet.</Text>
        )
      ) : (
        <>
          {/* Coach view keeps the partner switcher; client only ever has Louis. */}
          {!isClient && (
            <View style={styles.partnersRow}>
              {partners.map((p) => (
                <Pressable
                  key={p.id}
                  testID={`partner-${p.id}`}
                  onPress={() => setActive(p)}
                  style={[styles.pChip, active?.id === p.id && styles.pChipActive]}
                >
                  <Text style={[styles.pChipText, active?.id === p.id && { color: "#fff" }]}>
                    {p.name}
                  </Text>
                </Pressable>
              ))}
            </View>
          )}

          <FlatList
            data={thread}
            keyExtractor={(m) => m.id}
            contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 20 }}
            renderItem={({ item }) => {
              const mine = item.from_user_id === user?.id;
              // From-Louis bubble on the client's screen \u2014 show avatar + label.
              const showLouisMeta = isClient && !mine;
              return (
                <View style={[styles.bubbleWrap, mine ? styles.mineWrap : styles.theirsWrap]}>
                  {showLouisMeta && (
                    <View style={styles.louisMeta}>
                      <LouisAvatar size={26} />
                    </View>
                  )}
                  <View style={{ flexShrink: 1 }}>
                    {showLouisMeta && (
                      <View style={styles.louisLabelRow}>
                        <Text style={styles.louisLabel}>{LOUIS.displayName}</Text>
                        <Text style={styles.louisRole}> \u00b7 {LOUIS.title}</Text>
                      </View>
                    )}
                    <View style={[styles.bubble, mine ? styles.mine : styles.theirs]}>
                      <Text style={[styles.bubbleText, mine && { color: "#fff" }]}>{item.text}</Text>
                    </View>
                  </View>
                </View>
              );
            }}
            ListEmptyComponent={
              isClient ? (
                <View style={styles.threadPrompt}>
                  <Text style={styles.threadPromptTitle}>Say hi to {LOUIS.displayName}</Text>
                  <Text style={styles.threadPromptCopy}>
                    Tell him a bit about your goals, current roster, or anything you\u2019d like
                    his eyes on this week.
                  </Text>
                </View>
              ) : (
                <Text style={styles.empty}>No messages yet.</Text>
              )
            }
          />

          <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} keyboardVerticalOffset={90}>
            <View style={styles.composer}>
              <TextInput
                testID="msg-input"
                style={styles.input}
                value={text}
                onChangeText={setText}
                placeholder={composerPlaceholder}
                placeholderTextColor={theme.color.textDim}
                multiline
              />
              <Pressable testID="msg-send" onPress={send} style={styles.sendBtn}>
                <Ionicons name="arrow-up" color="#fff" size={20} />
              </Pressable>
            </View>
            {isClient && (
              <Text style={styles.footerNote}>
                {LOUIS.displayName} will review your message and reply as soon as possible.
              </Text>
            )}
          </KeyboardAvoidingView>
        </>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  // Legacy coach header
  coachHeader: { paddingHorizontal: theme.space.lg, paddingTop: theme.space.lg, paddingBottom: theme.space.md, borderBottomWidth: 1, borderBottomColor: theme.color.divider, gap: 8 },
  title: { color: theme.color.text, fontSize: 20, letterSpacing: 2, fontWeight: "900" },
  replyingAsRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 4 },
  replyingAsText: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700", letterSpacing: 1 },
  replyingAsName: { color: theme.color.brand, fontWeight: "900" },
  // Premium client header
  clientHeader: {
    flexDirection: "row", alignItems: "center", gap: 14,
    paddingHorizontal: theme.space.lg, paddingTop: theme.space.md, paddingBottom: theme.space.md,
    borderBottomWidth: 1, borderBottomColor: theme.color.divider,
    backgroundColor: theme.color.surface,
  },
  headerTitleRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  clientHeaderTitle: { color: theme.color.text, fontSize: 20, fontWeight: "900", letterSpacing: 0.3 },
  onlineDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: theme.color.green || "#22c55e" },
  clientHeaderSubtitle: { color: theme.color.textMuted, fontSize: 12, marginTop: 3, fontWeight: "600" },
  // Bubbles
  empty: { color: theme.color.textMuted, textAlign: "center", marginTop: 40 },
  partnersRow: { flexDirection: "row", gap: 8, padding: theme.space.lg, paddingBottom: theme.space.sm },
  pChip: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: theme.radius.pill, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  pChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  pChipText: { color: theme.color.textMuted, fontWeight: "700", fontSize: 12 },
  bubbleWrap: { marginBottom: 14, flexDirection: "row", gap: 8 },
  mineWrap: { justifyContent: "flex-end" },
  theirsWrap: { justifyContent: "flex-start" },
  louisMeta: { paddingTop: 18 },
  louisLabelRow: { flexDirection: "row", alignItems: "baseline", marginBottom: 4 },
  louisLabel: { color: theme.color.text, fontWeight: "800", fontSize: 12 },
  louisRole: { color: theme.color.textDim, fontSize: 10, fontWeight: "600" },
  bubble: { maxWidth: 320, padding: 12, borderRadius: theme.radius.md },
  mine: { backgroundColor: theme.color.brand },
  theirs: { backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  bubbleText: { color: theme.color.text, fontSize: 14, lineHeight: 20 },
  // Composer + footer
  composer: { flexDirection: "row", gap: 8, padding: theme.space.md, borderTopWidth: 1, borderTopColor: theme.color.divider, backgroundColor: theme.color.surface, alignItems: "flex-end" },
  input: { flex: 1, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, padding: theme.space.md, color: theme.color.text, borderWidth: 1, borderColor: theme.color.border, maxHeight: 120 },
  sendBtn: { backgroundColor: theme.color.brand, width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center" },
  footerNote: { color: theme.color.textDim, fontSize: 11, textAlign: "center", paddingHorizontal: theme.space.lg, paddingBottom: 10, paddingTop: 2 },
  // Empty state
  emptyWrap: { flex: 1, alignItems: "center", justifyContent: "center", paddingHorizontal: theme.space.lg, gap: 14, paddingBottom: 60 },
  emptyTitle: { color: theme.color.text, fontSize: 22, fontWeight: "900", textAlign: "center", marginTop: 4 },
  emptyCopy: { color: theme.color.textMuted, fontSize: 14, lineHeight: 22, textAlign: "center", maxWidth: 320 },
  emptyBtn: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: theme.color.brand, paddingHorizontal: 18, paddingVertical: 12, borderRadius: theme.radius.pill, marginTop: 8 },
  emptyBtnText: { color: "#fff", fontWeight: "900", fontSize: 12, letterSpacing: 1.4 },
  threadPrompt: { padding: theme.space.md, alignItems: "center", gap: 6 },
  threadPromptTitle: { color: theme.color.text, fontSize: 15, fontWeight: "800" },
  threadPromptCopy: { color: theme.color.textMuted, fontSize: 12, textAlign: "center", lineHeight: 18 },
});
