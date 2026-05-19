from __future__ import annotations

import logging
from datetime import timezone

from app.config import Config
from app.db import Database, decode_dt, encode_dt, utc_now
from app.depletion import (
    calculate_depletion_rate_per_minute,
    estimate_depleted_time_from_last_positive,
    estimate_restock_time_from_observation,
    filter_depletion_rate_history,
    stable_depletion_rate,
)
from app.detector import EVENT_OUT_OF_STOCK, EVENT_RESTOCK, detect_stock_event
from app.discord_webhook import format_airstrip_reminder, format_business_reminder, format_restock_detected, send_webhook
from app.json_state import (
    JsonStateStore,
    add_depletion_to_restock_interval,
    add_pending_notification_once,
    add_recent_depleted_time,
    add_recent_restock_time,
    mark_notification_sent,
    observation_from_json,
    prediction_from_json,
    previous_observation_from_state,
    recent_restock_datetimes,
    update_last_observation,
)
from app.main import run_sqlite_cycle
from app.parser import StockParseError, extract_stock_observation
from app.predictor import predict_next_restock
from app.scheduler import AIRSTRIP_DEPARTURE_REMINDER, BUSINESS_DEPARTURE_REMINDER
from app.tick import diff_in_ticks
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
    _sanitize_json_depletion_rates(config, state)
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
        _update_json_depletion_rate(config, state, previous, observation)

        LOGGER.info(
            "JSON state check item_id=%s country=%s previous_quantity=%s current_quantity=%s",
            observation.item_id,
            observation.country,
            previous.quantity if previous else None,
            observation.quantity,
        )

        if event and event.event_type == EVENT_RESTOCK and event.normalized_at is not None:
            _handle_json_restock(config, state, event, observation)
        elif event and event.event_type == EVENT_OUT_OF_STOCK:
            _handle_json_depletion(config, state, previous)
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


def _update_json_depletion_rate(config: Config, state: dict, previous, observation) -> None:
    if previous is None:
        return
    rate = calculate_depletion_rate_per_minute(
        previous,
        observation,
        min_elapsed_seconds=config.min_depletion_rate_sample_seconds,
    )
    if rate is None:
        return
    filtered = _filtered_depletion_history(config, [*_state_depletion_history(state), rate])
    state["depletion_rate_history"] = filtered[-config.depletion_rate_history_window :]
    state["depletion_rate_per_minute"] = _effective_depletion_rate(config, state)
    LOGGER.info(
        "Recorded filtered depletion_rate_per_minute=%s sample=%s",
        round(state["depletion_rate_per_minute"], 4),
        round(rate, 4),
    )


def _effective_depletion_rate(config: Config, state: dict) -> float:
    return stable_depletion_rate(
        _state_depletion_history(state),
        default_rate=config.default_depletion_rate_per_minute,
        min_multiplier=config.depletion_rate_min_multiplier,
        max_multiplier=config.depletion_rate_max_multiplier,
    )


def _state_depletion_history(state: dict) -> list[float]:
    values: list[float] = []
    for value in state.get("depletion_rate_history", []):
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            values.append(parsed)
    return values


def _filtered_depletion_history(config: Config, history: list[float]) -> list[float]:
    return filter_depletion_rate_history(
        history,
        default_rate=config.default_depletion_rate_per_minute,
        min_multiplier=config.depletion_rate_min_multiplier,
        max_multiplier=config.depletion_rate_max_multiplier,
    )


def _sanitize_json_depletion_rates(config: Config, state: dict) -> None:
    filtered = _filtered_depletion_history(config, _state_depletion_history(state))
    state["depletion_rate_history"] = filtered[-config.depletion_rate_history_window :]
    state["depletion_rate_per_minute"] = _effective_depletion_rate(config, state)


def _handle_json_restock(config: Config, state: dict, event, observation) -> None:
    rate = _effective_depletion_rate(config, state)
    normalized = estimate_restock_time_from_observation(observation, rate)
    normalized_key = encode_dt(normalized)
    state["last_estimated_restock_at"] = normalized_key
    add_recent_restock_time(state, normalized, max_items=config.prediction_history_window + 1)
    depleted_key = state.get("last_estimated_depleted_at")
    if depleted_key:
        interval_ticks = diff_in_ticks(decode_dt(depleted_key), normalized)
        add_depletion_to_restock_interval(state, interval_ticks, max_items=config.prediction_history_window)
        LOGGER.info("Recorded depletion_to_restock_interval_ticks=%s", interval_ticks)

    current_cycle_depletion = estimate_depleted_time_from_last_positive(observation, rate)
    prediction = predict_next_restock(
        current_restock_event_id=0,
        current_normalized_restock_at=current_cycle_depletion.estimated_at,
        historical_restock_times=recent_restock_datetimes(state),
        history_window=config.prediction_history_window,
        departure_buffer_minutes=config.github_actions_delay_buffer_minutes,
        ping_lead_minutes=config.ping_lead_minutes,
        historical_interval_ticks=[int(value) for value in state.get("depletion_to_restock_interval_ticks", [])],
    )
    state["last_predicted_restock_at"] = encode_dt(prediction.predicted_restock_at)

    if state.get("last_notified_restock_normalized_at") != normalized_key:
        content = format_restock_detected(
            event,
            prediction,
            prediction_id=0,
            include_airstrip=config.enable_airstrip_pings,
            include_business=config.enable_business_class_pings,
        )
        ok, error = send_webhook(config.discord_webhook_url, content)
        if ok:
            state["last_notified_restock_normalized_at"] = normalized_key
            LOGGER.info("Sent JSON restock notification normalized_at=%s", normalized_key)
        else:
            LOGGER.error("Failed JSON restock notification normalized_at=%s error=%s", normalized_key, error)
    else:
        LOGGER.info("Skipped duplicate JSON restock notification normalized_at=%s", normalized_key)


def _handle_json_depletion(config: Config, state: dict, previous) -> None:
    last_positive = observation_from_json(state.get("last_positive_observation"))
    if last_positive is None and previous is not None and previous.quantity > 0:
        last_positive = previous
    if last_positive is None:
        LOGGER.warning("Out-of-stock event has no last positive observation for depletion estimate")
        return

    rate = _effective_depletion_rate(config, state)
    estimate = estimate_depleted_time_from_last_positive(last_positive, rate)
    add_recent_depleted_time(state, estimate.estimated_at, max_items=config.prediction_history_window + 1)
    LOGGER.info(
        "Estimated depleted_at=%s source_quantity=%s drpm=%s",
        estimate.estimated_at.isoformat(),
        estimate.source_quantity,
        round(estimate.rate_per_minute, 4),
    )

    prediction = predict_next_restock(
        current_restock_event_id=0,
        current_normalized_restock_at=estimate.estimated_at,
        historical_restock_times=[],
        history_window=config.prediction_history_window,
        departure_buffer_minutes=config.github_actions_delay_buffer_minutes,
        ping_lead_minutes=config.ping_lead_minutes,
        historical_interval_ticks=[int(value) for value in state.get("depletion_to_restock_interval_ticks", [])],
    )
    state["last_predicted_restock_at"] = encode_dt(prediction.predicted_restock_at)
    _schedule_json_departure_reminders(
        config,
        state,
        prediction,
        restock_key=encode_dt(estimate.estimated_at),
        now=utc_now(),
    )


def _schedule_json_departure_reminders(config: Config, state: dict, prediction, *, restock_key: str, now) -> None:
    reminders = []
    if config.enable_airstrip_pings:
        reminders.append((AIRSTRIP_DEPARTURE_REMINDER, prediction.airstrip_ping_at))
    if config.enable_business_class_pings:
        reminders.append((BUSINESS_DEPARTURE_REMINDER, prediction.business_ping_at))
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
            if _json_notification_disabled(config, notification_type):
                notification["status"] = "SKIPPED"
                notification["sent_at"] = None
                notification["error_message"] = "Departure reminder type disabled by configuration"
                mark_notification_sent(state, str(notification["key"]))
                continue
            if notification_type == AIRSTRIP_DEPARTURE_REMINDER:
                content = format_airstrip_reminder(prediction, config.ping_lead_minutes)
            elif notification_type == BUSINESS_DEPARTURE_REMINDER:
                content = format_business_reminder(prediction, config.ping_lead_minutes)
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


def _json_notification_disabled(config: Config, notification_type: str) -> bool:
    if notification_type == AIRSTRIP_DEPARTURE_REMINDER:
        return not config.enable_airstrip_pings
    if notification_type == BUSINESS_DEPARTURE_REMINDER:
        return not config.enable_business_class_pings
    return False
