/**
 * Personal Activity Planner — shared types + API helpers + preset catalog.
 * Kept small; no side effects at import time.
 */
import { api } from "@/src/lib/api";

export type Intensity = "light" | "moderate" | "hard" | "very_hard" | "not_sure";
export type Recurrence = "once" | "weekly" | "biweekly" | "monthly";
export type PlanningMode = "protect" | "count_as_training" | "note_only" | "ask_coach";
export type ActivityStatus = "planned" | "completed" | "partial" | "skipped" | "cancelled";

export type ActivityPreset = {
  key: string;
  label: string;
  icon: string;
  default_intensity: Intensity;
  default_duration_min: number;
  load_areas: string[];
  load_score: number;
  note?: string;
  safety_note?: string;
};

export type AtlasSuggestion = {
  headline: string;
  body: string;
  recommended_action: string;
  actions: { id: string; label: string; kind: string; target_date?: string }[];
  conflict_level: "none" | "review" | "medium" | "high";
};

export type PersonalActivity = {
  id: string;
  user_id: string;
  activity_name: string;
  activity_type: string;
  date_local: string;
  start_time?: string | null;
  duration_minutes: number;
  intensity: Intensity;
  recurrence: Recurrence;
  series_id?: string | null;
  planning_mode: PlanningMode;
  notes?: string | null;
  location?: string | null;
  importance?: string | null;
  is_competition?: boolean;
  is_flexible?: boolean;
  affects_training?: boolean;
  coach_review_required?: boolean;
  atlas_suggestion?: AtlasSuggestion | null;
  linked_workout_id?: string | null;
  status: ActivityStatus;
  perceived_effort?: string | null;
  applied_action?: string;
  applied_at?: string;
  created_at: string;
  updated_at: string;
};

export type PresetsResponse = {
  presets: ActivityPreset[];
  intensities: Intensity[];
  recurrence: Recurrence[];
  planning_modes: PlanningMode[];
};

export type CreateBody = {
  activity_type: string;
  activity_name?: string;
  date_local: string;
  start_time?: string | null;
  duration_minutes: number;
  intensity: Intensity;
  recurrence: Recurrence;
  planning_mode: PlanningMode;
  notes?: string;
  location?: string;
  importance?: string;
  is_competition?: boolean;
  is_flexible?: boolean;
};

let _presetCache: PresetsResponse | null = null;

export async function loadPresets(): Promise<PresetsResponse> {
  if (_presetCache) return _presetCache;
  const r = await api<PresetsResponse>("/personal-activities/presets");
  _presetCache = r;
  return r;
}

export async function listActivities(params: { start?: string; end?: string; include_past?: boolean } = {}): Promise<PersonalActivity[]> {
  const qs = new URLSearchParams();
  if (params.start) qs.set("start", params.start);
  if (params.end) qs.set("end", params.end);
  if (params.include_past === false) qs.set("include_past", "false");
  const q = qs.toString();
  const r = await api<{ activities: PersonalActivity[] }>(`/personal-activities${q ? `?${q}` : ""}`);
  return r.activities || [];
}

export async function todayActivities(): Promise<PersonalActivity[]> {
  const r = await api<{ activities: PersonalActivity[] }>("/personal-activities/today");
  return r.activities || [];
}

export async function createActivity(body: CreateBody) {
  return api<{ activities: PersonalActivity[]; count: number; series_id: string | null }>("/personal-activities", {
    method: "POST",
    body,
  });
}

export async function deleteActivity(id: string, scope: "one" | "series" = "one") {
  return api<{ deleted: number; scope: string }>(`/personal-activities/${id}?scope=${scope}`, { method: "DELETE" });
}

export async function completeActivity(id: string, status: ActivityStatus, perceived_effort?: string) {
  return api<{ activity: PersonalActivity }>(`/personal-activities/${id}/complete`, {
    method: "POST",
    body: { status, perceived_effort },
  });
}

export async function applySuggestion(id: string, action: string, opts: { workout_id?: string; target_date?: string } = {}) {
  return api<any>(`/personal-activities/${id}/apply-suggestion`, {
    method: "POST",
    body: { action, ...opts },
  });
}

export async function coachClientActivities(clientId: string): Promise<{ activities: PersonalActivity[]; range_load_score: number; range_conflicts: number }> {
  return api(`/coach/clients/${clientId}/personal-activities`);
}

export async function getRegularSports(): Promise<any[]> {
  const r = await api<{ sports: any[] }>("/personal-activities/profile/sports");
  return r.sports || [];
}

export async function putRegularSports(sports: any[]) {
  return api<{ sports: any[] }>("/personal-activities/profile/sports", { method: "PUT", body: { sports } });
}

export const INTENSITY_LABEL: Record<Intensity, string> = {
  light: "Light",
  moderate: "Moderate",
  hard: "Hard",
  very_hard: "Very hard",
  not_sure: "Not sure",
};

export const PLANNING_LABEL: Record<PlanningMode, string> = {
  protect: "Protect this activity",
  count_as_training: "Count as training",
  note_only: "Note only",
  ask_coach: "Ask Louis to review",
};

export const RECURRENCE_LABEL: Record<Recurrence, string> = {
  once: "One-off",
  weekly: "Every week",
  biweekly: "Every 2 weeks",
  monthly: "Every month",
};
