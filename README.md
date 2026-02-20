# MistakePatch MVP

MistakePatch is a grading-oriented mistake notebook for handwritten math/physics solutions.

MistakePatch는 손글씨 수학/물리 풀이를 "정답 해설"보다 "채점과 감점 원인 파악"에 집중해서 정리해주는 오답노트 MVP입니다.

## 이 MVP로 가능한 것
- 손글씨 풀이 이미지 업로드 (+ 문제 이미지 옵션)
- AI 채점(루브릭 기반) 결과를 다음 형태로 표시
  - 감점 포인트(미스테이크 카드)
  - 최소 수정 패치(minimal patch) 제안
  - 다음 체크리스트
- 위치 하이라이트(MVP 안정형 플로우)
  - 미스테이크 카드를 클릭한 뒤, 캔버스에서 한 번 탭해서 하이라이트 좌표를 저장
- 분석 결과를 노트로 자동 저장해서 노트북(Inbox/휴지통)에서 이동/복구/삭제 가능
- 히스토리 + Top 태그(자주 틀리는 유형) 표시

## Stack
- Frontend: Next.js 14 + TypeScript
- Backend: FastAPI + SQLite
- Queue: Redis + RQ (optional), FastAPI background fallback (default)
- AI: OpenAI Structured Outputs + fallback sample result

## 레포 구조
- `frontend/`: 업로드 UI, 결과 탭, 하이라이트 오버레이, 히스토리 패널
- `backend/`: API, 스키마 검증, OpenAI 연동, fallback 파이프라인
- `infra/`: Dockerfiles + compose setup
- `docs/`: API 요약 + 데모 스크립트

프론트 주요 파일:
- `frontend/app/page.tsx`: 메인 페이지 연결부(훅/컴포넌트로 분리됨)
- `frontend/hooks/`: 추출된 훅 (`useNotebooksState`, `useAnalysisFlow`)
- `frontend/lib/home/pageUtils.ts`: 메인 페이지에서 공용으로 쓰는 유틸
- `frontend/components/home/NoteDetailModal.tsx`: 노트 상세 모달(분리됨)

## 빠른 시작(추천)

이 레포에는 원커맨드 실행 스크립트가 들어있습니다:
- `dev`: 백엔드 + 프론트 dev 서버 실행
- `test`: lint + build 후 production 서버(`next start`)로 Playwright E2E 실행 (fallback 고정이라 재현성 좋음)

0. 준비물
- Python + Node.js(npm)

1. 가상환경(venv) 만들고 백엔드 의존성 설치

옵션 A(추천): `backend/.venv`
```bash
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env
```

옵션 B: 레포 루트 `.venv`
```bash
python -m venv .venv
.\.venv\Scripts\python -m pip install -r backend\requirements.txt
copy backend\.env.example backend\.env
```

2. 프론트 의존성 설치
```bash
cd frontend
npm install
```

3. (선택) API 키 연동(라이브 모델 호출: dev 모드)
- `backend/.env`에 `OPENAI_API_KEY=...` 추가(커밋 금지) 또는 쉘 환경변수로 설정

4. 실행
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\mistakepatch.ps1 -Mode dev
```

5. 브라우저 접속
- Frontend: `http://localhost:3000`
- Backend health: `http://localhost:8000/api/v1/health`

## 환경 변수(Backend)
- `OPENAI_API_KEY`: 라이브 모델 호출 키(dev 모드)
- `OPENAI_MODEL`: 기본값 `gpt-4o-mini`
- `OPENAI_TIMEOUT_SECONDS`: 기본값 `25`
- `ENABLE_OCR_HINTS`: `true/false` (기본 false)
- `USE_REDIS_QUEUE`: `true/false` (기본 false)
- `REDIS_URL`: 기본값 `redis://localhost:6379/0`
- `MISTAKEPATCH_DB_PATH`: 기본값 `data/mistakepatch.db`
- `MISTAKEPATCH_STORAGE_PATH`: 기본값 `data/uploads`
- `MISTAKEPATCH_MAX_UPLOAD_MB`: 기본값 `10`
- `MISTAKEPATCH_ALLOWED_ORIGINS`: 기본값 `http://localhost:3000,http://127.0.0.1:3000`

주의:
- `OPENAI_API_KEY`가 없으면 백엔드는 `backend/data/fallback_sample_result.json`로 fallback 처리합니다(데모/테스트 안정성).
- 테스트 러너(`scripts/mistakepatch.ps1 -Mode test`)는 E2E 재현성을 위해 `OPENAI_API_KEY`를 강제로 비워서(fallback) 실행합니다.

## 테스트
추천:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\mistakepatch.ps1 -Mode test
```

백엔드만:
```bash
backend\.venv\Scripts\python -m pytest -q
```

프론트 E2E만(서버가 떠 있어야 함):
```bash
cd frontend
npm run test:e2e
```

## API Summary
- `POST /api/v1/analyze`
- `GET /api/v1/analysis/{analysis_id}`
- `POST /api/v1/annotations`
- `GET /api/v1/history?limit=5`
- `GET /api/v1/health`

인증/격리 참고:
- `/api/v1/health`를 제외한 API는 `X-User-Id` 헤더가 필요합니다.
- 동일 백엔드 인스턴스에서 사용자 데이터는 `X-User-Id` 기준으로 분리 조회됩니다.
