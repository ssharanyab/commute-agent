import 'dart:convert';

import 'package:http/http.dart' as http;

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

/// Resolved place with coordinates (from Places Details).
class ResolvedPlace {
  final String placeId;
  final String name;
  final String formattedAddress;
  final double latitude;
  final double longitude;

  const ResolvedPlace({
    required this.placeId,
    required this.name,
    required this.formattedAddress,
    required this.latitude,
    required this.longitude,
  });

  String get displayLabel =>
      name.trim().isNotEmpty ? name : formattedAddress;

  factory ResolvedPlace.fromJson(Map<String, dynamic> json) {
    return ResolvedPlace(
      placeId: (json['place_id'] as String?) ?? '',
      name: (json['name'] as String?) ?? '',
      formattedAddress: (json['formatted_address'] as String?) ?? '',
      latitude: (json['latitude'] as num).toDouble(),
      longitude: (json['longitude'] as num).toDouble(),
    );
  }
}

/// HTTP client for `/places/autocomplete` and `/places/details`.
class PlacesApiClient {
  PlacesApiClient({http.Client? httpClient}) : _http = httpClient ?? http.Client();

  final http.Client _http;

  Future<List<PlaceSuggestion>> autocomplete({
    required String baseUrl,
    required String query,
    int limit = 6,
  }) async {
    final q = query.trim();
    if (q.length < 2) return const [];
    final uri = Uri.parse('$baseUrl/places/autocomplete').replace(
      queryParameters: {
        'q': q,
        'limit': '$limit',
      },
    );
    final res = await _http.get(uri).timeout(const Duration(seconds: 8));
    if (res.statusCode < 200 || res.statusCode >= 300) {
      return const [];
    }
    final body = jsonDecode(res.body);
    if (body is! Map) return const [];
    final raw = body['suggestions'];
    if (raw is! List) return const [];
    return [
      for (final item in raw)
        if (item is Map)
          PlaceSuggestion.fromJson(Map<String, dynamic>.from(item)),
    ];
  }

  Future<ResolvedPlace?> details({
    required String baseUrl,
    required String placeId,
  }) async {
    final id = placeId.trim();
    if (id.isEmpty) return null;
    final uri = Uri.parse('$baseUrl/places/details').replace(
      queryParameters: {'place_id': id},
    );
    final res = await _http.get(uri).timeout(const Duration(seconds: 8));
    if (res.statusCode < 200 || res.statusCode >= 300) return null;
    final body = jsonDecode(res.body);
    if (body is! Map || body['ok'] != true) return null;
    final place = body['place'];
    if (place is! Map) return null;
    return ResolvedPlace.fromJson(Map<String, dynamic>.from(place));
  }
}
