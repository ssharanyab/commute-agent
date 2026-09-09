import 'dart:convert';
import 'dart:io';

import 'package:commute_agent/core/errors/api_exception.dart';
import 'package:commute_agent/data/datasources/commute_api_client.dart';
import 'package:commute_agent/data/models/commute_models.dart';
import 'package:commute_agent/data/repositories/commute_repository_impl.dart';
import 'package:commute_agent/domain/entities/commute_request.dart';
import 'package:commute_agent/domain/entities/user_preferences.dart';
import 'package:commute_agent/domain/entities/value_status.dart';
import 'package:commute_agent/presentation/utils/labels.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

Map<String, dynamic> _loadPhase6fFixture() {
  final file = File('test/fixtures/plan_response_phase6f.json');
  return jsonDecode(file.readAsStringSync()) as Map<String, dynamic>;
}

void main() {
  group('Phase 6G.1 — Phase 6F plan contract', () {
    test('parses successful /plan response into typed domain', () {
      final json = _loadPhase6fFixture();
      final plan = PlanResponseModel.fromJson(json).toEntity();

      expect(plan.ok, isTrue);
      expect(plan.orchestration, 'adk_mobility_orchestrator');
      expect(plan.recommendation, isNotNull);
      expect(plan.recommendedJourney, isNotNull);
      expect(plan.decision, isNotNull);
      expect(plan.decision!.authoritative, isTrue);
      expect(
        plan.recommendedJourney!.candidateId,
        plan.recommendation!.routeId,
      );
      expect(
        plan.decision!.recommendedRouteId,
        plan.recommendation!.routeId,
      );
      expect(plan.candidateCount, isNotNull);
      expect(plan.journeys, isNotEmpty);
      expect(plan.evaluation, isNotNull);
    });

    test('optional/null fields do not crash parsing', () {
      final json = _loadPhase6fFixture();
      json['historical_context'] = null;
      json['weather_context'] = null;
      json['metadata'] = null;
      json.remove('recommended_journey');
      final plan = PlanResponseModel.fromJson(json).toEntity();
      expect(plan.historicalContext, isNull);
      expect(plan.weatherContext, isNull);
      expect(plan.recommendedJourney, isNull);
      expect(plan.recommendation, isNotNull);
    });

    test('unknown cost status preserved (not treated as free)', () {
      final json = _loadPhase6fFixture();
      final plan = PlanResponseModel.fromJson(json).toEntity();
      final unknown = [
        ...plan.alternatives,
        if (plan.recommendation != null) plan.recommendation!,
      ].where((r) => r.costStatus == ValueStatus.unknown);

      expect(unknown, isNotEmpty);
      final sample = unknown.first;
      expect(sample.hasKnownCost, isFalse);
      expect(
        formatCostLabel(cost: sample.cost, known: sample.hasKnownCost),
        'Fare unavailable',
      );
      expect(
        formatCostLabel(cost: sample.cost, known: sample.hasKnownCost),
        isNot(contains('Free')),
      );
    });

    test('unknown duration status preserved', () {
      final json = _loadPhase6fFixture();
      final plan = PlanResponseModel.fromJson(json).toEntity();
      final rec = plan.recommendation!;
      // Live fixture often has duration_status unknown without Maps enrichment.
      if (rec.durationStatus == ValueStatus.unknown) {
        expect(rec.hasKnownDuration, isFalse);
        final label = formatDurationLabel(
          travelTimeMinutes: rec.travelTimeMinutes,
          known: rec.hasKnownDuration,
        );
        expect(label == 'Time unavailable' || label.startsWith('~'), isTrue);
      }
      final journey = plan.recommendedJourney!;
      expect(journey.durationStatus, isNotNull);
    });

    test('journey legs parse with mode / distance / statuses', () {
      final json = _loadPhase6fFixture();
      final journey =
          PlanResponseModel.fromJson(json).toEntity().recommendedJourney!;
      expect(journey.legs, isNotEmpty);
      final leg = journey.legs.first;
      expect(leg.mode, isNotEmpty);
      expect(leg.edgeKind, isNotEmpty);
      expect(leg.costStatus, isNotNull);
      expect(leg.durationStatus, isNotNull);
      expect(leg.fromNodeId, isNotEmpty);
      expect(leg.toNodeId, isNotEmpty);
    });

    test('googlePolyline and googleRouteToken survive parsing', () {
      final json = _loadPhase6fFixture();
      final rec = PlanResponseModel.fromJson(json).toEntity().recommendation!;
      expect(rec.googlePolyline, '_p~iF~ps|U');
      expect(rec.googleRouteToken, 'TOKEN_NAV');
    });

    test('leg polyline/token from metadata survive', () {
      final model = JourneyLegModel.fromJson({
        'index': 0,
        'mode': 'cab',
        'from_node_id': 'a',
        'to_node_id': 'b',
        'edge_id': 'e',
        'edge_kind': 'road_direct',
        'cost_status': 'unknown',
        'duration_status': 'unknown',
        'metadata': {
          'google_polyline': 'POLY_LEG',
          'google_route_token': 'TOK_LEG',
        },
      });
      expect(model.entity.googlePolyline, 'POLY_LEG');
      expect(model.entity.googleRouteToken, 'TOK_LEG');
    });
  });

  group('Phase 6G.1 — API client errors', () {
    test('API error response with error code parses', () async {
      final mock = MockClient((request) async {
        return http.Response(
          jsonEncode({
            'ok': false,
            'error': 'MAPS_API_UNAVAILABLE',
            'error_detail': 'key missing',
            'recommendation': null,
            'alternatives': [],
            'explanation': '',
            'reasons': [],
            'data_sources': [],
            'warnings': [],
            'gemini': {
              'available': false,
              'invoked': false,
              'adk_invoked': false,
              'mode': 'deterministic_fallback',
            },
          }),
          502,
        );
      });
      final client = CommuteApiClient(
        baseUrl: 'http://test',
        httpClient: mock,
      );
      final model = await client.plan({'origin': 'A', 'destination': 'B'});
      expect(model.ok, isFalse);
      expect(model.error, 'MAPS_API_UNAVAILABLE');
      client.close();
    });

    test('network failure maps to ApiException.network', () async {
      final mock = MockClient((request) async {
        throw http.ClientException('connection refused');
      });
      final client = CommuteApiClient(
        baseUrl: 'http://test',
        httpClient: mock,
      );
      expect(
        () => client.plan({'origin': 'A', 'destination': 'B'}),
        throwsA(
          isA<ApiException>().having(
            (e) => e.kind,
            'kind',
            ApiErrorKind.network,
          ),
        ),
      );
      client.close();
    });

    test('malformed JSON maps to ApiException.malformed', () async {
      final mock = MockClient((request) async {
        return http.Response('not-json{{{', 200);
      });
      final client = CommuteApiClient(
        baseUrl: 'http://test',
        httpClient: mock,
      );
      expect(
        () => client.plan({'origin': 'A', 'destination': 'B'}),
        throwsA(
          isA<ApiException>().having(
            (e) => e.kind,
            'kind',
            ApiErrorKind.malformed,
          ),
        ),
      );
      client.close();
    });
  });

  group('Phase 6G.1 — plan request body', () {
    test('repository emits preference_profile and excluded_modes', () {
      final repo = CommuteRepositoryImpl(baseUrl: 'http://example.com');
      final body = repo.buildPlanRequestBody(
        CommuteRequest(
          origin: 'Electronic City, Bengaluru',
          destination: 'Majestic, Bengaluru',
          departureTimeIso8601: '2030-01-15T14:00:00+05:30',
          preferenceProfile: 'FASTEST',
          preferences: const UserPreferences(
            timeWeight: 8,
            excludedModes: ['cab', 'auto'],
          ),
          invokeLiveTraffic: false,
          invokeGemini: false,
        ),
      );
      expect(body['preference_profile'], 'FASTEST');
      expect(body['invoke_live_traffic'], isFalse);
      expect(body['invoke_gemini'], isFalse);
      expect(
        (body['preferences'] as Map)['excluded_modes'],
        ['cab', 'auto'],
      );
      repo.close();
    });
  });
}
