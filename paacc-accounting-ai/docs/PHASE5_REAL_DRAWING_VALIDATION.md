# Phase 5 – Kiểm chứng trên dữ liệu thật

## 1. Nguồn và cách chạy
- **Dữ liệu:** golden dataset riêng tư, ngoài git, mô tả trong `test-data/golden-dataset/README.md`.
  - Tài liệu thật R1: PDF báo giá 2 trang vector, `sha256 63fad3b75aa2…`.
  - Tham chiếu W4: workbook khối lượng ATGT.
- **Không có bản vẽ thi công** trong bộ dữ liệu được cung cấp. Xem `PHASE5_GEOMETRY_REQUIREMENTS.md` §0.
- **Chạy:**
  ```bash
  python -m tools.golden_run …
  ```
  ```bash
  python -m tools.golden_compare …
  ```
  ```bash
  PAACC_GOLDEN_DIR=… pytest tests/test_golden_dataset.py
  ```
- **Kỳ vọng hình học của R1** được sinh bằng kênh raster độc lập (`tools/raster_lines.py`: 288 dpi, ngưỡng mực 200, đường ≥ 15 pt, nối khe ≤ 1,5 pt), rồi soát lại thủ công. Loại trừ duy nhất: 4 đường nằm trong ảnh con dấu/chữ ký nhúng, là nội dung raster nên đúng ra không có vector.
- **Ngưỡng regression riêng tư:** metadata 12, dimensions 60, materials 7, BOQ 50, duplicates 38, geometry 94, associations 263 (bất biến loại trừ 5C), components 263 (bất biến loại trừ 5D, trần 0 ứng viên). Gate cũng yêu cầu 0 liên kết tự xác nhận và số ứng viên không vượt mức đã soát (2).

## 2. Ma trận năng lực (sau 5A)

"Real" = đã đo trên tài liệu thật R1/W4. "Synthetic" = chỉ có PDF tổng hợp. Ô synthetic **không bao giờ** được ghi PASS (thật).

| Năng lực | Tài liệu thật | Kỳ vọng | Thực tế | Trạng thái |
|---|---|---|---|---|
| Trích xuất vector (primitive) | R1, 2 trang | 449 line + 4 vùng tô (từ 453 item `re`) | 449 line (đều `filled_hairline_rect`) + 4 `fill_region`; 0 trùng lặp; 0 chồng lấn | **PASS (thật)** |
| Đối chiếu vector ↔ raster độc lập | R1 | 94 đường trục (49 + 45) sau loại trừ có lý do | 94/94 khớp, 0 đường chỉ có ở vector | **PASS (thật)** |
| Hệ toạ độ: rotation / CropBox | R1 không xoay, CropBox = MediaBox | – | đúng trên R1; xoay 90° và CropBox lệch chỉ kiểm bằng synthetic | Real: một phần; Synthetic: đã test |
| Trang scan → `raster_only`, không có hình học giả | (không có trang scan thật) | – | synthetic | Chưa kiểm chứng thật |
| Trích xuất kích thước (text) | R1 | 60 token | 60/60 (Phase 4.1, không hồi quy) | **PASS (thật)**, text, không gắn hình học |
| Đo chiều dài line | R1 (chiều dài trên giấy) | chiều dài đường kẻ bảng = khoảng cách 2 đầu | khớp kênh raster trong ±2 pt ở đầu mút | Real: chỉ chiều dài **trên giấy**; chưa có kích thước thật (R1 không có tỷ lệ) |
| Đo polyline | – | – | synthetic (150 pt chính xác) | Chưa kiểm chứng thật (5B) |
| Lý trình (chainage) | W4 có lý trình dạng text trong Excel, không có bản vẽ | – | parser + khoảng lý trình (5C) chỉ test synthetic | Synthetic: đã test. Real construction drawing: **chưa kiểm chứng** |
| Liên kết chữ ↔ hình học (5C) – bất biến | R1 (báo giá, **không phải bản vẽ thi công**) | 263 khối chữ bảng/khung tên/số trang/tỷ lệ/khác: 0 liên kết; 0 tự xác nhận | 263/263; 0 tự xác nhận; 2 ứng viên (1 tiêu đề in hoa → đường kẻ gần, trạng thái REVIEW_REQUIRED, không có nghĩa trên báo giá) | **PASS (Real PDF)** chỉ cho bất biến loại trừ. Độ chính xác liên kết trên bản vẽ thật: **chưa kiểm chứng** |
| Liên kết chữ ↔ hình học (5C) – độ chính xác | – | – | chỉ synthetic (`geometry_helpers.sheet`) | Chưa kiểm chứng thật |
| Nhận dạng cấu kiện (5D) – bất biến | R1 (báo giá, **không phải bản vẽ thi công**) | 0 cấu kiện từ chữ bảng / khung tên / số trang; 0 tự xác nhận | 263/263; 0 ứng viên; 0 tự xác nhận | **PASS (Real PDF)** chỉ cho bất biến loại trừ |
| Nhận dạng cấu kiện (5D) – độ chính xác | – | – | chỉ synthetic (`tests/component_helpers.py`) | Real construction drawing: **NOT AVAILABLE** – không tuyên bố độ chính xác |
| Phát hiện trùng lặp hình học | R1 | 0 trùng lặp thật | 0 | PASS (thật), nhưng chỉ có trường hợp âm tính; dương tính mới có synthetic |
| Phát hiện trùng lặp BOQ | R1 | 38 trường hợp | 38/38 (Phase 4.1) | PASS (thật) |
| Tích hợp BOQ (từ geometry) | – | – | chưa triển khai (5E) | Chưa có |
| BOQ / Excel không hồi quy khi bật 5A | R1 | 50 dòng; export 2 layout | 50/50; xuất cả 2 layout | **PASS (thật)** |
| Mã hoá TCVN3/VNI (5A.1, chỉ phát hiện) | W4 + W1–W3, ~31.000 chuỗi | 9 chuỗi TCVN3 trong W4 (soát toàn bộ chuỗi có thể là TCVN3); 0 trong W1–W3 | phát hiện 8/9 (độ phủ), 8/8 đúng (độ chính xác), 0 dương tính giả trên W1–W3; bỏ sót "Ghi chó" (= "Ghi chú", toàn ký tự hợp lệ) | **PASS (thật)** cho phát hiện; chuyển đổi chưa làm |

## 3. Phát hiện thật trong 5A
1. **PDF thật không có toán tử `l` (line).** Mọi đường kẻ là hình chữ nhật tô đặc dày 0,12–0,72 pt. Nếu không có quy tắc `filled_hairline_rect`, số hình học trích được bằng 0.
2. **Đường 0,12 pt** khi raster hoá cho ra màu xám khử răng cưa (~187–204). Ngưỡng "đen" kiểu cũ (<110) bỏ sót, nên kênh raster phải dùng ngưỡng mực 200.
3. **Đường kẻ vẽ theo từng ô** (cách nhau 0,6 pt): cần gộp đoạn thẳng hàng (`axis_runs`). Hàm này cũng là nền cho đo lan can/hàng rào vẽ thành nhiều đoạn (5B).
4. **Thứ tự vẽ (z-order):** dải nền xám của dòng tổng được vẽ **đè** lên đường kẻ cột. Vector vẫn liên tục nhưng trên ảnh bị che một phần.
   - Backlog: cờ "có thể bị che".
   - Khối lượng không được dựa vào phần hình học bị che mà không có xác nhận của kỹ sư.
5. **Ảnh nhúng** (con dấu, chữ ký, logo) chứa nét giống đường thẳng. Đó là raster, không phải vector, nên không được coi là hình học bản vẽ.

## 3b. Phát hiện thật trong 5A.1
- Text TCVN3 thật trong workbook khối lượng (ví dụ dạng "VÞ trÝ … vµo"). Ba workbook báo giá là Unicode sạch.
- **Bỏ sót không tránh được bằng phân tích ký tự:** TCVN3 chỉ dùng chữ trông hợp lệ ("Ghi chó"). Cần ngữ cảnh: cả sheet/cột đã là TCVN3, hoặc kiểm tra từ điển. Đây là backlog, có test ghi nhận hành vi hiện tại.
- **Không chuyển đổi** cho tới khi có bảng mã TCVN3/VNI được kiểm chứng trên mẫu thật. Văn bản gốc luôn giữ nguyên, kết quả phát hiện nằm ở `data.encoding` và cảnh báo trang.

## 4. Chiến lược regression với bản vẽ thật
- Mỗi tài liệu thật mới vào golden dataset với kỳ vọng được kiểm chứng độc lập:
  - ảnh render và kênh raster cho hình học
  - đọc tay cho text, kích thước và khối lượng
  - workbook KL cho khối lượng và lý trình
- Mỗi milestone thêm một phần vào file kỳ vọng:
  - `measurements` (5B): chiều dài/diện tích tính tay từ kích thước ghi trên bản vẽ
  - `associations` (5C)
  - `chainage` (5C): lý trình và chiều dài đoạn đối chiếu W4
  - `objects` (5D)
  - `boq_from_geometry` (5E)
- `regression_floor` trong manifest riêng: gate thất bại nếu bất kỳ hạng mục nào giảm.
- **Cần ngay:** 3–5 PDF bản vẽ ATGT/hạ tầng thật (mặt bằng tuyến có lý trình, mặt cắt, chi tiết biển/cột/tôn sóng/hàng rào), lý tưởng là **chính các bản vẽ đã sinh ra workbook W4**, để đo lại khối lượng W4 từ hình học.
