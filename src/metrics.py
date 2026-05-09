import json
import threading
import time

from redis import Redis

from src.config import settings

# Redis-backed so both API and worker processes share the same counters
METRICS_PREFIX = "metrics:"


class MetricsCollector:
    def __init__(self) -> None:
        self._redis: Redis | None = None

    def _conn(self) -> Redis:
        if self._redis is None:
            self._redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._redis

    def record_submission(self) -> None:
        self._conn().incr(f"{METRICS_PREFIX}jobs_submitted")

    def record_completion(self, processing_time: float, tokens: int) -> None:
        pipe = self._conn().pipeline()
        pipe.incr(f"{METRICS_PREFIX}jobs_completed")
        pipe.incrbyfloat(f"{METRICS_PREFIX}total_tokens", tokens)
        pipe.rpush(f"{METRICS_PREFIX}processing_times", str(round(processing_time, 3)))
        pipe.execute()

    def record_failure(self, error_type: str) -> None:
        pipe = self._conn().pipeline()
        pipe.incr(f"{METRICS_PREFIX}jobs_failed")
        pipe.hincrby(f"{METRICS_PREFIX}error_counts", error_type, 1)
        pipe.execute()

    def snapshot(self) -> dict:
        r = self._conn()
        pipe = r.pipeline()
        pipe.get(f"{METRICS_PREFIX}jobs_submitted")
        pipe.get(f"{METRICS_PREFIX}jobs_completed")
        pipe.get(f"{METRICS_PREFIX}jobs_failed")
        pipe.get(f"{METRICS_PREFIX}total_tokens")
        pipe.lrange(f"{METRICS_PREFIX}processing_times", 0, -1)
        pipe.hgetall(f"{METRICS_PREFIX}error_counts")
        submitted, completed, failed, tokens, times_raw, errors = pipe.execute()

        times = sorted(float(t) for t in times_raw) if times_raw else []
        avg = sum(times) / len(times) if times else 0.0
        p95 = times[int(len(times) * 0.95)] if times else 0.0

        return {
            "jobs_submitted": int(submitted or 0),
            "jobs_completed": int(completed or 0),
            "jobs_failed": int(failed or 0),
            "total_tokens": int(float(tokens or 0)),
            "avg_processing_time": round(avg, 3),
            "p95_processing_time": round(p95, 3),
            "error_counts_by_type": {k: int(v) for k, v in errors.items()} if errors else {},
        }


metrics = MetricsCollector()
