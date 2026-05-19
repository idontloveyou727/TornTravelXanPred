from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

from app.models import StockObservation
from app.tick import ceil_to_minute_tick, floor_to_minute_tick

RESTOCK_QUANTITY = 2500
DEFAULT_DEPLETION_MINUTES = 8
DEFAULT_DEPLETION_RATE_PER_MINUTE = RESTOCK_QUANTITY / DEFAULT_DEPLETION_MINUTES
MIN_DEPLETION_RATE_SAMPLE_SECONDS = 90
DEPLETION_RATE_MIN_MULTIPLIER = 0.25
DEPLETION_RATE_MAX_MULTIPLIER = 1.75
MAD_OUTLIER_THRESHOLD = 3.5
MIN_MAD_HISTORY_ITEMS = 5


@dataclass(frozen=True)
class DepletionEstimate:
    estimated_at: datetime
    rate_per_minute: float
    source_quantity: int
    source_observed_at: datetime


def calculate_depletion_rate_per_minute(
    previous: StockObservation,
    current: StockObservation,
    *,
    min_elapsed_seconds: int = MIN_DEPLETION_RATE_SAMPLE_SECONDS,
) -> float | None:
    if previous.quantity <= 0 or current.quantity <= 0:
        return None
    if current.quantity >= previous.quantity:
        return None

    elapsed_seconds = (current.observed_at - previous.observed_at).total_seconds()
    if elapsed_seconds < min_elapsed_seconds:
        return None

    elapsed_minutes = elapsed_seconds / 60
    return (previous.quantity - current.quantity) / elapsed_minutes


def filter_depletion_rate_history(
    history: list[float],
    *,
    default_rate: float = DEFAULT_DEPLETION_RATE_PER_MINUTE,
    min_multiplier: float = DEPLETION_RATE_MIN_MULTIPLIER,
    max_multiplier: float = DEPLETION_RATE_MAX_MULTIPLIER,
    mad_threshold: float = MAD_OUTLIER_THRESHOLD,
    min_mad_items: int = MIN_MAD_HISTORY_ITEMS,
) -> list[float]:
    if default_rate <= 0:
        default_rate = DEFAULT_DEPLETION_RATE_PER_MINUTE

    min_rate = default_rate * min_multiplier
    max_rate = default_rate * max_multiplier
    bounded = [float(value) for value in history if min_rate <= float(value) <= max_rate]
    if len(bounded) < min_mad_items:
        return bounded

    center = float(median(bounded))
    deviations = [abs(value - center) for value in bounded]
    mad = float(median(deviations))
    if mad == 0:
        tolerance = default_rate * 0.05
        return [value for value in bounded if abs(value - center) <= tolerance]

    max_deviation = mad_threshold * 1.4826 * mad
    return [value for value in bounded if abs(value - center) <= max_deviation]


def stable_depletion_rate(
    history: list[float],
    default_rate: float = DEFAULT_DEPLETION_RATE_PER_MINUTE,
    *,
    min_multiplier: float = DEPLETION_RATE_MIN_MULTIPLIER,
    max_multiplier: float = DEPLETION_RATE_MAX_MULTIPLIER,
) -> float:
    filtered = filter_depletion_rate_history(
        history,
        default_rate=default_rate,
        min_multiplier=min_multiplier,
        max_multiplier=max_multiplier,
    )
    if not filtered:
        return default_rate
    return float(median(filtered))


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
