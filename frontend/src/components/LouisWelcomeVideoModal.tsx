/**
 * LouisWelcomeVideoModal — Iter 104
 *
 * Full-screen dark overlay showing Louis's welcome video. Shows ONCE per
 * client (keyed by AsyncStorage flag `crewfit_louis_welcome_v1_seen`) the
 * next time they land on the client home. Covers:
 *   - brand-new signups
 *   - existing clients (Trainerize switchers, beta testers) who already
 *     completed onboarding before the video existed
 *
 * Behaviour:
 *   - Autoplays UNMUTED on native iOS/Android (allowed by ExoPlayer /
 *     AVPlayer for user-initiated app opens).
 *   - Autoplays MUTED on web (browser autoplay policy) — shows a big
 *     "TAP TO UNMUTE" pulse for the first 5 seconds so users notice.
 *   - Cinematic dark backdrop, subtle fade in, tap play/pause, mute toggle,
 *     "Skip" text after 5 seconds.
 *   - When the video ends (or user dismisses), the flag is written and the
 *     modal is torn down for the rest of that user's app lifetime.
 *
 * Placement: mounted inside /app/frontend/app/(client)/_layout.tsx so it
 * runs above whichever tab the client lands on after login.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, Modal, Pressable, ActivityIndicator, Animated,
  Platform, Dimensions,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { VideoView, useVideoPlayer } from "expo-video";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { theme } from "@/src/lib/theme";

const SEEN_KEY = "crewfit_louis_welcome_v1_seen";
const VIDEO_SOURCE = require("@/assets/louis/welcome.mp4");

export function LouisWelcomeVideoModal() {
  const [visible, setVisible] = useState(false);
  const [checked, setChecked] = useState(false);
  const [muted, setMuted] = useState(Platform.OS === "web"); // native starts UNMUTED
  const [showSkip, setShowSkip] = useState(false);
  const [ended, setEnded] = useState(false);
  const fade = useRef(new Animated.Value(0)).current;

  const player = useVideoPlayer(VIDEO_SOURCE, (p) => {
    p.loop = false;
    // Native devices allow sound autoplay for user-opened apps; web must
    // start muted to satisfy browser autoplay policy.
    p.muted = Platform.OS === "web";
    p.play();
  });

  // Check the "seen" flag on mount and only show the modal for
  // first-time viewers.
  useEffect(() => {
    (async () => {
      try {
        const v = await AsyncStorage.getItem(SEEN_KEY);
        if (v !== "1") {
          setVisible(true);
        }
      } catch { /* ignore — never block the app on storage errors */ }
      setChecked(true);
    })();
  }, []);

  // Fade the overlay in, then reveal the SKIP link after 5s so users can
  // always exit but aren't tempted to skip immediately.
  useEffect(() => {
    if (!visible) return;
    Animated.timing(fade, { toValue: 1, duration: 500, useNativeDriver: true }).start();
    const t = setTimeout(() => setShowSkip(true), 5000);
    return () => clearTimeout(t);
  }, [visible, fade]);

  useEffect(() => {
    if (!visible) return;
    const sub = player.addListener("playToEnd", () => setEnded(true));
    return () => { try { sub.remove(); } catch { /* ignore */ } };
  }, [visible, player]);

  const dismiss = useCallback(async () => {
    try {
      player.pause();
    } catch { /* ignore */ }
    try {
      await AsyncStorage.setItem(SEEN_KEY, "1");
    } catch { /* ignore */ }
    setVisible(false);
  }, [player]);

  const toggleMute = useCallback(() => {
    const next = !muted;
    try { player.muted = next; } catch { /* ignore */ }
    setMuted(next);
  }, [muted, player]);

  if (!checked || !visible) return null;

  const { width, height } = Dimensions.get("window");
  // Portrait 9:16 video — fill vertically but not more than 82% of the
  // screen so the copy under the frame is always visible on small devices.
  const videoW = Math.min(width - 40, 380);
  const videoH = Math.min(Math.round(videoW * (16 / 9)), height * 0.7);

  return (
    <Modal
      visible={visible}
      animationType="fade"
      transparent
      statusBarTranslucent
      onRequestClose={dismiss}
    >
      <Animated.View style={[styles.bg, { opacity: fade }]}>
        {/* Brand strip at the very top */}
        <View style={styles.brandStrip}>
          <Text style={styles.brandT}>CREW<Text style={styles.brandRed}>FIT</Text></Text>
          <Text style={styles.brandSub}>WELCOME</Text>
        </View>

        {/* Video */}
        <View style={[styles.frame, { width: videoW, height: videoH }]} testID="louis-welcome-modal">
          <VideoView
            player={player}
            style={StyleSheet.absoluteFill}
            contentFit="cover"
            nativeControls={false}
            allowsFullscreen={false}
            allowsPictureInPicture={false}
          />
          {/* Show a lightweight loading indicator until the first frame lands. */}
          {!ended ? null : (
            <View style={styles.endedOverlay} pointerEvents="none">
              <ActivityIndicator color="#fff" />
            </View>
          )}

          {/* Mute toggle */}
          <Pressable
            testID="louis-welcome-mute"
            onPress={toggleMute}
            hitSlop={12}
            style={styles.muteBtn}
          >
            <Ionicons name={muted ? "volume-mute" : "volume-high"} size={16} color="#fff" />
          </Pressable>

          {/* Web-only pulse hint for unmuting */}
          {muted && Platform.OS === "web" ? (
            <View style={styles.unmuteHint} pointerEvents="none">
              <Ionicons name="volume-high" size={12} color="#fff" />
              <Text style={styles.unmuteHintT}>TAP TO UNMUTE</Text>
            </View>
          ) : null}
        </View>

        {/* Louis label under the frame */}
        <Text style={styles.louisName}>LOUIS HALL</Text>
        <Text style={styles.louisRole}>FOUNDER · HEAD COACH</Text>

        {/* Bottom bar — Skip / Continue */}
        <View style={styles.bottomBar}>
          {(ended || showSkip) ? (
            <Pressable testID="louis-welcome-continue" onPress={dismiss} style={styles.continueBtn}>
              <Text style={styles.continueT}>{ended ? "CONTINUE TO YOUR DASHBOARD" : "SKIP INTRO"}</Text>
              <Ionicons name="arrow-forward" size={14} color="#fff" />
            </Pressable>
          ) : (
            <Text style={styles.holdCopy}>A quick welcome from Louis…</Text>
          )}
        </View>
      </Animated.View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  bg: {
    flex: 1,
    backgroundColor: "#000",
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 20,
  },
  brandStrip: {
    position: "absolute",
    top: 60,
    left: 20, right: 20,
    flexDirection: "row",
    alignItems: "flex-end",
    justifyContent: "space-between",
  },
  brandT: { color: "#fff", fontSize: 22, fontWeight: "900", letterSpacing: 2 },
  brandRed: { color: theme.color.brand },
  brandSub: { color: theme.color.textMuted, fontSize: 10, fontWeight: "800", letterSpacing: 2.5, marginBottom: 4 },
  frame: {
    borderRadius: 20,
    overflow: "hidden",
    backgroundColor: "#000",
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.08)",
    shadowColor: theme.color.brand,
    shadowOpacity: 0.55,
    shadowRadius: 28,
    shadowOffset: { width: 0, height: 10 },
    elevation: 14,
  },
  endedOverlay: {
    ...StyleSheet.absoluteFillObject,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(0,0,0,0.35)",
  },
  muteBtn: {
    position: "absolute",
    top: 12, right: 12,
    width: 34, height: 34, borderRadius: 17,
    backgroundColor: "rgba(0,0,0,0.55)",
    alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: "rgba(255,255,255,0.18)",
  },
  unmuteHint: {
    position: "absolute",
    bottom: 14, alignSelf: "center", left: 0, right: 0,
    flexDirection: "row", gap: 6,
    alignItems: "center", justifyContent: "center",
  },
  unmuteHintT: {
    color: "#fff",
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 2,
    backgroundColor: "rgba(0,0,0,0.55)",
    paddingHorizontal: 8, paddingVertical: 3, borderRadius: 4,
    borderWidth: 1, borderColor: "rgba(255,255,255,0.12)",
  },
  louisName: { color: "#fff", fontSize: 16, fontWeight: "900", letterSpacing: 3, marginTop: 16 },
  louisRole: { color: theme.color.brand, fontSize: 10, fontWeight: "800", letterSpacing: 2.5, marginTop: 3 },

  bottomBar: {
    position: "absolute",
    bottom: 50, left: 20, right: 20,
    alignItems: "center",
  },
  continueBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    paddingVertical: 14,
    paddingHorizontal: 22,
    borderRadius: 12,
    backgroundColor: theme.color.brand,
  },
  continueT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 1.6 },
  holdCopy: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700", letterSpacing: 1.5 },
});

export default LouisWelcomeVideoModal;
