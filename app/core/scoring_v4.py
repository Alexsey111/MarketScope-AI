"""
Scoring Engine V4 - Non-linear transforms with logistic curves.
This module is the single source of truth for scoring logic.
"""
import math
import statistics
from typing import Dict, List, Optional
from pydantic import BaseModel, field_validator
from enum import Enum


SCORING_VERSION = "v4.0"


class Niche(str, Enum):
    fashion = "fashion"
    electronics = "electronics"
    fmcg = "fmcg"
    default = "default"


class ScoringInput(BaseModel):
    """Input model for scoring with validation."""
    niche: Niche
    completeness: float
    seo_score: float
    usp_score: float
    visual_quality: float
    price_position: float
    competition_intensity: float
    differentiation: float
    entry_barrier: float
    demand_proxy: float
    price_alignment: float
    category_maturity: float
    brand_dependency: float
    logistics_complexity: float
    margin_percent: float
    upsell_potential: float
    repeat_purchase: float
    expansion_vector: float
    
    @field_validator('*', mode='before')
    @classmethod
    def clamp_values(cls, v, info):
        """Clamp all numeric values to [0, 100] range."""
        if info.field_name == 'niche':
            return v
        try:
            val = float(v)
            return max(0, min(100, val))
        except (TypeError, ValueError):
            return 50  # Safe default


# ==============================
# NON-LINEAR TRANSFORMS
# ==============================

def logistic(x: float, k: float = 0.1, x0: float = 50) -> float:
    """
    Logistic curve: score = 100 / (1 + exp(-k * (x - x0)))
    
    Args:
        x: Input value (0-100)
        k: Steepness (default 0.1)
        x0: Inflection point (default 50)
    
    Returns:
        Transformed score (0-100)
    """
    try:
        return 100 / (1 + math.exp(-k * (x - x0)))
    except OverflowError:
        return 0 if x < x0 else 100


def inverse_logistic(x: float, k: float = 0.1, x0: float = 50) -> float:
    """Inverse logistic (for penalties)."""
    return 100 - logistic(x, k, x0)


# ==============================
# SCORING ENGINE
# ==============================

class ScoringEngineV4:
    """V4 scoring engine with non-linear transforms."""

    version = SCORING_VERSION

    # Weights matching README documentation
    WEIGHTS = {
        "product": 0.35,
        "market": 0.30,
        "platform": 0.20,
        "growth": 0.15
    }

    def product_score(self, d: ScoringInput) -> float:
        """Product quality assessment (35% weight)."""
        visual_boost = logistic(d.visual_quality, k=0.12)
        seo_boost = logistic(d.seo_score, k=0.1)

        return (
            0.25 * logistic(d.completeness) +
            0.20 * seo_boost +
            0.20 * logistic(d.usp_score) +
            0.20 * visual_boost +
            0.15 * logistic(d.price_position)
        )

    def market_score(self, d: ScoringInput) -> float:
        """Market opportunity assessment (30% weight)."""
        competition_penalty = inverse_logistic(d.competition_intensity, k=0.15)

        return (
            0.30 * competition_penalty +
            0.30 * logistic(d.differentiation) +
            0.20 * inverse_logistic(d.entry_barrier) +
            0.20 * logistic(d.demand_proxy)
        )

    def platform_score(self, d: ScoringInput) -> float:
        """Platform fit assessment (20% weight)."""
        return (
            0.30 * logistic(d.price_alignment) +
            0.25 * logistic(d.category_maturity) +
            0.25 * inverse_logistic(d.brand_dependency) +
            0.20 * inverse_logistic(d.logistics_complexity)
        )

    def growth_score(self, d: ScoringInput) -> float:
        """Growth potential assessment (15% weight)."""
        margin_curve = logistic(d.margin_percent, k=0.2, x0=25)

        return (
            0.40 * margin_curve +
            0.20 * logistic(d.upsell_potential) +
            0.20 * logistic(d.repeat_purchase) +
            0.20 * logistic(d.expansion_vector)
        )

    def composite_risk(self, d: ScoringInput) -> tuple[float, List[str]]:
        """Calculate composite risk with interaction effects."""
        risk = 0
        flags = []

        # Margin risk (0-5 points)
        margin_risk = max(0, (20 - d.margin_percent) * 0.5)
        if margin_risk > 0:
            risk += margin_risk
            flags.append("low_margin")

        # Competition risk (0-12 points)
        competition_risk = max(0, (d.competition_intensity - 60) * 0.3)
        if competition_risk > 0:
            risk += competition_risk
            flags.append("high_competition")

        # Critical triple interaction (+25 points)
        if (d.margin_percent < 15 and
            d.competition_intensity > 70 and
            d.differentiation < 40):
            risk += 25
            flags.append("critical_market_risk")

        return min(risk, 40), flags

    def confidence(self, subscores: List[float], completeness: float) -> float:
        """Calculate confidence score based on consistency and completeness."""
        if not subscores:
            return 50.0
        
        std_dev = statistics.pstdev(subscores)
        stability = max(0, 1 - std_dev / 50)

        return (
            0.5 * (completeness / 100) +
            0.3 * stability +
            0.2
        ) * 100

    def calculate(self, d: ScoringInput, debug: bool = False) -> Dict:
        """
        Calculate final score with all components.
        
        Args:
            d: Scoring input data
            debug: Include debug information in output
        
        Returns:
            Dictionary with scores and metadata
        """
        # Component scores
        product = self.product_score(d)
        market = self.market_score(d)
        platform = self.platform_score(d)
        growth = self.growth_score(d)

        # Weighted average (matching README: 35/30/20/15)
        base = (
            self.WEIGHTS["product"] * product +
            self.WEIGHTS["market"] * market +
            self.WEIGHTS["platform"] * platform +
            self.WEIGHTS["growth"] * growth
        )
        
        # Risk penalty
        risk, risk_flags = self.composite_risk(d)
        final = max(0, min(100, base - risk))

        # Confidence score
        conf = self.confidence([product, market, platform, growth], d.completeness)

        result = {
            "version": self.version,
            "product_score": round(product, 2),
            "market_score": round(market, 2),
            "platform_score": round(platform, 2),
            "growth_score": round(growth, 2),
            "risk_penalty": round(risk, 2),
            "risk_flags": risk_flags,
            "final_score": round(final, 2),
            "confidence": round(conf, 2)
        }
        
        if debug:
            result["debug"] = {
                "base_score_before_risk": round(base, 2),
                "weighted_contributions": {
                    "product": round(self.WEIGHTS["product"] * product, 2),
                    "market": round(self.WEIGHTS["market"] * market, 2),
                    "platform": round(self.WEIGHTS["platform"] * platform, 2),
                    "growth": round(self.WEIGHTS["growth"] * growth, 2)
                },
                "raw_inputs": d.dict()
            }
        
        return result

    def compute(self, data: dict, debug: bool = False) -> Dict:
        """
        Compute score from dict data (for Celery tasks).
        Includes safe validation and default handling.
        
        Args:
            data: Raw input dictionary
            debug: Include debug information
        
        Returns:
            Scoring result dictionary
        """
        def safe_float(value, default=50, min_val=0, max_val=100):
            """Safely convert and clamp numeric values."""
            try:
                val = float(value) if value is not None else default
                return max(min_val, min(max_val, val))
            except (TypeError, ValueError):
                return default
        
        def safe_niche(value):
            """Safely parse niche enum."""
            try:
                return Niche(value) if value else Niche.default
            except (ValueError, TypeError):
                return Niche.default
        
        # Build validated input
        scoring_input = ScoringInput(
            niche=safe_niche(data.get("niche")),
            completeness=safe_float(data.get("completeness"), 50),
            seo_score=safe_float(data.get("seo_score"), 50),
            usp_score=safe_float(data.get("usp_score"), 50),
            visual_quality=safe_float(data.get("visual_quality"), 50),
            price_position=safe_float(data.get("price_position"), 50),
            competition_intensity=safe_float(data.get("competition_intensity"), 50),
            differentiation=safe_float(data.get("differentiation"), 50),
            entry_barrier=safe_float(data.get("entry_barrier"), 50),
            demand_proxy=safe_float(data.get("demand_proxy"), 50),
            price_alignment=safe_float(data.get("price_alignment"), 50),
            category_maturity=safe_float(data.get("category_maturity"), 50),
            brand_dependency=safe_float(data.get("brand_dependency"), 50),
            logistics_complexity=safe_float(data.get("logistics_complexity"), 50),
            margin_percent=safe_float(data.get("margin_percent"), 25),
            upsell_potential=safe_float(data.get("upsell_potential"), 50),
            repeat_purchase=safe_float(data.get("repeat_purchase"), 50),
            expansion_vector=safe_float(data.get("expansion_vector"), 50),
        )

        return self.calculate(scoring_input, debug=debug)


# Global engine instance
scoring_engine = ScoringEngineV4()
