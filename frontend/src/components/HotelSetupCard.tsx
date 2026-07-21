/**
 * HotelSetupCard — shows on the client home when we detect an upcoming layover
 * with either NO hotel attached OR a low-confidence hotel that needs re-confirming.
 *
 * Tapping the card opens `/hotel-setup?date=YYYY-MM-DD` for the earliest pending day.
 */
import { useEffect, useState, useCallback } from "react";
import { View, Text, Pressable, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

export type PendingHotel = {
  date: string;
  layover_city?: string | null;
  layover_country?: string | null;
  hotel_id: string | null;
  hotel_name?: string | null;
  status: "missing" | "needs_confirm";
  kind: "layover";
  confidence?: number;
};

export function HotelSetupCard({ refreshKey }: { refreshKey?: number }) {
  const router = useRouter();
  const [pending, setPending] = useState<PendingHotel[] | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await api<PendingHotel[]>("/hotels/pending-for-today").catch(() => []);
      setPending(Array.isArray(rows) ? rows : []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load, refreshKey]);

  if (loading && !pending) {
    return null;
  }
  if (!pending || pending.length === 0) return null;

  const first = pending[0];
  const missing = first.status === "missing";
  const count = pending.length;
  const cityLine = first.layover_city
    ? `${first.layover_city}${first.layover_country ? `, ${first.layover_country}` : ""}`
    : "Layover";

  return (
    <Pressable
      testID="hotel-setup-card"
      onPress={() => router.push({ pathname: "/hotel-setup", params: { date: first.date } })}
      style={styles.card}
    >
      <View style={styles.iconWrap}>
        <Ionicons name="bed" size={20} color={theme.color.brand} />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.title}>
          {missing ? "HOTEL SETUP · LAYOVER AHEAD" : "CONFIRM HOTEL GYM"}
        </Text>
        <Text style={styles.body}>
          {missing
            ? `${cityLine} — tell us the gym setup so your workout matches the equipment.`
            : `${cityLine} — quick confirm the gym setup so we can dial your session in.`}
        </Text>
        {count > 1 ? (
          <Text style={styles.sub}>+ {count - 1} more layover{count > 2 ? "s" : ""} to set up</Text>
        ) : null}
      </View>
      <View style={styles.chev}>
        <Text style={styles.chevText}>SET UP →</Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: theme.color.surface2,
    borderRadius: 12,
    padding: 14,
    borderLeftWidth: 4,
    borderLeftColor: theme.color.brand,
    marginBottom: 12,
    gap: 12,
  },
  iconWrap: {
    width: 40, height: 40, borderRadius: 20,
    backgroundColor: "rgba(163,24,46,0.18)",
    alignItems: "center", justifyContent: "center",
  },
  title: {
    fontSize: 12,
    fontWeight: "700",
    color: theme.color.brand,
    letterSpacing: 0.5,
    marginBottom: 2,
  },
  body: {
    fontSize: 13,
    color: theme.color.text,
    lineHeight: 18,
  },
  sub: {
    fontSize: 11,
    color: theme.color.textDim,
    marginTop: 3,
  },
  chev: {
    paddingHorizontal: 4,
  },
  chevText: {
    fontSize: 11,
    fontWeight: "700",
    color: theme.color.brand,
    letterSpacing: 0.5,
  },
});
