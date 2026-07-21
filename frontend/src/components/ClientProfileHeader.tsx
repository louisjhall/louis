/**
 * ClientProfileHeader — the new premium hero on the client home screen.
 *
 * Replaces the previous "HELLO ALEX + date" strip with a proper aviation
 * identity card: photo/avatar, first name, role · airline, base + current
 * location, today's day type / standby status.
 *
 * All fields degrade gracefully — missing airline shows role only, missing
 * location falls back to home base, missing photo shows the ProfileAvatar
 * monogram, and if today's day-type is unknown the day-load pill still
 * renders.
 */
import React from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { theme, loadColor } from "@/src/lib/theme";
import { ProfileAvatar } from "@/src/components/ProfileAvatar";
import { LocationBadge } from "@/src/components/LocationBadge";
import { CrewFitWings } from "@/src/components/Logo";

type User = {
  id: string;
  name?: string;
  profile_photo_url?: string | null;
  current_location_city?: string | null;
  current_location_country?: string | null;
  current_time_zone?: string | null;
  profile?: {
    job_title?: string;
    airline?: string;
    home_base?: string;
    aircraft_type?: string;
  } | null;
};

type Props = {
  user?: User | null;
  todayLoad?: string | null;      // green|amber|red|blue|purple|grey
  dayType?: string | null;
  dayTitle?: string | null;       // roster.day title if available
  isStandby?: boolean;
  onPressAvatar?: () => void;
};

function firstName(name?: string | null): string {
  if (!name) return "CREW";
  return String(name).trim().split(/\s+/)[0].toUpperCase();
}

function fmtDayline(): string {
  const d = new Date();
  const day = d.toLocaleDateString("en-GB", { weekday: "long" });
  const date = d.toLocaleDateString("en-GB", { day: "numeric", month: "long" });
  return `${day} · ${date}`.toUpperCase();
}

export function ClientProfileHeader({
  user, todayLoad, dayType, dayTitle, isStandby, onPressAvatar,
}: Props) {
  const router = useRouter();
  const p = user?.profile || {};
  const role = p.job_title;
  const airline = p.airline;
  const base = p.home_base;
  const loadC = loadColor(todayLoad || "grey");
  const dt = dayType ? String(dayType).replace(/_/g, " ").toUpperCase() : null;

  return (
    <View style={styles.wrap}>
      {/* Row 1: avatar + identity */}
      <View style={styles.row}>
        <Pressable
          onPress={onPressAvatar || (() => router.push("/(client)/profile"))}
          hitSlop={8}
          testID="client-header-avatar"
        >
          <ProfileAvatar
            userId={user?.id}
            name={user?.name}
            photoUrl={user?.profile_photo_url || null}
            size={62}
          />
        </Pressable>
        <View style={{ flex: 1, marginLeft: 12 }}>
          <View style={styles.helloRow}>
            <Text style={styles.helloEyebrow}>HELLO</Text>
            <CrewFitWings size={22} />
          </View>
          <Text style={styles.name} numberOfLines={1}>{firstName(user?.name)}</Text>

          {/* Role · Airline */}
          {(role || airline) ? (
            <Text style={styles.role} numberOfLines={1}>
              {role || "CREW"}{airline ? <Text style={styles.roleDim}>  ·  {airline}</Text> : null}
            </Text>
          ) : null}

          {/* Base + Location */}
          <View style={styles.baseRow}>
            {base ? (
              <View style={styles.baseChip}>
                <Ionicons name="airplane" size={11} color={theme.color.textMuted} />
                <Text style={styles.baseT}>{String(base).toUpperCase()}</Text>
              </View>
            ) : null}
            <LocationBadge
              city={user?.current_location_city}
              country={user?.current_location_country}
              tz={user?.current_time_zone}
              compact
            />
          </View>
        </View>
      </View>

      {/* Row 2: day-load + standby badges */}
      <View style={styles.metaRow}>
        <View style={[styles.loadPill, { borderColor: loadC }]} testID="header-load-pill">
          <View style={[styles.loadDot, { backgroundColor: loadC }]} />
          <Text style={styles.loadT}>{String(todayLoad || "grey").toUpperCase()} DAY</Text>
        </View>
        {isStandby ? (
          <View style={styles.standbyPill}>
            <Ionicons name="radio" size={11} color={theme.color.amber} />
            <Text style={styles.standbyT}>STANDBY</Text>
          </View>
        ) : null}
        {dt ? (
          <Text style={styles.dayType} numberOfLines={1}>{dt}</Text>
        ) : (
          <Text style={styles.dayline}>{fmtDayline()}</Text>
        )}
      </View>

      {/* Row 3: day title (workout / rest) */}
      {dayTitle ? (
        <Text style={styles.dayTitle} numberOfLines={1}>{dayTitle}</Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { paddingHorizontal: 4, paddingBottom: 12, gap: 12 },
  row: { flexDirection: "row", alignItems: "center" },

  helloRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 2 },
  helloEyebrow: {
    color: theme.color.brand, fontSize: 10, letterSpacing: 3, fontWeight: "900",
    fontFamily: theme.font.textSemi,
  },
  name: {
    color: theme.color.text, fontSize: 28, letterSpacing: 1.4,
    fontWeight: "900", fontFamily: theme.font.display, lineHeight: 32,
  },
  role: {
    color: theme.color.text, fontSize: 12, letterSpacing: 1.4, fontWeight: "700",
    fontFamily: theme.font.textSemi, marginTop: 2,
  },
  roleDim: { color: theme.color.textMuted, fontWeight: "600", letterSpacing: 0.8 },

  baseRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 6, flexWrap: "wrap" },
  baseChip: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 8, paddingVertical: 3, borderRadius: 20,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  baseT: { color: theme.color.textMuted, fontSize: 10, fontWeight: "800", letterSpacing: 1, fontFamily: theme.font.textSemi },

  metaRow: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" },
  loadPill: {
    flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 10, paddingVertical: 4,
    borderRadius: 20, borderWidth: 1, backgroundColor: "rgba(0,0,0,0.35)",
  },
  loadDot: { width: 6, height: 6, borderRadius: 3 },
  loadT: { color: theme.color.text, fontSize: 10, fontWeight: "900", letterSpacing: 1.3, fontFamily: theme.font.textSemi },
  standbyPill: {
    flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: 10, paddingVertical: 4,
    borderRadius: 20, borderWidth: 1, borderColor: theme.color.amber,
    backgroundColor: "rgba(245,158,11,0.14)",
  },
  standbyT: { color: theme.color.amber, fontSize: 10, fontWeight: "900", letterSpacing: 1.2, fontFamily: theme.font.textSemi },
  dayType: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1.3, fontWeight: "800", fontFamily: theme.font.textSemi, marginLeft: 2, flex: 1 },
  dayline: { color: theme.color.textDim, fontSize: 10, letterSpacing: 1.5, fontWeight: "700", fontFamily: theme.font.text, marginLeft: 2 },

  dayTitle: {
    color: theme.color.text, fontSize: 18, letterSpacing: 0.8,
    fontWeight: "900", fontFamily: theme.font.display, marginTop: -2,
  },
});
