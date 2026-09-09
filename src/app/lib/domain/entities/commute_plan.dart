import 'commute_route.dart';
import 'decision_summary.dart';
import 'gemini_meta.dart';
import 'journey.dart';
import 'route_category.dart';
import 'top_journey.dart';

/// Result of a plan attempt — mirrors backend `/plan` without raw JSON.
class CommutePlan {
  final bool ok;
  final String? orchestration;
  final CommuteRoute? recommendation;
  final RecommendedJourney? recommendedJourney;
  final List<CommuteRoute> alternatives;
  final List<RecommendedJourney> journeys;
  final DecisionSummary? decision;
  final EvaluationSummary? evaluation;
  final String explanation;
  final List<String> reasons;
  final List<String> dataSources;
  final Map<String, dynamic>? provenance;
  final Map<String, dynamic>? historicalContext;
  final Map<String, dynamic>? weatherContext;
  final Map<String, dynamic>? metadata;
  final int? candidateCount;
  final List<String> warnings;
  final String? error;
  final String? errorDetail;
  final GeminiMeta gemini;
  final bool historicalSignalUsed;
  final List<RouteCategory> routeCategories;
  /// Phase 7C/7D Top-5 selection (optional; missing ⇒ legacy recommendation UI).
  final TopJourneySelection? topSelection;

  const CommutePlan({
    required this.ok,
    this.orchestration,
    required this.recommendation,
    this.recommendedJourney,
    required this.alternatives,
    this.journeys = const [],
    this.decision,
    this.evaluation,
    required this.explanation,
    required this.reasons,
    required this.dataSources,
    required this.provenance,
    this.historicalContext,
    this.weatherContext,
    this.metadata,
    this.candidateCount,
    required this.warnings,
    required this.error,
    required this.errorDetail,
    required this.gemini,
    required this.historicalSignalUsed,
    this.routeCategories = const [],
    this.topSelection,
  });
}
