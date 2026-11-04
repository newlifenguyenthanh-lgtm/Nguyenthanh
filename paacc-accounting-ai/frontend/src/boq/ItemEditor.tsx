import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { api, errorText } from "../api";
import { formatDateVN } from "../format";
import { ACTION, CATEGORY, ORIGIN } from "./labels";
import type { BoqItem, HistoryRow, ModuleSpec } from "./types";

const SEV_CLASS: Record<string, string> = { blocking: "flag-block", warning: "flag-warn", info: "flag-info" };

export function FlagList({ flags }: { flags: BoqItem["flags"] }) {
  if (!flags.length) return <span className="muted">Không có cảnh báo</span>;
  return <ul className="flags">{flags.map((f, i) => <li key={i} className={SEV_CLASS[f.severity]}>
    {f.severity === "blocking" ? "⛔" : f.severity === "warning" ? "⚠" : "ℹ"} {f.message}</li>)}</ul>;
}

export default function ItemEditor({ boqId, item, module, editable, onChanged }:
  { boqId: string; item: BoqItem; module?: ModuleSpec; editable: boolean; onChanged: (i: BoqItem) => void }) {
  const [msg, setMsg] = useState("");
  const [hist, setHist] = useState<HistoryRow[] | null>(null);
  const base = `/boqs/${boqId}/items/${item.id}`;

  async function call(path: string, method: string, body: unknown) {
    try {
      const r = await api<BoqItem>(path, { method, body: JSON.stringify(body) });
      setMsg(""); onChanged(r); if (hist) loadHistory();
    } catch (e) { setMsg(errorText(e)); }
  }
  function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const body: Record<string, unknown> = { reason: f.get("reason") ?? "" };
    if (module) {
      const inputs: Record<string, string | null> = {};
      for (const fl of module.fields) {
        const v = String(f.get(`in_${fl.name}`) ?? "");
        if (v !== (item.inputs[fl.name]?.value ?? "")) inputs[fl.name] = v || null;
      }
      if (Object.keys(inputs).length) body.inputs = inputs;
      const us = String(f.get("unit_system") ?? "");
      if (module.dimensional && us !== (item.unit_system ?? "")) body.unit_system = us || null;
    } else {
      const q = String(f.get("stated_quantity") ?? "");
      if (q !== (item.inputs.quantity?.value ?? "")) body.stated_quantity = q || null;
      const su = String(f.get("stated_unit") ?? "");
      if (su !== (item.stated_unit ?? "")) body.stated_unit = su;
    }
    const w = String(f.get("waste_override") ?? "");
    if (w !== (item.waste_override ?? "")) body.waste_override = w || null;
    for (const k of ["description", "spec", "category"] as const) {
      const v = String(f.get(k) ?? "");
      if (v !== String(item[k] ?? "")) body[k] = v;
    }
    call(base, "PATCH", body);
  }
  async function loadHistory() {
    try { setHist(await api<HistoryRow[]>(`${base}/history`)); } catch (e) { setMsg(errorText(e)); }
  }
  const reviewNote = () => (document.getElementById(`note-${item.id}`) as HTMLInputElement | null)?.value ?? "";
  const sourceId = item.source_item_ids[0];

  return (
    <div className="item-editor" key={item.version}>
      <div className="row">
        <div><b>Công thức:</b> {item.formula_text || <span className="muted">chưa tính được</span>}</div>
        {item.drawing_id && <Link to={`/drawings/${item.drawing_id}?page=${item.page_no}${sourceId ? `&item=${sourceId}` : ""}`}>
          Xem vị trí trên bản vẽ (trang {item.page_no})</Link>}
      </div>
      <FlagList flags={item.flags} />
      <form onSubmit={save} className="editor-grid">
        <label>Danh mục<select name="category" defaultValue={item.category} disabled={!editable}>
          {Object.entries(CATEGORY).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        <label>Mô tả<input name="description" defaultValue={item.description} disabled={!editable} /></label>
        <label>Quy cách<input name="spec" defaultValue={item.spec} disabled={!editable} /></label>
        {module ? <>
          {module.fields.map((fl) => {
            const inp = item.inputs[fl.name];
            return <label key={fl.name}>{fl.label_vi}{fl.kind === "dim" ? ` (${item.unit_system ?? "?"})` : ""}
              <input name={`in_${fl.name}`} defaultValue={inp?.value ?? ""} disabled={!editable} aria-label={fl.label_vi}
                className={inp?.value == null ? "missing" : ""} />
              <small className={`origin origin-${inp?.origin ?? "none"}`}>{inp?.value == null ? "thiếu" : ORIGIN[inp.origin] ?? inp.origin}
                {inp?.previous_value !== undefined ? ` (trước: ${inp.previous_value ?? "—"})` : ""}{inp?.note ? ` – ${inp.note}` : ""}</small></label>;
          })}
          {module.dimensional && <label>Đơn vị kích thước<select name="unit_system" defaultValue={item.unit_system ?? ""} disabled={!editable} aria-label="Đơn vị kích thước">
            <option value="">— chưa xác định —</option><option value="mm">mm</option><option value="cm">cm</option><option value="m">m</option></select></label>}
        </> : <>
          <label>Khối lượng (nguyên văn)<input name="stated_quantity" defaultValue={item.inputs.quantity?.value ?? ""} disabled={!editable} aria-label="Khối lượng" />
            <small className={`origin origin-${item.inputs.quantity?.origin}`}>{ORIGIN[item.inputs.quantity?.origin ?? ""] ?? ""}
              {item.inputs.quantity?.raw ? ` – ô bảng: "${item.inputs.quantity.raw}"` : ""}</small></label>
          <label>Đơn vị tính<input name="stated_unit" defaultValue={item.stated_unit ?? ""} disabled={!editable} /></label>
        </>}
        <label>Hao hụt riêng (0–1)<input name="waste_override" defaultValue={item.waste_override ?? ""} placeholder={`theo quy tắc: ${item.waste_factor}`} disabled={!editable} /></label>
        {editable && <label className="wide">Lý do chỉnh sửa (bắt buộc)<input name="reason" required aria-label="Lý do chỉnh sửa" /></label>}
        {editable && <button>Lưu chỉnh sửa</button>}
      </form>
      {editable && <div className="row">
        <input id={`note-${item.id}`} placeholder="Ghi chú / lý do" aria-label="Ghi chú rà soát" />
        <button disabled={item.has_blocking || item.quantity == null} title={item.has_blocking ? "Còn lỗi chặn" : ""}
          onClick={() => call(`${base}/review`, "POST", { decision: "accept", note: reviewNote() })}>Chấp nhận</button>
        <button className="danger" onClick={() => call(`${base}/review`, "POST", { decision: "reject", note: reviewNote() })}>Loại bỏ</button>
        <button className="ghost" onClick={() => call(`${base}/review`, "POST", { decision: "reset", note: reviewNote() })}>Đặt lại</button>
        <button className="ghost" onClick={() => call(`${base}/notes`, "POST", { note: reviewNote() })}>Thêm ghi chú</button>
      </div>}
      {msg && <p className="error">{msg}</p>}
      {item.notes && <pre className="notes">{item.notes}</pre>}
      <button className="ghost" onClick={loadHistory}>Lịch sử phiên bản</button>
      {hist && <table className="hist"><thead><tr><th>v</th><th>Hành động</th><th>Khối lượng</th><th>Lý do</th><th>Thời gian</th></tr></thead>
        <tbody>{hist.map((h, i) => <tr key={i}><td>{h.version}</td><td>{ACTION[h.action] ?? h.action}</td><td>{h.quantity ?? "—"}</td>
          <td>{h.reason}</td><td>{formatDateVN(h.at)}</td></tr>)}</tbody></table>}
    </div>
  );
}
