# Phase 5 – Geometry: yêu cầu

**Mục tiêu:** chuyển từ `PDF → text/kích thước/bảng → BOQ` sang
`PDF → hình học → đối tượng → đo đạc → khối lượng → BOQ → Excel`. Toàn bộ tính toán là xác định (Decimal), có provenance đầy đủ, và kỹ sư duyệt cuối.

## 0. Bối cảnh dữ liệu thật (đính chính quan trọng)

Phase 4.1 đã kiểm chứng trên **dữ liệu thật**, nhưng bộ dữ liệu đó **không có bản vẽ thi công**:

| Mã | Tài liệu thật | Dùng cho Phase 5 |
|---|---|---|
| R1 | PDF báo giá nhà cung cấp, 2 trang vector, in từ Excel ("Print To PDF") | **Có**: hình học vector thật (đường kẻ bảng in dạng hình chữ nhật tô đặc mảnh, vùng tô, ảnh nhúng) |
| W4 | Workbook khối lượng ATGT (`Tong hop` + sheet theo hạng mục, có lý trình Km) | **Có**: tham chiếu lý trình/khối lượng và text TCVN3 thật cho 5C/5D và phát hiện mã hoá |
| W1–W3 | Workbook báo giá | Tham chiếu định giá (Phase 6) |

Hệ quả cho Phase 5:
- **Kiểm chứng được trên dữ liệu thật:** trích xuất vector, hệ toạ độ, đường kẻ mảnh, trùng lặp/chồng lấn, đối chiếu độc lập raster ↔ vector, và tích hợp BOQ/Excel không hồi quy.
- **Chưa kiểm chứng được trên dữ liệu thật** (không có nguồn): đo chiều dài/diện tích theo tỷ lệ bản vẽ, liên kết dimension ↔ đường kích thước, lý trình trên mặt bằng tuyến, nhận dạng cấu kiện hạ tầng.
- **Ma trận năng lực** (xem `PHASE5_REAL_DRAWING_VALIDATION.md`): ô nào chỉ có dữ liệu tổng hợp thì không bao giờ được ghi "PASS (thật)".
- **Dữ liệu thật** nằm trong golden dataset riêng tư, ngoài git (`test-data/golden-dataset/`, hash `63fad3b75aa2…`). Repo chỉ có cấu trúc, schema và báo cáo đã che.

## 1. Yêu cầu chức năng

| ID | Yêu cầu | Milestone |
|---|---|---|
| G-1 | Trích xuất primitive vector: line, polyline, polygon, rect, vùng tô, curve, circle; layer (OCG) nếu có | 5A |
| G-2 | Hình chữ nhật tô đặc mảnh → đường tâm (`derived_from`), không mất thông tin gốc | 5A |
| G-3 | Hệ toạ độ: PDF → trang (CropBox) → hiển thị (Rotation) → giấy (mm) → thực (tỷ lệ đã xác nhận) | 5A |
| G-4 | Trùng lặp hình học (vẽ 2 lần), chồng lấn thẳng hàng: gắn cờ, không xoá | 5A |
| G-5 | Trang scan: `raster_only`, **không** tạo hình học giả | 5A |
| G-6 | Kỹ sư xác nhận / loại bỏ / đánh dấu "không rõ" từng primitive (bắt buộc lý do), audit | 5A |
| G-7 | Đo: chiều dài line/polyline/arc, chu vi, diện tích, đếm, khoảng cách, bước lặp | 5B |
| G-8 | Text ↔ geometry: dimension ↔ đường kích thước, nhãn ↔ đối tượng, lý trình ↔ hình học, `AMBIGUOUS` khi không chắc | 5C |
| G-9 | Lý trình Km: parse, khoảng, trái/phải tuyến, hướng; mâu thuẫn hình học ↔ lý trình → `CONFLICT` | 5C/5D |
| G-10 | Nhận dạng cấu kiện hạ tầng (cọc, trụ, lan can, hàng rào, tôn sóng, biển, cống, rãnh, móng…) | 5D |
| G-11 | Geometry → BOQ qua Decimal engine, provenance `bản vẽ → trang → vùng → geometry id → phép đo → quy tắc → khối lượng` | 5E |
| G-12 | Bản vẽ scan / CV-ML (chỉ khi có dữ liệu huấn luyện) | 5F |
| G-13 | Phát hiện mã hoá TCVN3 / VNI / lỗi font; giữ nguyên bản gốc, không tự sửa khi độ tin cậy thấp | 5A.1 |

## 2. Yêu cầu phi chức năng
- **Không LLM tính toán:** LLM không tham gia đo đạc hay tính khối lượng. Nếu sau này dùng, LLM chỉ được gợi ý ngữ nghĩa và đánh dấu `ai_inferred`.
- **Decimal, toạ độ chính xác:** dùng Decimal cho mọi phép đo. Toạ độ lưu dạng chuỗi thập phân, chính xác 0,01 pt (≈0,0035 mm trên giấy).
- **Kích thước thật bị chặn:** không có kích thước thật nếu tỷ lệ trang chưa được kỹ sư xác nhận; trang N.T.S. không bao giờ cho ra kích thước thật.
- **Quy mô:**
  - Hơn 100 trang mỗi PDF, với đơn vị xử lý là từng trang.
  - Giới hạn 200.000 item vector mỗi trang; vượt ngưỡng thì gắn `too_complex`, không treo.
  - Lỗi ở một trang không làm hỏng các trang khác.
- **Tiến độ:** đi qua `ai_tasks` hiện có. Kiến trúc đã sẵn để chuyển sang worker (Redis/Celery).
- **Đa công ty:** cô lập theo `company_id` ở mọi truy vấn và API.
- **Bảo mật dữ liệu:** không commit tài liệu thật hay dữ liệu suy ra từ chúng.
