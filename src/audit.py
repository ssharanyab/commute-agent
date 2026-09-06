"""
Generalization Audit Module for Bangalore Uber Movement Model.

Executes rigorous evaluation across three holdout strategies:
1. Random Row Holdout (Baseline row split)
2. Unseen-Route Holdout (OD pair split)
3. Unseen-Zone Holdout (Destination zone split)

Extracts feature importances and exports generalization metrics.
"""

import os
import json
from typing import Dict, Any, Tuple
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.model_selection import train_test_split

from src.data import load_and_clean_data
from src.features import FeaturePipeline
from src.baseline import RouteHistoricalBaseline
from src.train import train_xgboost_model, compute_metrics


def run_random_row_audit(df: pd.DataFrame) -> Tuple[Dict[str, float], Dict[str, float], Any, FeaturePipeline]:
    """Test 1: Random Row Holdout Split (70/15/15)."""
    df_train_val, df_test = train_test_split(df, test_size=0.15, random_state=42)
    df_train, df_val = train_test_split(df_train_val, test_size=0.17647, random_state=42)

    # Baseline
    baseline = RouteHistoricalBaseline().fit(df_train)
    b_test_preds = baseline.predict(df_test)
    b_metrics = compute_metrics(df_test['mean_travel_time'].values, b_test_preds)

    # XGBoost
    pipeline = FeaturePipeline()
    X_train, y_train = pipeline.fit_transform(df_train)
    X_test = pipeline.transform(df_test)
    y_test = df_test['mean_travel_time'].values

    model = train_xgboost_model(X_train, y_train)
    m_test_preds = model.predict(X_test)
    m_metrics = compute_metrics(y_test, m_test_preds)

    return b_metrics, m_metrics, model, pipeline


def run_unseen_route_audit(df: pd.DataFrame) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Test 2: Unseen Route Holdout Split (OD Pair Split: 70/15/15)."""
    # Create unique OD route identifiers
    df_routes = df[['source_id', 'destination_id']].drop_duplicates()
    
    routes_train_val, routes_test = train_test_split(df_routes, test_size=0.15, random_state=42)
    routes_train, routes_val = train_test_split(routes_train_val, test_size=0.17647, random_state=42)

    # Convert to set of (source_id, destination_id) tuples for fast lookup
    train_set = set(zip(routes_train['source_id'], routes_train['destination_id']))
    val_set = set(zip(routes_val['source_id'], routes_val['destination_id']))
    test_set = set(zip(routes_test['source_id'], routes_test['destination_id']))

    # Filter dataframe by route sets
    od_pairs = list(zip(df['source_id'], df['destination_id']))
    df_train = df[[pair in train_set for pair in od_pairs]].copy()
    df_val = df[[pair in val_set for pair in od_pairs]].copy()
    df_test = df[[pair in test_set for pair in od_pairs]].copy()

    # Baseline
    baseline = RouteHistoricalBaseline().fit(df_train)
    b_test_preds = baseline.predict(df_test)
    b_metrics = compute_metrics(df_test['mean_travel_time'].values, b_test_preds)

    # XGBoost
    pipeline = FeaturePipeline()
    X_train, y_train = pipeline.fit_transform(df_train)
    X_test = pipeline.transform(df_test)
    y_test = df_test['mean_travel_time'].values

    model = train_xgboost_model(X_train, y_train)
    m_test_preds = model.predict(X_test)
    m_metrics = compute_metrics(y_test, m_test_preds)

    return b_metrics, m_metrics


def run_unseen_zone_audit(df: pd.DataFrame) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Test 3: Unseen Destination Zone Holdout (15% held-out destination zones)."""
    unique_dsts = df['destination_id'].unique()
    train_dsts, test_dsts = train_test_split(unique_dsts, test_size=0.15, random_state=42)
    train_dsts, val_dsts = train_test_split(train_dsts, test_size=0.17647, random_state=42)

    train_set = set(train_dsts)
    val_set = set(val_dsts)
    test_set = set(test_dsts)

    df_train = df[df['destination_id'].isin(train_set)].copy()
    df_val = df[df['destination_id'].isin(val_set)].copy()
    df_test = df[df['destination_id'].isin(test_set)].copy()

    # Baseline
    baseline = RouteHistoricalBaseline().fit(df_train)
    b_test_preds = baseline.predict(df_test)
    b_metrics = compute_metrics(df_test['mean_travel_time'].values, b_test_preds)

    # XGBoost
    pipeline = FeaturePipeline()
    X_train, y_train = pipeline.fit_transform(df_train)
    X_test = pipeline.transform(df_test)
    y_test = df_test['mean_travel_time'].values

    model = train_xgboost_model(X_train, y_train)
    m_test_preds = model.predict(X_test)
    m_metrics = compute_metrics(y_test, m_test_preds)

    return b_metrics, m_metrics


def extract_and_plot_feature_importance(model, feature_names: list, output_fig_path: str, output_json_path: str) -> Dict[str, float]:
    """Extract feature importances from XGBoost, plot figure, and export JSON."""
    if hasattr(model, "feature_importances_"):
        importances = model.feature_importances_
    else:
        importances = np.zeros(len(feature_names))

    fi_series = pd.Series(importances, index=feature_names).sort_values(ascending=False)
    fi_dict = {feat: float(val) for feat, val in fi_series.items()}

    # Save JSON
    os.makedirs(os.path.dirname(output_json_path), exist_ok=True)
    with open(output_json_path, "w") as f:
        json.dump(fi_dict, f, indent=2)

    # Plot Figure
    os.makedirs(os.path.dirname(output_fig_path), exist_ok=True)
    plt.figure(figsize=(10, 5))
    sns.barplot(x=fi_series.values, y=fi_series.index, palette="Blues_r")
    plt.title("XGBoost Feature Importance (Gain / Normalized Weight)", fontsize=13, fontweight="bold")
    plt.xlabel("Relative Importance Score", fontsize=11)
    plt.ylabel("Engineered Feature", fontsize=11)
    plt.tight_layout()
    plt.savefig(output_fig_path, dpi=150)
    plt.close()

    return fi_dict


def run_full_generalization_audit(data_path: str = "data/raw/bangalore-wards-2019-3-OnlyWeekdays-HourlyAggregate.csv", models_dir: str = "models", fig_dir: str = "docs/figures"):
    print("================================================================================")
    print("      GENERALIZATION AUDIT FOR BANGALORE UBER MOVEMENT ML MODEL")
    print("================================================================================")

    df_clean, inspection = load_and_clean_data(data_path)
    print(f"Loaded dataset: {len(df_clean):,} cleaned aggregated rows across {df_clean['source_id'].nunique()} zones.")

    print("\n--- TEST 1: Random Row Holdout Audit ---")
    b_test1, m_test1, model_test1, pipeline_test1 = run_random_row_audit(df_clean)
    print(f"Test 1 (Random Row Split)  -> Baseline MAE: {b_test1['MAE_minutes']:.2f} min | XGBoost MAE: {m_test1['MAE_minutes']:.2f} min | R2: {m_test1['R2']:.4f}")

    print("\n--- TEST 2: Unseen-Route (OD Pair) Holdout Audit ---")
    b_test2, m_test2 = run_unseen_route_audit(df_clean)
    print(f"Test 2 (Unseen OD Routes)  -> Baseline MAE: {b_test2['MAE_minutes']:.2f} min | XGBoost MAE: {m_test2['MAE_minutes']:.2f} min | R2: {m_test2['R2']:.4f}")

    print("\n--- TEST 3: Unseen Destination Zone Holdout Audit ---")
    b_test3, m_test3 = run_unseen_zone_audit(df_clean)
    print(f"Test 3 (Unseen Dest Zones) -> Baseline MAE: {b_test3['MAE_minutes']:.2f} min | XGBoost MAE: {m_test3['MAE_minutes']:.2f} min | R2: {m_test3['R2']:.4f}")

    # Extract Feature Importance from Random Row Model
    X_sample = pipeline_test1.transform(df_clean.head(10))
    feature_names = list(X_sample.columns)
    
    fig_path = os.path.join(fig_dir, "feature_importance.png")
    json_fi_path = os.path.join(models_dir, "feature_importance.json")
    fi_dict = extract_and_plot_feature_importance(model_test1, feature_names, fig_path, json_fi_path)

    print("\n--- Feature Importance Breakdown ---")
    for feat, imp in fi_dict.items():
        print(f"  {feat:<20}: {imp * 100:.2f}%")

    generalization_summary = {
        "test_1_random_row_holdout": {
            "description": "Random 70/15/15 row split across (sourceid, dstid, hod) tuples.",
            "baseline": b_test1,
            "xgboost": m_test1
        },
        "test_2_unseen_route_holdout": {
            "description": "OD-level 70/15/15 route split where test OD pairs are completely unseen in training.",
            "baseline": b_test2,
            "xgboost": m_test2
        },
        "test_3_unseen_zone_holdout": {
            "description": "Zone-level 70/15/15 split holding out 15% of destination zones completely from training.",
            "baseline": b_test3,
            "xgboost": m_test3
        },
        "feature_importance": fi_dict
    }

    json_gen_path = os.path.join(models_dir, "generalization_metrics.json")
    with open(json_gen_path, "w") as f:
        json.dump(generalization_summary, f, indent=2)

    print(f"\nGeneralization audit complete. Saved metrics to {json_gen_path} and plot to {fig_path}.")
    return generalization_summary


if __name__ == "__main__":
    run_full_generalization_audit()
