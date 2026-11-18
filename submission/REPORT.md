# Báo cáo Day 09 — Nguyễn Việt Quân, 2A202603035



## 1. Kết luận trước

Pipeline kết luận: RELEASE.
Số ảnh đầu vào: 224 ảnh, số ảnh sau khi làm sạch xuất ra dataset: 203 ảnh, loại bỏ 21 ảnh.
Lý do chính: Toàn bộ lỗi bắt buộc đã được xử lý triệt để (0 lỗi ERROR), tỉ lệ ảnh còn cảnh báo sau khi chuyên viên QC duyệt 80 ảnh có nguy cơ cao nhất là 7.88% (16/203 ảnh), nằm dưới ngưỡng cho phép 10.00%.

## 2. Lỗi và phân việc
Lấy từ `02_error_list_v1` (gom theo mã lỗi). Cột "ai sửa": **máy** (autofix) hay **người** (hàng đợi); chỉ ghi những mã có mặt trong lô của bạn.

| Mã lỗi | Số ảnh/dòng | Ai sửa (máy/người) | Vì sao |
| --- | ---: | --- | --- |
| `BAD_FORMAT` | 3 dòng | Máy | Dòng thiếu cột hoặc chứa ký tự NaN/chữ; máy tự xóa dòng (`drop_line`) vì không thể parse được hình học. |
| `BAD_CLASS_ID` | 6 dòng | Máy | ID lớp nằm ngoài phạm vi 0..3 của dự án (ví dụ ID 93, 7, -1); máy tự xóa dòng (`drop_line`). |
| `BOX_ZERO` | 4 dòng | Máy | Chiều rộng hoặc chiều cao ≤0\\le 0≤0; máy tự xóa dòng (`drop_line`) vì box không có diện tích. |
| `BOX_OUT_OF_IMAGE` | 8 dòng | Máy | Mép box tràn ra ngoài ảnh quá dung sai cho phép; máy tự cắt xén (`clip_box`) về [0,1][0, 1][0,1]. |
| `DUP_BOX` | 7 dòng | Máy | Trùng lặp hình học (IoU>0.9\\text{IoU} > 0.9IoU>0.9) và cùng lớp với một box trước đó; máy xóa dòng trùng lặp (`drop_line`). |
| `DUP_IMAGE_EXACT` | 8 ảnh | Máy | Trùng khớp từng byte mã băm MD5 với ảnh đã có; máy tự xóa ảnh + nhãn (`remove_image`). |
| `DUP_IMAGE_NEAR` | 3 ảnh | Máy | Trùng thị giác với khoảng cách pHash ≤8\\le 8≤8; máy tự xóa ảnh + nhãn (`remove_image`). |
| `LEAK_TEST` | 5 ảnh | Máy | Trùng ảnh với kho dữ liệu test/val; máy bắt buộc xóa (`remove_image`) để tránh gian lận / rò rỉ đề thi. |
| `CORRUPT_IMAGE` | 2 ảnh | Máy | File ảnh bị hỏng không mở được; máy tự loại bỏ (`remove_image`). |
| `BAD_SIZE` | 3 ảnh | Máy | Cạnh ngắn <250px< 250\\text{px}<250px không đủ độ phân giải; máy tự loại bỏ (`remove_image`). |
| `BAD_CLASS_NAME` | 2 lỗi | Máy | Tên lớp trong `data.yaml` bị viết hoa sai (`Person`, `Bus`); máy tự ghi đè lại tên chuẩn (`rename_classes`). |
| `MISSING_LABEL_FILE` | 6 ảnh | Người | Ảnh hoàn toàn chưa có file nhãn; máy không thể tự bịa nhãn nên chuyển người gán (`needs_label`). |
| `POSSIBLE_WRONG_CLASS` | 14 ảnh | Người | Model nghi ngờ gán nhầm lớp; máy không thể tự ý đổi nhãn nên cần mắt người xem xét ngữ cảnh. |
| `POSSIBLE_MISSING` | 32 ảnh | Người | Model phát hiện vật thể nghi bị bỏ sót; cần người xác nhận vật thể có thuộc đối tượng gán hay không. |
| `POSSIBLE_FALSE_POS` | 29 dòng | Người | Nhãn vẽ không khớp dự đoán nào của model; cần người kiểm tra xem nhãn vẽ đúng hay vẽ thừa vào nền. |
| `POSSIBLE_LOOSE_BOX` | 12 ảnh | Người | Box cùng lớp nhưng vẽ lệch/lỏng; cần chuyên viên QC chỉnh lại mép box cho khít. |
| `EMPTY_LABEL` | 12 ảnh | Người | File nhãn rỗng; cần người phân định đây là ảnh nền (không có xe/người) hay bị bỏ quên chưa gán. |
| `BOX_TINY` / `BOX_HUGE` | 9 dòng | Người | Cảnh báo hình học box quá nhỏ hoặc quá lớn so với chuẩn; đưa vào hàng đợi để người kiểm tra lại. |

vì sao `05_review_queue.csv` xếp ảnh đầu hàng như vậy? Với ngân sách 80 ảnh, người xem được bao nhiêu lỗi ngữ nghĩa?
Hàng đợi sắp xếp độ ưu tiên dựa trên tổng trọng số rủi ro trong review.weights. Người duyệt đã xử lý triệt để 6 ảnh thiếu nhãn bắt buộc, khắc phục hầu hết lỗi ngữ nghĩa: 13/14 ca nhầm lớp (WRONG_CLASS), 31/32 ca thiếu box (MISSING), và 11/12 ca box lỏng (LOOSE_BOX).

## 3. Calibration (2 ngưỡng)
| Tham số | Khởi đầu | Đã chọn | Precision / Recall (trước → sau) | Lý do (đánh đổi) |
|---|---|---|---|---|
| `duplicates.phash_dist` | 2 | 8 | DUP_IMAGE_NEAR: 1.00/0.50 -> 1.00/0.67| Giúp Recall tăng từ 0.50 lên 0.67 |
| `second_opinion.conf` | 0.25 | 0.6 | POSSIBLE_WRONG_CLASS: 0.56/0.83 -> 0.62/0.83, POSSIBLE_MISSING: 0.50/1.00 -> 0.57/1.00| Giúp Precision tăng lên mà vẫn giữ được Recall|

**một chỗ calibration có thể đánh lừa bạn**, kèm bằng chứng từ dữ liệu của bạn (vd. mở xem vài cặp ảnh bị cho là trùng; số ảnh bị loại ở bước 1 có hợp lý không?).
Calibration có thể đánh lừa ở duplicates.phash_dist ở ngưỡng 16, F1 cao nhất = 0.91, Recall = 0.83, Precision = 1.00. Trong tập calib chỉ có 39 ảnh với ngữ cảnh khác nhau nhưng tập raw có nhiều ảnh có ngữ cảnh giống nhau có thể gây hiện tượng nhận nhầm ảnh trùng và xóa ảnh.

## 4. Cửa chặn và điều pipeline KHÔNG bắt được
(a) chứng minh gate chặn đúng: chạy `python -m pipeline.run --budget 0 --reports work/rep_nb --export-dir work/exp_nb` (không có người duyệt nên ảnh thiếu file nhãn còn nguyên), chỉ ra kết luận **Rework**, mã thoát 20 và việc **không xuất** dataset. (Đừng sửa tay `work/run/ds`: pipeline dựng lại thư mục này từ raw mỗi lần chạy.) (b) ≥ 2 điểm mù có bằng chứng (box lỏng nhẹ, nhầm lớp mà model lớn cũng nhầm, ảnh trùng biến đổi mạnh…).

(a) Kết quả: Pipeline trả về "KHÔNG xuất: còn lỗi bắt buộc (Rework) — trả về bước 3", Thư mục work/exp_nb không khởi tạo.
(b)
- Box bị vẽ lỏng/lệch nhẹ (IoU >= 0.50): Nếu người gán nhãn vẽ bounding box rộng hơn so với vật thể thực tế nhưng IoU >= 0.50 thì pipeline sẽ xem như box đã bao phủ đúng vật thể.
- Lỗi phân lớp mà người gán và model đều nhầm: Với các đối tượng có thể bị nhầm lẫn với nhau như car và truck, nếu cả người gán và model cùng nhận định là car thì pipeline sẽ dễ dàng bỏ qua.

## 5. Train: raw vs clean (tùy chọn, chấm riêng)
Chưa train: ghi "chưa chạy" và lý do, rồi bỏ qua phần còn lại của mục này. Nếu đã train: dán bảng từ `submission/results/comparison.md` (model, epoch, seed, số ảnh train mỗi biến thể).
Chưa chạy do chưa chạy thực nghiệm trên Google Colab.

chênh mAP50 (clean − raw) so với **độ lệch chuẩn giữa các seed**; kết luận **trung thực** (nằm trong nhiễu thì nói là chưa kết luận được); ≥ 2 giả thuyết giải thích (ảnh trùng/rò rỉ test trong `raw`, nhãn máy còn lại trong `clean`, test chỉ 100 ảnh…) và cách kiểm.

## 6. Quyết định và ghi chú AI
(a) quyết định cuối; nếu Hold/Rework cần làm gì để thành Release? (b) Dùng AI viết code? Ghi 3 dòng: prompt chính, cách bạn kiểm code AI, 1 lần AI sai. Không dùng: ghi "không dùng".
(a) Quyết định cuối: RELEASE. Trước khi calibrate, pipeline từng bị Hold, calibrate bằng cách nâng conf = 0.6 và phash_dist = 2.
(b) 
- Prompt 4 module theo TDD
- Kiểm bằng pytest 79 test + calibrate
- Một lần AI sai: Trong autofix, ban đầu xử lý clip_box nếu box nằm hoàn toàn ngoài ảnh sẽ sinh box âm/rỗng, sau đó đã được bổ sung điều kiện chuyển thành drop_line.

*(Thưởng +2, tùy chọn)* CVAT: lọc `width < 20`, ảnh/số box khớp, đối chiếu `BOX_TINY` (xem docs/CVAT_FILTER.md), 1 câu về `can_review`.
