"""
Data Ingestion and Preprocessing Module for Uber Movement Data.

Handles CSV loading, dynamic schema detection, data cleaning, validation,
and saving cleaned datasets to data/processed/.
"""

import os
import glob
from typing import List, Tuple, Dict, Any
import pandas as pd
import numpy as np


# Standard candidate column mappings for Uber Movement datasets
COLUMN_MAPPINGS = {
    'source_id': ['sourceid', 'source_id', 'origin_id', 'source', 'start_id', 'origin'],
    'destination_id': ['dstid', 'destination_id', 'dst_id', 'destination', 'end_id'],
    'hour': ['hod', 'hour_of_day', 'hour', 'time_of_day'],
    'mean_travel_time': ['mean_travel_time', 'geometric_mean_travel_time', 'travel_time', 'duration', 'mean_duration'],
    'std_travel_time': ['standard_deviation_travel_time', 'std_travel_time', 'std_dev'],
    'geom_mean_travel_time': ['geometric_mean_travel_time', 'geom_mean'],
    'geom_std_travel_time': ['geometric_standard_deviation_travel_time', 'geom_std']
}


def find_raw_datasets(raw_dir: str = "data/raw") -> List[str]:
    """Find all CSV dataset files in the raw data directory.
    
    Args:
        raw_dir (str): Path to raw data directory.
        
    Returns:
        List[str]: List of paths to found CSV files.
    """
    if not os.path.exists(raw_dir):
        return []
    csv_files = glob.glob(os.path.join(raw_dir, "*.csv")) + glob.glob(os.path.join(raw_dir, "**/*.csv"), recursive=True)
    return csv_files


def detect_columns(df: pd.DataFrame) -> Dict[str, str]:
    """Detect and map actual CSV column names to standardized domain column names.
    
    Args:
        df (pd.DataFrame): Input raw dataframe.
        
    Returns:
        Dict[str, str]: Mapping from standardized name to actual column name in df.
    """
    column_map = {}
    df_cols_lower = {col.lower(): col for col in df.columns}

    for std_name, candidates in COLUMN_MAPPINGS.items():
        for candidate in candidates:
            if candidate.lower() in df_cols_lower:
                column_map[std_name] = df_cols_lower[candidate.lower()]
                break

    return column_map


def inspect_dataset(df: pd.DataFrame) -> Dict[str, Any]:
    """Inspect dataset schema, missing values, duplicate counts, and key stats.
    
    Args:
        df (pd.DataFrame): Dataframe to inspect.
        
    Returns:
        Dict[str, Any]: Summary dictionary of inspection metrics.
    """
    detected = detect_columns(df)
    
    source_col = detected.get('source_id', 'sourceid')
    dst_col = detected.get('destination_id', 'dstid')
    hour_col = detected.get('hour', 'hod')
    
    n_sources = df[source_col].nunique() if source_col in df.columns else 0
    n_dsts = df[dst_col].nunique() if dst_col in df.columns else 0
    all_zones = set(df[source_col]).union(set(df[dst_col])) if (source_col in df.columns and dst_col in df.columns) else set()
    
    od_hour_tuples = len(df.groupby([source_col, dst_col, hour_col])) if {source_col, dst_col, hour_col}.issubset(df.columns) else 0

    summary = {
        "num_rows": len(df),
        "num_cols": len(df.columns),
        "actual_columns": list(df.columns),
        "detected_mapping": detected,
        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
        "missing_counts": df.isnull().sum().to_dict(),
        "duplicate_rows": int(df.duplicated().sum()),
        "num_source_zones": int(n_sources),
        "num_destination_zones": int(n_dsts),
        "num_total_unique_zones": int(len(all_zones)),
        "num_od_hour_tuples": int(od_hour_tuples)
    }
    return summary


def clean_data(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Clean and validate raw Uber Movement dataset.
    
    Performs schema standardization, missing value removal, invalid record filtering,
    and type conversion.
    
    Args:
        df (pd.DataFrame): Input dataframe.
        
    Returns:
        Tuple[pd.DataFrame, Dict[str, Any]]: (cleaned_df, cleaning_stats)
    """
    initial_count = len(df)
    col_map = detect_columns(df)
    
    # Verify required core columns exist
    required_cols = ['source_id', 'destination_id', 'hour', 'mean_travel_time']
    missing_req = [col for col in required_cols if col not in col_map]
    if missing_req:
        raise ValueError(
            f"Dataset is missing required conceptual columns: {missing_req}. "
            f"Found columns: {list(df.columns)}"
        )

    # Rename to standardized column names
    rename_dict = {col_map[std]: std for std in col_map}
    df_clean = df.rename(columns=rename_dict).copy()
    
    # Coerce numeric types
    for col in required_cols:
        df_clean[col] = pd.to_numeric(df_clean[col], errors='coerce')

    # Drop missing values in core columns
    df_clean = df_clean.dropna(subset=required_cols)
    
    # Filter valid domain ranges:
    # 1. Hour between 0 and 23
    # 2. Mean travel time > 0 and <= 86400 seconds (24 hours)
    # 3. Non-negative Zone IDs
    valid_mask = (
        (df_clean['hour'] >= 0) & (df_clean['hour'] <= 23) &
        (df_clean['mean_travel_time'] > 0) & (df_clean['mean_travel_time'] <= 86400) &
        (df_clean['source_id'] >= 0) & (df_clean['destination_id'] >= 0)
    )
    df_clean = df_clean[valid_mask].copy()

    # Convert zone IDs and hour to integers
    df_clean['source_id'] = df_clean['source_id'].astype(int)
    df_clean['destination_id'] = df_clean['destination_id'].astype(int)
    df_clean['hour'] = df_clean['hour'].astype(int)

    final_count = len(df_clean)
    stats = {
        "initial_rows": initial_count,
        "final_rows": final_count,
        "removed_rows": initial_count - final_count
    }
    
    return df_clean, stats


def load_and_clean_data(file_path: str) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Load raw dataset CSV and apply data cleaning pipeline.
    
    Args:
        file_path (str): Path to raw CSV dataset.
        
    Returns:
        Tuple[pd.DataFrame, Dict[str, Any]]: (cleaned_dataframe, stats_and_inspection)
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Dataset file not found at path: {file_path}")
        
    df_raw = pd.read_csv(file_path)
    inspection = inspect_dataset(df_raw)
    df_clean, cleaning_stats = clean_data(df_raw)
    
    inspection["cleaning_stats"] = cleaning_stats
    return df_clean, inspection


def save_processed_data(df: pd.DataFrame, output_path: str = "data/processed/uber_movement_cleaned.csv") -> str:
    """Save cleaned dataset to processed data directory.
    
    Args:
        df (pd.DataFrame): Cleaned dataframe.
        output_path (str): Target output file path.
        
    Returns:
        str: Output file path.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df.to_csv(output_path, index=False)
    return output_path
