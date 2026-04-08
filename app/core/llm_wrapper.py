"""
LLM wrapper for async tasks.
"""
import asyncio
from typing import Type, Optional
from pydantic import BaseModel, ValidationError


class LLMClient:
    """Async LLM client wrapper."""

    def __init__(
        self,
        client,
        model: str = "gpt-4o-mini",
        temperature: float = 0.2,
        max_tokens: int = 1500,
        timeout: int = 25
    ):
        self.client = client
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    async def generate(
        self,
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[dict] = None
    ) -> str:
        """Generate text response from LLM."""
        temp = temperature if temperature is not None else self.temperature
        tokens = max_tokens if max_tokens is not None else self.max_tokens

        response = await asyncio.wait_for(
            self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a strict JSON generator."},
                    {"role": "user", "content": prompt}
                ],
                temperature=temp,
                max_tokens=tokens,
                response_format=response_format or {"type": "json_object"}
            ),
            timeout=self.timeout
        )

        return response.choices[0].message.content

    async def generate_json(
        self,
        prompt: str,
        response_model: Type[BaseModel],
        retries: int = 2
    ) -> BaseModel:
        """Generate and validate JSON response."""
        import json

        for attempt in range(retries):
            try:
                response = await self.generate(prompt)
                parsed = response_model.model_validate_json(response)
                return parsed

            except (ValidationError, json.JSONDecodeError):
                if attempt == retries - 1:
                    raise
                await asyncio.sleep(1 * (attempt + 1))

            except asyncio.TimeoutError:
                if attempt == retries - 1:
                    raise
                await asyncio.sleep(2 * (attempt + 1))

        raise RuntimeError("LLM generation failed after retries")


class LLMWrapper:
    """Main LLM wrapper with retry and timeout."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        temperature: float = 0.2,
        max_tokens: int = 1500,
        timeout: int = 25,
        retries: int = 2
    ):
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.retries = retries

        self._llm_client = LLMClient(
            self.client,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout
        )

    async def generate(self, prompt: str) -> str:
        """Generate text response."""
        return await self._llm_client.generate(prompt)

    async def generate_json(self, prompt: str, response_model: Type[BaseModel]) -> BaseModel:
        """Generate validated JSON response."""
        return await self._llm_client.generate_json(prompt, response_model, self.retries)

    async def analyze(self, payload: dict) -> dict:
        """
        Analyze product and return scoring metrics.
        In production, this calls LLM with proper prompts.
        """
        # For now, return mock data - in production call LLM
        return self._mock_analyze(payload)

    def _mock_analyze(self, payload: dict) -> dict:
        """Mock analysis for testing."""
        return {
            "niche": payload.get("niche", "default"),
            "completeness": payload.get("completeness", 50),
            "seo_score": payload.get("seo_score", 50),
            "usp_score": payload.get("usp_score", 50),
            "visual_quality": payload.get("visual_quality", 50),
            "price_position": payload.get("price_position", 50),
            "competition_intensity": payload.get("competition_intensity", 50),
            "differentiation": payload.get("differentiation", 50),
            "entry_barrier": payload.get("entry_barrier", 50),
            "demand_proxy": payload.get("demand_proxy", 50),
            "price_alignment": payload.get("price_alignment", 50),
            "category_maturity": payload.get("category_maturity", 50),
            "brand_dependency": payload.get("brand_dependency", 50),
            "logistics_complexity": payload.get("logistics_complexity", 50),
            "margin_percent": payload.get("margin_percent", 25),
            "upsell_potential": payload.get("upsell_potential", 50),
            "repeat_purchase": payload.get("repeat_purchase", 50),
            "expansion_vector": payload.get("expansion_vector", 50),
        }

    def analyze_sync(self, payload: dict) -> dict:
        """
        Synchronous analyze for Celery tasks.
        """
        return self._mock_analyze(payload)
