import { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator,
  KeyboardAvoidingView, Platform, FlatList,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import { api } from "@/src/lib/api";
import { useAuth } from "@/src/lib/auth";
import { theme } from "@/src/lib/theme";

export default function Messages() {
  const { user } = useAuth();
  const [partners, setPartners] = useState<any[]>([]);
  const [active, setActive] = useState<any>(null);
  const [thread, setThread] = useState<any[]>([]);
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(true);

  const loadPartners = useCallback(async () => {
    setLoading(true);
    try {
      const p = await api<any[]>("/messages");
      setPartners(p);
      if (p[0] && !active) setActive(p[0]);
    } finally { setLoading(false); }
  }, [active]);

  const loadThread = useCallback(async () => {
    if (!active) return;
    const t = await api<any[]>(`/messages/${active.id}`);
    setThread(t);
  }, [active]);

  useFocusEffect(useCallback(() => { loadPartners(); }, [loadPartners]));
  useEffect(() => { loadThread(); }, [active, loadThread]);

  const send = async () => {
    if (!text.trim() || !active) return;
    const t = text.trim();
    setText("");
    const m = await api<any>("/messages", { method: "POST", body: { to_user_id: active.id, text: t } });
    setThread((prev) => [...prev, m]);
  };

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Text style={styles.title}>MESSAGES</Text>
      </View>
      {loading ? (
        <ActivityIndicator color={theme.color.brand} style={{ marginTop: 40 }} />
      ) : partners.length === 0 ? (
        <Text style={styles.empty}>No conversations yet.</Text>
      ) : (
        <>
          <View style={styles.partnersRow}>
            {partners.map((p) => (
              <Pressable
                key={p.id}
                testID={`partner-${p.id}`}
                onPress={() => setActive(p)}
                style={[styles.pChip, active?.id === p.id && styles.pChipActive]}
              >
                <Text style={[styles.pChipText, active?.id === p.id && { color: "#fff" }]}>
                  {p.name}
                </Text>
              </Pressable>
            ))}
          </View>

          <FlatList
            data={thread}
            keyExtractor={(m) => m.id}
            contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 20 }}
            renderItem={({ item }) => {
              const mine = item.from_user_id === user?.id;
              return (
                <View style={[styles.bubbleWrap, mine ? styles.mineWrap : styles.theirsWrap]}>
                  <View style={[styles.bubble, mine ? styles.mine : styles.theirs]}>
                    <Text style={[styles.bubbleText, mine && { color: "#fff" }]}>{item.text}</Text>
                  </View>
                </View>
              );
            }}
            ListEmptyComponent={<Text style={styles.empty}>Say hi to your {user?.role === "client" ? "coach" : "client"}.</Text>}
          />

          <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} keyboardVerticalOffset={90}>
            <View style={styles.composer}>
              <TextInput
                testID="msg-input"
                style={styles.input}
                value={text}
                onChangeText={setText}
                placeholder="Send message…"
                placeholderTextColor={theme.color.textDim}
                multiline
              />
              <Pressable testID="msg-send" onPress={send} style={styles.sendBtn}>
                <Ionicons name="arrow-up" color="#fff" size={20} />
              </Pressable>
            </View>
          </KeyboardAvoidingView>
        </>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  title: { color: theme.color.text, fontSize: 20, letterSpacing: 2, fontWeight: "900" },
  empty: { color: theme.color.textMuted, textAlign: "center", marginTop: 40 },
  partnersRow: { flexDirection: "row", gap: 8, padding: theme.space.lg, paddingBottom: theme.space.sm },
  pChip: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: theme.radius.pill, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  pChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  pChipText: { color: theme.color.textMuted, fontWeight: "700", fontSize: 12 },
  bubbleWrap: { marginBottom: 8, flexDirection: "row" },
  mineWrap: { justifyContent: "flex-end" },
  theirsWrap: { justifyContent: "flex-start" },
  bubble: { maxWidth: "78%", padding: 12, borderRadius: theme.radius.md },
  mine: { backgroundColor: theme.color.brand },
  theirs: { backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  bubbleText: { color: theme.color.text, fontSize: 14 },
  composer: { flexDirection: "row", gap: 8, padding: theme.space.md, borderTopWidth: 1, borderTopColor: theme.color.divider, backgroundColor: theme.color.surface, alignItems: "flex-end" },
  input: { flex: 1, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, padding: theme.space.md, color: theme.color.text, borderWidth: 1, borderColor: theme.color.border, maxHeight: 120 },
  sendBtn: { backgroundColor: theme.color.brand, width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center" },
});
