import { useState } from "react";
import { View, Text, StyleSheet, Pressable, ScrollView, ActivityIndicator, TextInput } from "react-native";
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import * as DocumentPicker from "expo-document-picker";
import * as FileSystem from "expo-file-system/legacy";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme, loadColor } from "@/src/lib/theme";

export default function RosterUpload() {
  const router = useRouter();
  const [file, setFile] = useState<{ base64: string; mime: string; name?: string } | null>(null);
  const [extracted, setExtracted] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const pickImage = async () => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) return;
    const res = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      base64: true, quality: 0.7,
    });
    if (!res.canceled && res.assets[0]?.base64) {
      const a = res.assets[0];
      setFile({ base64: a.base64!, mime: a.mimeType || "image/jpeg", name: a.fileName || "roster.jpg" });
    }
  };

  const pickPdf = async () => {
    const res = await DocumentPicker.getDocumentAsync({ type: "application/pdf", copyToCacheDirectory: true });
    if (res.canceled) return;
    const a = res.assets[0];
    const b64 = await FileSystem.readAsStringAsync(a.uri, { encoding: FileSystem.EncodingType.Base64 });
    setFile({ base64: b64, mime: "application/pdf", name: a.name });
  };

  const extract = async () => {
    if (!file) return;
    setLoading(true); setErr(null);
    try {
      const r = await api<any>("/roster/extract", {
        method: "POST",
        body: { file_base64: file.base64, mime_type: file.mime, week_start: new Date().toISOString().slice(0, 10) },
      });
      setExtracted(r);
    } catch (e: any) { setErr(e.message); }
    finally { setLoading(false); }
  };

  const updateDay = (idx: number, key: string, val: any) => {
    setExtracted((r: any) => ({
      ...r,
      days: r.days.map((d: any, i: number) => (i === idx ? { ...d, [key]: val } : d)),
    }));
  };

  const confirm = async () => {
    if (!extracted) return;
    setLoading(true);
    try {
      await api(`/roster/${extracted.id}/confirm`, { method: "POST", body: { days: extracted.days } });
      router.replace("/(client)/calendar");
    } catch (e: any) { setErr(e.message); }
    finally { setLoading(false); }
  };

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} testID="roster-back">
          <Ionicons name="chevron-back" size={26} color={theme.color.text} />
        </Pressable>
        <Text style={styles.title}>ROSTER UPLOAD</Text>
        <View style={{ width: 26 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 120 }}>
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
                  <Text style={styles.dzSub}>{`PDF or photo · we'll extract flights, duties & off days`}</Text>
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
            <Pressable
              testID="extract-btn"
              onPress={extract}
              disabled={!file || loading}
              style={[styles.cta, (!file || loading) && { opacity: 0.5 }]}
            >
              {loading ? <ActivityIndicator color="#fff" /> : (
                <><Ionicons name="scan" size={16} color="#fff" /><Text style={styles.ctaText}>  EXTRACT ROSTER (AI)</Text></>
              )}
            </Pressable>
          </>
        ) : (
          <>
            <Text style={styles.sect}>REVIEW & CONFIRM</Text>
            <Text style={styles.sectSub}>Edit any day. Tap the color to change load status.</Text>
            {extracted.days.map((d: any, idx: number) => (
              <View key={idx} style={styles.dayCard} testID={`extract-day-${idx}`}>
                <Pressable
                  testID={`toggle-load-${idx}`}
                  onPress={() => {
                    const order = ["green", "amber", "red"];
                    const next = order[(order.indexOf(d.load || "green") + 1) % 3];
                    updateDay(idx, "load", next);
                  }}
                  style={[styles.loadPill, { backgroundColor: loadColor(d.load) }]}
                >
                  <Text style={styles.loadPillText}>{(d.load || "green").toUpperCase()}</Text>
                </Pressable>
                <View style={{ flex: 1, marginLeft: theme.space.md }}>
                  <TextInput style={styles.dInput} value={d.date} onChangeText={(v) => updateDay(idx, "date", v)} placeholderTextColor={theme.color.textDim} />
                  <TextInput style={styles.dInput} value={d.type} onChangeText={(v) => updateDay(idx, "type", v)} placeholder="flight / off / layover" placeholderTextColor={theme.color.textDim} />
                  <TextInput
                    style={styles.dInput}
                    value={(d.flights || []).map((f: any) => `${f.from}->${f.to}`).join(", ")}
                    onChangeText={(v) => {
                      const flights = v.split(",").map((s) => {
                        const [from, to] = s.trim().split("->").map((x) => x.trim());
                        return { from: from || "", to: to || "" };
                      }).filter((f) => f.from || f.to);
                      updateDay(idx, "flights", flights);
                    }}
                    placeholder="LHR->JFK, JFK->LHR"
                    placeholderTextColor={theme.color.textDim}
                  />
                </View>
              </View>
            ))}
            {err && <Text style={{ color: theme.color.red, marginTop: 12 }}>{err}</Text>}
            <Pressable testID="confirm-roster" onPress={confirm} disabled={loading} style={[styles.cta, loading && { opacity: 0.6 }]}>
              {loading ? <ActivityIndicator color="#fff" /> : <Text style={styles.ctaText}>CONFIRM ROSTER</Text>}
            </Pressable>
          </>
        )}
      </ScrollView>
    </SafeAreaView>
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
  sect: { color: theme.color.text, fontSize: 18, letterSpacing: 2, fontWeight: "900" },
  sectSub: { color: theme.color.textMuted, marginTop: 4, marginBottom: theme.space.md },
  dayCard: { flexDirection: "row", padding: theme.space.md, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, marginBottom: theme.space.sm, alignItems: "flex-start" },
  loadPill: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: theme.radius.sm },
  loadPillText: { color: "#fff", fontWeight: "800", fontSize: 10, letterSpacing: 1.5 },
  dInput: { backgroundColor: theme.color.surface3, borderRadius: theme.radius.sm, color: theme.color.text, padding: 8, borderWidth: 1, borderColor: theme.color.border, marginBottom: 6, fontSize: 13 },
});
