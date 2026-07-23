/**
 * TimezoneCard — Iter 94r
 *
 * Compact card shown at the TOP of the client home. Displays:
 *   - Home base city + Home timezone
 *   - Current timezone (resolved by roster > confirmed > device > home base)
 *   - Source badge (Roster / Confirmed / Device / Home base)
 *
 * Passes the device's IANA timezone to the backend as a query param so the
 * resolver can use it as a fallback.
 */
import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type TzStatus = {
  home_base?: string | null;
  home_timezone?: string | null;
  current_timezone?: string | null;
  current_timezone_city?: string | null;
  current_timezone_source?: "roster" | "client_confirmed" | "device" | "home_base" | "unknown";
  current_timezone_confidence?: "high" | "medium" | "low";
  reason?: string | null;
  needs_confirmation?: boolean;
};

function sourceLabel(src?: string | null): string {
  switch (src) {
    case "roster":            return "ROSTER";
    case "client_confirmed":  return "CONFIRMED";
    case "device":            return "DEVICE";
    case "home_base":         return "HOME BASE";
    default:                  return "UNKNOWN";
  }
}

function sourceColor(src?: string | null): string {
  switch (src) {
    case "roster":            return theme.color.brand;
    case "client_confirmed":  return theme.color.green || "#22c55e";
    case "device":            return theme.color.amber || "#f59e0b";
    case "home_base":         return theme.color.textMuted;
    default:                  return theme.color.textDim;
  }
}

function currentTimeIn(iana?: string | null): string {
  if (!iana) return "—";
  try {
    return new Intl.DateTimeFormat("en-GB", {
      timeZone: iana,
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(new Date());
  } catch {
    return "—";
  }
}

function offsetLabelFor(iana?: string | null): string {
  if (!iana) return "";
  try {
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone: iana,
      timeZoneName: "shortOffset",
    }).formatToParts(new Date());
    const off = parts.find((p) => p.type === "timeZoneName")?.value || "";
    return off.replace("GMT", "UTC");
  } catch {
    return "";
  }
}

export function TimezoneCard({ onOpenConfirm }: { onOpenConfirm?: () => void }) {
  const [tz, setTz] = useState<TzStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [now, setNow] = useState<number>(Date.now());

  useEffect(() => {
    let device_tz = "";
    try { device_tz = Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch { /* ignore */ }
    (async () => {
      setLoading(true);
      try {
        const q = device_tz ? `?device_tz=${encodeURIComponent(device_tz)}` : "";
        const r = await api<TzStatus>(`/profile/timezone-status${q}`);
        setTz(r);
      } catch { /* ignore */ } finally { setLoading(false); }
    })();
  }, []);

  // Ticker so the current-time label updates each minute without a full reload
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(id);
  }, []);

  if (loading && !tz) {
    return (
      <View style={styles.card} testID="timezone-card-loading">
        <ActivityIndicator color={theme.color.brand} />
      </View>
    );
  }
  if (!tz) return null;

  const src = tz.current_timezone_source;
  const currentCity =
    tz.current_timezone_city ||
    (tz.current_timezone ? tz.current_timezone.split("/").slice(-1)[0].replace(/_/g, " ") : null);
  const homeCity =
    tz.home_base ||
    (tz.home_timezone ? tz.home_timezone.split("/").slice(-1)[0].replace(/_/g, " ") : null);
  const away =
    !!tz.home_timezone && !!tz.current_timezone && tz.home_timezone !== tz.current_timezone;
  // Keep `now` referenced so the ticker rerender takes effect
  void now;

  return (
    <Pressable
      onPress={onOpenConfirm}
      testID="timezone-card"
      style={styles.card}
    >
      <View style={styles.headRow}>
        <Ionicons name="time" size={16} color={theme.color.brand} />
        <Text style={styles.headTitle}>YOUR TIMEZONE</Text>
        <View style={[styles.srcPill, { backgroundColor: sourceColor(src) }]}>
          <Text style={styles.srcPillT}>{sourceLabel(src)}</Text>
        </View>
      </View>

      <View style={styles.mainRow}>
        <View style={styles.col}>
          <Text style={styles.colLbl}>CURRENT</Text>
          <Text style={styles.colCity} numberOfLines={1}>
            {currentCity ? String(currentCity).toUpperCase() : "—"}
          </Text>
          <Text style={styles.colMeta} numberOfLines={1}>
            {currentTimeIn(tz.current_timezone)}
            {tz.current_timezone ? `  ${offsetLabelFor(tz.current_timezone)}` : ""}
          </Text>
        </View>

        <View style={styles.arrowWrap}>
          <Ionicons
            name={away ? "airplane" : "home"}
            size={16}
            color={theme.color.textMuted}
          />
        </View>

        <View style={[styles.col, { alignItems: "flex-end" }]}>
          <Text style={styles.colLbl}>HOME BASE</Text>
          <Text style={[styles.colCity, { textAlign: "right" }]} numberOfLines={1}>
            {homeCity ? String(homeCity).toUpperCase() : "—"}
          </Text>
          <Text style={[styles.colMeta, { textAlign: "right" }]} numberOfLines={1}>
            {currentTimeIn(tz.home_timezone)}
            {tz.home_timezone ? `  ${offsetLabelFor(tz.home_timezone)}` : ""}
          </Text>
        </View>
      </View>

      {tz.reason ? (
        <Text style={styles.reason} numberOfLines={1}>{tz.reason}</Text>
      ) : null}

      {tz.needs_confirmation ? (
        <Text style={styles.confirmHint}>TAP TO CONFIRM YOUR TIMEZONE</Text>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.color.border,
    padding: 12,
    marginBottom: 12,
    gap: 8,
  },
  headRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  headTitle: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 2, flex: 1 },
  srcPill: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 10 },
  srcPillT: { color: "#fff", fontSize: 9, fontWeight: "900", letterSpacing: 1.5 },

  mainRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  col: { flex: 1, minWidth: 0 },
  colLbl: { color: theme.color.textMuted, fontSize: 9, fontWeight: "800", letterSpacing: 1.5, marginBottom: 2 },
  colCity: { color: theme.color.text, fontSize: 14, fontWeight: "900", letterSpacing: 1 },
  colMeta: { color: theme.color.textMuted, fontSize: 11, marginTop: 2, fontWeight: "700" },

  arrowWrap: {
    paddingHorizontal: 4,
    alignItems: "center",
    justifyContent: "center",
  },

  reason: { color: theme.color.textMuted, fontSize: 11, marginTop: 4 },
  confirmHint: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1.5, marginTop: 4 },
});
