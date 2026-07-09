/**
 * Client video screen — plays a weekly video from Louis and shows the script transcript.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

export default function ClientVideo() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [video, setVideo] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const r = await api<any>("/videos/for-me");
      const v = (r?.videos || []).find((x: any) => x.id === id);
      setVideo(v || null);
      if (v && !v.watched_at) {
        api<any>(`/videos/${id}/watched`, { method: "POST", body: {} }).catch(() => {});
      }
    } catch { /* ignore */ } finally { setLoading(false); }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  if (loading) return <SafeAreaView style={styles.root}><View style={styles.centre}><ActivityIndicator color={theme.color.brand} /></View></SafeAreaView>;
  if (!video) return <SafeAreaView style={styles.root}><View style={styles.centre}><Text style={{ color: theme.color.textMuted }}>Video not found.</Text></View></SafeAreaView>;

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <View style={styles.topBar}>
        <Pressable onPress={() => router.back()} hitSlop={12}><Ionicons name="close" size={26} color={theme.color.text} /></Pressable>
        <Text style={styles.header}>VIDEO FROM LOUIS</Text>
        <View style={{ width: 26 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: 20 }}>
        <View style={styles.playerBox}>
          {video.file_url ? (
            <Text style={styles.playerT}>Video file: {video.file_url}</Text>
          ) : (
            <>
              <Ionicons name="chatbubbles" size={44} color={theme.color.brand} />
              <Text style={styles.eyebrow}>WRITTEN COACHING REVIEW</Text>
              <Text style={styles.hint}>
                Louis has sent your weekly review as a written message this week.
                Video recording ships in the next update.
              </Text>
            </>
          )}
        </View>

        <View style={styles.scriptCard}>
          <Text style={styles.scriptEyebrow}>YOUR WEEKLY REVIEW</Text>
          <Text style={styles.scriptBody}>{video.script}</Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  centre: { flex: 1, alignItems: "center", justifyContent: "center" },
  topBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 16, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  header: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  playerBox: { padding: 30, alignItems: "center", justifyContent: "center", borderRadius: 14, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, minHeight: 240 },
  playerT: { color: theme.color.textMuted, fontSize: 12 },
  eyebrow: { color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 2, marginTop: 12 },
  hint: { color: theme.color.textMuted, fontSize: 12, textAlign: "center", marginTop: 10, lineHeight: 17, fontStyle: "italic" },
  scriptCard: { marginTop: 16, padding: 16, borderRadius: 12, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  scriptEyebrow: { color: theme.color.brand, fontSize: 9, fontWeight: "900", letterSpacing: 2 },
  scriptBody: { color: theme.color.text, fontSize: 14, lineHeight: 22, marginTop: 10 },
});
