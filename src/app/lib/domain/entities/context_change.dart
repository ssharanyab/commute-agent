class ContextChange {
  final bool trafficChanged;
  final bool disruptionChanged;
  final bool weatherChanged;
  final String contextSource;
  final String? targetRouteId;
  final double congestionDelta;
  final double travelTimeDeltaMinutes;
  final double disruptionDelta;
  final String? weatherNote;
  final String description;
  final String? updatedDepartureTime;

  const ContextChange({
    this.trafficChanged = false,
    this.disruptionChanged = false,
    this.weatherChanged = false,
    this.contextSource = 'simulated',
    this.targetRouteId,
    this.congestionDelta = 0,
    this.travelTimeDeltaMinutes = 0,
    this.disruptionDelta = 0,
    this.weatherNote,
    this.description = '',
    this.updatedDepartureTime,
  });
}
