#services\security.py
import logging
import re
import unicodedata
from typing import Any, Optional, Tuple

from fastapi import HTTPException, status

# Sanitized logger - removes sensitive data
security_logger = logging.getLogger("security")


def sanitize_for_logging(data: dict, sensitive_keys: list[str] = None) -> dict:
    """
    Remove sensitive data from logs to prevent data leakage.
    """
    if sensitive_keys is None:
        sensitive_keys = [
            "description", "text", "prompt", "full_prompt",
            "api_key", "token", "password", "secret"
        ]

    sanitized = {}
    for key, value in data.items():
        key_lower = key.lower()
        if any(s in key_lower for s in sensitive_keys):
            # Truncate or mask
            if isinstance(value, str) and len(value) > 100:
                sanitized[key] = value[:100] + "... [MASKED]"
            else:
                sanitized[key] = "[MASKED]"
        else:
            sanitized[key] = value

    return sanitized


def log_analysis_request(event: str, data: dict, user_id: int = None):
    """Log analysis request with sanitized data."""
    sanitized = sanitize_for_logging(data)

    # Add user context if available
    context = {"user_id": user_id, "event": event, "data": sanitized}

    if user_id:
        security_logger.info(f"[{event}] User {user_id}: {sanitized}")
    else:
        security_logger.info(f"[{event}] {sanitized}")


def log_security_event(event: str, details: dict):
    """Log security-related events."""
    security_logger.warning(
        f"[SECURITY] {event}: {details}"
    )


def log_error_with_context(event: str, error: Exception, context: dict = None):
    """Log error without leaking sensitive data."""
    safe_context = sanitize_for_logging(context or {})

    security_logger.error(
        f"[ERROR] {event}: {type(error).__name__}: {str(error)} | Context: {safe_context}"
    )


# ============================================================
# Prompt Injection Detection
# ============================================================

class PromptInjectionDetector:
    """Detect and prevent prompt injection attempts."""
    
    # Critical patterns (immediate reject)
    CRITICAL_PATTERNS = [
        r"ignore\s+(previous|above|all)\s+instructions",
        r"disregard\s+(previous|above|all)",
        r"forget\s+(everything|all|your)",
        r"you\s+are\s+(now|a|an)\s+(ai|assistant|bot|model)",
        r"(new|change|update)\s+(your|system)\s+instructions",
        r"(system|admin)\s+prompt",
        r"reveal\s+(your|system)",
        r"pretend\s+(to\s+be|you\s+are)",
        r"roleplay\s+as",
        r"act\s+as\s+(a\s+)?(different|new|another)",
        r"override\s+(your|system)",
        r"bypass\s+(safety|restrictions)",
        r"<script[^>]*>",
        r"javascript:",
        r"on\w+\s*=",  # event handlers: onclick=, onerror=
        r"eval\s*\(",
        r"exec\s*\(",
        r"import\s*\(",
        r"__import__",
        r"\}\s*\{",  # JSON object injection
        r"\]\s*\[",  # JSON array injection
    ]
    
    # Suspicious patterns (score-based detection)
    SUSPICIOUS_PATTERNS = [
        r"output\s+(only|just|exactly)",
        r"respond\s+with",
        r"return\s+only",
        r"no\s+(other|additional|extra)",
        r"except\s+json",
        r"ignore\s+(all|everything)",
        r"disregard",
        r"instead\s+of",
        r"instead,",
        r"for\s+the\s+purpose\s+of",
        r"your\s+(task|job|role|function)",
        r"new\s+(task|role)",
    ]
    
    MAX_INPUT_LENGTH = 5000
    MIN_INPUT_LENGTH = 10
    
    @classmethod
    def is_suspicious(cls, text: str) -> Tuple[bool, Optional[str], float]:
        """
        Check if text contains injection patterns.
        
        Returns:
            Tuple of (is_suspicious, matched_pattern, threat_score)
        """
        text_lower = text.lower()
        threat_score = 0.0
        
        # Check critical patterns (high threat)
        for pattern in cls.CRITICAL_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                security_logger.warning(f"Critical injection detected: {pattern}")
                return True, pattern, 1.0
        
        # Check suspicious patterns (accumulate score)
        for pattern in cls.SUSPICIOUS_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                threat_score += 0.2
        
        if threat_score >= 0.4:
            security_logger.warning(f"High threat score: {threat_score}")
            return True, "accumulated_patterns", threat_score
        
        return False, None, threat_score

    @classmethod
    def sanitize(cls, text: str) -> str:
        """
        Sanitize user input with multiple defense layers.
        
        Args:
            text: User input text
            
        Returns:
            Sanitized text
            
        Raises:
            ValueError: If input fails any security checks
        """
        if not text or not isinstance(text, str):
            raise ValueError("Input must be a non-empty string")
        
        # Normalize unicode (e.g., Cyrillic 'а' → Latin 'a')
        text = unicodedata.normalize('NFKC', text)
        
        # Trim whitespace
        text = text.strip()
        
        # Check length
        if len(text) > cls.MAX_INPUT_LENGTH:
            raise ValueError(f"Input too long: {len(text)} > {cls.MAX_INPUT_LENGTH}")
        
        if len(text) < cls.MIN_INPUT_LENGTH:
            raise ValueError(f"Input too short: {len(text)} < {cls.MIN_INPUT_LENGTH}")
        
        # Check for injection attempts
        is_suspicious, pattern, score = cls.is_suspicious(text)
        
        if is_suspicious:
            security_logger.error(
                f"Prompt injection blocked: pattern='{pattern}', "
                f"score={score}, preview='{text[:80]}...'"
            )
            raise ValueError("Suspicious content detected")
        
        # Remove control characters (except newlines, tabs)
        text = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', text)
        
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Check for suspicious encoding attempts
        if any(indicator in text.lower() for indicator in ['%3c', '%3e', '%20', '\\x', '\\u']):
            raise ValueError("Encoded content not allowed")
        
        # Block JSON-like input (product cards are plain text, not JSON)
        if text.startswith('{') or text.startswith('['):
            security_logger.warning(f"JSON-like input blocked: {text[:50]}...")
            raise ValueError("JSON input not allowed for product cards")
        
        return text
    
    @classmethod
    def validate_product_card(cls, text: str) -> Tuple[bool, Optional[list]]:
        """
        Validate that text is actually a product card.
        
        Returns:
            Tuple of (is_valid, missing_fields)
        """
        text_lower = text.lower()
        
        # Check for required product card indicators
        has_name = any(kw in text_lower for kw in ['названи', 'name', 'товар', 'product', 'модел', 'model'])
        has_description = any(kw in text_lower for kw in ['описани', 'description', 'характеристик', 'specification', 'особенност', 'features'])
        has_price = any(kw in text_lower for kw in ['цен', 'price', 'стоимост', 'руб', '$', '€', '£'])
        has_category = any(kw in text_lower for kw in ['категор', 'category', 'тип', 'type', 'раздеел', 'section'])
        
        missing = []
        if not has_name:
            missing.append('name')
        if not has_description:
            missing.append('description')
        if not has_price:
            missing.append('price')
        if not has_category:
            missing.append('category')
        
        is_valid = len(missing) <= 1  # Allow 1 missing field
        
        return is_valid, missing if missing else None


def sanitize_product_input(card_text: str) -> str:
    """
    Sanitize product card input with defense-in-depth.
    
    Args:
        card_text: Raw product card text
        
    Returns:
        Sanitized text
        
    Raises:
        HTTPException: If sanitization fails
    """
    try:
        return PromptInjectionDetector.sanitize(card_text)
    except ValueError as e:
        security_logger.warning(f"Input sanitization failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


def validate_product_card(card_text: str) -> None:
    """
    Validate that input is a product card.
    
    Raises:
        HTTPException: If validation fails
    """
    is_valid, missing = PromptInjectionDetector.validate_product_card(card_text)
    
    if not is_valid:
        security_logger.warning(f"Invalid product card: missing={missing}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid product card format. Missing fields: {missing}"
        )
