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
    final networkNode = body['network_node'];
    return ResolvedPlace.fromJson(
      Map<String, dynamic>.from(place),
      networkNodeJson: networkNode is Map
          ? Map<String, dynamic>.from(networkNode)
          : null,
    );
  }
}
