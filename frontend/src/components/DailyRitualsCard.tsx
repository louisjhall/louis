/**
 * DailyRitualsCard — Iter168 (Today-tab overhaul).
 *
 * Consolidates four previously-independent home surfaces into ONE
 * collapsible section so the Today tab reads as: "workout → rituals →
 * schedule" instead of a wall of ~6 different cards.
 *
 * Wrapped children (in render order when expanded):
 *   1. HabitTodayCard      — daily habit ring
 *   2. DualSessionCard     — airport-gap bonus session (short-haul only)
 *   3. WeeklyCheckinCard   — Sunday check-in touchpoint
 *   4. WeeklyReviewCard    — Sunday weekly review
 *
 * Collapsed state shows a single one-line summary that pulls light-weight
 * status from `/habits/today-summary` (habits done vs total) and the
 * check-in / review status flags returned by their respective endpoints.
 * Any child that returns null (not eligible / already handled) is
 * silently omitted from both the summary count and the expanded body.
 *
 * Per iter168 UX brief: **collapsed by default**, one-line summary +
 * chevron. Tap the header to expand. `AsyncStorage` remembers the
 * user's last state so if they always expand it, it stays open next
 * launch.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, LayoutAnimation, Platform, UIManager,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { useFlag } from "@/src/lib/appConfig";
import { HabitTodayCard } from "@/src/components/HabitTodayCard";
import { DualSessionCard } from "@/src/components/DualSessionCard";
import { WeeklyCheckinCard } from "@/src/components/WeeklyCheckinCard";
import { WeeklyReviewCard } from "@/src/components/WeeklyReviewCard";

if (Platform.OS === "android" && UIManager.setLayoutAnimationEnabledExperimental) {
  UIManager.setLayoutAnimationEnabledExperimental(true);
}

const OPEN_KEY = "crewfit.dailyRituals.expanded";

type SummaryState = {
  habits_done: number;
  habits_total: number;
  checkin_due: boolean;
  review_due: boolean;
  dual_session_available: boolean;
};

const EMPTY: SummaryState = {
  habits_done: 0,
  habits_total: 0,
  checkin_due: false,
  review_due: false,
  dual_session_available: false,
};

export function DailyRitualsCard({ refreshKey = 0 }: { refreshKey?: number }) {
  const dualSessionFlag = useFlag("dual_session_enabled");
  const [expanded, setExpanded] = useState(false);
  const [summary, setSummary] = useState<SummaryState>(EMPTY);
  const [loading, setLoading] = useState(true);

  // Restore last state (default collapsed per iter168 UX).
  useEffect(() => {
    AsyncStorage.getItem(OPEN_KEY)
      .then((v) => setExpanded(v === "1"))
      .catch(() => setExpanded(false));
  }, []);

  const toggle = useCallback(() => {
    LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
    setExpanded((prev) => {
      const next = !prev;
      AsyncStorage.setItem(OPEN_KEY, next ? "1" : "0").catch(() => {});
      return next;
    });
  }, []);

  // Fetch the light-weight status flags so the collapsed summary line has
  // real content ("2/3 habits · check-in due"). We deliberately keep each
  // call best-effort so a single 500 doesn't hide the whole card.
  const load = useCallback(async () => {
    setLoading(true);
    // refreshKey referenced so `load` re-generates when the parent's
    // activityRefreshKey ticks, driving a refetch on focus.
    void refreshKey;
    try {
      const [habits, checkin, review] = await Promise.all([
        // /habits/today returns { habits: [...] } with today_log per row.
        api<any>("/habits/today").catch(() => null),
        api<any>("/checkins/current").catch(() => null),
        api<any>("/weekly-review/current").catch(() => null),
      ]);
      const hlist: any[] = habits?.habits || [];
      const habits_total = hlist.length;
      const habits_done = hlist.filter(
        (h) => (h.today_log?.status || "").toLowerCase() === "done",
      ).length;
      const checkin_due =
        !!checkin?.should_show_card && !checkin?.check_in;
      const review_due =
        !!review &&
        (review.checkin_status === "incomplete" ||
          review.progress_status === "incomplete");
      setSummary({
        habits_done,
        habits_total,
        checkin_due,
        review_due,
        dual_session_available: false, // set lazily below if needed
      });
    } catch {
      /* ignore — card degrades to zero counts */
    } finally {
      setLoading(false);
    }
  }, [refreshKey]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  // Build the collapsed summary line.
  const summaryParts: string[] = [];
  if (summary.habits_total > 0) {
    summaryParts.push(`${summary.habits_done}/${summary.habits_total} habits`);
  }
  if (summary.checkin_due) summaryParts.push("check-in due");
  if (summary.review_due) summaryParts.push("weekly review due");
  const summaryLine =
    summaryParts.length > 0
      ? summaryParts.join(" · ")
      : loading
        ? "Loading…"
        : "You're on track — nothing pending";

  const hasWork =
    summary.habits_done < summary.habits_total ||
    summary.checkin_due ||
    summary.review_due;

  return (
    <View style={styles.card} testID="daily-rituals-card">
      <Pressable
        onPress={toggle}
        style={({ pressed }) => [styles.header, pressed && styles.headerPressed]}
        testID="daily-rituals-toggle"
      >
        <View style={styles.headerLeft}>
          <View style={styles.iconWrap}>
            <Ionicons
              name={hasWork ? "sparkles" : "checkmark-circle"}
              size={16}
              color={hasWork ? theme.color.brand : theme.color.green}
            />
          </View>
          <View style={{ flex: 1, minWidth: 0 }}>
            <Text style={styles.eyebrow}>DAILY RITUALS</Text>
            <Text style={styles.summary} numberOfLines={1}>{summaryLine}</Text>
          </View>
        </View>
        <Ionicons
          name={expanded ? "chevron-up" : "chevron-down"}
          size={18}
          color={theme.color.textMuted}
        />
      </Pressable>

      {expanded ? (
        <View style={styles.body} testID="daily-rituals-body">
          {/* Each child card handles its own null / not-eligible state.
              We add small vertical spacing between them so the expanded
              body looks like a clean stack, not four boxes glued together. */}
          <HabitTodayCard />
          {dualSessionFlag ? <DualSessionCard refreshKey={refreshKey} /> : null}
          <WeeklyCheckinCard />
          <WeeklyReviewCard refreshKey={refreshKey} />
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: theme.color.surface,
    borderRadius: theme.radius.card,
    borderWidth: 1,
    borderColor: theme.color.border,
    overflow: "hidden",
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: 14,
    paddingHorizontal: 14,
    gap: 12,
  },
  headerPressed: {
    backgroundColor: theme.color.surface2,
  },
  headerLeft: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    minWidth: 0,
  },
  iconWrap: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: theme.color.brandTint,
    borderWidth: 1,
    borderColor: theme.color.brand,
    alignItems: "center",
    justifyContent: "center",
  },
  eyebrow: {
    color: theme.color.brand,
    fontSize: 11,
    fontWeight: "800",
    letterSpacing: 2,
    fontFamily: theme.font.textSemi,
  },
  summary: {
    color: theme.color.text,
    fontSize: 13,
    fontWeight: "700",
    marginTop: 2,
  },
  body: {
    padding: 14,
    paddingTop: 4,
    gap: 12,
    borderTopWidth: 1,
    borderTopColor: theme.color.divider,
  },
});
