import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import DepartmentPanel from "./DepartmentPanel";
import { ErrorBoundary } from "./ErrorBoundary";
import Office2D from "./Office2D";
import { STATUS_META } from "./status";
import type { ViewRequest } from "./scene/OfficeScene";
import { useOfficeData } from "./useOfficeData";
import { hasWebGL } from "./webgl";

// three.js / R3F are loaded only when the 3D view is opened.
const OfficeScene = lazy(() => import("./scene/OfficeScene"));

export const VIEW_KEY = "paacc_view";
type ViewInit = { kind: "overview" } | { kind: "focus"; code: string };

export default function OfficePage({ mode, pollMs = 10_000 }: { mode: "3d" | "2d"; pollMs?: number }) {
  const { code } = useParams();
  const navigate = useNavigate();
  const { departments, error, reload } = useOfficeData(pollMs);
  const webgl = useMemo(() => mode === "3d" && hasWebGL(), [mode]);
  const base = mode === "3d" ? "/office" : "/dashboard";
  const [view, setView] = useState<ViewRequest>({ id: 0, ...(code ? { kind: "focus", code } : { kind: "overview" }) } as ViewRequest);
  const request = (r: ViewInit | { kind: "zoom"; factor: number } | { kind: "rotate"; angle: number }) =>
    setView((v) => ({ ...r, id: v.id + 1 }) as ViewRequest);

  useEffect(() => { try { sessionStorage.setItem(VIEW_KEY, mode); } catch { /* storage unavailable */ } }, [mode]);
  useEffect(() => { request(code ? { kind: "focus", code } : { kind: "overview" }); }, [code]);

  const select = (c: string) => navigate(`${base}/${c}`);
  const other = mode === "3d" ? "/dashboard" : "/office";
  const fallback2D = departments && <Office2D departments={departments} selected={code} onSelect={select} />;

  return (
    <div className="office">
      <div className="toolbar" role="toolbar" aria-label="Điều hướng văn phòng">
        <button onClick={() => navigate(base)}>Toàn cảnh</button>
        <select aria-label="Chọn phòng ban" value={code ?? ""} onChange={(e) => (e.target.value ? select(e.target.value) : navigate(base))}>
          <option value="">— Chọn phòng ban —</option>
          {departments?.map((d) => <option key={d.code} value={d.code}>{d.name_vi}</option>)}
        </select>
        {mode === "3d" && webgl && <>
          <button aria-label="Phóng to" onClick={() => request({ kind: "zoom", factor: 1.3 })}>＋</button>
          <button aria-label="Thu nhỏ" onClick={() => request({ kind: "zoom", factor: 1 / 1.3 })}>－</button>
          <button aria-label="Xoay trái" onClick={() => request({ kind: "rotate", angle: Math.PI / 4 })}>⟲</button>
          <button aria-label="Xoay phải" onClick={() => request({ kind: "rotate", angle: -Math.PI / 4 })}>⟳</button>
        </>}
        <Link className="btn" to={code ? `${other}/${code}` : other}>{mode === "3d" ? "Chế độ 2D" : "Văn phòng 3D"}</Link>
        {mode === "3d" && <Link className="btn" to="/dashboard">Bảng điều khiển</Link>}
        <span className="legend">{Object.entries(STATUS_META).map(([k, m]) => <span key={k}><i className="dot" style={{ background: m.color }} />{m.label}</span>)}</span>
      </div>
      {error && <p className="error">{error}</p>}
      <div className={`office-body${code ? " with-panel" : ""}`}>
        <div className={mode === "3d" && webgl ? "canvas-wrap" : "grid-wrap"}>
          {!departments ? <p>Đang tải dữ liệu văn phòng…</p>
            : mode === "3d" && webgl ? (
              <ErrorBoundary fallback={<><p className="error">Không khởi tạo được 3D – hiển thị dạng 2D.</p>{fallback2D}</>}>
                <Suspense fallback={<p>Đang tải văn phòng 3D…</p>}>
                  <OfficeScene departments={departments} selected={code} onSelect={select} view={view} />
                </Suspense>
              </ErrorBoundary>)
            : <>{mode === "3d" && <p className="muted">Trình duyệt không hỗ trợ WebGL – hiển thị dạng 2D.</p>}{fallback2D}</>}
        </div>
        {code && <DepartmentPanel code={code} onClose={() => navigate(base)} onChanged={reload} pollMs={pollMs} />}
      </div>
    </div>
  );
}
