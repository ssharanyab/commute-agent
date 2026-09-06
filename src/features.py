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
    
    Excludes target-concurrent statistics (such as geometric_mean_travel_time 
    or standard_deviation_travel_time) because they are unavailable at inference time.
    """
    
    def __init__(self):
        self.global_mean_travel_time: float = 0.0
        self.route_stats: Dict[Tuple[int, int], float] = {}
        self.source_stats: Dict[int, float] = {}
        self.dst_stats: Dict[int, float] = {}
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
        
        self.is_fitted = True
        return self

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
