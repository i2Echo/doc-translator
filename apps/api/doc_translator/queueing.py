from functools import lru_cache

import redis

from doc_translator.core.config import get_settings


TRANSLATION_QUEUE_KEY = "translation_jobs"


@lru_cache(maxsize=1)
def get_redis_client() -> redis.Redis:
    settings = get_settings()
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


def enqueue_job(job_id: str) -> None:
    get_redis_client().rpush(TRANSLATION_QUEUE_KEY, job_id)
