# Architecture Summary

## Flow
1. Frontend uploads `solution_image` (+ optional `problem_image`).
2. Backend creates `submission` and `analysis` records in SQLite.
3. Job is sent to Redis/RQ if enabled; otherwise FastAPI background task runs it.
4. Analyzer calls OpenAI Structured Outputs and validates against JSON Schema.
5. On any model/schema failure, fallback result is loaded from `backend/data/fallback_sample_result.json`.
6. Result is stored, mistakes are normalized, and UI polls until `done`.
7. User can add tap-based annotations to missing highlight positions.

## Core Safety
- MIME and upload size validation
- Schema validation before DB write
- Fallback result for demo reliability
- Optional OCR hint mode behind env flag (`ENABLE_OCR_HINTS`)

## Data Model
- `submissions`
- `analyses`
- `mistakes`
- `annotations`
