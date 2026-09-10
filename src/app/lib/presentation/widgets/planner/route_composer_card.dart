import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';

import '../../../data/places_api_client.dart';
import '../../theme/planner_tokens.dart';
import '../place_autocomplete_field.dart';

/// Unified origin → destination card with swap. Autocomplete behavior unchanged.
class RouteComposerCard extends StatelessWidget {
  const RouteComposerCard({
    super.key,
    required this.originKey,
    required this.destinationKey,
    required this.originController,
    required this.destinationController,
    required this.baseUrl,
    required this.onOriginResolved,
    required this.onDestinationResolved,
    required this.onSwap,
  });

  final GlobalKey<PlaceAutocompleteFieldState> originKey;
  final GlobalKey<PlaceAutocompleteFieldState> destinationKey;
  final TextEditingController originController;
  final TextEditingController destinationController;
  final String baseUrl;
  final ValueChanged<ResolvedPlace?> onOriginResolved;
  final ValueChanged<ResolvedPlace?> onDestinationResolved;
  final VoidCallback onSwap;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Semantics(
      container: true,
      label: 'Route from origin to destination',
      child: DecoratedBox(
        decoration: BoxDecoration(
          color: PlannerTokens.surface(scheme),
          borderRadius: BorderRadius.circular(PlannerTokens.radiusCard),
          border: Border.all(color: PlannerTokens.hairline(scheme)),
        ),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 10, 10, 12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(
                width: 28,
                child: Column(
                  children: [
                    const SizedBox(height: 18),
                    Icon(
                      CupertinoIcons.circle,
                      size: 14,
                      color: scheme.primary,
                    ),
                    Container(
                      width: 2,
                      height: 36,
                      margin: const EdgeInsets.symmetric(vertical: 4),
                      decoration: BoxDecoration(
                        color: scheme.primary.withValues(alpha: 0.35),
                        borderRadius: BorderRadius.circular(1),
                      ),
                    ),
                    Icon(
                      CupertinoIcons.placemark_fill,
                      size: 16,
                      color: scheme.primary,
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Column(
                  children: [
                    PlaceAutocompleteField(
                      key: originKey,
                      controller: originController,
                      baseUrl: baseUrl,
                      label: 'Origin',
                      hint: 'Where are you starting?',
                      prefixIcon: Icons.trip_origin,
                      embedded: true,
                      onPlaceResolved: onOriginResolved,
                      validator: (v) =>
                          (v == null || v.trim().isEmpty) ? 'Required' : null,
                    ),
                    const SizedBox(height: 4),
                    PlaceAutocompleteField(
                      key: destinationKey,
                      controller: destinationController,
                      baseUrl: baseUrl,
                      label: 'Destination',
                      hint: 'Where are you going?',
                      prefixIcon: Icons.flag_outlined,
                      embedded: true,
                      onPlaceResolved: onDestinationResolved,
                      validator: (v) =>
                          (v == null || v.trim().isEmpty) ? 'Required' : null,
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 4),
              Padding(
                padding: const EdgeInsets.only(top: 28),
                child: IconButton(
                  key: const Key('route_swap'),
                  tooltip: 'Swap origin and destination',
                  onPressed: onSwap,
                  style: IconButton.styleFrom(
                    minimumSize:
                        const Size(PlannerTokens.minTouch, PlannerTokens.minTouch),
                    backgroundColor: PlannerTokens.surfaceStrong(scheme),
                    foregroundColor: scheme.primary,
                  ),
                  icon: const Icon(CupertinoIcons.arrow_up_arrow_down, size: 18),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
