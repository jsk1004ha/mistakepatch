from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    data_dir: Path
    db_path: Path
    storage_path: Path
    fallback_path: Path
    max_upload_bytes: int
    allowed_origins: list[str]
    openai_api_key: str | None
    openai_organization: str | None
    openai_project: str | None
    openai_model: str
    openai_timeout_seconds: int
    groq_api_key: str | None
    groq_model: str
    groq_base_url: str
    enable_ocr_hints: bool
    consensus_runs: int
    consensus_min_agreement: float
    uncertainty_threshold: float
    use_redis_queue: bool
    redis_url: str

    @classmethod
    def load(cls) -> "Settings":
        base_dir = Path(__file__).resolve().parents[1]
        _load_dotenv(base_dir / ".env")
        data_dir = base_dir / "data"

        db_value = os.getenv("MISTAKEPATCH_DB_PATH", "data/mistakepatch.db")
        storage_value = os.getenv("MISTAKEPATCH_STORAGE_PATH", "data/uploads")
        fallback_path = data_dir / "fallback_sample_result.json"

        db_path_raw = Path(db_value)
        storage_path_raw = Path(storage_value)
        db_path = (base_dir / db_path_raw).resolve() if not db_path_raw.is_absolute() else db_path_raw
        storage_path = (
            (base_dir / storage_path_raw).resolve()
            if not storage_path_raw.is_absolute()
            else storage_path_raw
        )

        max_upload_mb = int(os.getenv("MISTAKEPATCH_MAX_UPLOAD_MB", "10"))
        allowed_origins_env = os.getenv(
            "MISTAKEPATCH_ALLOWED_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000,https://mistakepatch-vercel.vercel.app",
        )
        allowed_origins = [item.strip() for item in allowed_origins_env.split(",") if item.strip()]

        return cls(
            base_dir=base_dir,
            data_dir=data_dir,
            db_path=db_path,
            storage_path=storage_path,
            fallback_path=fallback_path,
            max_upload_bytes=max_upload_mb * 1024 * 1024,
            allowed_origins=allowed_origins,
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_organization=os.getenv("OPENAI_ORGANIZATION"),
            openai_project=os.getenv("OPENAI_PROJECT"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            openai_timeout_seconds=int(os.getenv("OPENAI_TIMEOUT_SECONDS", "25")),
            groq_api_key=os.getenv("GROQ_API_KEY"),
            groq_model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
            groq_base_url=os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
            enable_ocr_hints=_to_bool(os.getenv("ENABLE_OCR_HINTS"), default=False),
            consensus_runs=max(1, int(os.getenv("MISTAKEPATCH_CONSENSUS_RUNS", "3"))),
            consensus_min_agreement=max(
                0.0,
                min(1.0, float(os.getenv("MISTAKEPATCH_CONSENSUS_MIN_AGREEMENT", "0.55"))),
            ),
            uncertainty_threshold=max(
                0.0,
                min(1.0, float(os.getenv("MISTAKEPATCH_UNCERTAINTY_THRESHOLD", "0.6"))),
            ),
            use_redis_queue=_to_bool(os.getenv("USE_REDIS_QUEUE"), default=False),
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        )


settings = Settings.load()
