import 'dart:async';
import 'dart:convert';

import 'package:commute_agent/core/config/app_config.dart';
import 'package:commute_agent/core/errors/api_exception.dart';
import 'package:commute_agent/core/utils/bengaluru_departure.dart';
import 'package:commute_agent/core/utils/constraint_parser.dart';
import 'package:commute_agent/core/utils/polyline_decoder.dart';
import 'package:commute_agent/data/datasources/commute_remote_data_source.dart';
import 'package:commute_agent/data/models/commute_models.dart';
import 'package:commute_agent/data/repositories/commute_repository_impl.dart';
import 'package:commute_agent/domain/entities/commute_plan.dart';
import 'package:commute_agent/domain/entities/commute_request.dart';
import 'package:commute_agent/domain/entities/commute_route.dart';
import 'package:commute_agent/domain/entities/context_change.dart';
import 'package:commute_agent/domain/entities/gemini_meta.dart';
import 'package:commute_agent/domain/entities/historical_signal.dart';
import 'package:commute_agent/domain/entities/route_category.dart';
import 'package:commute_agent/domain/entities/user_preferences.dart';
import 'package:commute_agent/presentation/providers/commute_provider.dart';
import 'package:commute_agent/presentation/screens/home/planner_page.dart';
import 'package:commute_agent/presentation/screens/results/result_page.dart';
import 'package:commute_agent/presentation/utils/labels.dart';
import 'package:commute_agent/presentation/widgets/planner/control_row.dart';
import 'package:commute_agent/presentation/widgets/planner/preference_chip.dart';
import 'package:commute_agent/presentation/widgets/route_map.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

Map<String, dynamic> _samplePlanJson({
  bool withGeometry = true,
  bool withHistorical = false,
  bool ok = true,
  String? error,
  List<Map<String, dynamic>>? alternatives,
  List<Map<String, dynamic>>? categories,
}) {
  final recommendation = {
    'route_id': 'maps_drive_0',
    'mode': 'cab',
    'travel_time_minutes': 33,
    'cost': 420,
    'walking_minutes': 2,
    'transfers': 0,
    'congestion_score': 0.4,
    'reliability_score': 0.8,
    'disruption_risk': 0.1,
    'distance_meters': 15000,
    if (withGeometry) 'google_polyline': '_p~iF~ps|U',
    if (withGeometry) 'google_route_token': 'TOKEN_ABC',
    if (withHistorical)
      'historical_mobility_signal': {
        'has_historical_coverage': true,
        'historical_expected_travel_time_minutes': 28,
        'historical_std_travel_time_minutes': 4,
        'historical_reliability_score': 0.9,
        'deviation_percent': 18,
        'deviation_state': 'ELEVATED',
        'confidence_level': 'HIGH',
      },
  };

  final metro = {
    'route_id': 'fixture_metro_1',
    'mode': 'metro',
    'travel_time_minutes': 47,
    'cost': 45,
    'walking_minutes': 8,
    'transfers': 1,
    'congestion_score': 0.2,
    'reliability_score': 0.92,
  };

  return {
    'ok': ok,
    'recommendation': recommendation,
    'alternatives': alternatives ?? [metro],
    'explanation': 'Cab is fastest for your preferences.',
    'reasons': ['FASTEST', 'LOW_WALKING'],
    'data_sources': ['google_maps_routes'],
    'provenance': {
      'notes': ['live = Maps API field via adapter'],
    },
    'warnings': [],
    'error': error,
    'error_detail': error == null ? null : 'detail',
    'gemini': {
      'available': true,
      'invoked': false,
      'adk_invoked': false,
      'mode': 'deterministic_fallback',
    },
    'historical_signal_used': withHistorical,
    'evaluation': {
      'route_categories': categories ??
          [
            {'category': 'BEST_OVERALL', 'route_id': 'maps_drive_0'},
            {'category': 'FASTEST', 'route_id': 'maps_drive_0'},
            {'category': 'CHEAPEST', 'route_id': 'fixture_metro_1'},
            {'category': 'MOST_RELIABLE', 'route_id': 'fixture_metro_1'},
          ],
    },
    'routes': [
      {'route_index': 0, 'mode': 'DRIVE', 'distance_meters': 15000},
    ],
  };
}

Widget _wrap(Widget child, {CommuteProvider? provider}) {
  final p = provider ?? CommuteProvider();
  return ChangeNotifierProvider<CommuteProvider>.value(
    value: p,
    child: MaterialApp(home: child),
  );
}

void main() {
  test('normalizeBaseUrl strips trailing slash', () {
    expect(
      AppConfig.normalizeBaseUrl('http://example.com:8000/'),
      'http://example.com:8000',
    );
  });

  test('initialApiBaseUrl defaults for platform when define empty', () {
    if (AppConfig.apiBaseUrlFromDefine.trim().isEmpty) {
      // Tests run as Android + debug → emulator local loopback.
      expect(
        AppConfig.initialApiBaseUrl,
        anyOf(
          AppConfig.androidEmulatorDefaultBaseUrl,
          AppConfig.cloudRunDefaultBaseUrl,
          AppConfig.localDevDefaultBaseUrl,
        ),
      );
      if (defaultTargetPlatform == TargetPlatform.android) {
        expect(
          AppConfig.initialApiBaseUrl,
          AppConfig.androidEmulatorDefaultBaseUrl,
        );
      }
    } else {
      expect(
        AppConfig.initialApiBaseUrl,
        AppConfig.apiBaseUrlFromDefine.trim(),
      );
    }
  });

  group('ConstraintParser', () {
    test('parses No cabs / Avoid cabs / taxi phrases', () {
      expect(ConstraintParser.parseExcludedModesFromText('No cabs'), ['cab']);
      expect(ConstraintParser.parseExcludedModesFromText('Avoid cabs'), [
        'cab',
      ]);
      expect(ConstraintParser.parseExcludedModesFromText("don't take a taxi"), [
        'cab',
      ]);
      expect(
        ConstraintParser.parseExcludedModesFromText('prefer metro'),
        isEmpty,
      );
    });

    test('excludeCabs toggle merges with notes', () {
      expect(ConstraintParser.excludedModes(excludeCabs: true, notes: ''), [
        'cab',
      ]);
      expect(
        ConstraintParser.excludedModes(excludeCabs: false, notes: 'No cabs'),
        ['cab'],
      );
    });
  });

  group('OptimizationProfile', () {
    test('Fast / Cheap / Reliable / Easy map to preference weights', () {
      final fast = OptimizationProfile.fastest.toWeights(
        avoidHeavyTraffic: true,
        maxWalkingMinutes: 20,
      );
      expect(fast.timeWeight, 8);
      expect(fast.costWeight, 1);

      final cheap = OptimizationProfile.cheapest.toWeights(
        avoidHeavyTraffic: true,
      );
      expect(cheap.costWeight, 8);

      final reliable = OptimizationProfile.moreReliable.toWeights(
        avoidHeavyTraffic: false,
        excludedModes: const ['cab'],
      );
      expect(reliable.reliabilityWeight, 8);
      expect(reliable.excludedModes, ['cab']);

      final easy = OptimizationProfile.lessWalking.toWeights(
        avoidHeavyTraffic: true,
        maxWalkingMinutes: 15,
      );
      expect(easy.walkingWeight, 8);
      expect(easy.transferWeight, 4);
      expect(easy.maxWalkingMinutes, 15);
    });
  });

  group('BengaluruDeparture IST', () {
    test('default display is IST wall clock (+1h), not UTC Z', () {
      final fixedUtc = DateTime.utc(2030, 1, 15, 8, 0);
      final display = BengaluruDeparture.defaultDisplay(utcNow: fixedUtc);
      expect(display, '2030-01-15 14:30');
      expect(display.contains('Z'), isFalse);
    });

    test('IST input converts to ISO-8601 with +05:30', () {
      expect(
        BengaluruDeparture.toApiIso8601('2030-01-15 14:00'),
        '2030-01-15T14:00:00+05:30',
      );
    });

    test('explicit UTC ISO converts to Z for API', () {
      expect(
        BengaluruDeparture.toApiIso8601('2030-01-15T08:30:00Z'),
        '2030-01-15T08:30:00Z',
      );
    });

    test('resolveForPlan bumps past IST to now+1h', () {
      final fixedUtc = DateTime.utc(2030, 1, 15, 10, 0);
      final result = BengaluruDeparture.resolveForPlan(
        '2030-01-15 09:00',
        utcNow: fixedUtc,
      );
      expect(result.adjusted, isTrue);
      expect(result.displayIst, '2030-01-15 16:30');
      expect(result.apiIso8601, '2030-01-15T16:30:00+05:30');
    });

    test('resolveForPlan keeps valid future IST', () {
      final fixedUtc = DateTime.utc(2030, 1, 15, 10, 0);
      final result = BengaluruDeparture.resolveForPlan(
        '2030-01-15 20:00',
        utcNow: fixedUtc,
      );
      expect(result.adjusted, isFalse);
      expect(result.displayIst, '2030-01-15 20:00');
    });
  });

  group('polyline decoder', () {
    test('decodes Google sample polyline', () {
      final points = decodeGooglePolyline('_p~iF~ps|U');
      expect(points, isNotEmpty);
      expect(points.first.latitude, closeTo(38.5, 0.01));
      expect(points.first.longitude, closeTo(-120.2, 0.01));
    });

    test('empty / invalid returns empty list', () {
      expect(decodeGooglePolyline(null), isEmpty);
      expect(decodeGooglePolyline(''), isEmpty);
    });
  });

  group('labels', () {
    test('reason and category labels are user-facing', () {
      expect(reasonLabel('LOW_COST'), 'Lower cost');
      expect(reasonLabel('HIGH_RELIABILITY'), 'More reliable');
      expect(categoryLabel('FASTEST'), '⚡ Fastest');
      expect(modeLabel('cab'), 'Cab');
    });
  });

  group('data model conversion', () {
    test('API response → data model → domain entity', () {
      final model = PlanResponseModel.fromJson(_samplePlanJson());
      final entity = model.toEntity();
      expect(entity.ok, isTrue);
      expect(entity.recommendation?.routeId, 'maps_drive_0');
      expect(entity.recommendation?.distanceKm, closeTo(15.0, 0.01));
      expect(entity.recommendation?.distanceMeters, 15000);
      expect(entity.recommendation?.googlePolyline, '_p~iF~ps|U');
      expect(entity.recommendation?.googleRouteToken, 'TOKEN_ABC');
      expect(entity.gemini.invoked, isFalse);
    });

    test('missing optional polyline/token does not fail', () {
      final model = PlanResponseModel.fromJson(
        _samplePlanJson(withGeometry: false),
      );
      final route = model.toEntity().recommendation!;
      expect(route.googlePolyline, isNull);
      expect(route.googleRouteToken, isNull);
      expect(route.distanceMeters, 15000);
    });

    test('historical signal and categories parse', () {
      final entity = PlanResponseModel.fromJson(
        _samplePlanJson(withHistorical: true),
      ).toEntity();
      expect(entity.recommendation?.historicalSignal?.hasCoverage, isTrue);
      expect(entity.recommendation?.historicalSignal?.expectedMinutes, 28);
      expect(entity.recommendation?.historicalSignal?.deviationPercent, 18);
      // BEST_OVERALL + same-as-rec FASTEST skipped; CHEAPEST (metro) kept once
      expect(entity.routeCategories.length, 1);
      expect(entity.routeCategories.first.category, 'CHEAPEST');
      expect(entity.routeCategories.first.route.mode, 'metro');
    });

    test('historical omitted when unavailable', () {
      final entity =
          PlanResponseModel.fromJson(_samplePlanJson()).toEntity();
      expect(entity.recommendation?.historicalSignal, isNull);
    });

    test('ReplanResponse parses before/after adaptive fields', () {
      final replan =
          ReplanResponseModel.fromJson({
            'ok': true,
            'recommendation_changed': true,
            'previous_route_id': 'maps_drive_0',
            'new_route_id': 'maps_drive_1',
            'previous_recommendation': {
              'route_id': 'maps_drive_0',
              'mode': 'cab',
              'travel_time_minutes': 55,
              'cost': 420,
              'walking_minutes': 2,
              'transfers': 0,
              'congestion_score': 0.9,
              'reliability_score': 0.7,
            },
            'new_recommendation': {
              'route_id': 'maps_drive_1',
              'mode': 'cab',
              'travel_time_minutes': 40,
              'cost': 400,
              'walking_minutes': 3,
              'transfers': 0,
              'congestion_score': 0.5,
              'reliability_score': 0.8,
              'google_polyline': 'abc',
              'google_route_token': 'tok',
            },
            'context_change': {
              'traffic_changed': true,
              'context_source': 'simulated',
              'congestion_delta': 0.55,
              'travel_time_delta_minutes': 22,
              'description': 'spike',
            },
            'explanation': 'Switched due to traffic.',
            'before': {
              'score': 10,
              'reason_codes': ['A'],
            },
            'after': {
              'score': 8,
              'reason_codes': ['B'],
            },
            'data_sources': ['google_maps_routes', 'simulated_context'],
            'provenance': {
              'replan_notes': ['SIMULATED:demo'],
            },
            'warnings': [],
            'gemini': {
              'available': true,
              'invoked': true,
              'adk_invoked': true,
              'mode': 'adk_gemini',
            },
          }).toEntity();
      expect(replan.recommendationChanged, isTrue);
      expect(replan.newRecommendation?.googlePolyline, 'abc');
      expect(replan.newRecommendation?.googleRouteToken, 'tok');
      expect(replan.contextChange?.contextSource, 'simulated');
    });
  });

  group('repository', () {
    test('planCommute maps remote JSON to domain', () async {
      final mock = MockClient((request) async {
        expect(request.url.path, '/plan');
        return http.Response(jsonEncode(_samplePlanJson()), 200);
      });
      final repo = CommuteRepositoryImpl(
        baseUrl: 'http://example.com',
        dataSource: CommuteRemoteDataSource(
          baseUrl: 'http://example.com',
          httpClient: mock,
        ),
      );
      final plan = await repo.planCommute(
        const CommuteRequest(
          origin: 'A',
          destination: 'B',
          departureTimeIso8601: '2030-01-15T14:00:00+05:30',
          preferences: UserPreferences(),
        ),
      );
      expect(plan.recommendation?.routeId, 'maps_drive_0');
      expect(plan.recommendation?.googlePolyline, isNotNull);
      repo.close();
    });

    test('buildPlanRequestBody includes profile weights and constraints', () {
      final repo = CommuteRepositoryImpl(baseUrl: 'http://example.com');
      final prefs = OptimizationProfile.cheapest.toWeights(
        avoidHeavyTraffic: true,
        maxWalkingMinutes: 20,
        excludedModes: const ['cab'],
      );
      final body = repo.buildPlanRequestBody(
        CommuteRequest(
          origin: 'A',
          destination: 'B',
          departureTimeIso8601: '2030-01-15T14:00:00+05:30',
          preferences: prefs,
        ),
      );
      final p = body['preferences'] as Map<String, dynamic>;
      expect(p['cost_weight'], 8.0);
      expect(p['excluded_modes'], ['cab']);
      expect(p['max_walking_minutes'], 20.0);
      expect(p['avoid_heavy_traffic'], isTrue);
      repo.close();
    });
  });

  group('CommuteProvider', () {
    test('initial state is idle', () {
      final p = CommuteProvider();
      expect(p.status, CommuteStatus.idle);
      expect(p.plan, isNull);
      expect(p.errorTitle, isNull);
    });

    test('planCommute success flow', () async {
      final mock = MockClient((request) async {
        return http.Response(jsonEncode(_samplePlanJson()), 200);
      });
      final provider = _TestableProvider(mock);
      expect(provider.status, CommuteStatus.idle);

      final future = provider.planCommute(
        baseUrl: 'http://test',
        request: const CommuteRequest(
          origin: 'A',
          destination: 'B',
          departureTimeIso8601: '2030-01-15T14:00:00+05:30',
          preferences: UserPreferences(timeWeight: 8),
        ),
      );
      expect(provider.status, CommuteStatus.loading);
      final ok = await future;
      expect(ok, isTrue);
      expect(provider.status, CommuteStatus.success);
      expect(provider.plan?.recommendation?.routeId, 'maps_drive_0');
      expect(provider.plan?.recommendation?.googleRouteToken, 'TOKEN_ABC');
      expect(provider.lastPlanRequest, isNotNull);
    });

    test('planCommute error when API returns ok=false', () async {
      final mock = MockClient((request) async {
        return http.Response(
          jsonEncode(_samplePlanJson(ok: false, error: 'NO_ROUTES')),
          200,
        );
      });
      final provider = _TestableProvider(mock);
      final ok = await provider.planCommute(
        baseUrl: 'http://test',
        request: const CommuteRequest(
          origin: 'A',
          destination: 'B',
          departureTimeIso8601: '2030-01-15T14:00:00+05:30',
          preferences: UserPreferences(),
        ),
      );
      expect(ok, isFalse);
      expect(provider.status, CommuteStatus.error);
      expect(provider.errorTitle, "Couldn't plan this commute");
      expect(provider.plan, isNull);
    });

    test('NO_VALID_ROUTES humanizes clearly', () {
      final msg = CommuteProvider.humanizePlanFailure(
        const CommutePlan(
          ok: false,
          recommendation: null,
          alternatives: [],
          explanation: '',
          reasons: [],
          dataSources: [],
          provenance: null,
          warnings: [],
          error: 'NO_VALID_ROUTES',
          errorDetail: '',
          gemini: GeminiMeta(
            available: false,
            invoked: false,
            adkInvoked: false,
            mode: 'x',
          ),
          historicalSignalUsed: false,
        ),
      );
      expect(msg, contains('No route matches your current constraints'));
    });

    test('planCommute error on ApiException', () async {
      final mock = MockClient((request) async {
        return http.Response('{"detail":"boom"}', 500);
      });
      final provider = _TestableProvider(mock);
      final ok = await provider.planCommute(
        baseUrl: 'http://test',
        request: const CommuteRequest(
          origin: 'A',
          destination: 'B',
          departureTimeIso8601: '2030-01-15T14:00:00+05:30',
          preferences: UserPreferences(),
        ),
      );
      expect(ok, isFalse);
      expect(provider.status, CommuteStatus.error);
      expect(provider.errorDetail, contains('500'));
    });

    test('replanCommute loading/success', () async {
      final completer = Completer<http.Response>();
      final mock = MockClient((request) async {
        if (request.url.path.endsWith('/plan')) {
          return http.Response(jsonEncode(_samplePlanJson()), 200);
        }
        return completer.future;
      });
      final provider = _TestableProvider(mock);
      await provider.planCommute(
        baseUrl: 'http://test',
        request: const CommuteRequest(
          origin: 'A',
          destination: 'B',
          departureTimeIso8601: '2030-01-15T14:00:00+05:30',
          preferences: UserPreferences(),
        ),
      );
      final future = provider.replanCommute(
        baseUrl: 'http://test',
        contextChange: const ContextChange(
          trafficChanged: true,
          contextSource: 'simulated',
        ),
      );
      expect(provider.replanStatus, CommuteStatus.loading);
      completer.complete(
        http.Response(
          jsonEncode({
            'ok': true,
            'recommendation_changed': true,
            'previous_route_id': 'maps_drive_0',
            'new_route_id': 'fixture_metro_1',
            'previous_recommendation': _samplePlanJson()['recommendation'],
            'new_recommendation': (_samplePlanJson()['alternatives'] as List)
                .first,
            'context_change': {
              'traffic_changed': true,
              'context_source': 'simulated',
            },
            'explanation': 'Road travel time increased significantly.',
            'before': {'score': 1},
            'after': {'score': 2},
            'data_sources': ['google_maps_routes'],
            'warnings': [],
            'gemini': {
              'available': false,
              'invoked': false,
              'adk_invoked': false,
              'mode': 'deterministic_fallback',
            },
          }),
          200,
        ),
      );
      await future;
      expect(provider.replanStatus, CommuteStatus.success);
      expect(provider.replanResult?.recommendationChanged, isTrue);
      expect(provider.plan, isNotNull); // previous plan kept
    });

    test('replanCommute error keeps prior plan', () async {
      final mock = MockClient((request) async {
        if (request.url.path.endsWith('/plan')) {
          return http.Response(jsonEncode(_samplePlanJson()), 200);
        }
        return http.Response('{"detail":"replan boom"}', 500);
      });
      final provider = _TestableProvider(mock);
      await provider.planCommute(
        baseUrl: 'http://test',
        request: const CommuteRequest(
          origin: 'A',
          destination: 'B',
          departureTimeIso8601: '2030-01-15T14:00:00+05:30',
          preferences: UserPreferences(),
        ),
      );
      await provider.replanCommute(
        baseUrl: 'http://test',
        contextChange: const ContextChange(
          trafficChanged: true,
          contextSource: 'simulated',
        ),
      );
      expect(provider.replanStatus, CommuteStatus.error);
      expect(provider.replanError, isNotNull);
      expect(provider.plan?.recommendation?.routeId, 'maps_drive_0');
    });
  });

  group('PlannerPage UI', () {
    testWidgets('renders header, inputs, optimize chips, CTA', (tester) async {
      await tester.binding.setSurfaceSize(const Size(400, 1400));
      addTearDown(() async {
        await tester.binding.setSurfaceSize(null);
      });
      await tester.pumpWidget(_wrap(const PlannerPage()));
      expect(find.text('GoWise'), findsOneWidget);
      expect(find.text('Plan your journey'), findsOneWidget);
      expect(
        find.text("I'll compose the best way to get there."),
        findsOneWidget,
      );
      expect(find.text('Origin'), findsWidgets);
      expect(find.text('Destination'), findsWidgets);
      expect(find.text('Balanced'), findsOneWidget);
      expect(find.text('Fastest'), findsOneWidget);
      expect(find.text('Cheapest'), findsOneWidget);
      expect(find.text('More reliable'), findsOneWidget);
      expect(find.text('Less walking'), findsOneWidget);
      expect(find.text('Lower traffic'), findsOneWidget);
      expect(find.text('Compose commute'), findsOneWidget);
      expect(find.text('Prefer lower traffic'), findsNothing);

      await tester.ensureVisible(find.byKey(const Key('more_controls_toggle')));
      expect(find.text('Avoid cab'), findsOneWidget);
      expect(find.text('Avoid auto'), findsOneWidget);
    });

    testWidgets('preference chip selection updates selection', (tester) async {
      await tester.pumpWidget(_wrap(const PlannerPage()));
      await tester.tap(find.text('Cheapest'));
      await tester.pump();
      final cheap = tester.widget<PreferenceChip>(
        find.byKey(const Key('pref_cheapest')),
      );
      expect(cheap.selected, isTrue);
    });

    testWidgets('constraint toggle Avoid cab works', (tester) async {
      await tester.binding.setSurfaceSize(const Size(400, 1200));
      addTearDown(() async {
        await tester.binding.setSurfaceSize(null);
      });
      await tester.pumpWidget(_wrap(const PlannerPage()));
      await tester.ensureVisible(find.byKey(const Key('exclude_cab')));
      final before = tester.widget<ControlRow>(
        find.byKey(const Key('exclude_cab')),
      );
      expect(before.value, isFalse);
      await tester.tap(find.byKey(const Key('exclude_cab')));
      await tester.pumpAndSettle();
      final after = tester.widget<ControlRow>(
        find.byKey(const Key('exclude_cab')),
      );
      expect(after.value, isTrue);
    });

    testWidgets('plan button enters loading state', (tester) async {
      final completer = Completer<http.Response>();
      final mock = MockClient((_) => completer.future);
      final provider = _TestableProvider(mock);
      await tester.binding.setSurfaceSize(const Size(400, 1400));
      addTearDown(() async {
        await tester.binding.setSurfaceSize(null);
      });
      await tester.pumpWidget(_wrap(const PlannerPage(), provider: provider));

      await tester.enterText(find.widgetWithText(TextFormField, 'Origin'), 'A');
      await tester.enterText(
        find.widgetWithText(TextFormField, 'Destination'),
        'B',
      );
      await tester.pump();
      await tester.ensureVisible(find.byKey(const Key('plan_cta')));
      await tester.tap(find.byKey(const Key('plan_cta')));
      await tester.pump();
      expect(find.byKey(const Key('planning_loading')), findsOneWidget);
      expect(provider.status, CommuteStatus.loading);

      // Fail the plan so we stay on PlannerPage (success would navigate).
      completer.complete(
        http.Response(
          jsonEncode(_samplePlanJson(ok: false, error: 'NO_ROUTES')),
          200,
        ),
      );
      await tester.pump();
      expect(provider.status, CommuteStatus.error);
    });

    testWidgets('error state shows retry', (tester) async {
      final provider = CommuteProvider();
      provider.setConfigurationError(
        "Couldn't plan this commute",
        'Set API base URL',
      );
      await tester.binding.setSurfaceSize(const Size(400, 1400));
      addTearDown(() async {
        await tester.binding.setSurfaceSize(null);
      });
      await tester.pumpWidget(_wrap(const PlannerPage(), provider: provider));
      await tester.pump();
      expect(provider.errorTitle, "Couldn't plan this commute");
      expect(find.byKey(const Key('planner_error_panel')), findsOneWidget);
      expect(find.text("Couldn't plan this commute"), findsOneWidget);
      expect(find.text('RETRY'), findsOneWidget);
    });
  });

  group('ResultPage UI', () {
    setUp(() {
      // Tall surface so scrollable result sections are reachable in tests.
      TestWidgetsFlutterBinding.ensureInitialized();
    });

    CommuteProvider seededProvider({
      bool withPolyline = true,
      bool withHistorical = true,
      bool noRecommendation = false,
    }) {
      final provider = CommuteProvider();
      final json = _samplePlanJson(
        withGeometry: withPolyline,
        withHistorical: withHistorical,
      );
      if (noRecommendation) {
        json['recommendation'] = null;
        json['alternatives'] = [];
        json['evaluation'] = {'route_categories': []};
      }
      final plan = PlanResponseModel.fromJson(json).toEntity();
      provider.plan = plan;
      provider.status = CommuteStatus.success;
      provider.lastPlanRequest = {
        'origin': 'Electronic City, Bengaluru',
        'destination': 'Koramangala, Bengaluru',
      };
      return provider;
    }

    Future<void> pumpResults(
      WidgetTester tester,
      CommuteProvider provider,
    ) async {
      await tester.binding.setSurfaceSize(const Size(400, 1600));
      addTearDown(() async {
        await tester.binding.setSurfaceSize(null);
      });
      await tester.pumpWidget(
        _wrap(const ResultPage(apiBaseUrl: 'http://test'), provider: provider),
      );
    }

    testWidgets('successful plan displays recommendation', (tester) async {
      await pumpResults(tester, seededProvider());
      expect(find.text('Best for you'), findsOneWidget);
      expect(find.textContaining('Cab'), findsWidgets);
      expect(find.textContaining('33 min'), findsWidgets);
      expect(find.textContaining('₹420'), findsWidgets);
    });

    testWidgets('historical information displays when available',
        (tester) async {
      await pumpResults(tester, seededProvider(withHistorical: true));
      expect(find.text('Historical context'), findsOneWidget);
      expect(find.textContaining('Usually'), findsOneWidget);
      expect(find.textContaining('above usual'), findsOneWidget);
    });

    testWidgets('historical omitted when unavailable', (tester) async {
      await pumpResults(tester, seededProvider(withHistorical: false));
      expect(find.text('Historical context'), findsNothing);
      expect(find.text('Limited historical data'), findsNothing);
    });

    testWidgets('route categories render', (tester) async {
      await pumpResults(tester, seededProvider());
      expect(find.text('Other ways to go'), findsOneWidget);
      expect(find.textContaining('Lower cost'), findsOneWidget);
      expect(find.textContaining('Metro'), findsWidgets);
    });

    testWidgets('why this route uses backend reasons', (tester) async {
      await pumpResults(tester, seededProvider());
      expect(find.text('Why this?'), findsOneWidget);
      expect(find.text('Cab is fastest for your preferences.'), findsOneWidget);
      expect(find.text('Faster than other known options'), findsOneWidget);
      expect(find.text('Less walking'), findsOneWidget);
    });

    testWidgets('no embedded map widget is rendered', (tester) async {
      final provider = seededProvider(withPolyline: true);
      await pumpResults(tester, provider);
      expect(find.byType(RouteMap), findsNothing);
      expect(find.text('Best for you'), findsOneWidget);
      expect(find.byKey(const Key('hero_recommendation')), findsOneWidget);
      expect(find.byKey(const Key('mode_sequence')), findsOneWidget);
      expect(provider.plan?.recommendation?.googlePolyline, '_p~iF~ps|U');
      expect(provider.plan?.recommendation?.googleRouteToken, 'TOKEN_ABC');
    });

    testWidgets('missing polyline still shows recommendation without map', (tester) async {
      await pumpResults(tester, seededProvider(withPolyline: false));
      expect(find.byType(RouteMap), findsNothing);
      expect(find.text('Best for you'), findsOneWidget);
    });

    testWidgets('no recommendation empty state', (tester) async {
      await pumpResults(tester, seededProvider(noRecommendation: true));
      expect(
        find.textContaining("couldn't find a suitable way"),
        findsOneWidget,
      );
    });

    testWidgets('replan and maps handoff actions present', (tester) async {
      await pumpResults(tester, seededProvider());
      expect(find.byKey(const Key('replan_button')), findsOneWidget);
      expect(find.byKey(const Key('maps_handoff')), findsOneWidget);
      final mapsBtn = tester.widget<FilledButton>(
        find.byKey(const Key('maps_handoff')),
      );
      expect(mapsBtn.onPressed, isNotNull);
      expect(find.text('Open in Maps'), findsOneWidget);
    });

    testWidgets('maps handoff disabled without origin/destination',
        (tester) async {
      final provider = seededProvider();
      provider.lastPlanRequest = {};
      await pumpResults(tester, provider);
      final mapsBtn = tester.widget<FilledButton>(
        find.byKey(const Key('maps_handoff')),
      );
      expect(mapsBtn.onPressed, isNull);
    });

    testWidgets('replan error banner while keeping plan', (tester) async {
      final provider = seededProvider();
      provider.replanStatus = CommuteStatus.error;
      provider.replanError = 'Replan failed: network';
      await pumpResults(tester, provider);
      expect(find.textContaining('Replan failed'), findsOneWidget);
      expect(find.text('Best for you'), findsOneWidget);
    });
  });

  group('RouteMap widget', () {
    testWidgets('fallback when polyline missing', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(body: RouteMap(encodedPolyline: null)),
        ),
      );
      expect(find.text('Route preview unavailable'), findsOneWidget);
    });

    testWidgets('renders sketch for decoded polyline on desktop test',
        (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: RouteMap(encodedPolyline: '_p~iF~ps|U'),
          ),
        ),
      );
      expect(find.byType(RouteMap), findsOneWidget);
      expect(find.text('Route preview unavailable'), findsNothing);
    });
  });

  group('limited historical card', () {
    testWidgets('shows limited copy when coverage false', (tester) async {
      final provider = CommuteProvider();
      provider.status = CommuteStatus.success;
      provider.lastPlanRequest = {
        'origin': 'A',
        'destination': 'B',
      };
      provider.plan = CommutePlan(
        ok: true,
        recommendation: const CommuteRoute(
          routeId: 'r1',
          mode: 'metro',
          travelTimeMinutes: 40,
          cost: 50,
          walkingMinutes: 5,
          transfers: 0,
          congestionScore: 0.2,
          reliabilityScore: 0.9,
          historicalSignal: HistoricalSignal(hasCoverage: false),
        ),
        alternatives: const [],
        explanation: '',
        reasons: const [],
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
        historicalSignalUsed: false,
        routeCategories: const [
          RouteCategory(
            category: 'CHEAPEST',
            route: CommuteRoute(
              routeId: 'r2',
              mode: 'bus',
              travelTimeMinutes: 55,
              cost: 30,
              walkingMinutes: 10,
              transfers: 1,
              congestionScore: 0.3,
              reliabilityScore: 0.7,
            ),
          ),
        ],
      );
      await tester.binding.setSurfaceSize(const Size(400, 1600));
      addTearDown(() async {
        await tester.binding.setSurfaceSize(null);
      });
      await tester.pumpWidget(
        _wrap(const ResultPage(apiBaseUrl: 'http://t'), provider: provider),
      );
      expect(find.text('Limited historical data'), findsOneWidget);
    });
  });
}


/// Provider that injects a MockClient into CommuteRepositoryImpl.
class _TestableProvider extends CommuteProvider {
  _TestableProvider(this._client);

  final http.Client _client;

  @override
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

    final repo = CommuteRepositoryImpl(
      baseUrl: baseUrl,
      dataSource: CommuteRemoteDataSource(
        baseUrl: baseUrl,
        httpClient: _client,
      ),
    );
    try {
      lastPlanRequest = repo.buildPlanRequestBody(request);
      final result = await repo.planCommute(request);
      if (!result.ok || result.error != null) {
        plan = null;
        status = CommuteStatus.error;
        errorTitle = "Couldn't plan this commute";
        errorDetail = CommuteProvider.humanizePlanFailure(result);
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
      errorTitle = "Couldn't plan this commute";
      errorDetail = e.message;
      notifyListeners();
      return false;
    } finally {
      // Do not close shared mock client.
    }
  }

  @override
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

    final repo = CommuteRepositoryImpl(
      baseUrl: baseUrl,
      dataSource: CommuteRemoteDataSource(
        baseUrl: baseUrl,
        httpClient: _client,
      ),
    );
    try {
      final result = await repo.replanCommute(
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
    }
  }
}
