import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator, RefreshControl } from "react-native";
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import { useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

export default function Progress() {
  const router = useRouter();
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [weight, setWeight] = useState("");
  const [photo, setPhoto] = useState<{ base64: string; mime: string } | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try { setItems(await api<any[]>("/progress")); } finally { setLoading(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const pick = async () => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) return;
    const r = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ImagePicker.MediaTypeOptions.Images, base64: true, quality: 0.6 });
    if (!r.canceled && r.assets[0]?.base64) setPhoto({ base64: r.assets[0].base64!, mime: r.assets[0].mimeType || "image/jpeg" });
  };

  const submit = async () => {
    setSaving(true);
    try {
      await api("/progress", { method: "POST", body: {
        weight_kg: weight ? parseFloat(weight) : null,
        photo_base64: photo?.base64 || null,
        photo_mime: photo?.mime || null,
      }});
      setWeight(""); setPhoto(null); await load();
    } finally { setSaving(false); }
  };

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()}><Ionicons name="chevron-back" size={26} color={theme.color.text} /></Pressable>
        <Text style={styles.title}>PROGRESS</Text>
        <View style={{ width: 26 }} />
      </View>
      <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 60 }} refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.color.brand} />}>
        <View style={styles.form}>
          <Text style={styles.label}>WEIGHT (kg)</Text>
          <TextInput testID="prog-weight" style={styles.input} value={weight} onChangeText={setWeight} keyboardType="numeric" placeholder="82" placeholderTextColor={theme.color.textDim} />
          <Pressable testID="prog-pick" onPress={pick} style={styles.photoBox}>
            {photo ? <Image source={{ uri: `data:${photo.mime};base64,${photo.base64}` }} style={{ width: "100%", height: 160, borderRadius: theme.radius.md }} contentFit="cover" /> : (
              <><Ionicons name="camera" size={22} color={theme.color.brand} /><Text style={styles.photoText}>ADD PROGRESS PHOTO</Text></>
            )}
          </Pressable>
          <Pressable testID="prog-submit" onPress={submit} disabled={saving || (!weight && !photo)} style={[styles.cta, (saving || (!weight && !photo)) && { opacity: 0.5 }]}>
            {saving ? <ActivityIndicator color="#fff" /> : <Text style={styles.ctaText}>LOG</Text>}
          </Pressable>
        </View>

        <Text style={styles.sect}>HISTORY</Text>
        {items.length === 0 ? <Text style={{ color: theme.color.textMuted }}>No logs yet.</Text> : items.map((i) => (
          <View key={i.id} style={styles.item}>
            {i.photo_base64 && <Image source={{ uri: `data:${i.photo_mime};base64,${i.photo_base64}` }} style={{ width: 80, height: 80, borderRadius: theme.radius.sm }} contentFit="cover" />}
            <View style={{ flex: 1, marginLeft: i.photo_base64 ? theme.space.md : 0 }}>
              <Text style={styles.itemDate}>{new Date(i.created_at).toDateString()}</Text>
              {i.weight_kg && <Text style={styles.itemWeight}>{i.weight_kg} kg</Text>}
            </View>
          </View>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  title: { color: theme.color.text, fontSize: 14, letterSpacing: 2, fontWeight: "900" },
  form: { padding: theme.space.md, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border },
  label: { color: theme.color.textMuted, letterSpacing: 2, fontSize: 11, fontWeight: "800" },
  input: { backgroundColor: theme.color.surface3, borderRadius: theme.radius.md, color: theme.color.text, padding: theme.space.md, borderWidth: 1, borderColor: theme.color.border, marginTop: 6 },
  photoBox: { marginTop: theme.space.md, borderRadius: theme.radius.md, borderWidth: 1, borderStyle: "dashed", borderColor: theme.color.borderStrong, minHeight: 100, alignItems: "center", justifyContent: "center", overflow: "hidden" },
  photoText: { color: theme.color.brand, marginTop: 4, letterSpacing: 1.5, fontWeight: "700", fontSize: 11 },
  cta: { backgroundColor: theme.color.brand, paddingVertical: 14, borderRadius: theme.radius.md, alignItems: "center", marginTop: theme.space.md },
  ctaText: { color: "#fff", fontWeight: "800", letterSpacing: 2 },
  sect: { color: theme.color.textMuted, letterSpacing: 2, fontSize: 11, fontWeight: "800", marginTop: theme.space.lg, marginBottom: theme.space.sm },
  item: { flexDirection: "row", padding: theme.space.md, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, marginBottom: theme.space.sm, borderWidth: 1, borderColor: theme.color.border, alignItems: "center" },
  itemDate: { color: theme.color.textMuted, fontSize: 12, letterSpacing: 1 },
  itemWeight: { color: theme.color.text, fontSize: 20, fontWeight: "900", marginTop: 2 },
});
