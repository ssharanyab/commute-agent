import 'commute_route.dart';
import 'gemini_meta.dart';
import 'route_category.dart';

/// Result of a successful or unsuccessful plan attempt.
class CommutePlan {
  final bool ok;
  final CommuteRoute? recommendation;
  final List<CommuteRoute> alternatives;
  final String explanation;
  final List<String> reasons;
  final List<String> dataSources;
  final Map<String, dynamic>? provenance;
  final List<String> warnings;
  final String? error;
  final String? errorDetail;
  final GeminiMeta gemini;
  final bool historicalSignalUsed;
  final List<RouteCategory> routeCategories;

  const CommutePlan({
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
    this.routeCategories = const [],
  });
}
