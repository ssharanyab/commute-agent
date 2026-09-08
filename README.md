# Commute Agent: AI Travel/Commute Intelligence Agent (Patchamomma)

A production-oriented AI Travel & Commute Intelligence Agent designed to predict travel times, evaluate route and commute conditions, recommend optimal departure times and transport options, and provide natural-language reasoning and explanations via Gemini.

---

## 🎯 Target Cities & Demo Journeys
- **Mumbai:** Andheri → BKC
- **Bengaluru demo OD:** Electronic City → Majestic

---

## 📊 Dataset Source & Schema

**Primary Mobility Source:** **Uber Movement India Data** (`data/raw/bangalore-wards-2019-3-OnlyWeekdays-HourlyAggregate.csv`)
- **Type:** Aggregated hourly weekday travel times across 198 Bangalore ward zones.
- **Records:** 818,262 unique `(sourceid, dstid, hod)` tuples.

| Column | Data Type | Description |
| :--- | :--- | :--- |
| `sourceid` | `int64` | Origin Ward ID |
| `dstid` | `int64` | Destination Ward ID |
| `hod` | `int64` | Hour of Day (0 – 23) |
| `mean_travel_time` | `float64` | Target: Mean travel duration in seconds |

---

## ⚙️ Route Evaluation Engine (`src/decision_engine/`)

The deterministic decision engine evaluates candidate commute routes (`RouteCandidate`) against user preferences and hard constraints (`UserPreferences`).

### Key Features:
1. **Normalized Attribute Scaling:** Min-max normalizes travel time, cost, walking, transfers, congestion, and disruption risks across candidate pools.
2. **Hard Constraint Enforcement:** Filters routes exceeding `max_walking_minutes`, `max_cost`, or `avoid_heavy_traffic`.
3. **Multi-Factor Utility Scoring:** Weighted trade-off utility function incorporating time, cost, walking effort, transfers, congestion, disruption, and reliability.
4. **Historical Mobility Signal Integration:** Seamlessly incorporates XGBoost ML historical signals when available (`has_historical_coverage=True`) with fallback for unrepresented routes.
5. **Human-Readable Reason Codes:** Generates transparent reason codes (`FASTEST`, `LOW_COST`, `LOW_WALKING`, `FEWER_TRANSFERS`, `LOW_CONGESTION`, `HIGH_RELIABILITY`, `HISTORICAL_SUPPORT`, `PREFERRED_MODE`, `CONSTRAINT_VIOLATION`).

---

## 🧪 Generalization & Audit Evaluation Results

To rigorously evaluate model behavior and prevent misleading claims, the ML model was tested under three holdout strategies:

| Holdout Test | Strategy Description | Baseline MAE | XGBoost MAE | XGBoost R² |
| :--- | :--- | :---: | :---: | :---: |
| **TEST 1 — Random Row Holdout** | 70/15/15 random split across `(sourceid, dstid, hod)` rows | 8.51 min | **2.60 min** | **0.9658** |
| **TEST 2 — Unseen-Route Holdout** | 70/15/15 split on OD pairs (Test routes completely unseen in training) | 15.88 min | **12.61 min** | **0.3963** |
| **TEST 3 — Unseen Destination Holdout** | 70/15/15 split holding out 15% of destination wards from training | 15.90 min | **12.78 min** | **0.3830** |

---

## 🔍 Feature Importance Analysis

XGBoost feature importances (normalized gain):
- `route_hist_mean`: **54.31%** (Historical route mean travel time)
- `hour`: **16.48%** (Hour of day context)
- `sin_hour` / `cos_hour`: **13.79%** (Cyclic continuous time representation)
- `dst_hist_mean` / `source_hist_mean`: **13.16%** (Zone area historical averages)
- `destination_id` / `source_id`: **2.26%** (Direct raw integer zone IDs)

---

## ⚠️ Dataset Limitations & Model Scope

1. **No Date-Level Observations:** The dataset consists of a single aggregated table of Q3 2019 Weekday average hourly travel times. It lacks individual calendar date timestamps.
2. **Not a Future-Day Forecaster:** This dataset does **not** support forecasting future-day events or real-time incident disruptions.
3. **Correct Framing for Patchamomma Demo:** The model is framed as a **Historical Mobility Intelligence Signal** provider. For known urban corridors across Bangalore's 198 wards, it estimates typical weekday hourly travel durations within **±2.6 minutes MAE**.

---

## 🏗️ System Architecture

```text
Google Maps Routes API (Live candidate routes & traffic)
       +
Uber Movement XGBoost ML (Historical mobility intelligence signal)
       ↓
Route Evaluation Engine (src/decision_engine/ - Deterministic Scoring & Constraints)
       ↓
Google ADK + Gemini (Reasoning, Planning & Explanations)
       ↓
FastAPI Backend API → Flutter Frontend
```

---

## 🚀 Usage Commands

### 1. Run Route Decision Engine Demo
```bash
python -m scripts.demo_decision_engine
```

### 2. Run Pipeline & Model Training
```bash
python -m src.train
```

### 3. Run Generalization Audit
```bash
python -m src.audit
```

### 4. Run Pytest Test Suite
```bash
python -m pytest tests/
```

---

## 📂 Directory Structure

```text
commute-agent/
├── data/
│   ├── raw/          # Uber Movement raw CSV dataset files
│   └── processed/    # Cleaned dataset outputs
├── docs/
│   ├── figures/      # EDA & feature importance plots
│   └── generate_eda_plots.py
├── models/           # Serialized models & metrics JSONs
├── scripts/
│   └── demo_decision_engine.py
├── src/              # Python source modules
│   ├── __init__.py
│   ├── init.py
│   ├── data.py       # Data loading & cleaning pipeline
│   ├── features.py   # Leakage-free feature transformer
│   ├── baseline.py   # Route historical baseline class
│   ├── train.py      # Main training CLI
│   ├── audit.py      # 3-test generalization audit script
│   ├── predict.py    # Historical mobility signal interface
│   └── decision_engine/
│       ├── __init__.py
│       ├── models.py      # RouteCandidate, UserPreferences, EvaluationResult
│       ├── scoring.py     # Deterministic normalization & utility scoring
│       └── evaluator.py   # Route ranking & recommendation engine
├── tests/            # Pytest test suite
│   ├── fixtures.py   # Local Bengaluru candidate route fixtures
│   ├── test_pipeline.py
│   └── test_decision_engine.py
├── requirements.txt  # Package dependencies
├── README.md         # Documentation
└── .gitignore
```
