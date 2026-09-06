"""
Historical Mobility Intelligence Prediction Module.

Exposes user-facing prediction interfaces for origin zone, destination zone,
and temporal parameters using serialized XGBoost model artifacts.

Note:
This module acts as the HISTORICAL MOBILITY INTELLIGENCE signal provider.
It does NOT replace real-time routing engines (e.g. Google Maps API).
For routes with historical coverage, it returns typical historical travel durations
and congestion context. For unrepresented routes, it signals missing coverage
so the decision layer can gracefully fall back to Maps API routing data.
"""

import os
from typing import Dict, Any, Optional
import pandas as pd
import numpy as np
import joblib
from src.features import FeaturePipeline
from src.baseline import RouteHistoricalBaseline


def load_prediction_artifacts(models_dir: str = "models"):
    """Load serialized model and feature pipeline artifacts.
    
    Args:
        models_dir (str): Directory where model files are saved.
        
    Returns:
        Tuple[ml_model, baseline_model, feature_pipeline]
    """
    ml_path = os.path.join(models_dir, "xgboost_commute_model.joblib")
    baseline_path = os.path.join(models_dir, "baseline_model.joblib")
    pipeline_path = os.path.join(models_dir, "feature_pipeline.joblib")

    if not os.path.exists(ml_path) or not os.path.exists(pipeline_path):
        raise FileNotFoundError(
            f"Trained model artifacts not found in '{models_dir}'. "
            "Please ensure raw dataset is placed in data/raw/ and run 'python -m src.train' first."
        )

    ml_model = joblib.load(ml_path)
    baseline_model = joblib.load(baseline_path) if os.path.exists(baseline_path) else None
    pipeline = joblib.load(pipeline_path)

    return ml_model, baseline_model, pipeline


def get_historical_mobility_signal(
    origin_zone: int,
    destination_zone: int,
    hour: int,
    day_of_week: Optional[int] = None,
    models_dir: str = "models"
) -> Dict[str, Any]:
    """Retrieve historical mobility intelligence signal for given origin, destination, and hour context.
    
    Args:
        origin_zone (int): Origin zone ID (sourceid).
        destination_zone (int): Destination zone ID (dstid).
        hour (int): Hour of day (0-23).
        day_of_week (Optional[int]): Day of week context if available.
        models_dir (str): Location of model artifacts.
        
    Returns:
        Dict[str, Any]: Result dictionary containing historical mobility signals and coverage flags.
    """
    # Validate inputs
    if not (0 <= hour <= 23):
        raise ValueError(f"Invalid hour: {hour}. Hour must be between 0 and 23.")
    if origin_zone < 0 or destination_zone < 0:
        raise ValueError("Zone IDs must be non-negative integers.")
        
    ml_model, baseline_model, pipeline = load_prediction_artifacts(models_dir=models_dir)

    # Check historical coverage
    has_coverage = (int(origin_zone), int(destination_zone)) in pipeline.route_stats

    # Build input dataframe
    input_dict = {
        "source_id": [int(origin_zone)],
        "destination_id": [int(destination_zone)],
        "hour": [int(hour)]
    }
    if day_of_week is not None:
        input_dict["day_of_week"] = [int(day_of_week)]

    df_input = pd.DataFrame(input_dict)
    
    # Feature transformation
    X_input = pipeline.transform(df_input)
    
    # Model inference
    ml_pred = float(ml_model.predict(X_input)[0])
    ml_pred = max(0.0, ml_pred)

    baseline_pred = None
    if baseline_model is not None:
        baseline_pred = float(baseline_model.predict(df_input)[0])
        baseline_pred = max(0.0, baseline_pred)

    # Congestion factor relative to route average
    route_hist_avg = pipeline.route_stats.get((int(origin_zone), int(destination_zone)), pipeline.global_mean_travel_time)
    congestion_factor = round(ml_pred / max(1.0, route_hist_avg), 2)

    return {
        "signal_source": "historical_uber_movement_ml",
        "has_historical_coverage": has_coverage,
        "origin_zone": int(origin_zone),
        "destination_zone": int(destination_zone),
        "hour": int(hour),
        "day_of_week": day_of_week,
        "historical_typical_travel_time_seconds": round(ml_pred, 2),
        "historical_typical_travel_time_minutes": round(ml_pred / 60.0, 2),
        "historical_baseline_travel_time_minutes": round(baseline_pred / 60.0, 2) if baseline_pred is not None else None,
        "historical_congestion_factor": congestion_factor
    }


def predict_travel_time(
    origin_zone: int,
    destination_zone: int,
    hour: int,
    day_of_week: Optional[int] = None,
    models_dir: str = "models"
) -> Dict[str, Any]:
    """Legacy alias wrapper for get_historical_mobility_signal."""
    res = get_historical_mobility_signal(
        origin_zone=origin_zone,
        destination_zone=destination_zone,
        hour=hour,
        day_of_week=day_of_week,
        models_dir=models_dir
    )
    # Maintain backwards compatible keys
    res["predicted_travel_time_seconds"] = res["historical_typical_travel_time_seconds"]
    res["predicted_travel_time_minutes"] = res["historical_typical_travel_time_minutes"]
    res["baseline_travel_time_seconds"] = round(res["historical_baseline_travel_time_minutes"] * 60.0, 2) if res["historical_baseline_travel_time_minutes"] is not None else None
    res["baseline_travel_time_minutes"] = res["historical_baseline_travel_time_minutes"]
    return res
