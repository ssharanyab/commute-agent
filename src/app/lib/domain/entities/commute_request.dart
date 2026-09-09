import 'user_preferences.dart';

/// Typed `/plan` request — fields match backend [PlanRequest] schema.
class CommuteRequest {
  final String origin;
  final String destination;
  final String? departureTimeIso8601;
  final UserPreferences preferences;
  final String? objective;
  final String? preferenceProfile;
  final String userId;
  final int? originZone;
  final int? destinationZone;
  final double? originLat;
  final double? originLon;
  final double? destinationLat;
  final double? destinationLon;
  final List<String>? modes;
  final bool invokeGemini;
  final bool invokeWeather;
  final bool invokeHistorical;
  final bool? invokeLiveTraffic;
  final bool allowLegacyMapsFallback;

  const CommuteRequest({
    required this.origin,
    required this.destination,
    this.departureTimeIso8601,
    required this.preferences,
    this.objective,
    this.preferenceProfile,
    this.userId = 'api-user',
    this.originZone,
    this.destinationZone,
    this.originLat,
    this.originLon,
    this.destinationLat,
    this.destinationLon,
    this.modes,
    this.invokeGemini = true,
    this.invokeWeather = true,
    this.invokeHistorical = true,
    this.invokeLiveTraffic,
    this.allowLegacyMapsFallback = true,
  });
}
