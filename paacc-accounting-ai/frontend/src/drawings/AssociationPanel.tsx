import { useState } from "react";
import { api, errorText } from "../api";
import { ASSOC_COLOR, ASSOC_STATUS_VI, ASSOC_TYPE_VI, TEXT_TYPE_VI } from "./labels";
import type { Association, TextBlock } from "./types";

/** Ranked candidates of ONE text block (or the texts linked to ONE geometry) + engineer review actions.
 *  Numbers (text value, measured value, difference) come from the backend's Decimal engine; nothing is computed here. */
export default function AssociationPanel({ block, geometryId, blocks, assocs, picking, onPick, onChanged, onSelectGeo }: {
  block?: TextBlock; geometryId?: string; blocks: TextBlock[]; assocs: Association[]; picking?: string;
  onPick: (assocId: string | undefined, reason: string) => void; onChanged: (a: Association) => void; onSelectGeo: (id: string) => void;
}) {
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState("");
  const byId = new Map(blocks.map((b) => [b.id, b]));
  const rows = block ? assocs.filter((a) => a.text_block_id === block.id).sort((a, b) => a.rank - b.rank)
    : assocs.filter((a) => a.geometry_id === geometryId);
  async function act(a: Association, action: "confirm" | "reject" | "mark-ambiguous") {
    try {
      const r = await api<Association>(`/associations/${a.id}/${action}`, { method: "POST", body: JSON.stringify({ note }) });
      setMsg(""); onChanged(r);
    } catch (e) { setMsg(errorText(e)); }
  }
  return (
    <div className="calib" aria-label="Liên kết chữ – hình học">
      {block ? <>
        <b>“{block.original_text}”</b> <span className="badge">{TEXT_TYPE_VI[block.text_type] ?? block.text_type}</span>
        {block.normalized_text !== block.original_text && <div className="muted">Chuẩn hoá: {block.normalized_text}</div>}
        {block.flags.length > 0 && <div className="error">Cờ: {block.flags.join(", ")}</div>}
        {block.encoding && <div className="muted">Nghi mã hoá cũ ({block.encoding.encoding ?? "?"}) – giữ nguyên văn bản gốc, không tự chuyển đổi</div>}
        {block.repeat_count > 1 && <div className="muted">Chữ lặp {block.repeat_count} lần trên trang</div>}
      </> : <b>Chữ gắn với hình học {geometryId?.slice(0, 8)}</b>}
      {rows.length === 0 && <p className="muted">Không có liên kết{block && ["TABLE", "TITLE", "SCALE", "REVISION"].includes(block.text_type) ? " (chữ trong bảng/khung tên không được liên kết)" : ""}</p>}
      <ol className="list">{rows.map((a) => (
        <li key={a.id} data-assoc={a.id}>
          <span className="badge" style={{ background: ASSOC_COLOR[a.status] }}>{ASSOC_STATUS_VI[a.status] ?? a.status}</span>{" "}
          {block ? <>#{a.rank} {ASSOC_TYPE_VI[a.association_type] ?? a.association_type}{" "}
            <button className="ghost" onClick={() => onSelectGeo(a.geometry_id)}>hình học {a.geometry_id.slice(0, 8)}</button></>
            : <>“{byId.get(a.text_block_id)?.original_text ?? a.text_block_id.slice(0, 8)}” – {ASSOC_TYPE_VI[a.association_type]}</>}
          {" "}· điểm {Math.round(a.confidence * 100)}% · cách {a.distance ?? "—"} pt{a.angle_difference != null ? ` · lệch góc ${a.angle_difference}°` : ""}
          {a.origin !== "rule" && <span className="muted"> · {a.origin === "engineer" ? "kỹ sư" : "AI gợi ý"}</span>}
          {a.duplicate_of && <span className="muted"> · chữ lặp (không đo riêng)</span>}
          {a.text_value != null && (
            <div className={a.status === "CONFLICT" ? "error" : "muted"} aria-label="So sánh chữ – hình học">
              Chữ: {a.text_value} m · Hình học: {a.measured_value ?? "chưa đo (chưa có tỷ lệ xác nhận)"}{a.measured_value != null ? " m" : ""}
              {a.difference != null && ` · Chênh: ${a.difference} m`}</div>)}
          <div className="muted">{a.reason}</div>
          {a.history.length > 0 && <div className="muted">Đổi hình học: {a.history.map((h) => `${h.old_geometry_id.slice(0, 8)}→${h.new_geometry_id.slice(0, 8)} (${h.user}: ${h.reason})`).join("; ")}</div>}
          {a.status !== "REJECTED" && <div className="row">
            <button onClick={() => act(a, "confirm")}>Chấp nhận</button>
            <button className="danger" onClick={() => act(a, "reject")}>Loại bỏ</button>
            <button className="ghost" onClick={() => act(a, "mark-ambiguous")}>Đánh dấu mơ hồ</button>
            <button className="ghost" onClick={() => onPick(picking === a.id ? undefined : a.id, note)}>
              {picking === a.id ? "Huỷ chọn" : "Chọn hình học khác"}</button>
          </div>}
        </li>))}</ol>
      {picking && <p className="muted">Bấm vào một đối tượng hình học trên bản vẽ để gán lại (cần lý do ở ô ghi chú).</p>}
      <input value={note} onChange={(e) => { setNote(e.target.value); if (picking) onPick(picking, e.target.value); }}
        placeholder="Lý do / ghi chú (bắt buộc khi loại bỏ, xung đột, đổi hình học)" aria-label="Ghi chú liên kết" />
      {msg && <p className="error">{msg}</p>}
    </div>
  );
}
