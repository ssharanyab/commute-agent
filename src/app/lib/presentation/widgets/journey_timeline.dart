import 'package:flutter/material.dart';

import '../../domain/entities/journey.dart';
import '../../domain/entities/journey_leg.dart';
import '../../domain/entities/journey_step.dart';
import '../utils/labels.dart';
import '../utils/mode_presentation.dart';

/// Vertical timeline of backend journey steps — presentation only.
/// Prefer structured [JourneyStep]s; fall back to leg tiles when absent.
class JourneyTimeline extends StatelessWidget {
  const JourneyTimeline({
    super.key,
    this.journey,
    this.steps = const [],
  });

  final RecommendedJourney? journey;
  final List<JourneyStep> steps;

  List<JourneyStep> get _resolvedSteps {
    if (steps.isNotEmpty) return steps;
    return journey?.steps ?? const [];
  }

  @override
  Widget build(BuildContext context) {
    final resolved = _resolvedSteps;
    if (resolved.isNotEmpty) {
      return _StepsColumn(steps: resolved);
    }

    final legs = journey?.legs ?? const <JourneyLeg>[];
    if (legs.isEmpty) {
      if (journey == null) {
        return const SizedBox.shrink();
      }
      return Text(
        modeSequenceForJourney(journey!),
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

class _StepsColumn extends StatelessWidget {
  const _StepsColumn({required this.steps});

  final List<JourneyStep> steps;

  @override
  Widget build(BuildContext context) {
    return Column(
      key: const Key('journey_steps_timeline'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (var i = 0; i < steps.length; i++) ...[
          if (steps[i].isTransfer)
            _TransferTile(step: steps[i])
          else
            _StepLegTile(step: steps[i]),
          if (i < steps.length - 1)
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

class _StepLegTile extends StatelessWidget {
  const _StepLegTile({required this.step});

  final JourneyStep step;

  @override
  Widget build(BuildContext context) {
    final mode = step.mode ?? '';
    return Row(
      key: Key('journey_step_leg_${step.instruction}'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(modeEmoji(mode), style: const TextStyle(fontSize: 22)),
        const SizedBox(width: 12),
        Expanded(
          child: Text(
            step.instruction,
            style: Theme.of(context).textTheme.titleSmall?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
          ),
        ),
      ],
    );
  }
}

class _TransferTile extends StatelessWidget {
  const _TransferTile({required this.step});

  final JourneyStep step;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final location = step.locationName?.trim();
    final modeLine = [
      if (step.fromMode != null && step.fromMode!.isNotEmpty)
        modeLabel(step.fromMode!),
      if (step.toMode != null && step.toMode!.isNotEmpty)
        modeLabel(step.toMode!),
    ].join(' → ');

    return Container(
      key: const Key('journey_step_transfer'),
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: scheme.surfaceContainerHighest.withValues(alpha: 0.55),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: scheme.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'CHANGE HERE',
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  fontWeight: FontWeight.w800,
                  letterSpacing: 0.8,
                  color: scheme.primary,
                ),
          ),
          if (location != null &&
              location.isNotEmpty &&
              !location.toLowerCase().contains('unknown')) ...[
            const SizedBox(height: 2),
            Text(
              location,
              style: Theme.of(context).textTheme.titleSmall?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
            ),
          ],
          if (modeLine.isNotEmpty) ...[
            const SizedBox(height: 2),
            Text(
              modeLine,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: scheme.onSurfaceVariant,
                  ),
            ),
          ],
          const SizedBox(height: 4),
          Text(
            step.instruction,
            style: Theme.of(context).textTheme.bodyMedium,
          ),
        ],
      ),
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
                  style: Theme.of(context).textTheme.bodySmall,
                ),
            ],
          ),
        ),
      ],
    );
  }
}
