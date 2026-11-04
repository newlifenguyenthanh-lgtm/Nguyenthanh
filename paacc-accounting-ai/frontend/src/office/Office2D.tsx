import type { Department } from "./types";
import { metricText } from "./metric";
import { StatusBadge } from "./StatusBadge";
import { MODULE_STATUS_LABEL } from "./status";

/** Conventional 2D dashboard over the same real data as the 3D office (also the no-WebGL fallback). */
export default function Office2D({ departments, selected, onSelect }:
  { departments: Department[]; selected?: string; onSelect: (code: string) => void }) {
  return (
    <div className="dept-grid">
      {departments.map((d) => {
        const active = (d.task_counts.queued ?? 0) + (d.task_counts.running ?? 0);
        return (
          <button key={d.code} className={`dept-card${selected === d.code ? " sel" : ""}`} style={{ borderTopColor: d.color }}
            onClick={() => onSelect(d.code)} aria-label={`Phòng ban ${d.name_vi}`}>
            <div className="dept-head"><strong>{d.name_vi}</strong><StatusBadge status={d.status} /></div>
            <div className="muted">AI Agent: {d.agents.length} · Nhân sự: {d.employees.length} · Phân hệ: {MODULE_STATUS_LABEL[d.module.status]}</div>
            <div className="muted">Đang xử lý: {active} · Chờ duyệt: {(d.task_counts.waiting_approval ?? 0) + d.pending_business_approvals} · Lỗi: {d.task_counts.error ?? 0}</div>
            {d.metrics.slice(0, 3).map((m) => <div key={m.key} className="metric"><span>{m.label_vi}</span><b>{metricText(m)}</b></div>)}
          </button>
        );
      })}
    </div>
  );
}
