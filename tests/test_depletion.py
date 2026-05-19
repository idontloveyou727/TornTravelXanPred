from datetime import datetime, timezone

from app.depletion import calculate_depletion_rate_per_minute, estimate_depleted_time_from_last_positive
from app.models import StockObservation


def obs(hour: int, minute: int, second: int, quantity: int) -> StockObservation:
    return StockObservation(
        observed_at=datetime(2026, 1, 1, hour, minute, second, tzinfo=timezone.utc),
        item_id=206,
        country="UK",
        quantity=quantity,
    )


def test_depletion_rate_uses_only_positive_to_positive_drop() -> None:
    assert calculate_depletion_rate_per_minute(obs(0, 0, 0, 1982), obs(0, 1, 0, 1772)) == 210
    assert calculate_depletion_rate_per_minute(obs(0, 0, 0, 0), obs(0, 1, 0, 1772)) is None
    assert calculate_depletion_rate_per_minute(obs(0, 0, 0, 19), obs(0, 1, 0, 0)) is None
    assert calculate_depletion_rate_per_minute(obs(0, 0, 0, 100), obs(0, 1, 0, 150)) is None


def test_estimated_depleted_at_ceil_to_next_minute() -> None:
    estimate = estimate_depleted_time_from_last_positive(obs(0, 20, 2, 5), rate_per_minute=312.5)

    assert estimate.estimated_at == datetime(2026, 1, 1, 0, 21, 0, tzinfo=timezone.utc)
