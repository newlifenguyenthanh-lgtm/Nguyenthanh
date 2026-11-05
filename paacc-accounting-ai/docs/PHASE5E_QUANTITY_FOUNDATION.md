# Phase 5E-1 – Nền tảng Quantity Engine

**Phạm vi:** chỉ phần nền tảng. Gồm mô hình kết quả, đơn vị, Decimal, phương pháp tính, provenance, state machine và API.

**Ngoài phạm vi:** BOQ hoàn chỉnh, Excel, đơn giá, AutoCAD, LLM, bảng tra thép, quy tắc đo bóc phức tạp. 5E-2 chưa bắt đầu.

Toàn bộ kiểm thử dùng bản vẽ **tổng hợp**. Không tuyên bố độ chính xác trên bản vẽ thật (chưa có dữ liệu).

## 1. Kiến trúc

```
CONFIRMED component (5D) + phép đo 5B (giá trị đọc từ `measurements`, không đo lại)
 + phương pháp tính + tham số kỹ sư nêu kèm nguồn
 → app/quantity/engine.py (thuần, Decimal) → quantity_results (có phiên bản) → review
```

| Module | Vai trò |
|---|---|
| `app/quantity/units.py` | **Bảng đơn vị duy nhất** của hệ thống. `takeoff/engine.py` (Phase 4) cũng lấy hệ số mm/cm/m từ bảng này |
| `app/quantity/rounding.py` | Làm tròn tường minh, cấu hình được, chỉ áp **một lần** cho giá trị cuối |
| `app/quantity/engine.py` | Registry phương pháp tính (thêm phương pháp = thêm một phần tử); quy tắc chặn khi đầu vào chưa đủ thẩm quyền |
| `app/quantity/service.py` | Kiểm tra trạng thái cấu kiện, chọn phép đo, quản lý phiên bản, review, provenance, audit |
| `app/api/quantities.py` | REST API |

Không tạo hệ tính thứ hai:
- Giá trị lấy từ 5B.
- Engine bóc tách cũ của Phase 4 (`takeoff`) giữ nguyên, chỉ dùng chung bảng đơn vị.

Không tạo worker hay queue mới, và không dùng LLM. Phép tính chạy đồng bộ và có audit.

## 2. Mô hình `quantity_results` (migration `0013`)

| Nhóm | Cột |
|---|---|
| Phạm vi | `company_id`, `project_id`, `drawing_id`, `page_id`, `component_id` |
| Đầu vào | `measurement_id` (đầu vào chính, FK), `input_measurement_ids` (danh sách đầy đủ) |
| Giá trị | `quantity_type`, `raw_value` Numeric(30,12) **chưa làm tròn**, `quantity_value` Numeric(24,6), `unit`, `precision`, `rounding_rule` |
| Cách tính | `calculation_method` (bắt buộc), `formula`, `parameters` (tham số kỹ sư **kèm nguồn**) |
| Ảnh chụp | `source_component`, `source_measurement`: trạng thái và giá trị lúc tính, đủ để tái lập kết quả |
| Review | `status`, `reason`, `created_by`, `reviewed_by`, `created_at`, `updated_at`, `reviewed_at` |
| Phiên bản | `version`, `superseded_by_id`. Lần chạy mới thay thế bản cũ cùng (cấu kiện, loại, phương pháp); bản cũ vẫn được giữ |

Ngoài ra, `component_boq_candidates.quantity_result_id` (nullable, FK) được thêm để 5F có thể tham chiếu. Hiện chưa dùng; kiến trúc BOQ không đổi.

## 3. Hệ đơn vị

| Thứ nguyên | Đơn vị |
|---|---|
| length | mm, cm, **m** |
| area | mm2, cm2, **m2** |
| volume | mm3, cm3, **m3** |
| mass | **kg**, t |
| count | **ea**, **set**, **piece** (là 3 thứ nguyên riêng, không quy đổi lẫn nhau) |
| tham số | kg/m, kg/m2 |

- Quy đổi: 1 m = 1000 mm; 1 m² = 1.000.000 mm²; 1 m³ = 10⁹ mm³; 1 t = 1000 kg.
- Alias: m², m³, count/cái/each → ea, bộ → set, tấn → t.
- Khác thứ nguyên hoặc đầu vào float đều bị từ chối.
- Mọi giá trị được quy về đơn vị chuẩn trước khi tính.

## 4. Quy tắc Decimal

- Mọi giá trị có thẩm quyền đều là `Decimal`. Engine không dùng `float(` hay `round(` (có test kiểm tra mã nguồn).
- Không làm tròn trung gian. Ví dụ: 51 × 2,4999 = 127,4949 → 127,49 (không phải 51 × 2,50).
- Quy tắc làm tròn: `ROUND_HALF_UP` (mặc định), `ROUND_HALF_EVEN`, `ROUND_UP`, `ROUND_DOWN`, `ROUND_CEILING`, `ROUND_FLOOR`.
- Số chữ số thập phân từ 0 đến 6. Mặc định cấu hình qua `PAACC_QUANTITY_PRECISION` / `PAACC_QUANTITY_ROUNDING`; có thể ghi đè theo từng lần chạy.
- Cột lưu cả `raw_value` lẫn `quantity_value`.

## 5. Phương pháp tính

| Phương pháp | Loại | Công thức | Phép đo 5B | Tham số |
|---|---|---|---|---|
| COUNT_REFERENCE | COUNT | = count | count | – |
| MEASUREMENT_REFERENCE | LENGTH | = length | length | – |
| SPACING_REFERENCE | SPACING | = spacing | spacing | – |
| AREA_REFERENCE | AREA | = area | area | – |
| PERIMETER_REFERENCE | PERIMETER | = perimeter | perimeter | – |
| COUNT_X_LENGTH | LENGTH | count × chiều dài đơn vị | count | `unit_length {value, unit, source}` |
| LENGTH_X_UNIT_WEIGHT | WEIGHT | length × trọng lượng đơn vị | length | `unit_weight {value, unit kg/m, source}` |

- VOLUME đã có trong danh sách loại nhưng **chưa có phương pháp**. 5B chưa đo thể tích; sẽ thêm ở 5E-2.
- Nếu không truyền `method`, hệ thống chọn mặc định theo `measurement_kind` trong cấu hình BOQ của loại cấu kiện.
- **Tham số do kỹ sư nêu phải có `source`.** Thiếu tham số hoặc thiếu nguồn thì kết quả là REQUIRES_REVIEW. Hệ thống không bao giờ tự đoán trọng lượng đơn vị hay chiều dài đơn vị.

## 6. Provenance

`GET /quantity-results/{id}` trả chuỗi: kết quả → cấu kiện (id, loại, trạng thái) → phép đo (id, loại, giá trị, trạng thái, geometry_ids, scale_source, công thức) → hình học → chữ / liên kết 5C → bản vẽ, trang.

Mỗi kết quả còn lưu ảnh chụp đầu vào tại thời điểm tính.

## 7. State machine

| Từ | Sang | Ghi chú |
|---|---|---|
| DRAFT | CALCULATED / REQUIRES_REVIEW / BLOCKED | Do engine đặt trong cùng một lần chạy |
| CALCULATED | CONFIRMED / REJECTED | Xác nhận bị từ chối nếu kết quả đã bị thay thế hoặc cấu kiện không còn CONFIRMED |
| REQUIRES_REVIEW | REJECTED | Muốn có giá trị thì sửa đầu vào rồi chạy lại |
| BLOCKED | REJECTED | |
| CONFIRMED | REJECTED | Thu hồi cần lý do |
| REJECTED | – | |

**Điều kiện cấu kiện:** chỉ cấu kiện **CONFIRMED** và không phải biểu diễn chi tiết mới được tính. Các trạng thái khác trả **422**.

**Điều kiện phép đo** (dùng nguyên trạng thái 5B: `computed | confirmed | rejected`, không thêm trạng thái mới):

| Tình trạng phép đo / dãy | Kết quả |
|---|---|
| `confirmed`, có giá trị thật | CALCULATED |
| `computed` (chưa được kỹ sư xác nhận) | REQUIRES_REVIEW |
| `rejected` | BLOCKED |
| Không có giá trị thật (chưa có tỷ lệ) | BLOCKED |
| Thiếu phép đo | BLOCKED |
| Dãy lặp OCCLUDED hoặc IRREGULAR_PATTERN (với phép đếm) | REQUIRES_REVIEW |
| Spacing không đều | REQUIRES_REVIEW |

Với REQUIRES_REVIEW và BLOCKED, `raw_value` và `quantity_value` luôn là null. Không có đường nào đưa CALCULATED vào BOQ ở 5E-1.

## 8. API

Cùng quy ước với các phase trước: JWT, `drawing:read` / `drawing:write`, 404 khi khác công ty, audit `quantity_run`, `quantity_confirm`, `quantity_reject`.

| Method | Đường dẫn | Ghi chú |
|---|---|---|
| GET | `/components/{id}/quantity-results?include_superseded=` | |
| POST | `/components/{id}/quantity/run` | body: `{method?, parameters?, precision?, rounding_rule?}`; trả kết quả kèm provenance |
| GET | `/quantity-results/{id}` | Kèm provenance |
| POST | `/quantity-results/{id}/review` | body: `{decision: confirm\|reject, note}` |

## 9. Tests

`tests/test_quantity.py` (21 test):

| # | Nội dung |
|---|---|
| 1 | count 51 → 51 ea |
| 2 | length 125,40 m |
| 3 | area 25,50 m² (kèm perimeter) |
| 4 | 2500 mm → 2,5 m; các phép quy đổi m²/m³/t; từ chối khác thứ nguyên, trộn đơn vị đếm, float |
| 5 | Decimal: 3 × 0,1 = 0,3 chính xác; 100 m × 3,95 kg/m = 395 kg |
| 6 | Làm tròn tường minh: 12,345678 → 12,35; HALF_EVEN; không làm tròn trung gian |
| 7 | Cấu kiện CANDIDATE → 422 |
| 8 | Phép đo computed / rejected / không có giá trị / thiếu; dãy OCCLUDED / IRREGULAR; spacing không đều → không ra giá trị |
| 9 | Luồng API: tham chiếu, quản lý phiên bản, provenance, review, đếm theo dãy, COUNT_X_LENGTH |
| 10 | Cô lập công ty và quyền |
| 11 | Audit |
| – | Derived / unit weight thiếu nguồn; state machine; không phụ thuộc LLM, không float |

- PostgreSQL: `test_postgres.py::test_quantity_results_on_postgres`.
- Hồi quy: toàn bộ test Phase 4 → 5D và gate golden riêng tư.

## 10. Giới hạn

- Chưa có VOLUME, chưa có công thức đo bóc theo loại cấu kiện (ví dụ số tấm tôn = ⌈L / chiều dài hữu dụng⌉), chưa có bảng tra trọng lượng thép, chưa có hao hụt.
- `COUNT_X_LENGTH` chỉ nhận chiều dài đơn vị là tham số kỹ sư nêu kèm nguồn, chưa lấy từ một phép đo.
- Chưa có UI.
- Chưa nối vào BOQ. `component_boq_candidates.quantity_result_id` mới chỉ là chỗ chờ.
- Chưa kiểm chứng trên bản vẽ thi công thật.

## 11. Lộ trình 5E-2 (chưa bắt đầu, chờ review)

- Quy tắc đo bóc theo loại cấu kiện, là **dữ liệu** giống taxonomy 5D, có tham số do kỹ sư xác nhận.
- VOLUME (diện tích × chiều dày nêu kèm nguồn).
- Bảng tra trọng lượng thép có nguồn.
- Hao hụt tường minh.
- UI review khối lượng.
- Sau đó 5F: kết quả CONFIRMED → `component_boq_candidates.quantity_result_id` → `boq_items` (nguồn "geometry") → phê duyệt 4 mắt → Excel.
