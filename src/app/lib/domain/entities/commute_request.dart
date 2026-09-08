import 'user_preferences.dart';

/// Input for planning a commute (domain request — not transport JSON).
class CommuteRequest {
  final String origin;
  final String destination;
  final String departureTimeIso8601;
  final UserPreferences preferences;
  final bool invokeGemini;

  const CommuteRequest({
    required this.origin,
    required this.destination,
    required this.departureTimeIso8601,
    required this.preferences,
    this.invokeGemini = true,
  });
}
