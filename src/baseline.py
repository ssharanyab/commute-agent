"""
Historical Route-Context Baseline Model Module.
"""

from typing import Dict, Tuple
import numpy as np
import pandas as pd


class RouteHistoricalBaseline:
    """Historical average travel-time baseline model for aggregated zone-to-zone commute data.
    
    Predicts travel time based on:
    1. (source_id, destination_id, hour) mean travel time
    2. Fallback to (source_id, destination_id) mean travel time
    3. Fallback to source_id mean travel time
    4. Fallback to global mean travel time
    """
    
    def __init__(self):
        self.global_mean: float = 0.0
        self.route_hour_means: Dict[Tuple[int, int, int], float] = {}
        self.route_means: Dict[Tuple[int, int], float] = {}
        self.source_means: Dict[int, float] = {}
        self.is_fitted: bool = False

    def fit(self, df_train: pd.DataFrame) -> "RouteHistoricalBaseline":
        """Compute baseline averages strictly from training split to prevent leakage.
        
        Args:
            df_train (pd.DataFrame): Cleaned training set with source_id, destination_id, hour, mean_travel_time.
        """
        self.global_mean = float(df_train['mean_travel_time'].mean())
        
        # Route + Hour means
        rh_grouped = df_train.groupby(['source_id', 'destination_id', 'hour'])['mean_travel_time'].mean()
        self.route_hour_means = rh_grouped.to_dict()
        
        # Route overall means
        r_grouped = df_train.groupby(['source_id', 'destination_id'])['mean_travel_time'].mean()
        self.route_means = r_grouped.to_dict()
        
        # Source overall means
        s_grouped = df_train.groupby('source_id')['mean_travel_time'].mean()
        self.source_means = s_grouped.to_dict()
        
        self.is_fitted = True
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        """Predict travel time for input dataframe.
        
        Args:
            df (pd.DataFrame): Input dataframe containing source_id, destination_id, hour.
            
        Returns:
            np.ndarray: Predicted travel times in seconds.
        """
        if not self.is_fitted:
            raise RuntimeError("Baseline model is not fitted yet.")
            
        preds = []
        sources = df['source_id'].values
        dests = df['destination_id'].values
        hours = df['hour'].values

        for src, dst, hr in zip(sources, dests, hours):
            key_rh = (int(src), int(dst), int(hr))
            key_r = (int(src), int(dst))
            s_id = int(src)
            
            if key_rh in self.route_hour_means:
                preds.append(self.route_hour_means[key_rh])
            elif key_r in self.route_means:
                preds.append(self.route_means[key_r])
            elif s_id in self.source_means:
                preds.append(self.source_means[s_id])
            else:
                preds.append(self.global_mean)

        return np.array(preds)
