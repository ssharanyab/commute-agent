"""
Named replanning thresholds (Phase 5E).

Rationale:
- Avoid switching journeys for Decision Engine score noise.
- Prefer KEEP when the previous journey remains valid and the challenger
  does not beat it by a meaningful margin.
- Invalid journeys (hard constraints / explicit disruption) always force
  reconsideration regardless of score margin.
"""

from __future__ import annotations

# Minimum Decision Engine score advantage (points) required to SWITCH away
# from a still-valid previous recommendation. Tuned for MVP demos — not optimized.
SCORE_SWITCH_MARGIN = 5.0

# Travel-time deltas below this (minutes) are treated as insignificant traffic noise
# when classifying NO_SIGNIFICANT_CHANGE for same-winner outcomes.
TRAVEL_TIME_INSIGNIFICANT_MINUTES = 2.0

# Travel-time deltas at/above this (minutes) are treated as significant context
# for KEEP_CURRENT vs NO_SIGNIFICANT_CHANGE labeling when the winner is unchanged.
TRAVEL_TIME_SIGNIFICANT_MINUTES = 8.0
