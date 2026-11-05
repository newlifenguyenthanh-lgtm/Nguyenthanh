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

## Kế hoạch 5B–5E (chưa có migration; sẽ thêm khi triển khai)

| Bảng | Nội dung chính |
|---|---|
| `scale_regions` | page, bbox, scale_ratio, status (confirmed bởi kỹ sư), nguồn ứng viên |
| `measurements` | geometry_ids[], loại đo (length/area/count/spacing/chainage_interval), giá trị Decimal, đơn vị, scale_region, công thức, trạng thái, người xác nhận |
| `associations` | text_item_id ↔ geometry_ids, loại (dimension/label/chainage/spec/reference/note), điểm số, lý do, `AMBIGUOUS/CONFLICT` |
| `chainage_marks` | page, text_item_id, giá trị mét (Decimal, từ `Km a+bbb`), phía (trái/phải/tim), geometry liên kết |
| `recognized_objects` | loại cấu kiện, geometry_ids, thuộc tính (từ association), quy tắc nhận dạng + phiên bản, tier (deterministic / rule / CV / LLM / human), trạng thái |
| `boq_items.inputs.*` | thêm `source_geometry_ids`, `measurement_id` (không đổi schema BOQ, chỉ thêm khoá trong JSON) |
