import '../entities/commute_plan.dart';
import '../entities/commute_request.dart';
import '../repositories/commute_repository.dart';

class PlanCommute {
  PlanCommute(this._repository);

  final CommuteRepository _repository;

  Future<CommutePlan> call(CommuteRequest request) {
    return _repository.planCommute(request);
  }
}
