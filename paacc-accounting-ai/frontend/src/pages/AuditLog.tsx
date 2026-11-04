import { useEffect, useState } from "react";
import { api } from "../api";

interface Row { action: string; entity: string; entity_id: string; user_id: string; detail: unknown }

export default function AuditLog() {
  const [rows, setRows] = useState<Row[]>([]);
  const [err, setErr] = useState("");
  useEffect(() => { api<Row[]>("/audit-logs").then(setRows).catch((e) => setErr(e.message)); }, []);
  return (
    <section>
      <h2>Nhật ký hệ thống</h2>
      {err && <p className="error">{err}</p>}
      <div className="scroll"><table><thead><tr><th>Hành động</th><th>Đối tượng</th><th>Mã</th><th>Chi tiết</th></tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i}><td>{r.action}</td><td>{r.entity}</td><td>{r.entity_id.slice(0, 8)}</td><td><code>{JSON.stringify(r.detail)?.slice(0, 120)}</code></td></tr>)}
          {rows.length === 0 && !err && <tr><td colSpan={4}>Chưa có dữ liệu</td></tr>}</tbody></table></div>
    </section>
  );
}
