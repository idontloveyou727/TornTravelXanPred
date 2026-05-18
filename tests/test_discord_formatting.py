from datetime import datetime, timezone

from app.discord_webhook import discord_ts


def test_discord_timestamp_formatting() -> None:
    value = datetime(2026, 5, 18, 0, 0, tzinfo=timezone.utc)
    unix = int(value.timestamp())

    assert discord_ts(value, "F") == f"<t:{unix}:F>"
    assert discord_ts(value, "R") == f"<t:{unix}:R>"

