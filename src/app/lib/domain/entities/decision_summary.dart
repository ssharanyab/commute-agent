/// Authoritative Decision Engine summary from `/plan` (`decision` object).
class DecisionSummary {
  final String? recommendedRouteId;
  final List<String> rankedRouteIds;
  final Map<String, String> categoryAssignments;
  final Map<String, double> scores;
  final List<String> reasonCodes;
  final bool authoritative;

  const DecisionSummary({
    this.recommendedRouteId,
    this.rankedRouteIds = const [],
    this.categoryAssignments = const {},
    this.scores = const {},
    this.reasonCodes = const [],
    this.authoritative = true,
  });
}

/// Compact evaluation payload used by Flutter (not raw DE internals).
class EvaluationSummary {
  final double? score;
  final List<String> reasonCodes;
  final String? recommendedRouteId;
  final List<RankedEvaluationEntry> ranked;
  final List<({String category, String routeId})> routeCategories;

  const EvaluationSummary({
    this.score,
    this.reasonCodes = const [],
    this.recommendedRouteId,
    this.ranked = const [],
    this.routeCategories = const [],
  });
}

class RankedEvaluationEntry {
  final String routeId;
  final double finalScore;
  final bool isValid;
  final List<String> reasonCodes;
  final String? costStatus;
  final String? durationStatus;
  final String? modeSignature;

  const RankedEvaluationEntry({
    required this.routeId,
    required this.finalScore,
    this.isValid = true,
    this.reasonCodes = const [],
    this.costStatus,
    this.durationStatus,
    this.modeSignature,
  });
}
