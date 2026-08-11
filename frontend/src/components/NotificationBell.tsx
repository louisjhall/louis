/**
 * NotificationBell — pressable bell with unread badge.
 * Opens the Notifications list as a modal drawer.
 * Reused on client home + coach dashboard.
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, Modal, ScrollView,
  ActivityIndicator, RefreshControl, Platform,
} from "react-native";
import { useFocusEffect, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type NotifRow = {
  id: string;
  notif_type: string;
  category?: string;
  title: string;
  body: string;
  action_url?: string;
  created_at: string;
  read_at: string | null;
  flight_duty_safe?: boolean;
};

const CAT_COLORS: Record<string, string> = {
  check_ins: theme.color.amber,
  habits: theme.color.brand,
  workouts: theme.color.brand,
  coach_messages: theme.color.brand,
  weekly_videos: theme.color.brand,
  roster: theme.color.amber,
  programme_updates: theme.color.green,
};

export function NotificationBell({ testID }: { testID?: string }) {
  const router = useRouter();
  const [count, setCount] = useState(0);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<NotifRow[]>([]);
  const [loading, setLoading] = useState(false);

  const loadCount = useCallback(async () => {
    try {
      const r = await api<{ unread: number }>("/notifications/unread-count");
      setCount(r.unread || 0);
    } catch { /* ignore */ }
  }, []);

  const loadList = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<{ notifications: NotifRow[]; unread: number }>("/notifications");
      setItems(r.notifications || []);
      setCount(r.unread || 0);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, []);

  useFocusEffect(useCallback(() => { loadCount(); }, [loadCount]));

  const openList = () => {
    setOpen(true);
    loadList();
  };

  const readAll = async () => {
    try {
      await api("/notifications/read-all", { method: "POST" });
      await loadList();
    } catch { /* ignore */ }
  };

  const tap = async (n: NotifRow) => {
    try {
      if (!n.read_at) {
        await api(`/notifications/${n.id}/read`, { method: "POST" });
      }
    } catch { /* ignore */ }
    setOpen(false);
    if (n.action_url) {
      if (n.action_url.startsWith("http")) return;
      try { router.push(n.action_url as any); } catch { /* ignore */ }
    }
    loadCount();
  };

  return (
    <>
      <Pressable testID={testID || "notif-bell"} onPress={openList} hitSlop={10} style={styles.bell}>
        <Ionicons name={count > 0 ? "notifications" : "notifications-outline"} size={22} color={theme.color.text} />
        {count > 0 ? (
          <View style={styles.badge}>
            <Text style={styles.badgeT}>{count > 99 ? "99+" : count}</Text>
          </View>
        ) : null}
      </Pressable>

      <Modal visible={open} transparent animationType="slide" onRequestClose={() => setOpen(false)}>
        <Pressable style={styles.bg} onPress={() => setOpen(false)}>
          <Pressable style={styles.sheet} onPress={(e) => e.stopPropagation()}>
            <View style={styles.sheetHeader}>
              <View style={styles.sheetHandle} />
              <View style={styles.headerRow}>
                <Text style={styles.title}>NOTIFICATIONS</Text>
                {items.some((n) => !n.read_at) ? (
                  <Pressable testID="notif-read-all" onPress={readAll} style={styles.readAllBtn}>
                    <Text style={styles.readAllT}>MARK ALL READ</Text>
                  </Pressable>
                ) : null}
              </View>
            </View>
            <ScrollView
              contentContainerStyle={{ padding: 16, paddingBottom: Platform.OS === "ios" ? 40 : 20 }}
              refreshControl={<RefreshControl refreshing={loading} onRefresh={loadList} tintColor={theme.color.brand} />}
            >
              {loading && !items.length ? (
                <ActivityIndicator color={theme.color.brand} style={{ marginTop: 40 }} />
              ) : items.length === 0 ? (
                <View style={styles.emptyCard}>
                  <Ionicons name="checkmark-circle-outline" size={22} color={theme.color.textDim} />
                  <Text style={styles.emptyT}>Nothing new right now.</Text>
                </View>
              ) : (
                <View style={{ gap: 8 }}>
                  {items.map((n) => (
                    <Pressable
                      key={n.id}
                      testID={`notif-${n.id}`}
                      onPress={() => tap(n)}
                      style={[styles.card, !n.read_at && styles.cardUnread]}
                    >
                      <View style={[styles.catDot, { backgroundColor: CAT_COLORS[n.category || ""] || theme.color.textDim }]} />
                      <View style={{ flex: 1 }}>
                        <View style={styles.rowTop}>
                          <Text style={styles.notifTitle}>{n.title}</Text>
                          {!n.read_at ? <View style={styles.newPill}><Text style={styles.newPillT}>NEW</Text></View> : null}
                        </View>
                        <Text style={styles.body} numberOfLines={3}>{n.body}</Text>
                        <View style={styles.metaRow}>
                          <Text style={styles.meta}>{(n.created_at || "").slice(0, 16).replace("T", " ")}</Text>
                          {n.flight_duty_safe ? (
                            <Text style={[styles.meta, { color: theme.color.amber }]}> · DUTY-SAFE</Text>
                          ) : null}
                        </View>
                      </View>
                      {n.action_url ? <Ionicons name="chevron-forward" size={16} color={theme.color.textDim} /> : null}
                    </Pressable>
                  ))}
                </View>
              )}
            </ScrollView>
          </Pressable>
        </Pressable>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  bell: { padding: 6 },
  badge: { position: "absolute", top: 0, right: 0, minWidth: 16, height: 16, borderRadius: 8, backgroundColor: "#c94a4a", alignItems: "center", justifyContent: "center", paddingHorizontal: 4 },
  badgeT: { color: "#fff", fontSize: 11, fontWeight: "900" },
  bg: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  sheet: { backgroundColor: theme.color.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20, maxHeight: "80%" },
  sheetHeader: { paddingTop: 10, paddingHorizontal: 16, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  sheetHandle: { alignSelf: "center", width: 40, height: 4, backgroundColor: theme.color.borderStrong, borderRadius: 2, marginBottom: 12 },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingBottom: 10 },
  title: { color: theme.color.text, fontSize: 14, fontWeight: "900", letterSpacing: 2 },
  readAllBtn: { paddingHorizontal: 10, paddingVertical: 5, borderRadius: 4, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  readAllT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  emptyCard: { flexDirection: "row", alignItems: "center", gap: 10, padding: 16, borderRadius: 10, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, justifyContent: "center" },
  emptyT: { color: theme.color.textMuted, fontSize: 12 },
  card: { flexDirection: "row", gap: 10, padding: 12, backgroundColor: theme.color.surface2, borderRadius: 10, borderWidth: 1, borderColor: theme.color.border, alignItems: "center" },
  cardUnread: { borderColor: theme.color.brand, backgroundColor: theme.color.brandTint },
  catDot: { width: 6, height: 6, borderRadius: 3, marginTop: 6, alignSelf: "flex-start" },
  rowTop: { flexDirection: "row", gap: 8, alignItems: "center", marginBottom: 2 },
  notifTitle: { color: theme.color.text, fontSize: 13, fontWeight: "800", flexShrink: 1 },
  newPill: { paddingHorizontal: 6, paddingVertical: 2, backgroundColor: theme.color.brand, borderRadius: 3 },
  newPillT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1 },
  body: { color: theme.color.textMuted, fontSize: 12, marginTop: 2, lineHeight: 16 },
  metaRow: { flexDirection: "row", marginTop: 4 },
  meta: { color: theme.color.textDim, fontSize: 11, letterSpacing: 0.5 },
});
