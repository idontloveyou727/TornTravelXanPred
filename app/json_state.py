from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.db import decode_dt, encode_dt
from app.models import Prediction, StockObservation

DEFAULT_STATE: dict[str, Any] = {
    "last_quantity": None,
    "last_observed_at": None,
    "last_restock_normalized_at": None,
    "last_notified_restock_normalized_at": None,
    "last_estimated_depleted_at": None,
    "last_estimated_restock_at": None,
    "last_predicted_restock_at": None,
    "recent_restock_times": [],
    "recent_depleted_times": [],
    "depletion_rate_per_minute": None,
    "depletion_rate_history": [],
    "depletion_to_restock_interval_ticks": [],
    "last_positive_observation": None,
    "pending_notifications": [],
    "sent_notification_keys": [],
}


class JsonStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return deepcopy(DEFAULT_STATE)
        with self.path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        state = deepcopy(DEFAULT_STATE)
        if isinstance(loaded, dict):
            state.update(loaded)
        return state

    def save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write("\n")
        tmp_path.replace(self.path)


def previous_observation_from_state(state: dict[str, Any], *, item_id: int, country: str) -> StockObservation | None:
    quantity = state.get("last_quantity")
    observed_at = state.get("last_observed_at")
    if quantity is None or observed_at is None:
        return None
    return StockObservation(
        observed_at=decode_dt(str(observed_at)),
        item_id=item_id,
        country=country,
        quantity=int(quantity),
    )


def update_last_observation(state: dict[str, Any], observation: StockObservation) -> None:
    state["last_quantity"] = observation.quantity
    state["last_observed_at"] = encode_dt(observation.observed_at)
    if observation.quantity > 0:
        state["last_positive_observation"] = observation_to_json(observation)


def observation_to_json(observation: StockObservation) -> dict[str, Any]:
    return {
        "observed_at": encode_dt(observation.observed_at),
        "item_id": observation.item_id,
        "country": observation.country,
        "quantity": observation.quantity,
    }


def observation_from_json(data: dict[str, Any] | None) -> StockObservation | None:
    if not data:
        return None
    return StockObservation(
        observed_at=decode_dt(str(data["observed_at"])),
        item_id=int(data["item_id"]),
        country=str(data["country"]),
        quantity=int(data["quantity"]),
    )


def add_recent_restock_time(state: dict[str, Any], normalized_at: datetime, *, max_items: int) -> None:
    normalized = encode_dt(normalized_at)
    values = [str(value) for value in state.get("recent_restock_times", [])]
    if not values or values[-1] != normalized:
        values.append(normalized)
    state["recent_restock_times"] = values[-max_items:]
    state["last_restock_normalized_at"] = normalized


def add_recent_depleted_time(state: dict[str, Any], depleted_at: datetime, *, max_items: int) -> None:
    encoded = encode_dt(depleted_at)
    values = [str(value) for value in state.get("recent_depleted_times", [])]
    if not values or values[-1] != encoded:
        values.append(encoded)
    state["recent_depleted_times"] = values[-max_items:]
    state["last_estimated_depleted_at"] = encoded


def add_depletion_rate(state: dict[str, Any], rate_per_minute: float, *, max_items: int) -> None:
    if rate_per_minute <= 0:
        return
    values = [float(value) for value in state.get("depletion_rate_history", []) if float(value) > 0]
    values.append(float(rate_per_minute))
    state["depletion_rate_history"] = values[-max_items:]
    state["depletion_rate_per_minute"] = float(rate_per_minute)


def add_depletion_to_restock_interval(state: dict[str, Any], ticks: int, *, max_items: int) -> None:
    if ticks <= 0:
        return
    values = [int(value) for value in state.get("depletion_to_restock_interval_ticks", []) if int(value) > 0]
    values.append(int(ticks))
    state["depletion_to_restock_interval_ticks"] = values[-max_items:]


def recent_restock_datetimes(state: dict[str, Any]) -> list[datetime]:
    values: list[datetime] = []
    for value in state.get("recent_restock_times", []):
        try:
            values.append(decode_dt(str(value)))
        except ValueError:
            continue
    return values


def add_pending_notification_once(
    state: dict[str, Any],
    *,
    key: str,
    notification_type: str,
    target_time: datetime,
    prediction: Prediction,
) -> bool:
    if key in state.get("sent_notification_keys", []):
        return False
    for notification in state.get("pending_notifications", []):
        if notification.get("key") == key:
            return False

    state.setdefault("pending_notifications", []).append(
        {
            "key": key,
            "notification_type": notification_type,
            "target_time": encode_dt(target_time),
            "status": "PENDING",
            "prediction": prediction_to_json(prediction),
        }
    )
    return True


def mark_notification_sent(state: dict[str, Any], key: str) -> None:
    sent = state.setdefault("sent_notification_keys", [])
    if key not in sent:
        sent.append(key)


def prediction_to_json(prediction: Prediction) -> dict[str, Any]:
    return {
        "based_on_restock_event_id": prediction.based_on_restock_event_id,
        "predicted_restock_at": encode_dt(prediction.predicted_restock_at),
        "predicted_interval_ticks": prediction.predicted_interval_ticks,
        "prediction_method": prediction.prediction_method,
        "airstrip_departure_at": encode_dt(prediction.airstrip_departure_at),
        "business_departure_at": encode_dt(prediction.business_departure_at),
        "airstrip_recommended_departure_at": encode_dt(prediction.airstrip_recommended_departure_at),
        "business_recommended_departure_at": encode_dt(prediction.business_recommended_departure_at),
        "airstrip_latest_departure_at": encode_dt(prediction.airstrip_latest_departure_at),
        "business_latest_departure_at": encode_dt(prediction.business_latest_departure_at),
        "airstrip_ping_at": encode_dt(prediction.airstrip_ping_at),
        "business_ping_at": encode_dt(prediction.business_ping_at),
    }


def prediction_from_json(data: dict[str, Any]) -> Prediction:
    return Prediction(
        based_on_restock_event_id=int(data["based_on_restock_event_id"]),
        predicted_restock_at=decode_dt(str(data["predicted_restock_at"])),
        predicted_interval_ticks=int(data["predicted_interval_ticks"]),
        prediction_method=str(data["prediction_method"]),
        airstrip_departure_at=decode_dt(str(data.get("airstrip_recommended_departure_at", data["airstrip_departure_at"]))),
        business_departure_at=decode_dt(str(data.get("business_recommended_departure_at", data["business_departure_at"]))),
        airstrip_latest_departure_at=decode_dt(
            str(data.get("airstrip_latest_departure_at", data["airstrip_departure_at"]))
        ),
        business_latest_departure_at=decode_dt(
            str(data.get("business_latest_departure_at", data["business_departure_at"]))
        ),
        airstrip_ping_at=decode_dt(str(data["airstrip_ping_at"])),
        business_ping_at=decode_dt(str(data["business_ping_at"])),
    )


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
