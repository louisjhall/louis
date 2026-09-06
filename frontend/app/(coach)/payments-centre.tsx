/**
 * Coach Payments Centre — Iter201 · Phase 1 Payments.
 *
 * Reads:
 *   GET /api/admin/memberships/overview
 *   GET /api/admin/memberships/clients
 *
 * Writes (per-row action bar):
 *   POST /api/admin/memberships/set-payment-required
 *   POST /api/admin/memberships/grant-complimentary
 *   POST /api/admin/memberships/restore-founding-eligibility
 *
 * Presentation-only — never touches Stripe.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TextInput, Pressable,
  ActivityIndicator, RefreshControl, Alert, Platform, Linking,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type ClientRow = {
  id: string; name: string; email: string;
  membership_status: string | null;
  membership_tier: string | null;
  is_founding_member?: boolean;
  founding_eligible?: boolean;
  payment_required_at?: string | null;
  stripe_customer_id?: string | null;
  subscription?: null | {
    status?: string; interval?: string;
    current_period_end?: string; cancel_at_period_end?: boolean;
  };
};

type Overview = {
  counts_by_status: Record<string, number>;
  counts_by_tier: Record<string, number>;
  active_paid: number;
};

const FILTERS: { key: string; label: string; match: (r: ClientRow) => boolean }[] = [
  { key: "all", label: "All", match: () => true },
  { key: "beta", label: "Beta", match: (r) => r.membership_status === "beta" },
  { key: "complimentary", label: "Complimentary", match: (r) => r.membership_status === "complimentary" },
  { key: "payment_required", label: "Payment Req'd", match: (r) => r.membership_status === "payment_required" },
  { key: "access", label: "Access", match: (r) => r.membership_tier === "access" },
  { key: "coaching", label: "Coaching", match: (r) => r.membership_tier === "coaching" },
  { key: "performance", label: "Performance", match: (r) => r.membership_tier === "performance" },
  { key: "past_due", label: "Past Due", match: (r) => r.membership_status === "past_due" },
  { key: "cancellation_scheduled", label: "Cancelling", match: (r) => r.membership_status === "cancellation_scheduled" },
  { key: "cancelled", label: "Cancelled", match: (r) => r.membership_status === "cancelled" || r.membership_status === "expired" },
];

function niceDate(iso?: string | null): string {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleDateString("en-GB"); } catch { return "—"; }
}

async function confirm(msg: string): Promise<boolean> {
  if (Platform.OS === "web" && typeof window !== "undefined") {
    return window.confirm(msg);
  }
  return new Promise((resolve) => {
    Alert.alert("Confirm", msg, [
      { text: "Cancel", style: "cancel", onPress: () => resolve(false) },
      { text: "Confirm", style: "destructive", onPress: () => resolve(true) },
    ]);
  });
}

export default function PaymentsCentre() {
  const router = useRouter();
  const [overview, setOverview] = useState<Overview | null>(null);
  const [rows, setRows] = useState<ClientRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("all");
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [o, c] = await Promise.all([
        api<Overview>("/admin/memberships/overview"),
        api<{ clients: ClientRow[] }>("/admin/memberships/clients"),
      ]);
      setOverview(o);
      setRows(c.clients || []);
    } finally {
      setLoading(false); setRefreshing(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const filtered = useMemo(() => {
    const f = FILTERS.find((x) => x.key === filter) || FILTERS[0];
    const query = q.trim().toLowerCase();
    return rows.filter((r) => f.match(r) && (
      !query || (r.name || "").toLowerCase().includes(query) || (r.email || "").toLowerCase().includes(query)
    ));
  }, [rows, filter, q]);

  const runAction = useCallback(async (
    action: "set-payment-required" | "grant-complimentary" | "restore-founding-eligibility",
    row: ClientRow,
  ) => {
    const msg = {
      "set-payment-required": `Set ${row.name} to Payment Required? They'll lose access to paid features until they pay.`,
      "grant-complimentary": `Grant ${row.name} complimentary access? No charge will be made.`,
      "restore-founding-eligibility": `Restore founding eligibility for ${row.name}? They'll see founding prices on their next checkout.`,
    }[action];
    if (!(await confirm(msg))) return;
    setBusy(row.id + action);
    try {
      await api(`/admin/memberships/${action}`, { method: "POST", body: { user_id: row.id } });
      await load();
    } catch (e: any) {
      Alert.alert("Failed", e?.message || "Action failed.");
    } finally {
      setBusy(null);
    }
  }, [load]);

  const openStripe = (row: ClientRow) => {
    if (!row.stripe_customer_id) {
      Alert.alert("No Stripe customer yet",
        `${row.name} has no Stripe customer id — they haven't started a checkout. Nothing to open.`);
      return;
    }
    const url = `https://dashboard.stripe.com/customers/${row.stripe_customer_id}`;
    if (Platform.OS === "web" && typeof window !== "undefined") {
      window.open(url, "_blank");
    } else {
      Linking.openURL(url).catch(() => {});
    }
  };

  if (loading) {
    return (
      <View style={[styles.root, { justifyContent: "center", alignItems: "center" }]}>
        <ActivityIndicator color={theme.color.brand} />
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} style={{ padding: 4 }}>
          <Ionicons name="chevron-back" size={22} color={theme.color.text} />
        </Pressable>
        <Text style={styles.headerTitle}>Payments Centre</Text>
        <View style={{ width: 32 }} />
      </View>

      <ScrollView
        contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 40 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
      >
        {/* Overview strip */}
        {overview ? (
          <View style={styles.stripWrap}>
            {[
              ["Active Paid", overview.active_paid],
              ["Access", overview.counts_by_tier.access || 0],
              ["Coaching", overview.counts_by_tier.coaching || 0],
              ["Performance", overview.counts_by_tier.performance || 0],
              ["Beta", overview.counts_by_status.beta || 0],
              ["Complimentary", overview.counts_by_status.complimentary || 0],
              ["Payment Req'd", overview.counts_by_status.payment_required || 0],
              ["Past Due", overview.counts_by_status.past_due || 0],
            ].map(([label, n]) => (
              <View key={String(label)} style={styles.stripCard}>
                <Text style={styles.stripNum}>{n}</Text>
                <Text style={styles.stripLabel}>{String(label)}</Text>
              </View>
            ))}
          </View>
        ) : null}

        {/* Search + filter chips */}
        <TextInput
          placeholder="Search by name or email"
          placeholderTextColor={theme.color.textDim}
          style={styles.search}
          value={q}
          onChangeText={setQ}
          autoCapitalize="none"
          autoCorrect={false}
        />
        <View style={styles.chipsWrap}>
          {FILTERS.map((f) => {
            const active = f.key === filter;
            return (
              <Pressable
                key={f.key}
                onPress={() => setFilter(f.key)}
                style={[styles.chip, active && styles.chipActive]}
              >
                <Text style={[styles.chipText, active && styles.chipTextActive]}>{f.label}</Text>
              </Pressable>
            );
          })}
        </View>

        <Text style={styles.countLine}>{filtered.length} of {rows.length} clients</Text>

        {/* Client rows */}
        <View style={{ gap: 8 }}>
          {filtered.map((r) => (
            <View key={r.id} style={styles.row}>
              <View style={{ flexDirection: "row", alignItems: "flex-start", gap: 8 }}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowName}>{r.name || r.email}</Text>
                  <Text style={styles.rowEmail}>{r.email}</Text>
                  <View style={styles.rowMeta}>
                    <Chip color={statusColor(r.membership_status)} label={r.membership_status || "—"} />
                    {r.membership_tier && r.membership_tier !== "none" ? <Chip color={theme.color.brand} label={r.membership_tier} /> : null}
                    {r.is_founding_member ? <Chip color="#f7b955" label="founding" /> : null}
                    {r.founding_eligible && !r.is_founding_member ? <Chip color="#f7b955" label="founding-eligible" outline /> : null}
                    {r.subscription?.cancel_at_period_end ? <Chip color="#e0a34e" label="cancelling" /> : null}
                  </View>
                  <Text style={styles.rowSub}>
                    {r.subscription?.interval ? `${r.subscription.interval} · ` : ""}
                    Next renewal: {niceDate(r.subscription?.current_period_end)}
                    {r.payment_required_at ? `   ·   Payment req'd: ${niceDate(r.payment_required_at)}` : ""}
                  </Text>
                </View>
              </View>

              {/* Per-row actions */}
              <View style={styles.actionsRow}>
                <ActionBtn
                  label="PAYMENT REQ"
                  disabled={!!busy}
                  loading={busy === r.id + "set-payment-required"}
                  onPress={() => runAction("set-payment-required", r)}
                />
                <ActionBtn
                  label="COMP"
                  disabled={!!busy}
                  loading={busy === r.id + "grant-complimentary"}
                  onPress={() => runAction("grant-complimentary", r)}
                />
                <ActionBtn
                  label="FOUNDING"
                  disabled={!!busy}
                  loading={busy === r.id + "restore-founding-eligibility"}
                  onPress={() => runAction("restore-founding-eligibility", r)}
                />
                <ActionBtn label="STRIPE" onPress={() => openStripe(r)} tinted />
              </View>
            </View>
          ))}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function statusColor(s: string | null | undefined): string {
  switch (s) {
    case "active": return "#3ecf8e";
    case "complimentary": return "#3ecf8e";
    case "beta": return "#5aa1ff";
    case "payment_required": return theme.color.brand;
    case "past_due": return theme.color.brand;
    case "cancellation_scheduled": return "#e0a34e";
    case "cancelled":
    case "expired": return theme.color.textDim;
    default: return theme.color.textMuted;
  }
}

function Chip({ color, label, outline = false }: { color: string; label: string; outline?: boolean }) {
  return (
    <View style={[
      chipStyles.chip,
      outline ? { borderColor: color, backgroundColor: "transparent" } : { backgroundColor: color + "22", borderColor: color },
    ]}>
      <Text style={[chipStyles.text, { color }]}>{label.toUpperCase()}</Text>
    </View>
  );
}

function ActionBtn({ label, onPress, disabled, loading, tinted }: {
  label: string; onPress: () => void; disabled?: boolean; loading?: boolean; tinted?: boolean;
}) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled || loading}
      style={({ pressed }) => [
        styles.actionBtn,
        tinted && { backgroundColor: theme.color.brand + "33", borderColor: theme.color.brand },
        (disabled || pressed || loading) && { opacity: 0.65 },
      ]}
    >
      {loading ? <ActivityIndicator size="small" color={theme.color.text} /> : (
        <Text style={styles.actionBtnText}>{label}</Text>
      )}
    </Pressable>
  );
}

const chipStyles = StyleSheet.create({
  chip: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 999, borderWidth: 1 },
  text: { fontSize: 9, fontWeight: "800", letterSpacing: 1 },
});

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.bg },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: theme.space.lg, paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth, borderColor: theme.color.border,
  },
  headerTitle: { color: theme.color.text, fontSize: 16, fontWeight: "800", letterSpacing: 0.4 },

  stripWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: theme.space.lg },
  stripCard: {
    minWidth: 88, flexGrow: 1,
    backgroundColor: theme.color.surface2, borderRadius: theme.radius.md,
    borderWidth: 1, borderColor: theme.color.border,
    padding: 10, alignItems: "flex-start",
  },
  stripNum: { color: theme.color.text, fontSize: 22, fontWeight: "800" },
  stripLabel: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 1.2, fontWeight: "700", marginTop: 2 },

  search: {
    backgroundColor: theme.color.surface2, color: theme.color.text,
    borderWidth: 1, borderColor: theme.color.border,
    borderRadius: theme.radius.md, paddingHorizontal: 12, paddingVertical: 10, fontSize: 14,
    marginBottom: 8,
  },
  chipsWrap: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 8 },
  chip: {
    paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999,
    borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface2,
  },
  chipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipText: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 0.5, fontWeight: "700" },
  chipTextActive: { color: "#fff" },

  countLine: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1, fontWeight: "700", marginBottom: 8 },

  row: {
    backgroundColor: theme.color.surface2, borderRadius: theme.radius.md,
    borderWidth: 1, borderColor: theme.color.border, padding: 12, gap: 10,
  },
  rowName: { color: theme.color.text, fontSize: 14, fontWeight: "800" },
  rowEmail: { color: theme.color.textMuted, fontSize: 11 },
  rowMeta: { flexDirection: "row", flexWrap: "wrap", gap: 5, marginTop: 6 },
  rowSub: { color: theme.color.textDim, fontSize: 10, marginTop: 6 },

  actionsRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  actionBtn: {
    paddingVertical: 6, paddingHorizontal: 10,
    borderRadius: theme.radius.sm,
    borderWidth: 1, borderColor: theme.color.border,
    backgroundColor: theme.color.surface3,
    minWidth: 78, alignItems: "center", justifyContent: "center",
  },
  actionBtnText: { color: theme.color.text, fontSize: 10, letterSpacing: 1.2, fontWeight: "800" },
});
