import { FormEvent, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Doc, api } from "../api";
import { KIND } from "../labels";

export default function Documents() {
  const [params, setParams] = useSearchParams();
  const kind = params.get("kind") ?? "";
  const [rows, setRows] = useState<Doc[]>([]);
  const [err, setErr] = useState("");
  const load = useCallback(() => api<Doc[]>(`/documents${kind ? `?kind=${encodeURIComponent(kind)}` : ""}`).then(setRows).catch((e) => setErr(e.message)), [kind]);
  useEffect(() => { load(); }, [load]);
  async function upload(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    try {
      const r = await api<{ duplicate_of_document_id: string | null }>("/documents", { method: "POST", body: new FormData(form) });
      setErr(r.duplicate_of_document_id ? "Cảnh báo: nội dung file trùng với một tài liệu đã có." : "");
      form.reset(); load();
    } catch (x) { setErr((x as Error).message); }
  }
  return (
    <section>
      <h2>Tài liệu</h2>
      <select aria-label="Lọc loại tài liệu" value={kind} onChange={(e) => setParams(e.target.value ? { kind: e.target.value } : {})}>
        <option value="">Tất cả loại</option>{Object.entries(KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
      {err && <p className="error">{err}</p>}
      <div className="scroll"><table><thead><tr><th>Tên</th><th>Loại</th><th>Phiên bản</th></tr></thead>
        <tbody>{rows.map((d) => <tr key={d.id}><td>{d.title}</td><td>{KIND[d.kind] ?? d.kind}</td><td>v{d.current_version}</td></tr>)}
          {rows.length === 0 && <tr><td colSpan={3}>Chưa có tài liệu</td></tr>}</tbody></table></div>
      <form onSubmit={upload} className="row">
        <input name="title" placeholder="Tên tài liệu" required />
        <select name="kind" defaultValue={kind || "drawing"}>{Object.entries(KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <input name="file" type="file" required /><button>Tải lên</button>
      </form>
    </section>
  );
}
