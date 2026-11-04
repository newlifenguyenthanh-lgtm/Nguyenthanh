import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Project, api, errorText } from "../api";
import { formatDateVN } from "../format";
import { STATUS_VI } from "./labels";
import type { DrawingSummary } from "./types";

export default function DrawingsPage() {
  const [rows, setRows] = useState<DrawingSummary[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const navigate = useNavigate();
  const load = useCallback(() => api<DrawingSummary[]>("/drawings").then(setRows).catch((e) => setErr(errorText(e))), []);
  useEffect(() => { load(); api<Project[]>("/projects").then(setProjects).catch(() => setProjects([])); }, [load]);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    fd.set("kind", "drawing");
    if (!fd.get("project_id")) fd.delete("project_id");
    setBusy(true); setErr("");
    try {
      const doc = await api<{ id: string }>("/documents", { method: "POST", body: fd });
      const d = await api<DrawingSummary>("/drawings", { method: "POST", body: JSON.stringify({ document_id: doc.id }) });
      navigate(`/drawings/${d.id}`);
    } catch (x) { setErr(errorText(x)); } finally { setBusy(false); }
  }

  return (
    <section>
      <h2>Bản vẽ PDF</h2>
      <form onSubmit={submit} className="row card">
        <input name="title" placeholder="Tên bản vẽ" required />
        <select name="project_id" aria-label="Dự án" defaultValue=""><option value="">— Không gắn dự án —</option>
          {projects.map((p) => <option key={p.id} value={p.id}>{p.code} – {p.name}</option>)}</select>
        <input name="file" type="file" accept="application/pdf,.pdf" required aria-label="Tệp PDF" />
        <button disabled={busy}>{busy ? "Đang phân tích…" : "Tải lên & phân tích"}</button>
      </form>
      <p className="muted">File gốc được lưu bất biến; phân tích chỉ đọc. Tỷ lệ và đơn vị phát hiện được luôn cần kỹ sư xác nhận.</p>
      {err && <p className="error">{err}</p>}
      <div className="scroll"><table><thead><tr><th>Tệp</th><th>Phiên bản</th><th>Trạng thái</th><th>Số trang</th><th>Cảnh báo</th><th>Ngày</th></tr></thead>
        <tbody>{rows.map((d) => (
          <tr key={d.id}><td><Link to={`/drawings/${d.id}`}>{d.filename}</Link></td><td>v{d.version_no}</td>
            <td>{STATUS_VI[d.status] ?? d.status}{d.error_message && <div className="error">{d.error_message}</div>}</td>
            <td>{d.page_count}</td><td>{d.findings.filter((f) => f.severity === "warning").length}</td><td>{formatDateVN(d.processed_at)}</td></tr>))}
          {rows.length === 0 && <tr><td colSpan={6}>Chưa có bản vẽ</td></tr>}</tbody></table></div>
    </section>
  );
}
