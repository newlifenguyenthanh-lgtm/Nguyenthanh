const BASE = "/api/v1";
let token: string | null = sessionStorage.getItem("paacc_token");

export const auth = {
  get token() { return token; },
  set(t: string | null) {
    token = t;
    if (t) sessionStorage.setItem("paacc_token", t); else sessionStorage.removeItem("paacc_token");
  },
};

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const res = await fetch(BASE + path, { ...init, headers });
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch { /* ignore */ }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export interface Project { id: string; code: string; name: string; location: string | null; status: string; start_date: string | null; end_date: string | null }
export interface Doc { id: string; title: string; kind: string; project_id: string | null; current_version: number }
export interface Me { id: string; email: string; full_name: string; role: string }
