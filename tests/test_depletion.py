from datetime import datetime, timezone

from app.depletion import (
    calculate_depletion_rate_per_minute,
    estimate_depleted_time_from_last_positive,
    filter_depletion_rate_history,
    stable_depletion_rate,
)
from app.models import StockObservation


def obs(hour: int, minute: int, second: int, quantity: int) -> StockObservation:
    return StockObservation(
        observed_at=datetime(2026, 1, 1, hour, minute, second, tzinfo=timezone.utc),
        item_id=206,
        country="UK",
        quantity=quantity,
    )


def test_depletion_rate_uses_only_positive_to_positive_drop() -> None:
    assert calculate_depletion_rate_per_minute(obs(0, 0, 0, 1982), obs(0, 2, 0, 1562)) == 210
    assert calculate_depletion_rate_per_minute(obs(0, 0, 0, 0), obs(0, 2, 0, 1772)) is None
    assert calculate_depletion_rate_per_minute(obs(0, 0, 0, 19), obs(0, 2, 0, 0)) is None
    assert calculate_depletion_rate_per_minute(obs(0, 0, 0, 100), obs(0, 2, 0, 150)) is None


def test_depletion_rate_ignores_too_short_samples() -> None:
    assert calculate_depletion_rate_per_minute(obs(0, 0, 0, 1982), obs(0, 1, 0, 1772)) is None


def test_estimated_depleted_at_ceil_to_next_minute() -> None:
    estimate = estimate_depleted_time_from_last_positive(obs(0, 20, 2, 5), rate_per_minute=312.5)

    assert estimate.estimated_at == datetime(2026, 1, 1, 0, 21, 0, tzinfo=timezone.utc)


def test_filter_depletion_rate_history_removes_obvious_bounds_outliers() -> None:
    history = [250, 251, 252, 40, 900, 253, 254]

    assert filter_depletion_rate_history(history, default_rate=250) == [250, 251, 252, 253, 254]
    assert stable_depletion_rate(history, default_rate=250) == 252


def test_filter_depletion_rate_history_removes_mad_outliers() -> None:
    history = [
        245.76982283829486,
        242.3361936072318,
        78.45579383778774,
        386.575588865477,
        459.9477191334383,
        268.76836797640857,
        260.0914330146905,
        265.3097740920848,
    ]

    filtered = filter_depletion_rate_history(history, default_rate=312.5)

    assert 78.45579383778774 not in filtered
    assert 386.575588865477 not in filtered
    assert 459.9477191334383 not in filtered
    assert filtered == [
        245.76982283829486,
        242.3361936072318,
        268.76836797640857,
        260.0914330146905,
        265.3097740920848,
    ]
