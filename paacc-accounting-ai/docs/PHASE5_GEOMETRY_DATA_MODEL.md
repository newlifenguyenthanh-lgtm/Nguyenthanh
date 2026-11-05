# Phase 5 – Geometry: mô hình dữ liệu

## 5A (đã triển khai, migration `0009_vector_geometry`)

### `geometry_primitives`
| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| id, company_id, drawing_id, page_no | uuid / int | khoá, cô lập công ty, liên kết bản vẽ/trang |
| kind | str | `line, polyline, polygon, rect, fill_region, curve, circle` |
| points | JSON `[["x","y"],…]` | toạ độ DISPLAY (pt, gốc trên-trái), chuỗi thập phân 0,01 pt, chính xác |
| closed | bool | hình khép kín |
| x0, y0, x1, y1 | float | bbox, chỉ để lọc theo vùng |
| length_pt, area_pt2 | Numeric(18,4) / (20,4) | đo bằng Decimal trên toạ độ đã lưu (giấy, chưa áp tỷ lệ) |
| stroke_width, stroke_color, fill_color, layer | | thuộc tính vẽ; layer = OCG nếu PDF có |
| path_index, item_index | int | vị trí trong `get_drawings()`, nguồn trong content stream |
| derived_from | str | ví dụ `filled_hairline_rect` |
| approximate | bool | độ dài đường cong là xấp xỉ |
| flags | JSON | `duplicate_geometry`, `collinear_overlap`, `outside_page` |
| duplicate_of | uuid → self | bản vẽ lặp; chỉ liên kết, không xoá |
| overlaps | JSON [uuid] | các primitive chồng lấn thẳng hàng |
| extra | JSON | ví dụ tâm/bán kính của đường tròn |
| status | str | `extracted, confirmed, rejected, ambiguous` (người kiểm tra) |
| review_note, reviewed_by, reviewed_at | | lý do (bắt buộc khi rejected/ambiguous), audit |

### Cột mới của `drawing_pages`
| Cột | Ý nghĩa |
|---|---|
| geometry_status | `not_extracted, extracted, no_vector_geometry, raster_only, too_complex, failed` |
| geometry_stats | số path/item, theo loại, số line suy ra từ hình chữ nhật mảnh, trùng lặp, chồng lấn, layer, cảnh báo |
| page_frame | rotation, MediaBox, CropBox, ma trận PAGE→DISPLAY, quy ước không gian |

**Quy tắc ghi:** chỉ trích xuất lại khi chưa có primitive nào được kỹ sư review. Nếu đã có thì trả 409, không ghi đè quyết định của người.

## 5B (đã triển khai, migration `0010_scale_regions_and_measurements`)
`scale_regions`, `measurements`. Xem `PHASE5B_MEASUREMENT_ENGINE.md`. 5C thêm hai giá trị:
- `measurements.kind = chainage_interval`
- `method = chainage-5C`

## 5C (đã triển khai, migration `0011_text_blocks_and_associations`)

### `drawing_text_blocks`
| Cột | Ý nghĩa |
|---|---|
| `extracted_item_id` | dòng chữ nguồn (`extracted_items`, kind `text`). Id khối ổn định qua các lần chạy lại |
| `original_text` | chữ gốc, **không bao giờ sửa**; giữ cả TCVN3/VNI |
| `normalized_text` | NFC, `×→x`, bỏ khoảng trắng thừa, `L = 5` → `L=5`. Không đổi dấu thập phân hay mã hoá |
| `x0..y1`, `center_x/y`, `rotation`, `font_size`, `font_name` | không gian DISPLAY (pt) |
| `text_type` | UNKNOWN, DIMENSION, LENGTH, AREA, COUNT, CHAINAGE, MATERIAL, SPECIFICATION, LABEL, NOTE, DETAIL_REFERENCE, TITLE, TABLE, SCALE, REVISION, OTHER |
| `values` | JSON giá trị đã phân tích (Decimal dạng chuỗi): `length.value_m`, `chainage[].meters`, `dimensions`, `specs`, `references` |
| `flags` | `in_table`, `in_title_block`, `page_number`, `unit_case_ambiguous`, `ambiguous_number`, `ENCODING_UNKNOWN`, `legacy_encoding`, `brand_or_notation_possible` |
| `encoding` | kết quả phát hiện 5A.1 (khi có nghi ngờ) |
| `repeat_count` | số lần chữ chuẩn hoá xuất hiện trên trang |

### `text_geometry_associations`
| Cột | Ý nghĩa |
|---|---|
| `text_block_id`, `geometry_id` | chủ thể và đối tượng |
| `association_type` | DIMENSION_OF, LABEL_OF, NOTE_FOR, MATERIAL_OF, REFERENCE_TO, CHAINAGE_FOR, SCALE_FOR, UNKNOWN |
| `rank`, `confidence` | thứ hạng; điểm heuristic 0–1 (float, **không phải số lượng**) |
| `distance`, `angle_difference`, `overlap_ratio`, `orientation_match`, `semantic_match`, `relation`, `components` | các thành phần điểm, lưu để giải thích được |
| `status` | CANDIDATE, REVIEW_REQUIRED, CONFIRMED, REJECTED, AMBIGUOUS, CONFLICT |
| `origin` | `rule` / `engineer` / `ai_inferred` (LLM chỉ được tạo ứng viên) |
| `duplicate_of` | liên kết chính khi chữ lặp lại cho cùng hình học; bản lặp không tạo phép đo |
| `measurement_id` | phép đo 5B hoặc khoảng lý trình dùng để so sánh |
| `text_value`, `measured_value`, `difference` | Numeric(24,6), mét: Chữ / Hình học / Chênh |
| `history` | danh sách `{old_geometry_id, new_geometry_id, reason, user, user_id, timestamp}` khi đổi hình học |
| `decided_by`, `decided_at` | người và thời điểm quyết định review |

**Quy tắc ghi:**
- Khi chạy lại, chỉ xoá ứng viên `rule` còn mở và chưa có ai quyết định.
- Liên kết do kỹ sư tạo hoặc đã quyết định thì giữ nguyên.
- Downstream (5E) chỉ được dùng `status = CONFIRMED` và `duplicate_of IS NULL`.

## 5D (đã triển khai, migration `0012_component_recognition`)

7 bảng mới:
- `component_types`, `component_symbol_patterns` (taxonomy và mẫu là dữ liệu, theo công ty)
- `drawing_components`
- `component_sources`
- `component_relations`
- `component_repeat_groups`
- `component_boq_candidates`

Chi tiết ở `PHASE5D_COMPONENT_RECOGNITION.md` §2.

Cấu kiện **không lưu số lượng**: chỉ tham chiếu `measurements`. 5B thêm kind `diameter`.

## Kế hoạch 5E

| Bảng | Nội dung chính |
|---|---|
| `boq_items.inputs.*` | thêm `source_geometry_ids`, `measurement_id`, `association_ids` (không đổi schema BOQ, chỉ thêm khoá trong JSON) |
