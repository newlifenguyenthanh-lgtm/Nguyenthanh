import { useCallback, useEffect, useState } from "react";
import { BrowserRouter, NavLink, Navigate, Route, Routes } from "react-router-dom";
import { Me, api, auth } from "./api";
import { ROLE } from "./labels";
import OfficePage, { VIEW_KEY } from "./office/OfficePage";
import DrawingDetailPage from "./drawings/DrawingDetailPage";
import DrawingsPage from "./drawings/DrawingsPage";
import AuditLog from "./pages/AuditLog";
import Contracts from "./pages/Contracts";
import Documents from "./pages/Documents";
import Login from "./pages/Login";
import Projects from "./pages/Projects";

function preferredHome(): string {
  try { return sessionStorage.getItem(VIEW_KEY) === "2d" ? "/dashboard" : "/office"; } catch { return "/office"; }
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to={preferredHome()} replace />} />
      <Route path="/office" element={<OfficePage mode="3d" />} />
      <Route path="/office/:code" element={<OfficePage mode="3d" />} />
      <Route path="/dashboard" element={<OfficePage mode="2d" />} />
      <Route path="/dashboard/:code" element={<OfficePage mode="2d" />} />
      <Route path="/projects" element={<main><Projects /></main>} />
      <Route path="/documents" element={<main><Documents /></main>} />
      <Route path="/contracts" element={<main><Contracts /></main>} />
      <Route path="/audit" element={<main><AuditLog /></main>} />
      <Route path="/drawings" element={<main><DrawingsPage /></main>} />
      <Route path="/drawings/:id" element={<DrawingDetailPage />} />
      <Route path="*" element={<main><p>Không tìm thấy trang.</p></main>} />
    </Routes>
  );
}

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);
  const refresh = useCallback(() => {
    if (!auth.token) { setMe(null); setReady(true); return; }
    api<Me>("/auth/me").then(setMe).catch(() => { auth.set(null); setMe(null); }).finally(() => setReady(true));
  }, []);
  useEffect(refresh, [refresh]);
  if (!ready) return null;
  if (!me) return <Login onDone={refresh} />;
  return (
    <BrowserRouter>
      <div className="app">
        <header><strong>PAACC Construction AI</strong>
          <nav>
            <NavLink to="/dashboard">Bảng điều khiển</NavLink><NavLink to="/office">Văn phòng 3D</NavLink>
            <NavLink to="/projects">Dự án</NavLink><NavLink to="/documents">Tài liệu</NavLink><NavLink to="/drawings">Bản vẽ</NavLink>
            <NavLink to="/contracts">Hợp đồng</NavLink><NavLink to="/audit">Nhật ký</NavLink>
          </nav>
          <span>{me.full_name || me.email} · {ROLE[me.role] ?? me.role} <button onClick={() => { auth.set(null); setMe(null); }}>Đăng xuất</button></span>
        </header>
        <AppRoutes />
      </div>
    </BrowserRouter>
  );
}
