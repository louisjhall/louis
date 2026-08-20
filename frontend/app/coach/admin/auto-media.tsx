/**
 * /coach/admin/auto-media — Per-kind Auto-Media-Gen toggles.
 *
 * Louis flips which content kinds get auto-generated when a new
 * exercise lands in the library. Coach still has to approve.
 *
 * Backed by:
 *   GET  /api/coach/auto-media-gen/settings
 *   PATCH /api/coach/auto-media-gen/settings
 *
 * Env kill-switches (AUTO_MEDIA_GEN_<KIND>=false) always win over the
 * DB toggle — the screen shows them as locked with a badge.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, Switch,
  ActivityIndicator, RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";
import { toast } from "@/src/lib/ux";

type SettingsPayload = {
  toggles: Record<string, boolean>;
  labels: Record<string, string>;
  env_kill_switches?: Record<string, boolean>;
};

type StatusPayload = {
  enabled?: boolean;
  budget_paused?: boolean;
  budget_paused_at?: string | null;
  budget_paused_reason?: string | null;
  budget_paused_by_kind?: string | null;
  budget_paused_by_exercise_id?: string | null;
  budget_resumed_at?: string | null;
};

// Cost hint per kind so Louis can see credit impact at a glance.
const COST_HINT: Record<string, string> = {
  image_primary:   "1 Nano-Banana image gen (single frame)",
  image_start:     "1 Nano-Banana image gen (extra frame)",
  image_end:       "1 Nano-Banana image gen (extra frame)",
  coaching_points: "1 Claude call (~500 tokens)",
  common_mistakes: "1 Claude call (~500 tokens)",
  alternatives:    "1 Claude call + auto-creates library drafts",
  instructions:    "1 Claude call (~500 tokens)",
};

// Split the toggles into two groups so images sit under their own section.
const IMAGE_KINDS = ["image_primary", "image_start", "image_end"];
const CONTENT_KINDS = ["coaching_points", "common_mistakes", "alternatives", "instructions"];

export default function AutoMediaSettingsScreen() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [saving, setSaving] = useState<string | null>(null);
  const [data, setData] = useState<SettingsPayload | null>(null);
  const [genStatus, setGenStatus] = useState<StatusPayload | null>(null);
  const [resuming, setResuming] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, st] = await Promise.all([
        api<SettingsPayload>("/coach/auto-media-gen/settings"),
        api<StatusPayload>("/coach/auto-media-gen/status").catch(() => null),
      ]);
      setData(s);
      setGenStatus(st);
    } catch (e: any) {
      toast(e?.message || "Couldn't load auto-media settings.", "error");
    } finally { setLoading(false); setRefreshing(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const resumeBudget = useCallback(async () => {
    setResuming(true);
    try {
      await api<any>("/coach/auto-media-gen/budget/resume", { method: "POST" });
      toast("Generation resumed — new tasks will fire on next exercise.", "success");
      await load();
    } catch (e: any) {
      toast(e?.message || "Couldn't resume generation.", "error");
    } finally { setResuming(false); }
  }, [load]);

  // Bundle helper — flip start + end frames together as "Multi-frame Images".
  const flipMultiFrame = useCallback(async (next: boolean) => {
    if (!data) return;
    setSaving("__multi_frame__");
    const patch: Record<string, boolean> = {};
    if (!(data.env_kill_switches || {})["image_start"]) patch.image_start = next;
    if (!(data.env_kill_switches || {})["image_end"])   patch.image_end   = next;
    try {
      const r = await api<any>("/coach/auto-media-gen/settings", {
        method: "PATCH", body: { toggles: patch },
      });
      if (r?.toggles) setData((d) => d ? { ...d, toggles: r.toggles } : d);
      toast(`Multi-frame Images → ${next ? "ON" : "OFF"}`, "success");
    } catch (e: any) {
      toast(e?.message || "Couldn't save.", "error");
    } finally { setSaving(null); }
  }, [data]);

  const flip = async (kind: string, next: boolean) => {
    if (!data) return;
    setSaving(kind);
    // Optimistic
    const prev = data.toggles[kind];
    setData({ ...data, toggles: { ...data.toggles, [kind]: next } });
    try {
      const r = await api<any>("/coach/auto-media-gen/settings", {
        method: "PATCH",
        body: { toggles: { [kind]: next } },
      });
      if (r?.ok && r?.toggles) {
        setData((d) => d ? { ...d, toggles: r.toggles } : d);
      }
      toast(`${data.labels[kind] || kind} → ${next ? "ON" : "OFF"}`, "success");
    } catch (e: any) {
      // Revert
      setData((d) => d ? { ...d, toggles: { ...d.toggles, [kind]: prev } } : d);
      toast(e?.message || "Couldn't save.", "error");
    } finally { setSaving(null); }
  };

  const bulk = async (value: boolean) => {
    if (!data) return;
    setSaving("__bulk__");
    const patch: Record<string, boolean> = {};
    for (const k of Object.keys(data.labels)) {
      if (!(data.env_kill_switches || {})[k]) patch[k] = value;
    }
    try {
      const r = await api<any>("/coach/auto-media-gen/settings", {
        method: "PATCH", body: { toggles: patch },
      });
      if (r?.toggles) setData((d) => d ? { ...d, toggles: r.toggles } : d);
      toast(value ? "All kinds ON" : "All kinds OFF", "success");
    } catch (e: any) {
      toast(e?.message || "Couldn't save.", "error");
    } finally { setSaving(null); }
  };

  // Iter181 · Sweep every exercise currently in "Needs Review" through
  // the same auto-generation pipeline that fires on new exercises.
  // Hard-capped server-side at 100 per call — coach can re-tap to keep
  // running batches until the report shows zero pending.
  const [backfilling, setBackfilling] = useState(false);
  const runNeedsReviewBackfill = async () => {
    if (backfilling) return;
    setBackfilling(true);
    try {
      // Dry-run first so the coach sees the count before spending credits.
      const dry = await api<any>("/coach/auto-media-gen/backfill-needs-review", {
        method: "POST", body: { dry_run: true },
      });
      const would = Number(dry?.would_queue_count || 0);
      if (!would) {
        toast("No exercises in Needs Review — nothing to backfill.", "info");
        return;
      }

      // Iter181d · Fire-and-forget kickoff — server returns 202 with a
      // job_id and we POLL /backfill-status/{job_id} every 2s until the
      // background worker reports complete/failed. Browser can never
      // time out because we never hold an HTTP request open during LLM
      // work. Kill-switches (MANUAL_MODE / EXERCISE_BACKFILL_DISABLED)
      // return 403 which surfaces via the api() error path.
      let kickoff: any;
      try {
        kickoff = await api<any>("/coach/auto-media-gen/backfill-needs-review", {
          method: "POST", body: { skip_images: true },
        });
      } catch (e: any) {
        // 409 already_running → attach to in-flight job_id (server sends
        // it in the response body). 403 kill-switch → surface message.
        const detail = e?.response?.detail || e?.detail || e?.message;
        const inflightJobId = e?.response?.job_id;
        if (inflightJobId) {
          kickoff = { job_id: inflightJobId, status: "already_running" };
          toast("Attaching to sweep already in progress…", "info");
        } else {
          toast(detail || "Backfill kickoff failed.", "error");
          return;
        }
      }

      const jobId: string = kickoff?.job_id;
      if (!jobId) {
        toast("Backfill: server did not return a job id.", "error");
        return;
      }

      // Poll loop — 2s interval, cap at 15 min (450 polls).
      let last = 0;
      for (let i = 0; i < 450; i += 1) {
        await new Promise((r) => setTimeout(r, 2000));
        let status: any;
        try {
          status = await api<any>(`/coach/auto-media-gen/backfill-status/${jobId}`);
        } catch {
          continue;                     // transient network — keep polling
        }
        const wrote = Number(status?.wrote || 0);
        const processed = Number(status?.processed || 0);
        const total = Number(status?.total_in_scope || would);
        if (wrote !== last) {
          toast(`… backfilling · ${wrote}/${total} written`, "info");
          last = wrote;
        }
        if (status?.status === "complete") {
          const errCount = Object.values(status?.errors || {}).reduce(
            (a: number, b: any) => a + Number(b || 0), 0,
          );
          if (status.budget_paused) {
            toast(`Budget paused mid-run — wrote ${wrote}/${processed}. Top up + resume + re-tap.`, "error");
          } else if (errCount) {
            toast(`Wrote content on ${wrote}/${processed} exercises (${errCount} errors — see logs).`, "info");
          } else {
            toast(`Wrote content on ${wrote}/${processed} exercises.`, "success");
          }
          return;
        }
        if (status?.status === "failed") {
          toast(`Backfill failed: ${status?.error || "unknown"}.`, "error");
          return;
        }
      }
      toast("Backfill still running after 15 min — check job status manually.", "info");
    } catch (e: any) {
      toast(e?.message || "Backfill failed.", "error");
    } finally { setBackfilling(false); }
  };

  const imageKinds = useMemo(() => {
    if (!data) return [] as string[];
    return IMAGE_KINDS.filter((k) => k in data.labels);
  }, [data]);
  const contentKinds = useMemo(() => {
    if (!data) return [] as string[];
    const known = Object.keys(data.labels);
    const inGroup = new Set([...IMAGE_KINDS, ...CONTENT_KINDS]);
    return [
      ...CONTENT_KINDS.filter((k) => known.includes(k)),
      ...known.filter((k) => !inGroup.has(k)),
    ];
  }, [data]);

  const totalOn = useMemo(() => {
    if (!data) return 0;
    return Object.values(data.toggles).filter(Boolean).length;
  }, [data]);

  const renderRow = (k: string) => {
    if (!data) return null;
    const label = data.labels[k] || k;
    const isOn = !!data.toggles[k];
    const envLocked = !!(data.env_kill_switches || {})[k];
    return (
      <View key={k} style={styles.row} testID={`toggle-${k}`}>
        <View style={{ flex: 1, marginRight: 12 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <Text style={styles.rowTitle}>{label}</Text>
            {envLocked && (
              <View style={styles.envBadge}>
                <Text style={styles.envBadgeT}>ENV LOCK</Text>
              </View>
            )}
          </View>
          {COST_HINT[k] ? <Text style={styles.rowDesc}>{COST_HINT[k]}</Text> : null}
        </View>
        {saving === k ? (
          <ActivityIndicator color={theme.color.brand} />
        ) : (
          <Switch
            value={isOn}
            onValueChange={(next) => flip(k, next)}
            disabled={envLocked}
            trackColor={{ true: theme.color.brand, false: "#3a3a3a" }}
            thumbColor="#fff"
          />
        )}
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={10}>
          <Ionicons name="chevron-back" size={24} color={theme.color.text} />
        </Pressable>
        <Text style={styles.headerTitle}>GENERATION CONTROL</Text>
        <View style={{ width: 24 }} />
      </View>

      {loading ? (
        <ActivityIndicator color={theme.color.brand} style={{ marginTop: 40 }} />
      ) : !data ? (
        <View style={styles.card}><Text style={styles.emptyT}>Could not load settings.</Text></View>
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: 16, paddingBottom: 60 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={theme.color.brand} />}
        >
          {/* Budget-paused banner — visible only when the LLM key ran out */}
          {genStatus?.budget_paused && (
            <View style={styles.budgetBanner} testID="budget-paused-banner">
              <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <Ionicons name="pause-circle" size={20} color="#ff6b6b" />
                <Text style={styles.budgetTitle}>GENERATION PAUSED · BUDGET EXCEEDED</Text>
              </View>
              <Text style={styles.budgetBody}>
                {genStatus.budget_paused_reason
                  ? String(genStatus.budget_paused_reason).slice(0, 220)
                  : "The Universal LLM Key is out of credits."}
              </Text>
              <Text style={styles.budgetHint}>
                {genStatus.budget_paused_by_kind ? `Tripped on ${genStatus.budget_paused_by_kind}` : ""}
                {"  ·  "}
                Top up via Profile → Manage plan → Universal Key → Add Balance, then hit Resume below.
              </Text>
              <View style={{ flexDirection: "row", gap: 8, marginTop: 10 }}>
                <Pressable
                  style={styles.resumeBtn}
                  onPress={resumeBudget}
                  disabled={resuming}
                  testID="resume-generation-btn"
                >
                  {resuming ? (
                    <ActivityIndicator color="#fff" />
                  ) : (
                    <Ionicons name="play" size={14} color="#fff" />
                  )}
                  <Text style={styles.resumeBtnT}>{resuming ? "RESUMING…" : "RESUME GENERATION"}</Text>
                </Pressable>
              </View>
            </View>
          )}

          <View style={styles.card}>
            <Text style={styles.sectionT}>SUMMARY</Text>
            <Text style={styles.sectionHint}>
              When any new exercise is added anywhere in the app, the enabled
              kinds below are queued in the background. Coach still has to
              approve — nothing is published automatically.
            </Text>
            <View style={styles.statRow}>
              <View style={styles.stat}>
                <Text style={styles.statN}>{totalOn}</Text>
                <Text style={styles.statL}>ON</Text>
              </View>
              <View style={styles.stat}>
                <Text style={styles.statN}>{Object.keys(data.labels).length - totalOn}</Text>
                <Text style={styles.statL}>OFF</Text>
              </View>
              <View style={styles.stat}>
                <Text style={styles.statN}>{Object.keys(data.env_kill_switches || {}).length}</Text>
                <Text style={styles.statL}>ENV LOCK</Text>
              </View>
              <View style={styles.stat}>
                <Text style={[styles.statN, { color: genStatus?.enabled === false ? "#ff6b6b" : "#4ade80" }]}>
                  {genStatus?.enabled === false ? "OFF" : "ON"}
                </Text>
                <Text style={styles.statL}>FEATURE</Text>
              </View>
            </View>
            <View style={{ flexDirection: "row", gap: 8, marginTop: 12 }}>
              <Pressable style={styles.bulkBtn} onPress={() => bulk(true)} disabled={saving === "__bulk__"}>
                <Text style={styles.bulkBtnT}>ALL ON</Text>
              </Pressable>
              <Pressable style={[styles.bulkBtn, styles.bulkBtnDark]} onPress={() => bulk(false)} disabled={saving === "__bulk__"}>
                <Text style={styles.bulkBtnT}>ALL OFF</Text>
              </Pressable>
              {saving === "__bulk__" && <ActivityIndicator color={theme.color.brand} />}
            </View>
            {/* Iter181 · Sweep every "Needs Review" exercise through the
                same auto-generation pipeline. Server hard-caps at 100
                per call; coach can tap again to keep clearing. */}
            <Pressable
              style={[styles.backfillBtn, backfilling && { opacity: 0.5 }]}
              onPress={runNeedsReviewBackfill}
              disabled={backfilling}
              testID="run-needs-review-backfill"
            >
              {backfilling ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <>
                  <Ionicons name="refresh-circle" size={16} color="#fff" />
                  <Text style={styles.backfillBtnT}>RUN FOR ALL NEEDS REVIEW</Text>
                </>
              )}
            </Pressable>
            <Text style={styles.backfillHint}>
              Sweeps every Needs Review / Missing exercise through the
              enabled text kinds (coaching points, common mistakes,
              alternatives, client instructions). LLM calls run inline
              in batches of 40 — the button waits until the full library
              is done. Images are skipped by default; regenerate images
              per-exercise from the Library detail view.
            </Text>
          </View>

          <View style={styles.card}>
            <Text style={styles.sectionT}>IMAGE FRAMES</Text>
            <Text style={styles.sectionHint}>
              Which Nano-Banana frames get generated automatically. Coach
              can still manually generate any frame per-exercise from the
              library.
            </Text>
            {imageKinds.map((k) => renderRow(k))}
            {/* Bundle toggle — flips start + end together as "Multi-frame" */}
            {(imageKinds.includes("image_start") || imageKinds.includes("image_end")) && (() => {
              const multiOn = !!(data && data.toggles.image_start && data.toggles.image_end);
              const envLocked = !!(data && ((data.env_kill_switches || {}).image_start || (data.env_kill_switches || {}).image_end));
              return (
                <View style={styles.row} testID="toggle-multi_frame">
                  <View style={{ flex: 1, marginRight: 12 }}>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                      <Text style={styles.rowTitle}>Multi-frame Images (start + end)</Text>
                      {envLocked && (
                        <View style={styles.envBadge}>
                          <Text style={styles.envBadgeT}>ENV LOCK</Text>
                        </View>
                      )}
                    </View>
                    <Text style={styles.rowDesc}>
                      One-click bundle — flips both extra frames together. +2 Nano-Banana image gens per exercise.
                    </Text>
                  </View>
                  {saving === "__multi_frame__" ? (
                    <ActivityIndicator color={theme.color.brand} />
                  ) : (
                    <Switch
                      value={multiOn}
                      onValueChange={(next) => flipMultiFrame(next)}
                      disabled={envLocked}
                      trackColor={{ true: theme.color.brand, false: "#3a3a3a" }}
                      thumbColor="#fff"
                    />
                  )}
                </View>
              );
            })()}
          </View>

          <View style={styles.card}>
            <Text style={styles.sectionT}>WRITTEN CONTENT</Text>
            <Text style={styles.sectionHint}>
              Text fields drafted by Claude in Louis’s voice. Every field
              lands as a draft — coach approves before it reaches clients.
            </Text>
            {contentKinds.map((k) => renderRow(k))}
          </View>

          {Object.keys(data.env_kill_switches || {}).length > 0 && (
            <View style={styles.card}>
              <Text style={styles.sectionT}>ENV-LOCKED KINDS</Text>
              <Text style={styles.sectionHint}>
                These kinds are forced OFF by an environment variable
                (AUTO_MEDIA_GEN_&lt;KIND&gt;=false) and cannot be flipped
                from this panel. Update the env in your Emergent
                deployment settings to unlock.
              </Text>
              {Object.keys(data.env_kill_switches || {}).map((k) => (
                <Text key={k} style={styles.envLockedItem}>· {data.labels[k] || k}</Text>
              ))}
            </View>
          )}

          <Text style={styles.footNote}>
            All auto-generation goes to “Needs Review” — you still approve
            everything before it lands in a client workout.
          </Text>

          {/* Iter184 · Bulk PRIMARY IMAGE finder — consolidated onto this
              admin page (was previously only reachable from Library on
              desktop, which coaches missed). Same server endpoint as the
              Library CTA; kept identical UX pattern to YouTube below. */}
          <BulkPrimaryImageSection toast={toast} />

          {/* Iter183 · YouTube Video finder — separate section so it can't
              be accidentally toggled with the LLM-media kinds above.
              Enable → toggle; Bulk run → sequential worker, ~1s per call. */}
          <YoutubeFinderSection toast={toast} />
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

// ---------------------------------------------------------------------------
// Iter184 · Bulk PRIMARY IMAGE Section — mirror of the button on
// /(coach)/library so coaches on desktop can find it here too. Same
// server endpoint (/api/coach/auto-media-gen/bulk-primary-images);
// kicks off (202) then polls /backfill-status/{jobId}. Sequential
// server-side to stay under Gemini rate limits.
// ---------------------------------------------------------------------------
function BulkPrimaryImageSection({ toast }: { toast: (m: string, k?: any) => void }) {
  const [busy, setBusy] = React.useState(false);
  const [dryOnly, setDryOnly] = React.useState(false);
  const [breakdown, setBreakdown] = React.useState<null | {
    would: number;
    raw: number;
    archived: number;
    deleted: number;
    aliases: number;
  }>(null);

  // Iter185 · Preview-only: fetch dry-run breakdown so coach can see
  // why the count is what it is before spending Gemini credits.
  const previewCounts = async () => {
    if (busy || dryOnly) return;
    setDryOnly(true);
    try {
      const dry = await api<any>("/coach/auto-media-gen/bulk-primary-images", {
        method: "POST", body: { dry_run: true },
      });
      const b = dry?.breakdown || {};
      setBreakdown({
        would: Number(dry?.would_queue_count || 0),
        raw: Number(b.raw_missing_primary_image || 0),
        archived: Number(b.excluded_archived_or_retired || 0),
        deleted: Number(b.excluded_soft_deleted || 0),
        aliases: Number(b.excluded_alias_duplicates || 0),
      });
    } catch (e: any) {
      toast(e?.message || "Preview failed", "error");
    } finally { setDryOnly(false); }
  };

  const run = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const dry = await api<any>("/coach/auto-media-gen/bulk-primary-images", {
        method: "POST", body: { dry_run: true },
      });
      const would = Number(dry?.would_queue_count || 0);
      const b = dry?.breakdown || {};
      setBreakdown({
        would,
        raw: Number(b.raw_missing_primary_image || 0),
        archived: Number(b.excluded_archived_or_retired || 0),
        deleted: Number(b.excluded_soft_deleted || 0),
        aliases: Number(b.excluded_alias_duplicates || 0),
      });
      if (!would) {
        toast("No DRAFT_REQUESTED / MISSING exercises need a primary image.", "info");
        return;
      }
      let kickoff: any;
      try {
        kickoff = await api<any>("/coach/auto-media-gen/bulk-primary-images", { method: "POST", body: {} });
      } catch (e: any) {
        const jid = e?.response?.job_id;
        if (jid) { kickoff = { job_id: jid }; toast("Attaching to sweep already in flight…", "info"); }
        else { toast(e?.response?.detail || e?.message || "Kickoff failed", "error"); return; }
      }
      const jobId: string = kickoff?.job_id;
      if (!jobId) { toast("Server did not return a job id.", "error"); return; }

      let lastWrote = 0;
      for (let i = 0; i < 900; i += 1) {
        await new Promise((r) => setTimeout(r, 2000));
        let s: any;
        try { s = await api<any>(`/coach/auto-media-gen/backfill-status/${jobId}`); } catch { continue; }
        const wrote = Number(s?.wrote || 0);
        const total = Number(s?.total_in_scope || would);
        if (wrote !== lastWrote) {
          toast(`… generating · ${wrote}/${total} images done`, "info");
          lastWrote = wrote;
        }
        if (s?.status === "complete" || s?.status === "failed") {
          const errs = Object.values(s?.errors || {}).reduce((a: number, b: any) => a + Number(b || 0), 0);
          if (s.budget_paused) {
            toast(`Budget paused — ${wrote}/${s.processed} done. Top up + resume + re-tap.`, "error");
          } else if (s.status === "failed") {
            toast(`Bulk run failed: ${s?.error || "unknown"}`, "error");
          } else {
            toast(`Generated ${wrote}/${s.processed} primary images${errs ? ` (${errs} errors)` : ""}.`, "success");
          }
          return;
        }
      }
      toast("Bulk run still going after 30 min — check status manually.", "info");
    } catch (e: any) {
      toast(e?.message || "Bulk run failed", "error");
    } finally { setBusy(false); }
  };

  return (
    <View style={styles.ytBlock} testID="bulk-primary-image-section">
      <Text style={styles.ytH}>PRIMARY IMAGES</Text>
      <Text style={styles.ytHint}>
        Sweeps every DRAFT / MISSING exercise through Nano-Banana to
        generate the primary frame. Sequential server-side (one image
        per exercise, ~10-15 s each). All results land in Needs Review.
      </Text>
      <Text style={styles.ytHint}>
        Excludes archived / retired / deprecated / soft-deleted rows and
        alias duplicates. Tap PREVIEW COUNTS to see the breakdown
        before spending credits.
      </Text>

      {breakdown && (
        <View style={styles.bdBox} testID="bulk-primary-image-breakdown">
          <Text style={styles.bdT}>QUERY BREAKDOWN</Text>
          <BdRow label="Raw missing primary image" value={breakdown.raw} />
          <BdRow label="− Archived / retired / deprecated" value={breakdown.archived} tone="dim" />
          <BdRow label="− Soft-deleted" value={breakdown.deleted} tone="dim" />
          <BdRow label="− Alias duplicates" value={breakdown.aliases} tone="dim" />
          <BdRow label="= Eligible to generate" value={breakdown.would} tone="brand" />
        </View>
      )}

      <View style={{ flexDirection: "row", gap: 8 }}>
        <Pressable onPress={previewCounts} disabled={busy || dryOnly}
          style={[styles.ytPreview, (busy || dryOnly) && { opacity: 0.5 }]}
          testID="bulk-primary-image-preview">
          {dryOnly
            ? <ActivityIndicator color={theme.color.brand} size="small" />
            : <Ionicons name="eye-outline" size={16} color={theme.color.brand} />}
          <Text style={styles.ytPreviewT}>PREVIEW COUNTS</Text>
        </Pressable>
        <Pressable onPress={run} disabled={busy}
          style={[styles.ytBulk, { flex: 1 }, busy && { opacity: 0.5 }]}
          testID="bulk-primary-image-run">
          {busy
            ? <ActivityIndicator color="#fff" size="small" />
            : <Ionicons name="images" size={16} color="#fff" />}
          <Text style={styles.ytBulkT}>
            {busy ? "GENERATING…" : "GENERATE MISSING PRIMARY IMAGES"}
          </Text>
        </Pressable>
      </View>
    </View>
  );
}

function BdRow({ label, value, tone }: { label: string; value: number; tone?: "dim" | "brand" }) {
  const color = tone === "brand" ? theme.color.brand : tone === "dim" ? theme.color.textDim : theme.color.text;
  return (
    <View style={styles.bdRow}>
      <Text style={[styles.bdL, { color }]}>{label}</Text>
      <Text style={[styles.bdV, { color }]}>{value}</Text>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Iter183 · YouTube Video Finder section (enable toggle + bulk sweep).
// ---------------------------------------------------------------------------
function YoutubeFinderSection({ toast }: { toast: (m: string, k?: any) => void }) {
  const [ytEnabled, setYtEnabled] = React.useState(false);
  const [ytKeyOk, setYtKeyOk] = React.useState(true);
  const [ytBusy, setYtBusy] = React.useState<"toggle" | "bulk" | null>(null);

  React.useEffect(() => {
    (async () => {
      try {
        const r = await api<any>("/coach/youtube-finder/settings");
        setYtEnabled(!!r?.enabled);
        setYtKeyOk(!!r?.api_key_configured);
      } catch { /* non-fatal */ }
    })();
  }, []);

  const toggle = async () => {
    if (ytBusy) return;
    setYtBusy("toggle");
    try {
      const next = !ytEnabled;
      await api<any>("/coach/youtube-finder/settings", {
        method: "PUT", body: { enabled: next },
      });
      setYtEnabled(next);
      toast(next ? "YouTube finder ON" : "YouTube finder OFF", "success");
    } catch (e: any) {
      toast(e?.message || "Toggle failed", "error");
    } finally { setYtBusy(null); }
  };

  const bulkRun = async (loose: boolean = false) => {
    if (ytBusy) return;
    setYtBusy("bulk");
    try {
      const dry = await api<any>("/coach/youtube-finder/bulk-run", {
        method: "POST", body: { dry_run: true },
      });
      const would = Number(dry?.would_queue_count || 0);
      if (!would) {
        toast("No exercises missing a primary video — nothing to search.", "info");
        return;
      }

      let kickoff: any;
      try {
        kickoff = await api<any>("/coach/youtube-finder/bulk-run", { method: "POST", body: { loose } });
      } catch (e: any) {
        const jid = e?.response?.job_id;
        if (jid) { kickoff = { job_id: jid }; toast("Attaching to sweep already in flight…", "info"); }
        else { toast(e?.response?.reason || e?.message || "Kickoff failed", "error"); return; }
      }
      const jobId: string = kickoff?.job_id;
      if (!jobId) { toast("No job id returned", "error"); return; }

      if (kickoff?.status === "resumed") {
        const pStart = Number(kickoff?.processed || 0);
        const tot = Number(kickoff?.total_in_scope || would);
        toast(`Resuming from ${pStart}/${tot}${loose ? " (loose)" : ""}…`, "info");
      } else if (kickoff?.status === "queued") {
        toast(`Starting ${loose ? "LOOSE " : ""}sweep — ${would} exercises`, "info");
      }

      // Iter188 · Poll for up to 60 min. Each batch of 10 takes ~10s
      // (1s spacing), so 527 items ≈ ~9 min. Give buffer for retries.
      let lastProcessed = -1;
      for (let i = 0; i < 1800; i += 1) {
        await new Promise((r) => setTimeout(r, 2000));
        let s: any;
        try { s = await api<any>(`/coach/auto-media-gen/backfill-status/${jobId}`); } catch { continue; }
        const wrote = Number(s?.wrote || 0);
        const processedN = Number(s?.processed || 0);
        const total = Number(s?.total_in_scope || would);
        // Progress toast whenever `processed` (not just `wrote`) changes,
        // so the coach sees "45 / 527" ticking even when videos aren't
        // being found for a run of exercises.
        if (processedN !== lastProcessed) {
          toast(`${processedN} / ${total} scanned · ${wrote} found`, "info");
          lastProcessed = processedN;
        }
        if (s?.status === "complete" || s?.status === "paused_quota" || s?.status === "failed") {
          const errs = Object.values(s?.errors || {}).reduce((a: number, b: any) => a + Number(b || 0), 0);
          if (s.status === "paused_quota") {
            toast(`YouTube quota exhausted — ${wrote}/${processedN} found. Tap 'Find Videos' again tomorrow to resume from where we stopped.`, "error");
          } else if (s.status === "failed") {
            toast(`Bulk run failed at ${processedN}/${total}: ${s?.error || "unknown"}. Tap 'Find Videos' to resume from ${processedN}.`, "error");
          } else {
            toast(`Complete · Found ${wrote}/${processedN} videos${errs ? ` (${errs} errors)` : ""}. All flagged Needs Review.`, "success");
          }
          return;
        }
      }
      toast("Bulk run still going after 60 min — check status manually.", "info");
    } catch (e: any) { toast(e?.message || "Bulk run failed", "error"); }
    finally { setYtBusy(null); }
  };

  return (
    <View style={styles.ytBlock}>
      <Text style={styles.ytH}>YOUTUBE VIDEO</Text>
      <Text style={styles.ytHint}>
        Auto-finds a ≤ 60 s YouTube demo video for each exercise missing one.
        Filters by known-good channels, view count, and like ratio. Excludes
        podcast/talk/interview channels. All results go to Needs Review.
      </Text>
      {!ytKeyOk ? (
        <Text style={styles.ytWarn}>⚠ YOUTUBE_API_KEY not configured on the backend.</Text>
      ) : null}
      <Pressable onPress={toggle} disabled={!!ytBusy || !ytKeyOk}
        style={[styles.ytToggle, ytEnabled && styles.ytToggleOn,
                (!!ytBusy || !ytKeyOk) && { opacity: 0.5 }]}
        testID="yt-finder-toggle">
        <Ionicons name={ytEnabled ? "checkmark-circle" : "ellipse-outline"} size={16}
          color={ytEnabled ? "#fff" : theme.color.text} />
        <Text style={[styles.ytToggleT, ytEnabled && { color: "#fff" }]}>
          {ytEnabled ? "ENABLED" : "DISABLED"}
        </Text>
      </Pressable>
      <Pressable onPress={() => bulkRun(false)} disabled={!!ytBusy || !ytEnabled}
        style={[styles.ytBulk, (!!ytBusy || !ytEnabled) && { opacity: 0.5 }]}
        testID="yt-finder-bulk-run">
        {ytBusy === "bulk"
          ? <ActivityIndicator color="#fff" size="small" />
          : <Ionicons name="logo-youtube" size={16} color="#fff" />}
        <Text style={styles.ytBulkT}>FIND VIDEOS FOR ALL MISSING</Text>
      </Pressable>

      {/* Iter188 · Diagnostic buttons — one-shot health check and a
          loose-filter sweep for when the strict filters find nothing. */}
      <View style={{ flexDirection: "row", gap: 8 }}>
        <Pressable
          onPress={async () => {
            setYtBusy("health");
            try {
              const r = await api<any>("/coach/youtube-finder/health?q=bench+press");
              if (r?.ok) {
                toast(`✅ API works — "${r.sample?.title?.slice(0, 40) || "found"}"`, "success");
              } else {
                toast(`❌ ${r?.advice || r?.reason || "unknown"}`, "error");
              }
            } catch (e: any) {
              toast(e?.message || "Health check failed", "error");
            } finally { setYtBusy(null); }
          }}
          disabled={!!ytBusy || !ytKeyOk}
          style={[styles.ytDiag, (!!ytBusy || !ytKeyOk) && { opacity: 0.5 }]}
          testID="yt-finder-health-check"
        >
          {ytBusy === "health"
            ? <ActivityIndicator color={theme.color.brand} size="small" />
            : <Ionicons name="pulse" size={14} color={theme.color.brand} />}
          <Text style={styles.ytDiagT}>API HEALTH</Text>
        </Pressable>
        <Pressable
          onPress={() => bulkRun(true)}
          disabled={!!ytBusy || !ytEnabled}
          style={[styles.ytDiag, (!!ytBusy || !ytEnabled) && { opacity: 0.5 }]}
          testID="yt-finder-bulk-run-loose"
        >
          <Ionicons name="filter-outline" size={14} color={theme.color.brand} />
          <Text style={styles.ytDiagT}>LOOSE MODE</Text>
        </Pressable>
      </View>
      <Text style={styles.ytDiagHint}>
        API HEALTH → 1-shot quota / connectivity check. LOOSE MODE → drops
        the &quot;shorts&quot; suffix, allows up to 3 min videos, skips channel and
        like-ratio filters — use when the strict sweep finds 0 videos.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  ytBlock: { marginTop: 24, padding: 16, borderRadius: 10,
             borderWidth: 1, borderColor: theme.color.border,
             backgroundColor: theme.color.card, gap: 10 },
  ytH: { color: theme.color.text, fontSize: 12, fontWeight: "900", letterSpacing: 1.4 },
  ytHint: { color: theme.color.textDim, fontSize: 12, lineHeight: 17 },
  ytWarn: { color: "#e5a337", fontSize: 12, fontWeight: "700" },
  ytToggle: { flexDirection: "row", alignItems: "center", gap: 8,
              alignSelf: "flex-start", paddingHorizontal: 14, paddingVertical: 8,
              borderRadius: 8, borderWidth: 1, borderColor: theme.color.border,
              backgroundColor: theme.color.surface2 },
  ytToggleOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  ytToggleT: { color: theme.color.text, fontSize: 11, fontWeight: "900", letterSpacing: 1.2 },
  ytBulk: { flexDirection: "row", alignItems: "center", justifyContent: "center",
            gap: 8, paddingVertical: 12, borderRadius: 8,
            backgroundColor: theme.color.brand },
  ytBulkT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 1.2 },
  // Iter188 · Diagnostic pair — ghost buttons under the main sweep CTA.
  ytDiag: {
    flex: 1,
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, paddingVertical: 10, borderRadius: 8,
    borderWidth: 1, borderColor: theme.color.brand,
    backgroundColor: "transparent",
  },
  ytDiagT: {
    color: theme.color.brand, fontSize: 10, fontWeight: "900", letterSpacing: 1.2,
  },
  ytDiagHint: {
    color: theme.color.textDim, fontSize: 10, fontStyle: "italic", lineHeight: 14,
  },
  // Iter185 · Bulk-primary-image preview + breakdown UI
  ytPreview: { flexDirection: "row", alignItems: "center", justifyContent: "center",
               gap: 6, paddingVertical: 12, paddingHorizontal: 14, borderRadius: 8,
               borderWidth: 1, borderColor: theme.color.brand,
               backgroundColor: theme.color.surface2 },
  ytPreviewT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.2 },
  bdBox: { padding: 12, borderRadius: 8, borderWidth: 1,
           borderColor: theme.color.border, backgroundColor: theme.color.surface2, gap: 6 },
  bdT: { color: theme.color.brand, fontSize: 11, fontWeight: "900", letterSpacing: 1.5, marginBottom: 2 },
  bdRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  bdL: { fontSize: 12, fontWeight: "700" },
  bdV: { fontSize: 13, fontWeight: "900", fontVariant: ["tabular-nums"] },
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    padding: 16, borderBottomWidth: 1, borderBottomColor: theme.color.divider,
  },
  headerTitle: { color: theme.color.text, fontSize: 14, letterSpacing: 2, fontWeight: "900" },

  card: {
    backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.md,
    borderWidth: 1, borderColor: theme.color.border,
    padding: 14, marginBottom: 12,
  },
  sectionT: { color: theme.color.brand, fontSize: 11, letterSpacing: 2, fontWeight: "900", marginBottom: 6 },
  sectionHint: { color: theme.color.textMuted, fontSize: 11, lineHeight: 16, marginBottom: 10 },

  statRow: { flexDirection: "row", gap: 12, marginTop: 6 },
  stat: { flex: 1, alignItems: "center", padding: 8, backgroundColor: theme.color.surface3, borderRadius: 8 },
  statN: { color: theme.color.text, fontSize: 20, fontWeight: "900" },
  statL: { color: theme.color.textMuted, fontSize: 11, letterSpacing: 1.2, fontWeight: "800", marginTop: 2 },

  row: {
    flexDirection: "row", alignItems: "center",
    paddingVertical: 12, borderTopWidth: 1, borderTopColor: theme.color.border,
  },
  rowTitle: { color: theme.color.text, fontSize: 13, fontWeight: "800", letterSpacing: 0.3 },
  rowDesc: { color: theme.color.textMuted, fontSize: 11, lineHeight: 15, marginTop: 3 },

  envBadge: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 3, backgroundColor: "#f5b54322", borderWidth: 1, borderColor: "#f5b543" },
  envBadgeT: { color: "#f5b543", fontSize: 11, fontWeight: "900", letterSpacing: 0.5 },

  bulkBtn: {
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: 8,
    backgroundColor: theme.color.brand,
  },
  bulkBtnDark: { backgroundColor: "#3a3a3a" },
  bulkBtnT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  // Iter181 · Needs-Review backfill CTA — same visual language as the
  // primary brand pill so coach can spot it quickly, but placed under
  // the ALL ON/OFF bulk row so it isn't mistaken for a global toggle.
  backfillBtn: {
    marginTop: 10, backgroundColor: theme.color.brand,
    paddingVertical: 12, paddingHorizontal: 14, borderRadius: 10,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
  },
  backfillBtnT: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 1.5 },
  backfillHint: {
    color: theme.color.textMuted, fontSize: 11, marginTop: 6, lineHeight: 15,
  },

  envLockedItem: { color: theme.color.textDim, fontSize: 12, paddingVertical: 3 },

  emptyT: { color: theme.color.textMuted, fontSize: 12 },
  footNote: { color: theme.color.textDim, fontSize: 11, textAlign: "center", marginTop: 8, marginBottom: 30, lineHeight: 14 },

  // Budget-paused banner
  budgetBanner: {
    backgroundColor: "#3B0B12",
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "#7A1122",
    padding: 14,
    marginBottom: 12,
  },
  budgetTitle: { color: "#ff6b6b", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  budgetBody: { color: theme.color.text, fontSize: 12, lineHeight: 17 },
  budgetHint: { color: theme.color.textMuted, fontSize: 11, lineHeight: 15, marginTop: 6 },
  resumeBtn: {
    backgroundColor: "#065f46",
    paddingHorizontal: 14, paddingVertical: 8,
    borderRadius: 8,
    flexDirection: "row", alignItems: "center", gap: 6,
  },
  resumeBtnT: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
});
