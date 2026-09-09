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
        'Duration unavailable',
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

      expect(find.text('BEST FOR YOU'), findsOneWidget);
      expect(find.byKey(const Key('mode_sequence')), findsOneWidget);
      expect(find.textContaining('Walk'), findsWidgets);
      expect(find.textContaining('Bus'), findsWidgets);
      expect(find.textContaining('Metro'), findsWidgets);
      expect(find.text('YOUR JOURNEY'), findsOneWidget);
      expect(find.byType(JourneyTimeline), findsOneWidget);
      expect(find.text('WHY THIS?'), findsOneWidget);
      expect(find.text('Backend explanation for this journey.'), findsOneWidget);
      expect(find.textContaining('OTHER OPTIONS'), findsOneWidget);
      expect(find.textContaining('Lower cost'), findsOneWidget);
      expect(find.byType(RouteMap), findsNothing);
      expect(provider.plan?.recommendation?.googlePolyline, 'POLY');
      expect(provider.plan?.recommendation?.googleRouteToken, 'TOK');
      await tester.scrollUntilVisible(
        find.byKey(const Key('maps_handoff')),
        200,
      );
      expect(find.text('Open in Google Maps'), findsOneWidget);
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
      expect(find.text('Fare unavailable'), findsWidgets);
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
}
