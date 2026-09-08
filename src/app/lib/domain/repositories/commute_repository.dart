import '../entities/commute_plan.dart';
import '../entities/commute_request.dart';
import '../entities/context_change.dart';
import '../entities/replan_result.dart';

abstract class CommuteRepository {
  Future<CommutePlan> planCommute(CommuteRequest request);

  Future<ReplanResult> replanCommute({
    required Map<String, dynamic> originalPlanRequest,
    required ContextChange contextChange,
    bool refreshLiveRoutes = false,
    bool invokeGemini = true,
  });
}
