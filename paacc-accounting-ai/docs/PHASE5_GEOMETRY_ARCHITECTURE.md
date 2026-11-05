# Phase 5 – Geometry: kiến trúc

## 1. Luồng tổng thể

```
PDF (bất biến, SHA-256)
 └─ Phase 4A extract (text, bảng, OCR)            app/pdf/extract.py
 └─ Phase 4B analysis (kích thước, quy cách…)     app/pdf/analysis.py
 └─ Phase 5A vector geometry   (xong)            app/geometry/{coords,primitives,service}.py
      page.get_drawings() → primitive (line/polyline/polygon/rect/fill/curve/circle)
      → hệ toạ độ hiển thị → trùng lặp/chồng lấn → geometry_primitives
 └─ 5B measurement engine (Decimal)  (xong)       app/geometry/{measure,measure_service}.py
 └─ 5C association text ↔ geometry, lý trình (xong; chưa kiểm chứng trên bản vẽ thi công thật)
                                                  app/association/{classify,engine,service}.py
 └─ 5D object recognition (rule-based trước)      app/geometry/objects.py
 └─ 5E quantity candidate → BOQ (engine hiện có)  app/boq/generate.py (thêm nguồn "geometry")
 └─ Review → Approval (4 mắt) → Excel (PAACC / company_kl)   (giữ nguyên)
```

**Tái sử dụng, không viết lại:**
- `_disp`/`rotation_matrix` (4A): `PageFrame` dùng chung quy ước.
- Hiệu chuẩn tỷ lệ/đơn vị (4B, chỉ người xác nhận): `coords.real_mm()` từ chối nếu tỷ lệ chưa xác nhận, tương tự `takeoff.measure.real_length_from_paper`.
- `ai_tasks`: geometry chạy trong task xử lý bản vẽ, hoặc task riêng khi trích xuất lại.
- Audit, phân quyền `drawing:read/write`, cô lập công ty.
- Decimal engine, BOQ workflow, Excel: không đổi trong 5A.

## 2. Hệ toạ độ (`app/geometry/coords.py`)

| Không gian | Đơn vị, gốc | Chuyển đổi |
|---|---|---|
| PDF user space | pt, gốc dưới-trái MediaBox, chưa xoay | do content stream định nghĩa |
| PAGE | pt, gốc trên-trái trang chưa xoay, **đã trừ gốc CropBox** | PyMuPDF (đã kiểm chứng bằng test CropBox lệch) |
| **DISPLAY** (lưu trữ) | pt, gốc trên-trái trang đang hiển thị | × `page.rotation_matrix` (0/90/180/270) |
| PAPER | mm trên giấy | × 25,4/72 (Decimal chính xác) |
| REAL | mm/m ngoài thực địa | PAPER × N, **chỉ khi** `scale_status == "confirmed"` |

**Quy ước chung:**
- **Lưu trữ:** toạ độ lưu dạng chuỗi thập phân, làm tròn `ROUND_HALF_UP` tới 0,01 pt. Bbox kiểu float chỉ dùng để lọc theo vùng.
- **Dung sai mặc định:** 0,5 pt cho snap, thẳng hàng và nằm trên trang; 0,05 pt cho nối đoạn.
- **Khung trang:** `drawing_pages.page_frame` lưu rotation, MediaBox, CropBox và ma trận PAGE→DISPLAY, đủ để tái lập mọi phép biến đổi.
- **Chưa hỗ trợ (5B):** viewport trong PDF (nhiều khung nhìn tỷ lệ khác nhau trên một trang) và gốc toạ độ công trình. Một trang có thể có nhiều vùng tỷ lệ (chi tiết 1:20 trong mặt bằng 1:100); 5B sẽ thêm `scale_regions` (bbox + tỷ lệ đã xác nhận), không suy đoán.

## 3. Trích xuất primitive (`primitives.py`)

| Nguồn PDF | Kết quả |
|---|---|
| chuỗi `l` nối liền | `line` (2 điểm) / `polyline` / `polygon` (khép kín) |
| chuỗi có `c` (Bézier) | `curve` (lấy mẫu 32 bước, `approximate=true`) hoặc `circle` (kiểm tra bán kính đều) |
| `re` có viền | `rect` (chu vi, diện tích) |
| `re` chỉ tô, mảnh ≤ 1,5 pt và dài ≥ 4× bề dày | `line` tâm, `derived_from="filled_hairline_rect"` (**phát hiện từ dữ liệu thật R1**) |
| `re` chỉ tô, kích thước lớn | `fill_region` |
| `qu` | `polygon` |

**Xử lý sau khi trích xuất:**
- Cờ `outside_page` cho primitive nằm ngoài trang.
- Trùng lặp (cùng hình học trong 0,1 pt, kể cả đảo chiều) → `duplicate_of`.
- Chồng lấn thẳng hàng (line trục ngang/dọc) → `overlaps` và cờ `collinear_overlap`.
- `axis_runs()` gộp các đoạn liền nhau (khe ≤ 1,5 pt) thành một đường. Đây chỉ là *khung nhìn phân tích*: dữ liệu gốc không bị thay đổi.

**Trạng thái trang:** `extracted`, `no_vector_geometry`, `raster_only` (scan), `too_complex` (> 200.000 item), `failed` (lỗi riêng trang đó).

## 4. Provenance (geometry → BOQ)

```
drawing (sha256, document_version) → page_no (page_frame) → bbox/region
 → geometry_primitive.id (path_index, item_index, derived_from)
 → text block → association (5C: chữ gốc, loại, điểm số, trạng thái review; chỉ CONFIRMED đi tiếp)
 → measurement (5B: phép đo, đơn vị, tỷ lệ đã xác nhận, người xác nhận)
 → rule (5D/5E: quy tắc nhận dạng + tham số)
 → quantity candidate → boq_item (inputs[].source_geometry_ids, origin)
```
- 5A cung cấp hai mắt xích đầu (đến geometry id và nguồn trong content stream).
- 5C nối TEXT → ASSOCIATION → GEOMETRY → MEASUREMENT (`GET /associations/{id}` trả cả chuỗi). Xem `PHASE5C_TEXT_GEOMETRY_ASSOCIATION.md`.
- Từ 5E, `boq_items.inputs.*.source_item_id` được mở rộng thêm `source_geometry_ids`. Không tạo bảng BOQ mới.

## 5. Hiệu năng và mở rộng
- **Đo trên dữ liệu thật:** R1 (2 trang, 453 item) mất 0,33 s cho riêng phần trích xuất.
- **Lưu trữ:** chèn hàng loạt theo trang. Index trên `drawing_id`, `page_no`, `kind`, `company_id`; lọc theo vùng bằng bbox (5B có thể thêm R-tree/PostGIS nếu cần).
- **Đơn vị công việc:** `extract_page_geometry(page)` là thuần tuý. Service chỉ cần `(drawing_id, user)`, nên chuyển sang Celery chỉ cần bọc `run_extraction`. Tiến độ ghi vào `ai_tasks` (mỗi trang cập nhật `output_summary`).
- **Bản vẽ CAD rất nặng:** áp ngưỡng `MAX_PRIMITIVES_PER_PAGE`; trang vượt ngưỡng được đánh dấu để xử lý nền.

## 6. Kiểm chứng độc lập (`tools/raster_lines.py`)
- Raster hoá trang ở 288 dpi rồi dò đường ngang/dọc bằng numpy. Kênh này không đọc toán tử vector, nên khớp với vector là bằng chứng thật, không phải kiểm tra vòng tròn.
- Áp cùng quy tắc nối khe 1,5 pt cho cả hai phía.
- Loại trừ các đường nằm trong ảnh nhúng (con dấu/chữ ký).

## 7. Mã hoá chữ Việt cũ (TCVN3/VNI) – 5A.1
- Phát hiện mã hoá trên text đã trích xuất: `unicode` / `tcvn3` / `vni` / `garbled`, kèm độ tin cậy.
- **Không sửa tự động.** Văn bản gốc luôn được giữ nguyên.
- Chuyển đổi chỉ được làm khi đã có bảng mã kiểm chứng trên mẫu thật.

## 8. Trạng thái Phase 5

- **5A:** xong (vector geometry).
- **5B:** xong (tối thiểu).
- **5C:** xong. Còn chờ kiểm chứng trên bản vẽ thi công thật, vì bộ dữ liệu hiện tại chỉ có báo giá PDF và workbook.
