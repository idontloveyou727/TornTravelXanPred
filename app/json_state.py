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
    "recent_restock_times": [],
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


def add_recent_restock_time(state: dict[str, Any], normalized_at: datetime, *, max_items: int) -> None:
    normalized = encode_dt(normalized_at)
    values = [str(value) for value in state.get("recent_restock_times", [])]
    if not values or values[-1] != normalized:
        values.append(normalized)
    state["recent_restock_times"] = values[-max_items:]
    state["last_restock_normalized_at"] = normalized


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
        "airstrip_ping_at": encode_dt(prediction.airstrip_ping_at),
        "business_ping_at": encode_dt(prediction.business_ping_at),
    }


def prediction_from_json(data: dict[str, Any]) -> Prediction:
    return Prediction(
        based_on_restock_event_id=int(data["based_on_restock_event_id"]),
        predicted_restock_at=decode_dt(str(data["predicted_restock_at"])),
        predicted_interval_ticks=int(data["predicted_interval_ticks"]),
        prediction_method=str(data["prediction_method"]),
        airstrip_departure_at=decode_dt(str(data["airstrip_departure_at"])),
        business_departure_at=decode_dt(str(data["business_departure_at"])),
        airstrip_ping_at=decode_dt(str(data["airstrip_ping_at"])),
        business_ping_at=decode_dt(str(data["business_ping_at"])),
    )


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
