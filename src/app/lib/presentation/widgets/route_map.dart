import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';

import '../../core/utils/polyline_decoder.dart';

/// Renders Google-encoded polyline geometry for the selected route.
///
/// Does not call routing APIs. Expects the backend-provided encoded polyline.
class RouteMap extends StatefulWidget {
  const RouteMap({
    super.key,
    required this.encodedPolyline,
    this.height = 220,
  });

  final String? encodedPolyline;
  final double height;

  @override
  State<RouteMap> createState() => _RouteMapState();
}

class _RouteMapState extends State<RouteMap> {
  GoogleMapController? _controller;

  bool get _mapsSupported {
    if (kIsWeb) return false;
    try {
      return Platform.isAndroid || Platform.isIOS;
    } catch (_) {
      return false;
    }
  }

  @override
  void dispose() {
    _controller?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final points = decodeGooglePolyline(widget.encodedPolyline);
    if (points.isEmpty) {
      return _Fallback(
        height: widget.height,
        message: 'Route preview unavailable',
      );
    }

    if (!_mapsSupported) {
      return _PolylineSketch(height: widget.height, points: points);
    }

    final latLngs = points
        .map((p) => LatLng(p.latitude, p.longitude))
        .toList(growable: false);
    final bounds = boundsFor(points)!;
    final center = LatLng(
      (bounds.minLat + bounds.maxLat) / 2,
      (bounds.minLng + bounds.maxLng) / 2,
    );

    return SizedBox(
      height: widget.height,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(16),
        child: GoogleMap(
          initialCameraPosition: CameraPosition(target: center, zoom: 12),
          polylines: {
            Polyline(
              polylineId: const PolylineId('selected_route'),
              points: latLngs,
              color: const Color(0xFF0F6E56),
              width: 5,
            ),
          },
          markers: {
            Marker(
              markerId: const MarkerId('origin'),
              position: latLngs.first,
              infoWindow: const InfoWindow(title: 'Start'),
            ),
            Marker(
              markerId: const MarkerId('destination'),
              position: latLngs.last,
              infoWindow: const InfoWindow(title: 'Destination'),
            ),
          },
          myLocationButtonEnabled: false,
          compassEnabled: false,
          mapToolbarEnabled: false,
          zoomControlsEnabled: false,
          onMapCreated: (c) async {
            _controller = c;
            await Future<void>.delayed(const Duration(milliseconds: 80));
            try {
              await c.animateCamera(
                CameraUpdate.newLatLngBounds(
                  LatLngBounds(
                    southwest: LatLng(bounds.minLat, bounds.minLng),
                    northeast: LatLng(bounds.maxLat, bounds.maxLng),
                  ),
                  48,
                ),
              );
            } catch (_) {
              // Bounds animation can fail on tiny segments — keep center.
            }
          },
        ),
      ),
    );
  }
}

class _Fallback extends StatelessWidget {
  const _Fallback({required this.height, required this.message});

  final double height;
  final String message;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      height: height,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: scheme.surfaceContainerHighest.withValues(alpha: 0.7),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.map_outlined, color: scheme.onSurfaceVariant, size: 36),
          const SizedBox(height: 8),
          Text(
            message,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: scheme.onSurfaceVariant,
                ),
          ),
        ],
      ),
    );
  }
}

/// Lightweight sketch of decoded Google geometry when Maps SDK is unavailable.
class _PolylineSketch extends StatelessWidget {
  const _PolylineSketch({required this.height, required this.points});

  final double height;
  final List<LatLngPoint> points;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      height: height,
      decoration: BoxDecoration(
        color: scheme.surfaceContainerHighest.withValues(alpha: 0.55),
        borderRadius: BorderRadius.circular(16),
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(16),
        child: CustomPaint(
          painter: _SketchPainter(points: points, color: scheme.primary),
          child: const SizedBox.expand(),
        ),
      ),
    );
  }
}

class _SketchPainter extends CustomPainter {
  _SketchPainter({required this.points, required this.color});

  final List<LatLngPoint> points;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final bounds = boundsFor(points);
    if (bounds == null || points.length < 2) return;
    final pad = 24.0;
    final latSpan = (bounds.maxLat - bounds.minLat).abs().clamp(0.0001, 90.0);
    final lngSpan = (bounds.maxLng - bounds.minLng).abs().clamp(0.0001, 180.0);

    Offset map(LatLngPoint p) {
      final x = pad +
          (p.longitude - bounds.minLng) / lngSpan * (size.width - 2 * pad);
      final y = pad +
          (bounds.maxLat - p.latitude) / latSpan * (size.height - 2 * pad);
      return Offset(x, y);
    }

    final path = Path()..moveTo(map(points.first).dx, map(points.first).dy);
    for (var i = 1; i < points.length; i++) {
      final o = map(points[i]);
      path.lineTo(o.dx, o.dy);
    }
    canvas.drawPath(
      path,
      Paint()
        ..color = color
        ..style = PaintingStyle.stroke
        ..strokeWidth = 4
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round,
    );
  }

  @override
  bool shouldRepaint(covariant _SketchPainter oldDelegate) =>
      oldDelegate.points != points || oldDelegate.color != color;
}
