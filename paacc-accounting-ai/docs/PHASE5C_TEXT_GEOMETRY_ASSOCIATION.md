# Phase 5C – Liên kết chữ ↔ hình học (Text ↔ Geometry Association)

**Trạng thái:** đã triển khai; **chưa kiểm chứng trên bản vẽ thi công thật**.

Phạm vi kiểm chứng:

| Mức | Nội dung |
|---|---|
| Synthetic | Đã kiểm thử đầy đủ (bản vẽ tổng hợp `tests/geometry_helpers.sheet`) |
| Real PDF | Chỉ kiểm chứng các bất biến loại trừ trên R1. R1 là báo giá in từ Excel, **không phải bản vẽ** |
| Real construction drawing | **Chưa có dữ liệu** |

## 1. Kiến trúc

```
extracted_items (text, 4A) ─┐
tables / title_block (4B) ──┼─ build_text_blocks ─► drawing_text_blocks (chữ gốc + chuẩn hoá + loại + giá trị + cờ)
encoding detector (5A.1) ───┘                              │
geometry_primitives (5A) ─────────────────────────────────┤
                                     engine.associate (thuần, không DB)
                                     GridIndex → điểm hình học → điểm ngữ nghĩa → xếp hạng → trạng thái
                                                           │
                                             text_geometry_associations
                                                           │
             check_dimension / chainage_intervals ─► measurements (5B: tỷ lệ đã xác nhận, Decimal)
                                                           │
                    review (confirm / reject / mark-ambiguous / reassign / tạo tay) → chỉ CONFIRMED đi downstream
```

| Module | Vai trò |
|---|---|
| `app/association/classify.py` | Chuẩn hoá, phân loại rule-based, phân tích chiều dài/lý trình. Tái dùng `find_dimensions`, `find_specs`, `find_symbols` (4B) và `detect` (5A.1) |
| `app/association/engine.py` | Engine thuần: chỉ số lưới, điểm số, xếp hạng, trạng thái, chữ lặp. Không có DB, không có LLM, không tính khối lượng |
| `app/association/service.py` | Lưu trữ, chạy lại an toàn, kiểm tra xung đột (dùng engine 5B), khoảng lý trình, review, provenance |
| `app/api/associations.py` | REST API |
| Hook trong `drawings.analysis_hook` | Chạy sau 5A trong cùng task xử lý, trong savepoint. Nếu lỗi, bản vẽ vẫn `processed` và lỗi được ghi vào `geometry_stats.association.error` |

**Không tạo hệ thống trùng lặp.** 5C dùng lại:
- vùng bảng và khung tên của 4B
- bộ phát hiện TCVN3 (5A.1)
- `choose_scale` / `measure` / bảng `measurements` (5B)
- `ai_tasks`, `audit`, phân quyền `drawing:read` / `drawing:write`, cô lập công ty

## 2. Cơ sở dữ liệu

Migration `0011_text_blocks_and_associations` tạo hai bảng: `drawing_text_blocks` và `text_geometry_associations`. Chi tiết cột ở `PHASE5_GEOMETRY_DATA_MODEL.md`.

5C dùng thêm hai giá trị trong `measurements`:
- `kind = chainage_interval`
- `method = chainage-5C` hoặc `geometry-5B.1/assoc-5C`

## 3. API

| Method | Đường dẫn | Quyền |
|---|---|---|
| GET | `/drawings/{id}/pages/{n}/text-blocks?text_type=` | drawing:read |
| GET | `/drawings/{id}/pages/{n}/associations?status=&text_block_id=&geometry_id=` | drawing:read |
| POST | `/drawings/{id}/associations/run` (tạo `ai_task` agent `pdf_drawing`) | drawing:write |
| POST | `/associations`: kỹ sư tạo tay (`text_block_id`, `geometry_id`, `association_type`, `reason` bắt buộc) | drawing:write |
| GET | `/associations/{id}`: kèm `provenance` TEXT → ASSOCIATION → GEOMETRY → MEASUREMENT và `downstream_allowed` | drawing:read |
| PATCH | `/associations/{id}`: đổi hình học (`geometry_id`, `reason` bắt buộc), ghi `history` | drawing:write |
| POST | `/associations/{id}/confirm`: cần `note` nếu đang CONFLICT/AMBIGUOUS | drawing:write |
| POST | `/associations/{id}/reject`: `note` bắt buộc | drawing:write |
| POST | `/associations/{id}/mark-ambiguous`: `note` bắt buộc | drawing:write |
| GET | `/measurements/{id}/associations` | drawing:read |

Mọi thao tác ghi đều được audit.

## 4. UI

Trang chi tiết bản vẽ có các lớp bật/tắt: **[Chữ] [Liên kết] [Phép đo] [Xung đột]**, cùng ô "Hiện hình học vector" sẵn có.
- Khi chưa bật lớp nào, UI không gọi API 5C.
- **Bấm vào chữ:** hiện `AssociationPanel` với:
  - chữ gốc, dạng chuẩn hoá, cờ, nghi vấn mã hoá
  - ứng viên xếp hạng: điểm, khoảng cách, góc, lý do
  - dòng **Chữ: X m · Hình học: Y m · Chênh: Z m**
  - các nút: Chấp nhận / Loại bỏ / Đánh dấu mơ hồ / Chọn hình học khác (bấm hình học trên trang để gán lại; lý do lấy từ ô ghi chú)
- **Bấm vào hình học:** liệt kê các chữ gắn với hình học đó.
- **Bản vẽ lớn:**
  - Đường liên kết chỉ vẽ cho lựa chọn hiện tại.
  - Khi tắt lớp hình học, chỉ vẽ hình học của liên kết đang chọn.
  - Lớp "Xung đột" riêng chỉ vẽ chữ đang xung đột và nhãn `≠ chữ / hình học`.

## 5. Thuật toán liên kết

1. **Loại trừ:**
   - Chữ có loại TABLE, TITLE, REVISION, SCALE, OTHER, UNKNOWN không được liên kết.
   - Chữ và hình học nằm trong vùng bảng hoặc khung tên bị loại. Đường kẻ bảng và khung tên không phải đối tượng bản vẽ.
   - Hình học bị loại bỏ hoặc là bản trùng (5A) không tham gia.
2. **Ứng viên thô:**
   - `GridIndex`: lưới đều, ô 64 pt, phủ lên bbox hình học.
   - Mỗi chữ chỉ truy vấn trong cửa sổ bán kính `r = clamp(4 × cỡ chữ, 20, 80) pt`.
   - Không bao giờ so một chữ với toàn bộ hình học. Test: 2001 hình học, dưới 10 lần chấm điểm.
3. **Điểm hình học:**
   - **Khoảng cách:** từ **khung chữ** tới đoạn gần nhất (bằng 0 khi chạm hoặc cắt). `s_d = 1 − d/r`.
   - **Hướng:** góc giữa đoạn và chữ (có tính xoay của chữ và của trang). `s_o = 1 − min(Δ, 90)/90`.
   - **Chiếu:** tỷ lệ phần khung chữ chiếu được lên đoạn (`s_p`).
   - **Quan hệ:** chữ nằm trên, dưới, trái, phải hoặc trong hình học.
4. **Điểm ngữ nghĩa** theo bảng `SEMANTIC[loại liên kết][loại hình học]`. Ví dụ:
   - DIMENSION_OF ↔ line/polyline = 1.0
   - REFERENCE_TO chỉ ↔ circle / polygon / rect
5. **Điểm tổng:** `w_d·s_d + w_o·s_o + w_p·s_p + w_s·sem`. Trọng số `WEIGHTS` riêng cho từng loại. Lý trình đánh dấu một **điểm** trên tuyến nên ít dựa vào phép chiếu.
6. **Xếp hạng:** giữ tối đa top 3 ứng viên có điểm ≥ 0,20.
7. **Chữ lặp:** cùng chữ chuẩn hoá, cùng loại, cùng hình học hạng 1. Ứng viên điểm cao nhất là bản chính; các bản khác có `duplicate_of`, không tạo phép đo và không được xác nhận riêng (409).

Loại liên kết theo loại chữ:

| Loại chữ | Loại liên kết |
|---|---|
| LENGTH / DIMENSION / AREA / COUNT | DIMENSION_OF |
| CHAINAGE | CHAINAGE_FOR |
| LABEL | LABEL_OF |
| MATERIAL / SPECIFICATION | MATERIAL_OF |
| NOTE | NOTE_FOR |
| DETAIL_REFERENCE | REFERENCE_TO, chỉ trong cùng trang |

`SCALE_FOR` và `UNKNOWN` chỉ do kỹ sư tạo. Tỷ lệ vẫn đi qua hiệu chuẩn 4B và vùng tỷ lệ 5B.

## 6. Điểm tin cậy và trạng thái

Ngưỡng cấu hình qua `PAACC_ASSOC_*`:
- `assoc_auto_threshold = 0.90`
- `assoc_review_threshold = 0.70`
- `assoc_margin = 0.10`

| Điều kiện (ứng viên hạng 1) | Trạng thái |
|---|---|
| Hạng 2 cách hạng 1 dưới `margin` | AMBIGUOUS cho cả hai |
| ≥ 0,90 | CANDIDATE ("auto candidate", **vẫn cần kỹ sư xác nhận**) |
| 0,70 – 0,89 | REVIEW_REQUIRED |
| < 0,70 | AMBIGUOUS |
| Chữ có cờ `ambiguous_number`, `unit_case_ambiguous`, `ENCODING_UNKNOWN` | AMBIGUOUS |
| Chữ ≠ hình học (mục 7) | CONFLICT |

Các ứng viên hạng ≥ 2 là "Phương án thay thế". **Không có trạng thái nào tự thành CONFIRMED**; chỉ kỹ sư xác nhận. Khi xác nhận một liên kết, các ứng viên cùng loại của cùng chữ tự chuyển sang REJECTED, kèm audit `auto_reject`.

Điểm là heuristic float. Nó không phải số lượng và không bao giờ đi vào phép tính khối lượng.

## 7. Phát hiện xung đột

- **DIMENSION_OF hạng 1** (không AMBIGUOUS, không phải chữ lặp):
  - `text_value` lấy từ chữ đã quy về mét (Decimal).
  - Hình học được đo bằng `measure("length")` của 5B, chỉ trên **tỷ lệ đã xác nhận** (vùng tỷ lệ hoặc trang).
  - Chưa có tỷ lệ: không so sánh. Lý do ghi "chưa có tỷ lệ xác nhận".
  - Có tỷ lệ: tạo hoặc dùng lại một `measurement` 5B, ghi `measured_value` và `difference`.
  - Dung sai = max(0,01 m; 0,5 % × chữ). Vượt dung sai thì CONFLICT với lý do `Chữ: X m · Hình học: Y m · Chênh: Z m – không tự sửa`.
- **Không bao giờ tự sửa** chữ, hình học hay tỷ lệ. Xác nhận một CONFLICT bắt buộc có ghi chú của kỹ sư.
- Hình học chọn theo điểm số, **không** theo việc giá trị có khớp hay không. Nếu chọn theo độ khớp, phát hiện xung đột sẽ không còn trung thực.
- Khi kỹ sư đổi hình học, xung đột được tính lại.

## 8. Lý trình

- **Parser:**
  - Hỗ trợ `Km12+350`, `K0+250` và `0+250` (đánh dấu `bare`).
  - Hỗ trợ khoảng `Km0+250 - Km0+500`.
  - Không parse bên trong biểu thức `=(…)`.
  - Giá trị là Decimal mét.
- **Khoảng lý trình** chỉ được tạo khi **đúng 2** liên kết CHAINAGE_FOR hạng 1, không mơ hồ, không lặp, cùng gắn **một** hình học.
  - Tạo `measurement` loại `chainage_interval` (`scale_source = chainage`).
  - Nếu hình học có chiều dài thật trên tỷ lệ đã xác nhận thì so sánh; lệch vượt dung sai thì cả hai liên kết thành CONFLICT.
- Trường hợp không tạo khoảng:
  - Nhiều hơn 2 lý trình: ghi lý do.
  - Chỉ 1 lý trình, hoặc 2 lý trình trên 2 hình học khác nhau: không đoán.
- Khi chạy lại, các khoảng chưa có ai quyết định được dọn để không tích luỹ trùng.
- **Chưa làm:** trái/phải tuyến, hướng tuyến, lý trình xuyên trang.

## 9. TCVN3 / VNI

- `original_text` luôn là chữ gốc. `normalized_text` không chuyển đổi mã hoá.
- Bộ phát hiện 5A.1:
  - Tin cậy ≥ 0,7: thêm cờ `legacy_encoding`.
  - Thấp hơn: thêm cờ `ENCODING_UNKNOWN`.
- Chữ nghi ngờ mã hoá và không có chữ số được xếp UNKNOWN, nên không được liên kết. Chữ có số nhưng mang `ENCODING_UNKNOWN` bị ép AMBIGUOUS.
- Bỏ sót đã biết từ 5A.1: "Ghi chó" toàn ký tự hợp lệ, không phát hiện được theo từng chuỗi.

## 10. Kiểm thử

| Bộ test | Phạm vi |
|---|---|
| `tests/test_association.py` (45 test, synthetic) | Xem danh sách bên dưới |
| `tests/test_postgres.py::test_associations_on_postgres` | Lưu/đọc Numeric, review, provenance trên PostgreSQL 16 |
| `src/drawings/drawings.test.tsx` (4 test 5C) | Xem danh sách bên dưới |
| `tests/test_golden_dataset.py` (riêng tư, cần `PAACC_GOLDEN_DIR`) | Bất biến 5C trên R1 |

`tests/test_association.py` kiểm:
- Chuẩn hoá: `L=125.50m`, `125,50m`, `12550 mm`, `L=(4700+5200)mm`, `Km12+350`, `0+250`, `D88.3`, `M16x35`, `M16×35`.
- "3M" không phải mét.
- Các loại chữ rule-based; bảng và số trang.
- TCVN3 giữ nguyên.
- Engine:
  - đường gần nhất, cùng hướng thắng
  - chữ xoay
  - 2 đường song song → AMBIGUOUS
  - ngưỡng cấu hình được
  - loại trừ
  - tham chiếu chi tiết chỉ tới hình tròn
  - chữ lặp
  - chỉ số không gian (đếm số lần chấm điểm)
  - không phụ thuộc LLM
- API:
  - khối chữ
  - xử lý chỉ tạo ứng viên
  - khớp kích thước trên tỷ lệ 1:100
  - xung đột 13,5 / 12,7 / 0,8
  - song song không kiểm tra xung đột
  - khoảng lý trình 250 m so với 8,819 m
  - chạy lại không nhân bản
  - tham chiếu chi tiết; nhãn
  - chữ lặp không đo 2 lần
  - review và tự loại ứng viên cạnh tranh
  - đổi hình học có lịch sử, chạy lại không ghi đè
  - tạo tay
  - provenance; downstream chỉ CONFIRMED
  - cô lập công ty và phân quyền
  - TCVN3 không liên kết
  - lỗi 5C không làm hỏng xử lý bản vẽ

`src/drawings/drawings.test.tsx` kiểm:
- không tải gì khi các lớp tắt
- màu theo trạng thái
- bảng so sánh Chữ / Hình học / Chênh
- chỉ vẽ liên kết của lựa chọn
- từ chối cần lý do
- đổi hình học và xác nhận gửi đúng payload
- lớp xung đột riêng

## 11. Kiểm chứng

| Mức | Kết quả |
|---|---|
| **Synthetic** | Toàn bộ bộ test ở mục 10. Không dùng để tuyên bố độ chính xác thực tế |
| **Real PDF (R1, báo giá 2 trang)** | Xem chi tiết bên dưới |
| **Real construction drawing** | **Chưa kiểm chứng**. Bộ dữ liệu không có bản vẽ thi công nào |

Kết quả trên R1:
- 266 khối chữ. 263 khối thuộc bảng, khung tên, số trang hoặc khác: **0 liên kết** (263/263).
- **0 tự xác nhận.**
- 2 ứng viên: một tiêu đề in hoa → đường kẻ gần, hạng 1 REVIEW_REQUIRED (0,738) và hạng 2. Trên báo giá liên kết này **không có ý nghĩa**. Đây là dương tính giả ở mức ứng viên và không đi downstream nếu không có người xác nhận.
- Không hồi quy: metadata 12/12, dimensions 60/60, materials 7/7, BOQ 50/50, duplicates 38/38, geometry 94/94.
- Gate riêng tư thêm sàn `associations = 263`, trần 2 ứng viên và yêu cầu 0 tự xác nhận.

Chưa thể kết luận gì về độ chính xác liên kết kích thước, lý trình hay nhãn trên bản vẽ thật. Cần 3–5 PDF bản vẽ ATGT/hạ tầng thật, lý tưởng là chính các bản vẽ của workbook W4 (xem `PHASE5_REAL_DRAWING_VALIDATION.md` §4).

## 12. Giới hạn

- Chưa dùng **đường gióng / mũi tên kích thước**. Kích thước chỉ gắn với đường gần nhất.
- Chưa có liên kết chéo trang cho tham chiếu chi tiết. `Xem chi tiết A-A` không có hình học gần thì không có liên kết.
- Chữ nhiều dòng chưa được gộp. Mỗi dòng là một khối chữ.
- Lý trình: chưa có trái/phải, hướng tuyến hay chuỗi nhiều lý trình trên một tuyến (> 2 thì chỉ ghi lý do).
- Điểm số là heuristic với trọng số chọn tay. Chưa được hiệu chỉnh trên dữ liệu thật.
- Nhãn LABEL dựa vào chữ in hoa ≥ 80 %. Ghi chú viết thường không có tiền tố "GHI CHÚ" sẽ thành OTHER.
- OCR (trang quét) đi qua cùng luồng, nhưng chưa được kiểm chứng.
- LLM: chưa có. Thiết kế cho phép `origin = ai_inferred` chỉ ở mức ứng viên. LLM không bao giờ xác nhận và không tính chiều dài, diện tích, khối lượng hay hiệu lý trình.
