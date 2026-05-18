from datetime import datetime, timezone

from app.json_state import JsonStateStore, prediction_from_json, prediction_to_json
from app.models import Prediction


def test_json_state_load_save(tmp_path) -> None:
    path = tmp_path / "state.json"
    store = JsonStateStore(path)

    state = store.load()
    assert state["last_quantity"] is None
    assert state["recent_restock_times"] == []

    state["last_quantity"] = 5
    state["last_observed_at"] = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc).isoformat()
    store.save(state)

    loaded = JsonStateStore(path).load()
    assert loaded["last_quantity"] == 5
    assert loaded["last_observed_at"] == "2026-05-18T12:00:00+00:00"
    assert loaded["pending_notifications"] == []


def test_prediction_json_preserves_latest_departure_fields() -> None:
    prediction = Prediction(
        based_on_restock_event_id=1,
        predicted_restock_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        predicted_interval_ticks=25,
        prediction_method="DEFAULT_25_TICKS",
        airstrip_departure_at=datetime(2026, 1, 1, 10, 4, tzinfo=timezone.utc),
        business_departure_at=datetime(2026, 1, 1, 11, 7, tzinfo=timezone.utc),
        airstrip_latest_departure_at=datetime(2026, 1, 1, 10, 9, tzinfo=timezone.utc),
        business_latest_departure_at=datetime(2026, 1, 1, 11, 12, tzinfo=timezone.utc),
        airstrip_ping_at=datetime(2026, 1, 1, 10, 4, tzinfo=timezone.utc),
        business_ping_at=datetime(2026, 1, 1, 11, 7, tzinfo=timezone.utc),
    )

    decoded = prediction_from_json(prediction_to_json(prediction))

    assert decoded.airstrip_latest_departure_at == prediction.airstrip_latest_departure_at
    assert decoded.business_latest_departure_at == prediction.business_latest_departure_at
    assert decoded.airstrip_recommended_departure_at == prediction.airstrip_recommended_departure_at


def test_prediction_json_old_state_falls_back_to_recommended_as_latest() -> None:
    decoded = prediction_from_json(
        {
            "based_on_restock_event_id": 1,
            "predicted_restock_at": "2026-01-01T12:00:00+00:00",
            "predicted_interval_ticks": 25,
            "prediction_method": "DEFAULT_25_TICKS",
            "airstrip_departure_at": "2026-01-01T10:04:00+00:00",
            "business_departure_at": "2026-01-01T11:07:00+00:00",
            "airstrip_ping_at": "2026-01-01T10:04:00+00:00",
            "business_ping_at": "2026-01-01T11:07:00+00:00",
        }
    )

    assert decoded.airstrip_latest_departure_at == decoded.airstrip_departure_at
    assert decoded.business_latest_departure_at == decoded.business_departure_at
