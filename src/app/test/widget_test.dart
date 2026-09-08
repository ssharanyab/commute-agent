import 'package:commute_agent/config.dart';
import 'package:commute_agent/constraint_parser.dart';
import 'package:commute_agent/departure_time.dart';
import 'package:commute_agent/models.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('normalizeBaseUrl strips trailing slash', () {
    expect(
      AppConfig.normalizeBaseUrl('http://example.com:8000/'),
      'http://example.com:8000',
    );
  });

  test('initialApiBaseUrl falls back to local default when define empty', () {
    // fromEnvironment is compile-time; without define it is empty → local default.
    if (AppConfig.apiBaseUrlFromDefine.trim().isEmpty) {
      expect(AppConfig.initialApiBaseUrl, AppConfig.localDevDefaultBaseUrl);
    } else {
      expect(AppConfig.initialApiBaseUrl, AppConfig.apiBaseUrlFromDefine.trim());
    }
  });

  group('ConstraintParser', () {
    test('parses No cabs / Avoid cabs / taxi phrases', () {
      expect(ConstraintParser.parseExcludedModesFromText('No cabs'), ['cab']);
      expect(ConstraintParser.parseExcludedModesFromText('Avoid cabs'), ['cab']);
      expect(
        ConstraintParser.parseExcludedModesFromText("don't take a taxi"),
        ['cab'],
      );
      expect(ConstraintParser.parseExcludedModesFromText('prefer metro'), isEmpty);
    });

    test('excludeCabs toggle merges with notes', () {
      expect(
        ConstraintParser.excludedModes(excludeCabs: true, notes: ''),
        ['cab'],
      );
      expect(
        ConstraintParser.excludedModes(excludeCabs: false, notes: 'No cabs'),
        ['cab'],
      );
    });
  });

  group('BengaluruDeparture IST', () {
    test('default display is IST wall clock (+1h), not UTC Z', () {
      final fixedUtc = DateTime.utc(2030, 1, 15, 8, 0); // 13:30 IST
      final display = BengaluruDeparture.defaultDisplay(utcNow: fixedUtc);
      expect(display, '2030-01-15 14:30');
      expect(display.contains('Z'), isFalse);
    });

    test('IST input converts to ISO-8601 with +05:30', () {
      expect(
        BengaluruDeparture.toApiIso8601('2030-01-15 14:00'),
        '2030-01-15T14:00:00+05:30',
      );
      expect(
        BengaluruDeparture.toApiIso8601('2030-01-15T09:30:00 IST'),
        '2030-01-15T09:30:00+05:30',
      );
    });

    test('explicit UTC ISO converts to Z for API', () {
      expect(
        BengaluruDeparture.toApiIso8601('2030-01-15T08:30:00Z'),
        '2030-01-15T08:30:00Z',
      );
    });

    test('IST+05:30 ISO normalizes to UTC Z', () {
      expect(
        BengaluruDeparture.toApiIso8601('2030-01-15T14:00:00+05:30'),
        '2030-01-15T08:30:00Z',
      );
    });

    test('resolveForPlan bumps past IST to now+1h', () {
      final fixedUtc = DateTime.utc(2030, 1, 15, 10, 0);
      final result = BengaluruDeparture.resolveForPlan(
        '2030-01-15 09:00', // 09:00 IST = 03:30 UTC — past relative to fixedUtc
        utcNow: fixedUtc,
      );
      expect(result.adjusted, isTrue);
      expect(result.displayIst, '2030-01-15 16:30'); // 10:00 UTC + 5:30 + 1h
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
      expect(result.apiIso8601, '2030-01-15T20:00:00+05:30');
    });
  });

  test('PlanResponse parses recommendation and empty alternatives', () {
    final plan = PlanResponse.fromJson({
      'ok': true,
      'recommendation': {
        'route_id': 'maps_drive_0',
        'mode': 'cab',
        'travel_time_minutes': 33,
        'cost': 420,
        'walking_minutes': 2,
        'transfers': 0,
        'congestion_score': 0.4,
        'reliability_score': 0.8,
        'disruption_risk': 0.1,
      },
      'alternatives': [],
      'explanation': 'fallback',
      'reasons': ['BEST_SCORE'],
      'data_sources': ['google_maps_routes'],
      'provenance': {
        'notes': ['live = Maps API field via adapter'],
      },
      'warnings': [],
      'error': null,
      'gemini': {
        'available': true,
        'invoked': false,
        'adk_invoked': false,
        'mode': 'deterministic_fallback',
      },
      'historical_signal_used': false,
      'routes': [
        {
          'route_index': 0,
          'mode': 'DRIVE',
          'distance_meters': 15000,
        },
      ],
    });
    expect(plan.ok, isTrue);
    expect(plan.recommendation?.routeId, 'maps_drive_0');
    expect(plan.recommendation?.distanceKm, closeTo(15.0, 0.01));
    expect(plan.alternatives, isEmpty);
    expect(plan.gemini.invoked, isFalse);
  });

  test('ReplanResponse parses before/after adaptive fields', () {
    final replan = ReplanResponse.fromJson({
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
        'disruption_risk': 0.2,
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
        'disruption_risk': 0.1,
      },
      'context_change': {
        'traffic_changed': true,
        'context_source': 'simulated',
        'congestion_delta': 0.55,
        'travel_time_delta_minutes': 22,
        'description': 'spike',
      },
      'explanation': 'Switched due to traffic.',
      'before': {'score': 10, 'reason_codes': ['A']},
      'after': {'score': 8, 'reason_codes': ['B']},
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
    });
    expect(replan.recommendationChanged, isTrue);
    expect(replan.previousRouteId, 'maps_drive_0');
    expect(replan.newRouteId, 'maps_drive_1');
    expect(replan.contextChange?.contextSource, 'simulated');
    expect(replan.gemini.invoked, isTrue);
  });
}
