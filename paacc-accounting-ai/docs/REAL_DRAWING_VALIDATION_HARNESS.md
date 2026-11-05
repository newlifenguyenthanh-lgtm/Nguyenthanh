# Real Drawing Validation Harness (5A → 5E-2)

**Trạng thái thử nghiệm (commit hiện tại):**
- **Chưa nhận được bản vẽ thi công thật.**
- Harness đã sẵn sàng và đã được kiểm tra trên:
  - PDF giả lập: logic, có test.
  - R1: báo giá, **không phải bản vẽ thi công**; chỉ kiểm tra tương thích pipeline.
- **Chưa có kết quả kiểm chứng thực tế nào.**

## 1. Mục đích
Chạy **đúng pipeline hiện có** trên một PDF bản vẽ thật và tạo báo cáo truy vết từng giai đoạn. Pipeline: tiếp nhận (4A/5A), hình học (5A), phép đo (5B), liên kết (5C), cấu kiện (5D), khối lượng (5E-1/5E-2).

Harness **không** phải hệ bóc tách thứ hai: nó chỉ gọi API thật trên một cơ sở dữ liệu tạm cô lập.

## 2. Cách chạy
```bash
cd paacc-accounting-ai/backend && python -m tools.validate_real_drawing --pdf /đường/dẫn/ban_ve.pdf --out /thư/mục/NGOÀI/repo
```
Có quyết định của kỹ sư và bảng QS thủ công:
```bash
cd paacc-accounting-ai/backend && python -m tools.validate_real_drawing --pdf ban_ve.pdf --out /ngoai/repo/run2 --decisions decisions.json --manual-ref manual_qs.csv
```

- **File PDF:** chỉ được đọc; không bị sửa, không chép vào repo.
- **Thư mục kết quả:** **bị từ chối nếu nằm trong git repo** (exit 2), vì báo cáo chứa dữ liệu lấy từ bản vẽ.
- **Đầu ra:** `<tên>.validation.md` và `<tên>.validation.json`.

## 3. Không tự xác nhận – quy trình hai lượt
1. **Lượt 1 (không có `--decisions`):** chỉ có ứng viên.
   - Không cấu kiện nào CONFIRMED, nên **không có khối lượng có thẩm quyền**. Đây là kết quả đúng, không phải lỗi.
   - Báo cáo in ra **fingerprint** ổn định của từng cấu kiện (`p<trang>:<loại>:<x0>,<y0>,<x1>,<y1>`).
2. **Kỹ sư** xem bản vẽ và báo cáo, rồi ghi `decisions.json` (có tên người review):

| Trường | Ý nghĩa |
|---|---|
| `scale` | `{trang: tỷ lệ}` do kỹ sư xác nhận. Không bao giờ suy ra từ ứng viên |
| `scale_regions` | Vùng tỷ lệ chi tiết |
| `confirm_components` / `reject_components` | Danh sách fingerprint |
| `confirm_measurements_of` | Kỹ sư đã kiểm phép đo 5B của các cấu kiện này |
| `parameters` | Tham số theo fingerprint, **bắt buộc có `source_type` + `source_reference`** |

3. **Lượt 2 (có `--decisions`):** harness áp đúng các quyết định đó qua API review thật (có audit), chạy lại 5C/5D trên tỷ lệ đã xác nhận, rồi chạy 5E.

## 4. So sánh với QS thủ công
`manual_qs.csv` có các cột: `item,rule_code,unit,quantity`. `rule_code` có thể là mã quy tắc (`FENCE.LENGTH`) hoặc loại cấu kiện.

| Trạng thái | Điều kiện |
|---|---|
| CORRECT | Mọi kết quả khớp đều CALCULATED, tổng lệch ≤ max(0,01; 0,5 %), có provenance |
| WRONG | Đã CALCULATED nhưng lệch vượt dung sai |
| NEEDS_REVIEW | Có kết quả hoặc ứng viên nhưng còn REQUIRES_REVIEW / BLOCKED / chưa xác nhận. **Không bao giờ nâng thành CORRECT** |
| CANNOT_TAKEOFF | Không có kết quả hoặc ứng viên nào |

Không có file tham chiếu thì báo cáo ghi `MANUAL_REFERENCE: NOT_AVAILABLE`, kèm danh sách cấu kiện cần kỹ sư xác nhận. **Không tuyên bố độ chính xác.**

## 5. Báo cáo
Các mục:
- **A.** Tóm tắt file và từng trang: loại trang, số bản vẽ, tên, revision, loại khung nhìn, tỷ lệ, hình học, mục trích xuất, loại chữ, liên kết.
- **B.** Tóm tắt giai đoạn, kèm thời gian.
- **C.** Kiểm tra cấu kiện: fingerprint, trạng thái, độ tin cậy, phép đo (giá trị thật hay chỉ trên giấy), khối lượng, có cần review hay không.
- **D.** Provenance từng khối lượng: rule → cấu kiện → phép đo (kèm nguồn tỷ lệ) → hình học → chữ / liên kết → trang.
- **E.** So sánh với QS thủ công.
- **REAL DRAWING VALIDATION RESULT.**

Kết luận được tính máy móc theo quy tắc trong `verdict()`:
- `NOT_EXERCISED` và `NOT_VALIDATED` được ghi đúng như vậy, **không bao giờ tính là PASS**.
- End-to-end chỉ PASS khi có bảng QS và mọi dòng đều CORRECT.

## 6. Kết quả đã chạy (không phải kiểm chứng thực tế)

| Đầu vào | Kết quả |
|---|---|
| PDF giả lập hàng rào, không có quyết định | 2 ứng viên (FENCE, FENCE_POST); 0 khối lượng; 5E ghi NOT_EXERCISED |
| PDF giả lập hàng rào, có quyết định giả lập + bảng tham chiếu có cài lỗi | FENCE.LENGTH 20,461 m CORRECT; FENCE_POST.COUNT 10 vs 11 WRONG; TOTAL_LENGTH 25 m CORRECT; FOOTING m³ CANNOT_TAKEOFF; Traceability PASS. Chứng minh việc phân loại trung thực |
| R1 (báo giá 2 trang vector) | Xem dòng bên dưới |

R1 chi tiết:
- 5A PASS, hình học PASS.
- 0 phép đo; 263 khối chữ bảng/khung tên bị loại trừ.
- 0 cấu kiện, 0 khối lượng.
- Khoảng 2,2 s/trang.
- Đúng với gate golden. **Không nói gì về bản vẽ thi công.**

Test: `tests/test_validate_harness.py` (4 test, chỉ dùng dữ liệu giả lập).

## 7. Việc cần để hoàn tất thử nghiệm thật
1. Upload 01 PDF bản vẽ thi công thật vào phiên làm việc. Không commit file này.
2. Chạy lượt 1, rồi để kỹ sư xác nhận tỷ lệ, cấu kiện và phép đo bằng `decisions.json`.
3. (Tuỳ chọn, cần để kết luận độ chính xác) Cung cấp bảng QS thủ công của chính bản vẽ đó.
4. Chạy lượt 2, sau đó `scripts/check.sh`.
