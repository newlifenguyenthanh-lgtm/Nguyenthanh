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
