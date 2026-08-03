/**
 * Coach Home — Today's Action Queue (Iter 128g)
 *
 * Route: /(coach)/v2-home
 *
 * Answers ONE question for the coach: what needs my attention right now?
 * Every visible row is:
 *   1. current unresolved state
 *   2. immediately understandable
 *   3. one obvious next action
 *   4. a deep link into the exact client workspace tab
 *   5. auto-resolves as soon as the underlying state is fixed
 *
 * Backend source: /api/v2/coach/home/action-queue (deterministic aggregator).
 *
 * NOT an event log. NOT a validation dump. NOT another client directory.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { useAuth } from "@/src/lib/auth";

type Priority = "urgent" | "attention" | "upcoming" | "waiting";
type TaskType =
  | "profile_blocker"
  | "draft_review"
  | "ready_to_publish"
  | "checkin_review"
  | "message"
  | "plan_ending"
  | "roster_required"
  | "media_required"
  | "exercise_review";

type Task = {
  id: string;
  type: TaskType;
  priority: Priority;
  client_id?: string;
  client_name?: string;
  client_subtitle?: string | null;
  scope?: "system" | "client";
  title: string;
  context?: string | null;
  meta?: string | null;
  action_label: string;
  deep_link: string;
  counts?: {
    blocking?: number; important?: number; total?: number;
    client_facing?: number; training?: number; flight_support?: number;
    unresolved?: number;
  };
};

type Queue = {
  date: string;
  counts: {
    needs_action: number;
    ready_to_publish: number;
    needs_media: number;
    needs_media_client_facing: number;
    needs_media_training: number;
    needs_media_flight_support: number;
    needs_media_unresolved: number;
    messages: number;
    checkins: number;
    upcoming: number;
    waiting: number;
    active_clients: number;
  };
  needs_attention: Task[];
  upcoming: Task[];
  waiting_on_client: Task[];
};

type FilterKind =
  | "all"
  | "needs_action"
  | "ready_to_publish"
  | "needs_media"
  | "messages"
  | "checkins";

const TYPE_ICON: Record<TaskType, any> = {
  profile_blocker:  "person-circle-outline",
  draft_review:     "document-text-outline",
  ready_to_publish: "rocket-outline",
  checkin_review:   "chatbubble-ellipses-outline",
  message:          "mail-outline",
  plan_ending:      "calendar-outline",
  roster_required:  "cloud-upload-outline",
  media_required:   "images-outline",
  exercise_review:  "help-circle-outline",
};

const PRIORITY_LABEL: Record<Priority, string> = {
  urgent:    "HIGH PRIORITY",
  attention: "NEEDS ACTION",
  upcoming:  "UPCOMING",
  waiting:   "WAITING",
};

const PRIORITY_TINT: Record<Priority, string> = {
  urgent:    "#ff5b5b",
  attention: "#f5b543",
  upcoming:  "#5aa9e6",
  waiting:   "#8e8e93",
};

function formatDate(iso: string): string {
  try {
    const d = new Date(iso + "T00:00:00");
    return d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  } catch { return iso; }
}

export default function CoachHomeScreen() {
  const router = useRouter();
  useAuth();  // ensures the screen re-renders after login state changes
  const [queue, setQueue] = useState<Queue | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterKind>("all");

  // Phase 1B — Programme reset dry-run preview.
  // DELIBERATELY exposes ONLY the dry-run. Execute must be done via
  // curl using the returned token, so a mis-click cannot cause deletion.
  const [resetPreviewOpen, setResetPreviewOpen] = useState(false);
  const [resetPreview, setResetPreview] = useState<any>(null);
  const [resetBusy, setResetBusy] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);
  // Reassurance-only counts (roster/client). NOT part of the delete set.
  const [reassure, setReassure] = useState<{
    clients: number | null; rosters: number | null;
  }>({ clients: null, rosters: null });
  const runResetDryRun = useCallback(async () => {
    setResetBusy(true); setResetError(null); setResetPreview(null);
    try {
      const r = await api<any>("/admin/programme-reset/dry-run", { method: "POST" });
      setResetPreview(r);
      // Fetch reassurance counts separately (read-only endpoints).
      try {
        const clientsResp = await api<{ clients: any[] }>("/coach/clients");
        const clientsCount = Array.isArray(clientsResp?.clients)
          ? clientsResp.clients.length
          : (Array.isArray(clientsResp) ? (clientsResp as any).length : null);
        setReassure(prev => ({ ...prev, clients: clientsCount }));
      } catch { /* non-fatal */ }
    } catch (e: any) {
      setResetError(e?.message || "Dry-run failed. Are you signed in as coach?");
    } finally {
      setResetBusy(false);
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const q = await api<Queue>("/v2/coach/home/action-queue");
      setQueue(q);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Filter the visible tasks based on which summary card is currently active.
  const view = useMemo(() => {
    if (!queue) return null;
    if (filter === "all") return queue;
    const filterTypes = (arr: Task[]): Task[] => {
      switch (filter) {
        case "needs_action":     return arr;
        case "ready_to_publish": return arr.filter((t) => t.type === "ready_to_publish");
        case "needs_media":      return arr.filter((t) => t.type === "media_required" || t.type === "exercise_review");
        case "messages":         return arr.filter((t) => t.type === "message");
        case "checkins":         return arr.filter((t) => t.type === "checkin_review");
        default:                 return arr;
      }
    };
    const na = filterTypes(queue.needs_attention);
    const up = filter === "needs_action" ? [] : filterTypes(queue.upcoming);
    const wo = filter === "needs_action" ? [] : queue.waiting_on_client;
    return { ...queue, needs_attention: na, upcoming: up, waiting_on_client: wo };
  }, [queue, filter]);

  if (loading) {
    return <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>;
  }

  const q = view || queue;

  return (
    <ScrollView
      style={styles.root}
      contentContainerStyle={{ paddingBottom: 60 }}
      testID="coach-home"
    >
      {/* Manual Mode banner — Phase 1A. Reminds coach that automatic
          programme generation is paused and manual entry is the flow. */}
      <View style={styles.manualBanner} testID="manual-mode-banner">
        <Ionicons name="hand-left" size={16} color="#f5b543" />
        <Text style={styles.manualBannerText}>
          Manual programming mode — automatic programme generation is paused.
        </Text>
      </View>

      {/* Prominent "New Manual Workout" call-to-action.
          Opens the existing Clients tab; coach then taps a client → workspace
          where DayActionsMenu + ManualWorkoutBuilderSheet live per-day. */}
      <Pressable
        onPress={() => router.push("/(coach)/clients" as any)}
        style={styles.newManualBtn}
        testID="new-manual-workout-btn"
      >
        <Ionicons name="people" size={22} color="#fff" />
        <Text style={styles.newManualBtnText}>Open a client to add a manual workout</Text>
        <Ionicons name="arrow-forward" size={18} color="#fff" />
      </Pressable>

      {/* Phase 1B — Read-only Preview Programme Reset. No execute button. */}
      <Pressable
        onPress={() => { setResetPreviewOpen(true); runResetDryRun(); }}
        style={styles.resetPreviewBtn}
        testID="reset-preview-btn"
      >
        <Ionicons name="eye-outline" size={18} color={theme.color.textHi} />
        <Text style={styles.resetPreviewBtnText}>Preview Programme Reset (dry-run)</Text>
      </Pressable>

      <Modal
        visible={resetPreviewOpen} transparent animationType="fade"
        onRequestClose={() => setResetPreviewOpen(false)}
      >
        <View style={styles.resetOverlay}>
          <View style={styles.resetBox}>
            <View style={styles.resetHead}>
              <Text style={styles.resetTitle}>Programme Reset — Dry-run</Text>
              <Pressable onPress={() => setResetPreviewOpen(false)}>
                <Ionicons name="close" size={20} color={theme.color.textHi} />
              </Pressable>
            </View>
            <ScrollView style={{ maxHeight: 520 }} contentContainerStyle={{ padding: 14 }}>
              {resetBusy && <ActivityIndicator color={theme.color.brand} style={{ margin: 16 }} />}
              {resetError && <Text style={styles.resetError}>{resetError}</Text>}
              {resetPreview && (
                <>
                  <Text style={styles.resetSubHead}>
                    Total documents that WOULD be deleted:{" "}
                    <Text style={{ color: theme.color.brand, fontWeight: "800" }}>
                      {resetPreview.total_documents_to_clear}
                    </Text>
                  </Text>
                  <Text style={styles.resetLabel}>Counts to clear (per collection)</Text>
                  {Object.entries(resetPreview.counts_to_clear || {})
                    .filter(([, v]: any) => v !== 0)
                    .sort((a: any, b: any) => (b[1] as number) - (a[1] as number))
                    .map(([name, n]: any) => (
                      <View key={name} style={styles.resetRow}>
                        <Text style={styles.resetRowName}>{name}</Text>
                        <Text style={styles.resetRowN}>{n}</Text>
                      </View>
                    ))}
                  <Text style={styles.resetLabel}>Flight Support (PROTECTED — will NOT be touched)</Text>
                  {Object.entries(resetPreview.flight_support_preview || {}).map(([name, n]: any) => (
                    <View key={name} style={[styles.resetRow, { borderColor: theme.color.green + "55" }]}>
                      <Text style={[styles.resetRowName, { color: theme.color.green }]}>{name}</Text>
                      <Text style={[styles.resetRowN, { color: theme.color.green }]}>{n}</Text>
                    </View>
                  ))}
                  <Text style={styles.resetLabel}>Reassurance-only counts (NOT deleted)</Text>
                  {Object.entries(resetPreview.reassurance_counts_not_deleted || {}).map(([name, n]: any) => (
                    <View key={name} style={styles.resetRow}>
                      <Text style={styles.resetRowName}>{name}</Text>
                      <Text style={styles.resetRowN}>{n}</Text>
                    </View>
                  ))}
                  <View style={styles.resetRow}>
                    <Text style={styles.resetRowName}>clients (from /coach/clients)</Text>
                    <Text style={styles.resetRowN}>
                      {reassure.clients == null ? "—" : reassure.clients}
                    </Text>
                  </View>
                  <Text style={styles.resetLabel}>Confirmation token</Text>
                  <View style={styles.resetTokenBox}>
                    <Text selectable style={styles.resetToken}>{resetPreview.expected_token}</Text>
                  </View>
                  <Text style={styles.resetLabel}>Backup collections that will be created (on execute)</Text>
                  <Text style={styles.resetHint}>
                    programme_reset_backup_&#123;iso_utc_ts&#125;_&#123;collection_name&#125;
                    {"\n"}One backup collection per non-empty source collection.
                  </Text>
                  <Text style={styles.resetLabel}>How to execute (curl, run only after you approve)</Text>
                  <View style={styles.resetCmdBox}>
                    <Text selectable style={styles.resetCmd}>
{`curl -X POST '\${YOUR_PROD_URL}/api/admin/programme-reset/execute' \\
  -H 'Authorization: Bearer \${YOUR_COACH_TOKEN}' \\
  -H 'Content-Type: application/json' \\
  -d '{"expected_token":"${resetPreview.expected_token}","confirm":"DELETE ALL PROGRAMMES"}'`}
                    </Text>
                  </View>
                </>
              )}
            </ScrollView>
            <View style={{ padding: 12, borderTopWidth: 1, borderTopColor: theme.color.border, alignItems: "flex-end" }}>
              <Pressable onPress={() => setResetPreviewOpen(false)} style={styles.resetCloseBtn}>
                <Text style={styles.resetCloseText}>Close</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Title strip */}
      <View style={styles.titleRow}>
        <View style={{ flex: 1 }}>
          <Text style={styles.h1}>Coach Home</Text>
          <Text style={styles.h1sub}>
            {q ? formatDate(q.date) : ""}
            {q ? ` · ${q.counts.needs_action} need attention · ${q.counts.upcoming} upcoming` : ""}
          </Text>
        </View>
        <Pressable
          onPress={() => router.push("/(coach)/clients" as any)}
          style={styles.viewClientsBtn}
          testID="home-view-clients"
        >
          <Text style={styles.viewClientsText}>View clients</Text>
          <Ionicons name="arrow-forward" size={13} color={theme.color.textHi} />
        </Pressable>
      </View>

      {/* Summary cards — clickable filter chips.
          Iter 128k: UPCOMING removed from top row (§1/§24). NEEDS MEDIA
          promoted to a first-class card (§1/§5). */}
      {q && (
        <View style={styles.summaryRow}>
          <SummaryCard
            label="Needs attention" value={q.counts.needs_action} icon="alert-circle"
            tint="#ff5b5b" hint="Action required"
            active={filter === "all" || filter === "needs_action"}
            onPress={() => setFilter(filter === "needs_action" ? "all" : "needs_action")}
            testID="summary-needs-action"
          />
          <SummaryCard
            label="Ready to publish" value={q.counts.ready_to_publish} icon="rocket"
            tint="#f5b543" hint="Plan ready"
            active={filter === "ready_to_publish"}
            onPress={() => setFilter(filter === "ready_to_publish" ? "all" : "ready_to_publish")}
            testID="summary-ready-to-publish"
          />
          <SummaryCard
            label="Needs media" value={q.counts.needs_media} icon="images"
            tint="#8b7cd6"
            hint={
              q.counts.needs_media === 0
                ? "All current media ready"
                : q.counts.needs_media_client_facing > 0
                  ? `${q.counts.needs_media_client_facing} client-facing`
                  : "Library cleanup"
            }
            active={filter === "needs_media"}
            onPress={() => setFilter(filter === "needs_media" ? "all" : "needs_media")}
            testID="summary-needs-media"
          />
          <SummaryCard
            label="Messages" value={q.counts.messages} icon="chatbubble"
            tint="#5aa9e6" hint="Unread"
            active={filter === "messages"}
            onPress={() => setFilter(filter === "messages" ? "all" : "messages")}
            testID="summary-messages"
          />
          <SummaryCard
            label="Check-ins" value={q.counts.checkins} icon="checkmark-circle"
            tint="#61c982" hint="Needs review"
            active={filter === "checkins"}
            onPress={() => setFilter(filter === "checkins" ? "all" : "checkins")}
            testID="summary-checkins"
          />
        </View>
      )}

      {error && <Text style={styles.errorText}>{error}</Text>}

      {q && (
        <>
          {/* Needs your attention */}
          {q.needs_attention.length > 0 && (
            <Section
              title="NEEDS YOUR ATTENTION"
              count={q.needs_attention.length}
            >
              {q.needs_attention.map((t) => (
                <TaskCard key={t.id} task={t} onOpen={(link) => router.push(link as any)} />
              ))}
            </Section>
          )}

          {/* Upcoming */}
          {q.upcoming.length > 0 && (
            <Section title="UPCOMING" count={q.upcoming.length}>
              {q.upcoming.map((t) => (
                <TaskCard key={t.id} task={t} onOpen={(link) => router.push(link as any)} />
              ))}
            </Section>
          )}

          {/* Waiting on client */}
          {q.waiting_on_client.length > 0 && (
            <Section title="WAITING ON CLIENT" count={q.waiting_on_client.length}>
              {q.waiting_on_client.map((t) => (
                <TaskCard key={t.id} task={t} onOpen={(link) => router.push(link as any)} />
              ))}
            </Section>
          )}

          {/* Empty state */}
          {q.needs_attention.length === 0 &&
            q.upcoming.length === 0 &&
            q.waiting_on_client.length === 0 && (
            <View style={styles.emptyCaughtUp} testID="home-empty-state">
              <Ionicons name="checkmark-done-circle" size={40} color="#61c982" />
              <Text style={styles.emptyCaughtUpTitle}>You&apos;re all caught up</Text>
              <Text style={styles.emptyCaughtUpBody}>
                {filter === "all"
                  ? "No client actions need your attention right now."
                  : "Nothing in this bucket. Tap the card again to clear the filter."}
              </Text>
            </View>
          )}
        </>
      )}
    </ScrollView>
  );
}

/* -------------------------------------------------------------------------- */
/*  Summary card                                                              */
/* -------------------------------------------------------------------------- */
function SummaryCard({
  label, value, icon, tint, hint, active, onPress, testID,
}: {
  label: string; value: number; icon: any; tint: string;
  hint: string; active: boolean; onPress: () => void; testID?: string;
}) {
  const inactive = !active && (value === 0);
  return (
    <Pressable
      style={[styles.sumCell, { borderTopColor: tint }, active && styles.sumCellActive, inactive && { opacity: 0.55 }]}
      onPress={onPress}
      testID={testID}
    >
      <View style={styles.sumHead}>
        <View style={[styles.sumIcon, { backgroundColor: `${tint}22` }]}>
          <Ionicons name={icon} size={14} color={tint} />
        </View>
        <Text style={[styles.sumValue, { color: value > 0 ? theme.color.textHi : theme.color.textDim }]}>{value}</Text>
      </View>
      <Text style={styles.sumLabel}>{label}</Text>
      <Text style={styles.sumHint}>{hint}</Text>
    </Pressable>
  );
}

/* -------------------------------------------------------------------------- */
/*  Section wrapper                                                           */
/* -------------------------------------------------------------------------- */
function Section({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <View style={styles.sectionHead}>
        <Text style={styles.sectionTitle}>{title}</Text>
        <Text style={styles.sectionCount}>{count} item{count === 1 ? "" : "s"}</Text>
      </View>
      {children}
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/*  Task card                                                                 */
/* -------------------------------------------------------------------------- */
function TaskCard({ task, onOpen }: { task: Task; onOpen: (deep_link: string) => void }) {
  const tint = PRIORITY_TINT[task.priority];
  const icon = TYPE_ICON[task.type];
  const isSystem = task.scope === "system" || !task.client_name;
  return (
    <Pressable
      style={styles.taskCard}
      onPress={() => onOpen(task.deep_link)}
      testID={`task-${task.id}`}
      accessibilityLabel={
        isSystem ? task.title : `${task.client_name}: ${task.title}`
      }
    >
      {/* Left icon */}
      <View style={[styles.taskIcon, { backgroundColor: `${tint}22`, borderColor: `${tint}55` }]}>
        <Ionicons name={icon} size={18} color={tint} />
      </View>

      {/* Body */}
      <View style={styles.taskBody}>
        {/* Client / system row */}
        {isSystem ? (
          <Text style={styles.taskSystemBadge}>OPERATIONS</Text>
        ) : (
          <View style={styles.taskClientRow}>
            <Text style={styles.taskClient} numberOfLines={1}>{task.client_name}</Text>
            {task.client_subtitle ? (
              <Text style={styles.taskSubtitle} numberOfLines={1}> · {task.client_subtitle}</Text>
            ) : null}
          </View>
        )}

        {/* Title */}
        <View style={styles.taskTitleRow}>
          <View style={[styles.taskDot, { backgroundColor: tint }]} />
          <Text style={styles.taskTitle} numberOfLines={1}>{task.title}</Text>
        </View>

        {/* Context + meta */}
        {task.context ? <Text style={styles.taskContext} numberOfLines={2}>{task.context}</Text> : null}
        {task.meta ? <Text style={styles.taskMeta} numberOfLines={1}>{task.meta}</Text> : null}
      </View>

      {/* Priority badge + action button */}
      <View style={styles.taskRight}>
        <View style={[styles.priorityPill, { borderColor: `${tint}55`, backgroundColor: `${tint}18` }]}>
          <Text style={[styles.priorityPillText, { color: tint }]}>{PRIORITY_LABEL[task.priority]}</Text>
        </View>
        <Pressable
          style={[styles.actionBtn, task.priority === "urgent" && styles.actionBtnUrgent]}
          onPress={(e) => { e.stopPropagation?.(); onOpen(task.deep_link); }}
          testID={`task-action-${task.id}`}
        >
          <Text style={[styles.actionBtnText, task.priority === "urgent" && styles.actionBtnTextUrgent]}>
            {task.action_label}
          </Text>
          <Ionicons
            name="arrow-forward"
            size={12}
            color={task.priority === "urgent" ? "#fff" : theme.color.textHi}
          />
        </Pressable>
      </View>
    </Pressable>
  );
}

/* -------------------------------------------------------------------------- */
/*  Styles                                                                    */
/* -------------------------------------------------------------------------- */
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.bg },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },

  /* Phase 1A — Manual Mode banner + New Manual Workout CTA */
  manualBanner: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: "rgba(245, 181, 67, 0.12)",
    borderColor: "rgba(245, 181, 67, 0.35)", borderWidth: 1,
    borderRadius: 8, marginHorizontal: 24, marginTop: 16,
    paddingHorizontal: 14, paddingVertical: 10,
  },
  manualBannerText: {
    color: "#f5b543", fontSize: 12, fontWeight: "700",
    letterSpacing: 0.3, flex: 1,
  },
  newManualBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10,
    backgroundColor: theme.color.brand, marginHorizontal: 24, marginTop: 12,
    paddingHorizontal: 16, paddingVertical: 14, borderRadius: 10,
  },
  newManualBtnText: {
    color: "#fff", fontWeight: "800", fontSize: 15, letterSpacing: 0.4, flex: 1,
  },

  /* Phase 1B — dry-run preview */
  resetPreviewBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    marginHorizontal: 24, marginTop: 10, paddingVertical: 10, paddingHorizontal: 12,
    borderRadius: 8, borderWidth: 1, borderColor: theme.color.border,
    backgroundColor: theme.color.card,
  },
  resetPreviewBtnText: { color: theme.color.textHi, fontSize: 13, fontWeight: "600" },
  resetOverlay: {
    flex: 1, backgroundColor: "rgba(0,0,0,0.75)",
    alignItems: "center", justifyContent: "center", padding: 20,
  },
  resetBox: {
    backgroundColor: theme.color.bg, borderRadius: 12, borderWidth: 1,
    borderColor: theme.color.border, width: "100%", maxWidth: 560,
  },
  resetHead: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    padding: 14, borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  resetTitle: { color: theme.color.textHi, fontWeight: "800", fontSize: 15 },
  resetSubHead: { color: theme.color.textHi, fontSize: 13, marginBottom: 10 },
  resetLabel: {
    color: theme.color.textDim, fontSize: 10, textTransform: "uppercase",
    letterSpacing: 0.6, marginTop: 14, marginBottom: 6, fontWeight: "700",
  },
  resetRow: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    paddingHorizontal: 10, paddingVertical: 7, borderWidth: 1,
    borderColor: theme.color.border, borderRadius: 6, marginBottom: 4,
    backgroundColor: theme.color.card,
  },
  resetRowName: { color: theme.color.textHi, fontSize: 12, flex: 1 },
  resetRowN: { color: theme.color.textHi, fontSize: 12, fontWeight: "700" },
  resetError: { color: "#ff6b6b", fontSize: 12, padding: 10 },
  resetTokenBox: {
    backgroundColor: theme.color.card, borderRadius: 6, padding: 10,
    borderWidth: 1, borderColor: theme.color.border,
  },
  resetToken: { color: theme.color.brand, fontFamily: "monospace" as any, fontWeight: "700", fontSize: 13 },
  resetCmdBox: {
    backgroundColor: theme.color.card, borderRadius: 6, padding: 10,
    borderWidth: 1, borderColor: theme.color.border, marginTop: 4,
  },
  resetCmd: { color: theme.color.textHi, fontFamily: "monospace" as any, fontSize: 10 },
  resetHint: { color: theme.color.textDim, fontSize: 11, marginBottom: 4 },
  resetCloseBtn: {
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: 6,
    backgroundColor: theme.color.card, borderWidth: 1, borderColor: theme.color.border,
  },
  resetCloseText: { color: theme.color.textHi, fontWeight: "700" },

  optCard: {
    maxWidth: 480, backgroundColor: theme.color.surface2, borderRadius: 12,
    borderWidth: 1, borderColor: theme.color.border, padding: 24, alignItems: "center",
  },
  optTitle: { color: theme.color.textHi, fontSize: 20, fontWeight: "800", marginBottom: 12 },
  optBody: { color: theme.color.textDim, textAlign: "center", marginBottom: 20, lineHeight: 20 },
  primaryBtn: {
    backgroundColor: theme.color.brand, paddingHorizontal: 24, paddingVertical: 12,
    borderRadius: 8, minWidth: 200, alignItems: "center",
  },
  primaryBtnText: { color: "#fff", fontWeight: "800", letterSpacing: 1 },

  titleRow: {
    flexDirection: "row", alignItems: "flex-start", paddingHorizontal: 24, paddingTop: 22, paddingBottom: 14,
  },
  h1: { color: theme.color.textHi, fontSize: 26, fontWeight: "800", letterSpacing: 0.3 },
  h1sub: { color: theme.color.textDim, fontSize: 12, marginTop: 4 },
  viewClientsBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: theme.color.surface2, paddingHorizontal: 12, paddingVertical: 8,
    borderRadius: 8, borderWidth: 1, borderColor: theme.color.border,
  },
  viewClientsText: { color: theme.color.textHi, fontSize: 12, fontWeight: "700" },

  /* Summary cards */
  summaryRow: {
    flexDirection: "row", flexWrap: "wrap", gap: 10, marginHorizontal: 24, marginBottom: 4,
  },
  sumCell: {
    minWidth: 150, flex: 1, backgroundColor: theme.color.surface2, borderRadius: 10,
    padding: 12, borderWidth: 1, borderColor: theme.color.border,
    borderTopWidth: 3,
  },
  sumCellActive: {
    borderColor: theme.color.brand,
  },
  sumHead: { flexDirection: "row", alignItems: "center", gap: 8 },
  sumIcon: {
    width: 24, height: 24, borderRadius: 6, alignItems: "center", justifyContent: "center",
  },
  sumValue: { color: theme.color.textHi, fontSize: 22, fontWeight: "800", marginLeft: "auto" },
  sumLabel: { color: theme.color.textHi, fontSize: 12, fontWeight: "700", marginTop: 6 },
  sumHint: { color: theme.color.textDim, fontSize: 10, marginTop: 1 },

  /* Sections */
  section: { marginTop: 20, paddingHorizontal: 24 },
  sectionHead: {
    flexDirection: "row", alignItems: "center", marginBottom: 8,
  },
  sectionTitle: {
    color: theme.color.textDim, fontSize: 11, letterSpacing: 1.5, fontWeight: "800", flex: 1,
  },
  sectionCount: {
    color: theme.color.textDim, fontSize: 11, fontWeight: "700",
  },

  /* Task cards */
  taskCard: {
    flexDirection: "row", alignItems: "flex-start", gap: 12,
    backgroundColor: theme.color.surface2, borderRadius: 10,
    borderWidth: 1, borderColor: theme.color.border,
    padding: 14, marginBottom: 8,
  },
  taskIcon: {
    width: 40, height: 40, borderRadius: 20, borderWidth: 1,
    alignItems: "center", justifyContent: "center",
  },
  taskBody: { flex: 1, minWidth: 0 },
  taskClientRow: { flexDirection: "row", alignItems: "center" },
  taskSystemBadge: {
    color: "#8b7cd6", fontSize: 9, fontWeight: "800", letterSpacing: 1.5,
    marginBottom: 2,
  },
  taskClient: { color: theme.color.textHi, fontSize: 14, fontWeight: "800" },
  taskSubtitle: { color: theme.color.textDim, fontSize: 12 },
  taskTitleRow: { flexDirection: "row", alignItems: "center", marginTop: 4, gap: 6 },
  taskDot: { width: 6, height: 6, borderRadius: 3 },
  taskTitle: { color: theme.color.textHi, fontSize: 14, fontWeight: "700", flexShrink: 1 },
  taskContext: { color: theme.color.textDim, fontSize: 12, marginTop: 3, lineHeight: 17 },
  taskMeta: { color: theme.color.brand, fontSize: 11, marginTop: 3, fontStyle: "italic" },

  taskRight: {
    alignItems: "flex-end", gap: 8, minWidth: 130,
  },
  priorityPill: {
    paddingHorizontal: 8, paddingVertical: 3, borderRadius: 4, borderWidth: 1,
  },
  priorityPillText: { fontSize: 9, fontWeight: "800", letterSpacing: 1 },
  actionBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border,
    paddingHorizontal: 12, paddingVertical: 7, borderRadius: 6,
  },
  actionBtnUrgent: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  actionBtnText: { color: theme.color.textHi, fontSize: 12, fontWeight: "700" },
  actionBtnTextUrgent: { color: "#fff" },

  /* Empty */
  emptyCaughtUp: {
    marginHorizontal: 24, marginTop: 24, padding: 32,
    alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: theme.color.surface2, borderRadius: 12,
    borderWidth: 1, borderColor: theme.color.border,
  },
  emptyCaughtUpTitle: {
    color: theme.color.textHi, fontSize: 17, fontWeight: "800", marginTop: 6,
  },
  emptyCaughtUpBody: {
    color: theme.color.textDim, fontSize: 13, textAlign: "center", maxWidth: 400, lineHeight: 19,
  },

  errorText: { color: "#ff6666", padding: 16 },
});
