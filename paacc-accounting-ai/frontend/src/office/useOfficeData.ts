import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { Department } from "./types";

/** Polls real backend data. Interval 0 disables polling (tests). */
export function useOfficeData(intervalMs = 10_000) {
  const [departments, setDepartments] = useState<Department[] | null>(null);
  const [error, setError] = useState("");
  const reload = useCallback(() =>
    api<{ departments: Department[] }>("/office/overview")
      .then((r) => { setDepartments(r.departments); setError(""); })
      .catch((e: Error) => setError(e.message)), []);
  useEffect(() => {
    reload();
    if (!intervalMs) return;
    const id = setInterval(reload, intervalMs);
    return () => clearInterval(id);
  }, [reload, intervalMs]);
  return { departments, error, reload };
}

export function useDepartment(code: string | undefined, intervalMs = 10_000) {
  const [dept, setDept] = useState<Department | null>(null);
  const [error, setError] = useState("");
  const reload = useCallback(() => {
    if (!code) return Promise.resolve();
    return api<Department>(`/office/departments/${code}`).then((d) => { setDept(d); setError(""); })
      .catch((e: Error) => setError(e.message));
  }, [code]);
  useEffect(() => {
    setDept(null); reload();
    if (!intervalMs || !code) return;
    const id = setInterval(reload, intervalMs);
    return () => clearInterval(id);
  }, [reload, intervalMs, code]);
  return { dept, error, reload };
}
