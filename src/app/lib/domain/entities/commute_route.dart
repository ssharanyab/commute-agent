import 'historical_signal.dart';

/// A candidate or recommended commute route (domain concept).
class CommuteRoute {
  final String routeId;
  final String mode;
  final double travelTimeMinutes;
  final double cost;
  final double walkingMinutes;
  final int transfers;
  final double congestionScore;
  final double reliabilityScore;
  final double? distanceKm;
  final int? distanceMeters;
  final String? googlePolyline;
  final String? googleRouteToken;
  final HistoricalSignal? historicalSignal;

  const CommuteRoute({
    required this.routeId,
    required this.mode,
    required this.travelTimeMinutes,
    required this.cost,
    required this.walkingMinutes,
    required this.transfers,
    required this.congestionScore,
    required this.reliabilityScore,
    this.distanceKm,
    this.distanceMeters,
    this.googlePolyline,
    this.googleRouteToken,
    this.historicalSignal,
  });
}
