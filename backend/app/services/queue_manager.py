from __future__ import annotations

from typing import Any, Literal

from ..config import settings

try:
    from redis import Redis
    from rq import Queue
except Exception:  # pragma: no cover - optional runtime path
    Redis = None  # type: ignore[assignment]
    Queue = None  # type: ignore[assignment]


class QueueManager:
    def __init__(self) -> None:
        self._queue = None
        if settings.use_redis_queue and Redis is not None and Queue is not None:
            try:
                redis_conn = Redis.from_url(settings.redis_url)
                redis_conn.ping()
                self._queue = Queue("mistakepatch", connection=redis_conn)
            except Exception:
                self._queue = None

    @property
    def mode(self) -> Literal["redis", "background"]:
        return "redis" if self._queue is not None else "background"

    def enqueue_analysis(self, payload: dict[str, Any]) -> bool:
        if self._queue is None:
            return False
        job_id = payload.get("analysis_id")
        self._queue.enqueue("app.workers.tasks.run_analysis_job", payload, job_id=job_id)
        return True


queue_manager = QueueManager()
