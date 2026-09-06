/**
 * MembershipTierBadge — small pill shown under the member's name on the
 * profile header. Iter201 · Phase 1 Payments.
 *
 * Read-only visualiser. Reads `membership_tier` and
 * `is_founding_member` from the backend `/payments/membership-status`
 * response — never mutates state. Renders nothing while the fetch is
 * in flight or when the user has no paid tier.
 *
 *   Access      →  subtle grey outline
 *   Coaching    →  brand red (mid-tier)
 *   Performance →  gold gradient (premium feel)
 *   +Founding   →  secondary amber pill alongside the tier badge
 */
import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet } from "react-native";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Tier = "access" | "coaching" | "performance" | "none" | null | undefined;

type Status = {
  membership_tier?: Tier;
  is_founding_member?: boolean;
  membership_status?: string | null;
};

export function MembershipTierBadge() {
  const [status, setStatus] = useState<Status | null>(null);

  useEffect(() => {
    let live = true;
    api<Status>("/payments/membership-status")
      .then((r) => { if (live) setStatus(r); })
      .catch(() => {});
    return () => { live = false; };
  }, []);

  if (!status) return null;
  const tier = status.membership_tier;
  const founding = !!status.is_founding_member;

  // Nothing to show for free/complimentary/none — badge is a paid signal.
  if (!tier || tier === "none") {
    // Founding badge without a tier is unusual but supported.
    if (!founding) return null;
    return (
      <View style={styles.row}>
        <FoundingBadge />
      </View>
    );
  }

  const tierStyle = TIER_STYLES[tier as keyof typeof TIER_STYLES];
  if (!tierStyle) return null;

  return (
    <View style={styles.row}>
      <View style={[styles.badge, tierStyle.bg]} testID={`tier-badge-${tier}`}>
        <Text style={[styles.badgeText, tierStyle.text]}>
          {tier.toUpperCase()}
        </Text>
      </View>
      {founding ? <FoundingBadge /> : null}
    </View>
  );
}

function FoundingBadge() {
  return (
    <View style={[styles.badge, styles.foundingBg]} testID="founding-badge">
      <Text style={[styles.badgeText, styles.foundingText]}>FOUNDING</Text>
    </View>
  );
}

const TIER_STYLES = {
  access: {
    bg:   { backgroundColor: theme.color.surface3, borderColor: theme.color.border },
    text: { color: theme.color.text },
  },
  coaching: {
    bg:   { backgroundColor: theme.color.brand + "33", borderColor: theme.color.brand },
    text: { color: theme.color.text },
  },
  performance: {
    // Muted gold — reads as "premium" against a dark background.
    bg:   { backgroundColor: "#d4a94733", borderColor: "#d4a947" },
    text: { color: "#f4d68c" },
  },
} as const;

const styles = StyleSheet.create({
  row: {
    flexDirection: "row", flexWrap: "wrap", alignItems: "center",
    gap: 6, marginTop: 6,
  },
  badge: {
    paddingHorizontal: 8, paddingVertical: 3,
    borderRadius: 999, borderWidth: 1,
  },
  badgeText: { fontSize: 10, fontWeight: "800", letterSpacing: 1.4 },
  foundingBg: { backgroundColor: "#f7b95533", borderColor: "#f7b955" },
  foundingText: { color: "#f7b955" },
});
