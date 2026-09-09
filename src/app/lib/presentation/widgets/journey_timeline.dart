import 'package:flutter/material.dart';

import '../../domain/entities/journey.dart';
import '../../domain/entities/journey_leg.dart';
import '../utils/labels.dart';
import '../utils/mode_presentation.dart';

/// Vertical timeline of backend journey legs — presentation only.
class JourneyTimeline extends StatelessWidget {
  const JourneyTimeline({super.key, required this.journey});

  final RecommendedJourney journey;

  @override
  Widget build(BuildContext context) {
    final legs = journey.legs;
    if (legs.isEmpty) {
      return Text(
        modeSequenceForJourney(journey),
        style: Theme.of(context).textTheme.bodyLarge,
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (var i = 0; i < legs.length; i++) ...[
          _LegTile(
            leg: legs[i],
            isLast: i == legs.length - 1,
          ),
          if (i < legs.length - 1)
            Padding(
              padding: const EdgeInsets.only(left: 18, top: 2, bottom: 2),
              child: Icon(
                Icons.arrow_downward,
                size: 16,
                color: Theme.of(context).colorScheme.outline,
              ),
            ),
        ],
      ],
    );
  }
}

class _LegTile extends StatelessWidget {
  const _LegTile({required this.leg, required this.isLast});

  final JourneyLeg leg;
  final bool isLast;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final metrics = <String>[
      if (legDurationLabel(leg) != null) legDurationLabel(leg)!,
      if (legDistanceLabel(leg) != null) legDistanceLabel(leg)!,
      if (legCostLabel(leg) != null) legCostLabel(leg)!,
    ];

    var title = '${modeEmoji(leg.mode)} ${modeLabel(leg.mode)}';
    if (isLast &&
        (leg.mode.toLowerCase() == 'walk' ||
            leg.mode.toLowerCase() == 'walking')) {
      title = '${modeEmoji(leg.mode)} Walk to destination';
    }

    final detail = <String>[
      if (leg.provider != null && leg.provider!.trim().isNotEmpty)
        leg.provider!,
      if (leg.routeId != null &&
          leg.routeId!.trim().isNotEmpty &&
          leg.routeId != leg.provider)
        leg.routeId!,
    ];

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(modeEmoji(leg.mode), style: const TextStyle(fontSize: 22)),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: Theme.of(context).textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
              ),
              if (detail.isNotEmpty)
                Text(
                  detail.join(' · '),
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: scheme.onSurfaceVariant,
                      ),
                ),
              if (metrics.isNotEmpty)
                Text(
                  metrics.join(' · '),
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
            ],
          ),
        ),
      ],
    );
  }
}
