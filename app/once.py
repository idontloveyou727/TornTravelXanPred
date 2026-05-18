from __future__ import annotations

import logging
from datetime import timezone

from app.config import Config
from app.db import Database, encode_dt, utc_now
from app.detector import EVENT_RESTOCK, detect_stock_event
from app.discord_webhook import format_airstrip_reminder, format_business_reminder, format_restock_detected, send_webhook
from app.json_state import (
    JsonStateStore,
    add_pending_notification_once,
    add_recent_restock_time,
    mark_notification_sent,
    prediction_from_json,
    previous_observation_from_state,
    recent_restock_datetimes,
    update_last_observation,
)
from app.main import run_sqlite_cycle
from app.parser import StockParseError, extract_stock_observation
from app.predictor import predict_next_restock
from app.scheduler import AIRSTRIP_DEPARTURE_REMINDER, BUSINESS_DEPARTURE_REMINDER
from app.yata_client import YataClient, YataClientError

LOGGER = logging.getLogger(__name__)


def run_once_command(config: Config) -> int:
    client = YataClient(config.yata_url)
    try:
        if config.state_backend == "json":
            run_json_once(config, client)
        elif config.state_backend == "sqlite":
            run_sqlite_once(config, client)
        else:
            LOGGER.error("Unsupported STATE_BACKEND=%s", config.state_backend)
            return 2
    except (YataClientError, StockParseError):
        LOGGER.exception("Recoverable monitor check failed")
        return 0
    except Exception:
        LOGGER.exception("Unrecoverable one-shot monitor failure")
        return 1
    return 0


def run_sqlite_once(config: Config, client: YataClient) -> None:
    db = Database(config.database_path)
    db.init_schema()
    try:
        run_sqlite_cycle(config, db, client)
    finally:
        db.close()


def run_json_once(config: Config, client: YataClient) -> None:
    store = JsonStateStore(config.state_path)
    state = store.load()
    now = utc_now()

    try:
        payload = client.fetch_json()
        observed_at = utc_now().astimezone(timezone.utc)
        previous = previous_observation_from_state(state, item_id=config.item_id, country=config.country)
        observation = extract_stock_observation(
            payload,
            item_id=config.item_id,
            country=config.country,
            country_aliases=config.country_aliases,
            observed_at=observed_at,
        )
        event = detect_stock_event(previous, observation)

        LOGGER.info(
            "JSON state check item_id=%s country=%s previous_quantity=%s current_quantity=%s",
            observation.item_id,
            observation.country,
            previous.quantity if previous else None,
            observation.quantity,
        )

        if event and event.event_type == EVENT_RESTOCK and event.normalized_at is not None:
            _handle_json_restock(config, state, event)
        elif event:
            LOGGER.info("Detected stock event type=%s", event.event_type)
        else:
            LOGGER.info("No stock event detected; quantity unchanged at %s", observation.quantity)

        update_last_observation(state, observation)
    finally:
        try:
            process_json_due_notifications(config, state, now=utc_now())
        except Exception:
            LOGGER.exception("Failed to process JSON due notifications")
        store.save(state)


def _handle_json_restock(config: Config, state: dict, event) -> None:
    normalized = event.normalized_at
    normalized_key = encode_dt(normalized)
    add_recent_restock_time(state, normalized, max_items=config.prediction_history_window + 1)

    prediction = predict_next_restock(
        current_restock_event_id=0,
        current_normalized_restock_at=normalized,
        historical_restock_times=recent_restock_datetimes(state),
        history_window=config.prediction_history_window,
    )

    if state.get("last_notified_restock_normalized_at") != normalized_key:
        content = format_restock_detected(event, prediction, prediction_id=0)
        ok, error = send_webhook(config.discord_webhook_url, content)
        if ok:
            state["last_notified_restock_normalized_at"] = normalized_key
            LOGGER.info("Sent JSON restock notification normalized_at=%s", normalized_key)
        else:
            LOGGER.error("Failed JSON restock notification normalized_at=%s error=%s", normalized_key, error)
    else:
        LOGGER.info("Skipped duplicate JSON restock notification normalized_at=%s", normalized_key)

    _schedule_json_departure_reminders(config, state, prediction, restock_key=normalized_key, now=utc_now())


def _schedule_json_departure_reminders(config: Config, state: dict, prediction, *, restock_key: str, now) -> None:
    reminders = [
        (AIRSTRIP_DEPARTURE_REMINDER, prediction.airstrip_ping_at),
        (BUSINESS_DEPARTURE_REMINDER, prediction.business_ping_at),
    ]
    for notification_type, target_time in reminders:
        key = f"{notification_type}:{restock_key}:{encode_dt(target_time)}"
        if target_time <= now:
            LOGGER.info("Skipping missed JSON reminder type=%s target_time=%s", notification_type, target_time.isoformat())
            mark_notification_sent(state, key)
            continue
        if add_pending_notification_once(
            state,
            key=key,
            notification_type=notification_type,
            target_time=target_time,
            prediction=prediction,
        ):
            LOGGER.info("Scheduled JSON reminder type=%s target_time=%s", notification_type, target_time.isoformat())


def process_json_due_notifications(config: Config, state: dict, *, now) -> None:
    pending = state.get("pending_notifications", [])
    for notification in pending:
        if notification.get("status") != "PENDING":
            continue
        try:
            target_time = str(notification["target_time"])
            if target_time > encode_dt(now):
                continue
            prediction = prediction_from_json(notification["prediction"])
            notification_type = str(notification["notification_type"])
            if notification_type == AIRSTRIP_DEPARTURE_REMINDER:
                content = format_airstrip_reminder(prediction)
            elif notification_type == BUSINESS_DEPARTURE_REMINDER:
                content = format_business_reminder(prediction)
            else:
                notification["status"] = "FAILED"
                notification["error_message"] = f"Unknown notification type: {notification_type}"
                continue

            ok, error = send_webhook(config.discord_webhook_url, content)
            notification["status"] = "SENT" if ok else "FAILED"
            notification["sent_at"] = encode_dt(now) if ok else None
            notification["error_message"] = error
            if ok:
                mark_notification_sent(state, str(notification["key"]))
        except Exception as exc:
            LOGGER.exception("Failed to process JSON notification key=%s", notification.get("key"))
            notification["status"] = "FAILED"
            notification["error_message"] = str(exc)
