"""
Rate limiting (tiêu chí 7) — sliding window 60s lưu trong Redis.
"""
import time
import uuid

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import get_redis

WINDOW_SECONDS = 60


def check_rate_limit(key: str) -> None:
    """Kiểm tra giới hạn request/phút theo API key bằng Redis sorted set."""
    client = get_redis()
    if client is None:
        raise HTTPException(status_code=503, detail="Rate limiter storage unavailable")

    now = time.time()
    redis_key = f"ratelimit:{key}"
    try:
        client.zremrangebyscore(redis_key, 0, now - WINDOW_SECONDS)
        current_count = client.zcard(redis_key)
        if current_count >= settings.rate_limit_per_minute:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(WINDOW_SECONDS)},
            )
        member = f"{now}:{uuid.uuid4().hex}"
        client.zadd(redis_key, {member: now})
        client.expire(redis_key, WINDOW_SECONDS)
    except RedisError:
        raise HTTPException(status_code=503, detail="Rate limiter storage unavailable")
