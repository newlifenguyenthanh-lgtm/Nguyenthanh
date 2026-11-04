import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, errorText } from "../api";
import PageViewer, { KIND_COLOR } from "./PageViewer";
import { CAL_STATUS, DISCIPLINE, FINDING_VI, FLAG_VI, ITEM_KIND, PAGE_KIND, REL_VI, STATUS_VI, VIEW, pct } from "./labels";
import type { DrawingDetail, Finding, Item, Page } from "./types";

const DEFAULT_KINDS = ["dimension", "count", "spec", "symbol", "reference", "region"];

function describe(it: Item): string {
  const d = it.data;
  if (it.kind === "dimension") {
    const vals = (d.values as (string | null)[] | undefined)?.map((v) => v ?? "?").join(" × ");
    if (d.type === "bar") return `Ø${d.diameter}${d.spacing ? ` a${d.spacing}` : ""}`;
    return `${vals ?? ""} ${d.unit ?? "(chưa rõ đơn vị)"}`;
  }
  if (it.kind === "count") return `SL = ${d.count}`;
  if (it.kind === "spec") return `${d.category}: ${d.value}`;
  if (it.kind === "reference") return `→ ${d.ref}`;
  if (it.kind === "region") return String(d.region_type);
  if (it.kind === "symbol") return `${d.type}`;
  return "";
}

function FindingRow({ f }: { f: Finding }) {
  let extra = "";
  if (f.type === "revision") extra = ` ${f.drawing_number}: rev ${f.this_revision ?? "?"} ${REL_VI[f.relation as string] ?? f.relation} rev ${f.other_revision ?? "?"}`;
  else if (f.type === "repeated_annotation") extra = ` "${f.text}" × ${(f.occurrences as unknown[]).length}`;
  else if (f.type === "overlapping_duplicate_text") extra = ` "${f.text}" (trang ${f.page_no})`;
  else if (f.type === "duplicate_page") extra = ` trang ${(f.pages as number[]).join(" & ")}`;
  return <li className={f.severity === "warning" ? "warn" : ""}>{FINDING_VI[f.type] ?? f.type}{extra}
    {typeof f.other_drawing_id === "string" && <> – <Link to={`/drawings/${f.other_drawing_id}`}>mở</Link></>}</li>;
}

function Calibration({ drawingId, page, onDone }: { drawingId: string; page: Page; onDone: () => void }) {
  const [msg, setMsg] = useState("");
  const first = page.scale_candidates?.find((c) => c.labeled) ?? page.scale_candidates?.[0];
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const nts = f.get("nts") === "on";
    const ratio = f.get("ratio") ? Number(f.get("ratio")) : null;
    const body = { scale_ratio: nts ? null : ratio, not_to_scale: nts, units: f.get("units") || null, note: f.get("note") || "" };
    try {
      const r = await api<{ warnings: string[] }>(`/drawings/${drawingId}/pages/${page.page_no}/calibration`, { method: "POST", body: JSON.stringify(body) });
      setMsg(r.warnings.includes("scale_differs_from_detected") || r.warnings.includes("units_differ_from_detected")
        ? "Đã lưu. Lưu ý: giá trị xác nhận khác với giá trị phát hiện trên bản vẽ." : "Đã lưu xác nhận.");
      onDone();
    } catch (x) { setMsg(errorText(x)); }
  }
  return (
    <form onSubmit={submit} className="calib" key={`${page.page_no}-${page.calibrated_at}`}>
      <div><b>Tỷ lệ:</b> {CAL_STATUS[page.scale_status] ?? page.scale_status}{page.scale_ratio ? ` – 1:${page.scale_ratio}` : ""}
        {page.scale_candidates?.length ? <span className="muted"> · phát hiện: {page.scale_candidates.map((c) => `1:${c.ratio}${c.labeled ? "" : " (không nhãn)"}`).join(", ")}</span> : null}</div>
      <div><b>Đơn vị:</b> {CAL_STATUS[page.units_status] ?? page.units_status}{page.units ? ` – ${page.units}` : ""}
        {page.units_candidates?.length ? <span className="muted"> · phát hiện: {page.units_candidates.map((c) => c.unit).join(", ")}</span> : null}</div>
      <div className="row">
        <label>1 : <input name="ratio" type="number" min={1} defaultValue={page.scale_ratio ?? first?.ratio ?? ""} aria-label="Tỷ lệ" style={{ width: 90 }} /></label>
        <label><input name="nts" type="checkbox" defaultChecked={page.scale_status === "not_to_scale"} /> Không theo tỷ lệ</label>
        <select name="units" aria-label="Đơn vị" defaultValue={page.units ?? page.units_candidates?.[0]?.unit ?? ""}>
          <option value="">— đơn vị —</option><option value="mm">mm</option><option value="cm">cm</option><option value="m">m</option></select>
        <input name="note" placeholder="Ghi chú xác nhận" />
        <button>Xác nhận tỷ lệ/đơn vị</button>
      </div>
      {msg && <p className="muted">{msg}</p>}
    </form>
  );
}

export default function DrawingDetailPage() {
  const { id } = useParams();
  const [d, setD] = useState<DrawingDetail | null>(null);
  const [pageNo, setPageNo] = useState(1);
  const [items, setItems] = useState<Item[]>([]);
  const [kinds, setKinds] = useState<string[]>(DEFAULT_KINDS);
  const [sel, setSel] = useState<string>();
  const [err, setErr] = useState("");
  const load = useCallback(() => api<DrawingDetail>(`/drawings/${id}`).then(setD).catch((e) => setErr(errorText(e))), [id]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!d || d.status !== "processed") return;
    api<Item[]>(`/drawings/${id}/items?page=${pageNo}&kind=${kinds.join(",")}&limit=2000`).then(setItems).catch((e) => setErr(errorText(e)));
  }, [d, id, pageNo, kinds]);
  const page = useMemo(() => d?.pages.find((p) => p.page_no === pageNo), [d, pageNo]);
  if (err) return <main><p className="error">{err}</p></main>;
  if (!d) return <main><p>Đang tải…</p></main>;
  const toggle = (k: string) => setKinds((ks) => (ks.includes(k) ? ks.filter((x) => x !== k) : [...ks, k]));
  return (
    <main className="wide">
      <p><Link to="/drawings">← Danh sách bản vẽ</Link></p>
      <h2>{d.document_title} <span className="muted">– {d.filename} v{d.version_no} · {STATUS_VI[d.status] ?? d.status}</span></h2>
      {d.error_message && <p className="error">{d.error_message}</p>}
      {d.findings.length > 0 && <details open={d.findings.some((f) => f.severity === "warning")}><summary>Phát hiện kiểm tra ({d.findings.length})</summary>
        <ul className="list">{d.findings.map((f, i) => <FindingRow key={i} f={f} />)}</ul></details>}
      <div className="row" role="tablist">{d.pages.map((p) => (
        <button key={p.page_no} role="tab" aria-selected={p.page_no === pageNo} className={p.page_no === pageNo ? "" : "ghost"} onClick={() => { setPageNo(p.page_no); setSel(undefined); }}>
          Trang {p.page_no}{p.drawing_number ? ` · ${p.drawing_number}` : ""}</button>))}</div>
      {page && <div className="drawing-layout">
        <div>
          <PageViewer drawingId={d.id} page={page} items={items} selectedId={sel} onSelect={setSel} />
          <div className="row legend">{Object.keys(ITEM_KIND).map((k) => (
            <label key={k}><input type="checkbox" checked={kinds.includes(k)} onChange={() => toggle(k)} />
              <i className="dot" style={{ background: KIND_COLOR[k] }} />{ITEM_KIND[k]} {d.item_counts[k] != null ? `(${d.item_counts[k]})` : ""}</label>))}</div>
        </div>
        <div className="side">
          <h3>Trang {page.page_no}: {page.drawing_number ?? "chưa rõ số bản vẽ"} {page.revision ? `– Rev ${page.revision}` : ""}</h3>
          <p>{page.title ?? <span className="muted">Không tìm thấy tên bản vẽ</span>}</p>
          <p className="muted">Loại trang: {PAGE_KIND[page.kind] ?? page.kind}{page.ocr_used ? ` · OCR tin cậy TB ${pct(page.ocr_mean_confidence)}` : ""}
            {" · "}Bộ môn: {page.disciplines?.map((x) => `${DISCIPLINE[x.value] ?? x.value} (${x.basis})`).join(", ") || "—"}
            {" · "}Dạng: {page.view_types?.map((x) => VIEW[x.value] ?? x.value).join(", ") || "—"}</p>
          {page.warnings.length > 0 && <p className="error">Cảnh báo: {page.warnings.join(", ")}</p>}
          <Calibration drawingId={d.id} page={page} onDone={load} />
          <div className="scroll items"><table><thead><tr><th>Loại</th><th>Văn bản gốc</th><th>Giá trị</th><th>Tin cậy</th><th>Nguồn</th><th>Cờ</th></tr></thead>
            <tbody>{items.filter((i) => i.kind !== "text" || kinds.includes("text")).map((it) => (
              <tr key={it.id} className={it.id === sel ? "sel" : ""} onClick={() => setSel(it.id)}>
                <td>{ITEM_KIND[it.kind] ?? it.kind}</td><td>{it.text}</td><td>{describe(it)}</td><td>{pct(it.confidence)}</td>
                <td>{it.source === "analysis" ? String(it.data.from_source ?? "") : it.source}</td>
                <td>{(it.data.flags ?? []).map((f) => FLAG_VI[f] ?? f).join(", ")}</td></tr>))}
              {items.length === 0 && <tr><td colSpan={6}>Không có mục nào</td></tr>}</tbody></table></div>
        </div>
      </div>}
    </main>
  );
}
