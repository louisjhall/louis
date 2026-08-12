/**
 * /hotel-setup?date=YYYY-MM-DD
 *
 * Client flow for setting up (or confirming) the hotel gym setup for a specific
 * layover day on the roster. Three steps:
 *   1. Pick a hotel (fuzzy search) OR add a new one (name + city)
 *   2. Pick gym_type (full_gym / cardio_only / basic / bodyweight_only / none)
 *   3. Toggle specific equipment items (chips)
 *
 * On save:
 *   - Upserts /api/hotels
 *   - Attaches the hotel_id to the roster day via /api/roster/{rid}/hotel
 *   - Confirms via /api/hotels/{id}/confirm to bump confidence
 */
import { useEffect, useMemo, useState } from "react";
import {
  View, Text, ScrollView, Pressable, TextInput, StyleSheet, ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast } from "@/src/lib/ux";

type GymType = "full_gym" | "cardio_only" | "basic" | "bodyweight_only" | "none" | "unknown";

const GYM_TYPES: { key: GymType; label: string; blurb: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { key: "full_gym",         label: "FULL GYM",       blurb: "Weights + cardio + benches",     icon: "barbell" },
  { key: "cardio_only",      label: "CARDIO ONLY",    blurb: "Treadmill / bike / rower",       icon: "walk" },
  { key: "basic",            label: "BASIC",          blurb: "Dumbbells + mat",                icon: "fitness" },
  { key: "bodyweight_only",  label: "BODYWEIGHT ONLY",blurb: "Room-only session",              icon: "body" },
  { key: "none",             label: "NO GYM",         blurb: "Nothing at this hotel",          icon: "close-circle" },
];

const EQUIPMENT: { key: string; label: string }[] = [
  { key: "dumbbells",         label: "Dumbbells" },
  { key: "barbell",           label: "Barbell" },
  { key: "bench",             label: "Bench" },
  { key: "cable_stack",       label: "Cable stack" },
  { key: "smith_machine",     label: "Smith machine" },
  { key: "treadmill",         label: "Treadmill" },
  { key: "stationary_bike",   label: "Stationary bike" },
  { key: "rowing_machine",    label: "Rower" },
  { key: "kettlebell",        label: "Kettlebell" },
  { key: "resistance_bands",  label: "Resistance bands" },
  { key: "pull_up_bar",       label: "Pull-up bar" },
  { key: "yoga_mat",          label: "Yoga mat" },
  { key: "pool",              label: "Pool" },
];

// Small wrapper to keep call-sites simple — surfaces as native Alert on mobile,
// animated toast on web (both via @/src/lib/ux).
function Alert(title: string, _body?: string, kind: "info" | "error" | "success" = "success") {
  toast(title, kind === "error" ? "error" : "success");
}

export default function HotelSetup() {
  const router = useRouter();
  const params = useLocalSearchParams<{ date?: string }>();
  const date = String(params?.date || "");

  const [roster, setRoster] = useState<any>(null);
  const [dayInfo, setDayInfo] = useState<{ layover_city?: string | null; layover_country?: string | null; hotel_id?: string | null; hotel_name?: string | null } | null>(null);

  const [hotelName, setHotelName] = useState("");
  const [city, setCity] = useState("");
  const [country, setCountry] = useState("");
  const [gymType, setGymType] = useState<GymType>("unknown");
  const [equipment, setEquipment] = useState<Record<string, boolean>>({});
  const [safeOutdoor, setSafeOutdoor] = useState<boolean>(false);
  const [notes, setNotes] = useState("");

  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [, setSelectedHotelId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);

  // Load roster & day info on mount
  useEffect(() => {
    (async () => {
      try {
        const r = await api<any>("/roster/current");
        setRoster(r && r.id ? r : null);
        if (r?.days) {
          const d = r.days.find((x: any) => x.date === date);
          if (d) {
            setDayInfo({
              layover_city: d.layover_city,
              layover_country: d.layover_country,
              hotel_id: d.hotel_id,
              hotel_name: d.hotel_name,
            });
            if (d.layover_city) setCity(d.layover_city);
            if (d.layover_country) setCountry(d.layover_country);
            if (d.hotel_id) {
              // Pre-populate from existing hotel
              try {
                const h = await api<any>(`/hotels/${d.hotel_id}`);
                if (h) prefill(h);
              } catch { /* ignore */ }
            }
          }
        }
      } finally {
        setLoading(false);
      }
    })();
  }, [date]);

  function prefill(h: any) {
    setSelectedHotelId(h.id);
    setHotelName(h.name || "");
    setCity(h.city || "");
    setCountry(h.country || "");
    setGymType((h.gym_type || "unknown") as GymType);
    setEquipment(h.equipment || {});
    setSafeOutdoor(!!h.safe_outdoor_run);
    setNotes(h.notes || "");
  }

  const canSave = useMemo(() => hotelName.trim() && city.trim(), [hotelName, city]);

  const search = async (q: string) => {
    setHotelName(q);
    if (q.trim().length < 2) { setSearchResults([]); return; }
    try {
      const rows = await api<any[]>(`/hotels/lookup?query=${encodeURIComponent(q.trim())}`);
      setSearchResults(rows || []);
    } catch {
      setSearchResults([]);
    }
  };

  const toggleEq = (k: string) => {
    setEquipment((s) => ({ ...s, [k]: !s[k] }));
  };

  const applyGymTypePreset = (gt: GymType) => {
    setGymType(gt);
    // Sensible preset for the equipment map — user can adjust after
    const presets: Record<GymType, Record<string, boolean>> = {
      full_gym: { dumbbells: true, barbell: true, bench: true, cable_stack: true, treadmill: true, kettlebell: true, pull_up_bar: true, yoga_mat: true },
      cardio_only: { treadmill: true, stationary_bike: true, rowing_machine: true, yoga_mat: true },
      basic: { dumbbells: true, resistance_bands: true, yoga_mat: true },
      bodyweight_only: { yoga_mat: true },
      none: {},
      unknown: {},
    };
    setEquipment(presets[gt] || {});
  };

  const save = async () => {
    if (!canSave || !roster) return;
    setSaving(true);
    try {
      // Step 1 — upsert hotel
      const hotel = await api<any>("/hotels", {
        method: "POST",
        body: {
          name: hotelName.trim(),
          city: city.trim(),
          country: country.trim() || undefined,
          gym_type: gymType,
          gym_available: gymType !== "none",
          equipment,
          safe_outdoor_run: safeOutdoor,
          notes: notes.trim() || undefined,
        },
      });

      // Step 2 — attach to roster day
      if (roster?.id && date) {
        try {
          await api(`/roster/${roster.id}/hotel`, {
            method: "POST",
            body: {
              date,
              hotel: {
                name: hotelName.trim(),
                city: city.trim(),
                country: country.trim() || undefined,
                gym_type: gymType,
                equipment,
                safe_outdoor_run: safeOutdoor,
              },
            },
          });
        } catch (e) {
          // Non-fatal — the hotel is created, roster attach may fail for older data
          console.log("[hotel-setup] attach to roster failed", e);
        }
      }

      // Step 3 — bump confidence via confirm
      if (hotel?.id) {
        try {
          await api(`/hotels/${hotel.id}/confirm`, {
            method: "POST",
            body: {
              equipment,
              gym_type: gymType,
              gym_available: gymType !== "none",
              safe_outdoor_run: safeOutdoor,
            },
          });
        } catch { /* non-fatal */ }
      }

      Alert("Saved", "Hotel setup saved — your next workout at this hotel will match the gym.");
      router.back();
    } catch (e: any) {
      Alert("Couldn't save", e?.message || "Please try again.", "error");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.root}>
        <SafeAreaView edges={["top"]}>
          <View style={{ padding: theme.space.xl, alignItems: "center" }}>
            <ActivityIndicator color={theme.color.brand} />
          </View>
        </SafeAreaView>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} style={styles.backBtn} testID="hotel-setup-back">
            <Ionicons name="chevron-back" size={22} color={theme.color.text} />
          </Pressable>
          <View>
            <Text style={styles.headerT}>HOTEL SETUP</Text>
            <Text style={styles.headerSub}>{date}{dayInfo?.layover_city ? ` · ${dayInfo.layover_city}` : ""}</Text>
          </View>
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 60 }}>
        <Text style={styles.section}>1 · HOTEL</Text>
        <TextInput
          testID="hotel-name-input"
          style={styles.input}
          placeholder="Hotel name (e.g. Le Meridien)"
          placeholderTextColor={theme.color.textDim}
          value={hotelName}
          onChangeText={search}
          autoCapitalize="words"
        />
        {searchResults.length > 0 && (
          <View style={styles.results}>
            {searchResults.slice(0, 6).map((h: any) => (
              <Pressable key={h.id} onPress={() => { prefill(h); setSearchResults([]); }} style={styles.resultRow}>
                <Ionicons name="bed" size={14} color={theme.color.brand} />
                <View style={{ flex: 1, marginLeft: 8 }}>
                  <Text style={styles.resultName}>{h.name}</Text>
                  <Text style={styles.resultSub}>{h.city}{h.country ? `, ${h.country}` : ""} · {h.gym_type || "unknown"}</Text>
                </View>
                {h.verified_by_coach ? (
                  <Ionicons name="shield-checkmark" size={14} color={theme.color.green} />
                ) : null}
              </Pressable>
            ))}
          </View>
        )}
        <View style={{ flexDirection: "row", gap: 8 }}>
          <TextInput
            testID="hotel-city-input"
            style={[styles.input, { flex: 1 }]}
            placeholder="City"
            placeholderTextColor={theme.color.textDim}
            value={city}
            onChangeText={setCity}
            autoCapitalize="words"
          />
          <TextInput
            testID="hotel-country-input"
            style={[styles.input, { flex: 1 }]}
            placeholder="Country"
            placeholderTextColor={theme.color.textDim}
            value={country}
            onChangeText={setCountry}
            autoCapitalize="words"
          />
        </View>

        <Text style={styles.section}>2 · GYM TYPE</Text>
        <View style={styles.gymTypeGrid}>
          {GYM_TYPES.map((g) => {
            const active = gymType === g.key;
            return (
              <Pressable
                key={g.key}
                testID={`gym-type-${g.key}`}
                onPress={() => applyGymTypePreset(g.key)}
                style={[styles.gtCard, active && styles.gtCardActive]}
              >
                <Ionicons name={g.icon} size={20} color={active ? theme.color.brand : theme.color.textMuted} />
                <Text style={[styles.gtLabel, active && { color: theme.color.brand }]}>{g.label}</Text>
                <Text style={styles.gtBlurb}>{g.blurb}</Text>
              </Pressable>
            );
          })}
        </View>

        {gymType !== "none" && (
          <>
            <Text style={styles.section}>3 · EQUIPMENT (TAP TO TOGGLE)</Text>
            <View style={styles.chipRow}>
              {EQUIPMENT.map((eq) => {
                const on = !!equipment[eq.key];
                return (
                  <Pressable
                    key={eq.key}
                    testID={`eq-chip-${eq.key}`}
                    onPress={() => toggleEq(eq.key)}
                    style={[styles.chip, on && styles.chipOn]}
                  >
                    {on ? <Ionicons name="checkmark" size={12} color={theme.color.onBrand} style={{ marginRight: 4 }} /> : null}
                    <Text style={[styles.chipText, on && styles.chipTextOn]}>{eq.label}</Text>
                  </Pressable>
                );
              })}
            </View>
          </>
        )}

        <Text style={styles.section}>OUTDOOR RUN</Text>
        <Pressable
          testID="outdoor-run-toggle"
          onPress={() => setSafeOutdoor((s) => !s)}
          style={[styles.toggle, safeOutdoor && styles.toggleOn]}
        >
          <Ionicons name={safeOutdoor ? "checkmark-circle" : "ellipse-outline"} size={20} color={safeOutdoor ? theme.color.green : theme.color.textDim} />
          <Text style={styles.toggleText}>Safe to run outside here</Text>
        </Pressable>

        <Text style={styles.section}>NOTES (OPTIONAL)</Text>
        <TextInput
          testID="hotel-notes-input"
          style={[styles.input, { height: 80, textAlignVertical: "top" }]}
          placeholder="e.g. Gym open 24h, cardio deck on floor 3"
          placeholderTextColor={theme.color.textDim}
          value={notes}
          onChangeText={setNotes}
          multiline
        />

        <Pressable
          testID="hotel-save-btn"
          onPress={save}
          disabled={!canSave || saving}
          style={[styles.saveBtn, (!canSave || saving) && { opacity: 0.5 }]}
        >
          {saving ? <ActivityIndicator color={theme.color.onBrand} /> : (
            <>
              <Ionicons name="checkmark-circle" size={16} color={theme.color.onBrand} />
              <Text style={styles.saveText}>SAVE HOTEL SETUP</Text>
            </>
          )}
        </Pressable>

        <Text style={styles.footNote}>
          Louis will review this setup before your next hotel visit. Confirmed setups help other crew training here too.
        </Text>
      </ScrollView>
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
  headerT: { fontSize: 14, fontWeight: "700", color: theme.color.text, letterSpacing: 0.5 },
  headerSub: { fontSize: 12, color: theme.color.textMuted, marginTop: 2 },

  section: {
    fontSize: 11, fontWeight: "700", color: theme.color.textMuted,
    letterSpacing: 0.8, marginTop: theme.space.xl, marginBottom: theme.space.sm,
  },
  input: {
    backgroundColor: theme.color.surface2,
    borderRadius: 8,
    padding: 12,
    color: theme.color.onRed,
    fontSize: 14,
    borderWidth: 1,
    borderColor: theme.color.border,
    marginBottom: theme.space.sm,
  },
  results: {
    backgroundColor: theme.color.surface2,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: theme.color.border,
    marginBottom: theme.space.sm,
  },
  resultRow: {
    flexDirection: "row", alignItems: "center",
    padding: 12,
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  resultName: { fontSize: 13, color: theme.color.text, fontWeight: "600" },
  resultSub: { fontSize: 11, color: theme.color.textMuted, marginTop: 2 },

  gymTypeGrid: {
    flexDirection: "row", flexWrap: "wrap", gap: theme.space.sm,
  },
  gtCard: {
    width: "48%",
    padding: 12,
    borderRadius: 10,
    backgroundColor: theme.color.surface2,
    borderWidth: 1,
    borderColor: theme.color.border,
    gap: 6,
  },
  gtCardActive: {
    borderColor: theme.color.brand,
    backgroundColor: theme.color.brandTint,
  },
  gtLabel: { fontSize: 12, fontWeight: "700", color: theme.color.text, letterSpacing: 0.5 },
  gtBlurb: { fontSize: 11, color: theme.color.textMuted },

  chipRow: {
    flexDirection: "row", flexWrap: "wrap", gap: 8,
  },
  chip: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: 12, paddingVertical: 8,
    borderRadius: 999,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
    marginBottom: 6,
  },
  chipOn: {
    backgroundColor: theme.color.brand,
    borderColor: theme.color.brand,
  },
  chipText: { fontSize: 12, color: theme.color.textMuted, fontWeight: "600" },
  chipTextOn: { color: theme.color.onBrand },

  toggle: {
    flexDirection: "row", alignItems: "center", gap: 10,
    padding: 12,
    borderRadius: 8,
    backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border,
  },
  toggleOn: {
    borderColor: theme.color.green,
  },
  toggleText: { fontSize: 13, color: theme.color.text },

  saveBtn: {
    marginTop: theme.space.xl,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    padding: 14,
    borderRadius: 10,
    backgroundColor: theme.color.brand,
  },
  saveText: { color: theme.color.onBrand, fontWeight: "700", letterSpacing: 0.6, fontSize: 13 },

  footNote: {
    marginTop: theme.space.lg,
    fontSize: 11,
    color: theme.color.textDim,
    textAlign: "center",
    lineHeight: 16,
  },
});
