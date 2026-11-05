import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import BoqReviewPage from "./BoqReviewPage";
import type { Boq, BoqExport, BoqItem } from "./types";

// Synthetic fixtures only.
const blocked: BoqItem = {
  id: "i1", item_no: 1, category: "concrete", description: "DẦM D1 300x600 L=6000 SL=4", spec: "", module: "concrete_prism",
  inputs: { width: { value: "300", origin: "extracted", source_item_id: "s1" }, height: { value: "600", origin: "extracted", source_item_id: "s1" },
    length: { value: "6000", origin: "extracted", source_item_id: "s2" }, count: { value: "4", origin: "extracted", source_item_id: "s3" } },
  unit_system: null, stated_unit: null, waste_factor: "0.0000", waste_override: null, quantity: null, unit: "m3", formula_text: "",
  origin: "extracted", review_status: "pending", flags: [{ code: "unit_unconfirmed", severity: "blocking", message: "Chưa có đơn vị kích thước" }],
  notes: "", drawing_id: "d1", page_no: 1, bbox: [1, 2, 3, 4], source_item_ids: ["line-7", "s1"], version: 1, has_blocking: true,
};
const stated: BoqItem = { ...blocked, id: "i2", item_no: 2, module: null, description: "Dầm D1", unit_system: null, stated_unit: "m3",
  inputs: { quantity: { value: "4.32", origin: "extracted", source_item_id: "t1", raw: "4,32", cell: [1, 4] } }, quantity: "4.3200",
  formula_text: "4.32 (trích nguyên văn bảng thống kê)", flags: [{ code: "possible_duplicate", severity: "warning", message: "Có thể trùng (khối lượng khớp)" }],
  has_blocking: false, group_path: [{ code: "I", title: "An toàn giao thông" }, { code: "4.1", title: "Tôn sóng" }] };
const boq: Boq = {
  id: "b1", title: "BOQ KC-01", version_no: 1, previous_boq_id: null, status: "draft", project_id: null,
  rules: { decimals: 3, steel_density: "7850", waste: {} }, submitted_at: null, decided_at: null, decision_note: "", created_at: null,
  sources: [{ drawing_id: "d1", document_version_id: "v1" }], item_count: 2, review_counts: { pending: 2 }, blocking_count: 1,
  totals: [{ category: "concrete", unit: "m3", accepted: "0", all_active: "4.3200", items: 1 }], items: [blocked, stated],
};
const modules = { modules: [{ key: "concrete_prism", title_vi: "Bê tông", category: "concrete", out_unit: "m3", dimensional: true,
  fields: [{ name: "length", label_vi: "Chiều dài", kind: "dim" }, { name: "width", label_vi: "Chiều rộng", kind: "dim" },
    { name: "height", label_vi: "Chiều cao", kind: "dim" }, { name: "count", label_vi: "Số lượng", kind: "count" }] }] };

const exp: BoqExport = { id: "e1", boq_version_no: 1, boq_status: "draft", filename: "BOQ_KC_v1_NHAP_20261104.xlsx", sha256: "a".repeat(64), size_bytes: 20480, item_count: 2, created_at: null, layout: "paacc" };
let exportsList: typeof exp[] = [];
let calls: { url: string; method: string; body: unknown }[];
let current: Boq;
beforeEach(() => {
  calls = []; current = boq; exportsList = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input).replace("/api/v1", ""), method = init?.method ?? "GET";
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
    if (url === "/boqs/b1" && method === "GET") return json(current);
    if (url === "/takeoff/modules") return json(modules);
    if (url === "/boqs/b1/items/i1" && method === "PATCH") return json({ ...blocked, unit_system: "mm", quantity: "4.3200", has_blocking: false, flags: [] });
    if (url === "/boqs/b1/submit") return json({ detail: "Còn 2 hạng mục chưa rà soát (STT 1, 2)" }, 409);
    if (url === "/boqs/b1/decision") return json({ ...current, status: "approved" });
    if (url === "/boqs/b1/exports" && method === "GET") return json(exportsList);
    if (url.startsWith("/boqs/b1/exports?layout=") && method === "POST") {
      const layout = url.split("=")[1];
      exportsList = [{ ...exp, id: layout, layout, filename: layout === "company_kl" ? "BOQ_KC_v1_NHAP_TongHop.xlsx" : exp.filename }, ...exportsList];
      return json(exportsList[0], 201);
    }
    return json({ detail: "not found" }, 404);
  }));
});

function show() {
  return render(<MemoryRouter initialEntries={["/boqs/b1"]}><Routes><Route path="/boqs/:id" element={<BoqReviewPage />} /></Routes></MemoryRouter>);
}

describe("BOQ review", () => {
  it("lists items with quantity, provenance, flags and Decimal totals from the backend", async () => {
    show();
    expect(await screen.findByText("DẦM D1 300x600 L=6000 SL=4")).toBeTruthy();
    expect(screen.getByText(/còn lỗi chặn: 1/)).toBeTruthy();
    const rows = screen.getAllByRole("row");
    expect(rows.some((r) => r.textContent?.includes("4,320") && r.textContent.includes("Trích xuất"))).toBe(true);
    expect(screen.getAllByText("—").length).toBeGreaterThan(0); // blocked item has no quantity
    const group = screen.getByText("4.1"); // source hierarchy code (Phase 4.1)
    expect(group.getAttribute("title")).toBe("I An toàn giao thông › 4.1 Tôn sóng");
  });

  it("blocks accepting an item with blocking flags and links to the source region", async () => {
    show();
    fireEvent.click(await screen.findByLabelText("Hạng mục 1"));
    expect(screen.getByText(/Chưa có đơn vị kích thước/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Chấp nhận" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Xem vị trí trên bản vẽ/).getAttribute("href")).toBe("/drawings/d1?page=1&item=line-7");
  });

  it("sends only changed fields plus the mandatory reason", async () => {
    show();
    fireEvent.click(await screen.findByLabelText("Hạng mục 1"));
    fireEvent.change(screen.getByLabelText("Đơn vị kích thước"), { target: { value: "mm" } });
    fireEvent.change(screen.getByLabelText("Số lượng"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Lý do chỉnh sửa"), { target: { value: "Theo khung tên" } });
    fireEvent.submit(screen.getByText("Lưu chỉnh sửa").closest("form")!);
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(calls.find((c) => c.method === "PATCH")!.body).toEqual({ reason: "Theo khung tên", inputs: { count: "5" }, unit_system: "mm" });
  });

  it("shows backend workflow errors and approval actions only when submitted", async () => {
    show();
    fireEvent.click(await screen.findByText("Trình phê duyệt"));
    expect(await screen.findByText(/chưa rà soát/)).toBeTruthy();
    expect(screen.queryByText("Phê duyệt")).toBeNull();
    current = { ...boq, status: "submitted" };
    show();
    const approve = await screen.findAllByText("Phê duyệt");
    fireEvent.click(approve[approve.length - 1]);
    await waitFor(() => expect(calls.some((c) => c.url === "/boqs/b1/decision")).toBe(true));
    expect(calls.find((c) => c.url === "/boqs/b1/decision")!.body).toEqual({ decision: "approve", note: "" });
  });
});

describe("BOQ Excel export", () => {
  it("creates an export and lists it in the history with version and status", async () => {
    show();
    fireEvent.click(await screen.findByText("Xuất Excel (bản nháp)"));
    expect(await screen.findByText("BOQ_KC_v1_NHAP_20261104.xlsx")).toBeTruthy();
    expect(screen.getByText(/v1 · Nháp · mẫu PAACC · 2 hạng mục · 20 KB/)).toBeTruthy();
    expect(calls.some((c) => c.url === "/boqs/b1/exports?layout=paacc" && c.method === "POST")).toBe(true);
    fireEvent.click(screen.getByText("Xuất theo mẫu công ty (Tổng hợp KL)"));
    expect(await screen.findByText("BOQ_KC_v1_NHAP_TongHop.xlsx")).toBeTruthy();
    expect(calls.some((c) => c.url === "/boqs/b1/exports?layout=company_kl")).toBe(true);
  });
});
