import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DrawingDetailPage from "./DrawingDetailPage";
import DrawingsPage from "./DrawingsPage";
import type { DrawingDetail, Item } from "./types";

// Synthetic fixtures only.
const page = {
  page_no: 1, width_pt: 1000, height_pt: 500, rotation: 0, kind: "vector", text_chars: 400, ocr_used: false, ocr_engine: null,
  ocr_mean_confidence: null, warnings: [], drawing_number: "KC-01", title: "MẶT BẰNG KẾT CẤU", revision: "A",
  disciplines: [{ value: "structural", basis: "title", confidence: 0.9 }], view_types: [{ value: "plan", basis: "title", confidence: 0.9 }],
  scale_candidates: [{ ratio: 100, labeled: true, item_id: "t9", raw: "1:100", confidence: 0.9 }], scale_status: "unverified", scale_ratio: null,
  units_candidates: [{ unit: "mm", item_id: "t10", raw: "mm", confidence: 0.9 }], units_status: "unverified", units: null, calibrated_at: null,
};
const drawing: DrawingDetail = {
  id: "d1", document_id: "doc1", version_no: 1, filename: "kc.pdf", status: "processed", page_count: 1, error_code: "", error_message: "",
  duplicate_of_drawing_id: null, processed_at: "2026-11-04T10:00:00Z", project_id: null, document_title: "Bản vẽ KC",
  findings: [{ type: "revision", severity: "warning", relation: "conflict_same_revision_different_content", drawing_number: "KC-01",
    this_revision: "A", other_revision: "A", other_drawing_id: "d0" }],
  pages: [page], item_counts: { dimension: 1, text: 5 },
};
const items: Item[] = [{ id: "i1", page_no: 1, kind: "dimension", text: "300x600", bbox: [100, 50, 200, 75], source: "analysis",
  confidence: 0.8, data: { type: "section", values: ["300", "600"], unit: null, flags: ["unit_not_stated"], from_source: "text" } }];

let calls: { url: string; method: string; body?: string }[];
beforeEach(() => {
  calls = [];
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: () => {} }));
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input).replace("/api/v1", "");
    const method = init?.method ?? "GET";
    calls.push({ url, method, body: typeof init?.body === "string" ? init.body : undefined });
    const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
    if (url.includes("/image")) return new Response(new Blob(["png"]), { status: 200 });
    if (url === "/drawings/d1") return json(drawing);
    if (url.startsWith("/drawings/d1/items")) return json(items);
    if (url.endsWith("/calibration")) return json({ ...page, scale_status: "confirmed", scale_ratio: 100, warnings: [] });
    if (url === "/drawings" && method === "GET") return json([]);
    if (url === "/projects") return json([]);
    if (url === "/documents" && method === "POST") return json({ id: "doc9" }, 201);
    if (url === "/drawings" && method === "POST") return json({ ...drawing, id: "d9" }, 201);
    return json({ detail: "not found" }, 404);
  }));
});

function Where() { return <div data-testid="where">{useLocation().pathname}</div>; }

describe("drawing inspector", () => {
  it("shows detected-but-unconfirmed scale, findings and items with source boxes", async () => {
    render(<MemoryRouter initialEntries={["/drawings/d1"]}><Routes><Route path="/drawings/:id" element={<DrawingDetailPage />} /></Routes></MemoryRouter>);
    expect(await screen.findByText(/KC-01 – Rev A/)).toBeTruthy();
    expect(screen.getAllByText(/Phát hiện – chưa xác nhận/).length).toBe(2);
    expect(screen.getByText(/XUNG ĐỘT/)).toBeTruthy();
    const box = await screen.findByLabelText("Vị trí 300x600");
    // bbox [100,50,200,75] on a 1000x500 pt page -> 10% / 10% / 10% / 5%
    expect(box.style.left).toBe("10%"); expect(box.style.top).toBe("10%");
    expect(box.style.width).toBe("10%"); expect(box.style.height).toBe("5%");
    expect(screen.getByText("Không ghi đơn vị")).toBeTruthy();
    expect(screen.getByText("300 × 600 (chưa rõ đơn vị)")).toBeTruthy();
    fireEvent.click(screen.getByText("300x600"));
    expect(box.className).toContain("sel");
  });

  it("sends an explicit human calibration", async () => {
    render(<MemoryRouter initialEntries={["/drawings/d1"]}><Routes><Route path="/drawings/:id" element={<DrawingDetailPage />} /></Routes></MemoryRouter>);
    await screen.findByText(/KC-01 – Rev A/);
    fireEvent.change(screen.getByLabelText("Đơn vị"), { target: { value: "mm" } });
    fireEvent.click(screen.getByText("Xác nhận tỷ lệ/đơn vị"));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/pages/1/calibration"))).toBe(true));
    const body = JSON.parse(calls.find((c) => c.url.endsWith("/calibration"))!.body!);
    expect(body).toEqual({ scale_ratio: 100, not_to_scale: false, units: "mm", note: "" });
  });
});

describe("drawing upload", () => {
  it("uploads the PDF as a drawing document, starts analysis and opens the result", async () => {
    render(<MemoryRouter initialEntries={["/drawings"]}><Routes><Route path="/drawings" element={<DrawingsPage />} />
      <Route path="/drawings/:id" element={<div>detail</div>} /></Routes><Where /></MemoryRouter>);
    fireEvent.change(screen.getByPlaceholderText("Tên bản vẽ"), { target: { value: "KC" } });
    fireEvent.change(screen.getByLabelText("Tệp PDF"), { target: { files: [new File(["%PDF"], "kc.pdf", { type: "application/pdf" })] } });
    fireEvent.submit(screen.getByText("Tải lên & phân tích").closest("form")!);
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/drawings/d9"));
    expect(calls.filter((c) => c.method === "POST").map((c) => c.url)).toEqual(["/documents", "/drawings"]);
  });
});
