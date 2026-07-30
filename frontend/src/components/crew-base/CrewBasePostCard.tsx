/**
 * Iter 129 — Crew Base community post card.
 *
 * Displays a coach or client post with:
 *   - author identity (initials avatar or profile photo per privacy mode)
 *   - text
 *   - optional image or video (base64 data URI)
 *   - aviation-themed "Wings" reaction (airplane icon)
 *   - flat, chronological comments preview + "view all" expansion
 *
 * All identity data comes RESOLVED from the server (never renders full
 * name when identity_mode = initials).
 */
import React, { useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, Pressable, Image, TextInput, ActivityIndicator } from "react-native";
import { VideoView, useVideoPlayer } from "expo-video";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

export type CrewBaseAuthor = {
  author_id: string;
  public_name: string;
  avatar_kind: "initials" | "photo" | "coach";
  avatar_initials: string;
  avatar_photo_url?: string;
  role: "client" | "coach";
  subtype?: string | null;
  coach_only?: { real_name: string; email?: string; identity_mode?: string };
};

export type CrewBaseComment = {
  id: string;
  text: string;
  author: CrewBaseAuthor;
  created_at: string;
};

export type CrewBasePost = {
  id: string;
  author: CrewBaseAuthor;
  text: string;
  media_type: "none" | "image" | "video";
  media_url?: string | null;
  status: string;
  published_at?: string | null;
  reactions: { kind: "wings"; count: number; viewer_reacted: boolean };
  comments_preview: CrewBaseComment[];
  comments_count: number;
};

function relTime(iso?: string | null): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const diff = Math.max(0, Date.now() - t);
  const min = Math.floor(diff / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h}h`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d}d`;
  return new Date(iso).toLocaleDateString();
}

function Avatar({ author, size = 40 }: { author: CrewBaseAuthor; size?: number }) {
  const s = { width: size, height: size, borderRadius: size / 2 };
  if (author.avatar_kind === "photo" && author.avatar_photo_url) {
    return <Image source={{ uri: author.avatar_photo_url }} style={[styles.avatarBase, s]} />;
  }
  const isCoach = author.role === "coach";
  return (
    <View
      style={[
        styles.avatarBase,
        s,
        { backgroundColor: isCoach ? theme.color.brand : theme.color.surface3, borderColor: isCoach ? theme.color.brand : theme.color.border },
      ]}
    >
      <Text style={[styles.avatarInitials, { fontSize: Math.max(11, size * 0.36), color: isCoach ? "#fff" : theme.color.text }]}>
        {author.avatar_initials}
      </Text>
    </View>
  );
}

function VideoBlock({ uri }: { uri: string }) {
  const player = useVideoPlayer(uri, (p) => {
    p.loop = false;
  });
  return (
    <VideoView
      player={player}
      style={styles.media}
      contentFit="cover"
      nativeControls
    />
  );
}

export function CrewBasePostCard({
  post,
  viewerIsCoach,
  onChanged,
  onDeleteRequested,
  onEditRequested,
}: {
  post: CrewBasePost;
  viewerIsCoach: boolean;
  onChanged?: () => void;
  onDeleteRequested?: (post: CrewBasePost) => void;
  onEditRequested?: (post: CrewBasePost) => void;
}) {
  const [expandedComments, setExpandedComments] = useState<CrewBaseComment[] | null>(null);
  const [loadingComments, setLoadingComments] = useState(false);
  const [reactCount, setReactCount] = useState(post.reactions.count);
  const [reacted, setReacted] = useState(post.reactions.viewer_reacted);
  const [commentText, setCommentText] = useState("");
  const [posting, setPosting] = useState(false);

  useEffect(() => {
    setReactCount(post.reactions.count);
    setReacted(post.reactions.viewer_reacted);
  }, [post.reactions.count, post.reactions.viewer_reacted]);

  const totalComments = post.comments_count;
  const commentsToShow = expandedComments ?? post.comments_preview;

  const toggleWings = async () => {
    // Optimistic update
    setReacted((r) => !r);
    setReactCount((c) => c + (reacted ? -1 : 1));
    try {
      const res = await api<{ count: number; viewer_reacted: boolean }>(
        `/crew-base/posts/${post.id}/react`,
        { method: "POST", body: {} },
      );
      setReactCount(res.count);
      setReacted(res.viewer_reacted);
    } catch (_e) {
      // Rollback
      setReacted((r) => !r);
      setReactCount((c) => c + (reacted ? 1 : -1));
    }
  };

  const expandComments = async () => {
    if (expandedComments) {
      setExpandedComments(null);
      return;
    }
    setLoadingComments(true);
    try {
      const res = await api<{ comments: CrewBaseComment[] }>(`/crew-base/posts/${post.id}/comments`);
      setExpandedComments(res.comments || []);
    } finally {
      setLoadingComments(false);
    }
  };

  const submitComment = async () => {
    const t = commentText.trim();
    if (!t) return;
    setPosting(true);
    try {
      const res = await api<{ comment: CrewBaseComment }>(
        `/crew-base/posts/${post.id}/comments`,
        { method: "POST", body: { text: t } },
      );
      setCommentText("");
      // Optimistic append
      setExpandedComments((cur) => {
        const list = cur ?? post.comments_preview.slice();
        return [...list, res.comment];
      });
      onChanged?.();
    } finally {
      setPosting(false);
    }
  };

  const deleteComment = async (commentId: string) => {
    try {
      await api(`/crew-base/comments/${commentId}`, { method: "DELETE" });
      setExpandedComments((cur) => (cur ?? []).filter((c) => c.id !== commentId));
      onChanged?.();
    } catch (_e) {
      /* ignore */
    }
  };

  const coachRealName = useMemo(() => {
    if (!viewerIsCoach) return null;
    return post.author.coach_only?.real_name;
  }, [viewerIsCoach, post.author]);

  return (
    <View style={styles.card} testID={`cb-post-${post.id}`}>
      {/* Header */}
      <View style={styles.headerRow}>
        <Avatar author={post.author} size={40} />
        <View style={{ flex: 1, marginLeft: 10 }}>
          <Text style={styles.authorName} numberOfLines={1}>{post.author.public_name}</Text>
          <Text style={styles.authorSub} numberOfLines={1}>
            {post.author.subtype ? `${post.author.subtype} · ` : ""}
            {relTime(post.published_at)}
          </Text>
          {viewerIsCoach && coachRealName && post.author.role === "client" && coachRealName !== post.author.public_name ? (
            <Text style={styles.coachOnly}>{coachRealName} · visible to coach only</Text>
          ) : null}
        </View>
        {viewerIsCoach ? (
          <View style={{ flexDirection: "row", gap: 8 }}>
            {onEditRequested ? (
              <Pressable onPress={() => onEditRequested(post)} hitSlop={8} testID={`cb-post-edit-${post.id}`}>
                <Ionicons name="pencil" size={16} color={theme.color.textMuted} />
              </Pressable>
            ) : null}
            {onDeleteRequested ? (
              <Pressable onPress={() => onDeleteRequested(post)} hitSlop={8} testID={`cb-post-delete-${post.id}`}>
                <Ionicons name="trash" size={16} color={theme.color.textMuted} />
              </Pressable>
            ) : null}
          </View>
        ) : null}
      </View>

      {/* Body */}
      {post.text ? <Text style={styles.body}>{post.text}</Text> : null}

      {/* Media */}
      {post.media_type === "image" && post.media_url ? (
        <Image source={{ uri: post.media_url }} style={styles.media} resizeMode="cover" />
      ) : post.media_type === "video" && post.media_url ? (
        <VideoBlock uri={post.media_url} />
      ) : null}

      {/* Reaction bar */}
      <View style={styles.reactBar}>
        <Pressable
          onPress={toggleWings}
          style={[styles.wingsBtn, reacted && styles.wingsBtnActive]}
          testID={`cb-wings-${post.id}`}
          accessibilityRole="button"
          accessibilityLabel="Give wings"
        >
          <Ionicons name="airplane" size={14} color={reacted ? "#fff" : theme.color.brand} />
          <Text style={[styles.wingsT, reacted && styles.wingsTActive]}>
            {reactCount > 0 ? `${reactCount} ${reactCount === 1 ? "wing" : "wings"}` : "Wings"}
          </Text>
        </Pressable>
        <Pressable onPress={expandComments} style={styles.commentsToggle} testID={`cb-comments-toggle-${post.id}`}>
          <Ionicons name="chatbubble-outline" size={14} color={theme.color.textMuted} />
          <Text style={styles.commentsToggleT}>
            {totalComments} {totalComments === 1 ? "comment" : "comments"}
          </Text>
        </Pressable>
      </View>

      {/* Comments */}
      {commentsToShow.length > 0 ? (
        <View style={styles.commentsBlock}>
          {commentsToShow.map((c) => (
            <View key={c.id} style={styles.commentRow}>
              <Avatar author={c.author} size={26} />
              <View style={{ flex: 1, marginLeft: 8 }}>
                <View style={styles.commentBubble}>
                  <Text style={styles.commentAuthor}>{c.author.public_name}</Text>
                  <Text style={styles.commentText}>{c.text}</Text>
                  {viewerIsCoach && c.author.coach_only?.real_name && c.author.coach_only.real_name !== c.author.public_name ? (
                    <Text style={styles.coachOnlySmall}>{c.author.coach_only.real_name}</Text>
                  ) : null}
                </View>
                <Text style={styles.commentMeta}>
                  {relTime(c.created_at)}
                  {viewerIsCoach ? (
                    <Text onPress={() => deleteComment(c.id)} style={styles.commentDelete}>{"  · delete"}</Text>
                  ) : null}
                </Text>
              </View>
            </View>
          ))}
          {expandedComments === null && totalComments > commentsToShow.length ? (
            <Pressable onPress={expandComments} testID={`cb-view-all-${post.id}`}>
              <Text style={styles.viewAll}>View all {totalComments} comments</Text>
            </Pressable>
          ) : null}
          {loadingComments ? <ActivityIndicator size="small" style={{ marginTop: 6 }} /> : null}
        </View>
      ) : null}

      {/* Composer */}
      <View style={styles.composer}>
        <TextInput
          value={commentText}
          onChangeText={setCommentText}
          placeholder="Add a comment…"
          placeholderTextColor={theme.color.textDim}
          style={styles.composerInput}
          testID={`cb-composer-${post.id}`}
          multiline
        />
        <Pressable
          onPress={submitComment}
          disabled={posting || !commentText.trim()}
          style={[styles.composerSend, (!commentText.trim() || posting) && { opacity: 0.4 }]}
          testID={`cb-composer-send-${post.id}`}
        >
          {posting ? <ActivityIndicator color="#fff" /> : <Ionicons name="send" size={14} color="#fff" />}
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: theme.color.surface,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.color.border,
    padding: theme.space.md,
    marginBottom: theme.space.md,
  },
  headerRow: { flexDirection: "row", alignItems: "center" },
  avatarBase: { borderWidth: 1, alignItems: "center", justifyContent: "center", overflow: "hidden" },
  avatarInitials: { fontWeight: "900", letterSpacing: 0.5 },
  authorName: { color: theme.color.text, fontWeight: "800", fontSize: 14 },
  authorSub: { color: theme.color.textMuted, fontSize: 11, marginTop: 1 },
  coachOnly: { color: theme.color.amber, fontSize: 10, marginTop: 2, letterSpacing: 0.3 },
  coachOnlySmall: { color: theme.color.amber, fontSize: 9, marginTop: 3, letterSpacing: 0.3 },
  body: { color: theme.color.text, fontSize: 14, lineHeight: 20, marginTop: theme.space.sm },
  media: { width: "100%", height: 220, marginTop: theme.space.sm, borderRadius: theme.radius.sm, backgroundColor: "#000" },

  reactBar: {
    flexDirection: "row",
    alignItems: "center",
    gap: theme.space.md,
    marginTop: theme.space.md,
    paddingTop: theme.space.sm,
    borderTopWidth: 1,
    borderTopColor: theme.color.divider,
  },
  wingsBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingVertical: 6, paddingHorizontal: 12, borderRadius: 999,
    borderWidth: 1, borderColor: theme.color.brand,
    backgroundColor: theme.color.brandTint,
  },
  wingsBtnActive: { backgroundColor: theme.color.brand },
  wingsT: { color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 0.6 },
  wingsTActive: { color: "#fff" },
  commentsToggle: { flexDirection: "row", alignItems: "center", gap: 6 },
  commentsToggleT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700" },

  commentsBlock: { marginTop: theme.space.sm },
  commentRow: { flexDirection: "row", alignItems: "flex-start", marginTop: theme.space.sm },
  commentBubble: { backgroundColor: theme.color.surface2, padding: 8, borderRadius: 8, borderWidth: 1, borderColor: theme.color.border },
  commentAuthor: { color: theme.color.text, fontWeight: "800", fontSize: 12 },
  commentText: { color: theme.color.text, fontSize: 13, lineHeight: 18, marginTop: 2 },
  commentMeta: { color: theme.color.textDim, fontSize: 10, marginTop: 3, letterSpacing: 0.3 },
  commentDelete: { color: theme.color.red, fontSize: 10, letterSpacing: 0.3 },
  viewAll: { color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 0.6, marginTop: theme.space.sm },

  composer: {
    flexDirection: "row",
    alignItems: "flex-end",
    gap: 8,
    marginTop: theme.space.sm,
  },
  composerInput: {
    flex: 1,
    minHeight: 36,
    maxHeight: 100,
    color: theme.color.text,
    backgroundColor: theme.color.surface2,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: theme.color.border,
    paddingHorizontal: 10,
    paddingVertical: 8,
    fontSize: 13,
  },
  composerSend: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
  },
});

export default CrewBasePostCard;
