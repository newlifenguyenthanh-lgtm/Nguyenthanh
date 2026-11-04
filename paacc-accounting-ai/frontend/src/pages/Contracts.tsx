import { useEffect, useState } from "react";
import { api } from "../api";
import { formatVND } from "../format";

interface Contract { id: string; number: string; title: string; direction: string; original_value: string; status: string }
interface Summary { adjusted_value: string; pending_appendices: number }

/** Read-only contract register (Phase 7 will add full contract/payment management UI). Values come from the backend. */
export default function Contracts() {
  const [rows, setRows] = useState<Contract[]>([]);
  const [sum, setSum] = useState<Record<string, Summary>>({});
  const [err, setErr] = useState("");
  useEffect(() => {
    api<Contract[]>("/contracts").then(async (cs) => {
      setRows(cs);
      const entries = await Promise.all(cs.map(async (c) => [c.id, await api<Summary>(`/contracts/${c.id}/summary`)] as const));
      setSum(Object.fromEntries(entries));
    }).catch((e) => setErr(e.message));
  }, []);
  return (
    <section>
      <h2>Hợp đồng</h2>
      {err && <p className="error">{err}</p>}
      <div className="scroll"><table><thead><tr><th>Số HĐ</th><th>Tên</th><th>Loại</th><th>Giá trị gốc</th><th>Giá trị sau điều chỉnh</th><th>Phụ lục chờ duyệt</th></tr></thead>
        <tbody>{rows.map((c) => <tr key={c.id}><td>{c.number}</td><td>{c.title || "—"}</td><td>{c.direction === "outbound" ? "Đầu ra" : "Đầu vào"}</td>
          <td>{formatVND(c.original_value)}</td><td>{sum[c.id] ? formatVND(sum[c.id].adjusted_value) : "…"}</td><td>{sum[c.id]?.pending_appendices ?? "…"}</td></tr>)}
          {rows.length === 0 && <tr><td colSpan={6}>Chưa có hợp đồng</td></tr>}</tbody></table></div>
    </section>
  );
}
