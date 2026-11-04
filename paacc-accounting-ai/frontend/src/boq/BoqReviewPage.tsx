import { FormEvent, Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, errorText } from "../api";
import ItemEditor from "./ItemEditor";
import { BOQ_STATUS, BOQ_STATUS_COLOR, CATEGORY, ORIGIN, REVIEW } from "./labels";
import type { Boq, BoqItem, ModuleSpec } from "./types";

export function qty(v: string | null, decimals: number): string {
  if (v == null) return "—";
  const n = Number(v);
  return Number.isFinite(n) ? n.toLocaleString("vi-VN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) : v;
}

export default function BoqReviewPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [boq, setBoq] = useState<Boq | null>(null);
  const [modules, setModules] = useState<Record<string, ModuleSpec>>({});
  const [open, setOpen] = useState<string>();
  const [filter, setFilter] = useState("all");
  const [msg, setMsg] = useState("");
  const load = useCallback(() => api<Boq>(`/boqs/${id}`).then(setBoq).catch((e) => setMsg(errorText(e))), [id]);
  useEffect(() => {
    load();
    api<{ modules: ModuleSpec[] }>("/takeoff/modules").then((r) => setModules(Object.fromEntries(r.modules.map((m) => [m.key, m])))).catch(() => {});
  }, [load]);
  const items = useMemo(() => (boq?.items ?? []).filter((i) =>
    filter === "all" ? true : filter === "blocking" ? i.has_blocking && i.review_status !== "rejected"
      : filter === "flagged" ? i.flags.length > 0 : i.review_status === filter), [boq, filter]);
  if (!boq) return <main>{msg ? <p className="error">{msg}</p> : <p>Đang tải…</p>}</main>;
  const editable = boq.status === "draft" || boq.status === "returned";
  const dec = boq.rules.decimals;

  async function act(path: string, body: unknown, after?: (b: Boq) => void) {
    try { const r = await api<Boq>(`/boqs/${boq!.id}${path}`, { method: "POST", body: JSON.stringify(body) }); setMsg(""); after ? after(r) : setBoq(r); }
    catch (e) { setMsg(errorText(e)); }
  }
  function saveRules(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const waste: Record<string, string> = {};
    for (const c of Object.keys(CATEGORY)) { const v = String(f.get(`w_${c}`) ?? ""); if (v) waste[c] = v; }
    api<Boq>(`/boqs/${boq!.id}/rules`, { method: "PATCH", body: JSON.stringify({ decimals: Number(f.get("decimals")),
      steel_density: String(f.get("steel_density")), waste, reason: String(f.get("reason") ?? "") }) })
      .then((r) => { setBoq(r); setMsg(""); }).catch((x) => setMsg(errorText(x)));
  }
  const updateItem = (it: BoqItem) => { load(); setOpen(it.id); };
  const note = () => (document.getElementById("boq-note") as HTMLInputElement | null)?.value ?? "";

  return (
    <main className="wide">
      <p><Link to="/boqs">← Danh sách BOQ</Link></p>
      <h2>{boq.title} <span className="muted">v{boq.version_no}</span>{" "}
        <span className="badge" style={{ background: BOQ_STATUS_COLOR[boq.status] }}>{BOQ_STATUS[boq.status] ?? boq.status}</span></h2>
      <p className="muted">Nguồn: {boq.sources.map((s) => <Link key={s.drawing_id} to={`/drawings/${s.drawing_id}`}> bản vẽ </Link>)}
        · {boq.item_count} hạng mục · chờ rà soát {boq.review_counts.pending ?? 0} · chấp nhận {boq.review_counts.accepted ?? 0}
        · loại bỏ {boq.review_counts.rejected ?? 0} · <b className={boq.blocking_count ? "error" : ""}>còn lỗi chặn: {boq.blocking_count}</b>
        {boq.previous_boq_id && <> · <Link to={`/boqs/${boq.previous_boq_id}`}>phiên bản trước</Link></>}</p>
      {boq.decision_note && <p>Ý kiến phê duyệt: <i>{boq.decision_note}</i></p>}
      <div className="row card">
        <input id="boq-note" placeholder="Ghi chú / lý do" aria-label="Ghi chú BOQ" />
        {editable && <button onClick={() => act("/submit", { note: note() })}>Trình phê duyệt</button>}
        {boq.status === "submitted" && <>
          <button onClick={() => act("/decision", { decision: "approve", note: note() })}>Phê duyệt</button>
          <button className="danger" onClick={() => act("/decision", { decision: "return", note: note() })}>Trả lại</button>
          <span className="muted">Cần quyền phê duyệt; người trình không được tự duyệt.</span></>}
        {boq.status === "approved" && <button onClick={() => act("/new-version", { reason: note() }, (b) => navigate(`/boqs/${b.id}`))}>Tạo phiên bản mới</button>}
      </div>
      {msg && <p className="error">{msg}</p>}

      <details><summary>Quy tắc đo bóc (thập phân {dec}, tỷ trọng thép {boq.rules.steel_density} kg/m³, hao hụt theo danh mục)</summary>
        <form onSubmit={saveRules} className="row" key={JSON.stringify(boq.rules)}>
          <label>Số thập phân <input name="decimals" type="number" min={0} max={6} defaultValue={dec} disabled={!editable} style={{ width: 60 }} /></label>
          <label>Tỷ trọng thép <input name="steel_density" defaultValue={boq.rules.steel_density} disabled={!editable} style={{ width: 80 }} /></label>
          {Object.entries(CATEGORY).map(([c, v]) => <label key={c}>Hao hụt {v} <input name={`w_${c}`} defaultValue={boq.rules.waste[c] ?? ""} placeholder="0" disabled={!editable} style={{ width: 60 }} /></label>)}
          {editable && <><input name="reason" placeholder="Lý do" /><button>Lưu & tính lại</button></>}
        </form>
      </details>

      <h3>Tổng hợp</h3>
      <div className="scroll"><table><thead><tr><th>Danh mục</th><th>ĐVT</th><th>Đã chấp nhận</th><th>Tất cả (trừ loại bỏ)</th><th>Số mục</th></tr></thead>
        <tbody>{boq.totals.map((t) => <tr key={`${t.category}-${t.unit}`}><td>{CATEGORY[t.category] ?? t.category}</td><td>{t.unit}</td>
          <td>{qty(t.accepted, dec)}</td><td>{qty(t.all_active, dec)}</td><td>{t.items}</td></tr>)}</tbody></table></div>

      <h3>Hạng mục</h3>
      <select value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Lọc hạng mục">
        <option value="all">Tất cả</option><option value="pending">Chờ rà soát</option><option value="accepted">Chấp nhận</option>
        <option value="rejected">Loại bỏ</option><option value="blocking">Còn lỗi chặn</option><option value="flagged">Có cảnh báo</option></select>
      <div className="scroll"><table className="boq-table"><thead><tr><th>STT</th><th>Danh mục</th><th>Mô tả</th><th>Quy cách</th>
        <th>Khối lượng</th><th>ĐVT</th><th>Nguồn gốc</th><th>Cảnh báo</th><th>Rà soát</th></tr></thead>
        <tbody>{items.map((i) => (
          <Fragment key={i.id}>
            <tr className={`clickable ${i.review_status}`} onClick={() => setOpen(open === i.id ? undefined : i.id)} aria-label={`Hạng mục ${i.item_no}`}>
              <td>{i.item_no}</td><td>{CATEGORY[i.category] ?? i.category}</td><td>{i.description}</td><td>{i.spec}</td>
              <td className="num">{qty(i.quantity, dec)}</td><td>{i.unit}</td><td>{ORIGIN[i.origin] ?? i.origin}</td>
              <td>{i.has_blocking ? "⛔ " : ""}{i.flags.filter((f) => f.severity === "warning").length ? `⚠ ${i.flags.filter((f) => f.severity === "warning").length}` : ""}</td>
              <td>{REVIEW[i.review_status]}</td></tr>
            {open === i.id && <tr><td colSpan={9}>
              <ItemEditor boqId={boq.id} item={i} module={i.module ? modules[i.module] : undefined} editable={editable} onChanged={updateItem} /></td></tr>}
          </Fragment>))}
          {items.length === 0 && <tr><td colSpan={9}>Không có hạng mục</td></tr>}</tbody></table></div>
    </main>
  );
}
