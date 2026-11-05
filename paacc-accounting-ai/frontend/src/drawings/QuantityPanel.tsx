import { useCallback, useEffect, useState } from "react";
import { api, errorText } from "../api";
import type { QuantityResult, QuantityRunSummary } from "./types";

const STATUS_VI: Record<string, string> = { CALCULATED: "Đã tính", REQUIRES_REVIEW: "Cần kiểm tra", BLOCKED: "Bị chặn",
  CONFIRMED: "Đã xác nhận", REJECTED: "Loại bỏ", DRAFT: "Nháp" };
const UNIT: Record<string, string> = { m2: "m²", m3: "m³" };

/** Minimal 5E-2 quantity view: run the deterministic rules for the drawing and inspect results + provenance.
 *  Every number is produced by the backend Decimal engine; nothing is calculated here. */
export default function QuantityPanel({ drawingId, onShowSource }: { drawingId: string; onShowSource: (pageNo: number, geometryIds: string[]) => void }) {
  const [rows, setRows] = useState<QuantityResult[]>([]);
  const [summary, setSummary] = useState<QuantityRunSummary | null>(null);
  const [sel, setSel] = useState<QuantityResult | null>(null);
  const [msg, setMsg] = useState("");
  const load = useCallback(() => api<QuantityResult[]>(`/drawings/${drawingId}/quantity-results`).then(setRows).catch((e) => setMsg(errorText(e))),
    [drawingId]);
  useEffect(() => { load(); }, [load]);
  async function run() {
    try {
      setSummary(await api<QuantityRunSummary>(`/drawings/${drawingId}/quantities/run`, { method: "POST", body: JSON.stringify({}) }));
      setMsg(""); load();
    } catch (e) { setMsg(errorText(e)); }
  }
  async function open(id: string) {
    try { setSel(await api<QuantityResult>(`/quantity-results/${id}`)); } catch (e) { setMsg(errorText(e)); }
  }
  return (
    <section aria-label="Khối lượng">
      <h3>Khối lượng (5E – quy tắc tất định)</h3>
      <p className="muted">Chỉ cấu kiện ĐÃ XÁC NHẬN và phép đo 5B ĐÃ XÁC NHẬN mới cho ra số. Chưa phải BOQ.</p>
      <button onClick={run}>Tính khối lượng</button>
      {summary && <p aria-label="Tóm tắt">Đã quét {summary.components_scanned} cấu kiện · khớp {summary.rules_matched} quy tắc ·
        tính được {summary.calculated} · cần kiểm tra {summary.requires_review} · bị chặn {summary.blocked} · chưa xác nhận {summary.not_confirmed}
        · biểu diễn bỏ qua {summary.representations_skipped} · thiếu tham số {summary.skipped_missing_parameter}</p>}
      <div className="scroll"><table><thead><tr><th>Cấu kiện</th><th>Loại</th><th>Quy tắc</th><th>Công thức</th><th>Khối lượng</th>
        <th>ĐV</th><th>Trạng thái</th><th>Trang</th><th>Nguồn</th></tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={r.id} data-qty={r.id} onClick={() => open(r.id)} className={sel?.id === r.id ? "sel" : ""}>
            <td>{r.component_description || r.component_id.slice(0, 8)}</td><td>{r.component_type}</td><td>{r.rule_code ?? r.calculation_method}</td>
            <td>{r.formula_trace || r.formula}</td><td>{r.quantity_value ?? "—"}</td><td>{UNIT[r.unit] ?? r.unit}</td>
            <td>{STATUS_VI[r.status] ?? r.status}</td><td>{r.page_no ?? ""}</td><td>{r.input_measurement_ids.length} phép đo</td></tr>))}
          {rows.length === 0 && <tr><td colSpan={9}>Chưa có kết quả khối lượng</td></tr>}</tbody></table></div>
      {sel?.provenance && <div className="calib" aria-label="Chi tiết khối lượng">
        <b>{sel.provenance.component.type}</b> – {sel.provenance.component.description} ({sel.provenance.component.status})
        <div>Tính toán: {sel.formula} → <b>{sel.formula_trace || "chưa có giá trị"}</b> · {sel.calculation_method} · làm tròn {sel.rounding_rule}/{sel.precision}
          {sel.raw_value ? ` · giá trị thô ${sel.raw_value}` : ""}</div>
        {sel.reason && <div className="error">{sel.reason}</div>}
        <div>Phép đo: {sel.provenance.measurements.map((m) => `${m.kind} = ${m.value_real ?? "—"} ${m.real_unit ?? ""} (${m.status})`).join(" · ")}</div>
        <div>Tham số: {Object.entries(sel.parameters).map(([k, v]) => `${k} = ${v.value ?? v.measurement_id} ${v.unit ?? ""} [${v.source_type ?? "phép đo"}: ${v.source_reference ?? ""}${v.entered_by ? `, ${v.entered_by}` : ""}]`).join(" · ") || "—"}</div>
        <div>Hình học: {sel.provenance.geometry_ids.length} đối tượng · Chữ: {sel.provenance.texts.map((t) => t.original_text).join(", ") || "—"} ·
          Liên kết 5C: {sel.provenance.association_ids.length} · Trang {sel.provenance.drawing.page_no}</div>
        <div className="muted">Audit: {sel.provenance.audit.map((a) => `${a.action} (${a.user ?? ""})`).join(", ")}</div>
        <button className="ghost" onClick={() => onShowSource(sel.provenance!.drawing.page_no, sel.provenance!.geometry_ids)}>↗ Xem nguồn trên bản vẽ</button>
      </div>}
      {msg && <p className="error">{msg}</p>}
    </section>
  );
}
