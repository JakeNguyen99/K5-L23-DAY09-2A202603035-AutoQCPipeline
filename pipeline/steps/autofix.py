"""BƯỚC 2/4 — Sửa tự động những lỗi bắt buộc mà máy sửa được AN TOÀN.   ★★

Test:  pytest tests/test_autofix.py -q

`fix(ds, issues, cfg) -> list[dict]`: duyệt `issues` (chỉ lỗi severity ERROR), sửa thẳng vào thư mục `ds`,
và trả về danh sách thay đổi; mỗi phần tử có khoá: image, line, action, before, after
(đây chính là file `03_fixes.csv` — bằng chứng pipeline đã làm gì, người có thể kiểm lại).

| code lỗi                                       | cách sửa                                    | action           |
|------------------------------------------------|---------------------------------------------|------------------|
| BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO, DUP_BOX    | xoá dòng đó khỏi file nhãn                  | "drop_line"      |
| BOX_OUT_OF_IMAGE                               | cắt box về trong [0,1] (giữ nguyên lớp)     | "clip_box"       |
| MISSING_LABEL_FILE                             | KHÔNG sửa file (máy không thể bịa nhãn): ghi 1 dòng fix, before="(không có file)", after="chuyển người gán" | "needs_label" |
| BAD_CLASS_NAME                                 | ghi lại `names` trong data.yaml đúng `cfg["classes"]` | "rename_classes" |
| DUP_IMAGE_*, LEAK_TEST, CORRUPT_IMAGE, BAD_SIZE| xoá ảnh + nhãn khỏi `ds`                    | "remove_image"   |

Bẫy cần nghĩ tới (có test cho từng cái)
- Một file có NHIỀU dòng lỗi: số dòng trong `issues` là số dòng GỐC. Nếu xoá từng dòng một thì số dòng lệch.
  Gom theo file, rồi ghi lại MỘT lần.
- Sau khi cắt, box có thể không còn diện tích (nằm hẳn ngoài ảnh): lúc đó xoá dòng thay vì ghi box rỗng.
- Một dòng có 2 lỗi (vd. BOX_OUT_OF_IMAGE + DUP_BOX): xoá dòng thắng, chỉ ghi 1 fix `drop_line`, không ghi thêm `clip_box`. Dòng trống ở giữa file vẫn đếm vào số dòng gốc.
- Ảnh vừa bị xoá (DUP_IMAGE_*...) mà còn issue dòng của chính nó: bỏ qua êm, không được báo lỗi/chết.
- Không động tới lỗi WARN (cảnh báo là việc của người). Không sửa file ở `data/raw/` — chỉ sửa `ds`.
- Chạy lần 2 trên dữ liệu đã sửa phải không làm gì thêm (idempotent) — NGOẠI LỆ duy nhất: `needs_label` được ghi lại mỗi lần còn lỗi `MISSING_LABEL_FILE` (vì ảnh vẫn chưa có nhãn).

- `needs_label` KHÔNG tạo file nhãn rỗng (rỗng = "ảnh nền", khác với "chưa gán"). `review_queue` sẽ đẩy ảnh này lên đầu hàng đợi cho người.

Gợi ý: `yaml.safe_load / safe_dump`.
"""
from collections import defaultdict
import yaml
from ..common import ERROR, parse_yolo_line
DROP_CODES = {"BAD_FORMAT", "BAD_CLASS_ID", "BOX_ZERO", "DUP_BOX"}
def fix(ds, issues, cfg):
    fixes = []
    # Chỉ xử lý các lỗi có mức độ nghiêm trọng là ERROR (bỏ qua WARN)
    err_issues = [i for i in issues if i.severity == ERROR]
    if not err_issues:
        return fixes
    # =========================================================================
    # 1. Xoá ảnh hỏng / trùng / rò rỉ (remove_image)
    # DUP_IMAGE_*, LEAK_TEST, CORRUPT_IMAGE, BAD_SIZE
    # =========================================================================
    removed_stems = set()
    for iss in err_issues:
        code = iss.code
        if code.startswith("DUP_IMAGE_") or code in {"LEAK_TEST", "CORRUPT_IMAGE", "BAD_SIZE"}:
            stem = iss.image
            if stem not in removed_stems:
                removed_stems.add(stem)
                # Xoá file ảnh nếu có
                img_p = ds.image_path(stem)
                if img_p and img_p.exists():
                    img_p.unlink()
                elif ds.images_dir.exists():
                    for f in ds.images_dir.glob(f"{stem}.*"):
                        f.unlink()
                # Xoá file nhãn tương ứng nếu có
                lbl_p = ds.label_path(stem)
                if lbl_p.exists():
                    lbl_p.unlink()
                fixes.append({
                    "image": stem,
                    "line": "",
                    "action": "remove_image",
                    "before": "exists",
                    "after": "removed",
                })
    # =========================================================================
    # 2. Cập nhật tên lớp trong data.yaml (rename_classes)
    # =========================================================================
    has_bad_class_name = any(iss.code == "BAD_CLASS_NAME" for iss in err_issues)
    if has_bad_class_name and ds.yaml_path.exists():
        data = yaml.safe_load(ds.yaml_path.read_text(encoding="utf-8")) or {}
        old_names = data.get("names", {})
        data["names"] = list(cfg["classes"])
        ds.yaml_path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        fixes.append({
            "image": "data.yaml",
            "line": "",
            "action": "rename_classes",
            "before": str(old_names),
            "after": str(cfg["classes"]),
        })
    # =========================================================================
    # 3. Ảnh thiếu nhãn (needs_label)
    # Ghi nhận fix để chuyển người duyệt, tuyệt đối KHÔNG tạo file nhãn rỗng
    # =========================================================================
    missing_stems = set()
    for iss in err_issues:
        if iss.code == "MISSING_LABEL_FILE":
            stem = iss.image
            if stem not in removed_stems and stem not in missing_stems:
                missing_stems.add(stem)
                fixes.append({
                    "image": stem,
                    "line": "",
                    "action": "needs_label",
                    "before": "(không có file)",
                    "after": "chuyển người gán",
                })
    # =========================================================================
    # 4. Gom nhóm lỗi cấp dòng theo từng file nhãn (drop_line, clip_box)
    # =========================================================================
    file_line_issues = defaultdict(lambda: defaultdict(list))
    for iss in err_issues:
        stem = iss.image
        # Bỏ qua nếu ảnh đã bị xóa ở bước 1 hoặc không có số dòng
        if stem in removed_stems or iss.line is None:
            continue
        file_line_issues[stem][iss.line].append(iss)
    # Duyệt từng file để sửa đồng loạt (tránh lệch số dòng gốc)
    for stem, line_issues_dict in file_line_issues.items():
        lbl_p = ds.label_path(stem)
        if not lbl_p.exists():
            continue
        orig_lines = lbl_p.read_text(encoding="utf-8", errors="replace").splitlines()
        line_actions = {}  # line_idx -> (action, before, after, new_text_if_keep)
        for line_idx in sorted(line_issues_dict.keys()):
            idx_0 = line_idx - 1
            if idx_0 < 0 or idx_0 >= len(orig_lines):
                continue
            orig_text = orig_lines[idx_0]
            issues_here = line_issues_dict[line_idx]
            has_drop = any(i.code in DROP_CODES for i in issues_here)
            has_clip = any(i.code == "BOX_OUT_OF_IMAGE" for i in issues_here)
            # Quy tắc ưu tiên: Nếu vừa có drop vừa có clip -> drop_line thắng
            if has_drop:
                line_actions[line_idx] = ("drop_line", orig_text, "", None)
            elif has_clip:
                try:
                    c, cx, cy, w, h = parse_yolo_line(orig_text)
                    x1 = cx - w / 2.0
                    x2 = cx + w / 2.0
                    y1 = cy - h / 2.0
                    y2 = cy + h / 2.0
                    x1_c = max(0.0, min(1.0, x1))
                    x2_c = max(0.0, min(1.0, x2))
                    y1_c = max(0.0, min(1.0, y1))
                    y2_c = max(0.0, min(1.0, y2))
                    new_w = x2_c - x1_c
                    new_h = y2_c - y1_c
                    # Nếu sau khi cắt box không còn diện tích -> xoá dòng
                    if new_w <= 0.0 or new_h <= 0.0:
                        line_actions[line_idx] = ("drop_line", orig_text, "", None)
                    else:
                        new_cx = (x1_c + x2_c) / 2.0
                        new_cy = (y1_c + y2_c) / 2.0
                        new_text = f"{int(c)} {new_cx:.6f} {new_cy:.6f} {new_w:.6f} {new_h:.6f}"
                        line_actions[line_idx] = ("clip_box", orig_text, new_text, new_text)
                except ValueError:
                    line_actions[line_idx] = ("drop_line", orig_text, "", None)
        # Ghi lại file nhãn với các dòng đã sửa / xoá
        new_lines = []
        for idx_0, text in enumerate(orig_lines):
            line_idx = idx_0 + 1
            if line_idx in line_actions:
                action, before, after, new_text = line_actions[line_idx]
                fixes.append({
                    "image": stem,
                    "line": line_idx,
                    "action": action,
                    "before": before,
                    "after": after,
                })
                if action == "clip_box":
                    new_lines.append(new_text)
            else:
                new_lines.append(text)
        new_content = "\n".join(new_lines) + ("\n" if new_lines else "")
        lbl_p.write_text(new_content, encoding="utf-8")
    return fixes