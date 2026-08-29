import random
from datetime import datetime, timezone
from typing import List, Optional


def _hours_since(timestamp: Optional[str], now: datetime) -> float:
    if not timestamp:
        return 10_000.0
    reviewed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return max(0.0, (now - reviewed).total_seconds() / 3600)


def adaptive_cards(cards: List[dict], limit: int, now: Optional[datetime] = None) -> List[dict]:
    """Return a varied, no-deadline selection. Low confidence and new cards win.

    Time since review is a gentle boost only: every card remains eligible at all times.
    """
    now = now or datetime.now(timezone.utc)
    if len(cards) <= limit:
        shuffled = cards[:]
        random.shuffle(shuffled)
        return shuffled

    scored = []
    for card in cards:
        seen = card["seen_count"]
        confidence = card["confidence"]
        age_boost = min(0.9, _hours_since(card["last_reviewed_at"], now) / (24 * 30))
        new_boost = 3.5 if seen == 0 else 0
        wrong_rate = card["wrong_count"] / seen if seen else 0
        score = new_boost + (2.5 - confidence) + (wrong_rate * 2) + age_boost + random.random() * 0.35
        scored.append((score, card))

    scored.sort(key=lambda item: item[0], reverse=True)
    # Preserve a small familiar-card slice so the learner is not only drilled on misses.
    weak_count = max(1, round(limit * 0.8))
    selected = [card for _, card in scored[:weak_count]]
    remainder = [card for _, card in scored[weak_count:]]
    if remainder:
        selected.extend(random.sample(remainder, min(limit - len(selected), len(remainder))))
    random.shuffle(selected)
    return selected


def update_confidence(current: float, result: str) -> float:
    if result == "right":
        return min(3.0, current + 0.42)
    return max(-3.0, current - 0.85)
