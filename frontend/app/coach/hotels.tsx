/**
 * /coach/hotels — Coach Hotel Review Queue (Phase 4 of Master Fix Prompt).
 *
 * Lists all low-confidence unverified hotel profiles submitted by clients.
 * The coach can:
 *   * Toggle equipment items on each hotel (PATCH /api/hotels/{id})
 *   * Verify a hotel — bumps confidence + flags verified_by_coach
 *     (POST /api/coach/hotels/{id}/verify)
 */
import { useCallback, useEffect, useState } from "react";
import {
  View, Text, ScrollView, Pressable, StyleSheet, ActivityIndicator, RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast } from "@/src/lib/ux";

type Hotel = {
  id: string;
  name: string;
  city: string;
  country?: string | null;
  gym_type?: string;
  gym_available?: boolean;
  equipment?: Record<string, boolean>;
  safe_outdoor_run?: boolean;
  confidence?: number;
  submissions?: number;
  last_confirmed_at?: string;
  verified_by_coach?: boolean;
  notes?: string;
};

const GYM_TYPE_LABEL: Record<string, string> = {
  full_gym: "FULL GYM",
  cardio_only: "CARDIO ONLY",
  basic: "BASIC",
  bodyweight_only: "BODYWEIGHT",
  none: "NO GYM",
  unknown: "UNKNOWN",
};

const EQUIPMENT_ITEMS = [
  { key: "dumbbells", label: "Dumbbells" },
  { key: "barbell", label: "Barbell" },
  { key: "bench", label: "Bench" },
  { key: "cable_stack", label: "Cable stack" },
  { key: "smith_machine", label: "Smith machine" },
  { key: "treadmill", label: "Treadmill" },
  { key: "stationary_bike", label: "Bike" },
  { key: "rowing_machine", label: "Rower" },
  { key: "kettlebell", label: "Kettlebell" },
  { key: "resistance_bands", label: "Bands" },
  { key: "pull_up_bar", label: "Pull-up bar" },
  { key: "yoga_mat", label: "Mat" },
];

export default function CoachHotelsReviewScreen() {
  const router = useRouter();
  const [hotels, setHotels] = useState<Hotel[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const rows = await api<Hotel[]>("/coach/hotels/review-queue").catch(() => []);
      setHotels(Array.isArray(rows) ? rows : []);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const onRefresh = () => { setRefreshing(true); load(); };

  const toggleEquipment = async (h: Hotel, key: string) => {
    const merged = { ...(h.equipment || {}), [key]: !(h.equipment?.[key]) };
    setBusyId(h.id);
    try {
      const updated = await api<Hotel>(`/hotels/${h.id}`, {
        method: "PATCH",
        body: { equipment: merged },
      });
      setHotels((prev) => prev.map((x) => (x.id === h.id ? { ...x, ...updated } : x)));
    } catch (e: any) {
      toast(e?.message || "Couldn't update", "error");
    } finally {
      setBusyId(null);
    }
  };

  const verify = async (h: Hotel) => {
    setBusyId(h.id);
    try {
      await api(`/coach/hotels/${h.id}/verify`, { method: "POST" });
      toast(`${h.name} verified`, "success");
      // Remove from queue on success
      setHotels((prev) => prev.filter((x) => x.id !== h.id));
    } catch (e: any) {
      toast(e?.message || "Couldn't verify", "error");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} style={styles.backBtn} testID="coach-hotels-back">
            <Ionicons name="chevron-back" size={22} color={theme.color.text} />
          </Pressable>
          <View style={{ flex: 1 }}>
            <Text style={styles.hTitle}>HOTEL REVIEW QUEUE</Text>
            <Text style={styles.hSub}>
              {hotels.length} hotel{hotels.length !== 1 ? "s" : ""} awaiting your verification
            </Text>
          </View>
        </View>
      </SafeAreaView>

      {loading ? (
        <View style={{ padding: theme.space.xl, alignItems: "center" }}>
          <ActivityIndicator color={theme.color.brand} />
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 60 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.color.brand} />}
        >
          {hotels.length === 0 ? (
            <View style={styles.empty} testID="coach-hotels-empty">
              <Ionicons name="checkmark-circle-outline" size={32} color={theme.color.green} />
              <Text style={styles.emptyTitle}>Queue is clear</Text>
              <Text style={styles.emptyBody}>
                Nothing to verify right now. New client submissions will appear here once they drop below 70% confidence.
              </Text>
            </View>
          ) : (
            hotels.map((h) => {
              const confPct = Math.round((h.confidence || 0) * 100);
              const isBusy = busyId === h.id;
              return (
                <View key={h.id} style={styles.card} testID={`coach-hotel-${h.id}`}>
                  <View style={styles.cardHead}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.hotelName}>{h.name}</Text>
                      <Text style={styles.hotelSub}>
                        {h.city}{h.country ? `, ${h.country}` : ""}
                      </Text>
                    </View>
                    <View style={styles.confPill}>
                      <Text style={styles.confPillText}>{confPct}%</Text>
                    </View>
                  </View>

                  <View style={styles.metaRow}>
                    <View style={styles.metaChip}>
                      <Ionicons name="fitness" size={11} color={theme.color.textMuted} />
                      <Text style={styles.metaChipText}>
                        {GYM_TYPE_LABEL[h.gym_type || "unknown"] || h.gym_type}
                      </Text>
                    </View>
                    <View style={styles.metaChip}>
                      <Ionicons name="people" size={11} color={theme.color.textMuted} />
                      <Text style={styles.metaChipText}>{h.submissions || 1} submission{(h.submissions || 1) !== 1 ? "s" : ""}</Text>
                    </View>
                    {h.safe_outdoor_run ? (
                      <View style={styles.metaChip}>
                        <Ionicons name="walk" size={11} color={theme.color.green} />
                        <Text style={styles.metaChipText}>OUTDOOR SAFE</Text>
                      </View>
                    ) : null}
                  </View>

                  <Text style={styles.subHead}>EQUIPMENT (TAP TO TOGGLE)</Text>
                  <View style={styles.chipRow}>
                    {EQUIPMENT_ITEMS.map((eq) => {
                      const on = !!h.equipment?.[eq.key];
                      return (
                        <Pressable
                          key={eq.key}
                          onPress={() => !isBusy && toggleEquipment(h, eq.key)}
                          disabled={isBusy}
                          testID={`coach-hotel-${h.id}-eq-${eq.key}`}
                          style={[styles.chip, on && styles.chipOn]}
                        >
                          {on ? <Ionicons name="checkmark" size={11} color={theme.color.onBrand} style={{ marginRight: 3 }} /> : null}
                          <Text style={[styles.chipText, on && styles.chipTextOn]}>{eq.label}</Text>
                        </Pressable>
                      );
                    })}
                  </View>

                  {h.notes ? (
                    <View style={styles.notes}>
                      <Text style={styles.notesLabel}>CLIENT NOTES</Text>
                      <Text style={styles.notesText}>{h.notes}</Text>
                    </View>
                  ) : null}

                  <Pressable
                    onPress={() => verify(h)}
                    disabled={isBusy}
                    testID={`coach-hotel-${h.id}-verify`}
                    style={[styles.verifyBtn, isBusy && { opacity: 0.5 }]}
                  >
                    {isBusy ? (
                      <ActivityIndicator size="small" color={theme.color.onBrand} />
                    ) : (
                      <>
                        <Ionicons name="shield-checkmark" size={14} color={theme.color.onBrand} />
                        <Text style={styles.verifyBtnText}>VERIFY HOTEL</Text>
                      </>
                    )}
                  </Pressable>
                </View>
              );
            })
          )}
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: {
    flexDirection: "row", alignItems: "center", padding: theme.space.lg, gap: 12,
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  backBtn: {
    width: 36, height: 36, borderRadius: 18,
    alignItems: "center", justifyContent: "center",
    backgroundColor: theme.color.surface2,
  },
  hTitle: { fontSize: 14, fontWeight: "700", color: theme.color.text, letterSpacing: 0.5 },
  hSub: { fontSize: 12, color: theme.color.textMuted, marginTop: 2 },

  empty: { alignItems: "center", padding: theme.space.xxl, gap: theme.space.md },
  emptyTitle: { fontSize: 14, fontWeight: "700", color: theme.color.text, letterSpacing: 0.5 },
  emptyBody: { fontSize: 13, color: theme.color.textMuted, textAlign: "center", lineHeight: 19 },

  card: {
    backgroundColor: theme.color.surface2,
    borderRadius: 12,
    padding: 14,
    marginBottom: 12,
    borderLeftWidth: 3,
    borderLeftColor: theme.color.amber,
  },
  cardHead: {
    flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between",
    marginBottom: 8,
  },
  hotelName: { fontSize: 15, fontWeight: "700", color: theme.color.text },
  hotelSub: { fontSize: 12, color: theme.color.textMuted, marginTop: 2 },
  confPill: {
    paddingHorizontal: 8, paddingVertical: 3,
    borderRadius: 999,
    backgroundColor: "rgba(245,158,11,0.15)",
  },
  confPillText: { fontSize: 11, fontWeight: "800", color: "#B45309", letterSpacing: 0.5 },

  metaRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: theme.space.md },
  metaChip: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 8, paddingVertical: 4,
    borderRadius: 6,
    backgroundColor: theme.color.surface,
    borderWidth: 1, borderColor: theme.color.border,
  },
  metaChipText: { fontSize: 10.5, fontWeight: "700", color: theme.color.textMuted, letterSpacing: 0.4 },

  subHead: {
    fontSize: 10, fontWeight: "800", color: theme.color.textMuted,
    letterSpacing: 0.8, marginBottom: theme.space.sm, marginTop: theme.space.xs,
  },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: theme.space.md },
  chip: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: 10, paddingVertical: 6,
    borderRadius: 999,
    backgroundColor: theme.color.surface,
    borderWidth: 1, borderColor: theme.color.border,
  },
  chipOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipText: { fontSize: 11, color: theme.color.textMuted, fontWeight: "600" },
  chipTextOn: { color: theme.color.onBrand },

  notes: {
    marginTop: theme.space.sm,
    padding: 10,
    backgroundColor: theme.color.surface,
    borderRadius: 8,
    borderLeftWidth: 2, borderLeftColor: theme.color.textMuted,
    marginBottom: theme.space.md,
  },
  notesLabel: { fontSize: 10, fontWeight: "800", color: theme.color.textMuted, letterSpacing: 0.5, marginBottom: 3 },
  notesText: { fontSize: 12, color: theme.color.text, lineHeight: 17 },

  verifyBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    padding: 12,
    borderRadius: 8,
    backgroundColor: theme.color.brand,
  },
  verifyBtnText: { color: theme.color.onBrand, fontWeight: "700", letterSpacing: 0.6, fontSize: 12 },
});
