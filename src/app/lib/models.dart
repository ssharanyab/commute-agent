// Typed models mirroring FastAPI /plan and /replan JSON (display-only).

class GeminiMeta {
  final bool available;
  final bool invoked;
  final bool adkInvoked;
  final String mode;

  const GeminiMeta({
    required this.available,
    required this.invoked,
    required this.adkInvoked,
    required this.mode,
  });

  factory GeminiMeta.fromJson(Map<String, dynamic>? json) {
    if (json == null) {
      return const GeminiMeta(
        available: false,
        invoked: false,
        adkInvoked: false,
        mode: 'unknown',
      );
    }
    return GeminiMeta(
      available: json['available'] == true,
      invoked: json['invoked'] == true,
      adkInvoked: json['adk_invoked'] == true,
      mode: (json['mode'] as String?) ?? 'unknown',
    );
  }

  String get statusLabel {
    if (invoked) return 'Gemini ($mode)';
    if (!available) return 'Gemini unavailable — deterministic fallback';
    return 'Deterministic fallback ($mode)';
  }
}

class RouteSummary {
  final String routeId;
  final String mode;
  final double travelTimeMinutes;
  final double cost;
  final double walkingMinutes;
  final int transfers;
  final double congestionScore;
  final double reliabilityScore;
  final double? distanceKm;

  const RouteSummary({
    required this.routeId,
    required this.mode,
    required this.travelTimeMinutes,
    required this.cost,
    required this.walkingMinutes,
    required this.transfers,
    required this.congestionScore,
    required this.reliabilityScore,
    this.distanceKm,
  });

  factory RouteSummary.fromJson(
    Map<String, dynamic> json, {
    double? distanceKm,
  }) {
    return RouteSummary(
      routeId: (json['route_id'] as String?) ?? 'unknown',
      mode: (json['mode'] as String?) ?? 'unknown',
      travelTimeMinutes: (json['travel_time_minutes'] as num?)?.toDouble() ?? 0,
      cost: (json['cost'] as num?)?.toDouble() ?? 0,
      walkingMinutes: (json['walking_minutes'] as num?)?.toDouble() ?? 0,
      transfers: (json['transfers'] as num?)?.toInt() ?? 0,
      congestionScore: (json['congestion_score'] as num?)?.toDouble() ?? 0,
      reliabilityScore: (json['reliability_score'] as num?)?.toDouble() ?? 0,
      distanceKm: distanceKm,
    );
  }
}

double? _distanceKmForRouteId(
  String? routeId,
  List<dynamic>? mapsRoutes,
) {
  if (routeId == null || mapsRoutes == null) return null;
  // route_id pattern: maps_<mode>_<index> e.g. maps_drive_0
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

class PlanResponse {
  final bool ok;
  final RouteSummary? recommendation;
  final List<RouteSummary> alternatives;
  final String explanation;
  final List<String> reasons;
  final List<String> dataSources;
  final Map<String, dynamic>? provenance;
  final List<String> warnings;
  final String? error;
  final String? errorDetail;
  final GeminiMeta gemini;
  final bool historicalSignalUsed;

  const PlanResponse({
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
  });

  factory PlanResponse.fromJson(Map<String, dynamic> json) {
    final routes = json['routes'] as List<dynamic>?;
    RouteSummary? rec;
    final recJson = json['recommendation'];
    if (recJson is Map) {
      final map = Map<String, dynamic>.from(recJson);
      rec = RouteSummary.fromJson(
        map,
        distanceKm: _distanceKmForRouteId(map['route_id'] as String?, routes),
      );
    }
    final alts = <RouteSummary>[];
    final altList = json['alternatives'];
    if (altList is List) {
      for (final a in altList) {
        if (a is! Map) continue;
        final map = Map<String, dynamic>.from(a);
        alts.add(
          RouteSummary.fromJson(
            map,
            distanceKm: _distanceKmForRouteId(map['route_id'] as String?, routes),
          ),
        );
      }
    }
    return PlanResponse(
      ok: json['ok'] == true,
      recommendation: rec,
      alternatives: alts,
      explanation: (json['explanation'] as String?) ?? '',
      reasons: (json['reasons'] as List?)?.map((e) => '$e').toList() ?? const [],
      dataSources:
          (json['data_sources'] as List?)?.map((e) => '$e').toList() ?? const [],
      provenance: json['provenance'] is Map
          ? Map<String, dynamic>.from(json['provenance'] as Map)
          : null,
      warnings:
          (json['warnings'] as List?)?.map((e) => '$e').toList() ?? const [],
      error: json['error'] as String?,
      errorDetail: json['error_detail'] as String?,
      gemini: GeminiMeta.fromJson(
        json['gemini'] is Map
            ? Map<String, dynamic>.from(json['gemini'] as Map)
            : null,
      ),
      historicalSignalUsed: json['historical_signal_used'] == true,
    );
  }
}

class ContextChangePayload {
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

  const ContextChangePayload({
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

  factory ContextChangePayload.fromJson(Map<String, dynamic> json) {
    return ContextChangePayload(
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
}

class ReplanResponse {
  final bool ok;
  final bool recommendationChanged;
  final String? previousRouteId;
  final String? newRouteId;
  final RouteSummary? previousRecommendation;
  final RouteSummary? newRecommendation;
  final ContextChangePayload? contextChange;
  final String explanation;
  final Map<String, dynamic>? before;
  final Map<String, dynamic>? after;
  final Map<String, dynamic>? reasons;
  final List<String> dataSources;
  final Map<String, dynamic>? provenance;
  final List<String> warnings;
  final String? error;
  final String? errorDetail;
  final GeminiMeta gemini;

  const ReplanResponse({
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

  factory ReplanResponse.fromJson(Map<String, dynamic> json) {
    RouteSummary? prev;
    RouteSummary? next;
    final p = json['previous_recommendation'];
    final n = json['new_recommendation'];
    if (p is Map) {
      prev = RouteSummary.fromJson(Map<String, dynamic>.from(p));
    }
    if (n is Map) {
      next = RouteSummary.fromJson(Map<String, dynamic>.from(n));
    }
    ContextChangePayload? ctx;
    if (json['context_change'] is Map) {
      ctx = ContextChangePayload.fromJson(
        Map<String, dynamic>.from(json['context_change'] as Map),
      );
    }
    return ReplanResponse(
      ok: json['ok'] == true,
      recommendationChanged: json['recommendation_changed'] == true,
      previousRouteId: json['previous_route_id'] as String?,
      newRouteId: json['new_route_id'] as String?,
      previousRecommendation: prev,
      newRecommendation: next,
      contextChange: ctx,
      explanation: (json['explanation'] as String?) ?? '',
      before: json['before'] is Map
          ? Map<String, dynamic>.from(json['before'] as Map)
          : null,
      after: json['after'] is Map
          ? Map<String, dynamic>.from(json['after'] as Map)
          : null,
      reasons: json['reasons'] is Map
          ? Map<String, dynamic>.from(json['reasons'] as Map)
          : null,
      dataSources:
          (json['data_sources'] as List?)?.map((e) => '$e').toList() ?? const [],
      provenance: json['provenance'] is Map
          ? Map<String, dynamic>.from(json['provenance'] as Map)
          : null,
      warnings:
          (json['warnings'] as List?)?.map((e) => '$e').toList() ?? const [],
      error: json['error'] as String?,
      errorDetail: json['error_detail'] as String?,
      gemini: GeminiMeta.fromJson(
        json['gemini'] is Map
            ? Map<String, dynamic>.from(json['gemini'] as Map)
            : null,
      ),
    );
  }
}

class ApiException implements Exception {
  final int? statusCode;
  final String message;
  final String? errorCode;
  final Map<String, dynamic>? body;

  ApiException({
    required this.message,
    this.statusCode,
    this.errorCode,
    this.body,
  });

  @override
  String toString() => message;
}
