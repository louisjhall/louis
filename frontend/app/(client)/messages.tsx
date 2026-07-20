/**
 * Messages screen — Louis-branded client chat with rich attachments
 * (images, videos, voice notes) and a role-aware header. The coach view
 * shows a "Replying as Louis" badge; the client view shows Louis's avatar
 * and the attachment-aware composer.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput, ActivityIndicator, Alert,
  KeyboardAvoidingView, Platform, FlatList, Linking,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import { api } from "@/src/lib/api";
import { useAuth } from "@/src/lib/auth";
import { theme } from "@/src/lib/theme";
import { LOUIS } from "@/src/lib/coachProfile";
import { LouisAvatar } from "@/src/components/LouisAvatar";
import { AttachmentPickerSheet, PickedFile } from "@/src/components/AttachmentPickerSheet";
import { VoiceRecorderOverlay, RecordedVoiceNote } from "@/src/components/VoiceRecorderOverlay";
import { MessageAttachmentBubble } from "@/src/components/MessageAttachmentBubble";
import {
  uploadAttachment, deleteAttachment, MessageAttachment, AttachmentKind,
} from "@/src/lib/messageAttachments";

type QueueItem = {
  key: string;
  kind: AttachmentKind;
  localUri: string;
  mimeType: string;
  durationSeconds?: number;
  progress: number;
  status: "uploading" | "uploaded" | "failed";
  attachment?: MessageAttachment;
  error?: string;
};

export default function Messages() {
  const { user } = useAuth();
  const isClient = user?.role === "client";
  const [partners, setPartners] = useState<any[]>([]);
  const [active, setActive] = useState<any>(null);
  const [thread, setThread] = useState<any[]>([]);
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  // Slice 2: adapt UI copy to the client's assigned coach (defaults to Louis).
  const [coachName, setCoachName] = useState<string>(LOUIS.displayName);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await api<any>(`/me/coach`);
        if (cancelled) return;
        const n = r?.coach?.first_name || r?.coach?.name;
        if (n) setCoachName(n);
      } catch {}
    })();
    return () => { cancelled = true; };
  }, []);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [voiceOpen, setVoiceOpen] = useState(false);
  const listRef = useRef<FlatList<any>>(null);

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
    setTimeout(() => listRef.current?.scrollToEnd({ animated: false }), 50);
  }, [active]);

  useFocusEffect(useCallback(() => { loadPartners(); }, [loadPartners]));
  useEffect(() => { loadThread(); }, [active, loadThread]);

  const enqueueUploads = async (files: PickedFile[]) => {
    // Guard: no more than 5 images per composed message.
    const existingImages = queue.filter((q) => q.kind === "image").length;
    const existingVideos = queue.filter((q) => q.kind === "video").length;
    const existingVoice = queue.filter((q) => q.kind === "voice").length;

    for (const f of files) {
      if (f.kind === "image" && existingImages + queue.filter((q) => q.kind === "image").length >= 5) {
        Alert.alert("Attachment limit", "You can attach up to 5 images per message.");
        return;
      }
      if (f.kind === "video" && (existingVideos > 0 || queue.some((q) => q.kind === "video"))) {
        Alert.alert("Attachment limit", "You can attach one video per message.");
        return;
      }
      if (f.kind === "voice" && (existingVoice > 0 || queue.some((q) => q.kind === "voice"))) {
        Alert.alert("Attachment limit", "You can attach one voice note per message.");
        return;
      }
      const key = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      setQueue((q) => [...q, {
        key, kind: f.kind, localUri: f.uri, mimeType: f.mimeType,
        durationSeconds: f.durationSeconds, progress: 0, status: "uploading",
      }]);
      // Fire the upload in the background — the composer stays interactive.
      doUpload(key, f);
    }
  };

  const doUpload = async (key: string, file: PickedFile | RecordedVoiceNote & { kind: AttachmentKind, mimeType: string }) => {
    try {
      const uploaded = await uploadAttachment({
        uri: file.uri,
        kind: (file as any).kind,
        mimeType: file.mimeType,
        durationSeconds: (file as any).durationSeconds,
        onProgress: (pct) => {
          setQueue((q) => q.map((it) => (it.key === key ? { ...it, progress: pct } : it)));
        },
      });
      setQueue((q) =>
        q.map((it) => (it.key === key ? { ...it, status: "uploaded", progress: 100, attachment: uploaded } : it)),
      );
    } catch (e: any) {
      setQueue((q) => q.map((it) => (it.key === key ? { ...it, status: "failed", error: e?.message || "Upload failed" } : it)));
    }
  };

  const retry = (item: QueueItem) => {
    setQueue((q) => q.map((it) => (it.key === item.key ? { ...it, status: "uploading", progress: 0, error: undefined } : it)));
    doUpload(item.key, {
      uri: item.localUri, kind: item.kind, mimeType: item.mimeType,
      durationSeconds: item.durationSeconds,
    } as any);
  };

  const removeQueued = async (item: QueueItem) => {
    setQueue((q) => q.filter((it) => it.key !== item.key));
    if (item.attachment?.id) await deleteAttachment(item.attachment.id);
  };

  const send = async () => {
    if (sending || !active) return;
    const anyUploading = queue.some((it) => it.status === "uploading");
    if (anyUploading) { Alert.alert("Please wait", "Attachments are still uploading."); return; }
    const failed = queue.filter((it) => it.status === "failed");
    if (failed.length > 0) { Alert.alert("Fix failed uploads", "Retry or remove the failed attachments first."); return; }
    if (!text.trim() && queue.length === 0) return;

    setSending(true);
    const t = text.trim();
    const attachment_ids = queue.map((it) => it.attachment!.id).filter(Boolean);
    setText("");
    setQueue([]);

    try {
      const m = await api<any>("/messages", {
        method: "POST",
        body: { to_user_id: active.id, text: t, attachment_ids },
      });
      setThread((prev) => [...prev, m]);
      setTimeout(() => listRef.current?.scrollToEnd({ animated: true }), 80);
    } catch (e: any) {
      Alert.alert("Couldn’t send", e?.message || "Please try again.");
    } finally {
      setSending(false);
    }
  };

  const onVoiceRecorded = async (note: RecordedVoiceNote) => {
    setVoiceOpen(false);
    const key = `${Date.now()}-v`;
    setQueue((q) => [...q, {
      key, kind: "voice", localUri: note.uri, mimeType: note.mimeType,
      durationSeconds: note.durationSeconds, progress: 0, status: "uploading",
    }]);
    doUpload(key, { ...note, kind: "voice" });
  };

  const openReport = () => {
    Alert.alert(
      "Report a problem",
      "Send Louis a note about an issue in the app, an abusive message, or anything unsafe.",
      [
        { text: "Email Louis", onPress: () => Linking.openURL(`mailto:${LOUIS.email}?subject=CrewFit%20support`) },
        { text: "Support inbox", onPress: () => Linking.openURL("mailto:support@crewfit.net?subject=CrewFit%20support") },
        { text: "Cancel", style: "cancel" },
      ],
    );
  };

  const composerPlaceholder = useMemo(
    () => (isClient
      ? `Message ${coachName} or attach a voice note, image or video…`
      : "Reply to your client…"),
    [isClient, coachName],
  );

  const renderClientHeader = () => (
    <View style={styles.clientHeader}>
      <LouisAvatar size={52} showRing />
      <View style={{ flex: 1 }}>
        <View style={styles.headerTitleRow}>
          <Text style={styles.clientHeaderTitle}>Message {coachName}</Text>
          <View style={styles.onlineDot} />
        </View>
        <Text style={styles.clientHeaderSubtitle}>Your CrewFit coach · replies personally</Text>
      </View>
      <Pressable onPress={openReport} hitSlop={12} testID="msg-report">
        <Ionicons name="flag-outline" size={20} color={theme.color.textMuted} />
      </Pressable>
    </View>
  );

  const renderCoachHeader = () => (
    <View style={styles.coachHeader}>
      <View>
        <Text style={styles.title}>MESSAGES</Text>
        <View style={styles.replyingAsRow}>
          <LouisAvatar size={22} />
          <Text style={styles.replyingAsText}>
            Replying as <Text style={styles.replyingAsName}>{coachName}</Text>
          </Text>
        </View>
      </View>
    </View>
  );

  const renderClientEmpty = () => (
    <View style={styles.emptyWrap} testID="messages-empty-client">
      <LouisAvatar size={84} showRing />
      <Text style={styles.emptyTitle}>Message {coachName} Directly</Text>
      <Text style={styles.emptyCopy}>
        Ask Louis about your workouts, roster, nutrition or recovery. You can also
        send voice notes, videos or images if something is easier to show than explain.
      </Text>
      <Pressable
        testID="messages-empty-cta"
        onPress={() => setText(`Hi ${coachName}, `)}
        style={styles.emptyBtn}
      >
        <Ionicons name="paper-plane" size={14} color="#fff" />
        <Text style={styles.emptyBtnText}>SEND {coachName.toUpperCase()} A MESSAGE</Text>
      </Pressable>
    </View>
  );

  const renderQueue = () => {
    if (queue.length === 0) return null;
    return (
      <View style={styles.queueRow}>
        {queue.map((it) => (
          <View key={it.key} style={styles.queueItem} testID={`queue-${it.kind}-${it.status}`}>
            <View style={styles.queueIcon}>
              <Ionicons
                name={it.kind === "image" ? "image" : it.kind === "video" ? "videocam" : "mic"}
                size={16}
                color={theme.color.brand}
              />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.queueLabel}>
                {it.kind === "image" ? "Image" : it.kind === "video" ? "Video" : "Voice note"}
                {it.durationSeconds ? ` · ${Math.round(it.durationSeconds)}s` : ""}
              </Text>
              {it.status === "uploading" && (
                <View style={styles.progressBar}>
                  <View style={[styles.progressFill, { width: `${it.progress}%` }]} />
                </View>
              )}
              {it.status === "failed" && (
                <Text style={styles.queueError} numberOfLines={1}>{it.error || "Upload failed"}</Text>
              )}
              {it.status === "uploaded" && (
                <Text style={styles.queueReady}>Ready to send</Text>
              )}
            </View>
            {it.status === "failed" && (
              <Pressable onPress={() => retry(it)} testID={`queue-retry-${it.key}`}>
                <Ionicons name="refresh" size={18} color={theme.color.brand} />
              </Pressable>
            )}
            <Pressable onPress={() => removeQueued(it)} testID={`queue-remove-${it.key}`}>
              <Ionicons name="close-circle" size={20} color={theme.color.textDim} />
            </Pressable>
          </View>
        ))}
      </View>
    );
  };

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
            ref={listRef}
            data={thread}
            keyExtractor={(m) => m.id}
            contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 20 }}
            renderItem={({ item }) => {
              const mine = item.from_user_id === user?.id;
              const showLouisMeta = isClient && !mine;
              const attachments = (item.attachments || []) as any[];
              return (
                <View style={[styles.bubbleWrap, mine ? styles.mineWrap : styles.theirsWrap]}>
                  {showLouisMeta && (
                    <View style={styles.louisMeta}>
                      <LouisAvatar size={26} />
                    </View>
                  )}
                  <View style={{ flexShrink: 1, alignItems: mine ? "flex-end" : "flex-start" }}>
                    {showLouisMeta && (
                      <View style={styles.louisLabelRow}>
                        <Text style={styles.louisLabel}>{coachName}</Text>
                        <Text style={styles.louisRole}> · {LOUIS.title}</Text>
                      </View>
                    )}
                    {!!item.text && (
                      <View style={[styles.bubble, mine ? styles.mine : styles.theirs]}>
                        <Text style={[styles.bubbleText, mine && { color: "#fff" }]}>{item.text}</Text>
                      </View>
                    )}
                    {attachments.map((a) => (
                      <MessageAttachmentBubble key={a.id} att={a} mine={mine} />
                    ))}
                  </View>
                </View>
              );
            }}
            ListEmptyComponent={
              isClient ? (
                <View style={styles.threadPrompt}>
                  <Text style={styles.threadPromptTitle}>Say hi to {coachName}</Text>
                  <Text style={styles.threadPromptCopy}>
                    Tell him a bit about your goals, current roster, or anything you’d like
                    his eyes on this week.
                  </Text>
                </View>
              ) : (
                <Text style={styles.empty}>No messages yet.</Text>
              )
            }
          />

          <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} keyboardVerticalOffset={90}>
            {renderQueue()}
            <View style={styles.composer}>
              <Pressable
                testID="msg-attach"
                style={styles.iconBtn}
                onPress={() => setPickerOpen(true)}
                hitSlop={8}
              >
                <Ionicons name="add" size={22} color={theme.color.brand} />
              </Pressable>
              <TextInput
                testID="msg-input"
                style={styles.input}
                value={text}
                onChangeText={setText}
                placeholder={composerPlaceholder}
                placeholderTextColor={theme.color.textDim}
                multiline
              />
              <Pressable
                testID="msg-voice"
                style={styles.iconBtn}
                onPress={() => setVoiceOpen(true)}
                hitSlop={8}
              >
                <Ionicons name="mic" size={22} color={theme.color.brand} />
              </Pressable>
              <Pressable
                testID="msg-send"
                onPress={send}
                style={[styles.sendBtn, sending && { opacity: 0.6 }]}
                disabled={sending}
              >
                {sending ? <ActivityIndicator color="#fff" /> : <Ionicons name="arrow-up" color="#fff" size={20} />}
              </Pressable>
            </View>
            {isClient && (
              <Text style={styles.footerNote}>
                Louis will review your message and reply as soon as possible.
              </Text>
            )}
          </KeyboardAvoidingView>
        </>
      )}

      <AttachmentPickerSheet
        visible={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onPicked={(files) => enqueueUploads(files)}
        onVoiceRequested={() => setVoiceOpen(true)}
      />
      <VoiceRecorderOverlay
        visible={voiceOpen}
        onCancel={() => setVoiceOpen(false)}
        onSend={onVoiceRecorded}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  coachHeader: { paddingHorizontal: theme.space.lg, paddingTop: theme.space.lg, paddingBottom: theme.space.md, borderBottomWidth: 1, borderBottomColor: theme.color.divider, gap: 8 },
  title: { color: theme.color.text, fontSize: 20, letterSpacing: 2, fontWeight: "900" },
  replyingAsRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 4 },
  replyingAsText: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700", letterSpacing: 1 },
  replyingAsName: { color: theme.color.brand, fontWeight: "900" },
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
  bubble: { maxWidth: 300, padding: 12, borderRadius: theme.radius.md },
  mine: { backgroundColor: theme.color.brand },
  theirs: { backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  bubbleText: { color: theme.color.text, fontSize: 14, lineHeight: 20 },
  // Queue
  queueRow: {
    paddingHorizontal: theme.space.md, paddingTop: theme.space.sm, paddingBottom: 4,
    gap: 6, backgroundColor: theme.color.surface, borderTopWidth: 1, borderTopColor: theme.color.divider,
  },
  queueItem: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: theme.color.surface2, borderRadius: 10, paddingHorizontal: 10, paddingVertical: 8,
    borderWidth: 1, borderColor: theme.color.border,
  },
  queueIcon: {
    width: 30, height: 30, borderRadius: 8, backgroundColor: theme.color.brandTint,
    alignItems: "center", justifyContent: "center",
  },
  queueLabel: { color: theme.color.text, fontWeight: "700", fontSize: 12 },
  queueReady: { color: theme.color.green || "#22c55e", fontSize: 10, fontWeight: "700", marginTop: 2 },
  queueError: { color: theme.color.brand, fontSize: 10, fontWeight: "700", marginTop: 2 },
  progressBar: { height: 3, backgroundColor: theme.color.border, borderRadius: 2, marginTop: 6, overflow: "hidden" },
  progressFill: { height: 3, backgroundColor: theme.color.brand },
  // Composer
  composer: { flexDirection: "row", gap: 6, padding: theme.space.md, borderTopWidth: 1, borderTopColor: theme.color.divider, backgroundColor: theme.color.surface, alignItems: "flex-end" },
  iconBtn: {
    width: 40, height: 40, borderRadius: 20, backgroundColor: theme.color.surface2,
    alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: theme.color.border,
  },
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
