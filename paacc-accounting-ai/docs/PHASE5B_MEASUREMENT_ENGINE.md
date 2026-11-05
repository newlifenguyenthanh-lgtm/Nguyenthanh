# Phase 5B – Deterministic Measurement Engine

**Trạng thái:** đã triển khai trong commit 5B. Trước commit này repository **chưa có** 5B, dù yêu cầu Phase 5C mô tả là "vừa triển khai". 5B được làm tối thiểu, đủ cho chuỗi TEXT → GEOMETRY → MEASUREMENT của 5C.

## Thành phần
- **`app/geometry/measure.py`** (thuần, Decimal, không LLM): `length`, `perimeter`, `area`, `count`, `distance` (tâm–tâm), `spacing` (trung bình các khoảng liên tiếp theo trục chính, kèm độ lệch và cờ `uniform`).
- **Chọn tỷ lệ (`choose_scale`):**
  1. Vùng tỷ lệ **đã xác nhận** chứa *toàn bộ* đối tượng; nếu có nhiều vùng thì chọn vùng nhỏ nhất.
  2. Nếu không có vùng nào, dùng tỷ lệ cả trang đã được kỹ sư hiệu chuẩn (Phase 4B).
  3. Đối tượng vắt qua các vùng khác tỷ lệ → `scale_ambiguous`.
  4. Chưa xác nhận hoặc trang N.T.S. → `scale_unconfirmed`. Vẫn lưu giá trị trên giấy, còn giá trị thật để trống kèm lý do.
- **Công thức quy đổi:** pt × 25,4/72 mm × N (diện tích thì nhân bình phương), làm tròn ROUND_HALF_UP: chiều dài 0,001 m, diện tích 0,0001 m². Cột lưu `Numeric(24,6)`.
- **`scale_regions`:** page, bbox, tỷ lệ, nhãn, trạng thái `candidate → confirmed | rejected` (loại bỏ phải có lý do), có audit.
- **`measurements`:**
  - Dữ liệu đo: kind, geometry_ids, giá trị giấy và thật, đơn vị, tỷ lệ cùng nguồn của nó (`page` hoặc `region:<id>`), công thức, chi tiết, phiên bản phương pháp.
  - Trạng thái `computed → confirmed | rejected`, có audit. Không xác nhận được khi chưa có giá trị thật. Không đo trên hình học đã bị loại hoặc là bản trùng.
- **API:**
  - `POST/GET /drawings/{id}/scale-regions`
  - `POST /scale-regions/{id}/confirm|reject`
  - `POST /measurements`
  - `GET /measurements/{id}`
  - `GET /drawings/{id}/measurements`
  - `POST /measurements/{id}/confirm|reject`
- **Migration:** `0010`.

## Kiểm chứng
- Synthetic: giá trị tính tay chính xác (720 pt ở 1:100 = 25,400 m; hình vuông 72 pt ở 1:100 = 6,4516 m²; ưu tiên vùng 1:20 hoặc 1:50; tỷ lệ hỗn hợp bị từ chối), có test PostgreSQL.
- PDF thật (báo giá R1): không có tỷ lệ, nên chỉ đo được trên giấy; không đo thử kích thước thật.
- Bản vẽ thi công thật: **chưa có dữ liệu**.

## Chưa làm (sau 5B)
- Cờ z-order "có thể bị che".
- Viewport PDF.
- UI vẽ vùng tỷ lệ bằng chuột: hiện nhập bbox qua API.
- Đo cung tròn dùng `length` của `circle`/`curve`; độ dài cung chưa tách riêng.
