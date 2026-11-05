# Phase 5D – Nhận dạng cấu kiện (Component Recognition Engine)

**Trạng thái:** đã triển khai. **Chưa kiểm chứng trên bản vẽ thi công thật** vì hiện **chưa có dữ liệu** (xem §17).

5D trả lời câu hỏi: *"Đây là cấu kiện gì, và bằng chứng nào cho nhận dạng đó?"* 5D **không** tính khối lượng, **không** tạo BOQ chính thức và **không** tự xác nhận.

```
PDF → TEXT (4A/5C) → GEOMETRY (5A) → MEASUREMENT (5B) → TEXT↔GEOMETRY (5C) → COMPONENT CANDIDATE (5D)
    → ENGINEER REVIEW → CONFIRMED COMPONENT → (5E) QUANTITY ENGINE → BOQ → EXCEL
```

## 1. Kiến trúc

| Module | Vai trò |
|---|---|
| `app/components/catalog.json` | Taxonomy, quy tắc nhận dạng và mẫu ký hiệu mặc định. Đây là **DỮ LIỆU**, không phải code |
| `app/components/spatial.py` | Lưới không gian và 10 quan hệ không gian (thuần, float, heuristic) |
| `app/components/symbols.py` | So khớp mẫu ký hiệu trên primitive vector (không dùng CV) |
| `app/components/repetition.py` | Phát hiện dãy lặp: dọc tuyến (carrier) hoặc hàng thẳng. Dãy không đều thành IRREGULAR_PATTERN, bị che thành OCCLUDED. **Không nội suy** |
| `app/components/engine.py` | Engine nhận dạng **thuần**, xem chi tiết bên dưới |
| `app/components/service.py` | Seed taxonomy theo công ty, chạy và lưu, liên kết biểu diễn mặt bằng/chi tiết, state machine, review, bàn giao 5E (nháp), tích hợp AI task |
| `app/api/components.py` | REST API |
| Hook `drawings.analysis_hook` | Chạy sau 5C, trong savepoint. Nếu lỗi, bản vẽ vẫn `processed` và lỗi được ghi vào `geometry_stats.components.error` |

`engine.py`:
- Không có DB, không có LLM.
- Phép đo được **tiêm vào** dưới dạng callable, chính là engine 5B.
- Engine không chứa mã loại cấu kiện nào trong taxonomy. Ngoại lệ duy nhất: `STEEL_POST` là mặc định có tài liệu cho dãy trụ không có nhãn.

**Tái sử dụng** thay vì viết lại:
- Primitive 5A, có thứ tự vẽ `path_index` / `item_index`.
- `measure()` của 5B. Chỉ thêm kind `diameter` (bổ sung, không đổi hành vi cũ).
- Khối chữ và liên kết 5C.
- Vùng bảng / khung tên / ghi chú của 4B, và `view_types` của 4B lấy từ tên bản vẽ.
- `audit()`, `ai_tasks`, phân quyền `drawing:read` / `drawing:write`, cô lập công ty.

**Tương thích ngược:**
- 5C chạy lại thì xoá các ứng viên 5D còn mở và chưa ai review (dữ liệu dẫn xuất).
- 5C không xoá liên kết mà một cấu kiện **đã được review** đang dùng làm bằng chứng. Lỗi này được phát hiện nhờ FK trên PostgreSQL; đã có test hồi quy.

## 2. Mô hình cấu kiện

Bảng `drawing_components`. Các cột thường truy vấn là **cột thật**, không để trong JSON:

| Nhóm | Cột |
|---|---|
| Phạm vi | `company_id`, `project_id`, `drawing_id`, `page_id` (FK `drawing_pages`), `page_no` |
| Loại | `component_type`, `component_type_id` (FK taxonomy), `component_subtype` |
| Mô tả | `name`, `description`, `specification`, `material` |
| Vị trí | `x0..y1` (bbox), `centroid_x/y`, `view_context` (PLAN / SECTION / ELEVATION / DETAIL / TABLE / NOTE / UNKNOWN) |
| Nhận dạng | `recognition_method` (rule / engineer / ai_inferred), `recognition_rule`, `recognition_confidence`, `confidence_band` |
| Bằng chứng | `text_score`, `geometry_score`, `measurement_score`, `symbol_score`, `spatial_score`, `repetition_score`, `semantic_score` |
| Review | `status`, `ambiguity_reason`, `rejection_reason`, `created_by`, `reviewed_by`, `created_at`, `reviewed_at`, `updated_at` |
| Cấu trúc | `parent_id` (hệ thống, ví dụ FENCE ← FENCE_POST), `representation_of_id` (chi tiết/mặt cắt là biểu diễn của cấu kiện khác), `repeat_group_id` |
| JSON | `dimensions`: kích thước **ghi trên bản vẽ** (quy cách, không phải khối lượng); `evidence`: lý do, quan hệ, phương án khác, so sánh |

**Khác với spec ban đầu, có giải thích:**
- `source_text_ids`, `source_geometry_ids`, `source_measurement_ids`, `source_association_ids` được lưu ở bảng liên kết `component_sources`, có **FK thật** và index theo từng loại, thay vì 4 mảng JSON. Lý do: tra ngược "hình học này thuộc cấu kiện nào" là truy vấn thường xuyên của viewer. API vẫn trả 4 mảng như spec.
- **Không có cột số lượng.** Số đếm, chiều dài, bước lặp, đường kính là **tham chiếu** `measurements.id`, nên Measurement Engine là nguồn duy nhất.

Các bảng khác:

| Bảng | Nội dung |
|---|---|
| `component_types` | Taxonomy theo công ty: `code`, `group_code`, `parent_code` (quan hệ is-a), `family`, `member_type`, `rule` (JSON quy tắc), `boq`, `active`, `source` (catalog / company). Có unique `(company_id, code)` |
| `component_symbol_patterns` | `component_type`, `pattern_type`, `parameters`, `tolerance`, `confidence_weight`, `active` |
| `component_repeat_groups` | `pattern_type`, `signature`, `carrier_geometry_id`, `pattern_status`, `count_measurement_id`, `spacing_measurement_id`, `start_x/y`, `end_x/y`, `gaps_pt`, `occluders` |
| `component_sources` | `component_id`, `source_type`, `role`, và FK tới text / geometry / measurement / association |
| `component_relations` | `PART_OF`, `REPEATED_ALONG`, `REPRESENTATION_OF`, `DETAILED_IN`, `REFERENCES` |
| `component_boq_candidates` | Bàn giao cho 5E: `DRAFT` / `WITHDRAWN`, `approval_status = NOT_APPROVED`, `measurement_id` (tham chiếu) |

## 3. Taxonomy

`catalog.json` có 37 loại, mỗi loại có `group`, `parent` (is-a), `family`, `rule`, `boq`, `member_type`.

| Nhóm | Loại |
|---|---|
| ATGT | GUARDRAIL, CRASH_BARRIER, CORRUGATED_SHEET (là một GUARDRAIL), FENCE, FENCE_POST, STEEL_POST, ROAD_SIGN, SIGN_POST, DELINEATOR, REFLECTOR, BOLLARD, DRAINAGE_GRATING |
| Hạ tầng | PIPE, CULVERT, MANHOLE, DRAIN, CONCRETE_CHANNEL (là một DRAIN), ROAD_SURFACE, KERB, SIDEWALK |
| Kết cấu | COLUMN, BEAM, SLAB, FOOTING, WALL, STEEL_MEMBER, PLATE, BOLT, BRACKET |
| Thép | ROUND_PIPE, RECTANGULAR_TUBE, H_BEAM, I_BEAM, ANGLE, CHANNEL, PLATE (dùng chung), REBAR |
| Chung | LINEAR_COMPONENT: cấu kiện tuyến tính chưa rõ loại, có từ `L=…` + hình học đã đo |

- **Mở rộng không sửa engine:**
  - `POST /component-types`: thêm loại và quy tắc riêng của công ty.
  - Hoặc thêm phần tử vào catalog: các công ty đã có taxonomy sẽ được bổ sung loại còn thiếu và **không ghi đè** chỉnh sửa của họ.
  - Test `test_new_component_type_without_code_change` tạo `NOISE_BARRIER` qua API và nhận dạng được ngay.
- **Từ khoá khớp CÓ DẤU.** Bỏ dấu sẽ gộp "CỐT THÉP" (cốt thép) với "CỘT THÉP" (cột thép). Chữ thuần ASCII thì so với dạng bỏ dấu.

## 4. Quy tắc nhận dạng (deterministic)

Mỗi `rule` khai báo:

| Khoá | Ý nghĩa |
|---|---|
| `keywords` | Từ khoá, có dấu |
| `regex` | Biểu thức chính quy, ví dụ `H300x150` |
| `spec_categories` | Loại quy cách từ bộ phân tích 4B |
| `dimension_types` | Loại kích thước (`round` = D…, `bolt` = M…x…) |
| `dimension_score` | Điểm chữ khi chỉ khớp loại kích thước |
| `geometry_kinds` | Loại hình học phù hợp |
| `geometry_optional` | Không có hình học thì không bị trừ điểm |
| `measurement_kind` | `length` / `diameter` / `area` / `count` |
| `compare` | So giá trị ghi với giá trị đo |
| `weights` | Trọng số riêng cho loại |
| `exclude_text_types` | Loại chữ không được kích hoạt nhận dạng |

Luồng mỗi trang:
1. **Ký hiệu** (mẫu là dữ liệu), sau đó **dãy lặp** dựa trên các ký hiệu `repeatable`, mỗi neo chỉ giữ ký hiệu có trọng số cao nhất.
2. **Chữ → loại:**
   - **Ngữ cảnh loại trừ:** NOTE, TABLE, TITLE, SCALE, REVISION, UNKNOWN, CHAINAGE, DETAIL_REFERENCE, và các cờ `in_table`, `in_title_block`, `page_number`, `ENCODING_UNKNOWN`.
   - **Ví dụ "M16x35":** trong ghi chú chung thì không thành cấu kiện; trong bảng thống kê cũng không.
   - **Độ cụ thể:** từ khoá ngắn nằm trong từ khoá dài hơn thì thua ("TƯỜNG" thua "TƯỜNG CHẮN XE"); loại cha thua loại con (GUARDRAIL thua CORRUGATED_SHEET).
   - **Xếp hạng:** mọi loại trong khoảng `margin` của loại dẫn đầu đều được **chấm trên bằng chứng**. Ví dụ "D88.3" khớp các loại trụ và ống; ký hiệu tròn có thân đứng quyết định STEEL_POST. Nếu 2 loại không tương thích có điểm sát nhau thì AMBIGUOUS.
3. **Bằng chứng cho từng ứng viên:**
   - Liên kết 5C (chỉ trạng thái dùng được).
   - Ký hiệu tương thích gần chữ, hoặc có đường dẫn (leader).
   - Hình học **đúng loại**: nếu liên kết 5C trỏ tới loại sai (ví dụ nhãn hàng rào → hình tròn trụ) thì lấy hình học đúng loại gần nhất.
   - Quan hệ không gian.
   - Ngữ cảnh bộ môn của trang.
   - Phép đo 5B. **Chỉ đo cho phương án thắng**, nên không có phép đo mồ côi.
4. **Cấu kiện tuyến tính chung:** chữ LENGTH có liên kết DIMENSION_OF tới line/polyline tạo LINEAR_COMPONENT, kèm phép đo length và so sánh.
5. **Dãy lặp → MỘT cấu kiện cho cả dãy**, không tạo một cấu kiện cho mỗi trụ.
   - Carrier thuộc cấu kiện có `member_type` (ví dụ FENCE → FENCE_POST) thì dãy lấy loại đó, kèm `PART_OF` và `REPEATED_ALONG` tới hệ thống.
   - `count` và `spacing` do 5B đo trên các neo của ký hiệu.
6. **Gộp danh tính** (mục 8).
7. **Gắn bằng chứng 5C còn lại** (nhãn, vật liệu, lý trình, ghi chú, tham chiếu) vào cấu kiện sở hữu hình học đó.
8. **Chấm điểm và trạng thái** (mục 10).

Ví dụ tổng hợp (đã có test):

| Đầu vào | Kết quả |
|---|---|
| `D88.3` + đường tròn + thân đứng | STEEL_POST; `dimensions.diameter_mm = 88.3`; phép đo `diameter` (5B) = 0,0883 m; so sánh 88,3 / 88,3 mm |
| `M16x35` | BOLT, `bolt_diameter_mm = 16`, `bolt_length_mm = 35`; không có phép đo |
| `HỘ LAN TÔN LƯỢN SÓNG` + polyline | CORRUGATED_SHEET; không có GUARDRAIL trùng |
| `L=13.50m` trên đường dài 12,7 m | LINEAR_COMPONENT ở trạng thái **CONFLICT** |

Đơn vị của quy cách thép không ghi (D88.3, M16x35) được hiểu theo **quy ước mm**. Điều này được ghi rõ trong `dimensions.unit_basis`.

## 5. Nhận dạng ký hiệu

Bảng `component_symbol_patterns` (seed từ catalog). Các loại mẫu:

| Mẫu | Điều kiện | Ghi chú |
|---|---|---|
| `circle` | Bán kính trong khoảng | |
| `circle_with_stem` | Tròn + đoạn thẳng chạm biên hoặc tâm, có thể yêu cầu đứng (±10°) | Trụ: mặt bằng + đứng |
| `rectangle` | Hình chữ nhật hoặc đa giác 4 góc vuông | |
| `line` | Độ dài tối thiểu | |
| `parallel_lines` | Lệch góc ≤ dung sai, khe trong khoảng, chồng chiếu ≥ ngưỡng | |
| `cross` | Hai đoạn vuông góc cắt nhau gần tâm | |
| `arrow` | Tam giác khép kín nhỏ | |
| `leader` | Đường có một đầu sát chữ, đầu kia chạm hình học | Dùng như bằng chứng không gian |
| `filled_region` | Vùng tô, diện tích tối thiểu | |
| `repeated_geometry` | Xử lý trong `repetition.py` | |

Mọi truy vấn lân cận dùng lưới, kể cả lưới riêng cho chữ khi dò leader.

## 6. Quan hệ không gian

`spatial.relations(a, b)`:
- NEAR, ON, INSIDE, INTERSECTS, ALIGNED_WITH (thẳng hàng), PARALLEL_TO, PERPENDICULAR_TO, CONNECTED_TO (đầu mút chạm).

`spatial.between()` cho BETWEEN.

`text_relation()` trả quan hệ và độ gần của chữ với hình học: INSIDE, ON hoặc NEAR.

REPEATED_ALONG được xác định trong `repetition`.

Quan hệ dùng để chấm `spatial_score` và lưu trong `evidence.relations`. Quan hệ giữa các cấu kiện lưu ở `component_relations`.

## 7. Phát hiện dãy lặp

| Bước | Quy tắc |
|---|---|
| 1. Cụm kích thước | Các ký hiệu cùng mẫu, kích thước lệch ≤ 10 % |
| 2a. Dọc carrier | Line/polyline dùng được, ký hiệu cách ≤ max(3 pt, kích thước ký hiệu); sắp theo vị trí trên tuyến (hỗ trợ tuyến gấp khúc) |
| 2b. Hàng thẳng | Liên kết đơn qua lưới (khoảng ≤ 3 × láng giềng gần trung vị); độ lệch ngang ≤ dung sai. Cụm không thẳng hàng **không** được coi là dãy |
| 3. Trạng thái | REGULAR nếu (max − min khoảng) ≤ 5 % trung bình; ngược lại IRREGULAR_PATTERN, cấu kiện thành REVIEW_REQUIRED |
| 4. Bị che | Vùng tô vẽ **sau** dãy, đè lên một thành viên hoặc lên một khoảng ≥ 1,5 × trung vị → **OCCLUDED** |
| 5. Tối thiểu | Ít hơn 3 ký hiệu thì không thành dãy |

- Khi bị che, số đếm vẫn là **số thấy được**. Test: thiếu 1 trụ dưới hộp che thì `count = 9`, không phải 10.
- `component_repeat_groups` lưu `group_id`, mẫu, `count_measurement_id`, `spacing_measurement_id`, điểm đầu và điểm cuối. **Số đếm chỉ là ứng viên.**

## 8. Kiểm soát biểu diễn trùng

Một cấu kiện có thể xuất hiện dưới nhiều dạng: chữ, ký hiệu, hình học, kích thước.
- **Gộp danh tính:** union-find trên các ứng viên **chia sẻ hình học** và có loại tương thích (cùng loại, cùng family, quan hệ is-a, hoặc một bên là LINEAR_COMPONENT).
- **Loại giữ lại:** ưu tiên loại không phải chung, rồi loại lấy từ ngữ cảnh carrier, rồi loại trong dãy, rồi loại sâu hơn trong taxonomy, rồi điểm chữ.
- **Hai loại không tương thích trên cùng hình học:** **không gộp**; cả hai thành AMBIGUOUS.
- **Ví dụ:**
  - D88.3 + tròn + thân + phép đo đường kính → 1 cấu kiện.
  - Nhãn tôn sóng + polyline + `L=8.82m` → 1 CORRUGATED_SHEET, không có LINEAR_COMPONENT riêng.

## 9. Mặt bằng / mặt cắt / chi tiết / tham chiếu

- **`view_context`:**
  - Lấy từ `view_types` (4B, theo tên bản vẽ).
  - Vùng tỷ lệ có nhãn "CHI TIẾT", "MẶT CẮT", "MẶT ĐỨNG" hoặc "MẶT BẰNG" thì ghi đè cho phần nằm trong vùng.
  - "schedule" và "general_notes" chỉ mô tả một **phần** tờ bản vẽ, nên không áp cho cả trang.
- **Cấu kiện ở DETAIL / SECTION / ELEVATION:**
  - Khớp với cấu kiện trên mặt bằng cùng family và cùng khoá quy cách (D…, M…x… hoặc quy cách chuẩn hoá) → `representation_of_id`, quan hệ `REPRESENTATION_OF` (chi tiết → mặt bằng) và `DETAILED_IN` (mặt bằng → chi tiết).
  - **Biểu diễn không phải cấu kiện mới:** không tạo ứng viên BOQ, `downstream_allowed = false`, và bị loại khỏi `confirmed_for_downstream()`.
  - Không khớp được thì giữ là cấu kiện chính, kèm lý do "Chỉ thấy ở chi tiết – kiểm tra".
- **Tham chiếu:** chữ "CHI TIẾT A" gần cấu kiện mặt bằng tạo quan hệ `REFERENCES` tới cấu kiện trên trang có tên "CHI TIẾT A", và nguồn `role = reference`.
- **Bảng:** chữ trong bảng không bao giờ kích hoạt cấu kiện (đã có test). Bảng là nguồn của Phase 4, không được cộng lần nữa.

## 10. Độ tin cậy và bằng chứng

- 7 điểm riêng: text, geometry, measurement, symbol, spatial, repetition, semantic. Cộng thêm số liên kết 5C hiển thị riêng trong UI.
- `overall` = trung bình có trọng số **chỉ trên các thành phần áp dụng được**:
  - không có ký hiệu cho loại → không tính symbol
  - không phải dãy → không tính repetition
  - hình học tuỳ chọn mà không có → không tính geometry/spatial
- Trọng số mặc định nằm trong catalog, có thể ghi đè theo loại.

| Điều kiện | Kết quả |
|---|---|
| overall ≥ 0,90 | HIGH |
| 0,70 – 0,89 | MEDIUM |
| < 0,70 | LOW |

Ngưỡng cấu hình qua `PAACC_COMPONENT_HIGH/MEDIUM/MARGIN`. **HIGH ≠ CONFIRMED.**

Trạng thái ban đầu, xét theo thứ tự:
1. Có xung đột (5C xung đột, hoặc giá trị ghi ≠ giá trị đo vượt dung sai) → CONFLICT. Dung sai: length = max(0,01 m; 0,5 %), diameter = max(1 mm; 2 %).
2. Dãy bị che → OCCLUDED.
3. Mơ hồ hoặc LOW → AMBIGUOUS.
4. MEDIUM hoặc dãy không đều → REVIEW_REQUIRED.
5. Còn lại → CANDIDATE.

## 11. Quy trình review

State machine được kiểm tra trong `service.TRANSITIONS`:

| Từ | Sang |
|---|---|
| CANDIDATE | REVIEW_REQUIRED, REJECTED, AMBIGUOUS (**không** sang thẳng CONFIRMED) |
| REVIEW_REQUIRED | CONFIRMED, REJECTED, AMBIGUOUS |
| AMBIGUOUS / CONFLICT / OCCLUDED | REVIEW_REQUIRED, CONFIRMED (bắt buộc ghi chú), REJECTED (AMBIGUOUS chỉ từ CONFLICT/OCCLUDED) |
| CONFIRMED / REJECTED | REVIEW_REQUIRED (mở lại, cần lý do) |

- Loại bỏ và đánh dấu mơ hồ bắt buộc có lý do.
- **Phân loại lại** được sửa `component_type` (phải có trong taxonomy), `component_subtype`, `description`, `specification`, `material`, `dimensions`. Bắt buộc có lý do. Trạng thái về REVIEW_REQUIRED và `recognition_method = engineer`.
- **Cấm sửa khối lượng:** các khoá `quantity`, `count`, `length*`, `area*`, `spacing*`, `volume*` bị từ chối (422).
- Mọi thay đổi đều ghi `audit_logs` (`entity = drawing_component`). `GET /components/{id}/history` đọc lại từ đó, không có bảng lịch sử thứ hai.
- **Chạy lại:** chỉ xoá ứng viên `rule` còn mở và chưa ai review, cùng nguồn, quan hệ, dãy và phép đo 5D không còn ai tham chiếu. Cấu kiện đã review được giữ, và chữ/hình học của nó không bị nhận dạng lại.

## 12. API

Cùng quy ước với 5C: `/api/v1`, JWT, `drawing:read` / `drawing:write`, 404 khi khác công ty, audit cho mọi thao tác ghi.

| Method | Đường dẫn | Ghi chú |
|---|---|---|
| GET | `/drawings/{id}/components?page=&status=&component_type=&geometry_id=` | |
| POST | `/drawings/{id}/components/run` | Tạo `ai_task` (`pdf_drawing`); xem mục 19 |
| GET | `/components/{id}` | Cả 4 mảng nguồn và `downstream_allowed` |
| GET | `/components/{id}/evidence` | Điểm, nguồn kèm vai trò, phép đo 5B (giá trị đọc từ `measurements`), dãy lặp, quan hệ, so sánh |
| GET | `/components/{id}/history` | |
| POST | `/components/{id}/review` | Bắt đầu review hoặc mở lại |
| POST | `/components/{id}/confirm` | |
| POST | `/components/{id}/reject` | |
| POST | `/components/{id}/ambiguous` | |
| POST | `/components/{id}/reclassify` | |
| POST | `/components/{id}/boq-candidate` | 409 nếu chưa CONFIRMED |
| GET | `/drawings/{id}/component-boq-candidates` | |
| GET / POST | `/component-types` | |
| GET | `/component-symbol-patterns` | |

**Tích hợp AI task (mục 19 của yêu cầu).** Dùng hệ thống `ai_tasks` hiện có:
- `running`.
- Sang `waiting_approval` (tương đương *waiting_review* của hệ thống này) nếu còn cấu kiện mở, hoặc `completed`.
- Khi cấu kiện mở cuối cùng được quyết định, task tự sang `completed`.
- Lỗi thì `error` (= *failed*).
- "Approve" tác vụ hàng loạt ở trung tâm tác vụ bị chặn (409), để mỗi cấu kiện phải được review riêng.

Phòng Kỹ thuật/QS trong văn phòng 3D có 5 chỉ số lấy thật từ DB:
- cấu kiện nhận dạng
- chờ review
- đã xác nhận
- mơ hồ/bị che
- xung đột

## 13. Database

Migration `0012_component_recognition` tạo 7 bảng; unique constraint có tên để tương thích SQLite batch mode. Không sửa migration cũ. Đã kiểm:
- upgrade / downgrade / upgrade
- `alembic check` (không drift)
- PostgreSQL 16

## 14. Tests

| Bộ test | Phạm vi |
|---|---|
| `tests/test_components.py` (26 test, synthetic) | Xem danh sách bên dưới |
| `tests/test_postgres.py::test_components_on_postgres` | Mặt bằng + chi tiết, phép đo đường kính, review, bàn giao 5E, cô lập công ty, lịch sử trên PostgreSQL 16 |
| `src/drawings/drawings.test.tsx` (3 test 5D) | Không tải khi lớp tắt; điểm bằng chứng; phép đo tham chiếu; xem nguồn; bắt đầu review; từ chối cần lý do; phân loại lại chỉ gửi trường được sửa; lớp xung đột |
| `tests/test_golden_dataset.py` | Bất biến 5D trên R1 (riêng tư) |

`tests/test_components.py` kiểm:
- **Taxonomy:** là dữ liệu; thêm loại mới mà không sửa code.
- **Engine thuần:** quan hệ không gian; mẫu ký hiệu; dãy đều / không đều / bị che / dưới ngưỡng.
- **12 kịch bản bắt buộc:**
  1. trụ thép
  2. bu lông và ngữ cảnh ghi chú
  3. tôn lượn sóng
  4. 10 trụ = 1 dãy, `count = 10` (kèm các biến thể không đều và bị che)
  5. biểu diễn trùng
  6. mặt bằng + chi tiết không đếm 2 lần
  7. xung đột 13,5 / 12,7 / 0,8
  8. chưa xác nhận thì không vào BOQ; BOQ của Phase 4 không đổi
  9. cô lập công ty và quyền
  10. audit và lịch sử
- **Hành vi khác:** state machine; AI task và chỉ số văn phòng; chạy lại giữ quyết định; xử lý bản vẽ và lỗi được cô lập; chữ bảng/khung tên không kích hoạt; không phụ thuộc LLM; benchmark; hồi quy chạy lại 5C sau 5D.

**Benchmark** (`test_benchmark_1000_geometry_5000_texts`; engine thuần, phép đo giả, máy CI của phiên này):

| Bước | Thời gian |
|---|---|
| Sinh ứng viên (ký hiệu + dãy lặp) | ≈ 60 ms |
| Nhận dạng | ≈ 1,45 s |
| Tổng | ≈ 1,5 s |

Đầu vào 1.000 hình học và 5.000 khối chữ cho ra 2.822 ứng viên (chữ ngẫu nhiên, mật độ cao). Không có vòng lặp chữ × toàn bộ hình học; mọi truy vấn lân cận dùng lưới.

## 15. Giới hạn

- Không có CV hay ký hiệu raster. Trang scan không có hình học nên không có cấu kiện.
- Dãy lặp chỉ dựa trên ký hiệu tròn/chữ nhật lặp lại. Chưa so khớp "chữ ký hình học" tổng quát (số đỉnh, tỷ lệ cạnh, xoay).
- `view_context` theo trang (tên bản vẽ) và vùng tỷ lệ có nhãn. Chưa tự tách khung nhìn trong một trang.
- **Khớp mặt bằng ↔ chi tiết:**
  - Theo family + khoá quy cách. Nếu cấu kiện không có quy cách thì chỉ liên kết khi mặt bằng có **đúng 1** ứng viên cùng family.
  - Không liên kết chéo bản vẽ (chỉ trong cùng bản vẽ).
- `spacing` của 5B tính theo khoảng cách tâm–tâm sắp theo trục, nên chỉ là xấp xỉ với tuyến cong. `gaps_pt` theo tuyến được lưu riêng.
- Quy cách thép không ghi đơn vị được hiểu theo quy ước mm (có ghi rõ).
- Trọng số và từ khoá chọn tay, **chưa hiệu chỉnh trên bản vẽ thật**.
- LLM: không có. `recognition_method = ai_inferred` dành sẵn cho tương lai, chỉ ở mức ứng viên.

## 16. Bảo mật

- Không commit PDF thật, Excel thật, báo giá, bản vẽ, dữ liệu cá nhân, tài khoản ngân hàng, con dấu/chữ ký, golden dataset hay credential.
- Fixture 5D là PDF tổng hợp sinh trong test (`tests/component_helpers.py`), nội dung tự đặt.
- Golden dataset và kỳ vọng 5D nằm ngoài git.
- Trước commit đã chạy `git status`, `git diff`, `git ls-files`, `git grep` theo danh sách chuỗi nhạy cảm, và kiểm tra lịch sử không có pdf/xls(x).

## 17. Kiểm chứng trên dữ liệu thật

| Mức | Kết quả |
|---|---|
| **Synthetic** | Toàn bộ mục 14. Chỉ chứng minh logic |
| **Real PDF R1** (báo giá 2 trang, **không phải bản vẽ thi công**) | Chi tiết bên dưới |
| **Real construction drawing** | **NOT AVAILABLE**. Không có bản vẽ thi công nào trong bộ dữ liệu. **Không tuyên bố độ chính xác nhận dạng.** Không tạo dữ liệu giả rồi gọi là kiểm chứng thật |

Kết quả trên R1 (chỉ dùng cho regression, loại trừ, bảo mật, tương thích pipeline):
- 0 ứng viên cấu kiện: mọi tên hạng mục đều nằm trong bảng.
- 263/263 khối chữ bảng/khung tên/số trang không kích hoạt cấu kiện; 0 tự xác nhận.
- Gate riêng tư thêm sàn `components = 263` và trần 0 ứng viên.
- Không hồi quy Phase 4/5A/5B/5C: metadata 12, dimensions 60, materials 7, BOQ 50, duplicates 38, geometry 94, associations 263.

## 18. Lộ trình sang 5E

5E **chỉ** đọc:
- `confirmed_for_downstream()` (CONFIRMED, không phải biểu diễn chi tiết/mặt cắt)
- `component_boq_candidates` có `status = DRAFT`

Sau đó:
```
cấu kiện + phép đo được tham chiếu (5B; kỹ sư xác nhận measurement)
 + quy cách trên bản vẽ + quy tắc đo bóc (ví dụ số tấm tôn = ⌈L / chiều dài hữu dụng⌉, tham số do kỹ sư xác nhận)
 → Quantity Engine (Decimal) → boq_items (nguồn "geometry", provenance: component → measurement → geometry → text)
 → review / phê duyệt 4 mắt → Excel (2 layout)
```
Việc cần làm ở 5E:
- quy tắc đo bóc theo loại
- xử lý trùng mặt bằng/chi tiết/bảng thống kê (nguồn Phase 4)
- đối chiếu với W4

**5E chưa được bắt đầu. Chờ review 5D.**
