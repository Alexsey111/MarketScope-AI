import re

NICHE_WEIGHTS = {
    "electronics": {
        "length": 15,
        "features": 30,
        "usp": 15,
        "numbers": 25,
        "structure": 15
    },
    "clothing": {
        "length": 15,
        "features": 15,
        "usp": 20,
        "numbers": 10,
        "structure": 20,
        "emotion": 20
    },
    "home": {
        "length": 20,
        "features": 20,
        "usp": 15,
        "numbers": 15,
        "structure": 20,
        "emotion": 10
    }
}

def detect_emotional_words(text: str) -> int:
    emotional_words = ["стильный", "комфортный", "идеальный", "уют", "модный"]
    return sum(1 for word in emotional_words if word in text.lower())

def calculate_score(text: str, niche: str = "electronics") -> dict:
    weights = NICHE_WEIGHTS.get(niche, NICHE_WEIGHTS["electronics"])
    total_score = 0
    details = {}

    # Length
    length_score = weights["length"] if len(text) > 800 else weights["length"] // 2
    total_score += length_score
    details["Длина"] = length_score

    # Features
    keywords = ["материал", "размер", "вес", "характеристики", "мощность"]
    found = sum(1 for word in keywords if word in text.lower())
    feature_score = min(found * (weights["features"] // 5), weights["features"])
    total_score += feature_score
    details["Характеристики"] = feature_score

    # USP
    usp_words = ["уникальный", "эксклюзив", "инновационный"]
    usp_score = weights["usp"] if any(word in text.lower() for word in usp_words) else weights["usp"] // 3
    total_score += usp_score
    details["УТП"] = usp_score

    # Numbers
    numbers = re.findall(r"\d+", text)
    number_score = weights["numbers"] if len(numbers) >= 3 else weights["numbers"] // 2
    total_score += number_score
    details["Цифры"] = number_score

    # Structure
    structure_score = weights["structure"] if text.count("\n") >= 5 else weights["structure"] // 2
    total_score += structure_score
    details["Структура"] = structure_score

    # Emotion (если есть)
    if "emotion" in weights:
        emotion_score = min(detect_emotional_words(text) * 5, weights["emotion"])
        total_score += emotion_score
        details["Эмоциональность"] = emotion_score

    return {
        "total_score": min(total_score, 100),
        "details": details
    }


def format_score_block(score_data: dict) -> str:
    """
    Format scoring results for human‑readable Telegram output.

    Expected input structure:
        {
            "total_score": <int>,
            "details": {
                "<name>": <int>,
                ...
            }
        }
    """
    total = score_data.get("total_score", 0)
    details = score_data.get("details", {}) or {}

    lines = [f"📊 Итоговый скоринг: {total}/100"]

    if details:
        lines.append("")
        lines.append("Детализация по критериям:")
        for name, value in details.items():
            lines.append(f"• {name}: {value}")

    return "\n".join(lines)