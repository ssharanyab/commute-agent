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
      return 'Fastest';
    case 'CHEAPEST':
      return 'Cheapest';
    case 'MOST_RELIABLE':
      return 'Most reliable';
    default:
      return category;
  }
}

String modeLabel(String mode) {
  switch (mode.toLowerCase()) {
    case 'cab':
    case 'drive':
    case 'taxi':
      return 'Cab';
    case 'metro':
      return 'Metro';
    case 'bus':
      return 'Bus';
    case 'auto':
      return 'Auto';
    case 'walking':
    case 'walk':
      return 'Walking';
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
