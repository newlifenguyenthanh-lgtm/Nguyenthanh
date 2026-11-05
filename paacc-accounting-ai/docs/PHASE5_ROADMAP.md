# Phase 5 – Lộ trình

| Milestone | Nội dung | Trạng thái | Phụ thuộc dữ liệu thật |
|---|---|---|---|
| **5A** Trích xuất hình học vector | primitive, hệ toạ độ, hình chữ nhật mảnh → line, trùng lặp/chồng lấn, `raster_only`, API, lớp phủ UI + review, chỉ số phòng Kỹ thuật, golden geometry | **Xong** (commit 5A) | R1: 94/94 đối chiếu raster |
| 5A.1 | Phát hiện mã hoá TCVN3/VNI/lỗi font trên text trích xuất (không tự sửa) | Tiếp theo | W4 (text TCVN3 thật) |
| 5B Measurement engine | `scale_regions` (nhiều tỷ lệ trên 1 trang, do kỹ sư xác nhận); đo chiều dài/polyline/cung/chu vi/diện tích/đếm/khoảng cách/bước lặp bằng Decimal; bảng `measurements`; "có thể bị che" (z-order); xác nhận/sửa số đo trong UI | Kế hoạch | cần bản vẽ có tỷ lệ |
| 5C Association + lý trình | dimension text ↔ đường kích thước (gần nhất + hướng + kẹp giữa 2 đường gióng); nhãn/quy cách/tham chiếu ↔ đối tượng; parse `Km a+bbb`, khoảng, trái/phải, hướng tuyến; `AMBIGUOUS` khi điểm số thấp; `CONFLICT` khi lý trình ≠ hình học | Kế hoạch | W4 (lý trình) + bản vẽ tuyến |
| 5D Nhận dạng cấu kiện | xem bảng phân tầng bên dưới | Kế hoạch | cần bản vẽ ATGT/hạ tầng |
| 5E Geometry → BOQ | ứng viên khối lượng từ phép đo đã xác nhận → `generate.py` (nguồn "geometry"), provenance đầy đủ, trùng lặp mặt bằng/chi tiết, xuất Excel 2 layout | Kế hoạch | đối chiếu W4 |
| 5F Scan / CV | vector hoá raster, dò ký hiệu bằng ML, chỉ khi có dữ liệu huấn luyện có nhãn | Kế hoạch (dài hạn) | bộ dữ liệu có nhãn |

## Phân tầng nhận dạng cấu kiện (5D)

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
