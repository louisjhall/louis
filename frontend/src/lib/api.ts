import AsyncStorage from "@react-native-async-storage/async-storage";

const RAW_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || "";
export const API_BASE = RAW_BASE.replace(/\/$/, "") + "/api";

let cachedToken: string | null = null;

export async function getToken(): Promise<string | null> {
  if (cachedToken) return cachedToken;
  const t = await AsyncStorage.getItem("cf_token");
  cachedToken = t;
  return t;
}

export async function setToken(t: string | null) {
  cachedToken = t;
  if (t) await AsyncStorage.setItem("cf_token", t);
  else await AsyncStorage.removeItem("cf_token");
}

export async function api<T = any>(
  path: string,
  opts: { method?: string; body?: any; noAuth?: boolean } = {}
): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (!opts.noAuth) {
    const token = await getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  const res = await fetch(`${API_BASE}${path}`, {
    method: opts.method || "GET",
    headers,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    let structuredDetail: any = null;
    try {
      const j = await res.json();
      // Preview-mode friendly error: bubble up a clean toast, don't spam consoles.
      if (res.status === 403 && j?.detail && typeof j.detail === "object" && j.detail.error === "preview_readonly") {
        const err: any = new Error(j.detail.message || "Preview mode is read-only.");
        err.preview_readonly = true;
        throw err;
      }
      // Iter 84 (Task 1.4) — preserve structured detail (e.g. profile_incomplete)
      // so callers can branch on `err.detail.code` without re-parsing.
      if (j?.detail && typeof j.detail === "object") {
        structuredDetail = j.detail;
        msg = j.detail.message || JSON.stringify(j.detail);
      } else {
        msg = j.detail || JSON.stringify(j);
      }
    } catch (e: any) {
      if (e?.preview_readonly) throw e;
    }
    const err: any = new Error(msg);
    err.status = res.status;
    if (structuredDetail) err.detail = structuredDetail;
    throw err;
  }
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return (await res.json()) as T;
  return (await res.text()) as unknown as T;
}

/**
 * Upload a file via multipart/form-data.
 * `file` should be either a React-Native-friendly object
 * `{ uri, name, type }` (works on native + expo web via Blob polyfill),
 * or a browser File/Blob.
 */
export async function uploadFile<T = any>(
  path: string,
  file: { uri: string; name: string; type: string } | Blob | File,
  extraFields: Record<string, string | number | undefined | null> = {},
  opts: { onProgress?: (loaded: number, total: number) => void } = {}
): Promise<T> {
  const form = new FormData();
  // @ts-ignore RN FormData accepts { uri, name, type }
  form.append("file", file as any);
  for (const [k, v] of Object.entries(extraFields)) {
    if (v === undefined || v === null) continue;
    form.append(k, String(v));
  }
  const token = await getToken();
  const url = `${API_BASE}${path}`;

  // Prefer XHR for progress reporting where available
  if (typeof XMLHttpRequest !== "undefined" && opts.onProgress) {
    return await new Promise<T>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", url);
      if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) opts.onProgress?.(e.loaded, e.total);
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try { resolve(JSON.parse(xhr.responseText) as T); }
          catch { resolve(xhr.responseText as unknown as T); }
        } else {
          let msg = `HTTP ${xhr.status}`;
          try { const j = JSON.parse(xhr.responseText); msg = j.detail || msg; } catch {}
          reject(new Error(msg));
        }
      };
      xhr.onerror = () => reject(new Error("Network error during upload"));
      xhr.send(form as any);
    });
  }

  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(url, { method: "POST", headers, body: form as any });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try { const j = await res.json(); msg = j.detail || JSON.stringify(j); } catch {}
    throw new Error(msg);
  }
  return (await res.json()) as T;
}

/** Build a token-signed streaming URL (used for <video> preview since <video> can't send headers). */
export async function buildStreamUrl(path: string): Promise<string> {
  const token = await getToken();
  const sep = path.includes("?") ? "&" : "?";
  return `${API_BASE}${path}${token ? `${sep}token=${encodeURIComponent(token)}` : ""}`;
}
