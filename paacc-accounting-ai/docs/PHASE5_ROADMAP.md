# Phase 5 – Lộ trình

**Trạng thái:**
- 5A: xong
- 5B: xong
- 5C: xong, còn chờ kiểm chứng trên bản vẽ thi công thật
- 5D: xong, còn chờ kiểm chứng trên bản vẽ thi công thật
- 5E-1 (nền tảng Quantity Engine): xong (xem PHASE5E_QUANTITY_FOUNDATION.md)
- 5E-2 (quy tắc khối lượng tất định + demo chạy được): xong (xem PHASE5E2_QUANTITY_RULES.md); 5F chưa bắt đầu (chờ review)

| Milestone | Nội dung | Trạng thái | Phụ thuộc dữ liệu thật |
|---|---|---|---|
| **5A** Trích xuất hình học vector | primitive, hệ toạ độ, hình chữ nhật mảnh → line, trùng lặp/chồng lấn, `raster_only`, API, lớp phủ UI + review, chỉ số phòng Kỹ thuật, golden geometry | **Xong** (commit 5A) | R1: 94/94 đối chiếu raster |
| **5A.1** | Phát hiện mã hoá TCVN3/VNI/UTF-8 lỗi trên text trích xuất (không tự sửa; cờ trên mục + cảnh báo trang) | **Xong** | W4: 8/9 phát hiện, 0 dương tính giả trên W1–W3; chuyển đổi chờ bảng mã kiểm chứng |
| **5B** Measurement engine | `scale_regions` (nhiều tỷ lệ trên 1 trang, do kỹ sư xác nhận); đo chiều dài/polyline/cung/chu vi/diện tích/đếm/khoảng cách/bước lặp bằng Decimal; bảng `measurements`; "có thể bị che" (z-order); xác nhận/sửa số đo trong UI | **Xong** (tối thiểu, xem PHASE5B_MEASUREMENT_ENGINE.md); z-order + UI vẽ vùng tỷ lệ còn lại | cần bản vẽ có tỷ lệ |
| **5C** Association + lý trình | khối chữ (`drawing_text_blocks`, giữ chữ gốc) + phân loại rule-based; liên kết chữ ↔ hình học (lưới không gian, khoảng cách/hướng/chiếu/ngữ nghĩa, xếp hạng); `AMBIGUOUS` khi điểm thấp hoặc 2 ứng viên sát nhau; `CONFLICT` khi chữ ≠ hình học đo trên tỷ lệ đã xác nhận; khoảng lý trình chỉ khi đúng 2 lý trình gắn cùng một hình học; review + lịch sử đổi hình học; lớp phủ UI | **Xong** (xem PHASE5C_TEXT_GEOMETRY_ASSOCIATION.md). **Chưa kiểm chứng trên bản vẽ thi công thật.** Còn lại: đường gióng, trái/phải tuyến, liên kết chéo trang | W4 (lý trình) + bản vẽ tuyến |
| **5D** Nhận dạng cấu kiện | taxonomy mở rộng (dữ liệu, 37 loại), mẫu ký hiệu, 10 quan hệ không gian, dãy lặp (đều / không đều / bị che, không nội suy), gộp biểu diễn trùng, mặt bằng↔chi tiết (`REPRESENTATION_OF` / `DETAILED_IN` / `REFERENCES`), 7 điểm bằng chứng riêng, state machine + review + audit, bàn giao 5E ở dạng nháp (tham chiếu phép đo), AI task + chỉ số văn phòng, lớp UI [Cấu kiện] | **Xong** (xem PHASE5D_COMPONENT_RECOGNITION.md). **Chưa kiểm chứng trên bản vẽ thi công thật (chưa có dữ liệu).** | cần bản vẽ ATGT/hạ tầng |
| **5E-1** Nền tảng Quantity Engine | `quantity_results` có phiên bản; bảng đơn vị duy nhất; Decimal + làm tròn tường minh một lần; 7 phương pháp (tham chiếu phép đo 5B, COUNT_X_LENGTH, LENGTH_X_UNIT_WEIGHT); chỉ cấu kiện CONFIRMED; phép đo chưa xác nhận → REQUIRES_REVIEW/BLOCKED; provenance; review + audit | **Xong** | – |
| **5E-2** Quy tắc khối lượng | registry quy tắc (dữ liệu, kiểm tra theo phương pháp 5E-1); COUNT / LENGTH / AREA / COUNT × UNIT_LENGTH / LENGTH × UNIT_WEIGHT; tham số bắt buộc có nguồn; diễn giải công thức từ Decimal; chống trùng (biểu diễn, cùng phép đo); chạy cả bản vẽ; khu "Khối lượng" trên UI; demo `python -m app.quantity.demo [--pipeline]` | **Xong** | – |
| 5F Geometry → BOQ (**chưa bắt đầu, chờ review 5E-2**) | ứng viên khối lượng từ phép đo đã xác nhận → `generate.py` (nguồn "geometry"), provenance đầy đủ, trùng lặp mặt bằng/chi tiết, xuất Excel 2 layout | Kế hoạch | đối chiếu W4 |
| 5G Scan / CV (trước đây ghi 5F) | vector hoá raster, dò ký hiệu bằng ML, chỉ khi có dữ liệu huấn luyện có nhãn | Kế hoạch (dài hạn) | bộ dữ liệu có nhãn |

## Phân tầng nhận dạng cấu kiện (5D)

Đã triển khai tầng 1 (deterministic) và tầng 2 (rule-based). Tầng 5 (Human) là review bắt buộc. Tầng 3 (CV) và tầng 4 (LLM) chưa làm; LLM, nếu sau này có, chỉ được tạo ứng viên `ai_inferred`.

| Cấu kiện | Tầng | Cách làm dự kiến |
|---|---|---|
| Tôn lượn sóng / hộ lan | 2 Rule-based | polyline dọc tuyến + nhãn "tôn sóng" + lý trình đầu/cuối → chiều dài; số tấm = ⌈L / chiều dài hữu dụng⌉ (tham số do kỹ sư xác nhận) |
| Hàng rào B40 | 2 Rule-based | polyline + nhãn; số panel = L / khổ panel (tham số xác nhận) |
| Cọc / trụ / cột biển lặp lại | 2 Rule-based → 3 CV | cụm ký hiệu giống nhau (cùng hình học tương đối) → đếm, bước = khoảng cách trung bình; CV nếu ký hiệu raster |
| Biển báo | 2 + 4 | ký hiệu + mã QCVN 41 (Phase 4.1) gần nhau; LLM chỉ để diễn giải chú thích lạ |
| Vạch sơn | 2 | vùng tô/khép kín + nhãn "vạch 1.1/3.1a…" → diện tích |
| Dầm / móng / cống / rãnh | 2 + 5 | hình chữ nhật/đa giác + kích thước ghi + mặt cắt; kỹ sư xác nhận |
| Thép / bulông | 1 Deterministic (bảng) / 5 | từ bảng thống kê (Phase 4) là chính; hình học chỉ để đối chiếu |
| Cấu kiện lặp lại bất kỳ | 2 | so khớp chữ ký hình học (số đỉnh, tỷ lệ cạnh, chuẩn hoá xoay) |
| Chú thích tự do, ký hiệu lạ | 4 LLM-assisted | chỉ gợi ý `ai_inferred`, không tính số |
| Mọi trường hợp điểm số thấp / mâu thuẫn | 5 Human | `AMBIGUOUS` / `CONFLICT` → review |

**Backlog kỹ thuật:**
- R-tree hoặc PostGIS cho truy vấn không gian khi > 10⁶ primitive.
- Worker Celery cho PDF > 100 trang.
- Viewport/khung nhìn PDF.
- Đơn giản hoá đường cong cho UI ở mức zoom thấp.
- Phân trang lớp phủ khi > 20.000 primitive/trang.
