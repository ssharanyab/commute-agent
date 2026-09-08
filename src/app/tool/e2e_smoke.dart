// Live smoke against a running API. Run:
//   fvm dart run --dart-define=API_BASE_URL=http://127.0.0.1:8000 tool/e2e_smoke.dart
import 'dart:convert';
import 'dart:io';

import 'package:commute_agent/core/config/app_config.dart';
import 'package:commute_agent/core/utils/bengaluru_departure.dart';
import 'package:commute_agent/data/datasources/commute_remote_data_source.dart';
import 'package:commute_agent/data/models/commute_models.dart';

Future<void> main() async {
  final base = AppConfig.normalizeBaseUrl(
    AppConfig.apiBaseUrlFromDefine.isNotEmpty
        ? AppConfig.apiBaseUrlFromDefine
        : (Platform.environment['API_BASE_URL'] ?? ''),
  );
  if (base.isEmpty) {
    stderr.writeln('API_BASE_URL required via --dart-define or env');
    exit(2);
  }

  final client = CommuteRemoteDataSource(baseUrl: base);
  try {
    final health = await client.health();
    stdout.writeln('health: ${jsonEncode(health)}');

    final planBody = {
      'origin': 'Electronic City, Bengaluru',
      'destination': 'Koramangala, Bengaluru',
      'departure_time':
          BengaluruDeparture.resolveForPlan(
            BengaluruDeparture.defaultDisplay(),
          ).apiIso8601,
      'invoke_gemini': true,
      'preferences': {
        'avoid_heavy_traffic': true,
        'max_walking_minutes': 20,
        'time_weight': 8.0,
      },
    };
    final plan = await client.plan(planBody);
    stdout.writeln(
      'plan ok=${plan.ok} error=${plan.error} '
      'rec=${plan.recommendation?.routeId} '
      'polyline=${plan.recommendation?.googlePolyline != null} '
      'alts=${plan.alternatives.length}',
    );

    if (plan.ok && plan.recommendation != null) {
      final replan = await client.replan({
        'request': planBody,
        'context_change':
            ContextChangeModel(
              trafficChanged: true,
              contextSource: 'simulated',
              congestionDelta: 0.55,
              travelTimeDeltaMinutes: 22,
              description: 'SIMULATED e2e smoke spike',
            ).toJson(),
        'refresh_live_routes': false,
        'invoke_gemini': true,
      });
      stdout.writeln(
        'replan ok=${replan.ok} changed=${replan.recommendationChanged} '
        '${replan.previousRouteId} -> ${replan.newRouteId}',
      );
    }
  } finally {
    client.close();
  }
}
