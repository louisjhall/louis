import React, { createContext, useContext, useEffect, useState } from "react";
import { api, getToken, setToken } from "./api";
import { registerForPush, unregisterForPush } from "./push";

export type Role = "client" | "coach";
export interface UserT {
  id: string;
  email: string;
  name: string;
  role: Role;
  onboarded: boolean;
  coach_id?: string | null;
  profile?: any;
  is_admin?: boolean;
  is_primary_coach?: boolean;
  coach_tier?: string;
  status?: string;
  display_name?: string;
  avatar_url?: string;
  age_confirmed?: boolean;
  [key: string]: any;
}

export type SignupPayload = {
  email: string;
  password: string;
  first_name: string;
  last_name: string;
  age_confirmed: boolean;
  age?: number;
  sex?: string;
  height_cm?: number;
  weight_kg?: number;
  airline?: string;
  job_title?: string;
  home_base?: string;
  photo_base64?: string;
  photo_mime?: string;
};

interface AuthCtx {
  user: UserT | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<UserT>;
  signup: (payload: SignupPayload) => Promise<UserT>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  setUser: (u: UserT | null) => void;
}

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserT | null>(null);
  const [loading, setLoading] = useState(true);

  const bootstrap = async () => {
    setLoading(true);
    const t = await getToken();
    if (t) {
      try {
        const me = await api<UserT>("/auth/me");
        setUser(me);
        registerForPush(me.id).catch(() => {});
      } catch {
        await setToken(null);
        setUser(null);
      }
    }
    setLoading(false);
  };

  useEffect(() => {
    bootstrap();
  }, []);

  const login = async (email: string, password: string) => {
    const r = await api<{ token: string; user: UserT }>("/auth/login", {
      method: "POST",
      body: { email, password },
      noAuth: true,
    });
    await setToken(r.token);
    setUser(r.user);
    registerForPush(r.user.id).catch(() => {});
    return r.user;
  };

  const signup = async (payload: SignupPayload) => {
    const name = `${(payload.first_name || "").trim()} ${(payload.last_name || "").trim()}`.trim();
    const r = await api<{ token: string; user: UserT }>("/auth/signup", {
      method: "POST",
      body: {
        email: payload.email,
        password: payload.password,
        name,
        first_name: payload.first_name,
        last_name: payload.last_name,
        role: "client",   // self-service signup is always client — coaches added by Louis only
        age_confirmed: payload.age_confirmed,
        age: payload.age,
        sex: payload.sex,
        height_cm: payload.height_cm,
        weight_kg: payload.weight_kg,
        airline: payload.airline,
        job_title: payload.job_title,
        home_base: payload.home_base,
        photo_base64: payload.photo_base64,
        photo_mime: payload.photo_mime,
      },
      noAuth: true,
    });
    await setToken(r.token);
    setUser(r.user);
    registerForPush(r.user.id).catch(() => {});
    return r.user;
  };

  const logout = async () => {
    // Iter 123 — Unregister THIS device's push token from the current user
    // BEFORE we clear the session token so the API call still authenticates.
    // Never blocks logout: any error is swallowed inside unregisterForPush.
    try {
      if (user?.id) {
        await unregisterForPush(user.id);
      }
    } catch { /* non-fatal */ }
    await setToken(null);
    setUser(null);
  };

  const refresh = async () => {
    const me = await api<UserT>("/auth/me");
    setUser(me);
  };

  return (
    <Ctx.Provider value={{ user, loading, login, signup, logout, refresh, setUser }}>
      {children}
    </Ctx.Provider>
  );
}

export const useAuth = () => {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth outside provider");
  return c;
};
