"""BƯỚC 4 — Cửa chặn: quyết định Release / Hold / Rework.   ★

Test:  pytest tests/test_gate.py -q

Cây quyết định Day 07 (slide Day 09: "Lỗi bắt buộc chặn pipeline; lỗi cảnh báo chuyển người xem"):

  còn ≥ 1 lỗi bắt buộc (severity ERROR)                          -> "Rework"
  không còn lỗi bắt buộc, nhưng tỉ lệ ẢNH còn cảnh báo
      >= cfg["gate"]["warn_ratio_hold"]                          -> "Hold"
  còn lại                                                        -> "Release"

Tỉ lệ cảnh báo = (số ẢNH khác nhau có ≥ 1 cảnh báo) / (tổng số ảnh).  Chú ý:
- chỉ đếm issue có `image` nằm trong `image_stems` (bỏ "<dataset>", "data.yaml");
- bỏ qua ảnh nằm trong `reviewed` (người đã xem, cảnh báo của ảnh đó coi như đã xử lý) — nhưng LỖI BẮT BUỘC thì không bao giờ được bỏ qua;
- mẫu số là số ảnh, không phải số issue.

Trả về dict: decision, n_errors, n_warn_images, n_images, warn_ratio (làm tròn 4 chữ số), reasons (list[str], giải thích bằng tiếng Việt, có số liệu).
"""
from ..common import ERROR, WARN
def decide(issues, image_stems, cfg, reviewed=frozenset()):
    # 1. Đọc ngưỡng hold từ cấu hình (mặc định 0.10 nếu không có)
    warn_ratio_hold = cfg.get("gate", {}).get("warn_ratio_hold", 0.10)
    stems_set = set(image_stems)
    reviewed_set = set(reviewed) if reviewed else set()
    # 2. Đếm số lỗi bắt buộc (ERROR)
    # Quy tắc: Lỗi bắt buộc KHÔNG BAO GIỜ được bỏ qua, kể cả ảnh đó đã nằm trong reviewed
    errors = [i for i in issues if i.severity == ERROR]
    n_errors = len(errors)
    # 3. Đếm số ẢNH khác nhau có cảnh báo (WARN) hợp lệ:
    # - Thuộc image_stems (loại bỏ "<dataset>", "data.yaml", hoặc ảnh đã bị xóa trước đó)
    # - Chưa nằm trong reviewed (nếu người đã duyệt thì cảnh báo xem như đã được xử lý)
    warn_images = {
        i.image
        for i in issues
        if i.severity == WARN
        and i.image in stems_set
        and i.image not in reviewed_set
    }
    n_warn_images = len(warn_images)
    n_images = len(image_stems)
    # 4. Tính tỉ lệ cảnh báo (tránh lỗi chia cho 0 khi dataset rỗng)
    warn_ratio = round(n_warn_images / n_images, 4) if n_images > 0 else 0.0
    # 5. Cây quyết định (Decision Tree)
    reasons = []
    if n_errors > 0:
        decision = "Rework"
        reasons.append(f"Còn {n_errors} lỗi bắt buộc (ERROR) chưa được khắc phục.")
    elif warn_ratio >= warn_ratio_hold:
        decision = "Hold"
        reasons.append(
            f"Tỉ lệ ảnh cảnh báo là {warn_ratio:.2%} ({n_warn_images}/{n_images} ảnh), "
            f"đạt hoặc vượt ngưỡng cho phép ({warn_ratio_hold:.2%})."
        )
    else:
        decision = "Release"
        reasons.append(
            f"Đạt chuẩn xuất xưởng: không còn lỗi bắt buộc, tỉ lệ cảnh báo "
            f"{warn_ratio:.2%} ({n_warn_images}/{n_images} ảnh) dưới ngưỡng ({warn_ratio_hold:.2%})."
        )
    return {
        "decision": decision,
        "n_errors": n_errors,
        "n_warn_images": n_warn_images,
        "n_images": n_images,
        "warn_ratio": warn_ratio,
        "reasons": reasons,
    }