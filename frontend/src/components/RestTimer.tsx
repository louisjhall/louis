/**
 * RestTimer — reusable rest timer used by BOTH Manual Mode and Guided Flow.
 *
 * Features:
 * - Circular progress ring (SVG) with big countdown numeral
 * - Haptic pulses at 3-2-1 and on completion (respects user setting)
 * - Audio cues at start / countdown / end (respects user setting)
 * - Auto-continue toggle: when OFF, shows CONTINUE button; when ON, auto-advances
 * - Controls: pause/resume, skip, +15s, +30s, end rest
 * - Clean single interval — no zombie timers if unmounted or workout closed
 */
import React, { useEffect, useRef, useState, useCallback } from "react";
import { View, Text, StyleSheet, Pressable, Platform } from "react-native";
import Svg, { Circle } from "react-native-svg";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";
import { hapticLight, hapticMedium, hapticSuccess } from "@/src/lib/haptics";
import { playRestStart, playCountdownTick, playRestEnd } from "@/src/lib/sounds";
import { getAutoContinue } from "@/src/lib/workoutMode";
import { narrateRestStart, narrateRestReady } from "@/src/lib/narration";

type Props = {
  seconds: number;
  nextLabel?: string;
  previousLabel?: string;
  size?: number;                 // ring diameter, default 240
  onComplete?: () => void;       // fires exactly once when the countdown reaches 0
  onSkip?: () => void;           // user tapped skip
  onEndEarly?: () => void;       // user tapped "END REST"
  autoContinueOverride?: boolean; // if set, uses this instead of AsyncStorage
  compact?: boolean;             // smaller layout for Manual Mode bottom sheet
};

export function RestTimer({
  seconds,
  nextLabel,
  previousLabel,
  size = 240,
  onComplete,
  onSkip,
  onEndEarly,
  autoContinueOverride,
  compact = false,
}: Props) {
  const [left, setLeft] = useState(seconds);
  const [paused, setPaused] = useState(false);
  const countdown: number | null = null; // reserved for future in-ring countdown UI
  const [readyToContinue, setReadyToContinue] = useState(false);   // auto-continue OFF
  const [autoCont, setAutoCont] = useState<boolean>(autoContinueOverride ?? true);

  const intervalRef = useRef<any>(null);
  const countdownRef = useRef<any>(null);
  const completedRef = useRef(false);
  const countdownedRef = useRef({ three: false, two: false, one: false });

  // Load the auto-continue preference once
  useEffect(() => {
    if (autoContinueOverride !== undefined) return;
    getAutoContinue().then(setAutoCont);
  }, [autoContinueOverride]);

  // Kick off on mount — one cue + start ticking
  useEffect(() => {
    playRestStart(); hapticLight();
    narrateRestStart(seconds, nextLabel);
    setLeft(seconds);
    completedRef.current = false;
    countdownedRef.current = { three: false, two: false, one: false };
    setReadyToContinue(false);
    return () => cleanup();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seconds]);

  const cleanup = useCallback(() => {
    if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null; }
    if (countdownRef.current) { clearInterval(countdownRef.current); countdownRef.current = null; }
  }, []);

  // Main countdown
  useEffect(() => {
    if (paused || readyToContinue || countdown !== null) return;
    if (intervalRef.current) return; // don't stack
    intervalRef.current = setInterval(() => {
      setLeft((s) => {
        if (s > 3) return s - 1;
        // 3-2-1 haptic/audio ticks — fire once each
        if (s === 3 && !countdownedRef.current.three) {
          countdownedRef.current.three = true;
          playCountdownTick(); hapticLight();
        }
        if (s === 2 && !countdownedRef.current.two) {
          countdownedRef.current.two = true;
          playCountdownTick(); hapticLight();
        }
        if (s === 1 && !countdownedRef.current.one) {
          countdownedRef.current.one = true;
          playCountdownTick(); hapticMedium();
        }
        if (s <= 1) {
          cleanup();
          finishNaturally();
          return 0;
        }
        return s - 1;
      });
    }, 1000);
    return cleanup;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paused, readyToContinue, countdown, cleanup]);

  const finishNaturally = () => {
    if (completedRef.current) return;
    completedRef.current = true;
    playRestEnd(); hapticSuccess();
    narrateRestReady();
    if (autoCont) {
      // Small delay so the completion cue lands before we jump
      setTimeout(() => onComplete?.(), 400);
    } else {
      setReadyToContinue(true);
    }
  };

  const skip = () => {
    cleanup();
    completedRef.current = true;
    hapticLight();
    onSkip?.();
  };

  const endEarly = () => {
    cleanup();
    completedRef.current = true;
    hapticMedium();
    onEndEarly?.();
  };

  const addSec = (n: number) => {
    if (completedRef.current) return;
    hapticLight();
    setLeft((s) => Math.max(1, s + n));
  };

  const togglePause = () => {
    hapticSelection();
    setPaused((p) => !p);
  };

  const proceed = () => {
    hapticMedium();
    onComplete?.();
  };

  // Circular progress math
  const stroke = compact ? 8 : 10;
  const radius = size / 2 - stroke;
  const circumference = 2 * Math.PI * radius;
  const pct = Math.max(0, Math.min(1, left / Math.max(1, seconds)));
  const dashOffset = circumference * (1 - pct);

  const mm = Math.floor(left / 60);
  const ss = left % 60;
  const timeLabel = `${mm}:${String(ss).padStart(2, "0")}`;

  return (
    <View style={styles.root}>
      {previousLabel && (
        <Text style={styles.previousLbl} numberOfLines={1}>
          <Text style={styles.previousLblDim}>Previous · </Text>{previousLabel}
        </Text>
      )}

      {/* Ring + numerals */}
      <View style={[styles.ringWrap, { width: size, height: size }]}>
        <Svg width={size} height={size}>
          <Circle
            cx={size / 2} cy={size / 2} r={radius}
            stroke={theme.color.surface3} strokeWidth={stroke} fill="none"
          />
          <Circle
            cx={size / 2} cy={size / 2} r={radius}
            stroke={readyToContinue ? theme.color.green : theme.color.brand}
            strokeWidth={stroke}
            strokeLinecap="round"
            fill="none"
            strokeDasharray={`${circumference}, ${circumference}`}
            strokeDashoffset={dashOffset}
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
          />
        </Svg>

        <View style={styles.ringCentre}>
          {readyToContinue ? (
            <>
              <Ionicons name="checkmark-circle" size={44} color={theme.color.green} />
              <Text style={styles.readyT}>READY</Text>
            </>
          ) : (
            <>
              <Text style={[styles.timeBig, compact && { fontSize: 42 }]}>{timeLabel}</Text>
              <Text style={styles.phaseSm}>{paused ? "PAUSED" : "REST"}</Text>
            </>
          )}
        </View>
      </View>

      {/* Next up */}
      {nextLabel && !readyToContinue && (
        <View style={styles.nextRow}>
          <Text style={styles.nextEyebrow}>NEXT</Text>
          <Text style={styles.nextT} numberOfLines={2}>{nextLabel}</Text>
        </View>
      )}

      {/* Coach line */}
      {!readyToContinue && (
        <Text style={styles.coachLine}>
          {left > 30
            ? "Rest here. Keep your breathing controlled."
            : left > 3
            ? "Next set coming up."
            : "You're ready."}
        </Text>
      )}

      {/* Controls */}
      {readyToContinue ? (
        <Pressable onPress={proceed} style={styles.continueBtn} testID="rest-continue">
          <Ionicons name="arrow-forward" size={18} color="#fff" />
          <Text style={styles.continueBtnT}>CONTINUE</Text>
        </Pressable>
      ) : (
        <>
          <View style={styles.row}>
            <SmallBtn label="+15s" icon="add" onPress={() => addSec(15)} testID="rest-add-15" />
            <SmallBtn label="+30s" icon="add-circle-outline" onPress={() => addSec(30)} testID="rest-add-30" />
            <SmallBtn label={paused ? "RESUME" : "PAUSE"} icon={paused ? "play" : "pause"} onPress={togglePause} testID="rest-pause" />
          </View>
          <View style={styles.row}>
            <SmallBtn label="SKIP REST" icon="play-forward" onPress={skip} testID="rest-skip" tone="brand" />
            {onEndEarly && (
              <SmallBtn label="END REST" icon="close-circle-outline" onPress={endEarly} testID="rest-end" />
            )}
          </View>
        </>
      )}
    </View>
  );
}

function SmallBtn({
  label, icon, onPress, testID, tone = "muted",
}: {
  label: string; icon: any; onPress: () => void; testID?: string; tone?: "brand" | "muted";
}) {
  const isBrand = tone === "brand";
  return (
    <Pressable
      onPress={onPress}
      style={[styles.smallBtn, isBrand && styles.smallBtnBrand]}
      testID={testID}
      hitSlop={6}
    >
      <Ionicons name={icon} size={14} color={isBrand ? "#fff" : theme.color.brand} />
      <Text style={[styles.smallBtnT, isBrand && styles.smallBtnTBrand]}>{label}</Text>
    </Pressable>
  );
}

// Selection helper isn't in haptics.ts exports — inline lightweight one here
async function hapticSelection() {
  if (Platform.OS === "web") return;
  try {
    const H = await import("expo-haptics");
    await H.selectionAsync();
  } catch { /* silent */ }
}

const styles = StyleSheet.create({
  root: { alignItems: "center", width: "100%", gap: 14 },
  previousLbl: { color: theme.color.text, fontSize: 12, fontWeight: "700" },
  previousLblDim: { color: theme.color.textMuted, fontWeight: "400" },

  ringWrap: { alignItems: "center", justifyContent: "center" },
  ringCentre: { ...StyleSheet.absoluteFillObject, alignItems: "center", justifyContent: "center" },
  timeBig: { color: theme.color.text, fontSize: 56, fontWeight: "900", fontVariant: ["tabular-nums"], letterSpacing: -1 },
  phaseSm: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 3, marginTop: 4 },
  readyT: { color: theme.color.green, fontSize: 14, fontWeight: "900", letterSpacing: 3, marginTop: 8 },

  nextRow: { alignItems: "center", gap: 4, paddingHorizontal: 16 },
  nextEyebrow: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  nextT: { color: theme.color.text, fontSize: 14, fontWeight: "800", textAlign: "center" },

  coachLine: {
    color: theme.color.textMuted, fontSize: 12,
    textAlign: "center", fontStyle: "italic", paddingHorizontal: 24, lineHeight: 17,
  },

  row: { flexDirection: "row", gap: 10, justifyContent: "center" },
  smallBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 14, paddingVertical: 10, borderRadius: 10,
    backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand,
    minWidth: 88, justifyContent: "center",
  },
  smallBtnBrand: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  smallBtnT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  smallBtnTBrand: { color: "#fff" },

  continueBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10,
    marginTop: 4,
    paddingHorizontal: 24, paddingVertical: 14, borderRadius: 12,
    backgroundColor: theme.color.green, minWidth: 220,
  },
  continueBtnT: { color: "#fff", fontSize: 13, fontWeight: "900", letterSpacing: 2 },
});
