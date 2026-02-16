from __future__ import annotations

import base64
import sys
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.main import create_app


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wn+V3kAAAAASUVORK5CYII="
)


class APITestCase(unittest.TestCase):
    def _client(self) -> TestClient:
        return TestClient(create_app())

    def _multipart(self, meta: str = '{"subject":"math","highlight_mode":"tap"}') -> dict:
        return {
            "files": {"solution_image": ("solution.png", PNG_1X1, "image/png")},
            "data": {"meta": meta},
        }

    def test_analyze_requires_solution_image(self) -> None:
        with self._client() as client:
            response = client.post("/api/v1/analyze", data={"meta": '{"subject":"math"}'})
            self.assertEqual(response.status_code, 400)
            self.assertIn("solution_image", response.json()["detail"])

    def test_analyze_transitions_to_done_and_supports_annotations(self) -> None:
        with self._client() as client:
            payload = self._multipart()
            response = client.post("/api/v1/analyze", files=payload["files"], data=payload["data"])
            self.assertEqual(response.status_code, 200)
            analysis_id = response.json()["analysis_id"]

            detail = None
            for _ in range(10):
                detail_resp = client.get(f"/api/v1/analysis/{analysis_id}")
                self.assertEqual(detail_resp.status_code, 200)
                detail = detail_resp.json()
                if detail["status"] in {"done", "failed"}:
                    break
                time.sleep(0.2)

            self.assertIsNotNone(detail)
            self.assertEqual(detail["status"], "done")
            self.assertIsNotNone(detail["result"])
            mistakes = detail["result"]["mistakes"]
            self.assertGreaterEqual(len(mistakes), 1)
            first_mistake = mistakes[0]
            self.assertIn("mistake_id", first_mistake)

            ann_resp = client.post(
                "/api/v1/annotations",
                json={
                    "analysis_id": analysis_id,
                    "mistake_id": first_mistake["mistake_id"],
                    "mode": "tap",
                    "shape": "circle",
                    "x": 0.52,
                    "y": 0.38,
                    "w": 0.12,
                    "h": 0.12,
                },
            )
            self.assertEqual(ann_resp.status_code, 200)
            self.assertEqual(ann_resp.json()["analysis_id"], analysis_id)

    def test_history_lists_recent_items(self) -> None:
        with self._client() as client:
            payload = self._multipart(meta='{"subject":"physics","highlight_mode":"tap"}')
            response = client.post("/api/v1/analyze", files=payload["files"], data=payload["data"])
            self.assertEqual(response.status_code, 200)

            history = client.get("/api/v1/history?limit=5")
            self.assertEqual(history.status_code, 200)
            body = history.json()
            self.assertIn("items", body)
            self.assertGreaterEqual(len(body["items"]), 1)
            self.assertIn("top_tags", body)


if __name__ == "__main__":
    unittest.main()

