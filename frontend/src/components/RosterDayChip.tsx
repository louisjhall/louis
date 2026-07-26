/**
 * RosterDayChip — Iter 100
 *
 * A tiny, glanceable chip that summarises a client's roster context for a
 * given day. Renders inline next to workouts / rest cards / calendar day
 * cells so pilots and crew see at-a-glance whether today is a Flying day,
 * Layover, Standby, Off, or a Turnaround.
 *
 * Shape:
 *   [ icon ] SHORT_CODE
 *
 * Examples (short_code auto-derived from roster day):
 *   - Flying   → flight number if present, else "FLIGHT"   (icon: airplane)
 *   - Layover  → layover city IATA / short name             (icon: bed)
 *   - Standby  → "STBY"                                     (icon: time)
 *   - Off/Rest → "OFF"                                      (icon: moon)
 *   - Turnaround → "T/R"                                    (icon: repeat)
 *
 * Colours are kept monotone-brand (subtle background tint per state) so
 * the chip is glanceable without being a rainbow. No emojis anywhere.
 *
 * Two sizes:
 *   - "sm"  (calendar day cells) — 9px text, icon 8px, minimal padding
 *   - "md"  (list rows / hero cards) — 10px text, icon 11px
 */
import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";

type Flight = { number?: string; from?: string; to?: string };

export type RosterDay = {
  day_type?: string | null;
  flights?: Flight[] | null;
  layover_city?: string | null;
};

type Size = "sm" | "md";

const SIZE_MAP: Record<Size, { pad: [number, number]; gap: number; icon: number; text: number; radius: number }> = {
  sm: { pad: [3, 5], gap: 3, icon: 8, text: 8, radius: 3 },
  md: { pad: [4, 7], gap: 4, icon: 11, text: 10, radius: 4 },
};

function normaliseDutyType(t?: string | null): string {
  if (!t) return "";
  return String(t).trim().toLowerCase();
}

function classify(day: RosterDay | null | undefined): {
  kind: "flying" | "layover" | "standby" | "turnaround" | "off" | "home" | "sick" | "leave" | "training" | null;
  icon: keyof typeof Ionicons.glyphMap;
  code: string;
} | null {
  if (!day) return null;
  const t = normaliseDutyType(day.day_type);
  const flightCount = day.flights?.length || 0;
  const primary = (day.flights && day.flights[0]) || undefined;

  // Flying / turnaround has real flight ops
  if (t === "flight" || t === "flying" || t === "fly" || (flightCount > 0 && t !== "layover")) {
    // Turnaround = one or more flights but not a layover — but PDF often
    // uses explicit "Turnaround" label; keep that as its own kind.
    if (t === "turnaround" || t === "t/r" || t === "turn") {
      return { kind: "turnaround", icon: "repeat", code: primary?.number || "T/R" };
    }
    return { kind: "flying", icon: "airplane", code: primary?.number || "FLIGHT" };
  }
  if (t === "layover") {
    // Use layover city (short); fallback to first flight destination
    const city = day.layover_city || primary?.to;
    return { kind: "layover", icon: "bed", code: (city || "LAYOVER").toString().toUpperCase().slice(0, 6) };
  }
  if (t === "turnaround" || t === "t/r" || t === "turn") {
    return { kind: "turnaround", icon: "repeat", code: primary?.number || "T/R" };
  }
  if (t === "standby" || t === "sby" || t === "stby") {
    return { kind: "standby", icon: "time", code: "STBY" };
  }
  if (t === "off" || t === "rest" || t === "day off" || t === "dayoff") {
    return { kind: "off", icon: "moon", code: "OFF" };
  }
  if (t === "home" || t === "at home" || t === "base") {
    return { kind: "home", icon: "home", code: "HOME" };
  }
  if (t === "sick" || t === "medical" || t === "med") {
    return { kind: "sick", icon: "medkit", code: "SICK" };
  }
  if (t === "leave" || t === "annual" || t === "annual leave" || t === "al") {
    return { kind: "leave", icon: "briefcase", code: "LEAVE" };
  }
  if (t === "training" || t === "sim" || t === "simulator" || t === "recurrent") {
    return { kind: "training", icon: "school", code: "TRNG" };
  }
  return null;
}

// Subtle colour language — flat brand palette, no rainbow.
function colours(kind: string): { bg: string; fg: string; border: string } {
  switch (kind) {
    case "flying":
    case "turnaround":
      return { bg: theme.color.brandTint, fg: theme.color.brand, border: theme.color.brand };
    case "layover":
      return { bg: theme.color.surface2, fg: theme.color.text, border: theme.color.border };
    case "standby":
      return { bg: theme.color.surface2, fg: theme.color.amber, border: theme.color.amber };
    case "off":
    case "home":
      return { bg: theme.color.surface2, fg: theme.color.textMuted, border: theme.color.border };
    case "sick":
      return { bg: theme.color.surface2, fg: theme.color.red, border: theme.color.red };
    case "leave":
    case "training":
      return { bg: theme.color.surface2, fg: theme.color.textMuted, border: theme.color.border };
    default:
      return { bg: theme.color.surface2, fg: theme.color.textMuted, border: theme.color.border };
  }
}

export function RosterDayChip({
  day,
  size = "md",
  showCode = true,
  testID,
}: {
  day: RosterDay | null | undefined;
  size?: Size;
  /** If false, only the icon is rendered (no code). Useful in the tiny
   *  calendar-cell mode where horizontal space is fought over. */
  showCode?: boolean;
  testID?: string;
}) {
  const c = classify(day);
  if (!c) return null;
  const s = SIZE_MAP[size];
  const cols = colours(c.kind);
  return (
    <View
      testID={testID || `roster-chip-${c.kind}`}
      style={[
        styles.chip,
        {
          paddingVertical: s.pad[0],
          paddingHorizontal: s.pad[1],
          gap: s.gap,
          borderRadius: s.radius,
          backgroundColor: cols.bg,
          borderColor: cols.border,
        },
      ]}
    >
      <Ionicons name={c.icon} size={s.icon} color={cols.fg} />
      {showCode ? (
        <Text
          style={[
            styles.code,
            { color: cols.fg, fontSize: s.text },
          ]}
          numberOfLines={1}
        >
          {c.code}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  chip: {
    flexDirection: "row",
    alignItems: "center",
    borderWidth: 1,
    alignSelf: "flex-start",
  },
  code: {
    fontWeight: "800",
    letterSpacing: 0.6,
  },
});

export default RosterDayChip;
