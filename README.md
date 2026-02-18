# MistakePatch MVP

MistakePatch is a grading-oriented mistake notebook for handwritten math/physics solutions.

## Stack
- Frontend: Next.js 14 + TypeScript
- Backend: FastAPI + SQLite
- Queue: Redis + RQ (optional), FastAPI background fallback (default)
- AI: OpenAI Structured Outputs + fallback sample result

## Repository Layout
- `frontend/`: upload UI, result tabs, highlight overlay, history panel
- `backend/`: API, schema validation, OpenAI integration, fallback pipeline
- `infra/`: Dockerfiles + compose setup
- `docs/`: API summary + demo script

## Local Run
1. Backend
```bash
python -m venv .venv
. .venv/Scripts/activate  # PowerShell: .venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
copy backend/.env.example backend/.env
cd backend
..\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

2. Frontend
```bash
cd frontend
npm install
copy .env.example .env.local
npm run dev
```

3. Open browser
- Frontend: `http://localhost:3000`
- Backend health: `http://localhost:8000/api/v1/health`

## Environment Variables (Backend)
- `OPENAI_API_KEY`: primary key for live model calls (preferred)
- `OPENAI_ORGANIZATION`: optional; force billing org to avoid wrong default org
- `OPENAI_PROJECT`: optional; force billing project to avoid wrong default project
- `OPENAI_MODEL`: default `gpt-4o-mini`
- `GROQ_API_KEY`: optional fallback key used only when `OPENAI_API_KEY` is empty
- `GROQ_MODEL`: fallback model for Groq (default `llama-3.1-8b-instant`)
- `GROQ_BASE_URL`: default `https://api.groq.com/openai/v1`
- `ENABLE_OCR_HINTS`: `true/false` (default false)
- `USE_REDIS_QUEUE`: `true/false` (default false)
- `REDIS_URL`: default `redis://localhost:6379/0`

## Test
```bash
.\.venv\Scripts\python -m pytest backend/tests -q
```

## API Summary
- `POST /api/v1/analyze`
- `GET /api/v1/analysis/{analysis_id}`
- `POST /api/v1/annotations`
- `GET /api/v1/history?limit=5`
- `GET /api/v1/health`
