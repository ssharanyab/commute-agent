import 'package:commute_agent/domain/entities/commute_plan.dart';
import 'package:commute_agent/domain/entities/commute_route.dart';
import 'package:commute_agent/domain/entities/decision_summary.dart';
import 'package:commute_agent/domain/entities/gemini_meta.dart';
import 'package:commute_agent/domain/entities/journey.dart';
import 'package:commute_agent/domain/entities/journey_leg.dart';
import 'package:commute_agent/domain/entities/replan_result.dart';
import 'package:commute_agent/domain/entities/route_category.dart';
import 'package:commute_agent/domain/entities/value_status.dart';
import 'package:commute_agent/presentation/providers/commute_provider.dart';
import 'package:commute_agent/presentation/screens/results/result_page.dart';
import 'package:commute_agent/presentation/utils/labels.dart';
import 'package:commute_agent/presentation/utils/mode_presentation.dart';
import 'package:commute_agent/presentation/utils/user_facing_explanation.dart';
import 'package:commute_agent/presentation/widgets/journey_timeline.dart';
import 'package:commute_agent/presentation/widgets/route_map.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

JourneyLeg _leg({
  required int index,
  required String mode,
  double? durationSeconds,
  ValueStatus durationStatus = ValueStatus.known,
  double? distanceMeters,
  double? costInr,
  ValueStatus costStatus = ValueStatus.known,
}) {
  return JourneyLeg(
    index: index,
    mode: mode,
    fromNodeId: 'a$index',
    toNodeId: 'b$index',
    edgeId: 'e$index',
    edgeKind: 'ride',
    durationSeconds: durationSeconds,
    durationStatus: durationStatus,
    distanceMeters: distanceMeters,
    costInr: costInr,
    costStatus: costStatus,
  );
}

CommutePlan _multimodalPlan({
  ValueStatus costStatus = ValueStatus.known,
  double cost = 42,
  ValueStatus durationStatus = ValueStatus.known,
  double minutes = 48,
}) {
  final journey = RecommendedJourney(
    candidateId: 'j_winner',
    modes: const ['walk', 'bus', 'metro', 'walk'],
    modeSignature: 'walk → bus → metro → walk',
    costStatus: costStatus,
    durationStatus: durationStatus,
    totalCostInr: costStatus == ValueStatus.known ? cost : null,
    totalDurationSeconds: durationStatus == ValueStatus.known ? minutes * 60 : null,
    transferCount: 1,
    walkingDistanceMeters: 320,
    legs: [
      _leg(index: 0, mode: 'walk', durationSeconds: 180, distanceMeters: 180),
      _leg(index: 1, mode: 'bus', durationSeconds: 18 * 60, costInr: 20),
      _leg(index: 2, mode: 'metro', durationSeconds: 21 * 60, costInr: 22),
      _leg(index: 3, mode: 'walk', durationSeconds: 60, distanceMeters: 50),
    ],
  );
  final route = CommuteRoute(
    routeId: 'j_winner',
    mode: 'hybrid',
    travelTimeMinutes: minutes,
    cost: cost,
    costStatus: costStatus,
    durationStatus: durationStatus,
    walkingMinutes: 4,
    transfers: 1,
    congestionScore: 0.2,
    reliabilityScore: 0.9,
    componentModes: const ['walk', 'bus', 'metro', 'walk'],
    modeSignature: 'walk → bus → metro → walk',
    googlePolyline: 'POLY',
    googleRouteToken: 'TOK',
  );
  return CommutePlan(
    ok: true,
    orchestration: 'adk_mobility_orchestrator',
    recommendation: route,
    recommendedJourney: journey,
    alternatives: const [],
    journeys: [journey],
    decision: const DecisionSummary(
      recommendedRouteId: 'j_winner',
      authoritative: true,
    ),
    explanation: 'Backend explanation for this journey.',
    reasons: const ['FASTEST', 'LOW_WALKING'],
    dataSources: const ['journey_builder'],
    provenance: null,
    warnings: const [],
    error: null,
    errorDetail: null,
    gemini: const GeminiMeta(
      available: false,
      invoked: false,
      adkInvoked: false,
      mode: 'deterministic_fallback',
    ),
    historicalSignalUsed: false,
    routeCategories: [
      RouteCategory(
        category: 'CHEAPEST',
        route: CommuteRoute(
          routeId: 'j_alt',
          mode: 'bus',
          travelTimeMinutes: 55,
          cost: 30,
          walkingMinutes: 8,
          transfers: 0,
          congestionScore: 0.3,
          reliabilityScore: 0.8,
          componentModes: const ['bus'],
          modeSignature: 'bus',
        ),
      ),
    ],
  );
}

Widget _wrap(Widget child, CommuteProvider provider) {
  return ChangeNotifierProvider<CommuteProvider>.value(
    value: provider,
    child: MaterialApp(home: child),
  );
}

void main() {
  group('Phase 6G.2 presentation helpers', () {
    test('mode sequence is dynamic from backend modes', () {
      expect(
        modeSequenceFromModes(['walk', 'bmtc', 'metro', 'walk']),
        contains('🚌'),
      );
      expect(
        modeSequenceFromModes(['walk', 'bmtc', 'metro', 'walk']),
        contains('🚇'),
      );
      expect(
        modeSequenceFromSignature('auto → bus → walk → metro → auto'),
        contains('🛺'),
      );
    });

    test('unknown cost never shows Free or ₹0', () {
      expect(
        formatCostLabel(cost: 0, known: false),
        'Fare unavailable',
      );
      expect(formatCostLabel(cost: 0, known: false), isNot(contains('₹0')));
      expect(formatCostLabel(cost: 0, known: false), isNot(contains('Free')));
    });

    test('unknown duration uses approximate when value present', () {
      expect(
        formatDurationLabel(travelTimeMinutes: 48, known: false),
        '~48 min',
      );
      expect(
        formatDurationLabel(travelTimeMinutes: 0, known: false),
        'Time unavailable',
      );
    });
  });

  group('Phase 6G.2 result UX', () {
    testWidgets('renders multimodal recommendation from authoritative journey',
        (tester) async {
      final provider = CommuteProvider()
        ..status = CommuteStatus.success
        ..plan = _multimodalPlan()
        ..lastPlanRequest = {
          'origin': 'Electronic City, Bengaluru',
          'destination': 'Majestic, Bengaluru',
        };
      await tester.binding.setSurfaceSize(const Size(390, 900));
      addTearDown(() async {
        await tester.binding.setSurfaceSize(null);
      });
      await tester.pumpWidget(
        _wrap(const ResultPage(apiBaseUrl: 'http://test'), provider),
      );

      expect(find.text('Best for you'), findsOneWidget);
      expect(find.byKey(const Key('mode_sequence')), findsOneWidget);
      expect(find.textContaining('Walk'), findsWidgets);
      expect(find.textContaining('Bus'), findsWidgets);
      expect(find.textContaining('Metro'), findsWidgets);
      expect(find.text('Your journey'), findsOneWidget);
      expect(find.byType(JourneyTimeline), findsOneWidget);
      expect(find.text('Why this?'), findsOneWidget);
      expect(find.text('Backend explanation for this journey.'), findsOneWidget);
      expect(find.textContaining('Other ways to go'), findsOneWidget);
      expect(find.textContaining('Lower cost'), findsOneWidget);
      expect(find.byType(RouteMap), findsNothing);
      expect(provider.plan?.recommendation?.googlePolyline, 'POLY');
      expect(provider.plan?.recommendation?.googleRouteToken, 'TOK');
      await tester.scrollUntilVisible(
        find.byKey(const Key('maps_handoff')),
        200,
      );
      expect(find.text('Take this journey'), findsOneWidget);
    });

    testWidgets('unknown cost shows Fare unavailable', (tester) async {
      final provider = CommuteProvider()
        ..status = CommuteStatus.success
        ..plan = _multimodalPlan(costStatus: ValueStatus.unknown, cost: 0)
        ..lastPlanRequest = {'origin': 'A', 'destination': 'B'};
      await tester.binding.setSurfaceSize(const Size(390, 900));
      addTearDown(() async {
        await tester.binding.setSurfaceSize(null);
      });
      await tester.pumpWidget(
        _wrap(const ResultPage(apiBaseUrl: 'http://test'), provider),
      );
      expect(find.textContaining('Fare unavailable'), findsWidgets);
      expect(find.text('₹0'), findsNothing);
      expect(find.text('Free'), findsNothing);
    });

    testWidgets('unknown duration communicates uncertainty', (tester) async {
      final provider = CommuteProvider()
        ..status = CommuteStatus.success
        ..plan = _multimodalPlan(
          durationStatus: ValueStatus.unknown,
          minutes: 48,
        )
        ..lastPlanRequest = {'origin': 'A', 'destination': 'B'};
      await tester.binding.setSurfaceSize(const Size(390, 900));
      addTearDown(() async {
        await tester.binding.setSurfaceSize(null);
      });
      await tester.pumpWidget(
        _wrap(const ResultPage(apiBaseUrl: 'http://test'), provider),
      );
      expect(find.textContaining('~48 min'), findsWidgets);
    });

    testWidgets('replan changed banner renders', (tester) async {
      final provider = CommuteProvider()
        ..status = CommuteStatus.success
        ..plan = _multimodalPlan()
        ..lastPlanRequest = {'origin': 'A', 'destination': 'B'}
        ..replanStatus = CommuteStatus.success
        ..replanResult = ReplanResult(
          ok: true,
          recommendationChanged: true,
          previousRouteId: 'j_winner',
          newRouteId: 'j_alt',
          previousRecommendation: _multimodalPlan().recommendation,
          newRecommendation: _multimodalPlan().routeCategories.first.route,
          contextChange: null,
          explanation: 'Traffic worsened on the previous option.',
          before: null,
          after: null,
          reasons: null,
          dataSources: const [],
          provenance: null,
          warnings: const [],
          error: null,
          errorDetail: null,
          gemini: const GeminiMeta(
            available: false,
            invoked: false,
            adkInvoked: false,
            mode: 'x',
          ),
        );
      await tester.binding.setSurfaceSize(const Size(390, 900));
      addTearDown(() async {
        await tester.binding.setSurfaceSize(null);
      });
      await tester.pumpWidget(
        _wrap(const ResultPage(apiBaseUrl: 'http://test'), provider),
      );
      expect(find.byKey(const Key('replan_banner')), findsOneWidget);
      expect(find.text('Your commute changed'), findsOneWidget);
    });

    testWidgets('narrow layout does not overflow', (tester) async {
      final provider = CommuteProvider()
        ..status = CommuteStatus.success
        ..plan = _multimodalPlan()
        ..lastPlanRequest = {'origin': 'A', 'destination': 'B'};
      await tester.binding.setSurfaceSize(const Size(320, 700));
      addTearDown(() async {
        await tester.binding.setSurfaceSize(null);
      });
      await tester.pumpWidget(
        _wrap(const ResultPage(apiBaseUrl: 'http://test'), provider),
      );
      expect(tester.takeException(), isNull);
      expect(find.byKey(const Key('hero_recommendation')), findsOneWidget);
    });
  });

  group('Phase 6G.2 user-facing explanation', () {
    test('strips technical deterministic explanation', () {
      final why = buildUserFacingExplanation(
        rawExplanation:
            'Deterministic Decision Engine selected journey j_8ed2506dea77 '
            '(score=100.0) as BEST_OVERALL. Candidates considered: 20. '
            'Gemini unavailable — deterministic fallback',
        reasonCodes: const [],
        recommended: _multimodalPlan().recommendation,
        peers: comparisonRoutesFor(_multimodalPlan()),
      );
      expect(why.summary, kDefaultWhySummary);
      expect(why.summary.toLowerCase(), isNot(contains('gemini')));
      expect(why.summary.toLowerCase(), isNot(contains('score=')));
      expect(why.summary.toLowerCase(), isNot(contains('best_overall')));
      expect(why.summary, isNot(contains('j_8ed2506dea77')));
      expect(why.summary.toLowerCase(), isNot(contains('candidates considered')));
      expect(why.summary.toLowerCase(), isNot(contains('deterministic')));
    });

    test('unknown cost cannot produce lower-cost claim', () {
      final rec = CommuteRoute(
        routeId: 'a',
        mode: 'bus',
        travelTimeMinutes: 40,
        cost: 0,
        costStatus: ValueStatus.unknown,
        walkingMinutes: 5,
        transfers: 0,
        congestionScore: 0.2,
        reliabilityScore: 0.8,
      );
      final peer = CommuteRoute(
        routeId: 'b',
        mode: 'cab',
        travelTimeMinutes: 30,
        cost: 200,
        costStatus: ValueStatus.known,
        walkingMinutes: 0,
        transfers: 0,
        congestionScore: 0.4,
        reliabilityScore: 0.7,
      );
      final why = buildUserFacingExplanation(
        rawExplanation: '',
        reasonCodes: const ['LOW_COST'],
        recommended: rec,
        peers: [rec, peer],
      );
      expect(
        why.reasons.any(
          (r) =>
              r.toLowerCase().contains('cost') ||
              r.toLowerCase().contains('fare') ||
              r.toLowerCase().contains('cheaper'),
        ),
        isFalse,
      );
      expect(
        alternativeCategoryTitle(
          category: 'CHEAPEST',
          route: peer,
          recommended: rec,
        ),
        'Another option',
      );
    });

    test('omits fastest when duration unknown', () {
      final why = buildUserFacingExplanation(
        rawExplanation: '',
        reasonCodes: const ['FASTEST'],
        recommended: _multimodalPlan(
          durationStatus: ValueStatus.unknown,
          minutes: 48,
        ).recommendation,
        peers: comparisonRoutesFor(_multimodalPlan()),
      );
      expect(why.reasons, isEmpty);
    });

    test('keeps friendly backend prose and verified reasons', () {
      final plan = _multimodalPlan();
      final why = explanationForPlan(plan);
      expect(why.summary, 'Backend explanation for this journey.');
      expect(why.reasons, contains('Faster than other known options'));
      expect(why.reasons, contains('Less walking'));
    });

    testWidgets('result page never shows debug internals', (tester) async {
      final dirty = _multimodalPlan();
      final plan = CommutePlan(
        ok: dirty.ok,
        orchestration: dirty.orchestration,
        recommendation: dirty.recommendation,
        recommendedJourney: dirty.recommendedJourney,
        alternatives: dirty.alternatives,
        journeys: dirty.journeys,
        decision: dirty.decision,
        explanation:
            'Deterministic Decision Engine selected journey j_winner '
            '(score=93.8) as BEST_OVERALL. Candidates considered: 20. '
            'Gemini unavailable — deterministic fallback',
        reasons: const ['LOW_COST'],
        dataSources: dirty.dataSources,
        provenance: dirty.provenance,
        warnings: dirty.warnings,
        error: dirty.error,
        errorDetail: dirty.errorDetail,
        gemini: dirty.gemini,
        historicalSignalUsed: dirty.historicalSignalUsed,
        routeCategories: [
          RouteCategory(
            category: 'CHEAPEST',
            route: CommuteRoute(
              routeId: 'j_cab',
              mode: 'cab',
              travelTimeMinutes: 40,
              cost: 0,
              costStatus: ValueStatus.unknown,
              walkingMinutes: 0,
              transfers: 0,
              congestionScore: 0.5,
              reliabilityScore: 0.5,
            ),
          ),
        ],
      );
      // Recommended cost known 42; peer cost unknown → no lower-cost claim.
      final provider = CommuteProvider()
        ..status = CommuteStatus.success
        ..plan = plan
        ..lastPlanRequest = {'origin': 'A', 'destination': 'B'};
      await tester.binding.setSurfaceSize(const Size(390, 900));
      addTearDown(() async {
        await tester.binding.setSurfaceSize(null);
      });
      await tester.pumpWidget(
        _wrap(const ResultPage(apiBaseUrl: 'http://test'), provider),
      );

      expect(find.textContaining('Gemini'), findsNothing);
      expect(find.textContaining('Gemini unavailable'), findsNothing);
      expect(find.textContaining('deterministic'), findsNothing);
      expect(find.textContaining('Deterministic'), findsNothing);
      expect(find.textContaining('BEST_OVERALL'), findsNothing);
      expect(find.textContaining('score='), findsNothing);
      expect(find.textContaining('j_winner'), findsNothing);
      expect(find.textContaining('Candidates considered'), findsNothing);
      expect(find.textContaining('Decision Engine'), findsNothing);
      expect(find.text(kDefaultWhySummary), findsOneWidget);
      expect(find.textContaining('Lower cost'), findsNothing);
      expect(find.text('Another option'), findsOneWidget);
      await tester.scrollUntilVisible(
        find.byKey(const Key('maps_handoff')),
        200,
      );
      expect(find.text('Take this journey'), findsOneWidget);
      expect(find.byType(RouteMap), findsNothing);
    });
  });
}
