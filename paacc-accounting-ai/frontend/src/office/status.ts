import type { Status } from "./types";

export const STATUS_META: Record<Status, { label: string; color: string }> = {
  idle: { label: "Rảnh", color: "#9aa5b1" },
  working: { label: "Đang xử lý", color: "#2f80ed" },
  waiting_approval: { label: "Chờ phê duyệt", color: "#f2994a" },
  completed: { label: "Hoàn thành", color: "#27ae60" },
  error: { label: "Lỗi", color: "#eb5757" },
};

export function statusMeta(s: string): { label: string; color: string } {
  return STATUS_META[s as Status] ?? { label: s, color: "#9aa5b1" };
}

export const TASK_STATUS_LABEL: Record<string, string> = {
  queued: "Đang chờ", running: "Đang chạy", waiting_approval: "Chờ phê duyệt",
  completed: "Hoàn thành", error: "Lỗi", cancelled: "Đã hủy",
};

export const MODULE_STATUS_LABEL = { available: "Sẵn sàng", partial: "Một phần", planned: "Chưa phát triển" } as const;
