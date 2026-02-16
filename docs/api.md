# API Overview

## POST /api/v1/analyze
- Content-Type: `multipart/form-data`
- Fields:
  - `solution_image` (required)
  - `problem_image` (optional)
  - `meta` JSON string

Example `meta`:
```json
{"subject":"math","highlight_mode":"tap"}
```

Response:
```json
{
  "analysis_id": "a_xxx",
  "status": "queued",
  "result": null
}
```

## GET /api/v1/analysis/{analysis_id}
Returns status and full analysis result.

## POST /api/v1/annotations
Request body:
```json
{
  "analysis_id": "a_xxx",
  "mistake_id": "m_xxx",
  "mode": "tap",
  "shape": "circle",
  "x": 0.52,
  "y": 0.38,
  "w": 0.12,
  "h": 0.12
}
```

## GET /api/v1/history?limit=5
Returns recent analyses and top mistake tags.

## GET /api/v1/health
Checks server availability and queue mode.
