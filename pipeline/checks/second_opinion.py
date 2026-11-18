"""CHECK 6 — Ý kiến thứ hai: so nhãn với một model LỚN HƠN (yolo26l).   ★★★ (khó nhất, đáng điểm nhất)

Test:  pytest tests/test_second_opinion.py -q

Máy kiểm quy tắc, người kiểm ý nghĩa (slide). Các lỗi như thiếu nhãn / gán nhầm lớp hợp lệ / box lỏng
KHÔNG bắt được bằng quy tắc cú pháp. Ta nhờ một model mạnh hơn "nhìn lại" và CHỈ CẢNH BÁO (model cũng có thể sai):
những ảnh bị cờ sẽ vào hàng đợi cho NGƯỜI duyệt.

`preds[stem]` = list `[id_lớp, conf, cx, cy, w, h]` của model (lấy qua `get_preds(ds, cfg, "checker")` nếu preds=None).
`L = ds.valid_boxes(stem)` = list `(id_lớp, cx, cy, w, h)` của nhãn (đã bỏ dòng hỏng).
Ngưỡng ở `cfg["second_opinion"]`: conf, min_area_px, fp_conf, iou_missing, iou_match, iou_loose.

Thuật toán gợi ý, với từng ảnh (bỏ qua ảnh không có trong preds hoặc không có file nhãn):
  P = dự đoán có conf >= conf  VÀ diện tích px (w*W * h*H) >= min_area_px
  Với mỗi dự đoán r trong P: lấy các nhãn có IoU(r, nhãn) >= iou_missing  (cands)
   - không có cands                            -> POSSIBLE_MISSING     (model thấy vật mà nhãn không có box)
   - có cands cùng lớp, tốt nhất IoU < iou_loose -> POSSIBLE_LOOSE_BOX  (đúng vật, box lỏng/lệch)
   - không có cands cùng lớp, nhưng cands tốt nhất IoU >= iou_match (khác lớp) -> POSSIBLE_WRONG_CLASS
  Với mỗi dòng nhãn hợp lệ: nếu IoU với MỌI dự đoán (conf >= fp_conf, không lọc diện tích) đều < iou_missing
                                             -> POSSIBLE_FALSE_POS  (box nhãn không khớp vật nào model thấy; Issue.line = số dòng)

Chi tiết các ca biên (test kiểm đúng các ca này)
- `cands` gồm nhãn MỌI lớp có IoU >= iou_missing; "tốt nhất cùng lớp" = cands cùng lớp có IoU lớn nhất; "tốt nhất khác lớp" tương tự với cands khác lớp.
- Thứ tự quyết định cho mỗi dự đoán: (1) cands rỗng -> MISSING. (2) có cands cùng lớp: IoU tốt nhất < iou_loose -> LOOSE_BOX, ngược lại KHÔNG cờ
  (nhãn đúng lớp đã phủ vật này, kể cả khi còn nhãn khác lớp chồng lên). (3) không có cands cùng lớp: nếu IoU tốt nhất khác lớp >= iou_match -> WRONG_CLASS;
  nếu chỉ có khác lớp với IoU trong [iou_missing, iou_match) -> không cờ gì (mơ hồ: để cho FALSE_POS / lần duyệt khác).
- Một dự đoán sinh tối đa MỘT issue (MISSING / LOOSE_BOX / WRONG_CLASS); một ảnh có thể có nhiều issue.
- Thứ tự issue: theo `ds.image_files()` rồi theo thứ tự dự đoán trong `preds[stem]`, cuối cùng là các FALSE_POS theo số dòng; `Issue.image` = stem, `Issue.line` chỉ đặt cho FALSE_POS.

Lưu ý số dòng: dùng `ds.read_label_lines(stem)` (giữ số dòng gốc, kể cả dòng hỏng/trống) để lấy `Issue.line`; `valid_boxes` KHÔNG giữ số dòng.

Tất cả severity WARN; `Issue.extra` nên có {"conf": ...} hoặc {"iou": ...} (hàng đợi duyệt dùng conf để xếp ưu tiên).

Gợi ý
- `iou_xywh` có sẵn. Dòng nhãn hỏng không được làm script chết (dùng `ds.valid_boxes` và `parse_yolo_line` trong try).
- Kết quả phụ thuộc mạnh vào ngưỡng: calibrate chúng ở Bước 3 thay vì đoán.
"""
from ..common import WARN, Issue, iou_xywh, parse_yolo_line
from ..model_cache import get_preds
def run(ds, cfg, preds=None):
    if preds is None:
        preds = get_preds(ds, cfg, "checker")
    # 1. Đọc ngưỡng cấu hình từ cfg["second_opinion"]
    so_cfg = cfg.get("second_opinion", {})
    conf_thresh = so_cfg.get("conf", 0.25)
    min_area_px = so_cfg.get("min_area_px", 600)
    fp_conf = so_cfg.get("fp_conf", 0.1)
    iou_missing = so_cfg.get("iou_missing", 0.3)
    iou_match = so_cfg.get("iou_match", 0.5)
    iou_loose = so_cfg.get("iou_loose", 0.5)
    num_classes = len(ds.classes)
    issues = []
    # 2. Duyệt qua từng ảnh theo thứ tự ds.image_files()
    for img_p in ds.image_files():
        stem = img_p.stem
        # Bỏ qua ảnh không có trong preds hoặc không có file nhãn
        if preds is None or stem not in preds:
            continue
        raw_lines = ds.read_label_lines(stem)
        if raw_lines is None:
            continue
        img_size = ds.image_size(stem)
        if img_size is None:
            continue
        img_w, img_h = img_size
        # 3. Lấy danh sách nhãn hợp lệ trong ảnh: (line_idx, cls_id, (cx, cy, w, h))
        valid_labels = []
        for line_idx, text in raw_lines:
            try:
                cls_id, cx, cy, w, h = parse_yolo_line(text)
            except ValueError:
                continue
            if 0 <= cls_id < num_classes:
                valid_labels.append((line_idx, cls_id, (cx, cy, w, h)))
        # 4. Lọc các dự đoán của model để kiểm tra đối chiếu (P)
        # Điều kiện: conf >= conf_thresh VÀ diện tích pixel >= min_area_px
        P = [
            r for r in preds[stem]
            if r[1] >= conf_thresh and (r[4] * img_w * r[5] * img_h) >= min_area_px
        ]
        # 5. So sánh từng dự đoán r trong P với các nhãn hợp lệ
        for r in P:
            pred_cls, pred_conf = int(r[0]), float(r[1])
            pred_box = (r[2], r[3], r[4], r[5])
            # Tìm các nhãn có IoU >= iou_missing (cands)
            cands = []
            for line_idx, l_cls, l_box in valid_labels:
                iou = iou_xywh(pred_box, l_box)
                if iou >= iou_missing:
                    cands.append((line_idx, l_cls, l_box, iou))
            # (1) Không có nhãn nào khớp -> nghi ngờ thiếu nhãn (POSSIBLE_MISSING)
            if not cands:
                issues.append(
                    Issue(
                        "second_opinion",
                        WARN,
                        "POSSIBLE_MISSING",
                        stem,
                        f"model thấy lớp {pred_cls} (conf={pred_conf:.2f}) nhưng nhãn thiếu box",
                        line=None,
                        extra={"conf": pred_conf},
                    )
                )
            else:
                # (2) Có nhãn cùng lớp
                same_class_cands = [c for c in cands if c[1] == pred_cls]
                if same_class_cands:
                    best_same_iou = max(c[3] for c in same_class_cands)
                    # Đúng vật, đúng lớp nhưng box lỏng/lệch
                    if best_same_iou < iou_loose:
                        issues.append(
                            Issue(
                                "second_opinion",
                                WARN,
                                "POSSIBLE_LOOSE_BOX",
                                stem,
                                f"box nhãn cùng lớp {pred_cls} bị lỏng/lệch (IoU={best_same_iou:.2f} < {iou_loose})",
                                line=None,
                                extra={"conf": pred_conf, "iou": best_same_iou},
                            )
                        )
                    # Nếu best_same_iou >= iou_loose: Đạt yêu cầu, KHÔNG cảnh báo
                else:
                    # (3) Không có nhãn cùng lớp, kiểm tra nhãn khác lớp
                    diff_class_cands = [c for c in cands if c[1] != pred_cls]
                    best_diff_iou = max(c[3] for c in diff_class_cands)
                    # Vị trí khớp cao nhưng khác lớp -> nghi ngờ gán nhầm lớp
                    if best_diff_iou >= iou_match:
                        issues.append(
                            Issue(
                                "second_opinion",
                                WARN,
                                "POSSIBLE_WRONG_CLASS",
                                stem,
                                f"khác lớp: model dự đoán {pred_cls} nhưng nhãn gán khác (IoU={best_diff_iou:.2f})",
                                line=None,
                                extra={"conf": pred_conf, "iou": best_diff_iou},
                            )
                        )
                    # Nếu IoU nằm trong [iou_missing, iou_match): vùng mơ hồ, KHÔNG cảnh báo
        # 6. Kiểm tra nhãn thừa (POSSIBLE_FALSE_POS)
        # Dự đoán dùng để đối soát FALSE_POS chỉ cần conf >= fp_conf (KHÔNG lọc diện tích)
        fp_preds = [r for r in preds[stem] if r[1] >= fp_conf]
        for line_idx, l_cls, l_box in valid_labels:
            max_iou = 0.0
            for r in fp_preds:
                pred_box = (r[2], r[3], r[4], r[5])
                iou = iou_xywh(l_box, pred_box)
                if iou > max_iou:
                    max_iou = iou
            # Nếu box nhãn không khớp với bất kỳ dự đoán nào của model (IoU < iou_missing)
            if max_iou < iou_missing:
                issues.append(
                    Issue(
                        "second_opinion",
                        WARN,
                        "POSSIBLE_FALSE_POS",
                        stem,
                        f"nhãn không khớp dự đoán nào của model (max IoU={max_iou:.2f} < {iou_missing})",
                        line=line_idx,
                        extra={"max_iou": max_iou},
                    )
                )
    return issues