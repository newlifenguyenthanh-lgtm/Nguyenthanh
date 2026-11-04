import { FormEvent, useCallback, useEffect, useState } from "react";
import { ApiError, Doc, Me, Project, api, auth } from "./api";
import { formatDateVN } from "./format";

const STATUS: Record<string, string> = { planning: "Chuẩn bị", active: "Đang thi công", done: "Hoàn thành", paused: "Tạm dừng" };
const KIND: Record<string, string> = { drawing: "Bản vẽ", boq: "BOQ", quote: "Báo giá", contract: "Hợp đồng", email: "Email", other: "Khác" };
const ROLE: Record<string, string> = { admin: "Quản trị", director: "Giám đốc", accountant: "Kế toán", site_manager: "Chỉ huy công trường", viewer: "Chỉ xem" };

function Login({ onDone }: { onDone: () => void }) {
  const [err, setErr] = useState("");
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    try {
      const r = await api<{ access_token: string }>("/auth/login", { method: "POST", body: JSON.stringify({ email: f.get("email"), password: f.get("password") }) });
      auth.set(r.access_token); onDone();
    } catch (x) { setErr(x instanceof ApiError ? x.message : "Không kết nối được máy chủ"); }
  }
  return (
    <form onSubmit={submit} className="card login">
      <h1>PAACC Construction AI</h1>
      <input name="email" type="email" placeholder="Email" required />
      <input name="password" type="password" placeholder="Mật khẩu" required />
      {err && <p className="error">{err}</p>}
      <button>Đăng nhập</button>
    </form>
  );
}

function Projects() {
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

function Documents() {
  const [rows, setRows] = useState<Doc[]>([]);
  const [err, setErr] = useState("");
  const load = useCallback(() => api<Doc[]>("/documents").then(setRows).catch((e) => setErr(e.message)), []);
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
      {err && <p className="error">{err}</p>}
      <div className="scroll"><table><thead><tr><th>Tên</th><th>Loại</th><th>Phiên bản</th></tr></thead>
        <tbody>{rows.map((d) => <tr key={d.id}><td>{d.title}</td><td>{KIND[d.kind] ?? d.kind}</td><td>v{d.current_version}</td></tr>)}
          {rows.length === 0 && <tr><td colSpan={3}>Chưa có tài liệu</td></tr>}</tbody></table></div>
      <form onSubmit={upload} className="row">
        <input name="title" placeholder="Tên tài liệu" required />
        <select name="kind" defaultValue="drawing">{Object.entries(KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <input name="file" type="file" required /><button>Tải lên</button>
      </form>
    </section>
  );
}

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [tab, setTab] = useState<"projects" | "documents">("projects");
  const [ready, setReady] = useState(false);
  const refresh = useCallback(() => {
    if (!auth.token) { setMe(null); setReady(true); return; }
    api<Me>("/auth/me").then(setMe).catch(() => { auth.set(null); setMe(null); }).finally(() => setReady(true));
  }, []);
  useEffect(refresh, [refresh]);
  if (!ready) return null;
  if (!me) return <Login onDone={refresh} />;
  return (
    <div className="app">
      <header><strong>PAACC Construction AI</strong>
        <nav><button className={tab === "projects" ? "on" : ""} onClick={() => setTab("projects")}>Dự án</button>
          <button className={tab === "documents" ? "on" : ""} onClick={() => setTab("documents")}>Tài liệu</button></nav>
        <span>{me.full_name || me.email} · {ROLE[me.role] ?? me.role} <button onClick={() => { auth.set(null); setMe(null); }}>Đăng xuất</button></span>
      </header>
      <main>{tab === "projects" ? <Projects /> : <Documents />}</main>
    </div>
  );
}
