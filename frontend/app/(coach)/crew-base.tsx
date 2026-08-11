/**
 * Iter 129b — Crew Base Coach Workspace.
 *
 * Two-column community command centre:
 *   • Left (~68%): Community Calendar (month view) with post chips per day.
 *                  Click a day → composer opens with that date preselected.
 *                  Beneath: Unscheduled Drafts strip.
 *   • Right (~32%): Tabbed panel — FEED (published) | MESSAGES (private).
 *
 * REUSES the existing Crew Base backend (posts / feed / scheduled / drafts)
 * and the existing Messages backend. No backend changes.
 *
 * Clients continue to see the community feed via the (client)/base tab.
 * This scheduling calendar is COACH-ONLY.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ScrollView, ActivityIndicator, useWindowDimensions,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast } from "@/src/lib/ux";
import { CrewBasePostCard, CrewBasePost } from "@/src/components/crew-base/CrewBasePostCard";
import { CrewBaseComposer } from "@/src/components/crew-base/CrewBaseComposer";
import { InstantPostComposer } from "@/src/components/crew-base/InstantPostComposer";

/* -------------------------------------------------------------------------- */
/*  Types                                                                      */
/* -------------------------------------------------------------------------- */

type CoachPost = {
  id: string;
  text?: string;
  media_type?: "none" | "image" | "video";
  status: "draft" | "scheduled" | "published" | "deleted";
  scheduled_at?: string | null;
  published_at?: string | null;
  updated_at?: string;
  created_at?: string;
};

type Partner = {
  id: string;
  name: string;
  email?: string;
  role: string;
  avatar_url?: string;
};

/* -------------------------------------------------------------------------- */
/*  Date helpers                                                               */
/* -------------------------------------------------------------------------- */

function startOfMonth(d: Date) { return new Date(d.getFullYear(), d.getMonth(), 1); }
function addMonths(d: Date, delta: number) {
  return new Date(d.getFullYear(), d.getMonth() + delta, 1);
}
function isSameDay(a: Date, b: Date) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}
function dateKey(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function monthLabel(d: Date) {
  return d.toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

/** Return 6*7 = 42 cells starting Monday of the week that contains day 1. */
function buildMonthGrid(anchor: Date): { date: Date; inMonth: boolean }[] {
  const first = startOfMonth(anchor);
  const dow = (first.getDay() + 6) % 7; // Monday-based
  const start = new Date(first.getFullYear(), first.getMonth(), 1 - dow);
  const cells: { date: Date; inMonth: boolean }[] = [];
  for (let i = 0; i < 42; i++) {
    const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
    cells.push({ date: d, inMonth: d.getMonth() === anchor.getMonth() });
  }
  return cells;
}

function shortPostLabel(p: CoachPost): string {
  const t = (p.text || "").trim().replace(/\s+/g, " ");
  return t ? (t.length > 36 ? t.slice(0, 36) + "…" : t) : "(no text)";
}

function timeLabel(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/* -------------------------------------------------------------------------- */
/*  Screen                                                                     */
/* -------------------------------------------------------------------------- */

type RightTab = "feed" | "messages";

export default function CoachCrewBaseScreen() {
  const router = useRouter();
  const { width } = useWindowDimensions();
  const isDesktop = width >= 1100;

  const [anchor, setAnchor] = useState<Date>(startOfMonth(new Date()));
  const [scheduled, setScheduled] = useState<CoachPost[]>([]);
  const [drafts, setDrafts] = useState<CoachPost[]>([]);
  const [feed, setFeed] = useState<CrewBasePost[]>([]);
  const [partners, setPartners] = useState<Partner[]>([]);
  const [loading, setLoading] = useState(true);

  const [composerOpen, setComposerOpen] = useState(false);
  const [composerDate, setComposerDate] = useState<Date | null>(null);
  const [rightTab, setRightTab] = useState<RightTab>("feed");

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [s, d, f] = await Promise.all([
        api<{ posts: CoachPost[] }>("/crew-base/coach/scheduled").catch(() => ({ posts: [] })),
        api<{ posts: CoachPost[] }>("/crew-base/coach/drafts").catch(() => ({ posts: [] })),
        api<{ posts: CrewBasePost[] }>("/crew-base/feed?limit=60").catch(() => ({ posts: [] })),
      ]);
      setScheduled(s.posts || []);
      setDrafts(d.posts || []);
      setFeed(f.posts || []);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadPartners = useCallback(async () => {
    try {
      const rows = await api<Partner[]>("/messages");
      setPartners(Array.isArray(rows) ? rows : []);
    } catch {
      setPartners([]);
    }
  }, []);

  useEffect(() => { loadAll(); loadPartners(); }, [loadAll, loadPartners]);

  /* ------------------------------------------------------------------- */
  /*  Post → calendar map                                                 */
  /* ------------------------------------------------------------------- */
  const postsByDate = useMemo(() => {
    const map: Record<string, CoachPost[]> = {};
    // Scheduled posts
    for (const p of scheduled) {
      if (!p.scheduled_at) continue;
      const d = new Date(p.scheduled_at);
      if (Number.isNaN(d.getTime())) continue;
      const key = dateKey(d);
      (map[key] ||= []).push(p);
    }
    // Dated drafts (drafts with scheduled_at set but status still draft)
    for (const p of drafts) {
      if (!p.scheduled_at) continue;
      const d = new Date(p.scheduled_at);
      if (Number.isNaN(d.getTime())) continue;
      const key = dateKey(d);
      (map[key] ||= []).push(p);
    }
    // Published posts — from feed
    for (const p of feed) {
      const iso = p.published_at || null;
      if (!iso) continue;
      const d = new Date(iso);
      if (Number.isNaN(d.getTime())) continue;
      const key = dateKey(d);
      // Adapt feed shape to CoachPost minimal shape
      (map[key] ||= []).push({
        id: p.id, text: p.text, media_type: p.media_type,
        status: "published", published_at: iso,
      });
    }
    return map;
  }, [scheduled, drafts, feed]);

  const unscheduledDrafts = useMemo(
    () => drafts.filter((d) => !d.scheduled_at),
    [drafts],
  );

  const upcoming = useMemo(() => {
    const now = Date.now();
    return [...scheduled]
      .filter((p) => p.scheduled_at && new Date(p.scheduled_at).getTime() >= now)
      .sort((a, b) => (a.scheduled_at || "").localeCompare(b.scheduled_at || ""))
      .slice(0, 4);
  }, [scheduled]);

  /* ------------------------------------------------------------------- */
  /*  Actions                                                            */
  /* ------------------------------------------------------------------- */
  const openComposer = (d: Date | null) => {
    setComposerDate(d);
    setComposerOpen(true);
  };

  const closeComposer = () => {
    setComposerOpen(false);
    setComposerDate(null);
  };

  const publishNow = async (postId: string) => {
    try {
      await api(`/crew-base/posts/${postId}/publish`, { method: "POST", body: {} });
      toast("Published.", "success");
      loadAll();
    } catch (e: any) {
      toast(e?.message || "Publish failed.", "error");
    }
  };

  const deletePost = async (postId: string) => {
    try {
      await api(`/crew-base/posts/${postId}`, { method: "DELETE" });
      toast("Post deleted.", "success");
      loadAll();
    } catch (e: any) {
      toast(e?.message || "Delete failed.", "error");
    }
  };

  const openMessages = (partnerId?: string) => {
    const path = partnerId ? `/(coach)/messages?partner=${partnerId}` : "/(coach)/messages";
    router.push(path as any);
  };

  /* ------------------------------------------------------------------- */
  /*  Render                                                             */
  /* ------------------------------------------------------------------- */
  const grid = useMemo(() => buildMonthGrid(anchor), [anchor]);

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      {/* Header */}
      <View style={styles.headerBar}>
        <View>
          <Text style={styles.h1}>Crew Base</Text>
          <Text style={styles.sub}>Community command centre — plan, publish and moderate.</Text>
        </View>
        <Pressable onPress={() => openComposer(null)} style={styles.newBtn} testID="cb-new-post">
          <Ionicons name="add" size={16} color="#fff" />
          <Text style={styles.newBtnT}>NEW POST</Text>
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={{ paddingBottom: 40 }}>
        <View style={[styles.body, isDesktop ? { flexDirection: "row", alignItems: "flex-start" } : null]}>
          {/* -------- LEFT: CALENDAR -------- */}
          <View style={[styles.leftCol, isDesktop ? { flexBasis: "68%", flexGrow: 1, paddingRight: 12 } : null]}>
            {/* Month navigation */}
            <View style={styles.monthNav}>
              <Pressable onPress={() => setAnchor(addMonths(anchor, -1))} style={styles.monthNavBtn} testID="cb-cal-prev">
                <Ionicons name="chevron-back" size={16} color={theme.color.text} />
              </Pressable>
              <Text style={styles.monthLabel}>{monthLabel(anchor)}</Text>
              <Pressable onPress={() => setAnchor(addMonths(anchor, 1))} style={styles.monthNavBtn} testID="cb-cal-next">
                <Ionicons name="chevron-forward" size={16} color={theme.color.text} />
              </Pressable>
              <Pressable onPress={() => setAnchor(startOfMonth(new Date()))} style={styles.todayBtn} testID="cb-cal-today">
                <Text style={styles.todayBtnT}>Today</Text>
              </Pressable>
            </View>

            {/* Day-of-week row */}
            <View style={styles.dowRow}>
              {["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"].map((d) => (
                <Text key={d} style={styles.dowLabel}>{d}</Text>
              ))}
            </View>

            {/* Grid */}
            <View style={styles.grid}>
              {grid.map(({ date, inMonth }, idx) => {
                const key = dateKey(date);
                const posts = postsByDate[key] || [];
                const isToday = isSameDay(date, new Date());
                return (
                  <Pressable
                    key={idx}
                    onPress={() => openComposer(date)}
                    style={[
                      styles.cell,
                      !inMonth && styles.cellDim,
                      isToday && styles.cellToday,
                    ]}
                    testID={`cb-cell-${key}`}
                  >
                    <View style={styles.cellHead}>
                      <Text style={[styles.cellDate, !inMonth && { color: theme.color.textDim }, isToday && { color: theme.color.brand }]}>
                        {date.getDate()}
                      </Text>
                      <Text style={styles.cellPlus}>+</Text>
                    </View>
                    {posts.slice(0, 3).map((p) => (
                      <View
                        key={p.id}
                        style={[
                          styles.chip,
                          p.status === "published" ? styles.chipPub :
                          p.status === "scheduled" ? styles.chipSched : styles.chipDraft,
                        ]}
                      >
                        <Text style={styles.chipTime}>{timeLabel(p.scheduled_at || p.published_at)}</Text>
                        <Text style={styles.chipTitle} numberOfLines={2}>{shortPostLabel(p)}</Text>
                        <View style={styles.chipFoot}>
                          {p.media_type && p.media_type !== "none" ? (
                            <Ionicons
                              name={p.media_type === "video" ? "videocam" : "image"}
                              size={9}
                              color={theme.color.textMuted}
                            />
                          ) : null}
                          <Text style={styles.chipStatus}>
                            {p.status === "published" ? "Published" : p.status === "scheduled" ? "Scheduled" : "Draft"}
                          </Text>
                        </View>
                      </View>
                    ))}
                    {posts.length > 3 ? (
                      <Text style={styles.moreLine}>+{posts.length - 3} more</Text>
                    ) : null}
                  </Pressable>
                );
              })}
            </View>

            {/* Upcoming */}
            {upcoming.length > 0 ? (
              <View style={styles.upcomingBlock}>
                <Text style={styles.section}>UPCOMING POSTS</Text>
                {upcoming.map((p) => (
                  <Pressable key={p.id} style={styles.upRow} onPress={() => publishNow(p.id)} testID={`cb-up-${p.id}`}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.upTitle} numberOfLines={1}>{shortPostLabel(p)}</Text>
                      <Text style={styles.upMeta}>
                        {new Date(p.scheduled_at!).toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
                        {" · Scheduled"}
                      </Text>
                    </View>
                    <View style={{ flexDirection: "row", gap: 6 }}>
                      <View style={styles.upBadge}>
                        <Text style={styles.upBadgeT}>PUBLISH NOW</Text>
                      </View>
                    </View>
                  </Pressable>
                ))}
              </View>
            ) : null}

            {/* Unscheduled drafts */}
            {unscheduledDrafts.length > 0 ? (
              <View style={styles.draftsBlock}>
                <Text style={styles.section}>UNSCHEDULED DRAFTS · {unscheduledDrafts.length}</Text>
                {unscheduledDrafts.map((p) => (
                  <View key={p.id} style={styles.draftRow}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.draftTitle} numberOfLines={1}>{shortPostLabel(p)}</Text>
                      <Text style={styles.draftMeta}>
                        {p.media_type && p.media_type !== "none" ? `${p.media_type} · ` : ""}
                        updated {new Date(p.updated_at || p.created_at || "").toLocaleDateString()}
                      </Text>
                    </View>
                    <View style={{ flexDirection: "row", gap: 6 }}>
                      <Pressable onPress={() => publishNow(p.id)} style={styles.miniBtn} testID={`cb-draft-publish-${p.id}`}>
                        <Text style={styles.miniBtnT}>PUBLISH</Text>
                      </Pressable>
                      <Pressable onPress={() => deletePost(p.id)} style={[styles.miniBtn, styles.miniBtnDanger]}>
                        <Text style={[styles.miniBtnT, { color: theme.color.red }]}>DELETE</Text>
                      </Pressable>
                    </View>
                  </View>
                ))}
              </View>
            ) : null}
          </View>

          {/* -------- RIGHT: FEED / MESSAGES -------- */}
          <View style={[styles.rightCol, isDesktop ? { flexBasis: "32%", minWidth: 340 } : { marginTop: 16 }]}>
            <View style={styles.tabs}>
              {(["feed", "messages"] as RightTab[]).map((k) => {
                const active = rightTab === k;
                // Feed tab shows just the label (§21 — no meaningless number).
                // Messages tab shows conversation count when we have partners.
                const label = k === "feed"
                  ? "FEED"
                  : (partners.length > 0 ? `MESSAGES · ${partners.length}` : "MESSAGES");
                return (
                  <Pressable key={k} onPress={() => setRightTab(k)} style={[styles.tab, active && styles.tabActive]} testID={`cb-side-tab-${k}`}>
                    <Text style={[styles.tabT, active && styles.tabTActive]}>{label}</Text>
                  </Pressable>
                );
              })}
            </View>

            {/* FEED — same rendering the client sees, with a sticky quick composer.
                Comments, reactions and privacy are all resolved server-side via
                the shared CrewBasePostCard component (§3, §5). */}
            {rightTab === "feed" ? (
              <View style={styles.rightFeedStack}>
                <ScrollView style={styles.rightScroll} contentContainerStyle={{ paddingBottom: 20 }}>
                  {loading ? (
                    <View style={{ padding: 30, alignItems: "center" }}><ActivityIndicator /></View>
                  ) : feed.length === 0 ? (
                    <View style={styles.empty}>
                      <Ionicons name="megaphone-outline" size={32} color={theme.color.textDim} />
                      <Text style={styles.emptyT}>No community posts yet.</Text>
                      <Text style={styles.emptySub}>Start the conversation below.</Text>
                    </View>
                  ) : (
                    feed.map((p) => (
                      <CrewBasePostCard
                        key={p.id}
                        post={p}
                        viewerIsCoach
                        onChanged={loadAll}
                        onDeleteRequested={() => deletePost(p.id)}
                      />
                    ))
                  )}
                </ScrollView>
                {/* Sticky quick composer — POST-now-only. Same backend as the
                    full composer; scheduling stays inside + NEW POST / calendar. */}
                <InstantPostComposer onPosted={loadAll} />
              </View>
            ) : (
              <ScrollView style={styles.rightScroll} contentContainerStyle={{ paddingBottom: 40 }}>
                <Pressable onPress={() => openMessages()} style={styles.viewInboxRow} testID="cb-view-inbox">
                  <Text style={styles.viewInboxT}>View full inbox</Text>
                  <Ionicons name="arrow-forward" size={14} color={theme.color.brand} />
                </Pressable>
                {partners.length === 0 ? (
                  <View style={styles.empty}>
                    <Ionicons name="chatbubbles-outline" size={32} color={theme.color.textDim} />
                    <Text style={styles.emptyT}>No conversations yet.</Text>
                  </View>
                ) : (
                  partners.map((p) => (
                    <Pressable
                      key={p.id}
                      onPress={() => openMessages(p.id)}
                      style={styles.convRow}
                      testID={`cb-conv-${p.id}`}
                    >
                      <View style={styles.convAvatar}>
                        <Text style={styles.convAvatarT}>
                          {(p.name || p.email || "?").split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase()}
                        </Text>
                      </View>
                      <View style={{ flex: 1 }}>
                        <Text style={styles.convName} numberOfLines={1}>{p.name || p.email || "(unnamed)"}</Text>
                        <Text style={styles.convMeta} numberOfLines={1}>
                          Private conversation · Coach only
                        </Text>
                      </View>
                      <Ionicons name="chevron-forward" size={14} color={theme.color.textMuted} />
                    </Pressable>
                  ))
                )}
              </ScrollView>
            )}
          </View>
        </View>
      </ScrollView>

      <CrewBaseComposer
        visible={composerOpen}
        onClose={closeComposer}
        onSaved={() => { closeComposer(); loadAll(); }}
        initial={composerDate ? { scheduleDate: composerDate } : undefined}
      />
    </SafeAreaView>
  );
}

/* -------------------------------------------------------------------------- */
/*  Styles                                                                     */
/* -------------------------------------------------------------------------- */

const CELL_MIN_HEIGHT = 96;

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.color.bg },

  headerBar: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: theme.space.lg, paddingVertical: theme.space.md,
    borderBottomWidth: 1, borderBottomColor: theme.color.divider,
  },
  h1: { color: theme.color.text, fontSize: 22, fontWeight: "900" },
  sub: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },
  newBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: 8,
    backgroundColor: theme.color.brand,
  },
  newBtnT: { color: "#fff", fontWeight: "900", fontSize: 11, letterSpacing: 1.5 },

  body: { padding: theme.space.md, gap: 12 },
  leftCol: {},
  rightCol: {},

  monthNav: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 8 },
  monthNavBtn: {
    width: 30, height: 30, borderRadius: 6,
    alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface,
  },
  monthLabel: { color: theme.color.text, fontSize: 15, fontWeight: "900", marginHorizontal: 4 },
  todayBtn: {
    marginLeft: 6, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6,
    borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface,
  },
  todayBtnT: { color: theme.color.text, fontSize: 11, fontWeight: "800", letterSpacing: 0.5 },

  dowRow: { flexDirection: "row" },
  dowLabel: {
    flex: 1, textAlign: "center",
    color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1.5,
    paddingVertical: 6,
  },

  grid: { flexDirection: "row", flexWrap: "wrap" },
  cell: {
    width: `${100 / 7}%`,
    minHeight: CELL_MIN_HEIGHT,
    borderWidth: 1,
    borderColor: theme.color.divider,
    padding: 4,
    backgroundColor: theme.color.surface,
  },
  cellDim: { backgroundColor: "transparent" },
  cellToday: { backgroundColor: theme.color.brandTint, borderColor: theme.color.brand },
  cellHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  cellDate: { color: theme.color.text, fontSize: 11, fontWeight: "800" },
  cellPlus: { color: theme.color.textDim, fontSize: 12, fontWeight: "900" },

  chip: {
    marginTop: 3, padding: 4, borderRadius: 4, borderLeftWidth: 3,
    backgroundColor: theme.color.surface2,
  },
  chipPub: { borderLeftColor: theme.color.green || "#22c55e" },
  chipSched: { borderLeftColor: theme.color.brand },
  chipDraft: { borderLeftColor: theme.color.textMuted },
  chipTime: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 0.4 },
  chipTitle: { color: theme.color.text, fontSize: 11, fontWeight: "700", lineHeight: 12 },
  chipFoot: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 2 },
  chipStatus: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 0.4, fontWeight: "800", textTransform: "uppercase" },
  moreLine: { color: theme.color.textMuted, fontSize: 11, fontWeight: "700", marginTop: 3 },

  section: {
    color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 2,
    marginTop: 20, marginBottom: 6,
  },
  upcomingBlock: {},
  upRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    padding: 12, marginBottom: 8, borderRadius: 10,
    backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border,
  },
  upTitle: { color: theme.color.text, fontSize: 13, fontWeight: "800" },
  upMeta: { color: theme.color.textMuted, fontSize: 11, marginTop: 3 },
  upBadge: { paddingHorizontal: 8, paddingVertical: 5, borderRadius: 6, borderWidth: 1, borderColor: theme.color.brand },
  upBadgeT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1 },

  draftsBlock: {},
  draftRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    padding: 12, marginBottom: 8, borderRadius: 10,
    backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border,
  },
  draftTitle: { color: theme.color.text, fontSize: 13, fontWeight: "700" },
  draftMeta: { color: theme.color.textMuted, fontSize: 11, marginTop: 3 },

  miniBtn: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6, borderWidth: 1, borderColor: theme.color.brand },
  miniBtnT: { color: theme.color.brand, fontSize: 11, fontWeight: "800", letterSpacing: 0.5 },
  miniBtnDanger: { borderColor: theme.color.red },

  tabs: { flexDirection: "row", gap: 6, marginBottom: 10 },
  tab: { flex: 1, paddingHorizontal: 8, paddingVertical: 8, borderRadius: 8, borderWidth: 1, borderColor: theme.color.border, alignItems: "center" },
  tabActive: { borderColor: theme.color.brand, backgroundColor: theme.color.brandTint },
  tabT: { color: theme.color.textMuted, fontSize: 11, fontWeight: "900", letterSpacing: 1 },
  tabTActive: { color: theme.color.brand },

  rightScroll: { maxHeight: 800 },
  // Iter 129e — Right-panel Feed stack: scroll takes available space, the
  // instant composer sticks to the bottom so the coach can quick-post at
  // any time.
  rightFeedStack: { flex: 1, minHeight: 500 },
  empty: { padding: 24, alignItems: "center" },
  emptyT: { color: theme.color.text, fontWeight: "800", marginTop: 10 },
  emptySub: { color: theme.color.textMuted, fontSize: 12, marginTop: 4, textAlign: "center", lineHeight: 17 },
  emptyBtn: {
    marginTop: 12, paddingHorizontal: 14, paddingVertical: 8,
    backgroundColor: theme.color.brand, borderRadius: 8,
  },
  emptyBtnT: { color: "#fff", fontWeight: "900", fontSize: 11, letterSpacing: 1.2 },

  viewInboxRow: {
    flexDirection: "row", justifyContent: "flex-end", alignItems: "center", gap: 6,
    paddingVertical: 4, paddingHorizontal: 2, marginBottom: 4,
  },
  viewInboxT: { color: theme.color.brand, fontWeight: "800", fontSize: 11, letterSpacing: 0.5 },
  convRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    padding: 12, marginBottom: 6, borderRadius: 10,
    backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border,
  },
  convAvatar: { width: 32, height: 32, borderRadius: 16, backgroundColor: theme.color.surface3, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: theme.color.border },
  convAvatarT: { color: theme.color.text, fontWeight: "900", fontSize: 11, letterSpacing: 0.5 },
  convName: { color: theme.color.text, fontWeight: "800", fontSize: 13 },
  convMeta: { color: theme.color.textMuted, fontSize: 11, marginTop: 2 },
});
