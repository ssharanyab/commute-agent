// Live smoke against a running API. Run:
//   fvm dart run --dart-define=API_BASE_URL=http://127.0.0.1:8000 tool/e2e_smoke.dart
import 'dart:convert';
import 'dart:io';

import 'package:commute_agent/api_client.dart';
import 'package:commute_agent/config.dart';
import 'package:commute_agent/departure_time.dart';
import 'package:commute_agent/models.dart';

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

  final client = CommuteApiClient(baseUrl: base);
  try {
    final health = await client.health();
    stdout.writeln('health: ${jsonEncode(health)}');

    final planBody = {
      'origin': 'Electronic City, Bengaluru',
      'destination': 'Koramangala, Bengaluru',
      'departure_time': BengaluruDeparture.resolveForPlan(
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
    stdout.writeln('PLAN ok=${plan.ok} error=${plan.error}');
    stdout.writeln(
      '  rec=${plan.recommendation?.routeId} '
      'mode=${plan.recommendation?.mode} '
      'min=${plan.recommendation?.travelTimeMinutes}',
    );
    stdout.writeln('  sources=${plan.dataSources}');
    stdout.writeln(
      '  gemini available=${plan.gemini.available} '
      'invoked=${plan.gemini.invoked} mode=${plan.gemini.mode}',
    );
    stdout.writeln(
      '  explanation_len=${plan.explanation.length} '
      'alts=${plan.alternatives.length}',
    );

    final replan = await client.replan({
      'request': planBody,
      'context_change': ContextChangePayload(
        trafficChanged: true,
        contextSource: 'simulated',
        congestionDelta: 0.55,
        travelTimeDeltaMinutes: 22,
        description: 'SIMULATED demo traffic spike',
      ).toJson(),
      'invoke_gemini': true,
    });
    stdout.writeln(
      'REPLAN ok=${replan.ok} changed=${replan.recommendationChanged} '
      'error=${replan.error}',
    );
    stdout.writeln(
      '  ${replan.previousRouteId} -> ${replan.newRouteId}',
    );
    stdout.writeln(
      '  gemini available=${replan.gemini.available} '
      'invoked=${replan.gemini.invoked} mode=${replan.gemini.mode}',
    );
    stdout.writeln('  explanation_len=${replan.explanation.length}');
    stdout.writeln('  sources=${replan.dataSources}');

    if (!plan.ok) {
      exit(1);
    }
    if (!replan.ok) {
      exit(1);
    }
  } finally {
    client.close();
  }
}
