export const BOQ_STATUS: Record<string, string> = { draft: "Nháp", submitted: "Chờ phê duyệt", approved: "Đã phê duyệt", returned: "Bị trả lại", failed: "Lỗi" };
export const BOQ_STATUS_COLOR: Record<string, string> = { draft: "#9aa5b1", submitted: "#f2994a", approved: "#27ae60", returned: "#eb5757", failed: "#eb5757" };
export const REVIEW: Record<string, string> = { pending: "Chờ rà soát", accepted: "Chấp nhận", rejected: "Loại bỏ" };
export const ORIGIN: Record<string, string> = { extracted: "Trích xuất", ai_inferred: "AI suy luận", engineer: "Kỹ sư nhập", mixed: "Hỗn hợp" };
export const CATEGORY: Record<string, string> = {
  concrete: "Bê tông", rebar: "Cốt thép", structural_steel: "Thép hình", steel_box: "Thép hộp", plate: "Bản mã / thép tấm", other: "Khác",
};
export const ACTION: Record<string, string> = {
  generated: "Tạo tự động", edited: "Chỉnh sửa", accepted: "Chấp nhận", rejected: "Loại bỏ", review_reset: "Đặt lại rà soát",
  annotated: "Ghi chú", recalculated: "Tính lại (đổi quy tắc)", created_manually: "Kỹ sư thêm", copied_from_version: "Sao chép từ phiên bản trước",
};
export const UNIT: Record<string, string> = { m3: "m³", m2: "m²" };
export function unitLabel(u: string | null | undefined): string { return u ? UNIT[u] ?? u : ""; }
