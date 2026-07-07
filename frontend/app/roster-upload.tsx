import { useState } from "react";
import { View, Text, StyleSheet, Pressable, ScrollView, ActivityIndicator, TextInput } from "react-native";
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import * as DocumentPicker from "expo-document-picker";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme, loadColor } from "@/src/lib/theme";

const DAY_TYPES = [
  "Home Day", "Home Training Day", "Turnaround Duty", "Layover Arrival Day",
  "Layover Full Day", "Layover Departure Day", "Long-Haul Duty", "Short-Haul Duty",
  "Night Flight", "Early Report", "Late Finish", "Rest Day", "Recovery Day",
  "Standby", "Simulator/Training Day", "Annual Leave", "Unknown/Needs Confirmation",
];
const LOADS = ["green", "amber", "red", "blue", "purple", "grey"];
const EQ_KEYS: [string, string][] = [
  ["dumbbells", "Dumbbells"], ["treadmill", "Treadmill"], ["bike", "Bike"], ["rower", "Rower"],
  ["cable_machine", "Cable"], ["machines", "Machines"], ["bench", "Bench"], ["squat_rack", "Squat rack"],
  ["free_weights", "Free weights"], ["pool", "Pool"], ["outdoor_running", "Outdoor OK"],
];

async function uriToBase64(uri: string): Promise<string> {
  const res = await fetch(uri);
  const blob = await res.blob();
  return await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const s = String(reader.result || "");
      const comma = s.indexOf(",");
      resolve(comma >= 0 ? s.slice(comma + 1) : s);
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

export default function RosterUpload() {
  const router = useRouter();
  const [file, setFile] = useState<{ base64: string; mime: string; name?: string } | null>(null);
  const [extracted, setExtracted] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  const pickImage = async () => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) return;
    const res = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ImagePicker.MediaTypeOptions.Images, base64: true, quality: 0.7 });
    if (!res.canceled && res.assets[0]?.base64) {
      const a = res.assets[0];
      setFile({ base64: a.base64!, mime: a.mimeType || "image/jpeg", name: a.fileName || "roster.jpg" });
    }
  };
  const pickPdf = async () => {
    const res = await DocumentPicker.getDocumentAsync({ type: "application/pdf", copyToCacheDirectory: true });
    if (res.canceled) return;
    const a = res.assets[0];
    try {
      const b64 = await uriToBase64(a.uri);
      setFile({ base64: b64, mime: a.mimeType || "application/pdf", name: a.name });
    } catch (e: any) { setErr(e?.message || "Could not read PDF"); }
  };

  const extract = async () => {
    if (!file) return;
    setLoading(true); setErr(null);
    try {
      const r = await api<any>("/roster/extract", { method: "POST", body: { file_base64: file.base64, mime_type: file.mime, week_start: new Date().toISOString().slice(0, 10) } });
      setExtracted(r);
    } catch (e: any) { setErr(e.message); }
    finally { setLoading(false); }
  };

  const updateDay = (idx: number, patch: any) => {
    setExtracted((r: any) => ({ ...r, days: r.days.map((d: any, i: number) => (i === idx ? { ...d, ...patch } : d)) }));
  };

  const confirm = async () => {
    if (!extracted) return;
    setLoading(true);
    try {
      await api(`/roster/${extracted.id}/confirm`, { method: "POST", body: { days: extracted.days } });
      router.replace("/(client)/calendar");
    } catch (e: any) { setErr(e.message); } finally { setLoading(false); }
  };

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} testID="roster-back"><Ionicons name="chevron-back" size={26} color={theme.color.text} /></Pressable>
        <Text style={styles.title}>{extracted ? "REVIEW ROSTER" : "ROSTER UPLOAD"}</Text>
        <View style={{ width: 26 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 140 }}>
        {!extracted ? (
          <>
            <View style={styles.dropzone}>
              {file ? (
                file.mime === "application/pdf" ? (
                  <View style={{ alignItems: "center" }}>
                    <Ionicons name="document" size={40} color={theme.color.brand} />
                    <Text style={styles.fileName}>{file.name}</Text>
                  </View>
                ) : (
                  <Image source={{ uri: `data:${file.mime};base64,${file.base64}` }} style={{ width: "100%", height: 220, borderRadius: theme.radius.sm }} contentFit="contain" />
                )
              ) : (
                <>
                  <Ionicons name="cloud-upload" size={56} color={theme.color.brand} />
                  <Text style={styles.dzTitle}>DROP YOUR ROSTER</Text>
                  <Text style={styles.dzSub}>{`PDF or photo · we'll extract the whole month`}</Text>
                </>
              )}
            </View>
            <View style={styles.pickRow}>
              <Pressable testID="pick-pdf" onPress={pickPdf} style={styles.pickBtn}>
                <Ionicons name="document-text" size={18} color={theme.color.brand} />
                <Text style={styles.pickText}>PICK PDF</Text>
              </Pressable>
              <Pressable testID="pick-image" onPress={pickImage} style={styles.pickBtn}>
                <Ionicons name="image" size={18} color={theme.color.brand} />
                <Text style={styles.pickText}>PICK PHOTO</Text>
              </Pressable>
            </View>
            {err && <Text style={{ color: theme.color.red, marginTop: 12 }}>{err}</Text>}
            <Pressable testID="extract-btn" onPress={extract} disabled={!file || loading} style={[styles.cta, (!file || loading) && { opacity: 0.5 }]}>
              {loading ? <ActivityIndicator color="#fff" /> : (<><Ionicons name="scan" size={16} color="#fff" /><Text style={styles.ctaText}>  EXTRACT (AI)</Text></>)}
            </Pressable>
          </>
        ) : (
          <>
            <Text style={styles.sectSub}>Tap a day to edit type, hotel or load status.</Text>
            {extracted.days.map((d: any, idx: number) => {
              const expanded = expandedIdx === idx;
              const isLayover = String(d.day_type || "").toLowerCase().includes("layover");
              return (
                <View key={idx} style={styles.dayCard} testID={`day-${idx}`}>
                  <Pressable onPress={() => setExpandedIdx(expanded ? null : idx)} testID={`day-toggle-${idx}`} style={styles.dayHead}>
                    <View style={[styles.loadPill, { backgroundColor: loadColor(d.load) }]}>
                      <Text style={styles.loadPillText}>{String(d.load || "grey").toUpperCase()}</Text>
                    </View>
                    <View style={{ flex: 1, marginLeft: theme.space.sm }}>
                      <Text style={styles.dayDate}>{d.date}</Text>
                      <Text style={styles.dayType}>{d.day_type}</Text>
                      {d.flights?.[0] && <Text style={styles.dayFlight}>{d.flights.map((f: any) => `${f.from}→${f.to}`).join("  ")}</Text>}
                      {d.layover_city && <Text style={styles.dayLayover}>🏨 {d.layover_city}</Text>}
                    </View>
                    <Ionicons name={expanded ? "chevron-up" : "chevron-down"} size={18} color={theme.color.textDim} />
                  </Pressable>
                  {expanded && (
                    <View style={styles.expandBox}>
                      <Text style={styles.miniLabel}>DAY TYPE</Text>
                      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipsScroll}>
                        {DAY_TYPES.map((t) => (
                          <Pressable key={t} testID={`day-${idx}-type-${t}`} onPress={() => updateDay(idx, { day_type: t })} style={[styles.chip, d.day_type === t && styles.chipActive]}>
                            <Text style={[styles.chipText, d.day_type === t && { color: "#fff" }]}>{t}</Text>
                          </Pressable>
                        ))}
                      </ScrollView>

                      <Text style={styles.miniLabel}>LOAD</Text>
                      <View style={styles.chipsWrap}>
                        {LOADS.map((l) => (
                          <Pressable key={l} testID={`day-${idx}-load-${l}`} onPress={() => updateDay(idx, { load: l })} style={[styles.chip, d.load === l && styles.chipActive]}>
                            <View style={[styles.dotSm, { backgroundColor: loadColor(l) }]} />
                            <Text style={[styles.chipText, d.load === l && { color: "#fff" }]}>  {l.toUpperCase()}</Text>
                          </Pressable>
                        ))}
                      </View>

                      <Text style={styles.miniLabel}>FLIGHTS (from→to)</Text>
                      <TextInput
                        testID={`day-${idx}-flights`}
                        style={styles.input}
                        value={(d.flights || []).map((f: any) => `${f.from}->${f.to}`).join(", ")}
                        onChangeText={(v) => updateDay(idx, {
                          flights: v.split(",").map((s: string) => {
                            const [f, t] = s.trim().split("->").map((x: string) => x.trim());
                            return { from: f || "", to: t || "" };
                          }).filter((f: any) => f.from || f.to),
                        })}
                        placeholder="LHR->SIN, SIN->LHR"
                        placeholderTextColor={theme.color.textDim}
                      />

                      {isLayover && <HotelSection dayIdx={idx} day={d} rosterId={extracted.id} onSaved={(hotel) => updateDay(idx, { hotel_id: hotel.id, hotel_name: hotel.name })} />}
                    </View>
                  )}
                </View>
              );
            })}
            {err && <Text style={{ color: theme.color.red, marginTop: 12 }}>{err}</Text>}
          </>
        )}
      </ScrollView>

      {extracted && (
        <View style={styles.sticky}>
          <Pressable testID="confirm-roster" onPress={confirm} disabled={loading} style={[styles.cta, loading && { opacity: 0.6 }]}>
            {loading ? <ActivityIndicator color="#fff" /> : <Text style={styles.ctaText}>CONFIRM ROSTER · {extracted.days.length} DAYS</Text>}
          </Pressable>
        </View>
      )}
    </SafeAreaView>
  );
}

function HotelSection({ dayIdx, day, rosterId, onSaved }: { dayIdx: number; day: any; rosterId: string; onSaved: (h: any) => void }) {
  const [name, setName] = useState(day.hotel_name || "");
  const [city, setCity] = useState(day.layover_city || "");
  const [country, setCountry] = useState(day.layover_country || "");
  const [gym, setGym] = useState<"yes" | "no" | "unknown">(day.hotel_id ? "yes" : "unknown");
  const [equip, setEquip] = useState<Record<string, boolean>>({});
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);

  const search = async () => {
    if (!name && !city) return;
    setBusy(true);
    try {
      const q = new URLSearchParams();
      if (name) q.set("name", name);
      if (city) q.set("city", city);
      const rows = await api<any[]>(`/hotels/search?${q.toString()}`);
      setSearchResults(rows);
    } finally { setBusy(false); }
  };
  const applyResult = (h: any) => {
    setName(h.name); setCity(h.city); setCountry(h.country || "");
    setGym(h.gym_available ? "yes" : h.gym_available === false ? "no" : "unknown");
    setEquip(h.equipment || {});
    setSearchResults([]);
  };
  const save = async () => {
    if (!name || !city) return;
    setBusy(true);
    try {
      const res = await api<any>(`/roster/${rosterId}/hotel`, {
        method: "POST",
        body: {
          date: day.date,
          hotel: {
            name, city, country: country || null,
            gym_available: gym === "yes" ? true : gym === "no" ? false : null,
            equipment: equip,
            outdoor_safe: !!equip.outdoor_running,
            pool: !!equip.pool,
          },
        },
      });
      onSaved(res.hotel);
    } finally { setBusy(false); }
  };
  const toggleEq = (k: string) => setEquip((e) => ({ ...e, [k]: !e[k] }));

  return (
    <View style={styles.hotelBox}>
      <Text style={styles.hotelHead}>🏨 HOTEL FOR LAYOVER</Text>
      <View style={{ flexDirection: "row", gap: 8 }}>
        <TextInput testID={`hotel-name-${dayIdx}`} style={[styles.input, { flex: 2 }]} value={name} onChangeText={setName} placeholder="Hotel name" placeholderTextColor={theme.color.textDim} />
        <TextInput testID={`hotel-city-${dayIdx}`} style={[styles.input, { flex: 1 }]} value={city} onChangeText={setCity} placeholder="City" placeholderTextColor={theme.color.textDim} />
      </View>
      <TextInput testID={`hotel-country-${dayIdx}`} style={styles.input} value={country} onChangeText={setCountry} placeholder="Country (opt)" placeholderTextColor={theme.color.textDim} />
      <View style={{ flexDirection: "row", gap: 8 }}>
        <Pressable testID={`hotel-search-${dayIdx}`} onPress={search} style={styles.searchBtn}>
          <Ionicons name="search" size={14} color={theme.color.brand} />
          <Text style={styles.searchText}>SEARCH COMMUNITY DB</Text>
        </Pressable>
      </View>
      {searchResults.length > 0 && (
        <View style={styles.results}>
          {searchResults.map((h) => (
            <Pressable key={h.id} onPress={() => applyResult(h)} style={styles.resultRow} testID={`hotel-result-${h.id}`}>
              <View style={{ flex: 1 }}>
                <Text style={styles.resultName}>{h.name}</Text>
                <Text style={styles.resultCity}>{h.city} · {h.country || "?"} · conf {(h.confidence * 100).toFixed(0)}%</Text>
              </View>
              <Text style={styles.resultUse}>USE</Text>
            </Pressable>
          ))}
        </View>
      )}

      <Text style={styles.miniLabel}>HOTEL GYM</Text>
      <View style={styles.chipsWrap}>
        {(["yes", "no", "unknown"] as const).map((g) => (
          <Pressable key={g} testID={`gym-${dayIdx}-${g}`} onPress={() => setGym(g)} style={[styles.chip, gym === g && styles.chipActive]}>
            <Text style={[styles.chipText, gym === g && { color: "#fff" }]}>{g.toUpperCase()}</Text>
          </Pressable>
        ))}
      </View>
      {gym === "yes" && (
        <>
          <Text style={styles.miniLabel}>EQUIPMENT</Text>
          <View style={styles.chipsWrap}>
            {EQ_KEYS.map(([k, l]) => (
              <Pressable key={k} testID={`equip-${dayIdx}-${k}`} onPress={() => toggleEq(k)} style={[styles.chip, equip[k] && styles.chipActive]}>
                <Text style={[styles.chipText, equip[k] && { color: "#fff" }]}>{l}</Text>
              </Pressable>
            ))}
          </View>
        </>
      )}
      <Pressable testID={`hotel-save-${dayIdx}`} onPress={save} disabled={busy || !name || !city} style={[styles.saveBtn, (busy || !name || !city) && { opacity: 0.5 }]}>
        {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.saveText}>SAVE HOTEL</Text>}
      </Pressable>
      {day.hotel_id && <Text style={styles.savedText}>✓ Linked hotel: {day.hotel_name}</Text>}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  title: { color: theme.color.text, fontSize: 15, letterSpacing: 2, fontWeight: "900" },
  dropzone: { alignItems: "center", justifyContent: "center", padding: theme.space.xxl, borderRadius: theme.radius.md, borderWidth: 1, borderStyle: "dashed", borderColor: theme.color.borderStrong, backgroundColor: theme.color.surface2, minHeight: 220 },
  dzTitle: { color: theme.color.text, marginTop: theme.space.md, letterSpacing: 2, fontWeight: "800" },
  dzSub: { color: theme.color.textMuted, marginTop: 4, textAlign: "center" },
  fileName: { color: theme.color.text, marginTop: theme.space.sm, fontWeight: "700" },
  pickRow: { flexDirection: "row", gap: theme.space.md, marginTop: theme.space.md },
  pickBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, paddingVertical: 14 },
  pickText: { color: theme.color.brand, letterSpacing: 1.5, fontWeight: "700", fontSize: 12 },
  cta: { flexDirection: "row", alignItems: "center", justifyContent: "center", backgroundColor: theme.color.brand, paddingVertical: 16, borderRadius: theme.radius.md, marginTop: theme.space.lg },
  ctaText: { color: "#fff", fontWeight: "800", letterSpacing: 2, fontSize: 13 },
  sectSub: { color: theme.color.textMuted, marginBottom: theme.space.md, fontSize: 12 },
  dayCard: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, marginBottom: theme.space.sm, overflow: "hidden" },
  dayHead: { flexDirection: "row", padding: theme.space.md, alignItems: "center" },
  loadPill: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: theme.radius.sm },
  loadPillText: { color: "#fff", fontSize: 9, fontWeight: "800", letterSpacing: 1 },
  dayDate: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 1.5, fontWeight: "700" },
  dayType: { color: theme.color.text, fontSize: 14, fontWeight: "800", marginTop: 2 },
  dayFlight: { color: theme.color.brand, fontSize: 11, marginTop: 2, fontWeight: "600" },
  dayLayover: { color: theme.color.text, fontSize: 11, marginTop: 2 },
  expandBox: { padding: theme.space.md, borderTopWidth: 1, borderTopColor: theme.color.divider },
  miniLabel: { color: theme.color.textMuted, fontSize: 10, letterSpacing: 1.5, fontWeight: "800", marginTop: 10, marginBottom: 6 },
  chipsScroll: { gap: 6, paddingBottom: 4 },
  chipsWrap: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: { flexDirection: "row", alignItems: "center", paddingHorizontal: 10, paddingVertical: 6, borderRadius: theme.radius.pill, backgroundColor: theme.color.surface3, borderWidth: 1, borderColor: theme.color.border, flexShrink: 0 },
  chipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipText: { color: theme.color.textMuted, fontSize: 10, fontWeight: "700" },
  dotSm: { width: 6, height: 6, borderRadius: 3 },
  input: { backgroundColor: theme.color.surface3, borderRadius: theme.radius.sm, color: theme.color.text, padding: 10, borderWidth: 1, borderColor: theme.color.border, marginTop: 6, fontSize: 13 },
  hotelBox: { marginTop: theme.space.md, padding: theme.space.md, borderRadius: theme.radius.md, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand },
  hotelHead: { color: theme.color.brand, letterSpacing: 1.5, fontWeight: "800", fontSize: 11 },
  searchBtn: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: theme.color.surface3, borderRadius: theme.radius.md, paddingHorizontal: 12, paddingVertical: 10, marginTop: 8, borderWidth: 1, borderColor: theme.color.border },
  searchText: { color: theme.color.brand, fontSize: 10, letterSpacing: 1.5, fontWeight: "800" },
  results: { marginTop: 8, backgroundColor: theme.color.surface3, borderRadius: theme.radius.sm, borderWidth: 1, borderColor: theme.color.border },
  resultRow: { flexDirection: "row", alignItems: "center", padding: 10, borderTopWidth: 1, borderTopColor: theme.color.divider },
  resultName: { color: theme.color.text, fontSize: 13, fontWeight: "700" },
  resultCity: { color: theme.color.textMuted, fontSize: 10, marginTop: 2 },
  resultUse: { color: theme.color.brand, fontSize: 10, letterSpacing: 2, fontWeight: "800" },
  saveBtn: { backgroundColor: theme.color.brand, marginTop: 10, paddingVertical: 12, borderRadius: theme.radius.md, alignItems: "center" },
  saveText: { color: "#fff", fontWeight: "800", letterSpacing: 2, fontSize: 12 },
  savedText: { color: theme.color.green, fontSize: 11, marginTop: 6, fontWeight: "700" },
  sticky: { position: "absolute", left: 0, right: 0, bottom: 0, padding: theme.space.lg, backgroundColor: theme.color.surface, borderTopWidth: 1, borderTopColor: theme.color.border },
});
