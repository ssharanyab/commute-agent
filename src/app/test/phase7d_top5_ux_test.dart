import 'package:commute_agent/data/models/commute_models.dart';
import 'package:commute_agent/domain/entities/commute_plan.dart';
import 'package:commute_agent/domain/entities/commute_route.dart';
import 'package:commute_agent/domain/entities/gemini_meta.dart';
import 'package:commute_agent/domain/entities/replan_result.dart';
import 'package:commute_agent/domain/entities/top_journey.dart';
import 'package:commute_agent/presentation/providers/commute_provider.dart';
import 'package:commute_agent/presentation/screens/results/result_page.dart';
import 'package:commute_agent/presentation/utils/labels.dart';
import 'package:commute_agent/presentation/utils/mode_presentation.dart';
import 'package:commute_agent/presentation/widgets/route_map.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

Map<String, dynamic> _topOptionJson({
  required String id,
  required List<String> modes,
  required bool recommended,
  String reason = 'Another option that fits your preferences',
  double? duration = 40,
  double? cost = 42,
  String costStatus = 'known',
  String durationStatus = 'known',
  double? walking = 320,
  int transfers = 0,
  int rank = 1,
}) {
  return {
    'route_id': id,
    'candidate_id': id,
    'mode': modes.length > 1 ? 'hybrid' : modes.first,
    'mode_signature': modes.join(' → '),
    'diversity_signature': modes.join('|'),
    'component_modes': modes,
    'duration': duration,
    'cost': cost,
    'cost_status': costStatus,
    'duration_status': durationStatus,
    'walking_distance_meters': walking,
    'transfers': transfers,
    'score': 90.0 - rank,
    'rank': rank,
    'strategy_tier': 0,
    'is_recommended': recommended,
    'reason': reason,
    'backbone': modes.contains('bus') || modes.contains('metro')
        ? 'public_transport'
        : 'road',
  };
}

CommutePlan _planWithTop(List<Map<String, dynamic>> top) {
  final json = {
    'ok': true,
    'orchestration': 'adk_mobility_orchestrator',
    'recommendation': {
      'route_id': top.first['route_id'],
      'mode': top.first['mode'],
      'travel_time_minutes': top.first['duration'] ?? 40,
      'cost': top.first['cost'] ?? 42,
      'cost_status': top.first['cost_status'] ?? 'known',
      'duration_status': top.first['duration_status'] ?? 'known',
      'walking_minutes': 4,
      'transfers': top.first['transfers'] ?? 0,
      'congestion_score': 0.2,
      'reliability_score': 0.9,
      'component_modes': top.first['component_modes'],
      'mode_signature': top.first['mode_signature'],
    },
    'alternatives': [],
    'journeys': [],
    'decision': {
      'recommended_route_id': top.first['route_id'],
      'authoritative': true,
      'ranked_route_ids': top.map((t) => t['route_id']).toList(),
      'reason_codes': ['FASTEST'],
      'scores': {},
      'category_assignments': {},
    },
    'explanation': 'Best match for your preferences',
    'reasons': ['FASTEST'],
    'data_sources': ['journey_builder'],
    'warnings': [],
    'error': null,
    'error_detail': null,
    'gemini': {
      'available': false,
      'invoked': false,
      'adk_invoked': false,
      'mode': 'deterministic_fallback',
    },
    'historical_signal_used': false,
    'top_journeys': top,
    'top_selection': {
      'recommended': top.first,
      'alternatives': top.skip(1).toList(),
      'selected_count': top.length,
      'max_count': 5,
      'top_journeys': top,
    },
  };
  return PlanResponseModel.fromJson(json).toEntity();
}

Widget _wrap(Widget child, CommuteProvider provider) {
  return ChangeNotifierProvider<CommuteProvider>.value(
    value: provider,
    child: MaterialApp(home: child),
  );
}

CommuteProvider _provider(CommutePlan plan) {
  final p = CommuteProvider();
  p.plan = plan;
  p.status = CommuteStatus.success;
  p.lastPlanRequest = {
    'origin': 'Electronic City, Bengaluru',
    'destination': 'Majestic, Bengaluru',
  };
  return p;
}

void main() {
  group('Phase 7D — TopJourney parsing', () {
    test('parses TopJourneyOption fields', () {
      final opt = TopJourneyOptionModel.fromJson(
        _topOptionJson(
          id: 'j1',
          modes: ['walk', 'metro', 'walk'],
          recommended: true,
          reason: 'Best match for your preferences',
        ),
      ).entity;
      expect(opt.routeId, 'j1');
      expect(opt.candidateId, 'j1');
      expect(opt.componentModes, ['walk', 'metro', 'walk']);
      expect(opt.diversitySignature, 'walk|metro|walk');
      expect(opt.isRecommended, isTrue);
      expect(opt.hasKnownCost, isTrue);
      expect(opt.hasKnownDuration, isTrue);
      expect(opt.hasKnownWalking, isTrue);
      expect(opt.reason, contains('Best match'));
    });

    test('parses TopJourneySelection and top_journeys', () {
      final plan = _planWithTop([
        _topOptionJson(id: 'a', modes: ['walk', 'metro', 'walk'], recommended: true, rank: 1),
        _topOptionJson(id: 'b', modes: ['walk', 'bus', 'walk'], recommended: false, rank: 2),
      ]);
      expect(plan.topSelection, isNotNull);
      expect(plan.topSelection!.selectedCount, 2);
      expect(plan.topSelection!.displayJourneys.length, 2);
      expect(plan.topSelection!.recommended!.routeId, 'a');
    });

    test('missing top_journeys is tolerated', () {
      final plan = PlanResponseModel.fromJson({
        'ok': true,
        'recommendation': {
          'route_id': 'r1',
          'mode': 'cab',
          'travel_time_minutes': 30,
          'cost': 100,
          'walking_minutes': 0,
          'transfers': 0,
          'congestion_score': 0.2,
          'reliability_score': 0.8,
        },
        'alternatives': [],
        'explanation': '',
        'reasons': [],
        'data_sources': [],
        'warnings': [],
        'error': null,
        'error_detail': null,
        'gemini': {},
        'historical_signal_used': false,
      }).toEntity();
      expect(plan.topSelection, isNull);
      expect(plan.recommendation?.routeId, 'r1');
    });

    test('empty top_journeys tolerated', () {
      final plan = PlanResponseModel.fromJson({
        'ok': true,
        'recommendation': {
          'route_id': 'r1',
          'mode': 'cab',
          'travel_time_minutes': 30,
          'cost': 100,
          'walking_minutes': 0,
          'transfers': 0,
          'congestion_score': 0.2,
          'reliability_score': 0.8,
        },
        'alternatives': [],
        'top_journeys': [],
        'top_selection': {
          'recommended': null,
          'alternatives': [],
          'selected_count': 0,
          'max_count': 5,
          'top_journeys': [],
        },
        'explanation': '',
        'reasons': [],
        'data_sources': [],
        'warnings': [],
        'error': null,
        'error_detail': null,
        'gemini': {},
        'historical_signal_used': false,
      }).toEntity();
      expect(plan.topSelection == null || plan.topSelection!.isEmpty, isTrue);
    });

    test('unknown cost/duration/walking statuses', () {
      final opt = TopJourneyOptionModel.fromJson(
        _topOptionJson(
          id: 'u',
          modes: ['cab'],
          recommended: true,
          cost: null,
          costStatus: 'unknown',
          duration: null,
          durationStatus: 'unknown',
          walking: null,
        ),
      ).entity;
      expect(opt.hasKnownCost, isFalse);
      expect(opt.hasKnownDuration, isFalse);
      expect(opt.hasKnownWalking, isFalse);
      expect(
        formatCostLabel(cost: opt.cost ?? 0, known: opt.hasKnownCost),
        'Fare unavailable',
      );
      expect(
        formatDurationLabel(
          travelTimeMinutes: opt.duration ?? 0,
          known: opt.hasKnownDuration,
        ),
        'Time unavailable',
      );
      expect(walkingMetricLabel(opt.walkingDistanceMeters), isNull);
    });
  });

  group('Phase 7D — mode presentation', () {
    test('human-readable sequences', () {
      final opt = TopJourneyOption(
        routeId: 'x',
        candidateId: 'x',
        mode: 'hybrid',
        componentModes: const ['walk', 'bus', 'metro', 'walk'],
      );
      final seq = modeSequenceForTopOption(opt);
      expect(seq, contains('Walk'));
      expect(seq, contains('Bus'));
      expect(seq, contains('Metro'));
      expect(seq, isNot(contains('walk|bus')));
    });

    test('maps handoff uses selected modes', () {
      final transit = TopJourneyOption(
        routeId: 't',
        candidateId: 't',
        mode: 'hybrid',
        componentModes: const ['walk', 'metro', 'walk'],
      );
      final road = TopJourneyOption(
        routeId: 'r',
        candidateId: 'r',
        mode: 'cab',
        componentModes: const ['cab'],
      );
      expect(mapsTravelModeForTopOption(transit), 'transit');
      expect(mapsTravelModeForTopOption(road), 'driving');
      final uri = googleMapsDirectionsUri(
        origin: 'Electronic City, Bengaluru',
        destination: 'Majestic, Bengaluru',
        travelMode: mapsTravelModeForTopOption(transit),
      );
      expect(uri.toString(), contains('origin=Electronic%20City'));
      expect(uri.toString(), contains('destination=Majestic'));
      expect(uri.toString(), contains('travelmode=transit'));
    });
  });

  group('Phase 7D — ResultPage Top-5 UX', () {
    Future<void> pump(WidgetTester tester, CommuteProvider provider) async {
      await tester.binding.setSurfaceSize(const Size(400, 2000));
      addTearDown(() async {
        await tester.binding.setSurfaceSize(null);
      });
      await tester.pumpWidget(
        _wrap(const ResultPage(apiBaseUrl: 'http://test'), provider),
      );
      await tester.pump();
    }

    testWidgets('recommended renders; alternatives when present', (tester) async {
      final plan = _planWithTop([
        _topOptionJson(
          id: 'rec',
          modes: ['walk', 'metro', 'walk'],
          recommended: true,
          reason: 'Best match for your preferences',
          rank: 1,
        ),
        _topOptionJson(
          id: 'alt1',
          modes: ['walk', 'bus', 'walk'],
          recommended: false,
          reason: 'Lowest-cost option',
          cost: 20,
          duration: 55,
          rank: 2,
        ),
        _topOptionJson(
          id: 'alt2',
          modes: ['cab'],
          recommended: false,
          reason: 'Direct road journey',
          duration: 35,
          cost: null,
          costStatus: 'unknown',
          walking: null,
          rank: 3,
        ),
      ]);
      await pump(tester, _provider(plan));
      expect(find.text('Best for you'), findsOneWidget);
      expect(find.byKey(const Key('hero_recommendation')), findsOneWidget);
      expect(find.text('Other ways to go'), findsOneWidget);
      expect(find.byKey(const Key('alt_card_alt1')), findsOneWidget);
      expect(find.byKey(const Key('alt_card_alt2')), findsOneWidget);
      expect(find.text('Best match for your preferences'), findsOneWidget);
      expect(find.text('Lowest-cost option'), findsOneWidget);
      expect(find.text('Direct road journey'), findsOneWidget);
      expect(find.textContaining('score'), findsNothing);
      expect(find.textContaining('strategy_tier'), findsNothing);
      expect(find.text('rec'), findsNothing);
    });

    testWidgets('one journey hides alternatives section', (tester) async {
      final plan = _planWithTop([
        _topOptionJson(
          id: 'only',
          modes: ['walk', 'metro', 'walk'],
          recommended: true,
          reason: 'Best match for your preferences',
        ),
      ]);
      await pump(tester, _provider(plan));
      expect(find.text('Other ways to go'), findsNothing);
      expect(find.byKey(const Key('hero_recommendation')), findsOneWidget);
    });

    testWidgets('five journeys render without crash; cap excess', (tester) async {
      final top = List.generate(
        6,
        (i) => _topOptionJson(
          id: 'j$i',
          modes: i == 0
              ? ['walk', 'metro', 'walk']
              : i == 1
                  ? ['walk', 'bus', 'walk']
                  : i == 2
                      ? ['auto', 'metro', 'walk']
                      : i == 3
                          ? ['cab']
                          : i == 4
                              ? ['walk', 'bus', 'metro', 'walk']
                              : ['auto'],
          recommended: i == 0,
          rank: i + 1,
          reason: i == 0
              ? 'Best match for your preferences'
              : 'Another option that fits your preferences',
        ),
      );
      final plan = _planWithTop(top);
      expect(plan.topSelection!.displayJourneys.length, 5);
      await pump(tester, _provider(plan));
      expect(find.text('Other ways to go'), findsOneWidget);
      expect(find.byType(RouteMap), findsNothing);
    });

    testWidgets('unknown cost does not show ₹0', (tester) async {
      final plan = _planWithTop([
        _topOptionJson(
          id: 'u',
          modes: ['cab'],
          recommended: true,
          cost: 0,
          costStatus: 'unknown',
          duration: 40,
          walking: null,
          reason: 'Best match for your preferences',
        ),
      ]);
      await pump(tester, _provider(plan));
      expect(find.textContaining('Fare unavailable'), findsOneWidget);
      expect(find.text('₹0'), findsNothing);
    });

    testWidgets('tapping alternative selects it visually', (tester) async {
      final plan = _planWithTop([
        _topOptionJson(
          id: 'rec',
          modes: ['walk', 'metro', 'walk'],
          recommended: true,
          reason: 'Best match for your preferences',
        ),
        _topOptionJson(
          id: 'alt',
          modes: ['cab'],
          recommended: false,
          reason: 'Direct road journey',
          duration: 32,
        ),
      ]);
      final provider = _provider(plan);
      await pump(tester, provider);
      await tester.tap(find.byKey(const Key('alt_card_alt')));
      await tester.pump();
      expect(find.text('Selected'), findsOneWidget);
      // Recommendation identity unchanged in plan.
      expect(provider.plan!.recommendation!.routeId, 'rec');
      expect(provider.plan!.topSelection!.recommended!.routeId, 'rec');
    });

    testWidgets('replan clears stale selection to new recommendation',
        (tester) async {
      final plan = _planWithTop([
        _topOptionJson(
          id: 'old',
          modes: ['walk', 'metro', 'walk'],
          recommended: true,
          reason: 'Best match for your preferences',
        ),
        _topOptionJson(
          id: 'alt',
          modes: ['cab'],
          recommended: false,
          reason: 'Direct road journey',
        ),
      ]);
      final provider = _provider(plan);
      await pump(tester, provider);
      await tester.tap(find.byKey(const Key('alt_card_alt')));
      await tester.pump();
      expect(find.text('Selected'), findsOneWidget);

      provider.replanResult = ReplanResult(
        ok: true,
        recommendationChanged: true,
        previousRouteId: 'old',
        newRouteId: 'old',
        previousRecommendation: plan.recommendation,
        newRecommendation: CommuteRoute(
          routeId: 'old',
          mode: 'hybrid',
          travelTimeMinutes: 40,
          cost: 42,
          walkingMinutes: 4,
          transfers: 0,
          congestionScore: 0.2,
          reliabilityScore: 0.9,
          componentModes: const ['walk', 'metro', 'walk'],
        ),
        contextChange: null,
        explanation: 'Updated',
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
          mode: 'deterministic_fallback',
        ),
      );
      provider.notifyListeners();
      await tester.pump();
      await tester.pump(); // post-frame selection reset
      expect(find.text('Selected'), findsNothing);
    });

    testWidgets('CTA present and maps URI encodes OD', (tester) async {
      final plan = _planWithTop([
        _topOptionJson(
          id: 'rec',
          modes: ['walk', 'metro', 'walk'],
          recommended: true,
          reason: 'Best match for your preferences',
        ),
      ]);
      await pump(tester, _provider(plan));
      expect(find.byKey(const Key('maps_handoff')), findsOneWidget);
      expect(find.text('Take this journey'), findsOneWidget);
      final btn = tester.widget<FilledButton>(
        find.byKey(const Key('maps_handoff')),
      );
      expect(btn.onPressed, isNotNull);
    });
  });

  group('Phase 7D — display helpers', () {
    test('displayReason falls back safely', () {
      expect(displayReason(null), 'Another option');
      expect(displayReason(''), 'Another option');
      expect(displayReason('Lower cost'), 'Lower cost');
    });
  });
}
