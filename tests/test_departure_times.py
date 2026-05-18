from datetime import datetime, timezone

from app.predictor import METHOD_DEFAULT, build_prediction


def test_departure_and_ping_times() -> None:
    prediction = build_prediction(
        event_id=1,
        predicted_restock_at=datetime(2026, 5, 18, 2, 0, tzinfo=timezone.utc),
        interval_ticks=25,
        method=METHOD_DEFAULT,
    )

    assert prediction.airstrip_departure_at == datetime(2026, 5, 18, 0, 9, tzinfo=timezone.utc)
    assert prediction.airstrip_ping_at == datetime(2026, 5, 18, 0, 8, tzinfo=timezone.utc)
    assert prediction.business_departure_at == datetime(2026, 5, 18, 1, 12, tzinfo=timezone.utc)
    assert prediction.business_ping_at == datetime(2026, 5, 18, 1, 11, tzinfo=timezone.utc)

