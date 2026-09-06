"""
Script to generate Exploratory Data Analysis (EDA) visualizations
for Bangalore Uber Movement travel-time dataset.
"""

import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

# Set visual style
sns.set_theme(style="whitegrid", palette="muted")
plt.rcParams.update({'font.sans-serif': 'Inter', 'font.family': 'sans-serif', 'figure.dpi': 150})

def generate_eda_figures(data_path: str = "data/raw/bangalore-wards-2019-3-OnlyWeekdays-HourlyAggregate.csv", output_dir: str = "docs/figures"):
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"Loading dataset from {data_path} for EDA...")
    df = pd.read_csv(data_path)
    df['mean_travel_time_min'] = df['mean_travel_time'] / 60.0

    # 1. Travel Time Distribution
    plt.figure(figsize=(10, 5))
    ax = sns.histplot(df['mean_travel_time_min'], bins=60, kde=True, color='#2b5c8f', edgecolor='none')
    plt.title("Distribution of Zone-to-Zone Average Travel Time in Bangalore (Q3 2019 Weekdays)", fontsize=13, fontweight='bold')
    plt.xlabel("Mean Travel Duration (Minutes)", fontsize=11)
    plt.ylabel("Frequency (Route-Hour Tuples)", fontsize=11)
    
    mean_val = df['mean_travel_time_min'].mean()
    median_val = df['mean_travel_time_min'].median()
    plt.axvline(mean_val, color='#d9534f', linestyle='--', linewidth=2, label=f'Mean: {mean_val:.1f} min')
    plt.axvline(median_val, color='#f0ad4e', linestyle='-', linewidth=2, label=f'Median: {median_val:.1f} min')
    plt.legend(frameon=True, facecolor='white')
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "travel_time_distribution.png"))
    plt.close()
    print("Saved docs/figures/travel_time_distribution.png")

    # 2. Travel Time by Hour & Congestion Profile
    plt.figure(figsize=(12, 6))
    hourly_stats = df.groupby('hod')['mean_travel_time_min'].agg(['mean', 'median', 'std']).reset_index()
    
    plt.plot(hourly_stats['hod'], hourly_stats['mean'], marker='o', linewidth=2.5, color='#c93b2b', label='Mean Travel Duration')
    plt.plot(hourly_stats['hod'], hourly_stats['median'], marker='s', linewidth=2, color='#2b5c8f', linestyle='--', label='Median Travel Duration')
    plt.fill_between(
        hourly_stats['hod'],
        hourly_stats['mean'] - hourly_stats['std'] * 0.25,
        hourly_stats['mean'] + hourly_stats['std'] * 0.25,
        color='#c93b2b', alpha=0.15, label='Route Variance Band'
    )
    
    # Highlight Peak Hours (8-10 AM Morning Peak, 17-20 PM Evening Peak)
    plt.axvspan(8, 10, color='#f0ad4e', alpha=0.2, label='Morning Rush (8-10 AM)')
    plt.axvspan(17, 20, color='#d9534f', alpha=0.2, label='Evening Rush (5-8 PM)')
    
    plt.xticks(range(0, 24))
    plt.title("Hourly Travel Time Profile & Peak Congestion in Bangalore", fontsize=13, fontweight='bold')
    plt.xlabel("Hour of Day (HOD)", fontsize=11)
    plt.ylabel("Travel Duration (Minutes)", fontsize=11)
    plt.legend(loc='upper right', frameon=True, facecolor='white')
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "travel_time_by_hour.png"))
    plt.close()
    print("Saved docs/figures/travel_time_by_hour.png")

    # 3. Busiest / Congested Hours Bar Chart
    plt.figure(figsize=(10, 5))
    palette = ['#d9534f' if hr in [8, 9, 10, 17, 18, 19, 20] else '#4a90e2' for hr in hourly_stats['hod']]
    sns.barplot(data=hourly_stats, x='hod', y='mean', palette=palette)
    plt.title("Average Zone-to-Zone Travel Duration by Hour (Peak Hours Highlighted)", fontsize=13, fontweight='bold')
    plt.xlabel("Hour of Day (0 - 23)", fontsize=11)
    plt.ylabel("Mean Travel Time (Minutes)", fontsize=11)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "busiest_congested_hours.png"))
    plt.close()
    print("Saved docs/figures/busiest_congested_hours.png")

    # 4. Top High Travel Time Origin-Destination Pairs
    plt.figure(figsize=(12, 6))
    route_means = df.groupby(['sourceid', 'dstid'])['mean_travel_time_min'].mean().reset_index()
    top15_routes = route_means.sort_values(by='mean_travel_time_min', ascending=False).head(15)
    top15_routes['route_label'] = top15_routes.apply(lambda r: f"Ward {int(r.sourceid)} → Ward {int(r.dstid)}", axis=1)
    
    sns.barplot(data=top15_routes, y='route_label', x='mean_travel_time_min', palette='Reds_r')
    plt.title("Top 15 Longest Zone-to-Zone Commute Routes in Bangalore (Q3 2019)", fontsize=13, fontweight='bold')
    plt.xlabel("Average Travel Duration (Minutes)", fontsize=11)
    plt.ylabel("Origin → Destination Ward Pair", fontsize=11)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "top_high_travel_time_od_pairs.png"))
    plt.close()
    print("Saved docs/figures/top_high_travel_time_od_pairs.png")

    # 5. Example Route Hourly Profiles
    plt.figure(figsize=(10, 5))
    sample_routes = top15_routes.head(4)[['sourceid', 'dstid']].values
    
    for src, dst in sample_routes:
        route_df = df[(df['sourceid'] == src) & (df['dstid'] == dst)].sort_values('hod')
        plt.plot(route_df['hod'], route_df['mean_travel_time_min'], marker='o', label=f'Ward {src} → Ward {dst}')
        
    plt.xticks(range(0, 24))
    plt.title("Hourly Travel Time Profile for Representative High-Congestion Routes", fontsize=13, fontweight='bold')
    plt.xlabel("Hour of Day (HOD)", fontsize=11)
    plt.ylabel("Travel Duration (Minutes)", fontsize=11)
    plt.legend(frameon=True, facecolor='white')
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "example_route_profiles.png"))
    plt.close()
    print("Saved docs/figures/example_route_profiles.png")


if __name__ == "__main__":
    generate_eda_figures()
