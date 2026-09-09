/// Map backend reason codes to concise user-facing labels.
String reasonLabel(String code) {
  switch (code.toUpperCase()) {
    case 'FASTEST':
      return 'Fastest option';
    case 'LOW_COST':
      return 'Lower cost';
    case 'LOW_WALKING':
      return 'Less walking';
    case 'FEWER_TRANSFERS':
      return 'Fewer transfers';
    case 'LOW_CONGESTION':
      return 'Lower traffic';
    case 'HIGH_RELIABILITY':
      return 'More reliable';
    case 'HISTORICALLY_STABLE':
      return 'Historically stable';
    case 'CURRENTLY_NEAR_TYPICAL':
      return 'Near typical travel time';
    case 'CURRENTLY_ABOVE_TYPICAL':
      return 'Currently above usual';
    case 'HISTORICAL_SUPPORT':
      return 'Supported by historical data';
    case 'PREFERRED_MODE':
      return 'Fits your preferred mode';
    case 'CONSTRAINT_VIOLATION':
      return 'Does not meet a hard constraint';
    case 'NO_VALID_ROUTE':
      return 'No route matches your constraints';
    default:
      return code.replaceAll('_', ' ').toLowerCase().replaceFirstMapped(
            RegExp(r'^[a-z]'),
            (m) => m.group(0)!.toUpperCase(),
          );
  }
}

String categoryLabel(String category) {
  switch (category.toUpperCase()) {
    case 'BEST_OVERALL':
      return 'Best overall';
    case 'FASTEST':
      return '⚡ Fastest';
    case 'CHEAPEST':
      return '💰 Lower cost';
    case 'MOST_RELIABLE':
      return '🛡️ More reliable';
    case 'LOW_WALKING':
      return '🚶 Less walking';
    default:
      return category;
  }
}

String modeLabel(String mode) {
  switch (mode.toLowerCase()) {
    case 'cab':
    case 'drive':
    case 'taxi':
    case 'uber':
    case 'ola':
    case 'rideshare':
      return 'Cab';
    case 'metro':
    case 'bmrcl':
      return 'Metro';
    case 'bus':
    case 'bmtc':
      return 'Bus';
    case 'auto':
    case 'auto_rickshaw':
    case 'rickshaw':
      return 'Auto';
    case 'walking':
    case 'walk':
      return 'Walk';
    case 'hybrid':
      return 'Mixed';
    default:
      if (mode.isEmpty) return 'Route';
      return mode[0].toUpperCase() + mode.substring(1);
  }
}

String reliabilityBand(double score) {
  if (score >= 0.85) return 'High';
  if (score >= 0.65) return 'Medium';
  return 'Lower';
}

/// Present cost without inventing ₹0 / "Free" for unknown backend values.
String formatCostLabel({
  required double cost,
  required bool known,
  double? partialKnownCostInr,
}) {
  if (!known) {
    if (partialKnownCostInr != null && partialKnownCostInr > 0) {
      return 'From ₹${partialKnownCostInr.toStringAsFixed(0)} (partial)';
    }
    return 'Fare unavailable';
  }
  return '₹${cost.toStringAsFixed(0)}';
}

/// Present duration; unknown values are never shown as exact guarantees.
String formatDurationLabel({
  required double travelTimeMinutes,
  required bool known,
}) {
  if (!known) {
    if (travelTimeMinutes > 0) {
      return '~${travelTimeMinutes.toStringAsFixed(0)} min';
    }
    return 'Time unavailable';
  }
  return '${travelTimeMinutes.toStringAsFixed(0)} min';
}

String agentExplanationOrFallback(String? explanation) {
  // Prefer [buildUserFacingExplanation] / [explanationForPlan] on ResultPage.
  // Kept for callers that only have raw prose — strips technical backend copy.
  final text = (explanation ?? '').trim();
  if (text.isEmpty) {
    return 'Commute Agent selected this journey because it best matches '
        'your preferences.';
  }
  final lower = text.toLowerCase();
  const technical = [
    'deterministic decision engine',
    'decision engine',
    'best_overall',
    'candidates considered',
    'gemini unavailable',
    'deterministic fallback',
    'gemini',
    'score=',
  ];
  for (final m in technical) {
    if (lower.contains(m)) {
      return 'Commute Agent selected this journey because it best matches '
          'your preferences.';
    }
  }
  if (RegExp(r'\bj_[a-z0-9]{4,}\b', caseSensitive: false).hasMatch(text)) {
    return 'Commute Agent selected this journey because it best matches '
        'your preferences.';
  }
  return text;
}
