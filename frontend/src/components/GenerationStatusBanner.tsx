/**
 * GenerationStatusBanner — coach-product state ribbon.
 *
 * Iter 128e — replaces the permanent 8-stage pipeline card with a single
 * product-state pill:
 *
 *   NO PLAN                — no draft, no live
 *   BUILDING               — actively running kickoff (stages.*.state === "in_progress")
 *   DRAFT NEEDS REVIEW     — latest plan_drafts_v2.status="needs_review" AND no fresher live
 *   LIVE                   — plan_live_v2.active=true; no unpublished newer draft
 *   LIVE + NEW DRAFT       — Live exists AND a newer unpublished Draft exists
 *   LIVE + ROSTER CHANGED  — Live exists AND roster_changed attention unresolved
 *
 * Only during BUILDING do we show the technical stage progress dots. In every
 * other state we show a single compact pill so the plan grid dominates the UX.
 */
import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { theme } from "@/src/lib/theme";

type Stage = {
  stage: string;
  state: "pending" | "in_progress" | "done" | "error";
  at?: string;
  detail?: string | number;
};

const BUILD_LABELS: Record<string, string> = {
  planning_programme:  "Planning",
  generating_workouts: "Building sessions",
  validating:          "Validating",
};

export function GenerationStatusBanner({
  clientId, month,
}: {
  clientId: string;
  month?: string;
}) {
  const router = useRouter();
  const [data, setData] = useState<{ overall: string; stages: Stage[] } | null>(null);
  const [product, setProduct] = useState<{
    state: "no_plan" | "building" | "draft_needs_review" | "live" | "live_plus_draft" | "live_plus_roster_changed";
    live?: any;
    draft?: any;
    roster_changed?: boolean;
    exceptions_count?: number;
  } | null>(null);
  const [buildingSlow, setBuildingSlow] = useState(false);

  useEffect(() => {
    let mounted = true;
    let interval: any;
    let buildStart: number | null = null;
    const tick = async () => {
      try {
        const [gen, ws] = await Promise.all([
          api<{ overall: string; stages: Stage[] }>(
            `/v2/coach/clients/${clientId}/generation/status${month ? `?month=${month}` : ""}`
          ).catch(() => null),
          api<any>(`/v2/coach/clients/${clientId}/engine-v2/state`).catch(() => null),
        ]);
        if (!mounted) return;
        setData(gen || null);

        const anyInProgress = (gen?.stages || []).some((s) => s.state === "in_progress");
        const anyError = (gen?.stages || []).some((s) => s.state === "error");
        const live = ws?.has_active_live ? { id: ws.active_live_id, planning_window: ws.roster_range, placements_count: ws.roster_range?.days } : null;
        const draft = ws?.has_active_draft ? { id: ws.active_draft_id, status: ws.active_draft_status } : null;
        // Roster-change / new-draft heuristics until dedicated endpoints exist.
        const rosterChanged = !!(ws?.has_active_live && ws?.has_active_draft && (ws.active_draft_status === "needs_review"));
        const newDraftAfterLive = rosterChanged;
        const exceptionsCount = 0;

        let productState: any;
        if (anyInProgress) {
          productState = "building";
          if (buildStart === null) buildStart = Date.now();
          setBuildingSlow((Date.now() - buildStart) > 45_000);
        } else {
          buildStart = null;
          setBuildingSlow(false);
          if (draft && !live) productState = "draft_needs_review";
          else if (live && draft && newDraftAfterLive) productState = "live_plus_draft";
          else if (live) productState = "live";
          else if (anyError) productState = "no_plan";
          else productState = "no_plan";
        }
        setProduct({ state: productState, live, draft, roster_changed: rosterChanged, exceptions_count: exceptionsCount });
      } catch {
        /* silent */
      }
    };
    tick();
    interval = setInterval(tick, 3500);
    return () => { mounted = false; clearInterval(interval); };
  }, [clientId, month]);

  if (!product) return null;

  // BUILDING — show progress dots
  if (product.state === "building" && data) {
    const buildStages = data.stages.filter((s) => s.stage in BUILD_LABELS);
    return (
      <View style={styles.buildingCard} testID="genstatus-building">
        <View style={styles.buildingHead}>
          <ActivityIndicator size="small" color={theme.color.brand} />
          <Text style={styles.buildingTitle}>BUILDING PLAN</Text>
          {buildingSlow && (
            <Text style={styles.buildingSlow}>Taking longer than expected…</Text>
          )}
        </View>
        <View style={styles.buildStages}>
          {buildStages.map((s, i) => (
            <View key={s.stage} style={styles.buildStage}>
              <View style={[styles.dot, { backgroundColor: s.state === "done" ? "#61c982" : s.state === "in_progress" ? "#f5b543" : "#3a3a45" }]}>
                {s.state === "done" && <Ionicons name="checkmark" size={10} color="#000" />}
              </View>
              <Text style={styles.buildLabel}>{BUILD_LABELS[s.stage]}</Text>
              {i < buildStages.length - 1 && <View style={styles.buildRail} />}
            </View>
          ))}
        </View>
      </View>
    );
  }

  // NO PLAN
  if (product.state === "no_plan") {
    return (
      <View style={styles.pillNoPlan} testID="genstatus-no-plan">
        <Ionicons name="calendar-outline" size={14} color={theme.color.textDim} />
        <Text style={styles.pillTextDim}>NO PLAN</Text>
        <Text style={styles.pillHint}>Upload roster and build a plan to get started.</Text>
      </View>
    );
  }

  // DRAFT NEEDS REVIEW (no live)
  if (product.state === "draft_needs_review") {
    return (
      <Pressable
        onPress={() => router.push(`/coach/engine-v2-draft/${clientId}` as any)}
        style={styles.pillAmber}
        testID="genstatus-draft-review"
      >
        <Ionicons name="alert-circle" size={14} color="#f5b543" />
        <Text style={styles.pillTextAmber}>DRAFT READY FOR REVIEW</Text>
        {product.exceptions_count ? (
          <Text style={styles.pillHint}>{product.exceptions_count} issue{product.exceptions_count > 1 ? "s" : ""}</Text>
        ) : null}
        <Ionicons name="chevron-forward" size={14} color="#f5b543" />
      </Pressable>
    );
  }

  // LIVE + NEW DRAFT
  if (product.state === "live_plus_draft") {
    return (
      <View style={styles.livePlus} testID="genstatus-live-plus-draft">
        <View style={styles.livePill}>
          <Ionicons name="checkmark-circle" size={14} color="#61c982" />
          <Text style={styles.pillTextGreen}>LIVE</Text>
          {product.live?.planning_window?.start && (
            <Text style={styles.pillHintTight}>{fmtMonth(product.live.planning_window.start)}</Text>
          )}
        </View>
        <Pressable
          onPress={() => router.push(`/coach/engine-v2-draft/${clientId}` as any)}
          style={styles.newDraftPill}
          testID="genstatus-review-new-draft"
        >
          <Ionicons name="alert-circle" size={14} color="#f5b543" />
          <Text style={styles.pillTextAmber}>NEW DRAFT · REVIEW</Text>
          <Ionicons name="chevron-forward" size={14} color="#f5b543" />
        </Pressable>
      </View>
    );
  }

  // LIVE + ROSTER CHANGED
  if (product.state === "live_plus_roster_changed") {
    return (
      <View style={styles.livePlus} testID="genstatus-live-roster-changed">
        <View style={styles.livePill}>
          <Ionicons name="checkmark-circle" size={14} color="#61c982" />
          <Text style={styles.pillTextGreen}>LIVE</Text>
        </View>
        <View style={styles.rosterChangedPill}>
          <Ionicons name="refresh" size={14} color="#5aa9e6" />
          <Text style={styles.pillTextBlue}>ROSTER CHANGED · REBUILD DRAFT</Text>
        </View>
      </View>
    );
  }

  // LIVE (steady state)
  return (
    <View style={styles.livePill} testID="genstatus-live">
      <Ionicons name="checkmark-circle" size={14} color="#61c982" />
      <Text style={styles.pillTextGreen}>LIVE</Text>
      {product.live?.placements_count !== undefined && (
        <Text style={styles.pillHintTight}>{product.live.placements_count} placements</Text>
      )}
      {product.live?.planning_window?.start && (
        <Text style={styles.pillHintTight}>· {fmtMonth(product.live.planning_window.start)}</Text>
      )}
    </View>
  );
}

function fmtMonth(iso?: string): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleString("default", { month: "short", year: "numeric" });
  } catch { return ""; }
}

const styles = StyleSheet.create({
  buildingCard: {
    marginHorizontal: 12, marginTop: 8, marginBottom: 4,
    backgroundColor: theme.color.surface2, borderRadius: 8,
    borderWidth: 1, borderColor: theme.color.border, padding: 10,
  },
  buildingHead: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 8 },
  buildingTitle: { color: theme.color.textDim, fontSize: 10, letterSpacing: 1.5, fontWeight: "800", flex: 1 },
  buildingSlow: { color: "#f5b543", fontSize: 10, fontStyle: "italic" },
  buildStages: { flexDirection: "row", alignItems: "center", gap: 4 },
  buildStage: { flexDirection: "row", alignItems: "center", gap: 4 },
  buildLabel: { color: theme.color.textHi, fontSize: 10, fontWeight: "700" },
  buildRail: { width: 12, height: 2, backgroundColor: "#3a3a45", marginHorizontal: 6 },
  dot: { width: 16, height: 16, borderRadius: 8, alignItems: "center", justifyContent: "center" },

  pillNoPlan: {
    marginHorizontal: 12, marginTop: 8, marginBottom: 4,
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
    borderRadius: 6, paddingHorizontal: 10, paddingVertical: 6,
  },
  pillAmber: {
    marginHorizontal: 12, marginTop: 8, marginBottom: 4,
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: "rgba(245,181,67,0.10)", borderWidth: 1, borderColor: "rgba(245,181,67,0.35)",
    borderRadius: 6, paddingHorizontal: 10, paddingVertical: 6,
  },
  livePill: {
    marginHorizontal: 12, marginTop: 8, marginBottom: 4,
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: "rgba(97,201,130,0.10)", borderWidth: 1, borderColor: "rgba(97,201,130,0.35)",
    borderRadius: 6, paddingHorizontal: 10, paddingVertical: 6,
  },
  livePlus: {
    marginHorizontal: 12, marginTop: 8, marginBottom: 4,
    flexDirection: "row", flexWrap: "wrap", gap: 6,
  },
  newDraftPill: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: "rgba(245,181,67,0.10)", borderWidth: 1, borderColor: "rgba(245,181,67,0.35)",
    borderRadius: 6, paddingHorizontal: 10, paddingVertical: 6,
  },
  rosterChangedPill: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: "rgba(90,169,230,0.10)", borderWidth: 1, borderColor: "rgba(90,169,230,0.35)",
    borderRadius: 6, paddingHorizontal: 10, paddingVertical: 6,
  },
  pillTextDim:   { color: theme.color.textDim, fontSize: 10, letterSpacing: 1.4, fontWeight: "800" },
  pillTextGreen: { color: "#61c982", fontSize: 10, letterSpacing: 1.4, fontWeight: "800" },
  pillTextAmber: { color: "#f5b543", fontSize: 10, letterSpacing: 1.4, fontWeight: "800" },
  pillTextBlue:  { color: "#5aa9e6", fontSize: 10, letterSpacing: 1.4, fontWeight: "800" },
  pillHint:      { color: theme.color.textDim, fontSize: 11, marginLeft: 4 },
  pillHintTight: { color: theme.color.textDim, fontSize: 10, marginLeft: 4 },
});
