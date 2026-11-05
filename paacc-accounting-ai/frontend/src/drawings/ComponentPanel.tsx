import { useEffect, useState } from "react";
import { api, errorText } from "../api";
import { COMP_COLOR, COMP_STATUS_VI, EVIDENCE_VI, VIEW_CTX_VI } from "./labels";
import type { Component, ComponentEvidence, ComponentTypeDef } from "./types";

/** One recognised component: evidence (separate scores), sources, review actions. Quantities shown are 5B measurements
 *  referenced by the component – nothing is computed or editable here. */
export default function ComponentPanel({ comp, onChanged, onViewSource }: {
  comp: Component; onChanged: (c: Component) => void; onViewSource: (geometryIds: string[]) => void;
}) {
  const [ev, setEv] = useState<ComponentEvidence | null>(null);
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState("");
  const [edit, setEdit] = useState(false);
  const [types, setTypes] = useState<ComponentTypeDef[]>([]);
  const [form, setForm] = useState({ component_type: comp.component_type, component_subtype: comp.component_subtype ?? "",
    description: comp.description, specification: comp.specification, material: comp.material });
  useEffect(() => { setEv(null); api<ComponentEvidence>(`/components/${comp.id}/evidence`).then(setEv).catch((e) => setMsg(errorText(e))); },
    [comp.id, comp.status]);
  async function act(action: string, body: Record<string, unknown> = { note }) {
    try {
      const r = await api<Component>(`/components/${comp.id}/${action}`, { method: "POST", body: JSON.stringify(body) });
      setMsg(""); setEdit(false); onChanged(r);
    } catch (e) { setMsg(errorText(e)); }
  }
  async function openEdit() {
    setEdit(!edit);
    if (!types.length) api<ComponentTypeDef[]>("/component-types").then(setTypes).catch((e) => setMsg(errorText(e)));
  }
  const fmt = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v * 100)}%`);
  return (
    <div className="calib" aria-label="Cấu kiện">
      <b>{comp.name || comp.component_type}</b> <span className="muted">({comp.component_type}{comp.component_subtype ? ` / ${comp.component_subtype}` : ""})</span>{" "}
      <span className="badge" style={{ background: COMP_COLOR[comp.status] }}>{COMP_STATUS_VI[comp.status] ?? comp.status}</span>
      <div>Mô tả: {comp.description || "—"} · Quy cách: {comp.specification || "—"} · Vật liệu: {comp.material || "—"}</div>
      <div>Độ tin cậy: {fmt(comp.recognition_confidence)} ({comp.confidence_band}) – <span className="muted">mức bằng chứng, không phải xác nhận</span></div>
      <table aria-label="Bằng chứng"><tbody>
        {EVIDENCE_VI.map(([k, label]) => <tr key={k}><td>{label}</td><td>{fmt(comp.scores[k])}</td></tr>)}
        <tr><td>Liên kết chữ–hình học (5C)</td><td>{comp.source_association_ids.length}</td></tr>
      </tbody></table>
      {ev?.detail.comparisons?.map((c, i) => (
        <div key={i} className={ev.detail.conflicts?.length ? "error" : "muted"}>Ghi: {c.stated} {c.unit} · Hình học: {c.measured} {c.unit} · Chênh: {c.difference} {c.unit}</div>))}
      {ev && ev.measurements.length > 0 && <div aria-label="Phép đo tham chiếu">Phép đo (5B): {ev.measurements.map((m) =>
        `${m.kind} = ${m.value_real ?? `${m.value_paper} ${m.paper_unit} (chưa có tỷ lệ)`}${m.value_real && m.real_unit && m.real_unit !== "count" ? ` ${m.real_unit}` : ""}`).join(" · ")}</div>}
      {ev?.repeat_group && <div>Dãy lặp: {ev.repeat_group.pattern_status} · {ev.repeat_group.gaps_pt.length + 1} ký hiệu thấy được (không nội suy phần bị che)</div>}
      {ev?.relations.length ? <div className="muted">Quan hệ: {[...new Set(ev.relations.map((r) => r.type))].join(", ")}</div> : null}
      {comp.representation_of_id && <div className="muted">Biểu diễn ({VIEW_CTX_VI[comp.view_context]}) của cấu kiện khác – không tính riêng</div>}
      {(ev?.detail.reasons ?? []).concat(ev?.detail.conflicts ?? [], ev?.detail.ambiguous ?? []).map((r, i) => <div key={i} className="muted">• {r}</div>)}
      <div className="muted">Nguồn: trang {comp.page_no} ({VIEW_CTX_VI[comp.view_context] ?? comp.view_context}) · vùng [{comp.bbox.map((v) => Math.round(v)).join(", ")}] ·
        {comp.source_text_ids.length} chữ, {comp.source_geometry_ids.length} hình học, {comp.source_measurement_ids.length} phép đo · quy tắc {comp.recognition_rule}</div>
      <div className="row">
        {comp.status === "CANDIDATE" && <button onClick={() => act("review")}>Bắt đầu review</button>}
        <button onClick={() => act("confirm")}>✓ Xác nhận</button>
        <button className="danger" onClick={() => act("reject")}>✕ Loại bỏ</button>
        <button className="ghost" onClick={() => act("ambiguous")}>⚠ Mơ hồ</button>
        <button className="ghost" onClick={openEdit}>✎ Phân loại lại</button>
        <button className="ghost" onClick={() => onViewSource(comp.source_geometry_ids)}>↗ Xem nguồn</button>
      </div>
      {edit && <div className="row" aria-label="Phân loại lại">
        <select aria-label="Loại cấu kiện" value={form.component_type} onChange={(e) => setForm({ ...form, component_type: e.target.value })}>
          {(types.length ? types : [{ code: comp.component_type, name_vi: comp.name, group: "", active: true }]).filter((t) => t.active)
            .map((t) => <option key={t.code} value={t.code}>{t.code} – {t.name_vi}</option>)}</select>
        <input aria-label="Phân loại phụ" placeholder="Phân loại phụ" value={form.component_subtype} onChange={(e) => setForm({ ...form, component_subtype: e.target.value })} />
        <input aria-label="Mô tả" placeholder="Mô tả" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        <input aria-label="Quy cách" placeholder="Quy cách" value={form.specification} onChange={(e) => setForm({ ...form, specification: e.target.value })} />
        <input aria-label="Vật liệu" placeholder="Vật liệu" value={form.material} onChange={(e) => setForm({ ...form, material: e.target.value })} />
        <button onClick={() => act("reclassify", { ...form, component_subtype: form.component_subtype || null, reason: note })}>Lưu</button>
        <span className="muted">Không sửa khối lượng ở đây – số đo lấy từ Measurement Engine</span>
      </div>}
      <input value={note} onChange={(e) => setNote(e.target.value)} aria-label="Ghi chú cấu kiện"
        placeholder="Lý do / ghi chú (bắt buộc khi loại bỏ, mơ hồ, sửa; khi xác nhận cấu kiện xung đột/mơ hồ/bị che)" />
      {msg && <p className="error">{msg}</p>}
    </div>
  );
}
