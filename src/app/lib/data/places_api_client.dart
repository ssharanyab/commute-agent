import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import '../core/config/app_config.dart';

/// Place suggestion from backend Places Autocomplete proxy.
class PlaceSuggestion {
  final String placeId;
  final String description;
  final String mainText;
  final String secondaryText;

  const PlaceSuggestion({
    required this.placeId,
    required this.description,
    required this.mainText,
    this.secondaryText = '',
  });

  factory PlaceSuggestion.fromJson(Map<String, dynamic> json) {
    return PlaceSuggestion(
      placeId: (json['place_id'] as String?) ?? '',
      description: (json['description'] as String?) ?? '',
      mainText: (json['main_text'] as String?) ?? '',
      secondaryText: (json['secondary_text'] as String?) ?? '',
    );
  }
}

/// Optional published mobility-node match from Places details.
class NetworkNodeRef {
  final String kind;
  final String network;
  final String nodeId;
  final double? lat;
  final double? lon;
  final String? placeId;
  final String? displayName;

  const NetworkNodeRef({
    required this.kind,
    required this.network,
    required this.nodeId,
    this.lat,
    this.lon,
    this.placeId,
    this.displayName,
  });

  factory NetworkNodeRef.fromJson(Map<String, dynamic> json) {
    return NetworkNodeRef(
      kind: (json['kind'] as String?) ?? 'network_node',
      network: (json['network'] as String?) ?? '',
      nodeId: (json['node_id'] as String?) ?? '',
      lat: (json['lat'] as num?)?.toDouble(),
      lon: (json['lon'] as num?)?.toDouble(),
      placeId: json['place_id'] as String?,
      displayName: json['display_name'] as String?,
    );
  }

  Map<String, dynamic> toJson() => {
        'kind': kind,
        'network': network,
        'node_id': nodeId,
        if (lat != null) 'lat': lat,
        if (lon != null) 'lon': lon,
        if (placeId != null) 'place_id': placeId,
        if (displayName != null) 'display_name': displayName,
      };
}

/// Resolved place with coordinates (from Places Details).
class ResolvedPlace {
  final String placeId;
  final String name;
  final String formattedAddress;
  final double latitude;
  final double longitude;
  final NetworkNodeRef? networkNode;

  const ResolvedPlace({
    required this.placeId,
    required this.name,
    required this.formattedAddress,
    required this.latitude,
    required this.longitude,
    this.networkNode,
  });

  String get displayLabel =>
      name.trim().isNotEmpty ? name : formattedAddress;

  bool get isNetworkNode =>
      networkNode != null && networkNode!.nodeId.trim().isNotEmpty;

  factory ResolvedPlace.fromJson(
    Map<String, dynamic> json, {
    Map<String, dynamic>? networkNodeJson,
  }) {
    NetworkNodeRef? node;
    final rawNode = networkNodeJson ?? json['network_node'];
    if (rawNode is Map) {
      node = NetworkNodeRef.fromJson(Map<String, dynamic>.from(rawNode));
      if (node.nodeId.trim().isEmpty) node = null;
    }
    return ResolvedPlace(
      placeId: (json['place_id'] as String?) ?? '',
      name: (json['name'] as String?) ?? '',
      formattedAddress: (json['formatted_address'] as String?) ?? '',
      latitude: (json['latitude'] as num).toDouble(),
      longitude: (json['longitude'] as num).toDouble(),
      networkNode: node,
    );
  }

  Map<String, dynamic> toEndpointJson() {
    if (isNetworkNode) {
      final n = networkNode!;
      return {
        'kind': 'network_node',
        'network': n.network,
        'node_id': n.nodeId,
        'lat': latitude,
        'lon': longitude,
        'place_id': placeId,
        'display_name': displayLabel,
      };
    }
    return {
      'kind': 'place',
      'lat': latitude,
      'lon': longitude,
      'place_id': placeId,
      'display_name': displayLabel,
    };
  }
}

/// HTTP client for `/places/autocomplete` and `/places/details`.
class PlacesApiClient {
  PlacesApiClient({
    http.Client? httpClient,
    Duration? requestTimeout,
  })  : _ownsClient = httpClient == null,
        _timeout = requestTimeout ?? const Duration(seconds: 15),
        _http = httpClient ?? http.Client();

  final bool _ownsClient;
  final Duration _timeout;
  http.Client _http;

  /// Rotate the HTTP client (base-URL change / select / retry). Do **not** call
  /// this on every keystroke — closing mid-TLS handshake cancels connections
  /// and shows up as TimeoutException on Android emulators.
  void abortInFlight() {
    if (!_ownsClient) return;
    try {
      _http.close();
    } catch (_) {}
    _http = http.Client();
    debugPrint('[Places] rotated HTTP client');
  }

  /// Best-effort wake of backend so the first autocomplete is less likely
  /// to hit a cold-start / DNS stall.
  Future<void> warmUp(String baseUrl) async {
    final uri = AppConfig.apiUri(baseUrl, '/health');
    debugPrint('[Places] warmUp GET $uri');
    try {
      final res = await _http.get(uri).timeout(const Duration(seconds: 8));
      debugPrint('[Places] warmUp http=${res.statusCode}');
    } catch (e) {
      debugPrint('[Places] warmUp failed (non-fatal): $e');
    }
  }

  Future<List<PlaceSuggestion>> autocomplete({
    required String baseUrl,
    required String query,
    int limit = 6,
  }) async {
    final q = query.trim();
    if (q.length < 2) {
      debugPrint('[Places] autocomplete skip q too short len=${q.length}');
      return const [];
    }
    final uri = AppConfig.apiUri(
      baseUrl,
      '/places/autocomplete',
      {'q': q, 'limit': '$limit'},
    );
    Object? lastError;
    for (var attempt = 1; attempt <= 2; attempt++) {
      final sw = Stopwatch()..start();
      debugPrint(
        '[Places] GET $uri (timeout=${_timeout.inSeconds}s attempt=$attempt)',
      );
      try {
        final res = await _http.get(uri).timeout(_timeout);
        debugPrint(
          '[Places] autocomplete http=${res.statusCode} '
          'bytes=${res.bodyBytes.length} elapsedMs=${sw.elapsedMilliseconds}',
        );
        if (res.statusCode < 200 || res.statusCode >= 300) {
          debugPrint(
            '[Places] autocomplete HTTP error body='
            '${res.body.length > 400 ? '${res.body.substring(0, 400)}…' : res.body}',
          );
          return const [];
        }
        final decoded = jsonDecode(res.body);
        if (decoded is! Map) {
          debugPrint('[Places] autocomplete parse: body not a Map');
          return const [];
        }
        final body = Map<String, dynamic>.from(decoded);
        final ok = body['ok'] == true;
        final err = body['error'];
        final configured = body['configured'];
        final raw = body['suggestions'];
        final count = raw is List ? raw.length : 0;
        debugPrint(
          '[Places] autocomplete ok=$ok error=$err configured=$configured '
          'suggestions=$count elapsedMs=${sw.elapsedMilliseconds}',
        );
        if (!ok || err != null) {
          debugPrint('[Places] autocomplete backend error detail: $err');
        }
        if (raw is! List) return const [];
        return [
          for (final item in raw)
            if (item is Map)
              PlaceSuggestion.fromJson(Map<String, dynamic>.from(item)),
        ];
      } catch (e, st) {
        lastError = e;
        debugPrint(
          '[Places] autocomplete exception after ${sw.elapsedMilliseconds}ms '
          'attempt=$attempt: $e',
        );
        if (!_isRetriableNetworkError(e) || attempt == 2) {
          debugPrint('[Places] $st');
          rethrow;
        }
        abortInFlight();
        await Future<void>.delayed(const Duration(milliseconds: 250));
      }
    }
    throw lastError ?? StateError('autocomplete failed');
  }

  Future<ResolvedPlace?> details({
    required String baseUrl,
    required String placeId,
  }) async {
    final id = placeId.trim();
    if (id.isEmpty) return null;
    final uri = AppConfig.apiUri(
      baseUrl,
      '/places/details',
      {'place_id': id},
    );
    debugPrint('[Places] GET $uri (timeout=${_timeout.inSeconds}s)');
    final res = await _http.get(uri).timeout(_timeout);
    if (res.statusCode < 200 || res.statusCode >= 300) return null;
    final body = jsonDecode(res.body);
    if (body is! Map || body['ok'] != true) return null;
    final place = body['place'];
    if (place is! Map) return null;
    final networkNode = body['network_node'];
    return ResolvedPlace.fromJson(
      Map<String, dynamic>.from(place),
      networkNodeJson: networkNode is Map
          ? Map<String, dynamic>.from(networkNode)
          : null,
    );
  }

  void close() {
    if (!_ownsClient) return;
    try {
      _http.close();
    } catch (_) {}
  }

  static bool _isRetriableNetworkError(Object e) {
    final s = e.toString();
    return e is TimeoutException ||
        s.contains('TimeoutException') ||
        s.contains('SocketException') ||
        s.contains('ClientException') ||
        s.contains('Connection attempt cancelled') ||
        s.contains('Connection closed') ||
        s.contains('Failed host lookup');
  }
}
