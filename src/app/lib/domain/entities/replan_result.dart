import 'commute_route.dart';
import 'context_change.dart';
import 'gemini_meta.dart';

class ReplanResult {
  final bool ok;
  final bool recommendationChanged;
  final String? previousRouteId;
  final String? newRouteId;
  final CommuteRoute? previousRecommendation;
  final CommuteRoute? newRecommendation;
  final ContextChange? contextChange;
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

  const ReplanResult({
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
}
