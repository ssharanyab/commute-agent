import 'dart:convert';

import 'package:http/http.dart' as http;

import 'config.dart';
import 'models.dart';

class CommuteApiClient {
  CommuteApiClient({
    required String baseUrl,
    http.Client? httpClient,
  })  : _baseUrl = AppConfig.normalizeBaseUrl(baseUrl),
        _http = httpClient ?? http.Client();

  final String _baseUrl;
  final http.Client _http;

  Uri _uri(String path) => Uri.parse('$_baseUrl$path');

  Future<Map<String, dynamic>> health() async {
    final res = await _http.get(_uri('/health')).timeout(
      const Duration(seconds: 10),
    );
    return _decodeMap(res);
  }

  Future<PlanResponse> plan(Map<String, dynamic> body) async {
    final res = await _http
        .post(
          _uri('/plan'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode(body),
        )
        .timeout(const Duration(seconds: 120));
    final map = _decodeMap(res, allowErrorBodies: true);
    final parsed = PlanResponse.fromJson(map);
    if (res.statusCode >= 400 && parsed.error == null) {
      throw ApiException(
        statusCode: res.statusCode,
        message: _httpErrorMessage(res, map),
        body: map,
      );
    }
    return parsed;
  }

  Future<ReplanResponse> replan(Map<String, dynamic> body) async {
    final res = await _http
        .post(
          _uri('/replan'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode(body),
        )
        .timeout(const Duration(seconds: 120));
    final map = _decodeMap(res, allowErrorBodies: true);
    final parsed = ReplanResponse.fromJson(map);
    if (res.statusCode >= 400 && parsed.error == null) {
      throw ApiException(
        statusCode: res.statusCode,
        message: _httpErrorMessage(res, map),
        body: map,
      );
    }
    return parsed;
  }

  Map<String, dynamic> _decodeMap(
    http.Response res, {
    bool allowErrorBodies = false,
  }) {
    Map<String, dynamic>? map;
    try {
      final decoded = jsonDecode(res.body);
      if (decoded is Map) {
        map = Map<String, dynamic>.from(decoded);
      }
    } catch (_) {
      map = null;
    }

    if (res.statusCode >= 400 && !allowErrorBodies) {
      throw ApiException(
        statusCode: res.statusCode,
        message: _httpErrorMessage(res, map),
        errorCode: map?['error'] as String?,
        body: map,
      );
    }
    if (map == null) {
      throw ApiException(
        statusCode: res.statusCode,
        message: 'Invalid JSON from API (${res.statusCode})',
      );
    }
    return map;
  }

  String _httpErrorMessage(http.Response res, Map<String, dynamic>? map) {
    if (map == null) {
      return 'HTTP ${res.statusCode}: ${res.body}';
    }
    final detail = map['detail'];
    if (detail != null) return 'HTTP ${res.statusCode}: $detail';
    final err = map['error'];
    final ed = map['error_detail'];
    if (err != null) {
      return ed != null ? '$err — $ed' : '$err';
    }
    return 'HTTP ${res.statusCode}';
  }

  void close() => _http.close();
}
