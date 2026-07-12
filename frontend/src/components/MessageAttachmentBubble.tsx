/**
 * MessageAttachmentBubble — renders images, videos and voice notes inside
 * a chat message. Images tap to full-screen; videos use expo-video; voice
 * notes have a simple mini player.
 */
import React, { useEffect, useState } from "react";
import {
  View, Text, Pressable, Image, Modal, StyleSheet, ActivityIndicator, Dimensions,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";
import { useAudioPlayer, useAudioPlayerStatus } from "expo-audio";
import { useVideoPlayer, VideoView } from "expo-video";
import { ensureLocalCopyOfAttachment } from "@/src/lib/messageAttachments";

type AttachmentDoc = {
  id: string;
  type: "image" | "video" | "voice";
  mime_type: string;
  duration_seconds: number | null;
  file_size: number;
  url: string; // relative /api/messages/attachments/{id}/file
};

export function MessageAttachmentBubble({
  att,
  mine,
}: {
  att: AttachmentDoc;
  mine: boolean;
}) {
  if (att.type === "image") return <ImageBubble att={att} mine={mine} />;
  if (att.type === "video") return <VideoBubble att={att} mine={mine} />;
  if (att.type === "voice") return <VoiceBubble att={att} mine={mine} />;
  return null;
}

function useLocalUri(att: AttachmentDoc): { uri: string | null; error: string | null } {
  const [uri, setUri] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancel = false;
    (async () => {
      try {
        const local = await ensureLocalCopyOfAttachment(att.url, att.id);
        if (!cancel) setUri(local);
      } catch (e: any) {
        if (!cancel) setError(e?.message || "failed");
      }
    })();
    return () => { cancel = true; };
  }, [att.id, att.url]);
  return { uri, error };
}

function ImageBubble({ att, mine }: { att: AttachmentDoc; mine: boolean }) {
  const { uri, error } = useLocalUri(att);
  const [open, setOpen] = useState(false);
  if (error) return <FailureRow message="Couldn\u2019t load image." mine={mine} />;
  if (!uri) return <PendingBox mine={mine} />;
  return (
    <>
      <Pressable onPress={() => setOpen(true)} testID={`att-image-${att.id}`}>
        <Image source={{ uri }} style={styles.imgThumb} resizeMode="cover" />
      </Pressable>
      <Modal visible={open} transparent animationType="fade" onRequestClose={() => setOpen(false)}>
        <Pressable style={styles.viewerBg} onPress={() => setOpen(false)}>
          <Image source={{ uri }} style={styles.viewerImg} resizeMode="contain" />
          <View style={styles.viewerClose}>
            <Ionicons name="close" size={22} color="#fff" />
          </View>
        </Pressable>
      </Modal>
    </>
  );
}

function VideoBubble({ att, mine }: { att: AttachmentDoc; mine: boolean }) {
  const { uri, error } = useLocalUri(att);
  const [open, setOpen] = useState(false);
  const player = useVideoPlayer(open && uri ? uri : null, (p) => {
    p.loop = false;
  });

  if (error) return <FailureRow message="Couldn\u2019t load video." mine={mine} />;
  if (!uri) return <PendingBox mine={mine} />;

  return (
    <>
      <Pressable onPress={() => setOpen(true)} style={styles.videoThumb} testID={`att-video-${att.id}`}>
        <View style={styles.videoPlayIcon}>
          <Ionicons name="play" size={26} color="#fff" />
        </View>
        {att.duration_seconds != null && (
          <Text style={styles.videoDuration}>{Math.round(att.duration_seconds)}s</Text>
        )}
      </Pressable>
      <Modal visible={open} animationType="slide" onRequestClose={() => setOpen(false)}>
        <View style={styles.videoPlayerRoot}>
          <Pressable onPress={() => setOpen(false)} style={styles.videoCloseBtn}>
            <Ionicons name="close" size={22} color="#fff" />
          </Pressable>
          {player && <VideoView player={player} style={styles.videoPlayer} contentFit="contain" allowsFullscreen />}
        </View>
      </Modal>
    </>
  );
}

function VoiceBubble({ att, mine }: { att: AttachmentDoc; mine: boolean }) {
  const { uri, error } = useLocalUri(att);
  const player = useAudioPlayer(uri ? { uri } : null);
  const status = useAudioPlayerStatus(player);

  if (error) return <FailureRow message="Couldn\u2019t load voice note." mine={mine} />;

  const playing = !!status?.playing;
  const duration = att.duration_seconds || Math.round((status?.duration || 0));
  const currentPct = status?.duration ? Math.min(100, ((status?.currentTime || 0) / status.duration) * 100) : 0;

  return (
    <View style={[styles.voiceRow, mine ? styles.voiceRowMine : styles.voiceRowTheirs]} testID={`att-voice-${att.id}`}>
      <Pressable
        style={[styles.voicePlay, mine && { backgroundColor: "rgba(255,255,255,0.25)" }]}
        onPress={() => (playing ? player?.pause() : player?.play())}
        disabled={!uri}
      >
        {uri ? (
          <Ionicons name={playing ? "pause" : "play"} size={18} color={mine ? "#fff" : theme.color.brand} />
        ) : (
          <ActivityIndicator size="small" color={mine ? "#fff" : theme.color.brand} />
        )}
      </Pressable>
      <View style={{ flex: 1, gap: 4 }}>
        <View style={styles.voiceTrack}>
          <View style={[styles.voiceTrackFill, { width: `${currentPct}%`, backgroundColor: mine ? "#fff" : theme.color.brand }]} />
        </View>
        <Text style={[styles.voiceMeta, mine && { color: "rgba(255,255,255,0.85)" }]}>
          Voice note · {duration || "?"}s
        </Text>
      </View>
    </View>
  );
}

function PendingBox({ mine }: { mine: boolean }) {
  return (
    <View style={[styles.imgThumb, styles.pending]}>
      <ActivityIndicator color={mine ? "#fff" : theme.color.brand} />
    </View>
  );
}

function FailureRow({ message, mine }: { message: string; mine: boolean }) {
  return (
    <View style={[styles.failRow]}>
      <Ionicons name="alert-circle" color={theme.color.brand} size={14} />
      <Text style={[styles.failText, mine && { color: "rgba(255,255,255,0.9)" }]}>{message}</Text>
    </View>
  );
}

const WIN = Dimensions.get("window");
const styles = StyleSheet.create({
  imgThumb: { width: 200, height: 200, borderRadius: 12, backgroundColor: theme.color.surface2, marginTop: 6 },
  pending: { alignItems: "center", justifyContent: "center" },
  viewerBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.95)", alignItems: "center", justifyContent: "center" },
  viewerImg: { width: WIN.width, height: WIN.height * 0.85 },
  viewerClose: { position: "absolute", top: 48, right: 20 },
  videoThumb: {
    width: 220, height: 130, borderRadius: 12, marginTop: 6,
    backgroundColor: "#111", alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: theme.color.border,
  },
  videoPlayIcon: {
    width: 46, height: 46, borderRadius: 23, backgroundColor: theme.color.brand,
    alignItems: "center", justifyContent: "center",
  },
  videoDuration: {
    position: "absolute", bottom: 8, right: 10, color: "#fff",
    backgroundColor: "rgba(0,0,0,0.55)", paddingHorizontal: 6, paddingVertical: 2,
    borderRadius: 6, fontSize: 11, fontWeight: "700",
  },
  videoPlayerRoot: { flex: 1, backgroundColor: "#000" },
  videoPlayer: { flex: 1 },
  videoCloseBtn: { position: "absolute", top: 48, right: 20, zIndex: 10, padding: 8 },
  voiceRow: {
    flexDirection: "row", alignItems: "center", gap: 10, padding: 10,
    borderRadius: 14, marginTop: 6, minWidth: 220, maxWidth: 260,
  },
  voiceRowMine: { backgroundColor: theme.color.brand },
  voiceRowTheirs: { backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  voicePlay: {
    width: 34, height: 34, borderRadius: 17, backgroundColor: theme.color.brandTint,
    alignItems: "center", justifyContent: "center",
  },
  voiceTrack: { height: 4, backgroundColor: "rgba(255,255,255,0.25)", borderRadius: 2, overflow: "hidden" },
  voiceTrackFill: { height: 4, borderRadius: 2 },
  voiceMeta: { color: theme.color.textMuted, fontSize: 11, fontWeight: "600" },
  failRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 6 },
  failText: { color: theme.color.textMuted, fontSize: 11 },
});
