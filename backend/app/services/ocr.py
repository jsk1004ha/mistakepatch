from __future__ import annotations

from typing import Any

from PIL import Image

try:
    import pytesseract  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    pytesseract = None


def extract_image_text(image_path: str, max_chars: int = 1500) -> str:
    try:
        with Image.open(image_path) as img:
            if pytesseract is None:
                return ""
            try:
                text = pytesseract.image_to_string(img)
                normalized = " ".join(text.split())
                return normalized[:max_chars]
            except Exception:
                return ""
    except Exception:
        return ""


def extract_image_lines(
    image_path: str,
    max_lines: int = 12,
    max_chars_per_line: int = 120,
) -> list[str]:
    try:
        with Image.open(image_path) as img:
            if pytesseract is None:
                return []
            try:
                text = pytesseract.image_to_string(img)
            except Exception:
                return []
    except Exception:
        return []

    lines: list[str] = []
    for raw in text.splitlines():
        normalized = " ".join(raw.split())
        if not normalized:
            continue
        lines.append(normalized[:max_chars_per_line])
        if len(lines) >= max_lines:
            break
    return lines


def suggest_ocr_boxes(image_path: str, max_boxes: int = 3) -> list[dict[str, Any]]:
    """Return normalized OCR hint boxes (0..1)."""
    try:
        with Image.open(image_path) as img:
            width, height = img.size
            if width <= 0 or height <= 0:
                return []

            # Prefer line-level boxes for step localization.
            try:
                line_boxes = _detect_ink_line_boxes(img, max_boxes=max_boxes)
                if line_boxes:
                    return line_boxes
            except Exception:
                pass

            if pytesseract is not None:
                try:
                    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
                    boxes: list[dict[str, Any]] = []
                    for i in range(len(data.get("text", []))):
                        text = (data["text"][i] or "").strip()
                        conf = float(data["conf"][i]) if data["conf"][i] not in ("-1", "") else -1
                        if not text or conf < 45:
                            continue
                        x, y = data["left"][i], data["top"][i]
                        w, h = data["width"][i], data["height"][i]
                        if w <= 0 or h <= 0:
                            continue
                        boxes.append(
                            {
                                "mode": "ocr_box",
                                "shape": "box",
                                "x": round(x / width, 4),
                                "y": round(y / height, 4),
                                "w": round(w / width, 4),
                                "h": round(h / height, 4),
                            }
                        )
                        if len(boxes) >= max_boxes:
                            break
                    if boxes:
                        return boxes
                except Exception:
                    pass

            # Conservative fallback hints if OCR engine is unavailable.
            return [
                {"mode": "ocr_box", "shape": "box", "x": 0.5, "y": 0.2, "w": 0.75, "h": 0.1},
                {"mode": "ocr_box", "shape": "box", "x": 0.5, "y": 0.33, "w": 0.75, "h": 0.1},
                {"mode": "ocr_box", "shape": "box", "x": 0.5, "y": 0.46, "w": 0.75, "h": 0.1},
                {"mode": "ocr_box", "shape": "box", "x": 0.5, "y": 0.59, "w": 0.75, "h": 0.1},
                {"mode": "ocr_box", "shape": "box", "x": 0.5, "y": 0.72, "w": 0.72, "h": 0.1},
                {"mode": "ocr_box", "shape": "box", "x": 0.5, "y": 0.85, "w": 0.7, "h": 0.1},
            ][:max_boxes]
    except Exception:
        pass

    return [
        {"mode": "ocr_box", "shape": "box", "x": 0.5, "y": 0.2, "w": 0.75, "h": 0.1},
        {"mode": "ocr_box", "shape": "box", "x": 0.5, "y": 0.33, "w": 0.75, "h": 0.1},
        {"mode": "ocr_box", "shape": "box", "x": 0.5, "y": 0.46, "w": 0.75, "h": 0.1},
        {"mode": "ocr_box", "shape": "box", "x": 0.5, "y": 0.59, "w": 0.75, "h": 0.1},
        {"mode": "ocr_box", "shape": "box", "x": 0.5, "y": 0.72, "w": 0.72, "h": 0.1},
        {"mode": "ocr_box", "shape": "box", "x": 0.5, "y": 0.85, "w": 0.7, "h": 0.1},
    ][:max_boxes]


def _detect_ink_line_boxes(img: Image.Image, max_boxes: int = 3) -> list[dict[str, Any]]:
    gray = img.convert("L")
    width, height = gray.size
    if width <= 0 or height <= 0:
        return []

    pixels = gray.load()
    dark_threshold = 195
    row_ink = [0] * height
    for y in range(height):
        count = 0
        for x in range(width):
            if pixels[x, y] < dark_threshold:
                count += 1
        row_ink[y] = count

    active_rows = max(6, int(width * 0.012))
    segments: list[tuple[int, int]] = []
    start = -1
    gap = 0
    max_gap = max(2, int(height * 0.008))

    for y, ink in enumerate(row_ink):
        if ink >= active_rows:
            if start < 0:
                start = y
            gap = 0
        else:
            if start >= 0:
                gap += 1
                if gap > max_gap:
                    end = y - gap
                    if end - start >= 8:
                        segments.append((start, end))
                    start = -1
                    gap = 0
    if start >= 0:
        end = height - 1
        if end - start >= 8:
            segments.append((start, end))

    if not segments:
        return []

    box_candidates: list[dict[str, Any]] = []
    for top, bottom in segments:
        band_h = bottom - top + 1
        col_ink = [0] * width
        for y in range(top, bottom + 1):
            for x in range(width):
                if pixels[x, y] < dark_threshold:
                    col_ink[x] += 1

        active_cols = max(2, int(band_h * 0.04))
        left = next((x for x, v in enumerate(col_ink) if v >= active_cols), None)
        right = next((x for x in range(width - 1, -1, -1) if col_ink[x] >= active_cols), None)
        if left is None or right is None or right <= left:
            continue

        pad_x = max(4, int(width * 0.008))
        pad_y = max(4, int(height * 0.008))
        x0 = max(0, left - pad_x)
        x1 = min(width - 1, right + pad_x)
        y0 = max(0, top - pad_y)
        y1 = min(height - 1, bottom + pad_y)

        bw = x1 - x0 + 1
        bh = y1 - y0 + 1
        if bw < int(width * 0.15) or bh < int(height * 0.03):
            continue

        box_candidates.append(
            {
                "mode": "ocr_box",
                "shape": "box",
                "x": round((x0 + bw / 2) / width, 4),
                "y": round((y0 + bh / 2) / height, 4),
                "w": round(bw / width, 4),
                "h": round(bh / height, 4),
                "_top": y0,
                "_ink": sum(row_ink[top : bottom + 1]),
            }
        )

    if not box_candidates:
        return []

    box_candidates.sort(key=lambda item: (item["_top"], -item["_ink"]))
    picked = box_candidates[:max_boxes]
    for box in picked:
        box.pop("_top", None)
        box.pop("_ink", None)
    return picked
