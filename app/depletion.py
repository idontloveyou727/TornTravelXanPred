from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

from app.models import StockObservation
from app.tick import ceil_to_minute_tick, floor_to_minute_tick

RESTOCK_QUANTITY = 2500
DEFAULT_DEPLETION_MINUTES = 8
DEFAULT_DEPLETION_RATE_PER_MINUTE = RESTOCK_QUANTITY / DEFAULT_DEPLETION_MINUTES


@dataclass(frozen=True)
class DepletionEstimate:
    estimated_at: datetime
    rate_per_minute: float
    source_quantity: int
    source_observed_at: datetime


def calculate_depletion_rate_per_minute(previous: StockObservation, current: StockObservation) -> float | None:
    if previous.quantity <= 0 or current.quantity <= 0:
        return None
    if current.quantity >= previous.quantity:
        return None

    elapsed_minutes = (current.observed_at - previous.observed_at).total_seconds() / 60
    if elapsed_minutes <= 0:
        return None

    return (previous.quantity - current.quantity) / elapsed_minutes


def stable_depletion_rate(history: list[float], default_rate: float = DEFAULT_DEPLETION_RATE_PER_MINUTE) -> float:
    positive = [value for value in history if value > 0]
    if not positive:
        return default_rate
    return float(median(positive))


def estimate_restock_time_from_observation(
    observation: StockObservation,
    rate_per_minute: float,
    restock_quantity: int = RESTOCK_QUANTITY,
) -> datetime:
    if rate_per_minute <= 0:
        rate_per_minute = DEFAULT_DEPLETION_RATE_PER_MINUTE
    consumed_units = max(0, restock_quantity - observation.quantity)
    elapsed_minutes = consumed_units / rate_per_minute
    return floor_to_minute_tick(observation.observed_at - timedelta(minutes=elapsed_minutes))


def estimate_depleted_time_from_last_positive(
    observation: StockObservation,
    rate_per_minute: float,
) -> DepletionEstimate:
    if rate_per_minute <= 0:
        rate_per_minute = DEFAULT_DEPLETION_RATE_PER_MINUTE
    minutes_until_empty = max(0, observation.quantity) / rate_per_minute
    estimated_at = ceil_to_minute_tick(observation.observed_at + timedelta(minutes=minutes_until_empty))
    return DepletionEstimate(
        estimated_at=estimated_at,
        rate_per_minute=rate_per_minute,
        source_quantity=observation.quantity,
        source_observed_at=observation.observed_at,
    )
