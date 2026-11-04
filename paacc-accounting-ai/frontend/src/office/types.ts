export type Status = "idle" | "working" | "waiting_approval" | "completed" | "error";

export interface Layout { x: number; z: number; w: number; d: number }
export interface Task {
  id: string; agent_key: string; department_code: string; title: string; status: string;
  requires_approval: boolean; error_message: string; output_summary: string; created_at: string | null; finished_at: string | null;
}
export interface Agent { key: string; name_vi: string; enabled: boolean; status: Status; current_task: Task | null }
export interface Employee { user_id: string; name: string; role: string; job_title: string }
export interface Metric { key: string; label_vi: string; value: string }
export interface Department {
  code: string; name_vi: string; color: string; layout: Layout; status: Status;
  agents: Agent[]; employees: Employee[]; metrics: Metric[];
  task_counts: Record<string, number>; pending_business_approvals: number;
  module: { route: string | null; status: "available" | "partial" | "planned"; phase: number | null };
  recent_tasks?: Task[]; recent_documents?: { id: string; title: string; kind: string; current_version: number }[];
}
