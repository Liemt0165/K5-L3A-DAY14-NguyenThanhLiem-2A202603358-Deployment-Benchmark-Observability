"""
Cost guard (tiêu chí 8) — theo dõi chi phí LLM trong Redis.
"""
from datetime import datetime, timezone

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import get_redis

PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006


def _budget_key() -> str:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"cost:daily:{day}"


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget -> raise HTTPException(status_code=402)."""
    client = get_redis()
    if client is None:
        raise HTTPException(status_code=503, detail="Cost guard storage unavailable")
    try:
        spent = float(client.get(_budget_key()) or 0.0)
    except RedisError:
        raise HTTPException(status_code=503, detail="Cost guard storage unavailable")

    if spent >= settings.daily_budget_usd:
        raise HTTPException(status_code=402, detail="Daily budget exceeded")


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí vào Redis, trả về chi phí request."""
    cost = (
        (input_tokens / 1000.0) * PRICE_INPUT_PER_1K
        + (output_tokens / 1000.0) * PRICE_OUTPUT_PER_1K
    )
    client = get_redis()
    if client is not None:
        key = _budget_key()
        try:
            client.incrbyfloat(key, cost)
            client.expire(key, 172800)
        except RedisError:
            pass
    return round(cost, 8)
