/**
 * Coach · Nutrition Dashboard (Phase 1).
 *
 * One-row-per-client summary: goal, targets, today's kcal/protein,
 * 7-day averages, days-logged, flags. Tap → deep dive with targets
 * editor + add-note.
 */
import React, { useCallback, useState } from "react";
import {
  ActivityIndicator, FlatList, KeyboardAvoidingView, Modal, Platform,
  Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useFocusEffect } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast } from "@/src/lib/ux";

type ClientRow = {
  user_id: string; name: string; email?: string; goal?: string;
  target_calories?: number; target_protein_g?: number;
  today_calories: number; today_protein_g: number;
  avg_calories_7d: number; avg_protein_g_7d: number;
  days_logged_7d: number;
  flag_low_protein: boolean;
  target_is_default: boolean;
};

const GOALS = [
  { key: "fat_loss", label: "FAT LOSS" }, { key: "muscle_gain", label: "MUSCLE" },
  { key: "endurance", label: "ENDURANCE" }, { key: "general_health", label: "GENERAL" },
  { key: "recovery", label: "RECOVERY" },
];

export default function CoachNutrition() {
  const router = useRouter();
  const [rows, setRows] = useState<ClientRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selected, setSelected] = useState<ClientRow | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [pending, setPending] = useState<any[]>([]);
  const [showPending, setShowPending] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [approvingId, setApprovingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [r, p] = await Promise.all([
        api<{ clients: ClientRow[] }>("/coach/nutrition/clients"),
        api<{ insights: any[] }>("/coach/nutrition/insights/pending").catch(() => ({ insights: [] })),
      ]);
      setRows(r.clients);
      setPending(p.insights || []);
    } catch (e: any) { toast(e?.message || "Load failed", "error"); }
  }, []);

  const scanTodos = async () => {
    setScanning(true);
    try {
      const r = await api<{ scanned: number; tasks_created: number }>("/coach/nutrition/scan-todos", { method: "POST", body: { force: false } });
      toast(`Scan · ${r.tasks_created} coach task${r.tasks_created === 1 ? "" : "s"} created`, "success");
      await load();
    } catch (e: any) { toast(e?.message || "Failed", "error"); }
    finally { setScanning(false); }
  };

  const approveInsight = async (id: string, applyChange: boolean) => {
    setApprovingId(id);
    try {
      await api(`/coach/nutrition/insights/${id}/approve`, { method: "POST", body: { apply_target_change: applyChange } });
      setPending((prev) => prev.filter((x) => x.id !== id));
      toast(applyChange ? "Target updated" : "Reviewed", "success");
      await load();
    } catch (e: any) { toast(e?.message || "Failed", "error"); }
    finally { setApprovingId(null); }
  };

  const dismissInsight = async (id: string) => {
    setApprovingId(id);
    try {
      await api(`/coach/nutrition/insights/${id}/dismiss`, { method: "POST", body: {} });
      setPending((prev) => prev.filter((x) => x.id !== id));
      toast("Dismissed", "success");
    } catch (e: any) { toast(e?.message || "Failed", "error"); }
    finally { setApprovingId(null); }
  };

  useFocusEffect(useCallback(() => { setLoading(true); load().finally(() => setLoading(false)); }, [load]));

  const openClient = async (c: ClientRow) => {
    setSelected(c); setDetail(null);
    try {
      const r = await api<any>(`/coach/nutrition/clients/${c.user_id}`);
      setDetail(r);
    } catch (e: any) { toast(e?.message || "Failed", "error"); }
  };

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="chevron-back" size={24} color={theme.color.text} />
        </Pressable>
        <Text style={styles.headerT}>NUTRITION</Text>
        <Pressable onPress={scanTodos} hitSlop={12} disabled={scanning} testID="coach-nutr-scan">
          {scanning ? <ActivityIndicator size="small" color={theme.color.brand} /> : (
            <Ionicons name="scan" size={20} color={theme.color.brand} />
          )}
        </Pressable>
      </View>

      {pending.length ? (
        <View style={styles.pendingBar}>
          <View style={styles.pendingIcon}>
            <Ionicons name="flag" size={12} color="#fff" />
          </View>
          <Text style={styles.pendingT}>{pending.length} pending Atlas review{pending.length === 1 ? "" : "s"}</Text>
          <Pressable onPress={() => setShowPending(true)}>
            <Text style={styles.pendingLink}>OPEN</Text>
          </Pressable>
        </View>
      ) : null}

      {loading && !rows.length ? (
        <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>
      ) : (
        <FlatList
          data={rows}
          keyExtractor={(c) => c.user_id}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} tintColor={theme.color.brand} />}
          contentContainerStyle={{ padding: 14, gap: 10 }}
          ListEmptyComponent={<Text style={styles.empty}>No clients yet.</Text>}
          renderItem={({ item }) => (
            <Pressable onPress={() => openClient(item)} style={styles.card} testID={`nutr-client-${item.user_id}`}>
              <View style={styles.cardHead}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.cardName}>{item.name}</Text>
                  <Text style={styles.cardEmail}>{item.email}</Text>
                </View>
                <View style={styles.cardGoal}>
                  <Text style={styles.cardGoalT}>{goalLabel(item.goal)}</Text>
                </View>
              </View>
              <View style={styles.cardRow}>
                <Stat k="TARGET" v={`${item.target_calories || 0}kcal · ${item.target_protein_g || 0}g P`} />
                <Stat k="TODAY" v={`${item.today_calories}kcal · ${Math.round(item.today_protein_g)}g`} />
              </View>
              <View style={styles.cardRow}>
                <Stat k="AVG 7D" v={`${item.avg_calories_7d}kcal · ${item.avg_protein_g_7d}g`} />
                <Stat k="LOGGED" v={`${item.days_logged_7d}/7 days`} />
              </View>
              <View style={styles.badgeRow}>
                {item.target_is_default ? (
                  <View style={[styles.badge, styles.badgeInfo]}>
                    <Text style={styles.badgeT}>ATLAS DEFAULT</Text>
                  </View>
                ) : (
                  <View style={[styles.badge, styles.badgeOk]}>
                    <Text style={styles.badgeT}>COACH SET</Text>
                  </View>
                )}
                {item.flag_low_protein ? (
                  <View style={[styles.badge, styles.badgeAmber]}>
                    <Ionicons name="warning" size={9} color="#fff" />
                    <Text style={styles.badgeT}>PROTEIN LOW</Text>
                  </View>
                ) : null}
                {item.days_logged_7d === 0 ? (
                  <View style={[styles.badge, styles.badgeDim]}>
                    <Text style={styles.badgeT}>NO LOGS 7D</Text>
                  </View>
                ) : null}
              </View>
            </Pressable>
          )}
        />
      )}

      {/* Client detail modal */}
      <Modal visible={!!selected} animationType="slide" onRequestClose={() => setSelected(null)} presentationStyle="pageSheet">
        <SafeAreaView style={styles.root} edges={["top"]}>
          <View style={styles.header}>
            <Pressable onPress={() => setSelected(null)} hitSlop={12}>
              <Ionicons name="close" size={24} color={theme.color.text} />
            </Pressable>
            <Text style={styles.headerT}>{selected?.name.toUpperCase()}</Text>
            <View style={{ width: 24 }} />
          </View>
          {!detail ? (
            <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>
          ) : (
            <ScrollView contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: 80 }}>
              <View style={styles.detailCard}>
                <Text style={styles.detailK}>GOAL</Text>
                <Text style={styles.detailV}>{goalLabel(detail.target?.goal)}</Text>
              </View>
              <View style={styles.detailRow}>
                <View style={styles.detailCol}><Text style={styles.detailK}>CALORIES</Text><Text style={styles.detailV}>{detail.target?.calories || 0}</Text></View>
                <View style={styles.detailCol}><Text style={styles.detailK}>PROTEIN</Text><Text style={styles.detailV}>{detail.target?.protein_g || 0}g</Text></View>
                <View style={styles.detailCol}><Text style={styles.detailK}>HYDRATION</Text><Text style={styles.detailV}>{detail.target?.hydration_ml || 0}ml</Text></View>
              </View>
              <Pressable onPress={() => setEditOpen(true)} style={styles.editBtn}>
                <Ionicons name="create-outline" size={14} color="#fff" />
                <Text style={styles.editBtnT}>EDIT TARGETS</Text>
              </Pressable>

              <Text style={styles.sect}>RECENT LOGS · {detail.recent_logs?.length || 0}</Text>
              {(detail.recent_logs || []).slice(0, 12).map((l: any) => (
                <View key={l.id} style={styles.logRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.logName}>{l.food_name}</Text>
                    <Text style={styles.logMeta}>{l.date_local} · {l.meal_type.replace(/_/g, " ").toUpperCase()}{l.roster_context ? " · " + l.roster_context.toUpperCase() : ""}</Text>
                  </View>
                  <Text style={styles.logKcal}>{l.calories}kcal · {Math.round(l.protein_g)}gP</Text>
                </View>
              ))}
              {(detail.recent_logs || []).length === 0 ? (
                <Text style={styles.empty}>No logs in the last 7 days.</Text>
              ) : null}

              <Text style={styles.sect}>COACH NOTES</Text>
              {(detail.notes || []).length === 0 ? (
                <Text style={styles.empty}>No notes yet.</Text>
              ) : (detail.notes || []).map((n: any) => (
                <View key={n.id} style={styles.noteCard}>
                  <Text style={styles.noteT}>{n.note}</Text>
                  <Text style={styles.noteMeta}>{new Date(n.created_at).toLocaleString()}</Text>
                </View>
              ))}
              <AddNote clientUserId={selected!.user_id} onAdded={(n) => setDetail((d: any) => ({ ...d, notes: [n, ...(d.notes || [])] }))} />
            </ScrollView>
          )}
        </SafeAreaView>

        {/* Edit targets modal */}
        {selected ? (
          <EditTargets
            visible={editOpen}
            initial={detail?.target}
            onClose={() => setEditOpen(false)}
            onSaved={(next) => {
              setDetail((d: any) => ({ ...d, target: next }));
              setRows((prev) => prev.map((r) => r.user_id === selected.user_id ? { ...r, target_calories: next.calories, target_protein_g: next.protein_g, goal: next.goal, target_is_default: false } : r));
              setEditOpen(false);
              toast("Targets updated", "success");
            }}
            clientUserId={selected.user_id}
          />
        ) : null}
      </Modal>

      {/* Pending Insights modal */}
      <Modal visible={showPending} animationType="slide" onRequestClose={() => setShowPending(false)} presentationStyle="pageSheet">
        <SafeAreaView style={styles.root} edges={["top"]}>
          <View style={styles.header}>
            <Pressable onPress={() => setShowPending(false)} hitSlop={12}>
              <Ionicons name="close" size={22} color={theme.color.text} />
            </Pressable>
            <Text style={styles.headerT}>ATLAS REVIEWS · {pending.length}</Text>
            <View style={{ width: 22 }} />
          </View>
          <ScrollView contentContainerStyle={{ padding: 14, gap: 10, paddingBottom: 40 }}>
            {pending.length === 0 ? (
              <Text style={styles.empty}>No pending Atlas reviews.</Text>
            ) : pending.map((i: any) => (
              <View key={i.id} style={styles.pendingCard}>
                <View style={styles.pendingHead}>
                  <Text style={styles.pendingClient}>{i.client_name}</Text>
                  <View style={[styles.actionBadge, actionBadgeColor(i.action)]}>
                    <Text style={styles.actionBadgeT}>{i.action.replace(/_/g, " ").toUpperCase()}</Text>
                  </View>
                </View>
                <Text style={styles.pendingSummary}>{i.atlas_summary}</Text>
                <Text style={styles.pendingMain}>{i.main_issue}</Text>
                {i.suggested_action ? <Text style={styles.pendingSug}>ATLAS SUGGESTS: {i.suggested_action}</Text> : null}
                {i.target_change_suggestion?.calories || i.target_change_suggestion?.protein_g ? (
                  <View style={styles.tcsCard}>
                    <Text style={styles.tcsHead}>TARGET SUGGESTION</Text>
                    <Text style={styles.tcsBody}>
                      {i.target_change_suggestion.calories ? `Calories → ${i.target_change_suggestion.calories} kcal` : ""}
                      {i.target_change_suggestion.calories && i.target_change_suggestion.protein_g ? " · " : ""}
                      {i.target_change_suggestion.protein_g ? `Protein → ${i.target_change_suggestion.protein_g}g` : ""}
                    </Text>
                  </View>
                ) : null}
                <View style={styles.pendingBtnRow}>
                  <Pressable onPress={() => dismissInsight(i.id)} disabled={approvingId === i.id}
                    style={[styles.pBtn, styles.pBtnGhost, approvingId === i.id && { opacity: 0.4 }]}>
                    <Text style={styles.pBtnGhostT}>DISMISS</Text>
                  </Pressable>
                  {i.target_change_suggestion?.calories || i.target_change_suggestion?.protein_g ? (
                    <Pressable onPress={() => approveInsight(i.id, true)} disabled={approvingId === i.id}
                      style={[styles.pBtn, styles.pBtnPri, approvingId === i.id && { opacity: 0.4 }]}>
                      {approvingId === i.id ? <ActivityIndicator color="#fff" size="small" /> :
                        <Text style={styles.pBtnT}>APPROVE + APPLY</Text>}
                    </Pressable>
                  ) : (
                    <Pressable onPress={() => approveInsight(i.id, false)} disabled={approvingId === i.id}
                      style={[styles.pBtn, styles.pBtnPri, approvingId === i.id && { opacity: 0.4 }]}>
                      {approvingId === i.id ? <ActivityIndicator color="#fff" size="small" /> :
                        <Text style={styles.pBtnT}>MARK REVIEWED</Text>}
                    </Pressable>
                  )}
                </View>
              </View>
            ))}
          </ScrollView>
        </SafeAreaView>
      </Modal>
    </SafeAreaView>
  );
}

function Stat({ k, v }: { k: string; v: string }) {
  return (
    <View style={{ flex: 1 }}>
      <Text style={styles.statK}>{k}</Text>
      <Text style={styles.statV}>{v}</Text>
    </View>
  );
}

function goalLabel(g?: string) {
  return ({ fat_loss: "Fat loss", muscle_gain: "Muscle gain", endurance: "Endurance", general_health: "General health", recovery: "Recovery" } as any)[g || ""] || "General";
}

function actionBadgeColor(a: string) {
  if (a === "keep") return { backgroundColor: theme.color.green };
  if (a === "flag_coach_review") return { backgroundColor: "#c94a4a" };
  if (a === "protein_focus" || a === "adjust_calories") return { backgroundColor: theme.color.brand };
  if (a === "simplify") return { backgroundColor: theme.color.amber };
  if (a === "add_travel_strategy") return { backgroundColor: "#3B82F6" };
  return { backgroundColor: theme.color.textDim };
}

/* -------------------- Edit Targets modal -------------------- */

function EditTargets({
  visible, initial, onClose, onSaved, clientUserId,
}: {
  visible: boolean; initial?: any; onClose: () => void;
  onSaved: (next: any) => void; clientUserId: string;
}) {
  const [cal, setCal] = useState(String(initial?.calories || 2200));
  const [pro, setPro] = useState(String(initial?.protein_g || 140));
  const [carb, setCarb] = useState(String(initial?.carbs_g || 240));
  const [fat, setFat] = useState(String(initial?.fats_g || 70));
  const [hyd, setHyd] = useState(String(initial?.hydration_ml || 2500));
  const [goal, setGoal] = useState<string>(initial?.goal || "general_health");
  const [saving, setSaving] = useState(false);

  React.useEffect(() => {
    if (visible && initial) {
      setCal(String(initial.calories || 2200));
      setPro(String(initial.protein_g || 140));
      setCarb(String(initial.carbs_g || 240));
      setFat(String(initial.fats_g || 70));
      setHyd(String(initial.hydration_ml || 2500));
      setGoal(initial.goal || "general_health");
    }
  }, [visible, initial]);

  const save = async () => {
    setSaving(true);
    try {
      const r = await api<{ target: any }>(`/coach/nutrition/targets/${clientUserId}`, {
        method: "PATCH",
        body: {
          calories: parseInt(cal, 10) || undefined,
          protein_g: parseInt(pro, 10) || undefined,
          carbs_g: parseInt(carb, 10) || undefined,
          fats_g: parseInt(fat, 10) || undefined,
          hydration_ml: parseInt(hyd, 10) || undefined,
          goal,
          target_type: "coach",
        },
      });
      onSaved(r.target);
    } catch (e: any) { toast(e?.message || "Failed", "error"); }
    finally { setSaving(false); }
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView style={styles.editBackdrop} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <View style={styles.editSheet}>
          <View style={styles.header}>
            <Pressable onPress={onClose} hitSlop={12}>
              <Ionicons name="close" size={22} color={theme.color.textMuted} />
            </Pressable>
            <Text style={styles.headerT}>EDIT TARGETS</Text>
            <View style={{ width: 22 }} />
          </View>
          <ScrollView contentContainerStyle={{ padding: 16, gap: 10 }}>
            <Text style={styles.label}>GOAL</Text>
            <View style={styles.chipRow}>
              {GOALS.map((g) => (
                <Pressable key={g.key} onPress={() => setGoal(g.key)}
                  style={[styles.chip, goal === g.key && styles.chipOn]}>
                  <Text style={[styles.chipT, goal === g.key && styles.chipTOn]}>{g.label}</Text>
                </Pressable>
              ))}
            </View>
            <FieldRow label="CALORIES (kcal)" value={cal} setValue={setCal} />
            <FieldRow label="PROTEIN (g)" value={pro} setValue={setPro} />
            <FieldRow label="CARBS (g)" value={carb} setValue={setCarb} />
            <FieldRow label="FATS (g)" value={fat} setValue={setFat} />
            <FieldRow label="HYDRATION (ml)" value={hyd} setValue={setHyd} />
            <Text style={styles.safety}>
              Safety floors: 1500 kcal · 60g protein · 1500ml hydration. Values below the floor will be raised automatically.
            </Text>
          </ScrollView>
          <View style={styles.footer}>
            <Pressable onPress={onClose} style={[styles.footerBtn, styles.footerBtnGhost]}>
              <Text style={styles.footerBtnGhostT}>CANCEL</Text>
            </Pressable>
            <Pressable onPress={save} disabled={saving} style={[styles.footerBtn, styles.footerBtnPri, saving && { opacity: 0.5 }]}>
              {saving ? <ActivityIndicator color="#fff" /> : <Text style={styles.footerBtnT}>SAVE</Text>}
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

function FieldRow({ label, value, setValue }: { label: string; value: string; setValue: (v: string) => void }) {
  return (
    <View>
      <Text style={styles.label}>{label}</Text>
      <TextInput value={value} onChangeText={setValue} style={styles.input} keyboardType="numeric" />
    </View>
  );
}

/* -------------------- Add note -------------------- */

function AddNote({ clientUserId, onAdded }: { clientUserId: string; onAdded: (n: any) => void }) {
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const add = async () => {
    if (!text.trim()) return;
    setSaving(true);
    try {
      const r = await api<{ note: any }>("/coach/nutrition/notes", {
        method: "POST", body: { client_user_id: clientUserId, note: text.trim(), kind: "nutrition" },
      });
      onAdded(r.note); setText("");
    } catch (e: any) { toast(e?.message || "Failed", "error"); }
    finally { setSaving(false); }
  };
  return (
    <View style={styles.noteBox}>
      <TextInput value={text} onChangeText={setText} style={styles.noteInput} multiline
        placeholder="Add a coaching note…" placeholderTextColor={theme.color.textDim} />
      <Pressable onPress={add} disabled={!text.trim() || saving}
        style={[styles.noteBtn, (!text.trim() || saving) && { opacity: 0.4 }]}>
        {saving ? <ActivityIndicator size="small" color="#fff" /> : (
          <><Ionicons name="add" size={14} color="#fff" /><Text style={styles.noteBtnT}>ADD</Text></>
        )}
      </Pressable>
    </View>
  );
}

/* -------------------- Styles -------------------- */

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  empty: { color: theme.color.textDim, fontStyle: "italic", textAlign: "center", padding: 20 },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 14, borderBottomWidth: 1, borderBottomColor: theme.color.divider },
  headerT: { color: theme.color.text, fontSize: 14, letterSpacing: 3, fontWeight: "900", fontFamily: theme.font.display },

  pendingBar: { flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 14, paddingVertical: 10, backgroundColor: theme.color.brandTint, borderBottomWidth: 1, borderBottomColor: theme.color.brand },
  pendingIcon: { width: 22, height: 22, borderRadius: 11, backgroundColor: theme.color.brand, alignItems: "center", justifyContent: "center" },
  pendingT: { color: theme.color.text, fontSize: 12, fontWeight: "900", letterSpacing: 0.5, flex: 1, fontFamily: theme.font.textSemi },
  pendingLink: { color: theme.color.brand, fontSize: 11, letterSpacing: 1.5, fontWeight: "900" },

  pendingCard: { padding: 14, borderRadius: 12, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.brand, gap: 8 },
  pendingHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  pendingClient: { color: theme.color.text, fontSize: 14, fontWeight: "900", fontFamily: theme.font.display },
  actionBadge: { paddingHorizontal: 6, paddingVertical: 3, borderRadius: 4 },
  actionBadgeT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 0.8 },
  pendingSummary: { color: theme.color.text, fontSize: 12, lineHeight: 18, fontFamily: theme.font.text },
  pendingMain: { color: theme.color.textMuted, fontSize: 11, lineHeight: 16 },
  pendingSug: { color: theme.color.brand, fontSize: 11, fontStyle: "italic" },
  tcsCard: { padding: 10, borderRadius: 8, backgroundColor: theme.color.surface3 },
  tcsHead: { color: theme.color.brand, fontSize: 11, letterSpacing: 1.5, fontWeight: "900" },
  tcsBody: { color: theme.color.text, fontSize: 13, marginTop: 4, fontWeight: "800" },
  pendingBtnRow: { flexDirection: "row", gap: 8, marginTop: 4 },
  pBtn: { flex: 1, paddingVertical: 10, borderRadius: 8, alignItems: "center", justifyContent: "center" },
  pBtnGhost: { backgroundColor: theme.color.surface3, borderWidth: 1, borderColor: theme.color.border },
  pBtnGhostT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1 },
  pBtnPri: { backgroundColor: theme.color.brand },
  pBtnT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1 },

  card: { padding: 12, borderRadius: 12, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, gap: 8 },
  cardHead: { flexDirection: "row", alignItems: "center" },
  cardName: { color: theme.color.text, fontSize: 15, fontWeight: "900", fontFamily: theme.font.display },
  cardEmail: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },
  cardGoal: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6, backgroundColor: theme.color.brandTint, borderWidth: 1, borderColor: theme.color.brand },
  cardGoalT: { color: theme.color.brand, fontSize: 11, letterSpacing: 1, fontWeight: "900" },
  cardRow: { flexDirection: "row", gap: 8 },
  statK: { color: theme.color.textDim, fontSize: 11, letterSpacing: 1.3, fontWeight: "900" },
  statV: { color: theme.color.text, fontSize: 12, fontWeight: "800", marginTop: 2 },
  badgeRow: { flexDirection: "row", gap: 4, flexWrap: "wrap", marginTop: 2 },
  badge: { flexDirection: "row", alignItems: "center", gap: 3, paddingHorizontal: 6, paddingVertical: 3, borderRadius: 4 },
  badgeInfo: { backgroundColor: theme.color.textDim },
  badgeOk: { backgroundColor: theme.color.green },
  badgeAmber: { backgroundColor: theme.color.amber },
  badgeDim: { backgroundColor: theme.color.surface3, borderWidth: 1, borderColor: theme.color.border },
  badgeT: { color: "#fff", fontSize: 11, letterSpacing: 0.7, fontWeight: "900" },

  detailCard: { padding: 12, borderRadius: 10, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, alignItems: "center" },
  detailRow: { flexDirection: "row", gap: 8 },
  detailCol: { flex: 1, padding: 10, borderRadius: 10, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, alignItems: "center" },
  detailK: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1.5, fontWeight: "900" },
  detailV: { color: theme.color.text, fontSize: 16, fontWeight: "900", marginTop: 4, fontFamily: theme.font.display },
  editBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: 12, borderRadius: 8, backgroundColor: theme.color.brand },
  editBtnT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },

  sect: { color: theme.color.brand, fontSize: 11, letterSpacing: 2, fontWeight: "900", marginTop: 8, fontFamily: theme.font.textSemi },
  logRow: { flexDirection: "row", padding: 10, borderRadius: 8, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, alignItems: "center" },
  logName: { color: theme.color.text, fontSize: 13, fontWeight: "800" },
  logMeta: { color: theme.color.textMuted, fontSize: 11, marginTop: 2, letterSpacing: 0.5 },
  logKcal: { color: theme.color.textMuted, fontSize: 11, fontWeight: "800" },

  noteCard: { padding: 12, borderRadius: 10, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  noteT: { color: theme.color.text, fontSize: 13, lineHeight: 19, fontFamily: theme.font.text },
  noteMeta: { color: theme.color.textDim, fontSize: 11, marginTop: 6 },
  noteBox: { flexDirection: "row", gap: 8, alignItems: "flex-start" },
  noteInput: { flex: 1, minHeight: 60, color: theme.color.text, backgroundColor: theme.color.surface2, borderRadius: 8, padding: 10, borderWidth: 1, borderColor: theme.color.border, fontSize: 13 },
  noteBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 12, paddingVertical: 12, borderRadius: 8, backgroundColor: theme.color.brand, alignSelf: "flex-start" },
  noteBtnT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1 },

  editBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.7)", justifyContent: "flex-end" },
  editSheet: { backgroundColor: theme.color.surface, borderTopLeftRadius: 16, borderTopRightRadius: 16, maxHeight: "90%" },
  label: { color: theme.color.brand, fontSize: 11, letterSpacing: 2, fontWeight: "900", marginTop: 4, fontFamily: theme.font.textSemi },
  input: { color: theme.color.text, backgroundColor: theme.color.surface2, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 10, fontSize: 14, borderWidth: 1, borderColor: theme.color.border, marginTop: 4 },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 4 },
  chip: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 20, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  chipOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1 },
  chipTOn: { color: "#fff" },
  safety: { color: theme.color.textDim, fontSize: 11, marginTop: 8, fontStyle: "italic", lineHeight: 15 },
  footer: { flexDirection: "row", gap: 8, padding: 14, borderTopWidth: 1, borderTopColor: theme.color.divider },
  footerBtn: { flex: 1, paddingVertical: 12, borderRadius: 8, alignItems: "center" },
  footerBtnGhost: { backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  footerBtnGhostT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1 },
  footerBtnPri: { backgroundColor: theme.color.brand },
  footerBtnT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
});
