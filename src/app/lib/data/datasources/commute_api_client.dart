import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../core/config/app_config.dart';
import '../../core/errors/api_exception.dart';
import '../models/commute_models.dart';

/// Single HTTP client for backend `/health`, `/plan`, `/replan`.
///
/// Widgets must not call this directly — go through the repository.
class CommuteApiClient {
  CommuteApiClient({
    required String baseUrl,
    http.Client? httpClient,
    Duration? timeout,
  })  : _baseUrl = AppConfig.normalizeBaseUrl(baseUrl),
        _http = httpClient ?? http.Client(),
        _timeout = timeout ?? const Duration(seconds: 120);

  final String _baseUrl;
  final http.Client _http;
  final Duration _timeout;

  Uri _uri(String path) => AppConfig.apiUri(_baseUrl, path);

  Future<Map<String, dynamic>> health() async {
    try {
      final res = await _http
          .get(_uri('/health'))
          .timeout(const Duration(seconds: 10));
      return _decodeMap(res);
    } on ApiException {
      rethrow;
    } on http.ClientException catch (e) {
      throw ApiException.network('Network failure: $e');
    } on TimeoutException catch (e) {
      throw ApiException.network('Request timed out: $e');
    }
  }

  Future<PlanResponseModel> plan(Map<String, dynamic> body) async {
    return _postModel('/plan', body, PlanResponseModel.fromJson);
  }

  Future<ReplanResponseModel> replan(Map<String, dynamic> body) async {
    return _postModel('/replan', body, ReplanResponseModel.fromJson);
  }

  Future<T> _postModel<T>(
    String path,
    Map<String, dynamic> body,
    T Function(Map<String, dynamic>) parse,
  ) async {
    try {
      final res = await _http
          .post(
            _uri(path),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode(body),
          )
          .timeout(_timeout);
      final map = _decodeMap(res, allowErrorBodies: true);
      final parsed = parse(map);
      if (res.statusCode >= 400) {
        final err = map['error'] as String?;
        final modelErr = _modelError(parsed);
        if (err == null && modelErr == null) {
          throw ApiException(
            statusCode: res.statusCode,
            message: _httpErrorMessage(res, map),
            errorCode: map['error'] as String?,
            body: map,
            kind: ApiErrorKind.backend,
          );
        }
      }
      return parsed;
    } on ApiException {
      rethrow;
    } on http.ClientException catch (e) {
      throw ApiException.network('Network failure: $e');
    } on TimeoutException catch (e) {
      throw ApiException.network('Request timed out: $e');
    }
  }

  String? _modelError(Object? parsed) {
    if (parsed is PlanResponseModel) return parsed.error;
    if (parsed is ReplanResponseModel) return parsed.error;
    return null;
  }

  Map<String, dynamic> _decodeMap(
    http.Response res, {
    bool allowErrorBodies = false,
  }) {
    late final Map<String, dynamic> map;
    try {
      if (res.body.isEmpty) {
        throw const FormatException('Empty response body');
      }
      final decoded = jsonDecode(res.body);
      if (decoded is! Map) {
        throw const FormatException('JSON root is not an object');
      }
      map = Map<String, dynamic>.from(decoded);
    } on FormatException catch (e) {
      throw ApiException.malformed(
        'Invalid JSON from API (${res.statusCode}): $e',
        statusCode: res.statusCode,
      );
    } catch (e) {
      if (e is ApiException) rethrow;
      throw ApiException.malformed(
        'Invalid JSON from API (${res.statusCode})',
        statusCode: res.statusCode,
      );
    }

    if (res.statusCode >= 400 && !allowErrorBodies) {
      throw ApiException(
        statusCode: res.statusCode,
        message: _httpErrorMessage(res, map),
        errorCode: map['error'] as String?,
        body: map,
        kind: ApiErrorKind.backend,
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

/// Historical name kept for existing imports.
typedef CommuteRemoteDataSource = CommuteApiClient;
