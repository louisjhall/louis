/**
 * preview.tsx — Coach "Preview as Client" context and helpers.
 *
 * Contract:
 *   - Coach logs in normally. Their token is in AsyncStorage as `cf_token`.
 *   - When they enter preview:
 *       1. We stash the current (coach) token in `cf_token_backup`.
 *       2. We call one of the preview endpoints, get a preview JWT.
 *       3. We setToken(previewJwt) so every subsequent API call is scoped
 *          to the client identity.
 *       4. We store minimal preview metadata (target user info, kind).
 *       5. Frontend banner + guard components watch this metadata.
 *   - On exit:
 *       1. POST /coach/preview/exit (best-effort).
 *       2. Restore cf_token from cf_token_backup.
 *       3. Refresh the auth context so the coach dashboard reloads.
 */
import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { api, setToken } from "./api";

export type PreviewMode = "real_client" | "demo" | "new_client";

export type PreviewTarget = {
  id: string;
  name: string | null;
  email: string | null;
  role: string;
};

export type PreviewState = {
  active: boolean;
  mode: PreviewMode | null;
  target: PreviewTarget | null;
  expiresAt: string | null;
};

const PREVIEW_META_KEY = "cf_preview_meta";
const COACH_TOKEN_BACKUP_KEY = "cf_token_backup";

async function readMeta(): Promise<PreviewState | null> {
  try {
    const raw = await AsyncStorage.getItem(PREVIEW_META_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as PreviewState;
  } catch {
    return null;
  }
}
async function writeMeta(state: PreviewState | null) {
  if (state) await AsyncStorage.setItem(PREVIEW_META_KEY, JSON.stringify(state));
  else await AsyncStorage.removeItem(PREVIEW_META_KEY);
}

type Ctx = {
  preview: PreviewState;
  enterReal: (targetUserId: string) => Promise<PreviewTarget>;
  enterDemo: () => Promise<PreviewTarget>;
  enterNewClient: () => Promise<PreviewTarget>;
  exit: () => Promise<void>;
};

const EMPTY: PreviewState = { active: false, mode: null, target: null, expiresAt: null };
const PreviewCtx = createContext<Ctx>({
  preview: EMPTY,
  enterReal: async () => { throw new Error("not initialised"); },
  enterDemo: async () => { throw new Error("not initialised"); },
  enterNewClient: async () => { throw new Error("not initialised"); },
  exit: async () => {},
});

export function PreviewProvider({ children, onSwap }: { children: React.ReactNode; onSwap?: () => Promise<void> }) {
  const [preview, setPreview] = useState<PreviewState>(EMPTY);

  useEffect(() => {
    (async () => {
      const m = await readMeta();
      if (m) setPreview(m);
    })();
  }, []);

  const enterWith = useCallback(async (path: string, body: any, mode: PreviewMode) => {
    // Backup the coach's current token, so exit can restore it.
    const cur = await AsyncStorage.getItem("cf_token");
    if (cur) await AsyncStorage.setItem(COACH_TOKEN_BACKUP_KEY, cur);

    const r = await api<{ token: string; target: PreviewTarget; expires_hours: number }>(
      path, { method: "POST", body }
    );

    await setToken(r.token);
    const state: PreviewState = {
      active: true,
      mode,
      target: r.target,
      expiresAt: new Date(Date.now() + r.expires_hours * 3600 * 1000).toISOString(),
    };
    await writeMeta(state);
    setPreview(state);
    if (onSwap) await onSwap();
    return r.target;
  }, [onSwap]);

  const enterReal = useCallback(
    (targetUserId: string) => enterWith("/coach/preview/impersonate", { target_user_id: targetUserId }, "real_client"),
    [enterWith]
  );

  const enterDemo = useCallback(async () => {
    // Ensure the demo user exists / is refreshed, then impersonate it.
    const seeded = await api<{ user_id: string; email: string }>("/coach/preview/demo-seed", { method: "POST" });
    return enterWith("/coach/preview/impersonate", { target_user_id: seeded.user_id }, "demo");
  }, [enterWith]);

  const enterNewClient = useCallback(
    () => enterWith("/coach/preview/new-client", {}, "new_client"),
    [enterWith]
  );

  const exit = useCallback(async () => {
    try { await api("/coach/preview/exit", { method: "POST" }); } catch {}
    const backup = await AsyncStorage.getItem(COACH_TOKEN_BACKUP_KEY);
    if (backup) {
      await setToken(backup);
      await AsyncStorage.removeItem(COACH_TOKEN_BACKUP_KEY);
    } else {
      // No coach token to restore — sign out to avoid being stuck as the client.
      await setToken(null);
    }
    await writeMeta(null);
    setPreview(EMPTY);
    if (onSwap) await onSwap();
  }, [onSwap]);

  return (
    <PreviewCtx.Provider value={{ preview, enterReal, enterDemo, enterNewClient, exit }}>
      {children}
    </PreviewCtx.Provider>
  );
}

export const usePreview = () => useContext(PreviewCtx);
