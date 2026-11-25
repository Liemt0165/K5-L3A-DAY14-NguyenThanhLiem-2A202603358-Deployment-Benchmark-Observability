"""
Kết nối Redis dùng chung cho rate limiter và cost guard.
"""
import redis
from redis.exceptions import RedisError

from app.config import settings


def _create_client():
    if not settings.redis_url:
        return None
    return redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


r = _create_client()


def get_redis():
    """Trả về Redis client dùng chung (không ping lúc import)."""
    return r


def redis_healthy() -> bool:
    """Kiểm tra Redis sẵn sàng cho GET /ready; lỗi kết nối -> False."""
    if r is None:
        return False
    try:
        return bool(r.ping())
    except (RedisError, OSError):
        return False
