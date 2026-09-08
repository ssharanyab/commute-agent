import '../../domain/entities/commute_plan.dart';
import '../../domain/entities/commute_request.dart';
import '../../domain/entities/context_change.dart';
import '../../domain/entities/replan_result.dart';
import '../../domain/repositories/commute_repository.dart';
import '../datasources/commute_remote_data_source.dart';
import '../models/commute_models.dart';

class CommuteRepositoryImpl implements CommuteRepository {
  CommuteRepositoryImpl({
    required String baseUrl,
    CommuteRemoteDataSource? dataSource,
  }) : _dataSource = dataSource ?? CommuteRemoteDataSource(baseUrl: baseUrl);

  final CommuteRemoteDataSource _dataSource;

  @override
  Future<CommutePlan> planCommute(CommuteRequest request) async {
    final body = _planBody(request);
    final model = await _dataSource.plan(body);
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
    final model = await _dataSource.replan(payload);
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
      'departure_time': request.departureTimeIso8601,
      'invoke_gemini': request.invokeGemini,
      'preferences': preferences,
    };
  }

  void close() => _dataSource.close();
}
