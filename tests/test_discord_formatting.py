from datetime import datetime, timezone

from app.discord_webhook import discord_ts, format_restock_detected
from app.models import Prediction, StockEvent


def test_discord_timestamp_formatting() -> None:
    value = datetime(2026, 5, 18, 0, 0, tzinfo=timezone.utc)
    unix = int(value.timestamp())

    assert discord_ts(value, "F") == f"<t:{unix}:F>"
    assert discord_ts(value, "R") == f"<t:{unix}:R>"


def test_restock_message_includes_departure_breakdown() -> None:
    event = StockEvent(
        event_type="RESTOCK",
        item_id=206,
        country="UK",
        observed_at=datetime(2026, 1, 1, 12, 7, 12, tzinfo=timezone.utc),
        normalized_at=datetime(2026, 1, 1, 12, 5, tzinfo=timezone.utc),
        previous_quantity=0,
        current_quantity=10,
        source_delay_seconds=132,
    )
    prediction = Prediction(
        based_on_restock_event_id=1,
        predicted_restock_at=datetime(2026, 1, 1, 14, 10, tzinfo=timezone.utc),
        predicted_interval_ticks=25,
        prediction_method="DEFAULT_125_TICKS",
        airstrip_departure_at=datetime(2026, 1, 1, 12, 14, tzinfo=timezone.utc),
        business_departure_at=datetime(2026, 1, 1, 13, 17, tzinfo=timezone.utc),
        airstrip_latest_departure_at=datetime(2026, 1, 1, 12, 19, tzinfo=timezone.utc),
        business_latest_departure_at=datetime(2026, 1, 1, 13, 22, tzinfo=timezone.utc),
        airstrip_ping_at=datetime(2026, 1, 1, 12, 14, tzinfo=timezone.utc),
        business_ping_at=datetime(2026, 1, 1, 13, 17, tzinfo=timezone.utc),
    )

    message = format_restock_detected(event, prediction, prediction_id=1)

    assert "Latest safe flight" in message
    assert "Recommended departure" in message
    assert "Projected ping time" in message
    assert "<t:" in message
    assert ":F>" in message
    assert ":R>" in message
