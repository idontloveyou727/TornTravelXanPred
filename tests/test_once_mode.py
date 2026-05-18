from datetime import datetime, timezone
from pathlib import Path

import monitor
from app.config import Config
from app.json_state import JsonStateStore
from app.once import run_json_once


class FakeClient:
    def __init__(self, quantity: int) -> None:
        self.quantity = quantity

    def fetch_json(self):
        return {
            "stocks": {
                "uni": {
                    "stocks": [
                        {"id": 206, "name": "Xanax", "quantity": self.quantity, "cost": 1},
                    ]
                }
            }
        }


def make_config(tmp_path: Path) -> Config:
    return Config(
        yata_url="https://yata.yt/api/v1/travel/export/",
        item_id=206,
        country="UK",
        country_aliases=("UK", "United Kingdom", "uni"),
        poll_seconds=60,
        discord_webhook_url=None,
        database_path=tmp_path / "local.sqlite3",
        state_backend="json",
        state_path=tmp_path / "state.json",
        github_actions_delay_buffer_minutes=5,
        ping_lead_minutes=0,
        prediction_history_window=10,
        log_level="INFO",
    )


def test_monitor_once_cli_exits_after_one_cycle(monkeypatch, tmp_path) -> None:
    config = make_config(tmp_path)
    calls = []

    monkeypatch.setattr(monitor, "load_config", lambda: config)
    monkeypatch.setattr(monitor, "configure_logging", lambda _level: None)
    monkeypatch.setattr(monitor, "run_once_command", lambda _config: calls.append(_config) or 0)

    assert monitor.main(["--once"]) == 0
    assert calls == [config]


def test_json_once_prevents_duplicate_restock_notifications(monkeypatch, tmp_path) -> None:
    config = make_config(tmp_path)
    store = JsonStateStore(config.state_path)
    state = store.load()
    state["last_quantity"] = 0
    state["last_observed_at"] = "2026-05-18T12:00:00+00:00"
    store.save(state)

    fixed_now = datetime(2026, 5, 18, 12, 7, 12, tzinfo=timezone.utc)
    sent_messages = []
    monkeypatch.setattr("app.once.utc_now", lambda: fixed_now)
    monkeypatch.setattr("app.once.send_webhook", lambda _url, content: sent_messages.append(content) or (True, None))

    run_json_once(config, FakeClient(quantity=10))
    run_json_once(config, FakeClient(quantity=10))

    final_state = store.load()
    assert len(sent_messages) == 1
    assert final_state["last_quantity"] == 10
    assert final_state["last_restock_normalized_at"] == "2026-05-18T12:05:00+00:00"
    assert final_state["last_notified_restock_normalized_at"] == "2026-05-18T12:05:00+00:00"
