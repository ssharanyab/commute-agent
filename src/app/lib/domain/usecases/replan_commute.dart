import '../entities/context_change.dart';
import '../entities/replan_result.dart';
import '../repositories/commute_repository.dart';

class ReplanCommute {
  ReplanCommute(this._repository);

  final CommuteRepository _repository;

  Future<ReplanResult> call({
    required Map<String, dynamic> originalPlanRequest,
    required ContextChange contextChange,
    bool refreshLiveRoutes = false,
    bool invokeGemini = true,
  }) {
    return _repository.replanCommute(
      originalPlanRequest: originalPlanRequest,
      contextChange: contextChange,
      refreshLiveRoutes: refreshLiveRoutes,
      invokeGemini: invokeGemini,
    );
  }
}
