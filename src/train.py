"""
Model Training and Evaluation Pipeline for Uber Movement Commute Agent.

Trains a route-context historical baseline model and an XGBoost regression model
on Bangalore aggregated weekday travel-time data, evaluates MAE, RMSE, and R2 without data leakage,
and serializes artifacts and evaluation metrics to models/.
"""

import os
import argparse
import sys
import json
from typing import Dict, Tuple, Any, Optional
import numpy as np
import pandas as pd
import joblib
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split

from src.data import find_raw_datasets, load_and_clean_data, save_processed_data
from src.features import FeaturePipeline
from src.baseline import RouteHistoricalBaseline


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    """Compute MAE, RMSE, and R2 regression metrics in seconds and minutes.
    
    Args:
        y_true (np.ndarray): True target values in seconds.
        y_pred (np.ndarray): Predicted values in seconds.
        
    Returns:
        Dict[str, float]: Metrics dictionary.
    """
    mae_sec = mean_absolute_error(y_true, y_pred)
    mse_sec = mean_squared_error(y_true, y_pred)
    rmse_sec = np.sqrt(mse_sec)
    r2 = r2_score(y_true, y_pred)
    
    return {
        "MAE_seconds": float(mae_sec),
        "MAE_minutes": float(mae_sec / 60.0),
        "RMSE_seconds": float(rmse_sec),
        "RMSE_minutes": float(rmse_sec / 60.0),
        "R2": float(r2)
    }


def train_xgboost_model(X_train: pd.DataFrame, y_train: pd.Series):
    """Train XGBoost regressor with tuned tree parameters."""
    try:
        import xgboost as xgb
        model = xgb.XGBRegressor(
            n_estimators=200,
            learning_rate=0.08,
            max_depth=7,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=-1
        )
    except ImportError:
        from sklearn.ensemble import HistGradientBoostingRegressor
        print("[WARNING] xgboost package not available. Falling back to HistGradientBoostingRegressor.")
        model = HistGradientBoostingRegressor(random_state=42)
        
    model.fit(X_train, y_train)
    return model


def run_training_pipeline(raw_data_path: str, models_dir: str = "models", processed_dir: str = "data/processed") -> Optional[Dict[str, Any]]:
    """Execute complete ingestion, feature engineering, baseline & ML training, and evaluation flow.
    
    Args:
        raw_data_path (str): Path to raw CSV file.
        models_dir (str): Path to save trained artifacts.
        processed_dir (str): Path to save processed CSV data.
        
    Returns:
        Optional[Dict[str, Any]]: Metrics summary dictionary.
    """
    if not os.path.exists(raw_data_path):
        print(f"[ERROR] Raw dataset file not found at: {raw_data_path}")
        return None

    print(f"\n--- 1. Loading and Cleaning Data from {raw_data_path} ---")
    df_clean, inspection = load_and_clean_data(raw_data_path)
    processed_path = os.path.join(processed_dir, "uber_movement_cleaned.csv")
    save_processed_data(df_clean, processed_path)
    print(f"Dataset successfully cleaned: {len(df_clean)} records saved to {processed_path}")

    print("\n--- 2. Holdout Partitioning Strategy (Train / Validation / Test) ---")
    # 70% Train, 15% Validation, 15% Test holdout split
    df_train_val, df_test = train_test_split(df_clean, test_size=0.15, random_state=42)
    df_train, df_val = train_test_split(df_train_val, test_size=0.17647, random_state=42) # ~70% train / 15% val / 15% test

    print(f"Training set:   {len(df_train):,} rows (70%)")
    print(f"Validation set: {len(df_val):,} rows (15%)")
    print(f"Test set:       {len(df_test):,} rows (15%)")

    print("\n--- 3. Fitting Route-Context Baseline Model ---")
    baseline = RouteHistoricalBaseline()
    baseline.fit(df_train)
    
    y_val_true = df_val['mean_travel_time'].values
    y_test_true = df_test['mean_travel_time'].values
    
    baseline_val_preds = baseline.predict(df_val)
    baseline_test_preds = baseline.predict(df_test)
    
    baseline_val_metrics = compute_metrics(y_val_true, baseline_val_preds)
    baseline_test_metrics = compute_metrics(y_test_true, baseline_test_preds)

    print("\n--- 4. Engineering Features & Training XGBoost Regressor ---")
    pipeline = FeaturePipeline()
    X_train, y_train = pipeline.fit_transform(df_train)
    X_val = pipeline.transform(df_val)
    X_test = pipeline.transform(df_test)

    ml_model = train_xgboost_model(X_train, y_train)

    ml_val_preds = ml_model.predict(X_val)
    ml_test_preds = ml_model.predict(X_test)
    
    ml_val_metrics = compute_metrics(y_val_true, ml_val_preds)
    ml_test_metrics = compute_metrics(y_test_true, ml_test_preds)

    print("\n" + "="*80)
    print("                      EVALUATION METRICS COMPARISON SUMMARY")
    print("="*80)
    print(f"{'Metric':<15} | {'Baseline (Val)':<16} | {'XGBoost (Val)':<16} | {'Baseline (Test)':<16} | {'XGBoost (Test)':<16}")
    print("-" * 85)
    print(f"{'MAE (minutes)':<15} | {baseline_val_metrics['MAE_minutes']:<16.2f} | {ml_val_metrics['MAE_minutes']:<16.2f} | {baseline_test_metrics['MAE_minutes']:<16.2f} | {ml_test_metrics['MAE_minutes']:<16.2f}")
    print(f"{'MAE (seconds)':<15} | {baseline_val_metrics['MAE_seconds']:<16.2f} | {ml_val_metrics['MAE_seconds']:<16.2f} | {baseline_test_metrics['MAE_seconds']:<16.2f} | {ml_test_metrics['MAE_seconds']:<16.2f}")
    print(f"{'RMSE (seconds)':<15} | {baseline_val_metrics['RMSE_seconds']:<16.2f} | {ml_val_metrics['RMSE_seconds']:<16.2f} | {baseline_test_metrics['RMSE_seconds']:<16.2f} | {ml_test_metrics['RMSE_seconds']:<16.2f}")
    print(f"{'R2 Score':<15} | {baseline_val_metrics['R2']:<16.4f} | {ml_val_metrics['R2']:<16.4f} | {baseline_test_metrics['R2']:<16.4f} | {ml_test_metrics['R2']:<16.4f}")
    print("="*80)
    
    beats_baseline = ml_test_metrics['MAE_seconds'] < baseline_test_metrics['MAE_seconds']
    mae_improvement_pct = ((baseline_test_metrics['MAE_seconds'] - ml_test_metrics['MAE_seconds']) / baseline_test_metrics['MAE_seconds']) * 100.0
    print(f"ML Model Beats Baseline: {'YES' if beats_baseline else 'NO'} ({mae_improvement_pct:.2f}% MAE improvement)\n")

    print(f"--- 5. Saving Trained Artifacts to {models_dir}/ ---")
    os.makedirs(models_dir, exist_ok=True)
    joblib.dump(ml_model, os.path.join(models_dir, "xgboost_commute_model.joblib"))
    joblib.dump(baseline, os.path.join(models_dir, "baseline_model.joblib"))
    joblib.dump(pipeline, os.path.join(models_dir, "feature_pipeline.joblib"))
    
    summary = {
        "inspection": inspection,
        "baseline_val": baseline_val_metrics,
        "baseline_test": baseline_test_metrics,
        "xgboost_val": ml_val_metrics,
        "xgboost_test": ml_test_metrics,
        "beats_baseline": beats_baseline,
        "mae_improvement_pct": mae_improvement_pct
    }
    
    with open(os.path.join(models_dir, "metrics_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    print(f"Successfully saved artifacts to {models_dir}/")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Train Commute Agent Travel-Time Prediction Model.")
    parser.add_argument("--input", type=str, default=None, help="Path to raw CSV dataset.")
    parser.add_argument("--models_dir", type=str, default="models", help="Directory to store model artifacts.")
    args = parser.parse_args()

    input_path = args.input
    if input_path is None:
        csv_files = find_raw_datasets("data/raw")
        if not csv_files:
            print("\n[STOP] data/raw/ contains no CSV dataset files.")
            sys.exit(0)
        input_path = csv_files[0]
        print(f"Auto-detected raw dataset file: {input_path}")

    run_training_pipeline(raw_data_path=input_path, models_dir=args.models_dir)


if __name__ == "__main__":
    main()
