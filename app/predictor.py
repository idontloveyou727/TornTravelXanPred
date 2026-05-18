from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median

from app.models import Prediction
from app.tick import add_ticks, diff_in_ticks, floor_to_5_minute_tick, is_aligned_to_5_minute_tick

DEFAULT_PREDICTION_TICKS = 25
AIRSTRIP_DURATION = timedelta(hours=1, minutes=51)
BUSINESS_DURATION = timedelta(minutes=48)
METHOD_DEFAULT = "DEFAULT_25_TICKS"
METHOD_MEDIAN = "MEDIAN_HISTORY"


def predict_next_restock(
    *,
    current_restock_event_id: int,
    current_normalized_restock_at: datetime,
    historical_restock_times: list[datetime],
    history_window: int,
    departure_buffer_minutes: int = 0,
    ping_lead_minutes: int = 0,
) -> Prediction:
    normalized_current = floor_to_5_minute_tick(current_normalized_restock_at)
    intervals = _recent_intervals(historical_restock_times, history_window)
    if len(intervals) < 3:
        interval_ticks = DEFAULT_PREDICTION_TICKS
        method = METHOD_DEFAULT
    else:
        interval_ticks = int(median(intervals))
        method = METHOD_MEDIAN

    predicted_restock_at = add_ticks(normalized_current, interval_ticks)
    return build_prediction(
        event_id=current_restock_event_id,
        predicted_restock_at=predicted_restock_at,
        interval_ticks=interval_ticks,
        method=method,
        departure_buffer_minutes=departure_buffer_minutes,
        ping_lead_minutes=ping_lead_minutes,
    )


def build_prediction(
    *,
    event_id: int,
    predicted_restock_at: datetime,
    interval_ticks: int,
    method: str,
    departure_buffer_minutes: int = 0,
    ping_lead_minutes: int = 0,
) -> Prediction:
    if departure_buffer_minutes < 0:
        raise ValueError("departure_buffer_minutes must be >= 0")
    if ping_lead_minutes < 0:
        raise ValueError("ping_lead_minutes must be >= 0")

    predicted = floor_to_5_minute_tick(predicted_restock_at)
    if not is_aligned_to_5_minute_tick(predicted):
        raise ValueError("Predicted restock time must be aligned to a 5-minute tick")

    departure_buffer = timedelta(minutes=departure_buffer_minutes)
    ping_lead = timedelta(minutes=ping_lead_minutes)
    airstrip_latest_departure_at = predicted - AIRSTRIP_DURATION
    business_latest_departure_at = predicted - BUSINESS_DURATION
    airstrip_departure_at = airstrip_latest_departure_at - departure_buffer
    business_departure_at = business_latest_departure_at - departure_buffer
    return Prediction(
        based_on_restock_event_id=event_id,
        predicted_restock_at=predicted,
        predicted_interval_ticks=interval_ticks,
        prediction_method=method,
        airstrip_departure_at=airstrip_departure_at,
        business_departure_at=business_departure_at,
        airstrip_latest_departure_at=airstrip_latest_departure_at,
        business_latest_departure_at=business_latest_departure_at,
        airstrip_ping_at=airstrip_departure_at - ping_lead,
        business_ping_at=business_departure_at - ping_lead,
    )


def _recent_intervals(restock_times: list[datetime], history_window: int) -> list[int]:
    ordered = sorted(floor_to_5_minute_tick(value) for value in restock_times)
    if len(ordered) < 2:
        return []
    intervals = [diff_in_ticks(start, end) for start, end in zip(ordered, ordered[1:])]
    return intervals[-history_window:]
