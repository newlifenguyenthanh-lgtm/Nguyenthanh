import { useEffect, useState } from "react";
import { api, errorText } from "../api";
import type { GeometryPrim } from "./types";

export const GEO_STATUS: Record<string, string> = { extracted: "Trích xuất", confirmed: "Đã xác nhận", rejected: "Loại bỏ", ambiguous: "Không rõ – cần xem lại" };
export const GEO_COLOR: Record<string, string> = { extracted: "#1f6feb", confirmed: "#27ae60", rejected: "#eb5757", ambiguous: "#f2994a" };
const KIND: Record<string, string> = { line: "Đoạn thẳng", polyline: "Đường gấp khúc", polygon: "Đa giác", rect: "Hình chữ nhật",
  fill_region: "Vùng tô", curve: "Đường cong", circle: "Đường tròn" };

/** Measurement + provenance of one vector primitive. Values come from the backend's Decimal engine. */
export default function GeometryPanel({ id, onChanged }: { id: string; onChanged: (g: GeometryPrim) => void }) {
  const [g, setG] = useState<GeometryPrim | null>(null);
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState("");
  useEffect(() => { setG(null); api<GeometryPrim>(`/geometry/${id}`).then(setG).catch((e) => setMsg(errorText(e))); }, [id]);
  async function review(status: string) {
    try {
      const r = await api<GeometryPrim>(`/geometry/${id}`, { method: "PATCH", body: JSON.stringify({ status, note }) });
      setG(r); setMsg(""); onChanged(r);
    } catch (e) { setMsg(errorText(e)); }
  }
  if (!g) return <div className="calib">{msg || "Đang tải…"}</div>;
  return (
    <div className="calib" aria-label="Chi tiết hình học">
      <b>{KIND[g.kind] ?? g.kind}</b> <span className="badge" style={{ background: GEO_COLOR[g.status] }}>{GEO_STATUS[g.status] ?? g.status}</span>
      <div>Chiều dài: {g.length_pt ?? "—"} pt · {g.length_paper_mm ?? "—"} mm trên giấy{g.approximate ? " (xấp xỉ đường cong)" : ""}</div>
      <div>Chiều dài thật: {g.length_real_m ? `${g.length_real_m} m (${g.real_basis})` : <span className="muted">{g.real_basis}</span>}</div>
      {g.area_pt2 && <div>Diện tích: {g.area_pt2} pt²</div>}
      <div className="muted">Nguồn: path #{g.source.path_index}, mục #{g.source.item_index}{g.derived_from ? ` · suy ra từ ${g.derived_from}` : ""}
        {g.layer ? ` · layer ${g.layer}` : ""} · mã {g.id.slice(0, 8)}</div>
      {g.flags.length > 0 && <div className="error">Cờ: {g.flags.join(", ")}</div>}
      {g.review_note && <div className="muted">Ghi chú: {g.review_note}</div>}
      <div className="row">
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Lý do / ghi chú" aria-label="Ghi chú hình học" />
        <button onClick={() => review("confirmed")}>Xác nhận</button>
        <button className="danger" onClick={() => review("rejected")}>Loại bỏ</button>
        <button className="ghost" onClick={() => review("ambiguous")}>Không rõ</button>
      </div>
      {msg && <p className="error">{msg}</p>}
    </div>
  );
}
