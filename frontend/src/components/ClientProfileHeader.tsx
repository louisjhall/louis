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
import React, { useMemo } from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { theme } from "@/src/lib/theme";
import type { ThemeMode } from "@/src/lib/theme";
import { useThemeMode } from "@/src/hooks/use-theme-mode";
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
  /** Iter 162b · when true the header renders vertically stacked and
   *  centre-aligned (used when a centred logo sits above it). */
  centered?: boolean;
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
  user, todayLoad: _todayLoad, dayType, dayTitle, isStandby, onPressAvatar,
  centered = false,
}: Props) {
  const router = useRouter();
  // Iter175 · Subscribe to the theme mode so this header repaints
  // instantly on Light ↔ Dark toggle. `styles` is rebuilt via
  // `buildStyles()` whose `theme.color.*` reads are evaluated at call
  // time — i.e. AFTER the palette mutation lands.
  const { mode } = useThemeMode();
  // Iter177 · Dynamic styles via `makeStyles(mode)` factory.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const styles = useMemo(() => makeStyles(mode), [mode]);
  const p = user?.profile || {};
  const role = p.job_title;
  const airline = p.airline;
  const base = p.home_base;
  // Iter 161 · todayLoad still accepted for prop back-compat but no longer
  // rendered — surface colouring elsewhere already conveys load.
  const dt = dayType ? String(dayType).replace(/_/g, " ").toUpperCase() : null;

  return (
    <View style={[styles.wrap, centered && styles.wrapCentered]}>
      {/* Row 1: avatar + identity — centered mode stacks vertically. */}
      <View style={[styles.row, centered && styles.rowCentered]}>
        <Pressable
          onPress={onPressAvatar || (() => router.push("/(client)/profile"))}
          hitSlop={8}
          testID="client-header-avatar"
        >
          <ProfileAvatar
            userId={user?.id}
            name={user?.name}
            photoUrl={user?.profile_photo_url || null}
            size={centered ? 56 : 62}
          />
        </Pressable>
        <View style={[
          { flex: 1, marginLeft: 12 },
          centered && { flex: 0, marginLeft: 0, marginTop: 10, alignItems: "center" },
        ]}>
          <View style={[styles.helloRow, centered && styles.helloRowCentered]}>
            <Text style={styles.helloEyebrow}>HELLO</Text>
            {!centered ? <CrewFitWings size={22} /> : null}
          </View>
          <Text style={styles.name} numberOfLines={1}>{firstName(user?.name)}</Text>

          {/* Role · Airline */}
          {(role || airline) ? (
            <Text style={[styles.role, centered && styles.roleCentered]} numberOfLines={1}>
              {role || "CREW"}{airline ? <Text style={styles.roleDim}>  ·  {airline}</Text> : null}
            </Text>
          ) : null}

          {/* Base + Location.
              Iter 165 · Give the row a hard `flexWrap: wrap` and cap the
              LocationBadge width so a long city name (e.g. "SYDNEY DOWNTOWN")
              can gracefully wrap to a new line under the base chip instead
              of overlapping the base pill or spilling past the header
              right-edge. */}
          <View style={[styles.baseRow, centered && styles.baseRowCentered]}>
            {base ? (
              <View style={styles.baseChip}>
                <Ionicons name="airplane" size={11} color={theme.color.textMuted} />
                <Text style={styles.baseT}>{String(base).toUpperCase()}</Text>
              </View>
            ) : null}
            <View style={styles.locWrap}>
              <LocationBadge
                city={user?.current_location_city}
                country={user?.current_location_country}
                tz={user?.current_time_zone}
                compact
              />
            </View>
          </View>
        </View>
      </View>

      {/* Row 2: standby + optional day-type strip.
          Iter 165 · Layout guards for long day-type labels like
          "LAYOVER ARRIVAL" — dayType now grows with `flexShrink: 1` and
          `minWidth: 0` so it truncates cleanly and never overlaps the
          standby pill on the left. */}
      <View style={[styles.metaRow, centered && styles.metaRowCentered]}>
        {isStandby ? (
          <View style={styles.standbyPill}>
            <Ionicons name="radio" size={11} color={theme.color.amber} />
            <Text style={styles.standbyT}>STANDBY</Text>
          </View>
        ) : null}
        {dt ? (
          <Text style={[styles.dayType, centered && styles.dayTypeCentered]} numberOfLines={1} ellipsizeMode="tail">{dt}</Text>
        ) : (
          <Text style={[styles.dayline, centered && styles.dayTypeCentered]} numberOfLines={1} ellipsizeMode="tail">{fmtDayline()}</Text>
        )}
      </View>

      {/* Row 3: day title (workout / rest) */}
      {dayTitle ? (
        <Text style={[styles.dayTitle, centered && styles.dayTitleCentered]} numberOfLines={1}>{dayTitle}</Text>
      ) : null}
    </View>
  );
}

// Iter177 · Style factory. Called from inside <ClientProfileHeader/>
// via `useMemo(..., [mode])` so every `theme.color.xxx` read happens
// at render time and the header repaints instantly on theme toggle.
function makeStyles(_mode: ThemeMode) {
  return StyleSheet.create({
  wrap: { paddingHorizontal: 4, paddingBottom: 12, gap: 12 },
  // Iter 162b · centered variant — used when a large CrewFit logo sits
  // above the header. Whole card stacks vertically and aligns to centre.
  wrapCentered: { alignItems: "center", paddingHorizontal: 0, gap: 8 },
  row: { flexDirection: "row", alignItems: "center" },
  rowCentered: { flexDirection: "column", alignItems: "center" },

  helloRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 2 },
  helloEyebrow: {
    color: theme.color.brand, fontSize: 11, letterSpacing: 3, fontWeight: "900",
    fontFamily: theme.font.textSemi,
  },
  // Iter174 · Header user-name MUST use `theme.color.text`. With the
  // Iter174 palette fix forcing dark-mode text to #FFFFFF, this
  // guarantees names like "PIETRO" render legibly on the dark hero.
  name: {
    color: theme.color.text, fontSize: 28, letterSpacing: 1.4,
    fontWeight: "900", fontFamily: theme.font.display, lineHeight: 32,
  },
  role: {
    color: theme.color.text, fontSize: 12, letterSpacing: 1.4, fontWeight: "700",
    fontFamily: theme.font.textSemi, marginTop: 2,
  },
  roleDim: { color: theme.color.textMuted, fontWeight: "600", letterSpacing: 0.8 },

  baseRow: {
    flexDirection: "row", alignItems: "center", gap: 6, marginTop: 6,
    // Iter 165 · Explicit wrap so a long LocationBadge drops under the
    // base chip rather than colliding with it on narrow screens.
    flexWrap: "wrap", rowGap: 6,
  },
  // Iter 165 · Cap the LocationBadge width so it wraps its own text if the
  // city name is long (e.g. "SAN FRANCISCO"). `flexShrink: 1` prevents
  // the badge from overflowing when it sits next to the base chip.
  locWrap: { flexShrink: 1, minWidth: 0, maxWidth: "100%" },
  baseChip: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 8, paddingVertical: 3, borderRadius: 20,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  baseT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "800", letterSpacing: 1, fontFamily: theme.font.textSemi },

  metaRow: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "nowrap" },
  loadPill: {
    flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 10, paddingVertical: 4,
    borderRadius: 20, borderWidth: 1, backgroundColor: "rgba(0,0,0,0.35)",
  },
  loadDot: { width: 6, height: 6, borderRadius: 3 },
  loadT: { color: theme.color.text, fontSize: 11, fontWeight: "900", letterSpacing: 1.3, fontFamily: theme.font.textSemi },
  standbyPill: {
    flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: 10, paddingVertical: 4,
    borderRadius: 20, borderWidth: 1, borderColor: theme.color.amber,
    backgroundColor: "rgba(245,158,11,0.14)",
  },
  standbyT: { color: theme.color.amber, fontSize: 11, fontWeight: "900", letterSpacing: 1.2, fontFamily: theme.font.textSemi },
  dayType: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1.3, fontWeight: "800", fontFamily: theme.font.textSemi, marginLeft: 2, flex: 1, flexShrink: 1, minWidth: 0, textAlign: "center" },
  dayline: { color: theme.color.textDim, fontSize: 11, letterSpacing: 1.5, fontWeight: "700", fontFamily: theme.font.text, marginLeft: 2, flex: 1, flexShrink: 1, minWidth: 0, textAlign: "center" },
  // Iter172 · Explicit centered variant for the Layover Arrival / Day Type
  // strip. Drops flex so the text hugs its own width and centres via the
  // parent metaRow's `justifyContent: center` — otherwise `flex: 1` on
  // the base dayType style pushed the text left of the visual midpoint.
  dayTypeCentered: {
    flex: 0,
    marginLeft: 0,
    textAlign: "center",
    alignSelf: "center",
    paddingHorizontal: 8,
  },

  dayTitle: {
    color: theme.color.text, fontSize: 18, letterSpacing: 0.8,
    fontWeight: "900", fontFamily: theme.font.display, marginTop: -2,
  },
  // Iter 162b · centred variants — used only when `centered` prop is on.
  helloRowCentered: { justifyContent: "center", marginBottom: 4 },
  roleCentered: { textAlign: "center" },
  baseRowCentered: { justifyContent: "center" },
  metaRowCentered: { justifyContent: "center", marginTop: 4 },
  dayTitleCentered: { textAlign: "center", marginTop: 4 },
  });
}
