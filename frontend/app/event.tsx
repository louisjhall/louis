import { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, TextInput, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  KeyboardAvoidingView, Platform,
} from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

const DAYS: string[] = []; void DAYS;

type CatalogItem = { slug: string; label: string; category: string; icon: string };
type Category = { key: string; label: string; short_label: string; days_label: string; icon: string; colour: string; safety_note?: string };

const phaseLabel: Record<string, string> = {
  base: "BASE", build: "BUILD", peak: "PEAK", taper: "TAPER",
  race_week: "EVENT WEEK", recovery: "RECOVERY", post: "COMPLETE", unknown: "—",
};
const phaseColor: Record<string, string> = {
  base: theme.color.info,
  build: "#3B82F6",
  peak: theme.color.brand,
  taper: theme.color.amber,
  race_week: theme.color.red,
  recovery: theme.color.green,
  post: theme.color.textDim,
  unknown: theme.color.textDim,
};

export default function EventScreen() {
  const router = useRouter();
  const [existing, setExisting] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Catalog fetched from backend so we don't hardcode drift.
  const [categories, setCategories] = useState<Category[]>([]);
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);

  // form state
  const [category, setCategory] = useState<string>("race");
  const [typeSlug, setTypeSlug] = useState<string | null>(null);
  const [type, setType] = useState("marathon");
  const [name, setName] = useState("");
  const [dateIso, setDateIso] = useState("");
  const [ability, setAbility] = useState("");
  const [prevTime, setPrevTime] = useState("");
  const [targetTime, setTargetTime] = useState("");
  const [weekly, setWeekly] = useState("");
  const [longest, setLongest] = useState("");
  const [injuries, setInjuries] = useState("");
  const [prefDays, setPrefDays] = useState<string[]>([]);
  const [accessGym, setAccessGym] = useState(false);
  const [accessPool, setAccessPool] = useState(false);
  const [accessBike, setAccessBike] = useState(false);
  const [accessTM, setAccessTM] = useState(false);
  const [strength, setStrength] = useState(true);
  const [mobility, setMobility] = useState(true);
  const [notes, setNotes] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [e, cat] = await Promise.all([
        api<any>("/events/current"),
        api<{ categories: Category[]; events: CatalogItem[] }>("/events/catalog"),
      ]);
      setCategories(cat.categories || []);
      setCatalog(cat.events || []);
      if (e && e.id) {
        setExisting(e);
        setCategory(e.category || "race");
        setType(e.event_type || "marathon"); setName(e.event_name); setDateIso(e.event_date);
        // Try to match a catalog slug for the chip selection.
        const found = (cat.events || []).find((x) => x.label.toLowerCase() === (e.event_type || "").toLowerCase() || x.slug === e.event_type);
        setTypeSlug(found?.slug || null);
        setAbility(e.current_ability || ""); setPrevTime(e.previous_time || "");
        setTargetTime(e.target_time || ""); setWeekly(e.weekly_availability_min ? String(e.weekly_availability_min) : "");
        setLongest(e.longest_recent || ""); setInjuries(e.injury_history || "");
        setPrefDays(e.preferred_days || []);
        setAccessGym(!!e.access_gym); setAccessPool(!!e.access_pool);
        setAccessBike(!!e.access_bike); setAccessTM(!!e.access_treadmill);
        setStrength(e.include_strength ?? true); setMobility(e.include_mobility ?? true);
        setNotes(e.notes || "");
      } else {
        setExisting(null);
      }
    } finally { setLoading(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const currentCatMeta = useMemo(() => categories.find((c) => c.key === category), [categories, category]);
  const eventsInCat = useMemo(() => catalog.filter((c) => c.category === category), [catalog, category]);

  useEffect(() => {
    // Reset typeSlug/label when switching categories (only if user hasn't typed a name yet)
    if (existing) return;
    if (!eventsInCat.length) return;
    const first = eventsInCat[0];
    setTypeSlug(first.slug);
    setType(first.label);
  }, [category, eventsInCat, existing]);

  const toggleDay = (d: string) => setPrefDays((p) => p.includes(d) ? p.filter((x) => x !== d) : [...p, d]); void toggleDay;

  const save = async () => {
    if (!name || !dateIso) { setErr("Event name and date are required"); return; }
    setSaving(true); setErr(null);
    try {
      await api("/events", {
        method: "POST",
        body: {
          event_type: type, event_name: name, event_date: dateIso, category,
          current_ability: ability || null,
          previous_time: prevTime || null,
          target_time: targetTime || null,
          weekly_availability_min: weekly ? parseInt(weekly) : null,
          longest_recent: longest || null,
          injury_history: injuries || null,
          preferred_days: prefDays,
          access_gym: accessGym, access_pool: accessPool,
          access_bike: accessBike, access_treadmill: accessTM,
          include_strength: strength, include_mobility: mobility,
          notes: notes || null,
        },
      });
      await load();
      router.back();
    } catch (e: any) { setErr(e.message); } finally { setSaving(false); }
  };

  const remove = async () => {
    if (!existing) return;
    setSaving(true);
    try {
      await api(`/events/${existing.id}`, { method: "DELETE" });
      router.back();
    } finally { setSaving(false); }
  };

  const phase = existing?.phase_info || {};
  const isRace = category === "race";
  const showPerf = isRace;
  const showAccess = isRace || category === "sport_hobby";
  const daysLabel = (existing?.days_label || currentCatMeta?.days_label || "days to event").toUpperCase();
  const daysValue = existing?.days_value ?? phase.days_to_race;

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()}><Ionicons name="chevron-back" size={26} color={theme.color.text} /></Pressable>
        <Text style={styles.title}>EVENT TRAINING</Text>
        <View style={{ width: 26 }} />
      </View>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 140 }} keyboardShouldPersistTaps="handled">
          {loading ? <ActivityIndicator color={theme.color.brand} /> : (
            <>
              {existing && (
                <View style={[styles.countdownCard, { borderLeftColor: existing.category_colour || theme.color.brand }]} testID="event-countdown">
                  <View style={styles.iconWrap}>
                    <Ionicons name={(existing.category_icon || "flag") as any} size={22} color={existing.category_colour || theme.color.brand} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.countLbl}>{(existing.category_label || String(existing.event_type || "").toUpperCase())}</Text>
                    <Text style={styles.countName}>{existing.event_name}</Text>
                    <Text style={styles.countDate}>{existing.event_date}</Text>
                  </View>
                  <View style={{ alignItems: "flex-end" }}>
                    <Text style={styles.countBig}>{typeof daysValue === "number" && daysValue >= 0 ? daysValue : "—"}</Text>
                    <Text style={styles.countBigLbl}>{daysLabel}</Text>
                    {isRace && (
                      <View style={[styles.phasePill, { backgroundColor: phaseColor[phase.phase] || theme.color.info }]}>
                        <Text style={styles.phaseText}>{phaseLabel[phase.phase] || "—"}</Text>
                      </View>
                    )}
                  </View>
                </View>
              )}

              {/* Safety disclaimer for medical events */}
              {(existing?.safety_note || (category === "medical" && !existing)) && (
                <View style={styles.safetyBox}>
                  <Ionicons name="shield-checkmark" size={14} color={theme.color.amber} />
                  <Text style={styles.safetyT}>
                    {existing?.safety_note || "CrewFit can support healthier habits, general fitness and consistency around your review. It does not provide medical advice — please speak to your doctor or aviation medical examiner for medical guidance."}
                  </Text>
                </View>
              )}

              <Sect label="CATEGORY">
                <View style={styles.chipsWrap}>
                  {categories.map((c) => (
                    <Pressable key={c.key} testID={`ev-cat-${c.key}`} onPress={() => setCategory(c.key)} style={[styles.chip, category === c.key && styles.chipActive]}>
                      <Ionicons name={c.icon as any} size={12} color={category === c.key ? "#fff" : theme.color.textMuted} style={{ marginRight: 4 }} />
                      <Text style={[styles.chipText, category === c.key && { color: "#fff" }]}>{c.short_label}</Text>
                    </Pressable>
                  ))}
                </View>
              </Sect>

              <Sect label="EVENT">
                <Text style={styles.miniLabel}>TYPE</Text>
                <View style={styles.chipsWrap}>
                  {eventsInCat.map((t) => {
                    const active = typeSlug === t.slug;
                    return (
                      <Pressable key={t.slug} testID={`ev-type-${t.slug}`} onPress={() => { setTypeSlug(t.slug); setType(t.label); }} style={[styles.chip, active && styles.chipActive]}>
                        <Ionicons name={t.icon as any} size={12} color={active ? "#fff" : theme.color.textMuted} style={{ marginRight: 4 }} />
                        <Text style={[styles.chipText, active && { color: "#fff" }]}>{t.label}</Text>
                      </Pressable>
                    );
                  })}
                </View>
                <Field label="NAME">
                  <TextInput
                    testID="ev-name" style={styles.input} value={name} onChangeText={setName}
                    placeholder={category === "medical" ? "Airline Medical Renewal (Blood Pressure)" : "Give this event a name"}
                    placeholderTextColor={theme.color.textDim}
                  />
                </Field>
                <Field label="DATE (YYYY-MM-DD)"><TextInput testID="ev-date" style={styles.input} value={dateIso} onChangeText={setDateIso} placeholder="2026-06-03" placeholderTextColor={theme.color.textDim} /></Field>
              </Sect>

              {showPerf && (
                <Sect label="PERFORMANCE">
                  <Field label="CURRENT ABILITY"><TextInput testID="ev-ability" style={styles.input} value={ability} onChangeText={setAbility} placeholder="Can run 10km in 55 min" placeholderTextColor={theme.color.textDim} /></Field>
                  <View style={styles.row2}>
                    <Field flex label="PREVIOUS TIME"><TextInput testID="ev-prev" style={styles.input} value={prevTime} onChangeText={setPrevTime} placeholder="4:12:00" placeholderTextColor={theme.color.textDim} /></Field>
                    <Field flex label="TARGET TIME"><TextInput testID="ev-target" style={styles.input} value={targetTime} onChangeText={setTargetTime} placeholder="3:45:00" placeholderTextColor={theme.color.textDim} /></Field>
                  </View>
                  <Field label="LONGEST RECENT SESSION"><TextInput testID="ev-longest" style={styles.input} value={longest} onChangeText={setLongest} placeholder="18km long run 3 weeks ago" placeholderTextColor={theme.color.textDim} /></Field>
                  <Field label="WEEKLY AVAILABILITY (min)"><TextInput testID="ev-weekly" style={styles.input} value={weekly} onChangeText={setWeekly} placeholder="360" keyboardType="number-pad" placeholderTextColor={theme.color.textDim} /></Field>
                </Sect>
              )}

              {showAccess && (
                <Sect label="ACCESS">
                  <View style={styles.chipsWrap}>
                    {([["gym", accessGym, setAccessGym], ["pool", accessPool, setAccessPool], ["bike", accessBike, setAccessBike], ["treadmill/turbo", accessTM, setAccessTM]] as [string, boolean, (v: boolean) => void][]).map(([k, v, s]) => (
                      <Pressable key={k} testID={`ev-access-${k}`} onPress={() => s(!v)} style={[styles.chip, v && styles.chipActive]}>
                        <Text style={[styles.chipText, v && { color: "#fff" }]}>{k}</Text>
                      </Pressable>
                    ))}
                  </View>
                  <View style={styles.chipsWrap}>
                    <Pressable onPress={() => setStrength(!strength)} testID="ev-strength" style={[styles.chip, strength && styles.chipActive]}>
                      <Text style={[styles.chipText, strength && { color: "#fff" }]}>Include strength</Text>
                    </Pressable>
                    <Pressable onPress={() => setMobility(!mobility)} testID="ev-mobility" style={[styles.chip, mobility && styles.chipActive]}>
                      <Text style={[styles.chipText, mobility && { color: "#fff" }]}>Include mobility</Text>
                    </Pressable>
                  </View>
                </Sect>
              )}

              <Sect label="PREFERENCES">
                <Text style={styles.helperNote}>
                  Sessions map to your actual roster days — CrewFit doesn&apos;t lock training to fixed weekdays.
                </Text>
                <Field label={category === "medical" ? "CLINICIAN ADVICE / RESTRICTIONS" : "INJURY HISTORY"}>
                  <TextInput
                    testID="ev-inj" style={[styles.input, { minHeight: 60 }]} multiline value={injuries} onChangeText={setInjuries}
                    placeholder={category === "medical" ? "Any restrictions or advice from your doctor?" : "Right knee — no downhill running"}
                    placeholderTextColor={theme.color.textDim}
                  />
                </Field>
                <Field label="NOTES"><TextInput testID="ev-notes" style={[styles.input, { minHeight: 60 }]} multiline value={notes} onChangeText={setNotes} placeholderTextColor={theme.color.textDim} /></Field>
              </Sect>

              {err && <Text style={{ color: theme.color.red, marginTop: 10 }}>{err}</Text>}

              {existing && (
                <Pressable testID="ev-delete" onPress={remove} style={styles.delBtn}>
                  <Text style={styles.delText}>REMOVE ACTIVE EVENT</Text>
                </Pressable>
              )}
            </>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
      <View style={styles.sticky}>
        <Pressable testID="ev-save" onPress={save} disabled={saving} style={[styles.cta, saving && { opacity: 0.6 }]}>
          {saving ? <ActivityIndicator color="#fff" /> : <Text style={styles.ctaText}>{existing ? "UPDATE EVENT" : "ADD EVENT"}</Text>}
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

function Sect({ label, children }: any) {
  return (
    <View style={{ marginTop: theme.space.md }}>
      <Text style={styles.sectLabel}>{label}</Text>
      <View style={styles.sectBody}>{children}</View>
    </View>
  );
}
function Field({ label, children, flex }: any) {
  return (
    <View style={{ marginBottom: theme.space.sm, flex: flex ? 1 : undefined }}>
      <Text style={styles.miniLabel}>{label}</Text>
      {children}
    </View>
  );
}
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  title: { color: theme.color.text, fontSize: 14, letterSpacing: 2, fontWeight: "900" },
  countdownCard: { flexDirection: "row", alignItems: "center", gap: 10, padding: theme.space.md, backgroundColor: theme.color.brandTint, borderLeftWidth: 4, borderLeftColor: theme.color.brand, borderRadius: theme.radius.md, marginBottom: theme.space.md },
  iconWrap: { width: 40, height: 40, borderRadius: 20, backgroundColor: theme.color.surface, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: theme.color.brand },
  countLbl: { color: theme.color.brand, fontSize: 10, letterSpacing: 1.5, fontWeight: "800" },
  countName: { color: theme.color.text, fontSize: 20, fontWeight: "900", marginTop: 4 },
  countDate: { color: theme.color.textMuted, fontSize: 12, marginTop: 2 },
  countBig: { color: theme.color.text, fontSize: 36, fontWeight: "900" },
  countBigLbl: { color: theme.color.textMuted, fontSize: 9, letterSpacing: 1.5, fontWeight: "800" },
  phasePill: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: theme.radius.sm, marginTop: 6 },
  phaseText: { color: "#fff", fontSize: 10, letterSpacing: 1.5, fontWeight: "800" },
  safetyBox: { flexDirection: "row", gap: 8, alignItems: "flex-start", padding: 12, borderRadius: 10, backgroundColor: "rgba(245,158,11,0.10)", borderWidth: 1, borderColor: theme.color.amber, marginBottom: theme.space.md },
  safetyT: { color: theme.color.text, fontSize: 12, lineHeight: 17, flex: 1 },
  sectLabel: { color: theme.color.brand, fontSize: 10, letterSpacing: 2, fontWeight: "800", marginBottom: 4 },
  sectBody: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, padding: theme.space.md },
  miniLabel: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 1.5, fontWeight: "700", marginBottom: 4, marginTop: 8 },
  helperNote: { color: theme.color.textMuted, fontSize: 11, fontStyle: "italic", lineHeight: 15, marginBottom: 8 },
  input: { backgroundColor: theme.color.surface3, borderRadius: theme.radius.md, color: theme.color.text, padding: 12, borderWidth: 1, borderColor: theme.color.border, fontSize: 14 },
  chipsWrap: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: { flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 6, borderRadius: theme.radius.pill, backgroundColor: theme.color.surface3, borderWidth: 1, borderColor: theme.color.border, flexShrink: 0 },
  chipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipText: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700" },
  row2: { flexDirection: "row", gap: theme.space.md },
  delBtn: { marginTop: theme.space.lg, padding: 14, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.red, alignItems: "center" },
  delText: { color: theme.color.red, fontWeight: "800", letterSpacing: 2, fontSize: 11 },
  sticky: { position: "absolute", left: 0, right: 0, bottom: 0, padding: theme.space.lg, backgroundColor: theme.color.surface, borderTopWidth: 1, borderTopColor: theme.color.border },
  cta: { backgroundColor: theme.color.brand, paddingVertical: 16, borderRadius: theme.radius.md, alignItems: "center" },
  ctaText: { color: "#fff", fontWeight: "800", letterSpacing: 2, fontSize: 13 },
});
