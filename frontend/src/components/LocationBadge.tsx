/**
 * LocationBadge — compact "Currently in <city>" chip driven by the user's
 * saved current_location_city + current_time_zone. Also shows local time
 * (updated once on mount) when the tz is known.
 */
import React, { useMemo } from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/lib/theme";

type Props = {
  city?: string | null;
  country?: string | null;
  tz?: string | null;
  compact?: boolean;
};

export function LocationBadge({ city, country, tz, compact }: Props) {
  const label = city ? city : country ? country : null;

  const time = useMemo(() => {
    if (!tz) return null;
    try {
      const now = new Date();
      const fmt = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: tz });
      return fmt.format(now);
    } catch { return null; }
  }, [tz]);

  if (!label && !time) return null;

  return (
    <View style={[styles.wrap, compact && styles.compact]}>
      <Ionicons name="location" size={12} color={theme.color.brand} />
      {label ? <Text style={styles.city}>{label.toUpperCase()}</Text> : null}
      {time ? <>
        <View style={styles.dot} />
        <Text style={styles.time}>{time}</Text>
      </> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 8, paddingVertical: 4, borderRadius: 20,
    backgroundColor: "rgba(163,24,46,0.10)", borderWidth: 1, borderColor: "rgba(163,24,46,0.35)",
    alignSelf: "flex-start",
  },
  compact: { paddingHorizontal: 6, paddingVertical: 3 },
  city: { color: theme.color.text, fontSize: 10, fontWeight: "800", letterSpacing: 1.2, fontFamily: theme.font.textSemi },
  time: { color: theme.color.textMuted, fontSize: 10, fontWeight: "700", letterSpacing: 0.5, fontFamily: theme.font.text },
  dot: { width: 3, height: 3, borderRadius: 1.5, backgroundColor: theme.color.textDim, opacity: 0.7 },
});
