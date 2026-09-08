/// Historical mobility intelligence attached to a route (optional).
class HistoricalSignal {
  final bool hasCoverage;
  final double? expectedMinutes;
  final double? stdMinutes;
  final double? reliabilityScore;
  final String? confidenceLevel;
  final double? deviationPercent;
  final String? deviationState;
  final double? congestionFactor;

  const HistoricalSignal({
    required this.hasCoverage,
    this.expectedMinutes,
    this.stdMinutes,
    this.reliabilityScore,
    this.confidenceLevel,
    this.deviationPercent,
    this.deviationState,
    this.congestionFactor,
  });
}
