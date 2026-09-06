"""
Unit tests for data loading, feature engineering, prediction output, and error handling.
"""

import os
import tempfile
import pytest
import pandas as pd
import numpy as np

from src.data import clean_data, detect_columns, COLUMN_MAPPINGS
from src.features import FeaturePipeline
from src.baseline import RouteHistoricalBaseline
from src.train import train_xgboost_model, compute_metrics
from src.predict import predict_travel_time, load_prediction_artifacts
import joblib


def test_data_cleaning_and_column_detection():
    """Test standard column detection, handling missing values, and invalid record removal."""
    raw_data = {
        'sourceid': [1, 1, 2, 3, np.nan, 4],
        'dstid': [10, 20, 20, 30, 40, 50],
        'hod': [8, 17, 25, 12, 14, -1],  # 25 and -1 are invalid hours
        'mean_travel_time': [1200.5, 1800.0, 900.0, -100.0, 1500.0, 2000.0]  # -100 is invalid
    }
    df_raw = pd.DataFrame(raw_data)
    
    col_map = detect_columns(df_raw)
    assert col_map['source_id'] == 'sourceid'
    assert col_map['destination_id'] == 'dstid'
    assert col_map['hour'] == 'hod'
    assert col_map['mean_travel_time'] == 'mean_travel_time'

    df_clean, stats = clean_data(df_raw)
    
    # Valid rows should only be row 0 (1, 10, 8, 1200.5) and row 1 (1, 20, 17, 1800.0)
    assert len(df_clean) == 2
    assert list(df_clean.columns) == ['source_id', 'destination_id', 'hour', 'mean_travel_time']
    assert (df_clean['hour'] >= 0).all() and (df_clean['hour'] <= 23).all()
    assert (df_clean['mean_travel_time'] > 0).all()


def test_missing_required_columns():
    """Test that missing required core columns raises ValueError."""
    df_invalid = pd.DataFrame({'sourceid': [1, 2], 'random_col': [10, 20]})
    with pytest.raises(ValueError, match="missing required conceptual columns"):
        clean_data(df_invalid)


def test_feature_transformation_and_leakage_prevention():
    """Test feature pipeline cyclic encoding and route historical statistics calculation."""
    df_train = pd.DataFrame({
        'source_id': [1, 1, 2],
        'destination_id': [10, 10, 20],
        'hour': [8, 9, 17],
        'mean_travel_time': [1000.0, 1200.0, 800.0]
    })
    
    pipeline = FeaturePipeline()
    X_train, y_train = pipeline.fit_transform(df_train)
    
    assert 'sin_hour' in X_train.columns
    assert 'cos_hour' in X_train.columns
    assert 'route_hist_mean' in X_train.columns
    
    # Route (1, 10) mean should be (1000 + 1200)/2 = 1100.0
    assert pipeline.route_stats[(1, 10)] == 1100.0
    
    # Test transform on unseen route (3, 30) -> should fallback to global mean (1000.0)
    df_unseen = pd.DataFrame({
        'source_id': [3],
        'destination_id': [30],
        'hour': [12],
        'mean_travel_time': [1500.0]
    })
    X_unseen = pipeline.transform(df_unseen)
    assert X_unseen['route_hist_mean'].iloc[0] == pipeline.global_mean_travel_time


def test_model_training_and_prediction_flow():
    """Test end-to-end training and prediction execution on sample data."""
    df_sample = pd.DataFrame({
        'source_id': [1, 1, 2, 2, 3, 3, 1, 2] * 5,
        'destination_id': [10, 20, 10, 20, 10, 20, 10, 20] * 5,
        'hour': [8, 9, 10, 17, 18, 19, 8, 17] * 5,
        'mean_travel_time': [1200, 1400, 800, 1600, 1100, 1300, 1250, 1550] * 5
    })

    with tempfile.TemporaryDirectory() as tmp_dir:
        # Fit baseline and feature pipeline
        baseline = RouteHistoricalBaseline()
        baseline.fit(df_sample)
        
        pipeline = FeaturePipeline()
        X, y = pipeline.fit_transform(df_sample)
        
        model = train_xgboost_model(X, y)
        
        # Save artifacts to temp models_dir
        models_dir = os.path.join(tmp_dir, "models")
        os.makedirs(models_dir, exist_ok=True)
        
        joblib.dump(model, os.path.join(models_dir, "xgboost_commute_model.joblib"))
        joblib.dump(baseline, os.path.join(models_dir, "baseline_model.joblib"))
        joblib.dump(pipeline, os.path.join(models_dir, "feature_pipeline.joblib"))
        
        # Run prediction
        res = predict_travel_time(
            origin_zone=1,
            destination_zone=10,
            hour=8,
            models_dir=models_dir
        )
        
        assert res["origin_zone"] == 1
        assert res["destination_zone"] == 10
        assert res["hour"] == 8
        assert res["predicted_travel_time_seconds"] > 0
        assert res["predicted_travel_time_minutes"] > 0
        assert res["baseline_travel_time_seconds"] is not None


def test_invalid_prediction_inputs():
    """Test error handling for invalid prediction input parameters."""
    with pytest.raises(ValueError, match="Invalid hour"):
        predict_travel_time(origin_zone=1, destination_zone=10, hour=25)

    with pytest.raises(ValueError, match="Zone IDs must be non-negative"):
        predict_travel_time(origin_zone=-1, destination_zone=10, hour=8)
