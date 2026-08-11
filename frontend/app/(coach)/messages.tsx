/**
 * Iter 129d — Coach Messages workspace (3-panel redesign).
 *
 *   ┌─────────────────┬───────────────────────────────┬─────────────────┐
 *   │ CONVERSATIONS   │ ACTIVE CONVERSATION           │ CLIENT CONTEXT  │
 *   │ search + list   │ header + thread + composer    │ identity + …    │
 *   └─────────────────┴───────────────────────────────┴─────────────────┘
 *
 * Reuses existing messaging backend:
 *   GET  /coach/inbox                (Iter 129d aggregator — hides test accounts)
 *   GET  /coach/client-context/{id}  (Iter 129d — right-panel bundle)
 *   GET  /messages/{other_id}        (existing thread endpoint)
 *   POST /messages                   (existing send endpoint)
 *   POST /messages/attachments       (existing image/video upload endpoint)
 *
 * No new messaging schema. Voice recording intentionally omitted from the
 * redesign per spec §12 (removed rather than left as a dead control).
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput, ScrollView, Image, ActivityIndicator,
  useWindowDimensions, KeyboardAvoidingView, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import * as ImagePicker from "expo-image-picker";
import Constants from "expo-constants";
import { api, getToken } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast } from "@/src/lib/ux";
import { MessageAttachmentBubble } from "@/src/components/MessageAttachmentBubble";

/* -------------------------------------------------------------------------- */
/*  Types                                                                      */
/* -------------------------------------------------------------------------- */

type Conversation = {
  id: string;
  name: string;
  avatar_url?: string | null;
  initials: string;
  subtype?: string | null;
  latest?: { text: string; at: string; from_me: boolean } | null;
  unread_count: number;
  // Iter 165b · Backend now returns a per-client pending check-in flag so
  // the coach can see at-a-glance which threads have a submitted check-in
  // waiting for review. Sources: coach_tasks (task_type=check_in_review),
  // check_ins (coach_review_status=pending), reality_events (ask_coach).
  pending_checkin?: boolean;
  pending_checkin_count?: number;
  pending_checkin_source?: "coach_task" | "check_in" | "reality_event" | null;
};

type ThreadMessage = {
  id: string;
  from_user_id: string;
  to_user_id: string;
  text?: string;
  created_at: string;
  read?: boolean;
  attachments?: Array<{
    id: string; kind: "image" | "video" | "voice";
    url?: string; preview_url?: string;
    mime?: string; duration_seconds?: number;
  }>;
};

type ClientContext = {
  identity: { id: string; name: string; initials: string; avatar_url?: string; subtype?: string | null; email?: string };
  goal?: string | null;
  phase?: string | null;
  plan_state?: string | null;
  next_session?: { date: string; label: string } | null;
  latest_checkin?: { week_start: string; state: string } | null;
  pinned_notes?: { text: string; updated_at?: string } | null;
};

/* -------------------------------------------------------------------------- */
/*  Helpers                                                                    */
/* -------------------------------------------------------------------------- */

function relTime(iso?: string): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const diff = Date.now() - t;
  if (diff < 60_000) return "just now";
  const min = Math.floor(diff / 60_000);
  if (min < 60) return `${min}m`;
  const h = Math.floor(min / 60);
  if (h < 24) return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const d = Math.floor(h / 24);
  if (d < 7) return `${d}d`;
  return new Date(iso).toLocaleDateString([], { day: "numeric", month: "short" });
}

function bubbleTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function daySeparator(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const yest = new Date(today.getTime() - 24 * 60 * 60 * 1000);
  const m = new Date(d); m.setHours(0, 0, 0, 0);
  if (m.getTime() === today.getTime()) return "Today";
  if (m.getTime() === yest.getTime()) return "Yesterday";
  return d.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" });
}

/* -------------------------------------------------------------------------- */
/*  Avatar                                                                     */
/* -------------------------------------------------------------------------- */

function Avatar({
  name, initials, url, size = 40,
}: { name?: string; initials?: string; url?: string | null; size?: number }) {
  const s = { width: size, height: size, borderRadius: size / 2 };
  if (url) return <Image source={{ uri: url }} style={[styles.avatarBase, s]} />;
  const label = initials || (name || "?").split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
  return (
    <View style={[styles.avatarBase, s, { backgroundColor: theme.color.surface3, borderColor: theme.color.border, alignItems: "center", justifyContent: "center" }]}>
      <Text style={{ color: theme.color.text, fontWeight: "900", fontSize: Math.max(11, size * 0.36) }}>{label}</Text>
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/*  Screen                                                                     */
/* -------------------------------------------------------------------------- */

export default function CoachMessagesScreen() {
  const router = useRouter();
  const { width } = useWindowDimensions();
  const isDesktop = width >= 1100;
  const isMedium = width >= 800 && width < 1100;

  const [convs, setConvs] = useState<Conversation[]>([]);
  const [loadingConvs, setLoadingConvs] = useState(true);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [thread, setThread] = useState<ThreadMessage[]>([]);
  const [loadingThread, setLoadingThread] = useState(false);
  const [context, setContext] = useState<ClientContext | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | "unread">("all");
  const [composer, setComposer] = useState("");
  const [pendingAttachmentIds, setPendingAttachmentIds] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const [sending, setSending] = useState(false);
  const [me, setMe] = useState<{ id: string } | null>(null);
  const scrollRef = useRef<ScrollView | null>(null);

  const loadConvs = useCallback(async () => {
    setLoadingConvs(true);
    try {
      const r = await api<{ conversations: Conversation[] }>("/coach/inbox");
      setConvs(r.conversations || []);
      // If no active yet, pick the top row (unread first)
      if (!activeId && r.conversations?.[0]) setActiveId(r.conversations[0].id);
    } finally {
      setLoadingConvs(false);
    }
  }, [activeId]);

  const loadThread = useCallback(async (cid: string) => {
    setLoadingThread(true);
    try {
      const rows = await api<ThreadMessage[]>(`/messages/${cid}`);
      setThread(Array.isArray(rows) ? rows : []);
      setTimeout(() => scrollRef.current?.scrollToEnd({ animated: false }), 80);
      // Refresh inbox to update unread counts (thread endpoint marks read)
      loadConvs();
    } finally {
      setLoadingThread(false);
    }
  }, [loadConvs]);

  const loadContext = useCallback(async (cid: string) => {
    try {
      const c = await api<ClientContext>(`/coach/client-context/${cid}`);
      setContext(c);
    } catch {
      setContext(null);
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const u = await api<{ id: string }>("/me");
        setMe(u);
      } catch { /* ignore */ }
    })();
    loadConvs();
  }, [loadConvs]);

  useEffect(() => {
    if (!activeId) return;
    loadThread(activeId);
    loadContext(activeId);
  }, [activeId, loadThread, loadContext]);

  /* Filtered conversation list ------------------------------------------- */
  const filteredConvs = useMemo(() => {
    let list = convs;
    if (filter === "unread") list = list.filter((c) => c.unread_count > 0);
    const q = query.trim().toLowerCase();
    if (q) {
      list = list.filter((c) =>
        c.name.toLowerCase().includes(q) ||
        (c.latest?.text || "").toLowerCase().includes(q),
      );
    }
    return list;
  }, [convs, filter, query]);

  const activeConv = useMemo(
    () => convs.find((c) => c.id === activeId) || null,
    [convs, activeId],
  );

  /* Composer ------------------------------------------------------------- */
  const pickAndUpload = async (kind: "image" | "video") => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) { toast("Media permission denied.", "error"); return; }
    const res = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: kind === "image" ? ImagePicker.MediaTypeOptions.Images : ImagePicker.MediaTypeOptions.Videos,
      quality: 0.7,
    });
    if (res.canceled || !res.assets?.[0]) return;
    const asset = res.assets[0];
    const uri = asset.uri;
    const mime = asset.mimeType || (kind === "image" ? "image/jpeg" : "video/mp4");

    setUploading(true);
    try {
      const backendUrl = (Constants.expoConfig?.extra?.EXPO_BACKEND_URL as string) || process.env.EXPO_BACKEND_URL || "";
      const url = `${(backendUrl || "").replace(/\/$/, "")}/api/messages/attachments`;
      const form = new FormData();
      // React Native FormData file object
      form.append("file", {
        uri,
        name: `upload.${kind === "image" ? "jpg" : "mp4"}`,
        type: mime,
      } as any);
      form.append("kind", kind);
      const token = await getToken();
      const r = await fetch(url, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
      if (!r.ok) throw new Error(`upload failed (${r.status})`);
      const j = await r.json();
      if (j.id) setPendingAttachmentIds((cur) => [...cur, j.id]);
      toast("Attached.", "success");
    } catch (e: any) {
      toast(e?.message || "Upload failed.", "error");
    } finally {
      setUploading(false);
    }
  };

  const send = async () => {
    if (!activeId) return;
    const text = composer.trim();
    if (!text && pendingAttachmentIds.length === 0) return;
    setSending(true);
    setComposer("");
    const attachment_ids = pendingAttachmentIds;
    setPendingAttachmentIds([]);
    try {
      const m = await api<ThreadMessage>("/messages", {
        method: "POST",
        body: { to_user_id: activeId, text, attachment_ids },
      });
      setThread((prev) => [...prev, m]);
      setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 80);
      loadConvs();
    } catch (e: any) {
      toast(e?.message || "Send failed.", "error");
    } finally {
      setSending(false);
    }
  };

  /* Quick actions -------------------------------------------------------- */
  const openWorkspace = (tab?: "plan" | "checkins" | "progress" | "profile") => {
    if (!activeId) return;
    const q = tab ? `?tab=${tab}` : "";
    router.push(`/coach/client/${activeId}/workspace${q}` as any);
  };

  /* Render --------------------------------------------------------------- */
  const totalUnread = convs.reduce((n, c) => n + c.unread_count, 0);
  const showRight = isDesktop; // hide right panel on medium screens per spec §28

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.pageHeader}>
        <Text style={styles.pageTitle}>
          Messages{totalUnread > 0 ? <Text style={styles.pageTitleUnread}>{`  ${totalUnread} unread`}</Text> : null}
        </Text>
      </View>

      <View style={[styles.row, !isDesktop && !isMedium && { flexDirection: "column" }]}>
        {/* -------- LEFT: CONVERSATION LIST -------- */}
        <View style={[styles.leftPanel, !isDesktop && !isMedium && styles.leftPanelMobile]}>
          <View style={styles.leftHeader}>
            <View style={styles.searchWrap}>
              <Ionicons name="search" size={14} color={theme.color.textMuted} />
              <TextInput
                value={query}
                onChangeText={setQuery}
                placeholder="Search messages…"
                placeholderTextColor={theme.color.textDim}
                style={styles.searchInput}
                testID="msg-search"
              />
            </View>
            <View style={styles.filterRow}>
              <Pressable onPress={() => setFilter("all")} style={[styles.filterBtn, filter === "all" && styles.filterBtnActive]} testID="msg-filter-all">
                <Text style={[styles.filterT, filter === "all" && styles.filterTActive]}>ALL</Text>
              </Pressable>
              <Pressable onPress={() => setFilter("unread")} style={[styles.filterBtn, filter === "unread" && styles.filterBtnActive]} testID="msg-filter-unread">
                <Text style={[styles.filterT, filter === "unread" && styles.filterTActive]}>
                  UNREAD{totalUnread > 0 ? ` · ${totalUnread}` : ""}
                </Text>
              </Pressable>
            </View>
          </View>
          <ScrollView contentContainerStyle={{ paddingBottom: 30 }}>
            {loadingConvs ? (
              <View style={{ padding: 30, alignItems: "center" }}><ActivityIndicator /></View>
            ) : filteredConvs.length === 0 ? (
              <View style={styles.emptyList}>
                <Ionicons name="chatbubbles-outline" size={30} color={theme.color.textDim} />
                <Text style={styles.emptyListT}>
                  {filter === "unread" ? "No unread messages." : "No conversations."}
                </Text>
              </View>
            ) : (
              filteredConvs.map((c) => {
                const active = c.id === activeId;
                const unread = c.unread_count > 0;
                const pendingCheckin = !!c.pending_checkin;
                return (
                  <Pressable
                    key={c.id}
                    onPress={() => setActiveId(c.id)}
                    style={[styles.convRow, active && styles.convRowActive, unread && !active && styles.convRowUnread]}
                    testID={`msg-conv-${c.id}`}
                  >
                    <View>
                      <Avatar name={c.name} initials={c.initials} url={c.avatar_url || null} size={40} />
                      {/* Iter 165b · Small red dot on the avatar when the client
                          has a pending check-in in the coach's review queue.
                          Visible even for read threads so the coach can still
                          spot outstanding reviews. */}
                      {pendingCheckin ? (
                        <View style={styles.checkinDot} testID={`msg-conv-checkin-dot-${c.id}`} />
                      ) : null}
                    </View>
                    <View style={{ flex: 1, marginLeft: 10 }}>
                      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
                        <View style={{ flexDirection: "row", alignItems: "center", flex: 1, gap: 6 }}>
                          <Text style={[styles.convName, unread && styles.convNameUnread]} numberOfLines={1}>{c.name}</Text>
                          {pendingCheckin ? (
                            <View style={styles.checkinPill} testID={`msg-conv-checkin-pill-${c.id}`}>
                              <Ionicons name="clipboard" size={9} color={theme.color.brand} />
                              <Text style={styles.checkinPillT}>CHECK-IN</Text>
                            </View>
                          ) : null}
                        </View>
                        <Text style={styles.convTime}>{relTime(c.latest?.at)}</Text>
                      </View>
                      <View style={{ flexDirection: "row", alignItems: "center", marginTop: 2 }}>
                        <Text style={[styles.convPreview, unread && styles.convPreviewUnread]} numberOfLines={1}>
                          {c.latest?.from_me ? "You: " : ""}{c.latest?.text || "No messages yet."}
                        </Text>
                        {unread ? (
                          <View style={styles.badge}>
                            <Text style={styles.badgeT}>{c.unread_count}</Text>
                          </View>
                        ) : null}
                      </View>
                    </View>
                  </Pressable>
                );
              })
            )}
          </ScrollView>
        </View>

        {/* -------- CENTRE: THREAD -------- */}
        <View style={[styles.centerPanel, !isDesktop && !isMedium && !activeId && { display: "none" }]}>
          {!activeId ? (
            <View style={styles.emptyCenter}>
              <Ionicons name="chatbubbles" size={40} color={theme.color.textDim} />
              <Text style={styles.emptyCenterT}>Select a conversation</Text>
              <Text style={styles.emptyCenterSub}>Choose a client from the inbox to view your messages.</Text>
            </View>
          ) : (
            <KeyboardAvoidingView
              style={{ flex: 1 }}
              behavior={Platform.OS === "ios" ? "padding" : undefined}
              keyboardVerticalOffset={80}
            >
              {/* Header */}
              <View style={styles.threadHeader}>
                {!isDesktop && !isMedium ? (
                  <Pressable onPress={() => setActiveId(null)} hitSlop={10} style={{ marginRight: 8 }}>
                    <Ionicons name="chevron-back" size={22} color={theme.color.text} />
                  </Pressable>
                ) : null}
                <Avatar name={activeConv?.name} initials={activeConv?.initials || ""} url={activeConv?.avatar_url || null} size={36} />
                <View style={{ flex: 1, marginLeft: 10 }}>
                  <Text style={styles.threadName} numberOfLines={1}>{activeConv?.name || "…"}</Text>
                  {activeConv?.subtype ? <Text style={styles.threadSub} numberOfLines={1}>{activeConv.subtype}</Text> : null}
                </View>
                <Pressable onPress={() => openWorkspace()} style={styles.headerBtn} testID="msg-header-view-client">
                  <Ionicons name="person" size={14} color={theme.color.brand} />
                  <Text style={styles.headerBtnT}>VIEW CLIENT</Text>
                </Pressable>
              </View>

              {/* Thread */}
              <ScrollView
                ref={scrollRef}
                style={styles.threadScroll}
                contentContainerStyle={{ padding: 12, paddingBottom: 20 }}
                onContentSizeChange={() => scrollRef.current?.scrollToEnd({ animated: false })}
              >
                {loadingThread ? (
                  <ActivityIndicator style={{ marginTop: 30 }} />
                ) : thread.length === 0 ? (
                  <View style={{ padding: 30, alignItems: "center" }}>
                    <Text style={styles.emptyThreadT}>No messages yet.</Text>
                    <Text style={styles.emptyThreadSub}>Start a conversation with {activeConv?.name}.</Text>
                  </View>
                ) : (
                  thread.map((m, i) => {
                    const isMine = me?.id ? m.from_user_id === me.id : m.from_user_id !== activeId;
                    const showDay = i === 0 || daySeparator(thread[i - 1].created_at) !== daySeparator(m.created_at);
                    return (
                      <React.Fragment key={m.id}>
                        {showDay ? (
                          <View style={styles.daySep}>
                            <View style={styles.daySepLine} />
                            <Text style={styles.daySepT}>{daySeparator(m.created_at)}</Text>
                            <View style={styles.daySepLine} />
                          </View>
                        ) : null}
                        <View style={[styles.bubbleRow, isMine ? styles.bubbleRowMine : styles.bubbleRowTheirs]}>
                          <View style={[styles.bubble, isMine ? styles.bubbleMine : styles.bubbleTheirs]}>
                            {/* Iter 165f · Delegate attachment rendering to the
                                shared <MessageAttachmentBubble /> exactly as
                                the client thread does. The previous inline
                                block gated on `att.kind === "image"` and
                                read `att.url || att.preview_url` directly,
                                which (a) uses the wrong field name for the
                                backend response (`file_url` / `storage_url`
                                shapes are handled inside the shared component)
                                and (b) hits the raw R2 path without the
                                auth-aware `getSignedUrl` fetcher the shared
                                component uses. Result: images looked broken
                                in the coach inbox even though they rendered
                                fine on the client side. */}
                            {(m.attachments || []).map((att) => (
                              <MessageAttachmentBubble
                                key={att.id}
                                att={att as any}
                                mine={isMine}
                              />
                            ))}
                            {m.text ? (
                              <Text style={[styles.bubbleText, isMine ? { color: "#fff" } : { color: theme.color.text }]}>{m.text}</Text>
                            ) : null}
                            <Text style={[styles.bubbleMeta, isMine && { color: "rgba(255,255,255,0.7)" }]}>{bubbleTime(m.created_at)}</Text>
                          </View>
                        </View>
                      </React.Fragment>
                    );
                  })
                )}
              </ScrollView>

              {/* Composer */}
              <View style={styles.composer}>
                {pendingAttachmentIds.length > 0 ? (
                  <View style={styles.attachedRow}>
                    <Ionicons name="attach" size={12} color={theme.color.brand} />
                    <Text style={styles.attachedT}>{pendingAttachmentIds.length} attachment{pendingAttachmentIds.length === 1 ? "" : "s"} ready</Text>
                    <Pressable onPress={() => setPendingAttachmentIds([])} hitSlop={8}>
                      <Ionicons name="close" size={12} color={theme.color.textMuted} />
                    </Pressable>
                  </View>
                ) : null}
                <View style={styles.composerRow}>
                  <Pressable onPress={() => pickAndUpload("image")} style={styles.iconBtn} disabled={uploading} testID="msg-attach-image">
                    <Ionicons name="image" size={18} color={theme.color.textMuted} />
                  </Pressable>
                  <Pressable onPress={() => pickAndUpload("video")} style={styles.iconBtn} disabled={uploading} testID="msg-attach-video">
                    <Ionicons name="videocam" size={18} color={theme.color.textMuted} />
                  </Pressable>
                  <TextInput
                    value={composer}
                    onChangeText={setComposer}
                    placeholder="Type a message…"
                    placeholderTextColor={theme.color.textDim}
                    style={styles.composerInput}
                    multiline
                    onSubmitEditing={send}
                    testID="msg-composer"
                  />
                  <Pressable
                    onPress={send}
                    disabled={sending || uploading || (!composer.trim() && pendingAttachmentIds.length === 0)}
                    style={[
                      styles.sendBtn,
                      (sending || uploading || (!composer.trim() && pendingAttachmentIds.length === 0)) && { opacity: 0.4 },
                    ]}
                    testID="msg-send"
                  >
                    {sending || uploading ? <ActivityIndicator color="#fff" /> : <Ionicons name="send" size={16} color="#fff" />}
                  </Pressable>
                </View>
              </View>
            </KeyboardAvoidingView>
          )}
        </View>

        {/* -------- RIGHT: CLIENT CONTEXT -------- */}
        {showRight ? (
          <View style={styles.rightPanel}>
            {!context ? (
              <View style={{ padding: 20, alignItems: "center" }}>
                <Text style={styles.emptyRightT}>Select a conversation.</Text>
              </View>
            ) : (
              <ScrollView contentContainerStyle={{ padding: 12, paddingBottom: 40 }}>
                {/* Identity card */}
                <View style={styles.identCard}>
                  <Avatar name={context.identity.name} initials={context.identity.initials} url={context.identity.avatar_url || null} size={56} />
                  <Text style={styles.identName}>{context.identity.name}</Text>
                  {context.identity.subtype ? <Text style={styles.identSub}>{context.identity.subtype}</Text> : null}
                  {(context.goal || context.phase || context.plan_state) ? (
                    <View style={styles.pillRow}>
                      {context.goal ? <View style={styles.pill}><Text style={styles.pillT}>{context.goal}</Text></View> : null}
                      {context.phase ? <View style={styles.pill}><Text style={styles.pillT}>{context.phase}</Text></View> : null}
                      {context.plan_state ? <View style={[styles.pill, context.plan_state === "Live" && styles.pillLive]}><Text style={[styles.pillT, context.plan_state === "Live" && { color: "#fff" }]}>{context.plan_state}</Text></View> : null}
                    </View>
                  ) : null}
                </View>

                {/* Next session */}
                {context.next_session ? (
                  <View style={styles.ctxCard}>
                    <Text style={styles.ctxLabel}>NEXT SESSION</Text>
                    <Text style={styles.ctxValue}>{context.next_session.label}</Text>
                    <Text style={styles.ctxMeta}>{new Date(context.next_session.date).toLocaleDateString([], { weekday: "long", day: "numeric", month: "short" })}</Text>
                  </View>
                ) : null}

                {/* Latest check-in */}
                {context.latest_checkin ? (
                  <View style={styles.ctxCard}>
                    <Text style={styles.ctxLabel}>LATEST CHECK-IN</Text>
                    <Text style={styles.ctxValue}>{context.latest_checkin.state}</Text>
                    <Text style={styles.ctxMeta}>week of {context.latest_checkin.week_start}</Text>
                  </View>
                ) : null}

                {/* Pinned notes */}
                {context.pinned_notes?.text ? (
                  <View style={styles.ctxCard}>
                    <Text style={styles.ctxLabel}>PINNED NOTES</Text>
                    <Text style={styles.ctxNote}>{context.pinned_notes.text}</Text>
                  </View>
                ) : null}

                {/* Quick actions */}
                <Text style={[styles.ctxLabel, { marginTop: 18 }]}>QUICK ACTIONS</Text>
                <QuickAction icon="clipboard-outline" label="View Plan" onPress={() => openWorkspace("plan")} />
                <QuickAction icon="checkbox-outline" label="Open Check-in" onPress={() => openWorkspace("checkins")} />
                <QuickAction icon="trending-up-outline" label="View Progress" onPress={() => openWorkspace("progress")} />
                <QuickAction icon="person-outline" label="Open Profile" onPress={() => openWorkspace("profile")} />
              </ScrollView>
            )}
          </View>
        ) : null}
      </View>
    </SafeAreaView>
  );
}

function QuickAction({ icon, label, onPress }: { icon: any; label: string; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={styles.qa} testID={`msg-qa-${label.toLowerCase().replace(/\s+/g, "-")}`}>
      <Ionicons name={icon} size={15} color={theme.color.brand} />
      <Text style={styles.qaT}>{label}</Text>
      <Ionicons name="chevron-forward" size={12} color={theme.color.textMuted} />
    </Pressable>
  );
}

/* -------------------------------------------------------------------------- */
/*  Styles                                                                     */
/* -------------------------------------------------------------------------- */

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.color.bg },

  pageHeader: {
    paddingHorizontal: theme.space.lg, paddingVertical: 10,
    borderBottomWidth: 1, borderBottomColor: theme.color.divider,
  },
  pageTitle: { color: theme.color.text, fontSize: 18, fontWeight: "900" },
  pageTitleUnread: { color: theme.color.brand, fontSize: 12, fontWeight: "800", letterSpacing: 0.8 },

  row: { flex: 1, flexDirection: "row" },

  /* Left panel */
  leftPanel: {
    width: 320,
    borderRightWidth: 1, borderRightColor: theme.color.divider,
    backgroundColor: theme.color.bg,
  },
  leftPanelMobile: { width: "100%", borderRightWidth: 0 },
  leftHeader: { padding: 10, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  searchWrap: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  searchInput: { flex: 1, color: theme.color.text, fontSize: 13 },
  filterRow: { flexDirection: "row", gap: 6, marginTop: 8 },
  filterBtn: { paddingHorizontal: 10, paddingVertical: 5, borderRadius: 6, borderWidth: 1, borderColor: theme.color.border },
  filterBtnActive: { borderColor: theme.color.brand, backgroundColor: theme.color.brandTint },
  filterT: { color: theme.color.textMuted, fontSize: 10, fontWeight: "900", letterSpacing: 1 },
  filterTActive: { color: theme.color.brand },

  convRow: { flexDirection: "row", alignItems: "center", padding: 10, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  convRowActive: { backgroundColor: theme.color.brandTint },
  convRowUnread: { backgroundColor: theme.color.surface },
  convName: { color: theme.color.text, fontSize: 13, fontWeight: "700", flex: 1 },
  convNameUnread: { fontWeight: "900" },
  convTime: { color: theme.color.textMuted, fontSize: 10, marginLeft: 6 },
  convPreview: { color: theme.color.textMuted, fontSize: 11, flex: 1 },
  convPreviewUnread: { color: theme.color.text, fontWeight: "600" },
  badge: {
    minWidth: 18, height: 18, borderRadius: 9, marginLeft: 6,
    paddingHorizontal: 5, backgroundColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
  },
  badgeT: { color: "#fff", fontSize: 10, fontWeight: "900" },
  // Iter 165b · Pending check-in indicators — small red dot on the avatar
  // + a compact "CHECK-IN" pill next to the client name so the coach can
  // spot outstanding review tasks even on already-read conversations.
  checkinDot: {
    position: "absolute", top: -2, right: -2,
    width: 10, height: 10, borderRadius: 5,
    backgroundColor: theme.color.brand,
    borderWidth: 1.5, borderColor: theme.color.bg,
  },
  checkinPill: {
    flexDirection: "row", alignItems: "center", gap: 3,
    paddingHorizontal: 6, paddingVertical: 1,
    borderRadius: 10,
    backgroundColor: "rgba(163,24,46,0.14)",
    borderWidth: 1, borderColor: "rgba(163,24,46,0.45)",
  },
  checkinPillT: {
    color: theme.color.brand, fontSize: 8, letterSpacing: 1.2,
    fontWeight: "900",
  },
  emptyList: { padding: 30, alignItems: "center" },
  emptyListT: { color: theme.color.textMuted, marginTop: 10, fontSize: 12 },

  avatarBase: { borderWidth: 1, alignItems: "center", justifyContent: "center", overflow: "hidden" },

  /* Center panel */
  centerPanel: { flex: 1, backgroundColor: theme.color.bg },
  emptyCenter: { flex: 1, alignItems: "center", justifyContent: "center", padding: 30 },
  emptyCenterT: { color: theme.color.text, fontSize: 16, fontWeight: "800", marginTop: 12 },
  emptyCenterSub: { color: theme.color.textMuted, fontSize: 13, marginTop: 6, textAlign: "center" },
  threadHeader: {
    flexDirection: "row", alignItems: "center", padding: 10,
    borderBottomWidth: 1, borderBottomColor: theme.color.divider,
    backgroundColor: theme.color.bg,
  },
  threadName: { color: theme.color.text, fontSize: 15, fontWeight: "900" },
  threadSub: { color: theme.color.textMuted, fontSize: 11, marginTop: 1 },
  headerBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6,
    borderWidth: 1, borderColor: theme.color.brand,
  },
  headerBtnT: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1 },
  threadScroll: { flex: 1 },
  emptyThreadT: { color: theme.color.text, fontSize: 14, fontWeight: "800" },
  emptyThreadSub: { color: theme.color.textMuted, fontSize: 12, marginTop: 4 },

  daySep: { flexDirection: "row", alignItems: "center", gap: 8, marginVertical: 12 },
  daySepLine: { flex: 1, height: 1, backgroundColor: theme.color.divider },
  daySepT: { color: theme.color.textMuted, fontSize: 10, fontWeight: "800", letterSpacing: 1 },

  bubbleRow: { flexDirection: "row", marginVertical: 2 },
  bubbleRowMine: { justifyContent: "flex-end" },
  bubbleRowTheirs: { justifyContent: "flex-start" },
  bubble: { maxWidth: "70%", padding: 10, borderRadius: 12 },
  bubbleMine: { backgroundColor: theme.color.brand, borderBottomRightRadius: 4 },
  bubbleTheirs: { backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, borderBottomLeftRadius: 4 },
  bubbleText: { fontSize: 14, lineHeight: 20 },
  bubbleMeta: { color: theme.color.textMuted, fontSize: 9, marginTop: 4, letterSpacing: 0.4 },
  attImage: { width: 220, height: 160, borderRadius: 8, marginBottom: 6, backgroundColor: "#000" },
  attGeneric: { flexDirection: "row", alignItems: "center", padding: 6, marginBottom: 4, borderRadius: 6, backgroundColor: theme.color.surface },

  /* Composer */
  composer: { padding: 8, borderTopWidth: 1, borderTopColor: theme.color.divider, backgroundColor: theme.color.bg },
  attachedRow: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 8, paddingVertical: 5, marginBottom: 6, borderRadius: 6,
    backgroundColor: theme.color.brandTint, alignSelf: "flex-start",
  },
  attachedT: { color: theme.color.brand, fontSize: 11, fontWeight: "800" },
  composerRow: { flexDirection: "row", alignItems: "flex-end", gap: 6 },
  iconBtn: { padding: 8, borderRadius: 6 },
  composerInput: {
    flex: 1, minHeight: 40, maxHeight: 120,
    color: theme.color.text, fontSize: 14,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
    borderRadius: 10, paddingHorizontal: 12, paddingVertical: 8,
  },
  sendBtn: {
    width: 40, height: 40, borderRadius: 20,
    backgroundColor: theme.color.brand, alignItems: "center", justifyContent: "center",
  },

  /* Right panel */
  rightPanel: {
    width: 320,
    borderLeftWidth: 1, borderLeftColor: theme.color.divider,
    backgroundColor: theme.color.bg,
  },
  emptyRightT: { color: theme.color.textMuted, fontSize: 12 },
  identCard: {
    alignItems: "center", padding: 14, borderRadius: 12,
    backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border,
  },
  identName: { color: theme.color.text, fontSize: 15, fontWeight: "900", marginTop: 8 },
  identSub: { color: theme.color.textMuted, fontSize: 11, marginTop: 3 },
  pillRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 10, justifyContent: "center" },
  pill: {
    paddingHorizontal: 8, paddingVertical: 4, borderRadius: 999,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  pillLive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  pillT: { color: theme.color.text, fontSize: 10, fontWeight: "800", letterSpacing: 0.5 },

  ctxCard: {
    marginTop: 12, padding: 12, borderRadius: 10,
    backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border,
  },
  ctxLabel: { color: theme.color.brand, fontSize: 9, fontWeight: "900", letterSpacing: 1.5 },
  ctxValue: { color: theme.color.text, fontSize: 14, fontWeight: "800", marginTop: 4 },
  ctxMeta: { color: theme.color.textMuted, fontSize: 11, marginTop: 3 },
  ctxNote: { color: theme.color.text, fontSize: 12, lineHeight: 17, marginTop: 4 },

  qa: {
    flexDirection: "row", alignItems: "center", gap: 8,
    padding: 10, marginTop: 6, borderRadius: 8,
    backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border,
  },
  qaT: { flex: 1, color: theme.color.text, fontSize: 12, fontWeight: "700" },
});
