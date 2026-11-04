import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, errorText } from "../api";
import { formatDateVN } from "../format";
import { BOQ_STATUS, BOQ_STATUS_COLOR } from "./labels";
import type { Boq } from "./types";

export default function BoqListPage() {
  const [rows, setRows] = useState<Boq[]>([]);
  const [err, setErr] = useState("");
  useEffect(() => { api<Boq[]>("/boqs").then(setRows).catch((e) => setErr(errorText(e))); }, []);
  return (
    <section>
      <h2>Bảng khối lượng (BOQ)</h2>
      <p className="muted">Tạo BOQ nháp từ trang chi tiết bản vẽ đã phân tích.</p>
      {err && <p className="error">{err}</p>}
      <div className="scroll"><table><thead><tr><th>Tên</th><th>Phiên bản</th><th>Trạng thái</th><th>Hạng mục</th><th>Chờ rà soát</th><th>Lỗi chặn</th><th>Ngày tạo</th></tr></thead>
        <tbody>{rows.map((b) => <tr key={b.id}><td><Link to={`/boqs/${b.id}`}>{b.title}</Link></td><td>v{b.version_no}</td>
          <td><span className="badge" style={{ background: BOQ_STATUS_COLOR[b.status] }}>{BOQ_STATUS[b.status] ?? b.status}</span></td>
          <td>{b.item_count}</td><td>{b.review_counts.pending ?? 0}</td><td>{b.blocking_count}</td><td>{formatDateVN(b.created_at)}</td></tr>)}
          {rows.length === 0 && <tr><td colSpan={7}>Chưa có BOQ</td></tr>}</tbody></table></div>
    </section>
  );
}
