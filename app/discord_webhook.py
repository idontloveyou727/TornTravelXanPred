from __future__ import annotations

import logging
import time
from datetime import datetime

import requests

from app.models import Prediction, StockEvent

LOGGER = logging.getLogger(__name__)


class DiscordWebhookError(RuntimeError):
    pass


def discord_ts(dt: datetime, style: str = "F") -> str:
    unix = int(dt.timestamp())
    return f"<t:{unix}:{style}>"


def send_webhook(url: str | None, content: str, *, max_attempts: int = 3) -> tuple[bool, str | None]:
    if not url:
        LOGGER.info("Discord webhook disabled; dry-run message content=%s", content)
        return True, None

    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(url, json={"content": content}, timeout=15)
        except requests.RequestException as exc:
            LOGGER.warning("Discord webhook request failed attempt=%s/%s error=%s", attempt, max_attempts, exc)
            if attempt < max_attempts:
                time.sleep(min(30.0, 2.0 ** (attempt - 1)))
                continue
            return False, str(exc)

        if response.status_code in {200, 204}:
            LOGGER.info("Discord webhook sent status=%s", response.status_code)
            return True, None

        if response.status_code == 429:
            retry_after = _discord_retry_after(response)
            LOGGER.warning("Discord webhook rate limited retry_after=%s body=%s", retry_after, response.text[:500])
            time.sleep(retry_after)
            continue

        error = f"Discord HTTP {response.status_code}: {response.text[:500]}"
        LOGGER.error(error)
        if response.status_code in {400, 401, 404}:
            return False, error
        if attempt < max_attempts:
            time.sleep(min(30.0, 2.0 ** (attempt - 1)))
            continue
        return False, error

    return False, "Discord webhook send exhausted retries"


def format_restock_detected(event: StockEvent, prediction: Prediction, prediction_id: int) -> str:
    return "\n".join(
        [
            "🇬🇧 UK Item 206 Restock Detected",
            "",
            f"Observed at: {discord_ts(event.observed_at, 'F')} ({discord_ts(event.observed_at, 'R')})",
            f"Normalized restock tick: {discord_ts(event.normalized_at, 'F') if event.normalized_at else 'unknown'}",
            f"Quantity: {event.current_quantity}",
            "",
            f"Next predicted restock: {discord_ts(prediction.predicted_restock_at, 'F')} ({discord_ts(prediction.predicted_restock_at, 'R')})",
            f"Prediction interval: {prediction.predicted_interval_ticks} ticks",
            f"Prediction ID: {prediction_id}",
            "",
            "Recommended departures:",
            f"Airstrip: {discord_ts(prediction.airstrip_departure_at, 'F')} ({discord_ts(prediction.airstrip_departure_at, 'R')})",
            f"Business: {discord_ts(prediction.business_departure_at, 'F')} ({discord_ts(prediction.business_departure_at, 'R')})",
        ]
    )


def format_airstrip_reminder(prediction: Prediction) -> str:
    return "\n".join(
        [
            "🛫 Airstrip Departure Reminder",
            "",
            "Predicted UK item 206 restock:",
            f"{discord_ts(prediction.predicted_restock_at, 'F')} ({discord_ts(prediction.predicted_restock_at, 'R')})",
            "",
            "Recommended Airstrip departure:",
            f"{discord_ts(prediction.airstrip_departure_at, 'F')} ({discord_ts(prediction.airstrip_departure_at, 'R')})",
            "",
            "This ping is sent 1 minute before recommended departure.",
        ]
    )


def format_business_reminder(prediction: Prediction) -> str:
    return "\n".join(
        [
            "💼 Business Class Departure Reminder",
            "",
            "Predicted UK item 206 restock:",
            f"{discord_ts(prediction.predicted_restock_at, 'F')} ({discord_ts(prediction.predicted_restock_at, 'R')})",
            "",
            "Recommended Business Class departure:",
            f"{discord_ts(prediction.business_departure_at, 'F')} ({discord_ts(prediction.business_departure_at, 'R')})",
            "",
            "This ping is sent 1 minute before recommended departure.",
        ]
    )


def _discord_retry_after(response: requests.Response) -> float:
    header = response.headers.get("Retry-After") or response.headers.get("X-RateLimit-Reset-After")
    if header:
        try:
            return max(0.0, float(header))
        except ValueError:
            pass
    try:
        body = response.json()
    except ValueError:
        return 5.0
    try:
        return max(0.0, float(body.get("retry_after", 5.0)))
    except (TypeError, ValueError, AttributeError):
        return 5.0
