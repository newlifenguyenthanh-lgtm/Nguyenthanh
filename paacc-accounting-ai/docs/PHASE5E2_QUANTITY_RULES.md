# Phase 5E-2 – Quy tắc khối lượng tất định và bản chạy thử

**Kết quả:** một lát cắt dọc chạy được: PDF → 5A → 5B → 5C → 5D → 5E-1 → **5E-2** → kết quả khối lượng có công thức và nguồn.

**Đặc điểm:**
- Tất định, đồng bộ, không dùng LLM.
- Không thêm Redis, Celery hay worker.

**Ngoài phạm vi:** Excel, BOQ, đơn giá, AutoCAD. 5F chưa bắt đầu.

Mọi kiểm thử và demo dùng dữ liệu **giả lập**. Không tuyên bố độ chính xác trên bản vẽ thật (chưa có dữ liệu).

## 1. Rule registry
- `app/quantity/rules.json` là **dữ liệu**; `app/quantity/rules.py` nạp và kiểm tra.
- Mỗi rule gồm: `rule_code`, `component_type`, `quantity_type`, `method` (một phương pháp 5E-1 trong `engine.METHODS`), `required_measurements`, `required_parameters`, `formula`, `output_unit`, `validation` (`integer` / `positive` / `max`), `auto`, `note`.
- **Kiểm tra khi nạp:** phương pháp phải tồn tại; loại khối lượng, đơn vị, phép đo và tham số phải khớp đúng với phương pháp; mã rule không được trùng. Sai thì dừng ngay khi khởi động.
- **Không rẽ nhánh theo tên cấu kiện** trong engine, service hay registry (có test quét mã nguồn). Chuỗi xử lý là: `component_type` → `rules_for()` → rule → phương pháp. Thêm loại cấu kiện chỉ cần thêm một mục JSON.

## 2. Các rule hỗ trợ (catalog khởi đầu, chưa phải thư viện BOQ cuối)

| Rule | Loại | Phương pháp | Công thức | Ghi chú |
|---|---|---|---|---|
| STEEL_POST.COUNT | COUNT | COUNT_REFERENCE | COUNT | |
| STEEL_POST.TOTAL_LENGTH | LENGTH | COUNT_X_LENGTH | COUNT × UNIT_LENGTH | Chiều dài **một trụ**, không phải bước trụ |
| STEEL_POST.WEIGHT | WEIGHT | LENGTH_X_UNIT_WEIGHT | LENGTH × UNIT_WEIGHT | |
| FENCE_POST.COUNT | COUNT | COUNT_REFERENCE | COUNT | |
| FENCE_POST.TOTAL_LENGTH | LENGTH | COUNT_X_LENGTH | COUNT × UNIT_LENGTH | |
| FENCE_POST.SPACING | SPACING | SPACING_REFERENCE | SPACING | `auto = false`: thông tin kiểm tra, không phải tổng chiều dài |
| BOLT.COUNT | COUNT | COUNT_REFERENCE | COUNT | |
| CORRUGATED_SHEET.AREA | AREA | AREA_REFERENCE | AREA | |
| CORRUGATED_SHEET.LENGTH | LENGTH | MEASUREMENT_REFERENCE | LENGTH | |
| GUARDRAIL.LENGTH | LENGTH | MEASUREMENT_REFERENCE | LENGTH | |
| NOISE_BARRIER.AREA | AREA | AREA_REFERENCE | AREA | |
| NOISE_BARRIER.LENGTH | LENGTH | MEASUREMENT_REFERENCE | LENGTH | |
| LINEAR_COMPONENT.LENGTH | LENGTH | MEASUREMENT_REFERENCE | LENGTH | |
| FENCE.LENGTH | LENGTH | MEASUREMENT_REFERENCE | LENGTH | |

- Các rule COUNT có kiểm tra `integer` + `positive`; các rule còn lại `positive`. Không đạt kiểm tra thì REQUIRES_REVIEW, không bao giờ tự "sửa" giá trị.
- NOISE_BARRIER không có trong taxonomy mặc định; công ty thêm qua `POST /component-types` của 5D, và rule đã có sẵn.

## 3. Ánh xạ cấu kiện
Chỉ cấu kiện thoả cả hai điều kiện sau mới được tính:
- `status = CONFIRMED`
- `representation_of_id IS NULL` (không phải biểu diễn chi tiết/mặt cắt)

Trường hợp còn lại:
- **Chạy theo từng cấu kiện:** trả 422.
- **Chạy cả bản vẽ:** đếm vào `not_confirmed` hoặc `representations_skipped`, không tạo dòng kết quả.

Một rule chỉ được kích hoạt khi cấu kiện **có đủ** các loại phép đo 5B cần thiết, và các tham số bắt buộc được cung cấp. Thiếu thì bỏ qua và đếm vào `skipped_missing_measurement` hoặc `skipped_missing_parameter`. Hệ thống không tự bịa kích thước.

## 4. Ánh xạ phép đo
- Phép đo lấy từ `component_sources` (5D). Với dãy lặp 5D, `count` và `spacing` là phép đo 5B của dãy.
- **COUNT, SPACING và TOTAL_LENGTH là ba đại lượng khác nhau:**
  - 10 trụ với bước 2,5 m **không** tự thành 25 m.
  - TOTAL_LENGTH chỉ được tạo bởi rule COUNT × UNIT_LENGTH, với chiều dài đơn vị nêu rõ.
  - Dùng một phép đo `spacing` làm `unit_length` bị từ chối (422).
- `unit_length` có thể lấy từ một **phép đo length 5B đã xác nhận** (`{"measurement_id": …}`). Khi đó **cả hai** id (count và length) được lưu trong `input_measurement_ids` và `source_measurement`.

## 5. Nguồn tham số
Tham số nhập tay có dạng `{value, unit, source_type, source_reference}`, trong đó:
- `source_type` thuộc: `ENGINEER_INPUT`, `PROJECT_STANDARD`, `DRAWING_NOTE`, `CATALOG`.
- `source_reference` bắt buộc, không được rỗng.
- `entered_by` do server ghi (email người chạy).

Thiếu nguồn, nguồn rỗng hoặc `source_type` lạ → **REQUIRES_REVIEW**, `quantity_value = NULL`. Không bao giờ tự đoán trọng lượng đơn vị hay chiều dài đơn vị.

Định dạng cũ của 5E-1 (`source`) vẫn được nhận và được hiểu là `ENGINEER_INPUT`.

## 6. Diễn giải công thức (formula trace)
Chuỗi được sinh từ giá trị Decimal (`engine.fmt`, không dùng float), lưu ở `quantity_results.formula_trace` và trả qua API:

| Trường hợp | Ví dụ |
|---|---|
| Nhân | `51 × 2.500 m = 127.500 m` |
| Nhân | `100.000 m × 3.950 kg/m = 395.000 kg` |
| Tham chiếu | `125.400 m`, `85.750 m²`, `240 ea` |
| Có làm tròn | `12.35 m (giá trị thô 12.345678)` |

- `formula` lưu dạng ký hiệu (`COUNT × UNIT_LENGTH`).
- Bảng `quantity_results` có thêm `rule_code` (migration `0014`).

## 7. Kiểm soát trùng
- **Biểu diễn 5D** (mặt bằng + chi tiết, `REPRESENTATION_OF`): chỉ cấu kiện chính được tính, nên **một** khối lượng.
- **Không xác định được trùng hay không** thì **REQUIRES_REVIEW**, kèm lý do. Không tự gộp, không tự xoá. Hai trường hợp:
  - Cấu kiện chỉ có ở DETAIL / SECTION / ELEVATION mà chưa liên kết với mặt bằng.
  - Hai cấu kiện CONFIRMED chính, cùng loại, cùng phép đo hoặc cùng hình học.

## 8. Xử lý trạng thái
Các quy tắc chặn của 5E-1 giữ nguyên, không nới lỏng:

| Tình huống | Kết quả |
|---|---|
| Cấu kiện CANDIDATE / REVIEW_REQUIRED / AMBIGUOUS / CONFLICT / OCCLUDED / REJECTED | 422; không có dòng kết quả |
| Phép đo `computed` (chưa xác nhận) | REQUIRES_REVIEW |
| Phép đo `rejected` / không có giá trị thật / thiếu phép đo | BLOCKED |
| Dãy lặp OCCLUDED / IRREGULAR_PATTERN với phép đếm | REQUIRES_REVIEW |
| Spacing không đều | REQUIRES_REVIEW |
| Thiếu tham số hoặc thiếu nguồn | REQUIRES_REVIEW |
| Rule-validation không đạt | REQUIRES_REVIEW |
| Rủi ro trùng | REQUIRES_REVIEW |

- Khi không CALCULATED, `raw_value` và `quantity_value` luôn là NULL.
- Hệ thống không nội suy phần bị che.
- 5B không có trạng thái "ambiguous" riêng; phép đo chưa được kỹ sư xác nhận được xử lý như mơ hồ (REQUIRES_REVIEW).

## 9. API
Dùng cùng xác thực, quyền (`drawing:read` / `drawing:write`), cô lập công ty và audit như các phase trước.

| Method | Đường dẫn | Ghi chú |
|---|---|---|
| POST | `/drawings/{id}/quantities/run` | body `{parameters: {component_id: {param: spec}}}`; trả tóm tắt `components_scanned`, `not_confirmed`, `representations_skipped`, `rules_matched`, `calculated`, `requires_review`, `blocked`, `skipped_missing_parameter`, `skipped_missing_measurement`, `no_rule`, `result_ids`. Audit `quantity_run_drawing` |
| GET | `/drawings/{id}/quantity-results` | Kèm loại cấu kiện, mô tả, trang |
| GET | `/components/{id}/quantity-results` | |
| POST | `/components/{id}/quantity/run` | body `{rule_code?, method?, parameters?, precision?, rounding_rule?}` |
| GET | `/quantity-results/{id}` | Provenance: cấu kiện → phép đo → hình học → chữ / liên kết → trang, cùng **audit** |
| POST | `/quantity-results/{id}/review` | (5E-1) |
| GET | `/quantity-rules?component_type=` | |

**UI tối thiểu:** khu "Khối lượng" trong trang bản vẽ.
- Nút "Tính khối lượng" và tóm tắt kết quả chạy.
- Bảng: cấu kiện / loại / quy tắc / công thức / khối lượng / đơn vị / trạng thái / trang / nguồn.
- Bấm một dòng để xem cấu kiện, phép đo, tham số kèm nguồn và người nhập, hình học, chữ, liên kết 5C, trang, phép tính và audit.
- "↗ Xem nguồn" tô sáng hình học nguồn trên bản vẽ.

## 10. Demo
```bash
cd backend && python -m app.quantity.demo
```
```bash
cd backend && python -m app.quantity.demo --pipeline
```
- **Phần A:** dữ liệu giả lập trong SQLite bộ nhớ (6 cấu kiện, phép đo đã xác nhận, tham số có nguồn), chạy đúng `run_drawing` của sản phẩm.
- **Phần B (`--pipeline`):** sinh PDF vector giả lập (hàng rào 10 trụ) và chạy qua API thật: 5A → 5B → 5C → 5D → 5E-2. Xác nhận ở đây theo **kịch bản DEMO**; trong sản phẩm chỉ kỹ sư thật xác nhận.

Kết quả phần A, tất định; test so khớp từng giá trị và công thức:

| Cấu kiện | Rule | Công thức | Khối lượng | Trạng thái |
|---|---|---|---|---|
| C1 STEEL_POST | COUNT | 51 ea | 51 ea | CALCULATED |
| C1 STEEL_POST | TOTAL_LENGTH | 51 × 2.500 m = 127.500 m | 127.500 m | CALCULATED |
| C2 GUARDRAIL | LENGTH | 125.400 m | 125.400 m | CALCULATED |
| C3 BOLT | COUNT | 240 ea | 240 ea | CALCULATED |
| C4 CORRUGATED_SHEET | AREA | 85.750 m² | 85.750 m² | CALCULATED |
| C5 STEEL_POST | WEIGHT | 100.000 m × 3.950 kg/m = 395.000 kg | 395.000 kg | CALCULATED |
| C6 STEEL_POST (CANDIDATE) | COUNT | – | – | BLOCKED (HTTP 422) |

Kết quả phần B: FENCE.LENGTH `20.461 m`; FENCE_POST.COUNT `10 ea`; FENCE_POST.TOTAL_LENGTH bị bỏ qua vì thiếu tham số.

## 11. Giới hạn
- Catalog rule khởi đầu chỉ có 14 rule. Chưa có quy tắc đo bóc chuyên ngành (số tấm tôn = ⌈L / chiều dài hữu dụng⌉, hao hụt, mối nối, bảng tra thép có nguồn).
- Chưa có VOLUME, vì 5B chưa đo thể tích.
- Rule chỉ chạy khi cấu kiện đã có đúng loại phép đo. Ví dụ 5D không tự đo diện tích tôn, nên CORRUGATED_SHEET.AREA chỉ chạy khi đã có phép đo area 5B.
- Kiểm tra trùng dựa trên dữ liệu 5D (biểu diễn, chung phép đo hoặc hình học, cùng loại). Chưa có so khớp xuyên bản vẽ.
- UI chỉ là bảng xem và chạy, chưa có review khối lượng trên UI (API đã có).
- Chưa kiểm chứng trên bản vẽ thi công thật.

## 12. Giai đoạn tiếp theo (chưa bắt đầu, chờ review)
5F: kết quả khối lượng **CONFIRMED** (không bị thay thế) → `component_boq_candidates.quantity_result_id` → `boq_items` (nguồn "geometry", provenance đầy đủ) → phê duyệt 4 mắt → Excel 2 layout; đối chiếu W4 khi có bản vẽ thật.
