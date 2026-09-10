import 'package:flutter/foundation.dart';

import '../../core/errors/api_exception.dart';
import '../../data/repositories/commute_repository_impl.dart';
import '../../domain/entities/commute_plan.dart';
import '../../domain/entities/commute_request.dart';
import '../../domain/entities/context_change.dart';
import '../../domain/entities/replan_result.dart';
import '../../domain/usecases/plan_commute.dart';
import '../../domain/usecases/replan_commute.dart';

enum CommuteStatus { idle, loading, success, error }

class CommuteProvider extends ChangeNotifier {
  CommuteStatus status = CommuteStatus.idle;
  CommuteStatus replanStatus = CommuteStatus.idle;

  CommutePlan? plan;
  ReplanResult? replanResult;
  Map<String, dynamic>? lastPlanRequest;

  String? errorTitle;
  String? errorDetail;
  String? replanError;

  bool get isLoading => status == CommuteStatus.loading;
  bool get isReplanLoading => replanStatus == CommuteStatus.loading;

  Future<bool> planCommute({
    required String baseUrl,
    required CommuteRequest request,
  }) async {
    errorTitle = null;
    errorDetail = null;
    replanResult = null;
    replanError = null;
    status = CommuteStatus.loading;
    notifyListeners();

    final repo = CommuteRepositoryImpl(baseUrl: baseUrl);
    try {
      lastPlanRequest = repo.buildPlanRequestBody(request);
      final result = await PlanCommute(repo)(request);
      if (!result.ok || result.error != null) {
        plan = null;
        status = CommuteStatus.error;
        errorTitle = "Couldn't plan this commute";
        errorDetail = humanizePlanFailure(result);
        notifyListeners();
        return false;
      }
      plan = result;
      status = CommuteStatus.success;
      notifyListeners();
      return true;
    } on ApiException catch (e) {
      plan = null;
      status = CommuteStatus.error;
      errorTitle = e.kind == ApiErrorKind.network
          ? "Couldn't reach GoWise."
          : "Couldn't plan this commute";
      errorDetail = e.kind == ApiErrorKind.network
          ? 'Could not connect to $baseUrl\n${e.message}'
          : e.message;
      notifyListeners();
      return false;
    } catch (e) {
      plan = null;
      status = CommuteStatus.error;
      errorTitle = "Couldn't reach GoWise.";
      errorDetail = 'Could not connect to $baseUrl\n$e';
      notifyListeners();
      return false;
    } finally {
      repo.close();
    }
  }

  Future<void> replanCommute({
    required String baseUrl,
    required ContextChange contextChange,
    bool refreshLiveRoutes = false,
  }) async {
    final requestBody = lastPlanRequest;
    if (requestBody == null) {
      replanStatus = CommuteStatus.error;
      replanError = 'Missing original plan request for replan.';
      notifyListeners();
      return;
    }

    replanStatus = CommuteStatus.loading;
    replanError = null;
    notifyListeners();

    final repo = CommuteRepositoryImpl(baseUrl: baseUrl);
    try {
      final result = await ReplanCommute(repo)(
        originalPlanRequest: requestBody,
        contextChange: contextChange,
        refreshLiveRoutes: refreshLiveRoutes,
      );
      replanResult = result;
      replanStatus = CommuteStatus.success;
      if (!result.ok && result.error != null) {
        replanError = '${result.error} ${result.errorDetail ?? ''}'.trim();
        replanStatus = CommuteStatus.error;
      }
      notifyListeners();
    } on ApiException catch (e) {
      replanStatus = CommuteStatus.error;
      replanError = e.message;
      notifyListeners();
    } catch (e) {
      replanStatus = CommuteStatus.error;
      replanError = 'Replan failed: $e';
      notifyListeners();
    } finally {
      repo.close();
    }
  }

  void setConfigurationError(String title, String detail) {
    errorTitle = title;
    errorDetail = detail;
    status = CommuteStatus.error;
    notifyListeners();
  }

  @visibleForTesting
  static String humanizePlanFailure(CommutePlan plan) {
    final detail = (plan.errorDetail ?? '').trim();
    final code = plan.error ?? '';
    if (code == 'MAPS_API_UNAVAILABLE') {
      if (detail.toLowerCase().contains('timestamp') ||
          detail.toLowerCase().contains('future')) {
        return 'Google Maps rejected the departure time. '
            'Choose a future time and try again.'
            '${detail.isEmpty ? '' : '\n\n$detail'}';
      }
      return 'Google Maps could not return routes.'
          '${detail.isEmpty ? '' : '\n\n$detail'}';
    }
    if (code == 'NO_ROUTES') {
      return 'No routes were found for this commute.'
          '${detail.isEmpty ? '' : '\n\n$detail'}';
    }
    if (code == 'NO_VALID_ROUTES') {
      return 'No route matches your current constraints.'
          '${detail.isEmpty ? '' : '\n\n$detail'}';
    }
    if (code == 'COORDINATES_UNRESOLVED') {
      return 'Could not resolve origin or destination.'
          '${detail.isEmpty ? '' : '\n\n$detail'}';
    }
    if (code == 'NO_FEASIBLE_JOURNEY' || code == 'NO_CANDIDATES') {
      return 'No feasible journey was found for this commute.'
          '${detail.isEmpty ? '' : '\n\n$detail'}';
    }
    if (code.isNotEmpty) {
      return detail.isNotEmpty ? '$code\n\n$detail' : code;
    }
    return detail.isNotEmpty
        ? detail
        : 'The API returned an unsuccessful plan.';
  }
}
