import 'dart:math' as math;

/// Decoded latitude/longitude from a Google encoded polyline.
class LatLngPoint {
  final double latitude;
  final double longitude;

  const LatLngPoint(this.latitude, this.longitude);
}

/// Decodes Google's encoded polyline algorithm into lat/lng points.
/// Does not fabricate geometry — returns empty if the string is invalid/empty.
List<LatLngPoint> decodeGooglePolyline(String? encoded) {
  if (encoded == null || encoded.trim().isEmpty) return const [];
  final points = <LatLngPoint>[];
  var index = 0;
  var lat = 0;
  var lng = 0;
  final len = encoded.length;

  try {
    while (index < len) {
      var shift = 0;
      var result = 0;
      int b;
      do {
        b = encoded.codeUnitAt(index++) - 63;
        result |= (b & 0x1f) << shift;
        shift += 5;
      } while (b >= 0x20);
      final dlat = ((result & 1) != 0) ? ~(result >> 1) : (result >> 1);
      lat += dlat;

      shift = 0;
      result = 0;
      do {
        b = encoded.codeUnitAt(index++) - 63;
        result |= (b & 0x1f) << shift;
        shift += 5;
      } while (b >= 0x20);
      final dlng = ((result & 1) != 0) ? ~(result >> 1) : (result >> 1);
      lng += dlng;

      points.add(LatLngPoint(lat / 1e5, lng / 1e5));
    }
  } catch (_) {
    return const [];
  }
  return points;
}

/// Bounding box for fitting a camera (minLat, maxLat, minLng, maxLng).
({double minLat, double maxLat, double minLng, double maxLng})? boundsFor(
  List<LatLngPoint> points,
) {
  if (points.isEmpty) return null;
  var minLat = points.first.latitude;
  var maxLat = points.first.latitude;
  var minLng = points.first.longitude;
  var maxLng = points.first.longitude;
  for (final p in points) {
    minLat = math.min(minLat, p.latitude);
    maxLat = math.max(maxLat, p.latitude);
    minLng = math.min(minLng, p.longitude);
    maxLng = math.max(maxLng, p.longitude);
  }
  return (minLat: minLat, maxLat: maxLat, minLng: minLng, maxLng: maxLng);
}
