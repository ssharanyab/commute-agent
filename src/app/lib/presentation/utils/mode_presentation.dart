import '../../domain/entities/commute_route.dart';
import '../../domain/entities/journey.dart';
import '../../domain/entities/journey_leg.dart';
import '../../domain/entities/top_journey.dart';
import 'labels.dart';

/// User-facing emoji for a backend mode token.
String modeEmoji(String mode) {
  switch (mode.trim().toLowerCase()) {
    case 'bus':
    case 'bmtc':
      return '🚌';
    case 'metro':
    case 'bmrcl':
    case 'subway':
    case 'rail':
      return '🚇';
    case 'walk':
    case 'walking':
      return '🚶';
    case 'auto':
    case 'auto_rickshaw':
    case 'rickshaw':
      return '🛺';
    case 'cab':
    case 'taxi':
    case 'drive':
    case 'rideshare':
    case 'uber':
    case 'ola':
      return '🚕';
    case 'hybrid':
      return '🔀';
    default:
      return '🚏';
  }
}

String modeChip(String mode) => '${modeEmoji(mode)} ${modeLabel(mode)}';

/// Dynamic mode sequence from backend mode tokens (not hardcoded combinations).
String modeSequenceFromModes(Iterable<String> modes) {
  final parts = modes
      .map((m) => m.trim())
      .where((m) => m.isNotEmpty)
      .map(modeChip)
      .toList();
  if (parts.isEmpty) return 'Route';
  return parts.join(' → ');
}

String modeSequenceFromSignature(String signature) {
  if (signature.trim().isEmpty) return 'Route';
  final tokens = signature
      .split(RegExp(r'\s*→\s*|\s*>\s*|\s*\|\s*|\s*,\s*'))
      .map((s) => s.trim())
      .where((s) => s.isNotEmpty);
  return modeSequenceFromModes(tokens);
}

String modeSequenceForRoute(CommuteRoute route) {
  if (route.componentModes.isNotEmpty) {
    return modeSequenceFromModes(route.componentModes);
  }
  if (route.modeSignature.isNotEmpty) {
    return modeSequenceFromSignature(route.modeSignature);
  }
  return modeChip(route.mode);
}

String modeSequenceForJourney(RecommendedJourney journey) {
  if (journey.modes.isNotEmpty) {
    return modeSequenceFromModes(journey.modes);
  }
  if (journey.legs.isNotEmpty) {
    return modeSequenceFromModes(journey.legs.map((l) => l.mode));
  }
  if (journey.modeSignature.isNotEmpty) {
    return modeSequenceFromSignature(journey.modeSignature);
  }
  return 'Route';
}

String modeSequenceForTopOption(TopJourneyOption option) {
  if (option.componentModes.isNotEmpty) {
    return modeSequenceFromModes(option.componentModes);
  }
  if (option.modeSignature.isNotEmpty) {
    return modeSequenceFromSignature(option.modeSignature);
  }
  if (option.diversitySignature.isNotEmpty) {
    return modeSequenceFromSignature(option.diversitySignature);
  }
  return modeChip(option.mode);
}

String? legDurationLabel(JourneyLeg leg) {
  if (leg.durationStatus.name == 'known' && leg.durationSeconds != null) {
    final mins = leg.durationSeconds! / 60.0;
    if (mins <= 0) return null;
    return '${mins < 1 ? mins.toStringAsFixed(1) : mins.toStringAsFixed(0)} min';
  }
  if (leg.durationSeconds != null && leg.durationSeconds! > 0) {
    final mins = leg.durationSeconds! / 60.0;
    return '~${mins < 1 ? mins.toStringAsFixed(1) : mins.toStringAsFixed(0)} min';
  }
  return null;
}

String? legDistanceLabel(JourneyLeg leg) {
  final m =
      leg.distanceMeters ?? (leg.walkingMeters > 0 ? leg.walkingMeters : null);
  if (m == null || m <= 0) return null;
  if (m >= 1000) return '${(m / 1000).toStringAsFixed(1)} km';
  return '${m.round()} m';
}

String? legCostLabel(JourneyLeg leg) {
  if (leg.costStatus.name != 'known') return null;
  if (leg.costInr == null) return null;
  return '₹${leg.costInr!.toStringAsFixed(0)}';
}

String walkingSummary({
  required double walkingMinutes,
  double? walkingMeters,
}) {
  if (walkingMeters != null && walkingMeters > 0) {
    final dist = walkingMeters >= 1000
        ? '${(walkingMeters / 1000).toStringAsFixed(1)} km'
        : '${walkingMeters.round()} m';
    return '$dist walking';
  }
  if (walkingMinutes > 0) {
    return '${walkingMinutes.toStringAsFixed(0)} min walking';
  }
  return 'No walking';
}

/// Omit when walking distance is unknown (never invent 0 m).
String? walkingMetricLabel(double? walkingMeters) {
  if (walkingMeters == null) return null;
  if (walkingMeters <= 0) return 'No walking';
  final dist = walkingMeters >= 1000
      ? '${(walkingMeters / 1000).toStringAsFixed(1)} km'
      : '${walkingMeters.round()} m';
  return '$dist walking';
}

String? transferMetricLabel(int transfers) {
  if (transfers <= 0) return null;
  if (transfers == 1) return '1 transfer';
  return '$transfers transfers';
}

String transferSummary(int transfers) {
  if (transfers <= 0) return 'No transfers';
  if (transfers == 1) return '1 transfer';
  return '$transfers transfers';
}

String displayReason(String? reason) {
  final text = (reason ?? '').trim();
  if (text.isEmpty) return 'Another option';
  return text;
}

/// Google Maps travelmode for OD handoff (not a new routing decision).
String mapsTravelModeFor(CommuteRoute? route, RecommendedJourney? journey) {
  final modes = <String>[
    ...?journey?.modes,
    ...?route?.componentModes,
    if (route != null) route.mode,
  ].map((m) => m.toLowerCase()).toList();
  return mapsTravelModeForModes(modes);
}

String mapsTravelModeForTopOption(TopJourneyOption option) {
  final modes = <String>[
    ...option.componentModes,
    if (option.mode.isNotEmpty) option.mode,
  ].map((m) => m.toLowerCase()).toList();
  return mapsTravelModeForModes(modes);
}

String mapsTravelModeForModes(List<String> modes) {
  if (modes.any((m) => m.contains('walk')) &&
      modes.every((m) => m.contains('walk') || m.isEmpty)) {
    return 'walking';
  }
  if (modes.any((m) =>
      m.contains('bus') ||
      m.contains('metro') ||
      m.contains('bmtc') ||
      m.contains('transit'))) {
    return 'transit';
  }
  if (modes.any((m) =>
      m.contains('cab') ||
      m.contains('drive') ||
      m.contains('auto') ||
      m.contains('taxi'))) {
    return 'driving';
  }
  return 'driving';
}

Uri googleMapsDirectionsUri({
  required String origin,
  required String destination,
  String travelMode = 'driving',
}) {
  return Uri.parse(
    'https://www.google.com/maps/dir/?api=1'
    '&origin=${Uri.encodeComponent(origin)}'
    '&destination=${Uri.encodeComponent(destination)}'
    '&travelmode=$travelMode',
  );
}
