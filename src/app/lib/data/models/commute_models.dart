import '../../domain/entities/commute_plan.dart';
import '../../domain/entities/commute_route.dart';
import '../../domain/entities/context_change.dart';
import '../../domain/entities/gemini_meta.dart';
import '../../domain/entities/historical_signal.dart';
import '../../domain/entities/replan_result.dart';
import '../../domain/entities/route_category.dart';

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

class RouteModel {
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

  const RouteModel({
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

  factory RouteModel.fromJson(
    Map<String, dynamic> json, {
    double? distanceKmFallback,
  }) {
    final meters = (json['distance_meters'] as num?)?.toInt();
    final distanceKm = meters != null ? meters / 1000.0 : distanceKmFallback;
    return RouteModel(
      routeId: (json['route_id'] as String?) ?? 'unknown',
      mode: (json['mode'] as String?) ?? 'unknown',
      travelTimeMinutes: (json['travel_time_minutes'] as num?)?.toDouble() ?? 0,
      cost: (json['cost'] as num?)?.toDouble() ?? 0,
      walkingMinutes: (json['walking_minutes'] as num?)?.toDouble() ?? 0,
      transfers: (json['transfers'] as num?)?.toInt() ?? 0,
      congestionScore: (json['congestion_score'] as num?)?.toDouble() ?? 0,
      reliabilityScore: (json['reliability_score'] as num?)?.toDouble() ?? 0,
      distanceKm: distanceKm,
      distanceMeters: meters,
      googlePolyline: (json['google_polyline'] as String?) ??
          (json['googlePolyline'] as String?),
      googleRouteToken: (json['google_route_token'] as String?) ??
          (json['googleRouteToken'] as String?),
      historicalSignal: _parseHistorical(
        json['historical_mobility_signal'] ?? json['historicalMobilitySignal'],
      ),
    );
  }

  CommuteRoute toEntity() => CommuteRoute(
        routeId: routeId,
        mode: mode,
        travelTimeMinutes: travelTimeMinutes,
        cost: cost,
        walkingMinutes: walkingMinutes,
        transfers: transfers,
        congestionScore: congestionScore,
        reliabilityScore: reliabilityScore,
        distanceKm: distanceKm,
        distanceMeters: distanceMeters,
        googlePolyline: googlePolyline,
        googleRouteToken: googleRouteToken,
        historicalSignal: historicalSignal,
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

class PlanResponseModel {
  final bool ok;
  final RouteModel? recommendation;
  final List<RouteModel> alternatives;
  final String explanation;
  final List<String> reasons;
  final List<String> dataSources;
  final Map<String, dynamic>? provenance;
  final List<String> warnings;
  final String? error;
  final String? errorDetail;
  final GeminiMetaModel gemini;
  final bool historicalSignalUsed;
  final List<({String category, String routeId})> categoryRefs;

  PlanResponseModel({
    required this.ok,
    required this.recommendation,
    required this.alternatives,
    required this.explanation,
    required this.reasons,
    required this.dataSources,
    required this.provenance,
    required this.warnings,
    required this.error,
    required this.errorDetail,
    required this.gemini,
    required this.historicalSignalUsed,
    this.categoryRefs = const [],
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

    final categoryRefs = <({String category, String routeId})>[];
    final evaluation = json['evaluation'];
    if (evaluation is Map) {
      final cats = evaluation['route_categories'];
      if (cats is List) {
        for (final c in cats) {
          if (c is! Map) continue;
          final cat = c['category'] as String?;
          final id = c['route_id'] as String?;
          if (cat == null || id == null) continue;
          categoryRefs.add((category: cat, routeId: id));
        }
      }
    }

    final model = PlanResponseModel(
      ok: json['ok'] == true,
      recommendation: rec,
      alternatives: alts,
      explanation: (json['explanation'] as String?) ?? '',
      reasons:
          (json['reasons'] as List?)?.map((e) => '$e').toList() ?? const [],
      dataSources:
          (json['data_sources'] as List?)?.map((e) => '$e').toList() ??
          const [],
      provenance: json['provenance'] is Map
          ? Map<String, dynamic>.from(json['provenance'] as Map)
          : null,
      warnings:
          (json['warnings'] as List?)?.map((e) => '$e').toList() ?? const [],
      error: json['error'] as String?,
      errorDetail: json['error_detail'] as String?,
      gemini: GeminiMetaModel.fromJson(
        json['gemini'] is Map
            ? Map<String, dynamic>.from(json['gemini'] as Map)
            : null,
      ),
      historicalSignalUsed: json['historical_signal_used'] == true,
      categoryRefs: categoryRefs,
    );
    model._routeIndex = byId;
    return model;
  }

  /// Filled during fromJson for category resolution.
  Map<String, RouteModel> _routeIndex = {};

  CommutePlan toEntity() {
    final categories = <RouteCategory>[];
    final seen = <String>{};
    for (final ref in categoryRefs) {
      if (ref.category == 'BEST_OVERALL') continue;
      final route = _routeIndex[ref.routeId];
      if (route == null) continue;
      if (seen.contains(route.routeId)) continue;
      // Skip if same as recommendation (avoid duplicate cards)
      if (recommendation?.routeId == route.routeId) continue;
      seen.add(route.routeId);
      categories.add(
        RouteCategory(category: ref.category, route: route.toEntity()),
      );
    }
    return CommutePlan(
      ok: ok,
      recommendation: recommendation?.toEntity(),
      alternatives: alternatives.map((a) => a.toEntity()).toList(),
      explanation: explanation,
      reasons: reasons,
      dataSources: dataSources,
      provenance: provenance,
      warnings: warnings,
      error: error,
      errorDetail: errorDetail,
      gemini: gemini.toEntity(),
      historicalSignalUsed: historicalSignalUsed,
      routeCategories: categories,
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
  final bool recommendationChanged;
  final String? previousRouteId;
  final String? newRouteId;
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

  const ReplanResponseModel({
    required this.ok,
    required this.recommendationChanged,
    required this.previousRouteId,
    required this.newRouteId,
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
      recommendationChanged: json['recommendation_changed'] == true,
      previousRouteId: json['previous_route_id'] as String?,
      newRouteId: json['new_route_id'] as String?,
      previousRecommendation: prev,
      newRecommendation: next,
      contextChange: ctx,
      explanation: (json['explanation'] as String?) ?? '',
      before:
          json['before'] is Map
              ? Map<String, dynamic>.from(json['before'] as Map)
              : null,
      after:
          json['after'] is Map
              ? Map<String, dynamic>.from(json['after'] as Map)
              : null,
      reasons:
          json['reasons'] is Map
              ? Map<String, dynamic>.from(json['reasons'] as Map)
              : null,
      dataSources:
          (json['data_sources'] as List?)?.map((e) => '$e').toList() ??
          const [],
      provenance:
          json['provenance'] is Map
              ? Map<String, dynamic>.from(json['provenance'] as Map)
              : null,
      warnings:
          (json['warnings'] as List?)?.map((e) => '$e').toList() ?? const [],
      error: json['error'] as String?,
      errorDetail: json['error_detail'] as String?,
      gemini: GeminiMetaModel.fromJson(
        json['gemini'] is Map
            ? Map<String, dynamic>.from(json['gemini'] as Map)
            : null,
      ),
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
