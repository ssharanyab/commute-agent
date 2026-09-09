import 'value_status.dart';

/// One leg of a Journey Builder candidate (backend `/plan` journey.legs[]).
///
/// Retains navigation fields (polyline / route token) for later external
/// Maps handoff — not for in-app map rendering in Phase 6G.1.
class JourneyLeg {
  final int index;
  final String mode;
  final String fromNodeId;
  final String toNodeId;
  final String edgeId;
  final String edgeKind;
  final String? fromRef;
  final String? toRef;
  final String? routeId;
  final String? provider;
  final double? distanceMeters;
  final bool isTransfer;
  final bool needsEnrichment;
  final String? estimatedDeparture;
  final String? estimatedArrival;
  final int? waitingSeconds;
  final String segmentRole;
  final double? costInr;
  final ValueStatus costStatus;
  final double? durationSeconds;
  final ValueStatus durationStatus;
  final double walkingMeters;
  final Map<String, dynamic>? provenance;
  final Map<String, dynamic> metadata;
  final String? googlePolyline;
  final String? googleRouteToken;

  const JourneyLeg({
    required this.index,
    required this.mode,
    required this.fromNodeId,
    required this.toNodeId,
    required this.edgeId,
    required this.edgeKind,
    this.fromRef,
    this.toRef,
    this.routeId,
    this.provider,
    this.distanceMeters,
    this.isTransfer = false,
    this.needsEnrichment = false,
    this.estimatedDeparture,
    this.estimatedArrival,
    this.waitingSeconds,
    this.segmentRole = 'other',
    this.costInr,
    this.costStatus = ValueStatus.unknown,
    this.durationSeconds,
    this.durationStatus = ValueStatus.unknown,
    this.walkingMeters = 0,
    this.provenance,
    this.metadata = const {},
    this.googlePolyline,
    this.googleRouteToken,
  });

  double? get durationMinutes =>
      durationSeconds == null ? null : durationSeconds! / 60.0;
}
