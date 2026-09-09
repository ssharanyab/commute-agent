import '../../domain/entities/commute_plan.dart';
import '../../domain/entities/commute_route.dart';
import '../../domain/entities/route_category.dart';

/// Neutral summary when no safe, data-grounded copy is available.
const String kDefaultWhySummary =
    'Commute Agent selected this journey because it best matches your preferences.';

/// User-facing "Why this?" content — never includes debug/engine internals.
class UserFacingExplanation {
  final String summary;
  final List<String> reasons;

  const UserFacingExplanation({
    required this.summary,
    this.reasons = const [],
  });
}

/// True when backend explanation text is developer/debug copy.
bool isTechnicalExplanation(String? raw) {
  final text = (raw ?? '').trim();
  if (text.isEmpty) return true;

  final lower = text.toLowerCase();
  const markers = [
    'deterministic decision engine',
    'decision engine',
    'best_overall',
    'candidates considered',
    'gemini unavailable',
    'deterministic fallback',
    'gemini',
    'orchestration',
    'journey builder',
    'adk',
    'final_score',
    'candidate_count',
    'ranked_route',
  ];
  for (final m in markers) {
    if (lower.contains(m)) return true;
  }
  if (RegExp(r'score\s*=\s*\d').hasMatch(lower)) return true;
  if (RegExp(r'\bj_[a-z0-9]{4,}\b', caseSensitive: false).hasMatch(text)) {
    return true;
  }
  if (RegExp(r'\broute_id\b', caseSensitive: false).hasMatch(text)) {
    return true;
  }
  return false;
}

/// Sanitize replan/plan prose; returns null when nothing user-safe remains.
String? safeProseExplanation(String? raw) {
  final text = (raw ?? '').trim();
  if (text.isEmpty || isTechnicalExplanation(text)) return null;
  return text;
}

List<CommuteRoute> comparisonRoutesFor(CommutePlan plan) {
  final byId = <String, CommuteRoute>{};
  void add(CommuteRoute? r) {
    if (r == null || r.routeId.isEmpty) return;
    byId.putIfAbsent(r.routeId, () => r);
  }

  add(plan.recommendation);
  for (final a in plan.alternatives) {
    add(a);
  }
  for (final c in plan.routeCategories) {
    add(c.route);
  }
  return byId.values.toList();
}

/// Build a data-grounded explanation without Flutter route ranking.
UserFacingExplanation buildUserFacingExplanation({
  required String? rawExplanation,
  required List<String> reasonCodes,
  required CommuteRoute? recommended,
  required List<CommuteRoute> peers,
}) {
  final summary = safeProseExplanation(rawExplanation) ?? kDefaultWhySummary;
  if (recommended == null) {
    return UserFacingExplanation(summary: summary);
  }

  final others =
      peers.where((r) => r.routeId != recommended.routeId).toList(growable: false);
  final codes = reasonCodes
      .map((c) => c.trim().toUpperCase())
      .where((c) => c.isNotEmpty && c != 'CONSTRAINT_VIOLATION')
      .toList();

  final reasons = <String>[];
  final seen = <String>{};

  void addReason(String text) {
    if (text.isEmpty || seen.contains(text)) return;
    seen.add(text);
    reasons.add(text);
  }

  for (final code in codes) {
    final label = _verifiedReasonLabel(
      code: code,
      recommended: recommended,
      others: others,
    );
    if (label != null) addReason(label);
  }

  return UserFacingExplanation(summary: summary, reasons: reasons);
}

String? _verifiedReasonLabel({
  required String code,
  required CommuteRoute recommended,
  required List<CommuteRoute> others,
}) {
  if (others.isEmpty && _isComparativeReason(code)) {
    return null;
  }

  switch (code) {
    case 'FASTEST':
      if (!recommended.hasKnownDuration) return null;
      final known = others.where((r) => r.hasKnownDuration).toList();
      if (known.isEmpty) return null;
      final minOther = known
          .map((r) => r.travelTimeMinutes)
          .reduce((a, b) => a < b ? a : b);
      if (recommended.travelTimeMinutes < minOther) {
        return 'Faster than other known options';
      }
      if (recommended.travelTimeMinutes == minOther) {
        return 'Among the quickest options';
      }
      return null;

    case 'LOW_COST':
      if (!recommended.hasKnownCost) return null;
      final known = others.where((r) => r.hasKnownCost).toList();
      if (known.isEmpty) return null;
      final minOther = known.map((r) => r.cost).reduce((a, b) => a < b ? a : b);
      if (recommended.cost < minOther) {
        return 'Lower fare than other options with known prices';
      }
      if (recommended.cost == minOther) {
        return 'Among the lower-fare options';
      }
      return null;

    case 'LOW_WALKING':
      final moreWalk = others.any(
        (r) => r.walkingMinutes > recommended.walkingMinutes,
      );
      if (!moreWalk) return null;
      return 'Less walking';

    case 'FEWER_TRANSFERS':
      final moreXfer = others.any((r) => r.transfers > recommended.transfers);
      if (!moreXfer) return null;
      return 'Fewer transfers';

    case 'LOW_CONGESTION':
      final worse = others.any(
        (r) => r.congestionScore > recommended.congestionScore,
      );
      if (!worse) return null;
      return 'Lower traffic exposure';

    case 'HIGH_RELIABILITY':
      final lessReliable = others.any(
        (r) => r.reliabilityScore < recommended.reliabilityScore,
      );
      if (!lessReliable) return null;
      if (recommended.reliabilityScore < 0.8) return null;
      return 'More reliable';

    case 'HISTORICALLY_STABLE':
      return 'Historically stable travel time';

    case 'CURRENTLY_NEAR_TYPICAL':
      return 'Near typical travel time right now';

    case 'CURRENTLY_ABOVE_TYPICAL':
      return 'Currently a bit above usual travel time';

    case 'HISTORICAL_SUPPORT':
      return 'Supported by historical travel patterns';

    case 'PREFERRED_MODE':
      return 'Fits your preferred mode';

    default:
      // Unknown comparative codes: omit rather than echo backend enums.
      return null;
  }
}

bool _isComparativeReason(String code) {
  switch (code) {
    case 'FASTEST':
    case 'LOW_COST':
    case 'LOW_WALKING':
    case 'FEWER_TRANSFERS':
    case 'LOW_CONGESTION':
    case 'HIGH_RELIABILITY':
      return true;
    default:
      return false;
  }
}

/// Safe title for an alternative category tile. Never invents unsupported claims.
String alternativeCategoryTitle({
  required String category,
  required CommuteRoute route,
  required CommuteRoute? recommended,
}) {
  switch (category.toUpperCase()) {
    case 'BEST_OVERALL':
      return 'Another option';
    case 'FASTEST':
      if (!route.hasKnownDuration) return 'Another option';
      if (recommended != null &&
          recommended.hasKnownDuration &&
          route.travelTimeMinutes > recommended.travelTimeMinutes) {
        return 'Another option';
      }
      return '⚡ Fastest';
    case 'CHEAPEST':
      if (!route.hasKnownCost) return 'Another option';
      if (recommended == null || !recommended.hasKnownCost) {
        return 'Another option';
      }
      if (route.cost > recommended.cost) return 'Another option';
      return '💰 Lower cost';
    case 'MOST_RELIABLE':
      if (recommended != null &&
          route.reliabilityScore < recommended.reliabilityScore) {
        return 'Another option';
      }
      return '🛡️ More reliable';
    case 'LOW_WALKING':
      if (recommended != null &&
          route.walkingMinutes > recommended.walkingMinutes) {
        return 'Another option';
      }
      return '🚶 Less walking';
    default:
      final cleaned = category.replaceAll('_', ' ').trim();
      if (cleaned.isEmpty) return 'Another option';
      // Avoid dumping raw enums that look technical.
      if (RegExp(r'^[A-Z0-9_]+$').hasMatch(category) &&
          category.contains('_')) {
        return 'Another option';
      }
      return cleaned[0].toUpperCase() + cleaned.substring(1).toLowerCase();
  }
}

/// Convenience for ResultPage.
UserFacingExplanation explanationForPlan(CommutePlan plan) {
  return buildUserFacingExplanation(
    rawExplanation: plan.explanation,
    reasonCodes: plan.reasons.isNotEmpty
        ? plan.reasons
        : (plan.decision?.reasonCodes ??
            plan.evaluation?.reasonCodes ??
            const []),
    recommended: plan.recommendation,
    peers: comparisonRoutesFor(plan),
  );
}

String? safeReplanExplanation(String? raw) => safeProseExplanation(raw);

/// Visible alternatives with safe titles (presentation only).
List<({String title, CommuteRoute route})> visibleAlternatives({
  required List<RouteCategory> categories,
  required CommuteRoute? recommended,
}) {
  return categories
      .map(
        (c) => (
          title: alternativeCategoryTitle(
            category: c.category,
            route: c.route,
            recommended: recommended,
          ),
          route: c.route,
        ),
      )
      .toList(growable: false);
}
