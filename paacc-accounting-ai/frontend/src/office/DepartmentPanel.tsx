import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { formatDateVN } from "../format";
import { KIND, ROLE } from "../labels";
import { metricText } from "./metric";
import { StatusBadge } from "./StatusBadge";
import { MODULE_STATUS_LABEL, TASK_STATUS_LABEL } from "./status";
import { useDepartment } from "./useOfficeData";

export default function DepartmentPanel({ code, onClose, pollMs = 10_000, onChanged }:
  { code: string; onClose: () => void; pollMs?: number; onChanged?: () => void }) {
  const { dept, error, reload } = useDepartment(code, pollMs);
  const [msg, setMsg] = useState("");
  async function decide(id: string, decision: "approve" | "reject") {
    try { await api(`/ai-tasks/${id}/${decision}`, { method: "POST" }); setMsg(""); await reload(); onChanged?.(); }
    catch (e) { setMsg((e as Error).message); }
  }
  if (error) return <aside className="panel"><p className="error">{error}</p></aside>;
  if (!dept) return <aside className="panel"><p>Đang tải…</p></aside>;
  return (
    <aside className="panel" aria-label={`Chi tiết ${dept.name_vi}`}>
      <div className="dept-head"><h3>{dept.name_vi}</h3><button className="ghost" onClick={onClose} aria-label="Đóng">✕</button></div>
      <p><StatusBadge status={dept.status} /> <span className="muted">Phân hệ: {MODULE_STATUS_LABEL[dept.module.status]}{dept.module.phase ? ` (Phase ${dept.module.phase})` : ""}</span></p>
      {dept.module.route
        ? <Link className="btn" to={dept.module.route}>Mở phân hệ</Link>
        : <p className="muted">Phân hệ chưa phát triển – dự kiến Phase {dept.module.phase}.</p>}
      {msg && <p className="error">{msg}</p>}

      <h4>AI Agent</h4>
      <ul className="list">{dept.agents.map((a) => (
        <li key={a.key}><StatusBadge status={a.status} /> {a.name_vi}{!a.enabled && <span className="muted"> (tạm khóa: chưa có quy tắc được kiểm duyệt)</span>}
          {a.current_task && <div className="muted">↳ {a.current_task.title} – {TASK_STATUS_LABEL[a.current_task.status] ?? a.current_task.status}</div>}</li>))}
      </ul>

      <h4>Nhân sự</h4>
      {dept.employees.length === 0 ? <p className="muted">Chưa phân công nhân sự.</p> :
        <ul className="list">{dept.employees.map((e) => <li key={e.user_id}>{e.name} <span className="muted">– {e.job_title || ROLE[e.role] || e.role}</span></li>)}</ul>}

      <h4>Chỉ số</h4>
      {dept.metrics.length === 0 ? <p className="muted">Chưa có dữ liệu (phân hệ chưa phát triển).</p> :
        dept.metrics.map((m) => <div key={m.key} className="metric"><span>{m.label_vi}</span><b>{metricText(m)}</b></div>)}

      <h4>Tác vụ gần đây</h4>
      {(dept.recent_tasks ?? []).length === 0 ? <p className="muted">Chưa có tác vụ.</p> :
        <ul className="list">{dept.recent_tasks!.map((t) => (
          <li key={t.id}><StatusBadge status={t.status === "running" || t.status === "queued" ? "working" : t.status === "cancelled" ? "idle" : t.status} /> {t.title}
            <span className="muted"> · {t.agent_key} · {formatDateVN(t.created_at)}</span>
            {t.error_message && <div className="error">{t.error_message}</div>}
            {t.status === "waiting_approval" && <div className="row">
              <button onClick={() => decide(t.id, "approve")}>Phê duyệt</button>
              <button className="danger" onClick={() => decide(t.id, "reject")}>Từ chối</button></div>}
          </li>))}</ul>}

      <h4>Tài liệu & báo cáo</h4>
      {(dept.recent_documents ?? []).length === 0 ? <p className="muted">Không có tài liệu liên quan.</p> :
        <ul className="list">{dept.recent_documents!.map((d) => <li key={d.id}>{d.title} <span className="muted">– {KIND[d.kind] ?? d.kind} v{d.current_version}</span></li>)}</ul>}
      {dept.code === "internal_audit" && <Link to="/audit">Xem nhật ký hệ thống</Link>}
    </aside>
  );
}
