/**
 * Membership & Payments — Iter201 · Phase 1
 *
 * Client-facing subscription page. Reads:
 *   GET  /api/payments/membership-status
 * Writes via:
 *   POST /api/payments/create-checkout-session  → opens Stripe Checkout
 *   POST /api/payments/create-portal-session    → opens Stripe Customer Portal
 *
 * The page renders:
 *   1. Status card (current membership, founding badge if applicable)
 *   2. Three tier cards (Access · Coaching · Performance) with an
 *      interval toggle (Monthly / 3-month / 6-month)
 *   3. Comparison table (features × tiers)
 *   4. "Which membership is right for me?" guide
 *
 * Prices are hard-coded on the client (matches the spec exactly).
 * Stripe is still the billing source of truth — this file merely
 * mirrors the pricing table for display.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  Linking, Platform, RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Interval = "monthly" | "quarterly" | "biannual";
type Tier = "access" | "coaching" | "performance";
type Audience = "public" | "founding";

type StatusResponse = {
  membership_status: string | null;
  membership_tier: string | null;
  is_founding_member: boolean;
  founding_eligible: boolean;
  founding_price_locked: boolean;
  trial_ends_at: string | null;
  access_until: string | null;
  payment_required_at: string | null;
  has_stripe_customer: boolean;
  subscription: null | {
    status?: string; interval?: string; tier?: string;
    current_period_end?: string; cancel_at_period_end?: boolean;
    is_founding?: boolean; stripe_price_id?: string;
  };
};

// Exact figures from the spec.
const PRICES: Record<Tier, Record<Audience, Record<Interval, { total: number; effMonthly: number; save?: number }>>> = {
  access: {
    public:   { monthly: { total: 29, effMonthly: 29 },
                quarterly: { total: 79, effMonthly: 26.33, save: 8 },
                biannual: { total: 149, effMonthly: 24.83, save: 25 } },
    founding: { monthly: { total: 19, effMonthly: 19 },
                quarterly: { total: 52, effMonthly: 17.33, save: 9 },
                biannual: { total: 99, effMonthly: 16.50, save: 15 } },
  },
  coaching: {
    public:   { monthly: { total: 169, effMonthly: 169 },
                quarterly: { total: 479, effMonthly: 159.67, save: 28 },
                biannual: { total: 929, effMonthly: 154.83, save: 85 } },
    founding: { monthly: { total: 134, effMonthly: 134 },
                quarterly: { total: 382, effMonthly: 127.33, save: 20 },
                biannual: { total: 739, effMonthly: 123.17, save: 65 } },
  },
  performance: {
    public:   { monthly: { total: 279, effMonthly: 279 },
                quarterly: { total: 799, effMonthly: 266.33, save: 38 },
                biannual: { total: 1529, effMonthly: 254.83, save: 145 } },
    founding: { monthly: { total: 229, effMonthly: 229 },
                quarterly: { total: 652, effMonthly: 217.33, save: 35 },
                biannual: { total: 1259, effMonthly: 209.83, save: 115 } },
  },
};

const TIER_META: Record<Tier, {
  label: string; headline: string; copy: string; note?: string;
  badge?: string; recommended?: boolean;
}> = {
  access: {
    label: "Best for independent crew",
    headline: "Full CrewFit technology, built around your roster.",
    copy: "Everything you need to train consistently as cabin crew or a pilot — roster-aware planning, On Demand workouts, flight support, recovery tools and progress tracking. Designed for members who are happy to manage their own training.",
    note: "Does not include personal programme management or coaching contact.",
  },
  coaching: {
    label: "Most Popular",
    headline: "Your training, personally managed around your roster.",
    copy: "A coach personally manages your programme, reviews your roster and adjusts your training around your flying schedule. Includes weekly personalised video feedback, direct coaching support, programme adjustments and a monthly live call. Built for crew who want accountability and results without guesswork.",
    badge: "MOST POPULAR",
    recommended: true,
  },
  performance: {
    label: "Best for maximum support",
    headline: "High-touch coaching with weekly live contact.",
    copy: "Everything in Coaching, plus a weekly live video call, priority support, detailed nutrition targets, video exercise analysis and performance preparation. Intentionally limited capacity. Built for those who want the highest level of access and accountability.",
  },
};

const COMPARISON = [
  ["Full CrewFit app", true, true, true],
  ["Roster-aware planning", true, true, true],
  ["On Demand workouts", true, true, true],
  ["Personalised programme management", false, true, true],
  ["Weekly personalised video feedback", false, true, true],
  ["Direct coaching support", false, true, true],
  ["Monthly live call", false, true, true],
  ["Weekly live call", false, false, true],
  ["Priority support", false, false, true],
  ["Event and performance preparation", false, false, true],
] as const;

const INTERVAL_LABEL: Record<Interval, string> = {
  monthly: "Monthly",
  quarterly: "3-month",
  biannual: "6-month",
};

function formatGBP(n: number): string {
  return "£" + (Math.round(n * 100) / 100).toLocaleString("en-GB", {
    minimumFractionDigits: n % 1 === 0 ? 0 : 2,
    maximumFractionDigits: 2,
  });
}

function openHosted(url: string) {
  if (Platform.OS === "web") {
    if (typeof window !== "undefined") window.location.assign(url);
  } else {
    Linking.openURL(url).catch(() => {});
  }
}

export default function Membership() {
  const router = useRouter();
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [interval, setInterval_] = useState<Interval>("monthly");
  const [refreshing, setRefreshing] = useState(false);
  const [busyTier, setBusyTier] = useState<Tier | null>(null);
  const [portalBusy, setPortalBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api<StatusResponse>("/payments/membership-status");
      setStatus(r);
    } catch {
      setStatus(null);
    } finally {
      setLoading(false); setRefreshing(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const audience: Audience = status?.founding_eligible ? "founding" : "public";
  const currentTier = (status?.subscription?.tier || status?.membership_tier) as Tier | null;
  const currentStatus = status?.membership_status || "unknown";
  const cancellationScheduled = !!status?.subscription?.cancel_at_period_end
    || currentStatus === "cancellation_scheduled";
  const hasActive = ["active", "past_due", "cancellation_scheduled"].includes(currentStatus);

  const startCheckout = useCallback(async (tier: Tier) => {
    setBusyTier(tier);
    try {
      const r = await api<{ url: string }>("/payments/create-checkout-session", {
        method: "POST", body: { tier, interval },
      });
      if (r?.url) openHosted(r.url);
    } catch (e: any) {
      // Uniform surface — production users see a generic message; the
      // exception has the actual reason for us to inspect in logs.
      alert(e?.message || "Unable to start checkout. Please try again shortly.");
    } finally {
      setBusyTier(null);
    }
  }, [interval]);

  const openPortal = useCallback(async () => {
    setPortalBusy(true);
    try {
      const r = await api<{ url: string }>("/payments/create-portal-session", { method: "POST" });
      if (r?.url) openHosted(r.url);
    } catch (e: any) {
      alert(e?.message || "Unable to open the customer portal.");
    } finally {
      setPortalBusy(false);
    }
  }, []);

  const daysRemaining = useMemo(() => {
    if (!status?.trial_ends_at && !status?.access_until) return null;
    const target = status.trial_ends_at || status.access_until;
    if (!target) return null;
    const ms = new Date(target).getTime() - Date.now();
    return Math.max(0, Math.ceil(ms / 86400000));
  }, [status]);

  if (loading) {
    return (
      <View style={[styles.root, { justifyContent: "center", alignItems: "center" }]}>
        <ActivityIndicator color={theme.color.brand} />
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.root}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
      >
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={10} style={styles.backBtn}>
            <Ionicons name="chevron-back" size={22} color={theme.color.text} />
          </Pressable>
          <Text style={styles.title}>Membership</Text>
          <View style={{ width: 32 }} />
        </View>

        {/* -------- Status card -------- */}
        <View style={styles.statusCard}>
          <Text style={styles.statusLabel}>YOUR MEMBERSHIP</Text>
          <View style={{ flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 8, marginTop: 6 }}>
            <Text style={styles.statusValue}>{prettyStatus(currentStatus)}</Text>
            {status?.is_founding_member ? (
              <View style={styles.foundingBadge}><Text style={styles.foundingBadgeText}>FOUNDING MEMBER</Text></View>
            ) : null}
            {currentTier ? (
              <View style={styles.tierBadgeInline}><Text style={styles.tierBadgeInlineText}>{currentTier.toUpperCase()}</Text></View>
            ) : null}
          </View>

          {currentStatus === "beta" && daysRemaining != null ? (
            <Text style={styles.statusSub}>{daysRemaining} day{daysRemaining === 1 ? "" : "s"} of beta access remaining</Text>
          ) : null}
          {cancellationScheduled && status?.access_until ? (
            <Text style={styles.statusSub}>Cancellation scheduled — full access until {new Date(status.access_until).toLocaleDateString("en-GB")}</Text>
          ) : null}
          {currentStatus === "past_due" && status?.access_until ? (
            <Text style={[styles.statusSub, { color: theme.color.brand }]}>Payment failed — access ends {new Date(status.access_until).toLocaleDateString("en-GB")}. Update your card below.</Text>
          ) : null}
          {currentStatus === "payment_required" ? (
            <Text style={[styles.statusSub, { color: theme.color.brand }]}>Your coach has asked you to set up a paid membership. Pick a plan below.</Text>
          ) : null}
          {(currentStatus === "cancelled" || currentStatus === "expired") ? (
            <Text style={[styles.statusSub, { color: theme.color.brand }]}>Your previous membership ended. Pick a plan below to reactivate.</Text>
          ) : null}
          {status?.founding_eligible && !hasActive ? (
            <Text style={[styles.statusSub, { color: "#f7b955" }]}>A Founding Member offer is available on the plans below.</Text>
          ) : null}

          {status?.has_stripe_customer ? (
            <Pressable
              onPress={openPortal}
              disabled={portalBusy}
              style={({ pressed }) => [styles.portalBtn, pressed && { opacity: 0.7 }]}
              testID="membership-manage"
            >
              {portalBusy
                ? <ActivityIndicator color={theme.color.text} />
                : <>
                    <Ionicons name="settings-outline" size={14} color={theme.color.text} />
                    <Text style={styles.portalBtnText}>MANAGE SUBSCRIPTION</Text>
                  </>}
            </Pressable>
          ) : null}
        </View>

        {/* -------- Interval toggle -------- */}
        <View style={styles.intervalRow}>
          {(["monthly", "quarterly", "biannual"] as Interval[]).map((iv) => {
            const active = interval === iv;
            return (
              <Pressable
                key={iv} onPress={() => setInterval_(iv)}
                style={[styles.intervalBtn, active && styles.intervalBtnActive]}
                testID={`interval-${iv}`}
              >
                <Text style={[styles.intervalBtnText, active && styles.intervalBtnTextActive]}>
                  {INTERVAL_LABEL[iv]}
                </Text>
              </Pressable>
            );
          })}
        </View>

        {/* -------- Three tier cards -------- */}
        <View style={styles.tierColumn}>
          {(["access", "coaching", "performance"] as Tier[]).map((tier) => {
            const meta = TIER_META[tier];
            const price = PRICES[tier][audience][interval];
            const busy = busyTier === tier;
            return (
              <View
                key={tier}
                style={[
                  styles.tierCard,
                  meta.recommended && styles.tierCardRecommended,
                ]}
                testID={`tier-card-${tier}`}
              >
                {meta.badge ? (
                  <View style={styles.recommendedBadge}>
                    <Text style={styles.recommendedBadgeText}>{meta.badge}</Text>
                  </View>
                ) : null}
                <Text style={styles.tierLabel}>{meta.label}</Text>
                <Text style={styles.tierName}>CrewFit {tier.charAt(0).toUpperCase() + tier.slice(1)}</Text>
                <Text style={styles.tierHeadline}>{meta.headline}</Text>

                <View style={styles.priceRow}>
                  <Text style={styles.priceLarge}>{formatGBP(price.total)}</Text>
                  <Text style={styles.priceUnit}>
                    {interval === "monthly" ? "/month" : `total · ${formatGBP(price.effMonthly)}/mo`}
                  </Text>
                </View>
                {price.save ? (
                  <Text style={styles.saveText}>Save {formatGBP(price.save)} vs monthly</Text>
                ) : null}
                {audience === "founding" ? (
                  <Text style={styles.foundingPriceNote}>Founding Member price · locked at signup</Text>
                ) : null}

                <Text style={styles.tierCopy}>{meta.copy}</Text>
                {meta.note ? <Text style={styles.tierNote}>{meta.note}</Text> : null}

                <Pressable
                  onPress={() => startCheckout(tier)}
                  disabled={busy || busyTier !== null}
                  style={({ pressed }) => [
                    styles.subscribeBtn,
                    meta.recommended && styles.subscribeBtnStrong,
                    (pressed || busy) && { opacity: 0.75 },
                  ]}
                  testID={`subscribe-${tier}`}
                >
                  {busy ? (
                    <ActivityIndicator color="#fff" />
                  ) : (
                    <Text style={styles.subscribeBtnText}>
                      {currentTier === tier && hasActive ? "CURRENT PLAN"
                        : hasActive ? "SWITCH TO " + tier.toUpperCase()
                        : "CHOOSE " + tier.toUpperCase()}
                    </Text>
                  )}
                </Pressable>
                <Text style={styles.autoRenewText}>Auto-renews every {intervalToWord(interval)}. Cancel anytime from Manage Subscription.</Text>
              </View>
            );
          })}
        </View>

        {/* -------- Comparison table -------- */}
        <Text style={styles.sectionTitle}>Compare plans</Text>
        <View style={styles.comparisonWrap}>
          <View style={[styles.compRow, styles.compHeaderRow]}>
            <View style={{ flex: 2.3 }}><Text style={styles.compHeaderCell}> </Text></View>
            <View style={styles.compHeadCell}><Text style={styles.compHeaderCell}>Access</Text></View>
            <View style={styles.compHeadCell}><Text style={styles.compHeaderCell}>Coaching</Text></View>
            <View style={styles.compHeadCell}><Text style={styles.compHeaderCell}>Perf.</Text></View>
          </View>
          {COMPARISON.map(([feat, a, c, p]) => (
            <View key={String(feat)} style={styles.compRow}>
              <View style={{ flex: 2.3 }}><Text style={styles.compFeature}>{String(feat)}</Text></View>
              <View style={styles.compCell}><Ionicons name={a ? "checkmark" : "close"} size={18} color={a ? "#3ecf8e" : theme.color.textDim} /></View>
              <View style={styles.compCell}><Ionicons name={c ? "checkmark" : "close"} size={18} color={c ? "#3ecf8e" : theme.color.textDim} /></View>
              <View style={styles.compCell}><Ionicons name={p ? "checkmark" : "close"} size={18} color={p ? "#3ecf8e" : theme.color.textDim} /></View>
            </View>
          ))}
        </View>

        {/* -------- Guide -------- */}
        <Text style={styles.sectionTitle}>Which membership is right for me?</Text>
        <View style={styles.guideCard}>
          <Text style={styles.guideItem}><Text style={styles.guideBullet}>Choose Access</Text> if you mainly want the app and roster-aware training, and you are comfortable managing your own programme independently.</Text>
          <Text style={styles.guideItem}><Text style={styles.guideBullet}>Choose Coaching</Text> if you want a coach personally managing your training, weekly feedback and accountability, and support on difficult flying weeks.</Text>
          <Text style={styles.guideItem}><Text style={styles.guideBullet}>Choose Performance</Text> if you want weekly live contact, priority access, and have a major performance or fitness goal.</Text>
          <Text style={styles.guideFooter}>Not sure? Most members choose Coaching.</Text>
        </View>

        <View style={{ height: 60 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

function prettyStatus(s: string): string {
  return {
    "beta": "Beta access",
    "complimentary": "Complimentary",
    "payment_required": "Payment required",
    "active": "Active",
    "past_due": "Payment past due",
    "cancellation_scheduled": "Active · cancelling",
    "cancelled": "Cancelled",
    "expired": "Expired",
  }[s] || (s.charAt(0).toUpperCase() + s.slice(1));
}
function intervalToWord(i: Interval): string {
  return i === "monthly" ? "month" : i === "quarterly" ? "3 months" : "6 months";
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.bg },
  scroll: { padding: theme.space.lg, paddingBottom: 40 },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: theme.space.lg },
  backBtn: { width: 32, height: 32, alignItems: "center", justifyContent: "center" },
  title: { color: theme.color.text, fontSize: 20, fontWeight: "800", letterSpacing: 0.4 },

  statusCard: {
    backgroundColor: theme.color.surface2, borderRadius: theme.radius.lg,
    padding: theme.space.lg, borderWidth: 1, borderColor: theme.color.border,
    marginBottom: theme.space.lg,
  },
  statusLabel: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1.6, fontWeight: "700" },
  statusValue: { color: theme.color.text, fontSize: 22, fontWeight: "800" },
  statusSub: { color: theme.color.textMuted, fontSize: 12, lineHeight: 18, marginTop: 8 },
  foundingBadge: { backgroundColor: "#f7b95533", borderRadius: 999, paddingHorizontal: 8, paddingVertical: 3, borderWidth: 1, borderColor: "#f7b955" },
  foundingBadgeText: { color: "#f7b955", fontSize: 10, letterSpacing: 1, fontWeight: "800" },
  tierBadgeInline: { backgroundColor: theme.color.brand + "33", borderRadius: 999, paddingHorizontal: 8, paddingVertical: 3, borderWidth: 1, borderColor: theme.color.brand },
  tierBadgeInlineText: { color: theme.color.text, fontSize: 10, letterSpacing: 1, fontWeight: "800" },

  portalBtn: {
    marginTop: theme.space.md, alignSelf: "flex-start",
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 12, paddingVertical: 8,
    borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border,
  },
  portalBtnText: { color: theme.color.text, fontSize: 11, letterSpacing: 1.4, fontWeight: "700" },

  intervalRow: {
    flexDirection: "row", backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border,
    marginBottom: theme.space.lg, overflow: "hidden",
  },
  intervalBtn: { flex: 1, paddingVertical: 12, alignItems: "center" },
  intervalBtnActive: { backgroundColor: theme.color.brand },
  intervalBtnText: { color: theme.color.textMuted, fontWeight: "700", fontSize: 12, letterSpacing: 1 },
  intervalBtnTextActive: { color: "#fff" },

  tierColumn: { gap: theme.space.lg },
  tierCard: {
    backgroundColor: theme.color.surface2, borderRadius: theme.radius.lg,
    padding: theme.space.lg, borderWidth: 1, borderColor: theme.color.border,
  },
  tierCardRecommended: {
    borderColor: theme.color.brand, borderWidth: 2,
    backgroundColor: theme.color.surface3,
  },
  recommendedBadge: {
    position: "absolute", top: -10, right: 16,
    backgroundColor: theme.color.brand, paddingHorizontal: 10, paddingVertical: 4,
    borderRadius: 999,
  },
  recommendedBadgeText: { color: "#fff", fontSize: 10, letterSpacing: 1.5, fontWeight: "800" },
  tierLabel: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1.4, fontWeight: "700" },
  tierName: { color: theme.color.text, fontSize: 20, fontWeight: "800", marginTop: 4 },
  tierHeadline: { color: theme.color.text, fontSize: 14, marginTop: 4, opacity: 0.9, fontWeight: "600" },
  priceRow: { flexDirection: "row", alignItems: "baseline", marginTop: theme.space.md, gap: 8 },
  priceLarge: { color: theme.color.text, fontSize: 30, fontWeight: "800" },
  priceUnit: { color: theme.color.textMuted, fontSize: 12 },
  saveText: { color: "#3ecf8e", fontSize: 12, fontWeight: "700", marginTop: 4 },
  foundingPriceNote: { color: "#f7b955", fontSize: 11, marginTop: 2, fontWeight: "600" },
  tierCopy: { color: theme.color.textMuted, fontSize: 13, lineHeight: 19, marginTop: theme.space.md },
  tierNote: { color: theme.color.textDim, fontSize: 11, lineHeight: 15, marginTop: 6, fontStyle: "italic" },
  subscribeBtn: {
    marginTop: theme.space.lg, backgroundColor: theme.color.surface3,
    paddingVertical: 14, borderRadius: theme.radius.md, alignItems: "center",
    borderWidth: 1, borderColor: theme.color.border, minHeight: 48, justifyContent: "center",
  },
  subscribeBtnStrong: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  subscribeBtnText: { color: "#fff", fontWeight: "800", letterSpacing: 1.6, fontSize: 13 },
  autoRenewText: { color: theme.color.textDim, fontSize: 10, marginTop: 8, textAlign: "center" },

  sectionTitle: { color: theme.color.text, fontWeight: "800", fontSize: 16, marginTop: theme.space.xl, marginBottom: theme.space.md },
  comparisonWrap: {
    backgroundColor: theme.color.surface2, borderRadius: theme.radius.md,
    borderWidth: 1, borderColor: theme.color.border, overflow: "hidden",
  },
  compRow: { flexDirection: "row", borderBottomWidth: StyleSheet.hairlineWidth, borderColor: theme.color.border, alignItems: "center", paddingVertical: 10, paddingHorizontal: 12 },
  compHeaderRow: { backgroundColor: theme.color.surface3 },
  compHeaderCell: { color: theme.color.text, fontSize: 12, fontWeight: "800", letterSpacing: 0.6, textAlign: "center" },
  compFeature: { color: theme.color.text, fontSize: 13 },
  compCell: { flex: 1, alignItems: "center" },
  compHeadCell: { flex: 1, alignItems: "center" },

  guideCard: {
    backgroundColor: theme.color.surface2, borderRadius: theme.radius.md,
    padding: theme.space.lg, borderWidth: 1, borderColor: theme.color.border,
    gap: 10,
  },
  guideItem: { color: theme.color.textMuted, fontSize: 13, lineHeight: 19 },
  guideBullet: { color: theme.color.text, fontWeight: "800" },
  guideFooter: { color: theme.color.text, fontSize: 13, fontWeight: "700", marginTop: 6, textAlign: "center" },
});
