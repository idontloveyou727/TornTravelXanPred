from app.config import load_config


def test_prediction_config_defaults(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    for name in [
        "PREDICTION_INTERVAL_MIN_TICKS",
        "PREDICTION_INTERVAL_MAX_TICKS",
        "PREDICTION_INTERVAL_MAD_THRESHOLD",
        "PREDICTION_ACCURACY_TOLERANCE_TICKS",
    ]:
        monkeypatch.delenv(name, raising=False)

    config = load_config()

    assert config.prediction_interval_min_ticks == 80
    assert config.prediction_interval_max_ticks == 180
    assert config.prediction_interval_mad_threshold == 3.5
    assert config.prediction_accuracy_tolerance_ticks == 10


def test_prediction_interval_max_must_be_greater_than_min(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PREDICTION_INTERVAL_MIN_TICKS", "180")
    monkeypatch.setenv("PREDICTION_INTERVAL_MAX_TICKS", "80")

    try:
        load_config()
    except ValueError as exc:
        assert "PREDICTION_INTERVAL_MAX_TICKS must be >= PREDICTION_INTERVAL_MIN_TICKS" in str(exc)
    else:
        raise AssertionError("Expected invalid prediction interval bounds to fail")
