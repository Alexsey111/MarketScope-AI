#services\cache.py
import hashlib
import json
import logging
import time
from typing import Optional, Dict, Any
import redis.asyncio as redis
from config import REDIS_URL

logger = logging.getLogger(__name__)


class AnalysisCache:
    """Cache for analysis results using hash of title + description."""

    def __init__(self, ttl_seconds: int = 3600, redis_url: str = REDIS_URL):
        self.ttl = ttl_seconds
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

    @staticmethod
    def compute_hash(title: str, description: str) -> str:
        """Compute SHA256 hash of title + description."""
        content = f"{title.strip().lower()}|{description.strip().lower()}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    async def get(self, title: str, description: str) -> Optional[Dict[str, Any]]:
        """Get cached analysis result."""
        key = self.compute_hash(title, description)
        client = await self._get_client()

        cached = await client.get(f"analysis:{key}")
        if cached:
            return json.loads(cached)
        return None

    async def set(self, title: str, description: str, result: Dict[str, Any]) -> None:
        """Store analysis result in cache."""
        key = self.compute_hash(title, description)
        client = await self._get_client()

        await client.setex(
            f"analysis:{key}",
            self.ttl,
            json.dumps(result)
        )


# Global cache instance
analysis_cache = AnalysisCache()


# ============================================================
# LLM Response Cache
# ============================================================

class LLMCache:
    """Redis cache for LLM responses with deterministic prompts."""
    
    CACHE_TTL = 3600 * 24  # 24 hours
    
    def __init__(self, redis_url: str = REDIS_URL):
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
    
    @staticmethod
    def generate_cache_key(prompt: str, model: str, temperature: float) -> str:
        """Generate cache key from prompt parameters."""
        key_data = f"{model}:{temperature}:{prompt}"
        hash_obj = hashlib.sha256(key_data.encode())
        return f"llm_cache:{hash_obj.hexdigest()}"
    
    async def get(self, prompt: str, model: str, temperature: float) -> Optional[Dict[str, Any]]:
        """Get cached LLM response."""
        key = self.generate_cache_key(prompt, model, temperature)
        
        try:
            client = await self._get_client()
            cached = await client.get(key)
            
            if cached:
                logger.info(f"LLM cache hit: {key[:32]}...")
                return json.loads(cached)
        except Exception as e:
            logger.warning(f"Cache retrieval failed: {e}")
        
        return None
    
    async def set(self, prompt: str, model: str, temperature: float, response: Dict[str, Any]) -> None:
        """Cache LLM response."""
        key = self.generate_cache_key(prompt, model, temperature)
        
        try:
            client = await self._get_client()
            await client.setex(
                key,
                self.CACHE_TTL,
                json.dumps(response)
            )
            logger.info(f"LLM response cached: {key[:32]}...")
        except Exception as e:
            logger.warning(f"Cache storage failed: {e}")


# Global LLM cache instance
llm_cache = LLMCache()
