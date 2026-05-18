from datetime import datetime, timezone

from app.json_state import JsonStateStore


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
