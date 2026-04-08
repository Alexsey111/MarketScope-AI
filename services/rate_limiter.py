#services\rate_limiter.py
import asyncio
import time
from typing import Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
import redis.asyncio as redis
from config import REDIS_URL


class RateLimiter:
    """Redis-based rate limiter with sliding window."""

    def __init__(
        self,
        requests_per_minute: int = 20,
        requests_per_hour: int = 100,
        redis_url: str = REDIS_URL
    ):
        self.requests_per_minute = requests_per_minute
        self.requests_per_hour = requests_per_hour
        self.redis_url = redis_url
        self._client: Optional[redis.Redis] = None

    async def _get_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.close()
            self._client = None

    async def check_limit(self, key: str) -> tuple[bool, dict]:
        """
        Check if request is within limits.
        Returns (allowed: bool, info: dict)
        """
        client = await self._get_client()
        now = time.time()

        # Sliding window: minute
        minute_key = f"ratelimit:{key}:minute"
        hour_key = f"ratelimit:{key}:hour"

        pipe = client.pipeline()
        pipe.zremrangebyscore(minute_key, 0, now - 60)
        pipe.zcard(minute_key)
        pipe.zremrangebyscore(hour_key, 0, now - 3600)
        pipe.zcard(hour_key)

        results = await pipe.execute()
        minute_count = results[1]
        hour_count = results[3]

        info = {
            "minute_used": minute_count,
            "minute_limit": self.requests_per_minute,
            "hour_used": hour_count,
            "hour_limit": self.requests_per_hour,
            "reset_in": 60 if minute_count >= self.requests_per_minute else 3600
        }

        # Check limits
        if minute_count >= self.requests_per_minute:
            info["reason"] = "minute_limit_exceeded"
            return False, info

        if hour_count >= self.requests_per_hour:
            info["reason"] = "hour_limit_exceeded"
            return False, info

        # Add request to windows
        pipe = client.pipeline()
        pipe.zadd(minute_key, {str(now): now})
        pipe.expire(minute_key, 65)
        pipe.zadd(hour_key, {str(now): now})
        pipe.expire(hour_key, 3700)
        await pipe.execute()

        return True, info


# Global rate limiter instance
rate_limiter = RateLimiter()


# ==============================
# OpenAI API Rate Limiter
# ==============================

# Synchronous Redis client for rate limiting
import redis
redis_client = redis.from_url(REDIS_URL, decode_responses=True)


class OpenAIRateLimiter:
    """Rate limiter for OpenAI API calls."""

    # OpenAI limits (for gpt-4o-mini)
    MAX_RPM = 500  # Requests per minute
    MAX_TPM = 200000  # Tokens per minute

    @staticmethod
    async def check_rate_limit(estimated_tokens: int = 1000) -> bool:
        """
        Check if we can make OpenAI API call.

        Args:
            estimated_tokens: Estimated tokens for this request

        Returns:
            True if allowed, False if rate limited
        """
        now = datetime.utcnow()
        minute_key = f"openai_rpm:{now.strftime('%Y%m%d%H%M')}"
        tokens_key = f"openai_tpm:{now.strftime('%Y%m%d%H%M')}"

        pipe = redis_client.pipeline()

        # Increment request counter
        pipe.incr(minute_key)
        pipe.expire(minute_key, 60)

        # Increment token counter
        pipe.incrby(tokens_key, estimated_tokens)
        pipe.expire(tokens_key, 60)

        results = pipe.execute()
        current_rpm = results[0]
        current_tpm = results[2]

        # Check limits
        if current_rpm > OpenAIRateLimiter.MAX_RPM:
            logger.warning(f"OpenAI RPM limit exceeded: {current_rpm}/{OpenAIRateLimiter.MAX_RPM}")
            # Wait until next minute
            seconds_to_wait = 60 - now.second
            await asyncio.sleep(seconds_to_wait)

        if current_tpm > OpenAIRateLimiter.MAX_TPM:
            logger.warning(f"OpenAI TPM limit exceeded: {current_tpm}/{OpenAIRateLimiter.MAX_TPM}")
            seconds_to_wait = 60 - now.second
            await asyncio.sleep(seconds_to_wait)

        return True
