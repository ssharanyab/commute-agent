"""
Unit tests for historical mobility signal: reliability, deviation, coverage.
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import patch

import joblib
import pandas as pd
import pytest

from src.baseline import RouteHistoricalBaseline
from src.features import FeaturePipeline
from src.historical_signal import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_NONE,
    DEVIATION_ANOMALOUS,
    DEVIATION_ELEVATED,
    DEVIATION_HIGH,
    DEVIATION_NORMAL,
    DEVIATION_ELEVATED_MAX_PCT,
    DEVIATION_HIGH_MAX_PCT,
    DEVIATION_NORMAL_MAX_PCT,
    SIGNAL_SOURCE,
    classify_deviation,
    compute_deviation_percent,
    compute_historical_reliability,
    resolve_confidence,
)
from src.predict import get_historical_mobility_signal, predict_travel_time
from src.train import train_xgboost_model


def _sample_df_with_std() -> pd.DataFrame:
    """Synthetic OD data with mean + std (seconds)."""
    rows = []
    # OD (1, 10): stable ~1200s ± 60s
    for hour, mean, std in [
        (8, 1200.0, 60.0),
        (8, 1180.0, 55.0),
        (9, 1250.0, 70.0),
        (17, 1400.0, 200.0),
    ]:
        rows.append(
            {
                "source_id": 1,
                "destination_id": 10,
                "hour": hour,
                "mean_travel_time": mean,
                "std_travel_time": std,
            }
        )
    # OD (2, 20): more variable
    for hour, mean, std in [
        (8, 1800.0, 600.0),
        (9, 1900.0, 650.0),
    ]:
        rows.append(
            {
                "source_id": 2,
                "destination_id": 20,
                "hour": hour,
                "mean_travel_time": mean,
                "std_travel_time": std,
            }
        )
    # Duplicate rows to give XGBoost enough samples
    return pd.DataFrame(rows * 8)


def _write_artifacts(models_dir: str, df: pd.DataFrame) -> FeaturePipeline:
    baseline = RouteHistoricalBaseline()
    baseline.fit(df)
    pipeline = FeaturePipeline()
    X, y = pipeline.fit_transform(df)
    model = train_xgboost_model(X, y)
    os.makedirs(models_dir, exist_ok=True)
    joblib.dump(model, os.path.join(models_dir, "xgboost_commute_model.joblib"))
    joblib.dump(baseline, os.path.join(models_dir, "baseline_model.joblib"))
    joblib.dump(pipeline, os.path.join(models_dir, "feature_pipeline.joblib"))
    return pipeline


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_reliability_low_dispersion_vs_high():
    """35 min ± 3 min more reliable than 35 min ± 12 min."""
    mean = 35.0 * 60.0
    high = compute_historical_reliability(mean, 3.0 * 60.0)
    low = compute_historical_reliability(mean, 12.0 * 60.0)
    assert high is not None and low is not None
    assert 0.0 <= low < high <= 1.0
    # Explicit formula check: 1 / (1 + std/mean)
    assert high == round(1.0 / (1.0 + (180.0 / mean)), 4)


def test_reliability_invalid_inputs():
    assert compute_historical_reliability(None, 10.0) is None
    assert compute_historical_reliability(100.0, None) is None
    assert compute_historical_reliability(0.0, 10.0) is None
    assert compute_historical_reliability(-5.0, 10.0) is None
    assert compute_historical_reliability(100.0, -1.0) is None


def test_deviation_percent_and_thresholds():
    assert compute_deviation_percent(40.0, 40.0) == 0.0
    assert compute_deviation_percent(46.0, 40.0) == 15.0
    assert compute_deviation_percent(None, 40.0) is None
    assert compute_deviation_percent(40.0, 0.0) is None
    assert compute_deviation_percent(40.0, None) is None
    assert compute_deviation_percent(-1.0, 40.0) is None

    assert classify_deviation(DEVIATION_NORMAL_MAX_PCT) == DEVIATION_NORMAL
    assert classify_deviation(DEVIATION_NORMAL_MAX_PCT + 0.01) == DEVIATION_ELEVATED
    assert classify_deviation(DEVIATION_ELEVATED_MAX_PCT) == DEVIATION_ELEVATED
    assert classify_deviation(DEVIATION_ELEVATED_MAX_PCT + 0.01) == DEVIATION_HIGH
    assert classify_deviation(DEVIATION_HIGH_MAX_PCT) == DEVIATION_HIGH
    assert classify_deviation(DEVIATION_HIGH_MAX_PCT + 0.01) == DEVIATION_ANOMALOUS
    assert classify_deviation(None) is None


def test_resolve_confidence_levels():
    assert resolve_confidence(has_historical_coverage=False, std_seconds=None) == CONFIDENCE_NONE
    assert resolve_confidence(has_historical_coverage=True, std_seconds=None) == CONFIDENCE_LOW
    assert resolve_confidence(has_historical_coverage=True, std_seconds=60.0) == CONFIDENCE_HIGH


# ---------------------------------------------------------------------------
# Feature pipeline std aggregates
# ---------------------------------------------------------------------------


def test_feature_pipeline_stores_std_aggregates():
    df = _sample_df_with_std()
    pipeline = FeaturePipeline()
    pipeline.fit(df)
    assert (1, 10) in pipeline.route_std_stats
    assert (1, 10, 8) in pipeline.route_hour_std_stats
    std_h = pipeline.lookup_route_std(1, 10, 8)
    assert std_h is not None and std_h > 0
    assert pipeline.lookup_route_std(99, 99, 8) is None


# ---------------------------------------------------------------------------
# End-to-end signal via temp artifacts
# ---------------------------------------------------------------------------


def test_valid_historical_coverage_exposes_signal_fields():
    df = _sample_df_with_std()
    with tempfile.TemporaryDirectory() as tmp:
        models_dir = os.path.join(tmp, "models")
        _write_artifacts(models_dir, df)

        signal = get_historical_mobility_signal(
            origin_zone=1,
            destination_zone=10,
            hour=8,
            models_dir=models_dir,
        )

        assert signal["has_historical_coverage"] is True
        assert signal["historical_coverage"] is True
        assert signal["signal_source"] == SIGNAL_SOURCE
        assert signal["historical_expected_travel_time_minutes"] > 0
        assert signal["historical_typical_travel_time_minutes"] > 0
        assert signal["historical_std_travel_time_seconds"] is not None
        assert signal["historical_std_travel_time_minutes"] is not None
        assert signal["historical_std_travel_time_seconds"] > 0
        assert 0.0 <= signal["historical_reliability_score"] <= 1.0
        assert signal["confidence_level"] == CONFIDENCE_HIGH
        assert signal["deviation_percent"] is None
        assert signal["deviation_state"] is None


def test_missing_historical_coverage():
    df = _sample_df_with_std()
    with tempfile.TemporaryDirectory() as tmp:
        models_dir = os.path.join(tmp, "models")
        _write_artifacts(models_dir, df)

        signal = get_historical_mobility_signal(
            origin_zone=99,
            destination_zone=88,
            hour=8,
            models_dir=models_dir,
            current_minutes=40.0,
        )

        assert signal["has_historical_coverage"] is False
        assert signal["historical_coverage"] is False
        assert signal["confidence_level"] == CONFIDENCE_NONE
        assert signal["historical_std_travel_time_seconds"] is None
        assert signal["historical_std_travel_time_minutes"] is None
        assert signal["historical_reliability_score"] is None
        assert signal["deviation_percent"] is None
        assert signal["deviation_state"] is None
        assert signal["signal_source"] == SIGNAL_SOURCE


def test_current_vs_historical_deviation_states():
    df = _sample_df_with_std()
    with tempfile.TemporaryDirectory() as tmp:
        models_dir = os.path.join(tmp, "models")
        _write_artifacts(models_dir, df)

        base = get_historical_mobility_signal(
            origin_zone=1,
            destination_zone=10,
            hour=8,
            models_dir=models_dir,
        )
        hist = base["historical_expected_travel_time_minutes"]
        assert hist > 0

        # NORMAL: at historical
        normal = get_historical_mobility_signal(
            origin_zone=1,
            destination_zone=10,
            hour=8,
            models_dir=models_dir,
            current_minutes=hist,
        )
        assert normal["deviation_percent"] == 0.0
        assert normal["deviation_state"] == DEVIATION_NORMAL

        # ELEVATED: just above NORMAL max
        elevated_minutes = hist * (1.0 + (DEVIATION_NORMAL_MAX_PCT + 5.0) / 100.0)
        elevated = get_historical_mobility_signal(
            origin_zone=1,
            destination_zone=10,
            hour=8,
            models_dir=models_dir,
            current_minutes=elevated_minutes,
        )
        assert elevated["deviation_state"] == DEVIATION_ELEVATED

        # HIGH
        high_minutes = hist * (1.0 + (DEVIATION_ELEVATED_MAX_PCT + 5.0) / 100.0)
        high = get_historical_mobility_signal(
            origin_zone=1,
            destination_zone=10,
            hour=8,
            models_dir=models_dir,
            current_minutes=high_minutes,
        )
        assert high["deviation_state"] == DEVIATION_HIGH

        # ANOMALOUS
        anomalous_minutes = hist * (1.0 + (DEVIATION_HIGH_MAX_PCT + 10.0) / 100.0)
        anomalous = get_historical_mobility_signal(
            origin_zone=1,
            destination_zone=10,
            hour=8,
            models_dir=models_dir,
            current_minutes=anomalous_minutes,
        )
        assert anomalous["deviation_state"] == DEVIATION_ANOMALOUS
        assert anomalous["deviation_percent"] == compute_deviation_percent(
            anomalous_minutes, hist
        )


def test_invalid_zero_historical_time_skips_deviation():
    """Zero/invalid historical expected minutes → no deviation fabrication."""
    assert compute_deviation_percent(30.0, 0.0) is None
    assert compute_deviation_percent(30.0, -5.0) is None
    assert classify_deviation(compute_deviation_percent(30.0, 0.0)) is None

    with patch("src.predict.load_prediction_artifacts") as load:
        # Minimal stub pipeline/model so predict path can run
        class _Pipe:
            route_stats = {(1, 10): 0.0}
            global_mean_travel_time = 0.0
            route_std_stats = {}
            route_hour_std_stats = {}

            def transform(self, df):
                return df.assign(
                    sin_hour=0.0,
                    cos_hour=0.0,
                    route_hist_mean=0.0,
                    source_hist_mean=0.0,
                    dst_hist_mean=0.0,
                )

            def lookup_route_std(self, *args, **kwargs):
                return 10.0

        class _Model:
            def predict(self, X):
                return [0.0]

        load.return_value = (_Model(), None, _Pipe())
        signal = get_historical_mobility_signal(
            origin_zone=1,
            destination_zone=10,
            hour=8,
            models_dir="unused",
            current_minutes=40.0,
        )
        assert signal["historical_expected_travel_time_minutes"] == 0.0
        assert signal["deviation_percent"] is None
        assert signal["deviation_state"] is None
        # Reliability also None when mean <= 0
        assert signal["historical_reliability_score"] is None


def test_backward_compatible_predict_travel_time_keys():
    df = _sample_df_with_std()
    with tempfile.TemporaryDirectory() as tmp:
        models_dir = os.path.join(tmp, "models")
        _write_artifacts(models_dir, df)

        res = predict_travel_time(
            origin_zone=1,
            destination_zone=10,
            hour=8,
            models_dir=models_dir,
        )
        # Legacy keys
        assert res["predicted_travel_time_seconds"] > 0
        assert res["predicted_travel_time_minutes"] > 0
        assert res["baseline_travel_time_minutes"] is not None
        assert res["has_historical_coverage"] is True
        assert "historical_congestion_factor" in res
        # New optional param default does not break callers
        assert "current_minutes" not in res or res.get("current_minutes") is None


def test_optional_current_minutes_backward_compatible_signature():
    """Existing 3-arg call path remains valid."""
    df = _sample_df_with_std()
    with tempfile.TemporaryDirectory() as tmp:
        models_dir = os.path.join(tmp, "models")
        _write_artifacts(models_dir, df)
        signal = get_historical_mobility_signal(1, 10, 8, models_dir=models_dir)
        assert signal["has_historical_coverage"] is True
        assert signal["current_minutes"] is None
