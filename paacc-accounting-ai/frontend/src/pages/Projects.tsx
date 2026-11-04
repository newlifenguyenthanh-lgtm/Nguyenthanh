import { FormEvent, useCallback, useEffect, useState } from "react";
import { Project, api } from "../api";
import { formatDateVN } from "../format";
import { STATUS } from "../labels";

export default function Projects() {
  const [rows, setRows] = useState<Project[]>([]);
  const [q, setQ] = useState("");
  const [err, setErr] = useState("");
  const load = useCallback(() => api<Project[]>(`/projects?q=${encodeURIComponent(q)}`).then(setRows).catch((e) => setErr(e.message)), [q]);
  useEffect(() => { load(); }, [load]);
  async function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget, f = new FormData(form);
    try {
      await api("/projects", { method: "POST", body: JSON.stringify({ code: f.get("code"), name: f.get("name"), location: f.get("location") || null }) });
      form.reset(); setErr(""); load();
    } catch (x) { setErr((x as Error).message); }
  }
  return (
    <section>
      <h2>Dự án</h2>
      <input placeholder="Tìm theo mã hoặc tên…" value={q} onChange={(e) => setQ(e.target.value)} />
      {err && <p className="error">{err}</p>}
      <div className="scroll"><table><thead><tr><th>Mã</th><th>Tên dự án</th><th>Địa điểm</th><th>Trạng thái</th><th>Bắt đầu</th></tr></thead>
        <tbody>{rows.map((p) => <tr key={p.id}><td>{p.code}</td><td>{p.name}</td><td>{p.location ?? "—"}</td><td>{STATUS[p.status] ?? p.status}</td><td>{formatDateVN(p.start_date)}</td></tr>)}
          {rows.length === 0 && <tr><td colSpan={5}>Chưa có dự án</td></tr>}</tbody></table></div>
      <form onSubmit={add} className="row"><input name="code" placeholder="Mã" required /><input name="name" placeholder="Tên dự án" required /><input name="location" placeholder="Địa điểm" /><button>Thêm dự án</button></form>
    </section>
  );
}
