export const PAGE_KIND: Record<string, string> = {
  vector: "Vector", scanned: "Bản quét (OCR)", mixed: "Hỗn hợp", vector_no_text: "Vector không chữ", empty: "Trống",
};
export const STATUS_VI: Record<string, string> = { queued: "Chờ xử lý", processing: "Đang xử lý", processed: "Đã phân tích", failed: "Lỗi" };
export const CAL_STATUS: Record<string, string> = {
  not_analyzed: "Chưa phân tích", not_detected: "Không tìm thấy", unverified: "Phát hiện – chưa xác nhận",
  conflicting: "Nhiều giá trị – cần chọn", nts_declared: "Ghi 'không theo tỷ lệ' – chưa xác nhận",
  confirmed: "Đã xác nhận", not_to_scale: "Không theo tỷ lệ (đã xác nhận)",
};
export const ITEM_KIND: Record<string, string> = {
  dimension: "Kích thước", count: "Số lượng", spec: "Quy cách/vật liệu", symbol: "Ký hiệu", reference: "Tham chiếu",
  region: "Vùng", table: "Bảng", text: "Chữ gốc",
};
export const FLAG_VI: Record<string, string> = {
  unit_not_stated: "Không ghi đơn vị", ambiguous_number: "Số mơ hồ (dấu phân cách)",
  implausible_value: "Giá trị bất thường – cần kỹ sư xác nhận",
};
export const DISCIPLINE: Record<string, string> = {
  architectural: "Kiến trúc", structural: "Kết cấu", traffic: "Giao thông", infrastructure: "Hạ tầng", mep: "Cơ điện",
};
export const VIEW: Record<string, string> = {
  plan: "Mặt bằng", section: "Mặt cắt", elevation: "Mặt đứng", detail: "Chi tiết", schedule: "Bảng thống kê",
  profile: "Trắc dọc/ngang", general_notes: "Ghi chú chung",
};
export const FINDING_VI: Record<string, string> = {
  overlapping_duplicate_text: "Chữ trùng chồng lên nhau (có thể đếm 2 lần)", repeated_annotation: "Ghi chú lặp lại",
  duplicate_page: "Trang trùng lặp", same_drawing_number_twice: "Số bản vẽ xuất hiện 2 lần", revision: "Phiên bản khác của cùng bản vẽ",
  duplicate_file: "File trùng nội dung với bản vẽ khác",
};
export const REL_VI: Record<string, string> = {
  newer_than: "mới hơn", older_than: "cũ hơn", identical_file: "giống hệt", conflict_same_revision_different_content: "XUNG ĐỘT: cùng phiên bản nhưng nội dung khác",
  different_revision_unordered: "khác phiên bản",
};
export function pct(v: number | null): string { return v == null ? "chính xác" : `${Math.round(v * 100)}%`; }
export const TEXT_TYPE_VI: Record<string, string> = {
  UNKNOWN: "Chưa rõ", DIMENSION: "Kích thước", LENGTH: "Chiều dài", AREA: "Diện tích", COUNT: "Số lượng", CHAINAGE: "Lý trình",
  MATERIAL: "Vật liệu", SPECIFICATION: "Quy cách", LABEL: "Nhãn", NOTE: "Ghi chú", DETAIL_REFERENCE: "Tham chiếu chi tiết",
  TITLE: "Khung tên", TABLE: "Bảng", SCALE: "Tỷ lệ", REVISION: "Lần sửa", OTHER: "Khác",
};
export const ASSOC_TYPE_VI: Record<string, string> = {
  DIMENSION_OF: "Kích thước của", LABEL_OF: "Nhãn của", NOTE_FOR: "Ghi chú cho", MATERIAL_OF: "Vật liệu của",
  REFERENCE_TO: "Tham chiếu tới", CHAINAGE_FOR: "Lý trình của", SCALE_FOR: "Tỷ lệ của", UNKNOWN: "Chưa rõ",
};
export const ASSOC_STATUS_VI: Record<string, string> = {
  CANDIDATE: "Ứng viên", REVIEW_REQUIRED: "Cần kiểm tra", CONFIRMED: "Đã xác nhận", REJECTED: "Loại bỏ",
  AMBIGUOUS: "Mơ hồ", CONFLICT: "Xung đột",
};
export const ASSOC_COLOR: Record<string, string> = {
  CANDIDATE: "#1f6feb", REVIEW_REQUIRED: "#f2994a", CONFIRMED: "#27ae60", REJECTED: "#adb5bd", AMBIGUOUS: "#9b51e0", CONFLICT: "#eb5757",
};
export const COMP_STATUS_VI: Record<string, string> = { ...ASSOC_STATUS_VI, OCCLUDED: "Có thể bị che" };
export const COMP_COLOR: Record<string, string> = { ...ASSOC_COLOR, OCCLUDED: "#795548" };
export const EVIDENCE_VI: [string, string][] = [["text", "Chữ"], ["geometry", "Hình học"], ["measurement", "Phép đo"], ["symbol", "Ký hiệu"],
  ["spatial", "Quan hệ không gian"], ["repetition", "Lặp lại"], ["semantic", "Ngữ cảnh bản vẽ"]];
export const VIEW_CTX_VI: Record<string, string> = { PLAN: "Mặt bằng", SECTION: "Mặt cắt", ELEVATION: "Mặt đứng", DETAIL: "Chi tiết",
  TABLE: "Bảng", NOTE: "Ghi chú", UNKNOWN: "Chưa rõ" };
