import 'package:commute_agent/data/models/commute_models.dart';
import 'package:commute_agent/domain/entities/commute_plan.dart';
import 'package:commute_agent/presentation/providers/commute_provider.dart';
import 'package:commute_agent/presentation/screens/results/result_page.dart';
import 'package:commute_agent/presentation/utils/mode_presentation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

Map<String, dynamic> _step({
  required String type,
  required String instruction,
  String? mode,
  String? fromMode,
  String? toMode,
  String? location,
}) {
  return {
    'type': type,
    'instruction': instruction,
    if (mode != null) 'mode': mode,
    if (fromMode != null) 'from_mode': fromMode,
    if (toMode != null) 'to_mode': toMode,
    if (location != null) 'location_name': location,
  };
}

Map<String, dynamic> _topOptionJson({
  required String id,
  required List<String> modes,
  required bool recommended,
  String reason = 'Another option that fits your preferences',
  List<Map<String, dynamic>> steps = const [],
  double? duration = 40,
  double? cost = 42,
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
    'cost_status': 'known',
    'duration_status': 'known',
    'walking_distance_meters': 320,
    'transfers': 0,
    'score': 90.0 - rank,
    'rank': rank,
    'strategy_tier': 0,
    'is_recommended': recommended,
    'reason': reason,
    'backbone': 'public_transport',
    'steps': steps,
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
      'cost_status': 'known',
      'duration_status': 'known',
      'walking_minutes': 4,
      'transfers': 0,
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
    'explanation': 'Deterministic explanation.',
    'reasons': ['FASTEST'],
    'data_sources': ['network'],
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
  group('Phase 7G — JourneyStep parsing', () {
    test('parses LEG and TRANSFER steps', () {
      final opt = TopJourneyOptionModel.fromJson(
        _topOptionJson(
          id: 'x',
          modes: ['bus', 'metro'],
          recommended: true,
          steps: [
            _step(
              type: 'LEG',
              instruction: 'Take the bus to Majestic',
              mode: 'bus',
            ),
            _step(
              type: 'TRANSFER',
              instruction: 'Change from Bus to Metro at Majestic',
              fromMode: 'bus',
              toMode: 'metro',
              location: 'Majestic',
            ),
            _step(
              type: 'LEG',
              instruction: 'Take the Metro to Indiranagar',
              mode: 'metro',
            ),
          ],
        ),
      ).entity;
      expect(opt.steps.length, 3);
      expect(opt.steps[0].isLeg, isTrue);
      expect(opt.steps[1].isTransfer, isTrue);
      expect(opt.steps[1].locationName, 'Majestic');
      expect(opt.steps[1].instruction, contains('Change from Bus to Metro'));
    });

    test('missing steps tolerated', () {
      final opt = TopJourneyOptionModel.fromJson(
        _topOptionJson(id: 'y', modes: ['cab'], recommended: true),
      ).entity;
      expect(opt.steps, isEmpty);
    });

    test('journey steps parse without Unknown', () {
      final journey = JourneyModel.fromJson({
        'candidate_id': 'j1',
        'legs': [],
        'steps': [
          {
            'type': 'TRANSFER',
            'instruction': 'Change from Bus to Metro',
            'from_mode': 'bus',
            'to_mode': 'metro',
          },
        ],
        'modes': ['bus', 'metro'],
        'mode_signature': 'bus → metro',
      }).entity;
      expect(journey.steps.single.instruction, isNot(contains('Unknown')));
    });
  });

  group('Phase 7G — ResultPage step rendering', () {
    Future<void> pump(WidgetTester tester, CommuteProvider provider) async {
      await tester.binding.setSurfaceSize(const Size(400, 2200));
      addTearDown(() async {
        await tester.binding.setSurfaceSize(null);
      });
      await tester.pumpWidget(
        _wrap(const ResultPage(apiBaseUrl: 'http://test'), provider),
      );
      await tester.pump();
    }

    final recSteps = [
      _step(type: 'LEG', instruction: 'Walk to Electronic City', mode: 'walk'),
      _step(type: 'LEG', instruction: 'Take the bus to Majestic', mode: 'bus'),
      _step(
        type: 'TRANSFER',
        instruction: 'Change from Bus to Metro at Majestic',
        fromMode: 'bus',
        toMode: 'metro',
        location: 'Majestic',
      ),
      _step(
        type: 'LEG',
        instruction: 'Take the Metro to Indiranagar',
        mode: 'metro',
      ),
      _step(
        type: 'LEG',
        instruction: 'Walk to your destination',
        mode: 'walk',
      ),
    ];

    final altSteps = [
      _step(
        type: 'LEG',
        instruction: 'Take an auto to Yelachenahalli',
        mode: 'auto',
      ),
      _step(
        type: 'TRANSFER',
        instruction: 'Change to Metro at Yelachenahalli',
        fromMode: 'auto',
        toMode: 'metro',
        location: 'Yelachenahalli',
      ),
      _step(type: 'LEG', instruction: 'Take the Metro to Majestic', mode: 'metro'),
      _step(
        type: 'LEG',
        instruction: 'Walk to your destination',
        mode: 'walk',
      ),
    ];

    testWidgets('recommended shows full steps + transfer', (tester) async {
      final plan = _planWithTop([
        _topOptionJson(
          id: 'rec',
          modes: ['walk', 'bus', 'metro', 'walk'],
          recommended: true,
          reason: 'Best match for your preferences',
          steps: recSteps,
        ),
        _topOptionJson(
          id: 'alt',
          modes: ['auto', 'metro', 'walk'],
          recommended: false,
          reason: 'Another option that fits your preferences',
          steps: altSteps,
          rank: 2,
        ),
      ]);
      await pump(tester, _provider(plan));
      expect(find.byKey(const Key('journey_steps_timeline')), findsOneWidget);
      expect(find.text('Walk to Electronic City'), findsOneWidget);
      expect(find.text('Change from Bus to Metro at Majestic'), findsOneWidget);
      expect(find.text('Change here'), findsOneWidget);
      expect(find.text('Majestic'), findsWidgets);
      expect(find.textContaining('Unknown'), findsNothing);
    });

    testWidgets('selecting alternative shows that journey steps', (tester) async {
      final plan = _planWithTop([
        _topOptionJson(
          id: 'rec',
          modes: ['walk', 'bus', 'metro', 'walk'],
          recommended: true,
          reason: 'Best match for your preferences',
          steps: recSteps,
        ),
        _topOptionJson(
          id: 'alt',
          modes: ['auto', 'metro', 'walk'],
          recommended: false,
          reason: 'Direct road access option',
          steps: altSteps,
          rank: 2,
        ),
      ]);
      final provider = _provider(plan);
      await pump(tester, provider);
      await tester.tap(find.byKey(const Key('alt_card_alt')));
      await tester.pump();
      expect(find.text('Take an auto to Yelachenahalli'), findsOneWidget);
      expect(find.textContaining('Yelachenahalli'), findsWidgets);
      expect(find.text('Walk to Electronic City'), findsNothing);
      // Backend recommendation identity unchanged.
      expect(plan.decision?.recommendedRouteId, 'rec');
      expect(plan.topSelection!.recommended!.identity, 'rec');
    });

    testWidgets('missing location does not show Unknown', (tester) async {
      final plan = _planWithTop([
        _topOptionJson(
          id: 'rec',
          modes: ['bus', 'metro'],
          recommended: true,
          reason: 'Best match for your preferences',
          steps: [
            _step(type: 'LEG', instruction: 'Continue by Bus', mode: 'bus'),
            _step(
              type: 'TRANSFER',
              instruction: 'Change from Bus to Metro',
              fromMode: 'bus',
              toMode: 'metro',
            ),
            _step(type: 'LEG', instruction: 'Continue by Metro', mode: 'metro'),
          ],
        ),
      ]);
      await pump(tester, _provider(plan));
      expect(find.text('Change from Bus to Metro'), findsOneWidget);
      expect(find.textContaining('Unknown'), findsNothing);
    });

    testWidgets('Maps CTA still uses selected journey mode', (tester) async {
      final plan = _planWithTop([
        _topOptionJson(
          id: 'rec',
          modes: ['walk', 'metro', 'walk'],
          recommended: true,
          reason: 'Best match for your preferences',
          steps: [
            _step(type: 'LEG', instruction: 'Take the Metro to Majestic', mode: 'metro'),
          ],
        ),
        _topOptionJson(
          id: 'cab',
          modes: ['cab'],
          recommended: false,
          reason: 'Direct road journey',
          steps: [
            _step(type: 'LEG', instruction: 'Cab to destination', mode: 'cab'),
          ],
          rank: 2,
        ),
      ]);
      final provider = _provider(plan);
      await pump(tester, provider);
      await tester.tap(find.byKey(const Key('alt_card_cab')));
      await tester.pump();
      final cab = plan.topSelection!.displayJourneys
          .firstWhere((o) => o.identity == 'cab');
      expect(mapsTravelModeForTopOption(cab), 'driving');
      expect(find.byKey(const Key('maps_handoff')), findsOneWidget);
      expect(plan.decision?.recommendedRouteId, 'rec');
    });
  });
}
