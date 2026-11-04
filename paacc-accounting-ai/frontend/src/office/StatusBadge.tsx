import { statusMeta } from "./status";

export function StatusBadge({ status }: { status: string }) {
  const m = statusMeta(status);
  return <span className="badge" style={{ background: m.color }} data-status={status}>{m.label}</span>;
}
