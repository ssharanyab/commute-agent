import 'historical_signal.dart';
import 'value_status.dart';

/// A candidate or recommended commute route (Decision Engine route shape).
///
/// Ranking/scoring remain backend-authoritative. Flutter only presents fields.
class CommuteRoute {
  final String routeId;
  final String mode;
  final double travelTimeMinutes;
  final double cost;
  final ValueStatus costStatus;
  final ValueStatus durationStatus;
  final double? partialKnownCostInr;
  final double walkingMinutes;
  final int transfers;
  final double congestionScore;
  final double reliabilityScore;
  final double disruptionRisk;
  final double? distanceKm;
  final int? distanceMeters;
  final String? googlePolyline;
  final String? googleRouteToken;
  final HistoricalSignal? historicalSignal;
  final List<String> componentModes;
  final String modeSignature;
  final double? accessWalkingMeters;
  final double? transferWalkingMeters;
  final double? egressWalkingMeters;

  const CommuteRoute({
    required this.routeId,
    required this.mode,
    required this.travelTimeMinutes,
    required this.cost,
    this.costStatus = ValueStatus.known,
    this.durationStatus = ValueStatus.known,
    this.partialKnownCostInr,
    required this.walkingMinutes,
    required this.transfers,
    required this.congestionScore,
    required this.reliabilityScore,
    this.disruptionRisk = 0,
    this.distanceKm,
    this.distanceMeters,
    this.googlePolyline,
    this.googleRouteToken,
    this.historicalSignal,
    this.componentModes = const [],
    this.modeSignature = '',
    this.accessWalkingMeters,
    this.transferWalkingMeters,
    this.egressWalkingMeters,
  });

  /// True when cost must not be shown as a concrete rupee amount.
  bool get hasKnownCost => costStatus == ValueStatus.known;

  /// True when travel time is an authoritative known duration.
  bool get hasKnownDuration => durationStatus == ValueStatus.known;
}
