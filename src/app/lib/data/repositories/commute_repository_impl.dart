import '../../domain/entities/commute_plan.dart';
import '../../domain/entities/commute_request.dart';
import '../../domain/entities/context_change.dart';
import '../../domain/entities/replan_result.dart';
import '../../domain/repositories/commute_repository.dart';
import '../datasources/commute_api_client.dart';
import '../models/commute_models.dart';

class CommuteRepositoryImpl implements CommuteRepository {
  CommuteRepositoryImpl({
    required String baseUrl,
    CommuteApiClient? dataSource,
    CommuteRemoteDataSource? remoteDataSource,
  }) : _client = dataSource ??
            remoteDataSource ??
            CommuteApiClient(baseUrl: baseUrl);

  final CommuteApiClient _client;

  @override
  Future<CommutePlan> planCommute(CommuteRequest request) async {
    final body = _planBody(request);
    final model = await _client.plan(body);
    return model.toEntity();
  }

  @override
  Future<ReplanResult> replanCommute({
    required Map<String, dynamic> originalPlanRequest,
    required ContextChange contextChange,
    bool refreshLiveRoutes = false,
    bool invokeGemini = true,
  }) async {
    final payload = {
      'request': originalPlanRequest,
      'context_change': ContextChangeModel.fromEntity(contextChange).toJson(),
      'refresh_live_routes': refreshLiveRoutes,
      'invoke_gemini': invokeGemini,
    };
    final model = await _client.replan(payload);
    return model.toEntity();
  }

  /// Public so the presentation layer can persist the exact request body for replan.
  Map<String, dynamic> buildPlanRequestBody(CommuteRequest request) =>
      _planBody(request);

  Map<String, dynamic> _planBody(CommuteRequest request) {
    final prefs = request.preferences;
    final preferences = <String, dynamic>{
      'avoid_heavy_traffic': prefs.avoidHeavyTraffic,
      if (prefs.maxWalkingMinutes != null)
        'max_walking_minutes': prefs.maxWalkingMinutes,
      if (prefs.maxCost != null) 'max_cost': prefs.maxCost,
      if (prefs.excludedModes.isNotEmpty) 'excluded_modes': prefs.excludedModes,
      if (prefs.timeWeight != null) 'time_weight': prefs.timeWeight,
      if (prefs.costWeight != null) 'cost_weight': prefs.costWeight,
      if (prefs.walkingWeight != null) 'walking_weight': prefs.walkingWeight,
      if (prefs.transferWeight != null) 'transfer_weight': prefs.transferWeight,
      if (prefs.congestionWeight != null)
        'congestion_weight': prefs.congestionWeight,
      if (prefs.reliabilityWeight != null)
        'reliability_weight': prefs.reliabilityWeight,
    };
    return {
      'origin': request.origin,
      'destination': request.destination,
      if (request.departureTimeIso8601 != null)
        'departure_time': request.departureTimeIso8601,
      'user_id': request.userId,
      if (request.objective != null) 'objective': request.objective,
      if (request.preferenceProfile != null)
        'preference_profile': request.preferenceProfile,
      if (request.originZone != null) 'origin_zone': request.originZone,
      if (request.destinationZone != null)
        'destination_zone': request.destinationZone,
      if (request.originLat != null) 'origin_lat': request.originLat,
      if (request.originLon != null) 'origin_lon': request.originLon,
      if (request.destinationLat != null)
        'destination_lat': request.destinationLat,
      if (request.destinationLon != null)
        'destination_lon': request.destinationLon,
      if (request.originEndpoint != null)
        'origin_endpoint': request.originEndpoint,
      if (request.destinationEndpoint != null)
        'destination_endpoint': request.destinationEndpoint,
      if (request.modes != null) 'modes': request.modes,
      'invoke_gemini': request.invokeGemini,
      'invoke_weather': request.invokeWeather,
      'invoke_historical': request.invokeHistorical,
      if (request.invokeLiveTraffic != null)
        'invoke_live_traffic': request.invokeLiveTraffic,
      'allow_legacy_maps_fallback': request.allowLegacyMapsFallback,
      'preferences': preferences,
    };
  }

  void close() => _client.close();
}
