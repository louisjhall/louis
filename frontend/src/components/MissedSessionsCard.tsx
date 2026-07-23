/**
 * MissedSessionsCard — Iter 94s
 *
 * Compact banner shown near the top of the client home when there are recent
 * missed workouts eligible for recovery. Clicking it opens the RecoverySheet
 * for the first missed workout; "View all" opens a list.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, Modal, ScrollView } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { RecoverySheet } from "./RecoverySheet";

type Missed = {
  id: string;
  title?: string;
  date: string;
  days_ago?: number;
  priority?: string;
  key_session?: boolean;
  recoverable?: boolean;
  recommendation?: string;
  client_copy?: { title?: string; body?: string; recommendation?: string };
};

export function MissedSessionsCard({ refreshKey = 0 }: { refreshKey?: number }) {
  const [items, setItems] = useState<Missed[]>([]);
  const [loading, setLoading] = useState(true);
  const [listOpen, setListOpen] = useState(false);
  const [active, setActive] = useState<Missed | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<any>("/recovery/missed?window=14");
      setItems((r?.missed || []) as Missed[]);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load, refreshKey]);

  const recoverable = items.filter((m) => m.recoverable !== false);
  if (loading && items.length === 0) return null;
  if (recoverable.length === 0) return null;

  const first = recoverable[0];
  return (
    <>
      <View style={styles.card} testID="missed-sessions-card">
        <View style={styles.headRow}>
          <View style={styles.iconWrap}>
            <Ionicons name="alert-circle" size={20} color={theme.color.amber} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>MISSED SESSIONS</Text>
            <Text style={styles.body}>
              You have {recoverable.length} session{recoverable.length === 1 ? "" : "s"} you can recover.
            </Text>
          </View>
        </View>
        <View style={styles.actions}>
          <Pressable
            onPress={() => setActive(first)}
            style={[styles.btn, styles.btnPrimary]}
            testID="missed-open-first"
          >
            <Text style={styles.btnPrimaryT}>RECOVER</Text>
          </Pressable>
          {recoverable.length > 1 ? (
            <Pressable
              onPress={() => setListOpen(true)}
              style={[styles.btn, styles.btnGhost]}
              testID="missed-view-all"
            >
              <Text style={styles.btnGhostT}>VIEW ALL</Text>
            </Pressable>
          ) : null}
        </View>
      </View>

      <Modal
        visible={listOpen}
        transparent
        animationType="slide"
        onRequestClose={() => setListOpen(false)}
      >
        <View style={styles.modalRoot}>
          <Pressable style={styles.modalBackdrop} onPress={() => setListOpen(false)} />
          <View style={styles.modalSheet}>
            <View style={styles.modalHandle} />
            <View style={styles.modalHead}>
              <Text style={styles.modalTitle}>MISSED SESSIONS</Text>
              <Pressable hitSlop={12} onPress={() => setListOpen(false)}>
                <Ionicons name="close" size={22} color={theme.color.textMuted} />
              </Pressable>
            </View>
            <ScrollView>
              {recoverable.map((m) => (
                <Pressable
                  key={m.id}
                  style={styles.row}
                  onPress={() => { setListOpen(false); setActive(m); }}
                  testID={`missed-row-${m.id}`}
                >
                  <View style={styles.rowLeft}>
                    <Ionicons
                      name={m.key_session ? "star" : "barbell"}
                      size={16}
                      color={m.key_session ? theme.color.brand : theme.color.textMuted}
                    />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.rowTitle} numberOfLines={1}>{m.title || "Missed session"}</Text>
                    <Text style={styles.rowMeta}>
                      {m.date} · {m.days_ago ?? 0} day{(m.days_ago ?? 0) === 1 ? "" : "s"} ago
                      {m.key_session ? " · KEY" : ""}
                    </Text>
                  </View>
                  <Ionicons name="chevron-forward" size={14} color={theme.color.textDim} />
                </Pressable>
              ))}
            </ScrollView>
          </View>
        </View>
      </Modal>

      <RecoverySheet
        workout={active}
        visible={!!active}
        onClose={() => setActive(null)}
        onDone={load}
      />
    </>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.color.amber,
    padding: 12,
    marginBottom: 12,
  },
  headRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  iconWrap: { width: 32, height: 32, borderRadius: 16, alignItems: "center", justifyContent: "center", backgroundColor: "rgba(245,158,11,0.15)" },
  title: { color: theme.color.text, fontSize: 12, fontWeight: "900", letterSpacing: 1.5 },
  body: { color: theme.color.textMuted, fontSize: 12, marginTop: 3 },
  actions: { flexDirection: "row", gap: 8, marginTop: 10 },
  btn: { flex: 1, padding: 10, borderRadius: 8, alignItems: "center" },
  btnPrimary: { backgroundColor: theme.color.brand },
  btnPrimaryT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  btnGhost: { borderWidth: 1, borderColor: theme.color.border },
  btnGhostT: { color: theme.color.text, fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },

  modalRoot: { flex: 1, justifyContent: "flex-end" },
  modalBackdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.55)" },
  modalSheet: { backgroundColor: theme.color.surface, borderTopLeftRadius: 18, borderTopRightRadius: 18, padding: 16, maxHeight: "78%" },
  modalHandle: { alignSelf: "center", width: 44, height: 4, borderRadius: 2, backgroundColor: theme.color.border, marginBottom: 10 },
  modalHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 10 },
  modalTitle: { color: theme.color.text, fontSize: 12, fontWeight: "900", letterSpacing: 2 },
  row: { flexDirection: "row", alignItems: "center", gap: 10, padding: 12, borderRadius: 10, borderWidth: 1, borderColor: theme.color.border, marginBottom: 8 },
  rowLeft: { width: 28, alignItems: "center" },
  rowTitle: { color: theme.color.text, fontSize: 13, fontWeight: "800" },
  rowMeta: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },
});
