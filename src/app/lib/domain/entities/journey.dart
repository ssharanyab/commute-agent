import 'journey_leg.dart';
import 'value_status.dart';

/// Full journey selected (or listed) by the backend Decision Engine.
class RecommendedJourney {
  final String candidateId;
  final List<double>? originLatLon;
  final List<double>? destinationLatLon;
  final List<JourneyLeg> legs;
  final List<String> modes;
  final String modeSignature;
  final ValueStatus costStatus;
  final ValueStatus durationStatus;
  final double? totalCostInr;
  final double? totalDurationSeconds;
  final int transferCount;
  final double walkingDistanceMeters;
  final int transitLegCount;
  final int roadLegCount;
  final Map<String, String> snapshotVersions;
  final List<String> provenanceSources;
  final String temporalFeasibility;
  final List<String> warnings;
  final double? accessWalkingMeters;
  final double? transferWalkingMeters;
  final double? egressWalkingMeters;

  const RecommendedJourney({
    required this.candidateId,
    this.originLatLon,
    this.destinationLatLon,
    this.legs = const [],
    this.modes = const [],
    this.modeSignature = '',
    this.costStatus = ValueStatus.unknown,
    this.durationStatus = ValueStatus.unknown,
    this.totalCostInr,
    this.totalDurationSeconds,
    this.transferCount = 0,
    this.walkingDistanceMeters = 0,
    this.transitLegCount = 0,
    this.roadLegCount = 0,
    this.snapshotVersions = const {},
    this.provenanceSources = const [],
    this.temporalFeasibility = 'unknown',
    this.warnings = const [],
    this.accessWalkingMeters,
    this.transferWalkingMeters,
    this.egressWalkingMeters,
  });
}
