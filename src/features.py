"""
Feature Engineering Module for Travel-Time Prediction.

Computes spatial, temporal, and historical route/zone statistics
strictly without data leakage.
"""

from typing import Tuple, Optional, Dict
import pandas as pd
import numpy as np


class FeaturePipeline:
    """Feature engineering pipeline for Uber Movement aggregate commute data.

    Model feature matrix excludes concurrent std/geom columns (unavailable as
    live inputs at inference). Optional OD / OD+hour std aggregates are still
    stored for the historical mobility *signal* layer when training data has them.
    """

    def __init__(self):
        self.global_mean_travel_time: float = 0.0
        self.route_stats: Dict[Tuple[int, int], float] = {}
        self.source_stats: Dict[int, float] = {}
        self.dst_stats: Dict[int, float] = {}
        # Historical variability lookups (empty on older serialized pipelines)
        self.route_std_stats: Dict[Tuple[int, int], float] = {}
        self.route_hour_mean_stats: Dict[Tuple[int, int, int], float] = {}
        self.route_hour_std_stats: Dict[Tuple[int, int, int], float] = {}
        self.is_fitted: bool = False

    def fit(self, df_train: pd.DataFrame) -> "FeaturePipeline":
        """Compute target statistics strictly on the training set to prevent data leakage.

        Args:
            df_train (pd.DataFrame): Training set containing source_id, destination_id,
                                     and mean_travel_time.

        Returns:
            FeaturePipeline: Fitted feature pipeline instance.
        """
        self.global_mean_travel_time = float(df_train['mean_travel_time'].mean())

        # Route-level historical mean travel time
        route_grouped = df_train.groupby(['source_id', 'destination_id'])['mean_travel_time'].mean()
        self.route_stats = route_grouped.to_dict()

        # Zone-level historical mean travel time (Origin & Destination)
        self.source_stats = df_train.groupby('source_id')['mean_travel_time'].mean().to_dict()
        self.dst_stats = df_train.groupby('destination_id')['mean_travel_time'].mean().to_dict()

        # OD+hour mean for historical signal context
        hour_mean = df_train.groupby(
            ['source_id', 'destination_id', 'hour']
        )['mean_travel_time'].mean()
        self.route_hour_mean_stats = hour_mean.to_dict()

        # Optional std aggregates from Uber Movement variability columns
        self.route_std_stats = {}
        self.route_hour_std_stats = {}
        if 'std_travel_time' in df_train.columns:
            std_numeric = pd.to_numeric(df_train['std_travel_time'], errors='coerce')
            with_std = df_train.loc[std_numeric.notna()].copy()
            with_std['_std'] = std_numeric.loc[std_numeric.notna()].astype(float)
            with_std = with_std[with_std['_std'] >= 0.0]
            if not with_std.empty:
                self.route_std_stats = (
                    with_std.groupby(['source_id', 'destination_id'])['_std'].mean().to_dict()
                )
                self.route_hour_std_stats = (
                    with_std.groupby(['source_id', 'destination_id', 'hour'])['_std']
                    .mean()
                    .to_dict()
                )

        self.is_fitted = True
        return self

    def lookup_route_std(
        self,
        origin_zone: int,
        destination_zone: int,
        hour: Optional[int] = None,
    ) -> Optional[float]:
        """Historical travel-time std (seconds) for OD, preferring OD+hour when available."""
        route_hour_std = getattr(self, "route_hour_std_stats", None) or {}
        route_std = getattr(self, "route_std_stats", None) or {}
        if hour is not None:
            key_h = (int(origin_zone), int(destination_zone), int(hour))
            if key_h in route_hour_std:
                return float(route_hour_std[key_h])
        key = (int(origin_zone), int(destination_zone))
        if key in route_std:
            return float(route_std[key])
        return None

    def lookup_route_hour_mean(
        self,
        origin_zone: int,
        destination_zone: int,
        hour: int,
    ) -> Optional[float]:
        """Historical mean travel time (seconds) for OD+hour when stored."""
        stats = getattr(self, "route_hour_mean_stats", None) or {}
        key = (int(origin_zone), int(destination_zone), int(hour))
        if key in stats:
            return float(stats[key])
        return None

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract and engineer features for training or inference.

        Args:
            df (pd.DataFrame): Dataframe containing input features.

        Returns:
            pd.DataFrame: Engineered feature matrix X.
        """
        X = pd.DataFrame(index=df.index)

        # Core Spatial Features
        X['source_id'] = df['source_id'].astype(int)
        X['destination_id'] = df['destination_id'].astype(int)

        # Core Temporal Features
        X['hour'] = df['hour'].astype(int)
        X['sin_hour'] = np.sin(2 * np.pi * X['hour'] / 24.0)
        X['cos_hour'] = np.cos(2 * np.pi * X['hour'] / 24.0)

        # Historical target statistics (Fallback hierarchy to prevent NaN for unseen routes/zones)
        if self.is_fitted:
            route_pairs = list(zip(X['source_id'], X['destination_id']))
            X['route_hist_mean'] = [
                self.route_stats.get(pair, self.source_stats.get(src, self.global_mean_travel_time))
                for pair, src in zip(route_pairs, X['source_id'])
            ]
            X['source_hist_mean'] = [
                self.source_stats.get(src, self.global_mean_travel_time)
                for src in X['source_id']
            ]
            X['dst_hist_mean'] = [
                self.dst_stats.get(dst, self.global_mean_travel_time)
                for dst in X['destination_id']
            ]
        else:
            X['route_hist_mean'] = 0.0
            X['source_hist_mean'] = 0.0
            X['dst_hist_mean'] = 0.0

        return X

    def fit_transform(self, df_train: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series]:
        """Fit on training data and return (X_features, y_target).

        Args:
            df_train (pd.DataFrame): Cleaned training dataframe.

        Returns:
            Tuple[pd.DataFrame, pd.Series]: Feature matrix X and target y.
        """
        self.fit(df_train)
        X = self.transform(df_train)
        y = df_train['mean_travel_time'].astype(float)
        return X, y


def prepare_features_and_target(
    df: pd.DataFrame,
    pipeline: Optional[FeaturePipeline] = None,
    is_train: bool = True
) -> Tuple[pd.DataFrame, Optional[pd.Series], FeaturePipeline]:
    """Helper function to execute feature pipeline on dataset split.

    Args:
        df (pd.DataFrame): Input dataset.
        pipeline (Optional[FeaturePipeline]): Pre-fitted feature pipeline or None.
        is_train (bool): Whether input is training data.

    Returns:
        Tuple[pd.DataFrame, Optional[pd.Series], FeaturePipeline]: (X, y, pipeline)
    """
    if pipeline is None:
        pipeline = FeaturePipeline()

    if is_train:
        X, y = pipeline.fit_transform(df)
        return X, y, pipeline
    else:
        X = pipeline.transform(df)
        y = df['mean_travel_time'].astype(float) if 'mean_travel_time' in df.columns else None
        return X, y, pipeline
