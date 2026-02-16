from __future__ import annotations

from typing import Any

from PIL import Image

try:
    import pytesseract  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    pytesseract = None


def suggest_ocr_boxes(image_path: str, max_boxes: int = 3) -> list[dict[str, Any]]:
    """Return normalized OCR hint boxes (0..1)."""
    with Image.open(image_path) as img:
        width, height = img.size
        if width <= 0 or height <= 0:
            return []

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
            {"mode": "ocr_box", "shape": "box", "x": 0.1, "y": 0.15, "w": 0.55, "h": 0.12},
            {"mode": "ocr_box", "shape": "box", "x": 0.12, "y": 0.36, "w": 0.58, "h": 0.12},
            {"mode": "ocr_box", "shape": "box", "x": 0.14, "y": 0.58, "w": 0.5, "h": 0.12},
        ][:max_boxes]

