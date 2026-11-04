import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import DepartmentPanel from "./DepartmentPanel";
import { agent, dept, mockFetch } from "./testData";

const task = { id: "t1", agent_key: "quantity_surveyor", department_code: "engineering_qs", title: "Bóc tách KC-01",
  status: "waiting_approval", requires_approval: true, error_message: "", output_summary: "", created_at: "2026-11-04T10:00:00Z", finished_at: null };

describe("department panel", () => {
  it("shows agents, employees, tasks, metrics and the module link from backend data", async () => {
    const d = dept("engineering_qs", 2, {
      status: "waiting_approval", agents: [agent("pdf_drawing", "idle"), agent("quantity_surveyor", "waiting_approval", { current_task: task })],
      employees: [{ user_id: "u1", name: "Nguyễn Văn A", role: "site_manager", job_title: "Kỹ sư QS" }],
      metrics: [{ key: "drawing_docs", label_vi: "Bản vẽ", value: "4" }],
      module: { route: "/documents?kind=drawing", status: "partial", phase: 4 }, recent_tasks: [task], recent_documents: [],
    });
    const calls: { url: string; method: string }[] = [];
    vi.stubGlobal("fetch", vi.fn(mockFetch({ "/office/departments/engineering_qs": d, "POST /ai-tasks/t1/approve": { ...task, status: "completed" } }, calls)));
    render(<MemoryRouter><DepartmentPanel code="engineering_qs" onClose={() => {}} pollMs={0} /></MemoryRouter>);
    await screen.findByText("Agent quantity_surveyor");
    expect(screen.getByText("Nguyễn Văn A")).toBeTruthy();
    expect(screen.getByText("Mở phân hệ").getAttribute("href")).toBe("/documents?kind=drawing");
    expect(screen.getAllByText(/Bóc tách KC-01/).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByText("Phê duyệt"));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === "/ai-tasks/t1/approve")).toBe(true));
  });

  it("states honestly when a module is not built yet", async () => {
    vi.stubGlobal("fetch", vi.fn(mockFetch({ "/office/departments/cad_design": dept("cad_design", 3, { recent_tasks: [], recent_documents: [] }) })));
    render(<MemoryRouter><DepartmentPanel code="cad_design" onClose={() => {}} pollMs={0} /></MemoryRouter>);
    expect(await screen.findByText(/Phân hệ chưa phát triển – dự kiến Phase 5/)).toBeTruthy();
    expect(screen.queryByText("Mở phân hệ")).toBeNull();
    expect(screen.getByText(/Chưa có dữ liệu/)).toBeTruthy();
  });
});
