import '../../domain/entities/commute_plan.dart';
import '../../domain/entities/commute_route.dart';
import '../../domain/entities/context_change.dart';
import '../../domain/entities/decision_summary.dart';
import '../../domain/entities/gemini_meta.dart';
import '../../domain/entities/historical_signal.dart';
import '../../domain/entities/journey.dart';
import '../../domain/entities/journey_leg.dart';
import '../../domain/entities/journey_step.dart';
import '../../domain/entities/replan_result.dart';
import '../../domain/entities/route_category.dart';
import '../../domain/entities/top_journey.dart';
import '../../domain/entities/value_status.dart';

List<JourneyStep> _parseJourneySteps(dynamic raw) {
  if (raw is! List) return const [];
  final out = <JourneyStep>[];
  for (final item in raw) {
    if (item is! Map) continue;
    final m = Map<String, dynamic>.from(item);
    final instruction = (m['instruction'] as String?) ?? '';
    if (instruction.trim().isEmpty) continue;
    out.add(
      JourneyStep(
        type: (m['type'] as String?) ?? 'LEG',
        instruction: instruction,
        mode: m['mode'] as String?,
        fromName: m['from_name'] as String?,
        toName: m['to_name'] as String?,
        fromMode: m['from_mode'] as String?,
        toMode: m['to_mode'] as String?,
        locationName: m['location_name'] as String?,
      ),
    );
  }
  return out;
}

class GeminiMetaModel {
  final bool available;
  final bool invoked;
  final bool adkInvoked;
  final String mode;

  const GeminiMetaModel({
    required this.available,
    required this.invoked,
    required this.adkInvoked,
    required this.mode,
  });

  factory GeminiMetaModel.fromJson(Map<String, dynamic>? json) {
    if (json == null) {
      return const GeminiMetaModel(
        available: false,
        invoked: false,
        adkInvoked: false,
        mode: 'unknown',
      );
    }
    return GeminiMetaModel(
      available: json['available'] == true,
      invoked: json['invoked'] == true,
      adkInvoked: json['adk_invoked'] == true,
      mode: (json['mode'] as String?) ?? 'unknown',
    );
  }

  GeminiMeta toEntity() => GeminiMeta(
        available: available,
        invoked: invoked,
        adkInvoked: adkInvoked,
        mode: mode,
      );
}

List<String> _stringList(dynamic raw) {
  if (raw is! List) return const [];
  return raw.map((e) => '$e').toList();
}

Map<String, dynamic>? _asStringKeyedMap(dynamic raw) {
  if (raw is! Map) return null;
  return Map<String, dynamic>.from(raw);
}

class RouteModel {
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

  const RouteModel({
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

  factory RouteModel.fromJson(
    Map<String, dynamic> json, {
    double? distanceKmFallback,
  }) {
    final meters = (json['distance_meters'] as num?)?.toInt();
    final distanceKm = meters != null ? meters / 1000.0 : distanceKmFallback;
    final components = _stringList(json['component_modes']);
    return RouteModel(
      routeId: (json['route_id'] as String?) ?? 'unknown',
      mode: (json['mode'] as String?) ?? 'unknown',
      travelTimeMinutes: (json['travel_time_minutes'] as num?)?.toDouble() ?? 0,
      cost: (json['cost'] as num?)?.toDouble() ?? 0,
      costStatus: ValueStatus.fromWire(
        json['cost_status'] as String?,
        whenMissing: ValueStatus.known,
      ),
      durationStatus: ValueStatus.fromWire(
        json['duration_status'] as String?,
        whenMissing: ValueStatus.known,
      ),
      partialKnownCostInr:
          (json['partial_known_cost_inr'] as num?)?.toDouble(),
      walkingMinutes: (json['walking_minutes'] as num?)?.toDouble() ?? 0,
      transfers: (json['transfers'] as num?)?.toInt() ?? 0,
      congestionScore: (json['congestion_score'] as num?)?.toDouble() ?? 0,
      reliabilityScore: (json['reliability_score'] as num?)?.toDouble() ?? 0,
      disruptionRisk: (json['disruption_risk'] as num?)?.toDouble() ?? 0,
      distanceKm: distanceKm,
      distanceMeters: meters,
      googlePolyline: (json['google_polyline'] as String?) ??
          (json['googlePolyline'] as String?),
      googleRouteToken: (json['google_route_token'] as String?) ??
          (json['googleRouteToken'] as String?),
      historicalSignal: _parseHistorical(
        json['historical_mobility_signal'] ?? json['historicalMobilitySignal'],
      ),
      componentModes: components,
      modeSignature: (json['mode_signature'] as String?) ?? '',
      accessWalkingMeters:
          (json['access_walking_meters'] as num?)?.toDouble(),
      transferWalkingMeters:
          (json['transfer_walking_meters'] as num?)?.toDouble(),
      egressWalkingMeters:
          (json['egress_walking_meters'] as num?)?.toDouble(),
    );
  }

  CommuteRoute toEntity() => CommuteRoute(
        routeId: routeId,
        mode: mode,
        travelTimeMinutes: travelTimeMinutes,
        cost: cost,
        costStatus: costStatus,
        durationStatus: durationStatus,
        partialKnownCostInr: partialKnownCostInr,
        walkingMinutes: walkingMinutes,
        transfers: transfers,
        congestionScore: congestionScore,
        reliabilityScore: reliabilityScore,
        disruptionRisk: disruptionRisk,
        distanceKm: distanceKm,
        distanceMeters: distanceMeters,
        googlePolyline: googlePolyline,
        googleRouteToken: googleRouteToken,
        historicalSignal: historicalSignal,
        componentModes: componentModes,
        modeSignature: modeSignature,
        accessWalkingMeters: accessWalkingMeters,
        transferWalkingMeters: transferWalkingMeters,
        egressWalkingMeters: egressWalkingMeters,
      );
}

HistoricalSignal? _parseHistorical(dynamic raw) {
  if (raw is! Map) return null;
  final json = Map<String, dynamic>.from(raw);
  final has = json['has_historical_coverage'] == true ||
      json['historical_coverage'] == true;
  return HistoricalSignal(
    hasCoverage: has,
    expectedMinutes: (json['historical_expected_travel_time_minutes'] as num?)
            ?.toDouble() ??
        (json['historical_typical_travel_time_minutes'] as num?)?.toDouble(),
    stdMinutes:
        (json['historical_std_travel_time_minutes'] as num?)?.toDouble(),
    reliabilityScore:
        (json['historical_reliability_score'] as num?)?.toDouble(),
    confidenceLevel: json['confidence_level'] as String?,
    deviationPercent: (json['deviation_percent'] as num?)?.toDouble(),
    deviationState: json['deviation_state'] as String?,
    congestionFactor:
        (json['historical_congestion_factor'] as num?)?.toDouble(),
  );
}

double? distanceKmForRouteId(String? routeId, List<dynamic>? mapsRoutes) {
  if (routeId == null || mapsRoutes == null) return null;
  final parts = routeId.split('_');
  if (parts.length < 3) return null;
  final index = int.tryParse(parts.last);
  final modeToken = parts.length >= 2 ? parts[1].toUpperCase() : null;
  if (index == null) return null;
  for (final raw in mapsRoutes) {
    if (raw is! Map) continue;
    final m = Map<String, dynamic>.from(raw);
    final ri = (m['route_index'] as num?)?.toInt();
    final mode = (m['mode'] as String?)?.toUpperCase();
    if (ri == index && (modeToken == null || mode == modeToken)) {
      final meters = (m['distance_meters'] as num?)?.toDouble();
      if (meters == null) return null;
      return meters / 1000.0;
    }
  }
  return null;
}

class JourneyLegModel {
  final JourneyLeg entity;

  JourneyLegModel(this.entity);

  factory JourneyLegModel.fromJson(Map<String, dynamic> json) {
    final metadata = _asStringKeyedMap(json['metadata']) ?? const {};
    final polyline = (json['google_polyline'] as String?) ??
        metadata['google_polyline'] as String? ??
        metadata['polyline'] as String?;
    final token = (json['google_route_token'] as String?) ??
        metadata['google_route_token'] as String? ??
        metadata['route_token'] as String?;
    return JourneyLegModel(
      JourneyLeg(
        index: (json['index'] as num?)?.toInt() ?? 0,
        mode: (json['mode'] as String?) ?? 'unknown',
        fromNodeId: (json['from_node_id'] as String?) ?? '',
        toNodeId: (json['to_node_id'] as String?) ?? '',
        edgeId: (json['edge_id'] as String?) ?? '',
        edgeKind: (json['edge_kind'] as String?) ?? '',
        fromRef: json['from_ref'] as String?,
        toRef: json['to_ref'] as String?,
        routeId: json['route_id'] as String?,
        provider: json['provider'] as String?,
        distanceMeters: (json['distance_meters'] as num?)?.toDouble(),
        isTransfer: json['is_transfer'] == true,
        needsEnrichment: json['needs_enrichment'] == true,
        estimatedDeparture: json['estimated_departure'] as String?,
        estimatedArrival: json['estimated_arrival'] as String?,
        waitingSeconds: (json['waiting_seconds'] as num?)?.toInt(),
        segmentRole: (json['segment_role'] as String?) ?? 'other',
        costInr: (json['cost_inr'] as num?)?.toDouble(),
        costStatus: ValueStatus.fromWire(json['cost_status'] as String?),
        durationSeconds: (json['duration_seconds'] as num?)?.toDouble(),
        durationStatus:
            ValueStatus.fromWire(json['duration_status'] as String?),
        walkingMeters: (json['walking_meters'] as num?)?.toDouble() ?? 0,
        provenance: _asStringKeyedMap(json['provenance']),
        metadata: metadata,
        googlePolyline: polyline,
        googleRouteToken: token,
      ),
    );
  }
}

class JourneyModel {
  final RecommendedJourney entity;

  JourneyModel(this.entity);

  factory JourneyModel.fromJson(Map<String, dynamic> json) {
    final legsRaw = json['legs'];
    final legs = <JourneyLeg>[];
    if (legsRaw is List) {
      for (final raw in legsRaw) {
        if (raw is! Map) continue;
        legs.add(
          JourneyLegModel.fromJson(Map<String, dynamic>.from(raw)).entity,
        );
      }
    }
    List<double>? latLon(dynamic raw) {
      if (raw is! List || raw.length < 2) return null;
      final a = (raw[0] as num?)?.toDouble();
      final b = (raw[1] as num?)?.toDouble();
      if (a == null || b == null) return null;
      return [a, b];
    }

    final snaps = <String, String>{};
    final snapRaw = json['snapshot_versions'];
    if (snapRaw is Map) {
      snapRaw.forEach((k, v) => snaps['$k'] = '$v');
    }

    return JourneyModel(
      RecommendedJourney(
        candidateId: (json['candidate_id'] as String?) ?? '',
        originLatLon: latLon(json['origin']),
        destinationLatLon: latLon(json['destination']),
        legs: legs,
        steps: _parseJourneySteps(json['steps']),
        modes: _stringList(json['modes']),
        modeSignature: (json['mode_signature'] as String?) ?? '',
        costStatus: ValueStatus.fromWire(json['cost_status'] as String?),
        durationStatus:
            ValueStatus.fromWire(json['duration_status'] as String?),
        totalCostInr: (json['total_cost_inr'] as num?)?.toDouble(),
        totalDurationSeconds:
            (json['total_duration_seconds'] as num?)?.toDouble(),
        transferCount: (json['transfer_count'] as num?)?.toInt() ?? 0,
        walkingDistanceMeters:
            (json['walking_distance_meters'] as num?)?.toDouble() ?? 0,
        transitLegCount: (json['transit_leg_count'] as num?)?.toInt() ?? 0,
        roadLegCount: (json['road_leg_count'] as num?)?.toInt() ?? 0,
        snapshotVersions: snaps,
        provenanceSources: _stringList(json['provenance_sources']),
        temporalFeasibility:
            (json['temporal_feasibility'] as String?) ?? 'unknown',
        warnings: _stringList(json['warnings']),
        accessWalkingMeters:
            (json['access_walking_meters'] as num?)?.toDouble(),
        transferWalkingMeters:
            (json['transfer_walking_meters'] as num?)?.toDouble(),
        egressWalkingMeters:
            (json['egress_walking_meters'] as num?)?.toDouble(),
      ),
    );
  }
}

class DecisionModel {
  final DecisionSummary entity;

  DecisionModel(this.entity);

  factory DecisionModel.fromJson(Map<String, dynamic> json) {
    final scores = <String, double>{};
    final scoresRaw = json['scores'];
    if (scoresRaw is Map) {
      scoresRaw.forEach((k, v) {
        final n = (v as num?)?.toDouble();
        if (n != null) scores['$k'] = n;
      });
    }
    final cats = <String, String>{};
    final catsRaw = json['category_assignments'];
    if (catsRaw is Map) {
      catsRaw.forEach((k, v) => cats['$k'] = '$v');
    }
    return DecisionModel(
      DecisionSummary(
        recommendedRouteId: json['recommended_route_id'] as String?,
        rankedRouteIds: _stringList(json['ranked_route_ids']),
        categoryAssignments: cats,
        scores: scores,
        reasonCodes: _stringList(json['reason_codes']),
        authoritative: json['authoritative'] != false,
      ),
    );
  }
}

class EvaluationModel {
  final EvaluationSummary entity;

  EvaluationModel(this.entity);

  factory EvaluationModel.fromJson(Map<String, dynamic> json) {
    final ranked = <RankedEvaluationEntry>[];
    final rankedRaw = json['ranked'];
    if (rankedRaw is List) {
      for (final raw in rankedRaw) {
        if (raw is! Map) continue;
        final m = Map<String, dynamic>.from(raw);
        ranked.add(
          RankedEvaluationEntry(
            routeId: (m['route_id'] as String?) ?? '',
            finalScore: (m['final_score'] as num?)?.toDouble() ?? 0,
            isValid: m['is_valid'] != false,
            reasonCodes: _stringList(m['reason_codes']),
            costStatus: m['cost_status'] as String?,
            durationStatus: m['duration_status'] as String?,
            modeSignature: m['mode_signature'] as String?,
          ),
        );
      }
    }
    final cats = <({String category, String routeId})>[];
    final catsRaw = json['route_categories'];
    if (catsRaw is List) {
      for (final c in catsRaw) {
        if (c is! Map) continue;
        final cat = c['category'] as String?;
        final id = c['route_id'] as String?;
        if (cat == null || id == null) continue;
        cats.add((category: cat, routeId: id));
      }
    }
    return EvaluationModel(
      EvaluationSummary(
        score: (json['score'] as num?)?.toDouble(),
        reasonCodes: _stringList(json['reason_codes']),
        recommendedRouteId: json['recommended_route_id'] as String?,
        ranked: ranked,
        routeCategories: cats,
      ),
    );
  }
}

class TopJourneyOptionModel {
  final TopJourneyOption entity;

  TopJourneyOptionModel(this.entity);

  factory TopJourneyOptionModel.fromJson(Map<String, dynamic> json) {
    final routeId = (json['route_id'] as String?) ?? '';
    final candidateId = (json['candidate_id'] as String?) ?? routeId;
    return TopJourneyOptionModel(
      TopJourneyOption(
        routeId: routeId,
        candidateId: candidateId,
        mode: (json['mode'] as String?) ?? 'unknown',
        modeSignature: (json['mode_signature'] as String?) ?? '',
        diversitySignature: (json['diversity_signature'] as String?) ?? '',
        componentModes: _stringList(json['component_modes']),
        duration: (json['duration'] as num?)?.toDouble(),
        cost: (json['cost'] as num?)?.toDouble(),
        costStatus: ValueStatus.fromWire(
          json['cost_status'] as String?,
          whenMissing: ValueStatus.known,
        ),
        durationStatus: ValueStatus.fromWire(
          json['duration_status'] as String?,
          whenMissing: ValueStatus.known,
        ),
        walkingDistanceMeters:
            (json['walking_distance_meters'] as num?)?.toDouble(),
        transfers: (json['transfers'] as num?)?.toInt() ?? 0,
        score: (json['score'] as num?)?.toDouble() ?? 0,
        rank: (json['rank'] as num?)?.toInt() ?? 0,
        strategyTier: (json['strategy_tier'] as num?)?.toInt() ?? 0,
        isRecommended: json['is_recommended'] == true,
        reason: (json['reason'] as String?) ?? '',
        backbone: (json['backbone'] as String?) ?? '',
        steps: _parseJourneySteps(json['steps']),
      ),
    );
  }
}

class TopJourneySelectionModel {
  final TopJourneySelection entity;

  TopJourneySelectionModel(this.entity);

  factory TopJourneySelectionModel.fromJson(Map<String, dynamic>? json) {
    if (json == null) {
      return TopJourneySelectionModel(const TopJourneySelection());
    }

    TopJourneyOption? recommended;
    final recRaw = json['recommended'];
    if (recRaw is Map) {
      recommended = TopJourneyOptionModel.fromJson(
        Map<String, dynamic>.from(recRaw),
      ).entity;
    }

    final alts = <TopJourneyOption>[];
    final altsRaw = json['alternatives'];
    if (altsRaw is List) {
      for (final raw in altsRaw) {
        if (raw is! Map) continue;
        alts.add(
          TopJourneyOptionModel.fromJson(Map<String, dynamic>.from(raw)).entity,
        );
      }
    }

    final top = <TopJourneyOption>[];
    final topRaw = json['top_journeys'];
    if (topRaw is List) {
      for (final raw in topRaw) {
        if (raw is! Map) continue;
        top.add(
          TopJourneyOptionModel.fromJson(Map<String, dynamic>.from(raw)).entity,
        );
      }
    }

    // Prefer flat list; otherwise reconstruct from recommended + alternatives.
    final journeys = top.isNotEmpty
        ? top
        : [
            if (recommended != null) recommended,
            ...alts,
          ];

    return TopJourneySelectionModel(
      TopJourneySelection(
        recommended: recommended ??
            (journeys.isNotEmpty
                ? journeys.firstWhere(
                    (o) => o.isRecommended,
                    orElse: () => journeys.first,
                  )
                : null),
        alternatives: alts.isNotEmpty
            ? alts
            : journeys.where((o) => !o.isRecommended).toList(),
        selectedCount:
            (json['selected_count'] as num?)?.toInt() ?? journeys.length,
        maxCount: (json['max_count'] as num?)?.toInt() ?? 5,
        topJourneys: journeys,
      ),
    );
  }

  /// Parse from either `top_selection` object or bare `top_journeys` list.
  static TopJourneySelection? parseFromPlanJson(Map<String, dynamic> json) {
    final selectionRaw = json['top_selection'];
    if (selectionRaw is Map) {
      final parsed = TopJourneySelectionModel.fromJson(
        Map<String, dynamic>.from(selectionRaw),
      ).entity;
      if (!parsed.isEmpty) return parsed;
    }

    final topRaw = json['top_journeys'];
    if (topRaw is List && topRaw.isNotEmpty) {
      final journeys = <TopJourneyOption>[];
      for (final raw in topRaw) {
        if (raw is! Map) continue;
        journeys.add(
          TopJourneyOptionModel.fromJson(Map<String, dynamic>.from(raw)).entity,
        );
      }
      if (journeys.isEmpty) return null;
      final recommended = journeys.firstWhere(
        (o) => o.isRecommended,
        orElse: () => journeys.first,
      );
      return TopJourneySelection(
        recommended: recommended,
        alternatives: journeys.where((o) => o.identity != recommended.identity).toList(),
        selectedCount: journeys.length,
        maxCount: 5,
        topJourneys: journeys,
      );
    }
    return null;
  }
}

class PlanResponseModel {
  final bool ok;
  final String? orchestration;
  final RouteModel? recommendation;
  final JourneyModel? recommendedJourney;
  final List<RouteModel> alternatives;
  final List<JourneyModel> journeys;
  final DecisionModel? decision;
  final EvaluationModel? evaluation;
  final String explanation;
  final List<String> reasons;
  final List<String> dataSources;
  final Map<String, dynamic>? provenance;
  final Map<String, dynamic>? historicalContext;
  final Map<String, dynamic>? weatherContext;
  final Map<String, dynamic>? metadata;
  final int? candidateCount;
  final List<String> warnings;
  final String? error;
  final String? errorDetail;
  final GeminiMetaModel gemini;
  final bool historicalSignalUsed;
  final List<({String category, String routeId})> categoryRefs;
  final TopJourneySelection? topSelection;

  PlanResponseModel({
    required this.ok,
    this.orchestration,
    required this.recommendation,
    this.recommendedJourney,
    required this.alternatives,
    this.journeys = const [],
    this.decision,
    this.evaluation,
    required this.explanation,
    required this.reasons,
    required this.dataSources,
    required this.provenance,
    this.historicalContext,
    this.weatherContext,
    this.metadata,
    this.candidateCount,
    required this.warnings,
    required this.error,
    required this.errorDetail,
    required this.gemini,
    required this.historicalSignalUsed,
    this.categoryRefs = const [],
    this.topSelection,
  });

  factory PlanResponseModel.fromJson(Map<String, dynamic> json) {
    final routes = json['routes'] as List<dynamic>?;
    final byId = <String, RouteModel>{};

    void indexRoute(RouteModel r) => byId[r.routeId] = r;

    if (routes != null) {
      for (final raw in routes) {
        if (raw is! Map) continue;
        final map = Map<String, dynamic>.from(raw);
        indexRoute(
          RouteModel.fromJson(
            map,
            distanceKmFallback: distanceKmForRouteId(
              map['route_id'] as String?,
              routes,
            ),
          ),
        );
      }
    }

    RouteModel? rec;
    final recJson = json['recommendation'];
    if (recJson is Map) {
      final map = Map<String, dynamic>.from(recJson);
      rec = RouteModel.fromJson(
        map,
        distanceKmFallback: distanceKmForRouteId(
          map['route_id'] as String?,
          routes,
        ),
      );
      indexRoute(rec);
    }

    final alts = <RouteModel>[];
    final altList = json['alternatives'];
    if (altList is List) {
      for (final a in altList) {
        if (a is! Map) continue;
        final map = Map<String, dynamic>.from(a);
        final model = RouteModel.fromJson(
          map,
          distanceKmFallback: distanceKmForRouteId(
            map['route_id'] as String?,
            routes,
          ),
        );
        alts.add(model);
        indexRoute(model);
      }
    }

    JourneyModel? recommendedJourney;
    final rj = json['recommended_journey'];
    if (rj is Map) {
      recommendedJourney =
          JourneyModel.fromJson(Map<String, dynamic>.from(rj));
    }

    final journeys = <JourneyModel>[];
    final journeysRaw = json['journeys'];
    if (journeysRaw is List) {
      for (final j in journeysRaw) {
        if (j is! Map) continue;
        journeys.add(JourneyModel.fromJson(Map<String, dynamic>.from(j)));
      }
    }

    DecisionModel? decision;
    if (json['decision'] is Map) {
      decision =
          DecisionModel.fromJson(Map<String, dynamic>.from(json['decision']));
    }

    EvaluationModel? evaluation;
    List<({String category, String routeId})> categoryRefs = const [];
    if (json['evaluation'] is Map) {
      final evalMap = Map<String, dynamic>.from(json['evaluation'] as Map);
      evaluation = EvaluationModel.fromJson(evalMap);
      categoryRefs = evaluation.entity.routeCategories;
    }

    final model = PlanResponseModel(
      ok: json['ok'] == true,
      orchestration: json['orchestration'] as String?,
      recommendation: rec,
      recommendedJourney: recommendedJourney,
      alternatives: alts,
      journeys: journeys,
      decision: decision,
      evaluation: evaluation,
      explanation: (json['explanation'] as String?) ?? '',
      reasons: _stringList(json['reasons']),
      dataSources: _stringList(json['data_sources']),
      provenance: _asStringKeyedMap(json['provenance']),
      historicalContext: _asStringKeyedMap(json['historical_context']),
      weatherContext: _asStringKeyedMap(json['weather_context']),
      metadata: _asStringKeyedMap(json['metadata']),
      candidateCount: (json['candidate_count'] as num?)?.toInt(),
      warnings: _stringList(json['warnings']),
      error: json['error'] as String?,
      errorDetail: json['error_detail'] as String?,
      gemini: GeminiMetaModel.fromJson(_asStringKeyedMap(json['gemini'])),
      historicalSignalUsed: json['historical_signal_used'] == true,
      categoryRefs: categoryRefs,
      topSelection: TopJourneySelectionModel.parseFromPlanJson(json),
    );
    model._routeIndex = byId;
    return model;
  }

  Map<String, RouteModel> _routeIndex = {};

  CommutePlan toEntity() {
    final categories = <RouteCategory>[];
    final seen = <String>{};
    for (final ref in categoryRefs) {
      if (ref.category == 'BEST_OVERALL') continue;
      final route = _routeIndex[ref.routeId];
      if (route == null) continue;
      if (seen.contains(route.routeId)) continue;
      if (recommendation?.routeId == route.routeId) continue;
      seen.add(route.routeId);
      categories.add(
        RouteCategory(category: ref.category, route: route.toEntity()),
      );
    }
    return CommutePlan(
      ok: ok,
      orchestration: orchestration,
      recommendation: recommendation?.toEntity(),
      recommendedJourney: recommendedJourney?.entity,
      alternatives: alternatives.map((a) => a.toEntity()).toList(),
      journeys: journeys.map((j) => j.entity).toList(),
      decision: decision?.entity,
      evaluation: evaluation?.entity,
      explanation: explanation,
      reasons: reasons,
      dataSources: dataSources,
      provenance: provenance,
      historicalContext: historicalContext,
      weatherContext: weatherContext,
      metadata: metadata,
      candidateCount: candidateCount,
      warnings: warnings,
      error: error,
      errorDetail: errorDetail,
      gemini: gemini.toEntity(),
      historicalSignalUsed: historicalSignalUsed,
      routeCategories: categories,
      topSelection: topSelection,
    );
  }
}

class ContextChangeModel {
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

  const ContextChangeModel({
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

  factory ContextChangeModel.fromEntity(ContextChange e) => ContextChangeModel(
        trafficChanged: e.trafficChanged,
        disruptionChanged: e.disruptionChanged,
        weatherChanged: e.weatherChanged,
        contextSource: e.contextSource,
        targetRouteId: e.targetRouteId,
        congestionDelta: e.congestionDelta,
        travelTimeDeltaMinutes: e.travelTimeDeltaMinutes,
        disruptionDelta: e.disruptionDelta,
        weatherNote: e.weatherNote,
        description: e.description,
        updatedDepartureTime: e.updatedDepartureTime,
      );

  factory ContextChangeModel.fromJson(Map<String, dynamic> json) {
    return ContextChangeModel(
      trafficChanged: json['traffic_changed'] == true,
      disruptionChanged: json['disruption_changed'] == true,
      weatherChanged: json['weather_changed'] == true,
      contextSource: (json['context_source'] as String?) ?? 'none',
      targetRouteId: json['target_route_id'] as String?,
      congestionDelta: (json['congestion_delta'] as num?)?.toDouble() ?? 0,
      travelTimeDeltaMinutes:
          (json['travel_time_delta_minutes'] as num?)?.toDouble() ?? 0,
      disruptionDelta: (json['disruption_delta'] as num?)?.toDouble() ?? 0,
      weatherNote: json['weather_note'] as String?,
      description: (json['description'] as String?) ?? '',
      updatedDepartureTime: json['updated_departure_time'] as String?,
    );
  }

  Map<String, dynamic> toJson() => {
        'traffic_changed': trafficChanged,
        'disruption_changed': disruptionChanged,
        'weather_changed': weatherChanged,
        'context_source': contextSource,
        if (targetRouteId != null) 'target_route_id': targetRouteId,
        'congestion_delta': congestionDelta,
        'travel_time_delta_minutes': travelTimeDeltaMinutes,
        'disruption_delta': disruptionDelta,
        if (weatherNote != null) 'weather_note': weatherNote,
        'description': description,
        if (updatedDepartureTime != null)
          'updated_departure_time': updatedDepartureTime,
      };

  ContextChange toEntity() => ContextChange(
        trafficChanged: trafficChanged,
        disruptionChanged: disruptionChanged,
        weatherChanged: weatherChanged,
        contextSource: contextSource,
        targetRouteId: targetRouteId,
        congestionDelta: congestionDelta,
        travelTimeDeltaMinutes: travelTimeDeltaMinutes,
        disruptionDelta: disruptionDelta,
        weatherNote: weatherNote,
        description: description,
        updatedDepartureTime: updatedDepartureTime,
      );
}

class ReplanResponseModel {
  final bool ok;
  final String? orchestration;
  final bool recommendationChanged;
  final String? previousRouteId;
  final String? newRouteId;
  final String? decision;
  final RouteModel? previousRecommendation;
  final RouteModel? newRecommendation;
  final ContextChangeModel? contextChange;
  final String explanation;
  final Map<String, dynamic>? before;
  final Map<String, dynamic>? after;
  final Map<String, dynamic>? reasons;
  final List<String> dataSources;
  final Map<String, dynamic>? provenance;
  final List<String> warnings;
  final String? error;
  final String? errorDetail;
  final GeminiMetaModel gemini;
  final String? planId;

  const ReplanResponseModel({
    required this.ok,
    this.orchestration,
    required this.recommendationChanged,
    required this.previousRouteId,
    required this.newRouteId,
    this.decision,
    required this.previousRecommendation,
    required this.newRecommendation,
    required this.contextChange,
    required this.explanation,
    required this.before,
    required this.after,
    required this.reasons,
    required this.dataSources,
    required this.provenance,
    required this.warnings,
    required this.error,
    required this.errorDetail,
    required this.gemini,
    this.planId,
  });

  factory ReplanResponseModel.fromJson(Map<String, dynamic> json) {
    RouteModel? prev;
    RouteModel? next;
    final p = json['previous_recommendation'];
    final n = json['new_recommendation'];
    if (p is Map) {
      prev = RouteModel.fromJson(Map<String, dynamic>.from(p));
    }
    if (n is Map) {
      next = RouteModel.fromJson(Map<String, dynamic>.from(n));
    }
    ContextChangeModel? ctx;
    if (json['context_change'] is Map) {
      ctx = ContextChangeModel.fromJson(
        Map<String, dynamic>.from(json['context_change'] as Map),
      );
    }
    return ReplanResponseModel(
      ok: json['ok'] == true,
      orchestration: json['orchestration'] as String?,
      recommendationChanged: json['recommendation_changed'] == true,
      previousRouteId: json['previous_route_id'] as String?,
      newRouteId: json['new_route_id'] as String?,
      decision: json['decision'] as String?,
      previousRecommendation: prev,
      newRecommendation: next,
      contextChange: ctx,
      explanation: (json['explanation'] as String?) ?? '',
      before: _asStringKeyedMap(json['before']),
      after: _asStringKeyedMap(json['after']),
      reasons: _asStringKeyedMap(json['reasons']),
      dataSources: _stringList(json['data_sources']),
      provenance: _asStringKeyedMap(json['provenance']),
      warnings: _stringList(json['warnings']),
      error: json['error'] as String?,
      errorDetail: json['error_detail'] as String?,
      gemini: GeminiMetaModel.fromJson(_asStringKeyedMap(json['gemini'])),
      planId: json['plan_id'] as String?,
    );
  }

  ReplanResult toEntity() => ReplanResult(
        ok: ok,
        recommendationChanged: recommendationChanged,
        previousRouteId: previousRouteId,
        newRouteId: newRouteId,
        previousRecommendation: previousRecommendation?.toEntity(),
        newRecommendation: newRecommendation?.toEntity(),
        contextChange: contextChange?.toEntity(),
        explanation: explanation,
        before: before,
        after: after,
        reasons: reasons,
        dataSources: dataSources,
        provenance: provenance,
        warnings: warnings,
        error: error,
        errorDetail: errorDetail,
        gemini: gemini.toEntity(),
      );
}
