import React, { createContext, useContext, useEffect, useState } from "react";
import { api, getToken, setToken } from "./api";
import { registerForPush } from "./push";

export type Role = "client" | "coach";
export interface UserT {
  id: string;
  email: string;
  name: string;
  role: Role;
  onboarded: boolean;
  coach_id?: string | null;
  profile?: any;
}

interface AuthCtx {
  user: UserT | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<UserT>;
  signup: (email: string, password: string, name: string, role: Role, ageConfirmed: boolean) => Promise<UserT>;
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

  const signup = async (email: string, password: string, name: string, role: Role, ageConfirmed: boolean) => {
    const r = await api<{ token: string; user: UserT }>("/auth/signup", {
      method: "POST",
      body: { email, password, name, role, age_confirmed: ageConfirmed },
      noAuth: true,
    });
    await setToken(r.token);
    setUser(r.user);
    registerForPush(r.user.id).catch(() => {});
    return r.user;
  };

  const logout = async () => {
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
