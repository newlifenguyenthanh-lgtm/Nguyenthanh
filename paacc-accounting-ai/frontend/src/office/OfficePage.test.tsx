import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import OfficePage from "./OfficePage";
import { dept, mockFetch, tenDepartments } from "./testData";

function Where() { return <div data-testid="where">{useLocation().pathname}</div>; }

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/office" element={<OfficePage mode="3d" pollMs={0} />} />
        <Route path="/office/:code" element={<OfficePage mode="3d" pollMs={0} />} />
        <Route path="/dashboard" element={<OfficePage mode="2d" pollMs={0} />} />
        <Route path="/dashboard/:code" element={<OfficePage mode="2d" pollMs={0} />} />
      </Routes>
      <Where />
    </MemoryRouter>);
}

describe("office page", () => {
  it("2D dashboard: clicking a department opens its workspace route and panel", async () => {
    vi.stubGlobal("fetch", vi.fn(mockFetch({ "/office/overview": { departments: tenDepartments() },
      "/office/departments/bidding": dept("bidding", 1, { recent_tasks: [], recent_documents: [] }) })));
    renderAt("/dashboard");
    fireEvent.click(await screen.findByLabelText("Phòng ban Phòng bidding"));
    expect(screen.getByTestId("where").textContent).toBe("/dashboard/bidding");
    expect(await screen.findByLabelText("Chi tiết Phòng bidding")).toBeTruthy();
    // toggle keeps the selected department
    expect(screen.getByText("Văn phòng 3D").getAttribute("href")).toBe("/office/bidding");
    fireEvent.click(screen.getByText("Toàn cảnh"));
    expect(screen.getByTestId("where").textContent).toBe("/dashboard");
  });

  it("3D route falls back to 2D when WebGL is unavailable (jsdom) and keeps navigation", async () => {
    vi.stubGlobal("fetch", vi.fn(mockFetch({ "/office/overview": { departments: tenDepartments() } })));
    renderAt("/office");
    expect(await screen.findByText(/không hỗ trợ WebGL/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Chọn phòng ban"), { target: { value: "estimation" } });
    expect(screen.getByTestId("where").textContent).toBe("/office/estimation");
    expect(screen.getByText("Bảng điều khiển").getAttribute("href")).toBe("/dashboard");
  });

  it("shows the backend error instead of fake data", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "Không đủ quyền" }), { status: 403 })));
    renderAt("/dashboard");
    expect(await screen.findByText("Không đủ quyền")).toBeTruthy();
  });
});
