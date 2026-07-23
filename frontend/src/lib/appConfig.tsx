/**
 * useAppConfig — Iter 94t (Phase 1)
 *
 * Fetches server-driven feature flags + content once per app session and
 * exposes them as a hook. Falls back to safe defaults if the network is
 * unavailable so the client is never blocked.
 */
import React, { createContext, useContext, useEffect, useState, useMemo } from "react";
import { api } from "@/src/lib/api";

type ConfigShape = {
  flags: Record<string, boolean | string | number>;
  content: Record<string, any>;
  loaded: boolean;
};

const SAFE_DEFAULTS: ConfigShape = {
  flags: {
    guided_flow_enabled: true,
    guided_flow_timer_mode_enabled: true,
    guided_flow_image_autoscroll: true,
    exercise_media_required: true,
    missing_media_client_fallback_enabled: true,
    hotel_system_enabled: true,
    progress_charts_enabled: true,
    nutrition_dashboard_enabled: true,
    wearable_steps_enabled: false,
    habits_dynamic_enabled: true,
    first_day_workout_choice_enabled: true,
    whatsapp_support_enabled: true,
    beta_banner_enabled: true,
    missed_workout_recovery_enabled: true,
    timezone_card_enabled: true,
    calendar_scroll_enabled: true,
  },
  content: {},
  loaded: false,
};

const Ctx = createContext<ConfigShape>(SAFE_DEFAULTS);

export function AppConfigProvider({ children }: { children: React.ReactNode }) {
  const [cfg, setCfg] = useState<ConfigShape>(SAFE_DEFAULTS);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await api<any>("/app-config");
        if (cancelled) return;
        setCfg({
          flags: { ...SAFE_DEFAULTS.flags, ...(r?.flags || {}) },
          content: r?.content || {},
          loaded: true,
        });
      } catch {
        if (!cancelled) setCfg({ ...SAFE_DEFAULTS, loaded: true });
      }
    })();
    return () => { cancelled = true; };
  }, []);
  const value = useMemo(() => cfg, [cfg]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAppConfig(): ConfigShape {
  return useContext(Ctx);
}

/** Convenience: returns a single flag boolean with safe default = true. */
export function useFlag(key: string, defaultVal = true): boolean {
  const cfg = useAppConfig();
  const v = cfg.flags?.[key];
  if (typeof v === "boolean") return v;
  return defaultVal;
}
