import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

const geometry = [
  { id: "g1", page_no: 1, kind: "line", points: [["100", "100"], ["400", "100"]], closed: false, bbox: [100, 100, 400, 100],
    length_pt: "300.0000", area_pt2: null, stroke_width: 0.6, derived_from: "filled_hairline_rect", approximate: false, flags: [],
    duplicate_of: null, status: "extracted", review_note: "", layer: null, source: { path_index: 3, item_index: 0 } },
  { id: "g2", page_no: 1, kind: "rect", points: [["10", "10"], ["50", "10"], ["50", "40"], ["10", "40"]], closed: true, bbox: [10, 10, 50, 40],
    length_pt: "140.0000", area_pt2: "1200.0000", stroke_width: 1, derived_from: null, approximate: false, flags: [], duplicate_of: null,
    status: "confirmed", review_note: "", layer: null, source: { path_index: 4, item_index: 0 } },
];
const blocks = [
  { id: "t1", page_no: 1, extracted_item_id: "x1", original_text: "L=13.50m", normalized_text: "L=13.50m", bbox: [200, 80, 260, 92],
    center: [230, 86], rotation: 0, font_size: 9, font_name: null, source: "text", confidence: null, text_type: "LENGTH",
    values: { length: { value_m: "13.50" } }, flags: [], encoding: null, repeat_count: 1 },
  { id: "t2", page_no: 1, extracted_item_id: "x2", original_text: "25.40", normalized_text: "25.40", bbox: [20, 20, 40, 30],
    center: [30, 25], rotation: 0, font_size: 8, font_name: null, source: "text", confidence: null, text_type: "TABLE",
    values: {}, flags: ["in_table"], encoding: null, repeat_count: 1 },
];
const assoc = (over: Record<string, unknown>) => ({
  id: "a1", drawing_id: "d1", page_no: 1, text_block_id: "t1", geometry_id: "g1", association_type: "DIMENSION_OF", rank: 1,
  distance: 4.2, angle_difference: 0, overlap_ratio: 1, orientation_match: true, semantic_match: 1, relation: "above", components: {},
  confidence: 0.962, status: "CONFLICT", reason: "Chữ: 13.5 m · Hình học: 12.7 m · Chênh: 0.8 m – không tự sửa", origin: "rule",
  duplicate_of: null, measurement_id: "m1", text_value: "13.5", measured_value: "12.7", difference: "0.8", unit: "m", history: [],
  decided_by: null, decided_at: null, ...over });
const associations = [assoc({}), assoc({ id: "a2", geometry_id: "g2", rank: 2, confidence: 0.4, status: "CANDIDATE", reason: "Phương án thay thế hạng 2",
  text_value: null, measured_value: null, difference: null, measurement_id: null })];
const comp = (over: Record<string, unknown> = {}) => ({
  id: "c1", drawing_id: "d1", page_no: 1, component_type: "FENCE", component_subtype: null, name: "Hàng rào", description: "HÀNG RÀO B40",
  specification: "", material: "", bbox: [100, 100, 400, 100], centroid: [250, 100], view_context: "PLAN", recognition_method: "rule",
  recognition_rule: "FENCE@catalog", recognition_confidence: 0.949, confidence_band: "HIGH",
  scores: { text: 1, geometry: 1, measurement: 0.8, symbol: null, spatial: 0.891, repetition: null, semantic: 1, overall: 0.949 },
  status: "CANDIDATE", ambiguity_reason: "", rejection_reason: "", parent_id: null, representation_of_id: null, repeat_group_id: null,
  dimensions: {}, source_text_ids: ["t1"], source_geometry_ids: ["g1"], source_measurement_ids: ["m1"], source_association_ids: ["a1"],
  downstream_allowed: false, ...over });
const compEvidence = { scores: {}, overall: 0.949, band: "HIGH", rule: "FENCE@catalog",
  measurements: [{ id: "m1", kind: "length", value_real: "20.461", real_unit: "m", value_paper: "580", paper_unit: "pt" }],
  detail: { reasons: [], comparisons: [], conflicts: [], ambiguous: [] }, repeat_group: null,
  relations: [{ from: "c2", to: "c1", type: "PART_OF" }] };
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
    if (url.startsWith("/drawings/d1/geometry?")) return json(geometry);
    if (url === "/geometry/g1" && method === "GET") return json({ ...geometry[0], length_paper_mm: "105.83", length_real_m: null,
      real_basis: "Tỷ lệ trang chưa được kỹ sư xác nhận – không thể đổi sang kích thước thật" });
    if (url === "/geometry/g1" && method === "PATCH") return json({ ...geometry[0], status: "ambiguous", review_note: "Không rõ" });
    if (url.startsWith("/drawings/d1/items")) return json(items);
    if (url === "/drawings/d1/components?page=1") return json([comp(), comp({ id: "c9", component_type: "LINEAR_COMPONENT", status: "CONFLICT",
      bbox: [200, 80, 260, 92] })]);
    if (url === "/components/c1/evidence") return json(compEvidence);
    if (url === "/components/c1/review") return json(comp({ status: "REVIEW_REQUIRED" }));
    if (url === "/components/c1/reject") return JSON.parse(init!.body as string).note ? json(comp({ status: "REJECTED" }))
      : json({ detail: "Cần ghi lý do loại bỏ" }, 422);
    if (url === "/components/c1/reclassify") return json(comp({ component_type: "GUARDRAIL", status: "REVIEW_REQUIRED" }));
    if (url === "/component-types") return json([{ code: "FENCE", group: "ATGT", name_vi: "Hàng rào", active: true },
      { code: "GUARDRAIL", group: "ATGT", name_vi: "Hộ lan", active: true }]);
    if (url === "/drawings/d1/pages/1/text-blocks") return json(blocks);
    if (url === "/drawings/d1/pages/1/associations") return json(associations);
    if (url === "/associations/a1/reject") return JSON.parse(init!.body as string).note ? json(assoc({ status: "REJECTED" }))
      : json({ detail: "Cần ghi lý do loại bỏ" }, 422);
    if (url === "/associations/a1/confirm") return json(assoc({ status: "CONFIRMED" }));
    if (url === "/associations/a1" && method === "PATCH") return json(assoc({ geometry_id: "g2", origin: "engineer", status: "REVIEW_REQUIRED",
      history: [{ old_geometry_id: "g1", new_geometry_id: "g2", reason: "đường khác", user: "qs@a.test", timestamp: "2026-11-05T00:00:00Z" }] }));
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

describe("vector geometry overlay (Phase 5A)", () => {
  it("draws primitives, shows backend measurement and records an ambiguity", async () => {
    const { container } = render(<MemoryRouter initialEntries={["/drawings/d1"]}><Routes><Route path="/drawings/:id" element={<DrawingDetailPage />} /></Routes></MemoryRouter>);
    await screen.findByText(/KC-01 – Rev A/);
    fireEvent.click(screen.getByLabelText(/Hiện hình học vector/));
    await waitFor(() => expect(container.querySelectorAll("[data-geo]").length).toBe(2));
    expect(container.querySelector('svg[aria-label="Lớp hình học vector"]')!.getAttribute("viewBox")).toBe("0 0 1000 500");
    expect(container.querySelector('polygon[data-geo="g2"]')!.getAttribute("stroke")).toBe("#27ae60");
    fireEvent.click(container.querySelector('[data-geo="g1"]')!);
    expect(await screen.findByText(/300.0000 pt · 105.83 mm trên giấy/)).toBeTruthy();
    expect(screen.getByText(/chưa được kỹ sư xác nhận/)).toBeTruthy();  // no real length without a confirmed scale
    expect(screen.getByText(/suy ra từ filled_hairline_rect/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Ghi chú hình học"), { target: { value: "Không rõ" } });
    fireEvent.click(screen.getByText("Không rõ"));
    await waitFor(() => expect(calls.some((c) => c.url === "/geometry/g1" && c.method === "PATCH")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PATCH")!.body!)).toEqual({ status: "ambiguous", note: "Không rõ" });
  });
});

describe("text ↔ geometry association overlay (Phase 5C)", () => {
  const open = async () => {
    const r = render(<MemoryRouter initialEntries={["/drawings/d1"]}><Routes><Route path="/drawings/:id" element={<DrawingDetailPage />} /></Routes></MemoryRouter>);
    await screen.findByText(/KC-01 – Rev A/);
    return r;
  };

  it("loads nothing until a layer is switched on, then shows text blocks coloured by status", async () => {
    const { container } = await open();
    expect(calls.some((c) => c.url.includes("/associations"))).toBe(false);
    fireEvent.click(screen.getByLabelText("Chữ"));
    await waitFor(() => expect(container.querySelectorAll("[data-text]").length).toBe(2));
    expect(container.querySelector('[data-text="t1"]')!.getAttribute("stroke")).toBe("#eb5757");  // conflict
    expect(container.querySelector('[data-text="t2"]')!.getAttribute("stroke")).toBe("#adb5bd");  // table text: no association
    expect(container.querySelectorAll("[data-geo]").length).toBe(0);  // geometry layer still off
  });

  it("clicking a text shows ranked candidates with Text / Geometry / Difference and draws only its links", async () => {
    const { container } = await open();
    fireEvent.click(screen.getByLabelText("Chữ"));
    fireEvent.click(screen.getByLabelText("Liên kết"));
    await waitFor(() => expect(container.querySelector('[data-text="t1"]')).toBeTruthy());
    expect(container.querySelectorAll("[data-link]").length).toBe(0);  // nothing selected -> no lines
    fireEvent.click(container.querySelector('[data-text="t1"]')!);
    expect(await screen.findByText(/Chữ: 13.5 m · Hình học: 12.7 m · Chênh: 0.8 m$/)).toBeTruthy();
    await waitFor(() => expect(container.querySelectorAll("[data-link]").length).toBe(2));
    expect(container.querySelectorAll("[data-assoc]").length).toBe(2);
    expect(screen.getAllByText("Xung đột").length).toBeGreaterThan(0);
    // only the selected association's geometries are drawn while the full geometry layer is off
    expect(container.querySelectorAll("[data-geo]").length).toBe(2);
  });

  it("reject needs a reason; confirm and reassign go to the backend with the engineer's note", async () => {
    const { container } = await open();
    fireEvent.click(screen.getByLabelText("Chữ"));
    fireEvent.click(screen.getByLabelText("Liên kết"));
    await waitFor(() => expect(container.querySelector('[data-text="t1"]')).toBeTruthy());
    fireEvent.click(container.querySelector('[data-text="t1"]')!);
    const first = await waitFor(() => container.querySelector('[data-assoc="a1"]') as HTMLElement);
    fireEvent.click(within(first).getByText("Loại bỏ"));
    expect(await screen.findByText(/Cần ghi lý do loại bỏ/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Ghi chú liên kết"), { target: { value: "đường khác" } });
    fireEvent.click(within(first).getByText("Chọn hình học khác"));
    await waitFor(() => expect(container.querySelector('[data-geo="g2"]')).toBeTruthy());
    fireEvent.click(container.querySelector('[data-geo="g2"]')!);
    await waitFor(() => expect(calls.some((c) => c.url === "/associations/a1" && c.method === "PATCH")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PATCH" && c.url === "/associations/a1")!.body!)).toEqual({ geometry_id: "g2", reason: "đường khác" });
    fireEvent.click(within(container.querySelector('[data-assoc="a1"]') as HTMLElement).getByText("Chấp nhận"));
    await waitFor(() => expect(calls.some((c) => c.url === "/associations/a1/confirm")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.url === "/associations/a1/confirm")!.body!)).toEqual({ note: "đường khác" });
  });

  it("conflict layer alone shows only conflicting texts and their Text ≠ Geometry tag", async () => {
    const { container } = await open();
    fireEvent.click(screen.getByLabelText("Xung đột"));
    await waitFor(() => expect(container.querySelectorAll("[data-text]").length).toBe(1));
    await waitFor(() => expect(container.querySelector('[data-tag="a1"]')?.textContent).toBe("≠ 13.5 / 12.7 m"));
  });
});

describe("component recognition layer (Phase 5D)", () => {
  const open = async () => {
    const r = render(<MemoryRouter initialEntries={["/drawings/d1"]}><Routes><Route path="/drawings/:id" element={<DrawingDetailPage />} /></Routes></MemoryRouter>);
    await screen.findByText(/KC-01 – Rev A/);
    return r;
  };

  it("loads components only when the layer is on and shows evidence, sources and referenced measurements", async () => {
    const { container } = await open();
    expect(calls.some((c) => c.url.includes("/components"))).toBe(false);
    fireEvent.click(screen.getByLabelText("Cấu kiện"));
    await waitFor(() => expect(container.querySelectorAll("[data-comp]").length).toBe(2));
    expect(container.querySelector('[data-comp="c9"]')!.getAttribute("stroke")).toBe("#eb5757");
    fireEvent.click(container.querySelector('[data-comp="c1"]')!);
    const panel = await screen.findByLabelText("Cấu kiện", { selector: "div" });
    expect(within(panel).getByText(/mức bằng chứng, không phải xác nhận/)).toBeTruthy();
    expect(within(panel).getByText("Chữ").nextSibling!.textContent).toBe("100%");
    expect(within(panel).getByText("Ký hiệu").nextSibling!.textContent).toBe("—");
    expect(await within(panel).findByText(/Phép đo \(5B\): length = 20.461 m/)).toBeTruthy();
    expect(within(panel).getByText(/Quan hệ: PART_OF/)).toBeTruthy();
    fireEvent.click(within(panel).getByText("↗ Xem nguồn"));
    await waitFor(() => expect(container.querySelector('[data-geo="g1"]')!.getAttribute("stroke")).toBe("#e8590c"));
  });

  it("review actions: start review, reject needs a reason, reclassify sends only editable fields", async () => {
    const { container } = await open();
    fireEvent.click(screen.getByLabelText("Cấu kiện"));
    await waitFor(() => expect(container.querySelector('[data-comp="c1"]')).toBeTruthy());
    fireEvent.click(container.querySelector('[data-comp="c1"]')!);
    const panel = await screen.findByLabelText("Cấu kiện", { selector: "div" });
    fireEvent.click(within(panel).getByText("Bắt đầu review"));
    await waitFor(() => expect(calls.some((c) => c.url === "/components/c1/review")).toBe(true));
    fireEvent.click(within(panel).getByText("✕ Loại bỏ"));
    expect(await within(panel).findByText(/Cần ghi lý do loại bỏ/)).toBeTruthy();
    fireEvent.click(within(panel).getByText("✎ Phân loại lại"));
    await waitFor(() => expect(within(panel).getByRole("option", { name: /GUARDRAIL/ })).toBeTruthy());
    fireEvent.change(within(panel).getByLabelText("Loại cấu kiện"), { target: { value: "GUARDRAIL" } });
    fireEvent.change(within(panel).getByLabelText("Ghi chú cấu kiện"), { target: { value: "là hộ lan" } });
    fireEvent.click(within(panel).getByText("Lưu"));
    await waitFor(() => expect(calls.some((c) => c.url === "/components/c1/reclassify")).toBe(true));
    const body = JSON.parse(calls.find((c) => c.url === "/components/c1/reclassify")!.body!);
    expect(body).toEqual({ component_type: "GUARDRAIL", component_subtype: null, description: "HÀNG RÀO B40", specification: "",
      material: "", reason: "là hộ lan" });
    expect(Object.keys(body)).not.toContain("quantity");
  });

  it("the conflict layer alone shows only conflicting components", async () => {
    const { container } = await open();
    fireEvent.click(screen.getByLabelText("Xung đột"));
    await waitFor(() => expect(container.querySelectorAll("[data-comp]").length).toBe(1));
    expect(container.querySelector('[data-comp="c9"]')).toBeTruthy();
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
