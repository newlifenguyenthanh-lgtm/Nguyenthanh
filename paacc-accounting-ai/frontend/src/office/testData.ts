// Synthetic fixtures for unit tests only (no real company data).
import type { Agent, Department, Status } from "./types";

export function agent(key: string, status: Status = "idle", extra: Partial<Agent> = {}): Agent {
  return { key, name_vi: `Agent ${key}`, enabled: true, status, current_task: null, ...extra };
}

export function dept(code: string, i: number, extra: Partial<Department> = {}): Department {
  return {
    code, name_vi: `Phòng ${code}`, color: "#4f7cac", status: "idle",
    layout: { x: (i % 5) * 9.5 - 19, z: Math.floor(i / 5) * 7.5 - 3.75, w: 8, d: 6 },
    agents: [agent(`${code}_a`)], employees: [], metrics: [], task_counts: {},
    pending_business_approvals: 0, module: { route: null, status: "planned", phase: 5 }, ...extra,
  };
}

export const CODES = ["board", "bidding", "engineering_qs", "cad_design", "estimation", "contract_payment",
  "accounting_finance", "procurement_inventory", "construction", "internal_audit"];

export function tenDepartments(): Department[] {
  return CODES.map((c, i) => dept(c, i));
}

export function mockFetch(routes: Record<string, unknown>, calls: { url: string; method: string }[] = []) {
  return async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input).replace("/api/v1", "");
    calls.push({ url, method: init?.method ?? "GET" });
    const body = routes[`${init?.method ?? "GET"} ${url}`] ?? routes[url];
    if (body === undefined) return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
    return new Response(JSON.stringify(body), { status: 200 });
  };
}
