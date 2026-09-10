import 'package:flutter/material.dart';

import '../../domain/entities/journey.dart';
import '../../domain/entities/journey_leg.dart';
import '../../domain/entities/journey_step.dart';
import '../theme/result_tokens.dart';
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
        for (var i = 0; i < legs.length; i++)
          _TimelineEntry(
            isLast: i == legs.length - 1,
            isEmphasis: i == 0 || i == legs.length - 1,
            leading: Text(
              modeEmoji(legs[i].mode),
              style: const TextStyle(fontSize: 20),
            ),
            child: _LegBody(leg: legs[i], isLast: i == legs.length - 1),
          ),
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
        for (var i = 0; i < steps.length; i++)
          if (steps[i].isTransfer)
            _TimelineEntry(
              isLast: i == steps.length - 1,
              isEmphasis: false,
              leading: Icon(
                Icons.swap_horiz_rounded,
                size: 18,
                color: ResultTokens.mutedText(Theme.of(context).colorScheme),
              ),
              child: _TransferBody(step: steps[i]),
            )
          else
            _TimelineEntry(
              isLast: i == steps.length - 1,
              isEmphasis: i == 0 || i == steps.length - 1,
              leading: Text(
                modeEmoji(steps[i].mode ?? ''),
                style: const TextStyle(fontSize: 20),
              ),
              child: _StepLegBody(step: steps[i]),
            ),
      ],
    );
  }
}

class _TimelineEntry extends StatelessWidget {
  const _TimelineEntry({
    required this.isLast,
    required this.isEmphasis,
    required this.leading,
    required this.child,
  });

  final bool isLast;
  final bool isEmphasis;
  final Widget leading;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final railColor = scheme.outlineVariant.withValues(alpha: 0.8);

    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            width: 28,
            child: Column(
              children: [
                Container(
                  width: ResultTokens.timelineDot,
                  height: ResultTokens.timelineDot,
                  margin: const EdgeInsets.only(top: 6),
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: isEmphasis ? scheme.primary : scheme.surface,
                    border: Border.all(
                      color: isEmphasis ? scheme.primary : railColor,
                      width: 2,
                    ),
                  ),
                ),
                if (!isLast)
                  Expanded(
                    child: Container(
                      width: ResultTokens.timelineRail,
                      margin: const EdgeInsets.symmetric(vertical: 4),
                      color: railColor,
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(width: 4),
          Padding(
            padding: const EdgeInsets.only(top: 2),
            child: leading,
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Padding(
              padding: EdgeInsets.only(
                bottom: isLast ? 0 : ResultTokens.spaceXl,
              ),
              child: child,
            ),
          ),
        ],
      ),
    );
  }
}

class _StepLegBody extends StatelessWidget {
  const _StepLegBody({required this.step});

  final JourneyStep step;

  @override
  Widget build(BuildContext context) {
    return Text(
      step.instruction,
      key: Key('journey_step_leg_${step.instruction}'),
      style: ResultTokens.stepTitle(context),
    );
  }
}

class _TransferBody extends StatelessWidget {
  const _TransferBody({required this.step});

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
        color: ResultTokens.surfaceMuted(scheme),
        borderRadius: BorderRadius.circular(ResultTokens.radiusRow),
        border: Border.all(color: ResultTokens.hairline(scheme)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Change here',
            style: Theme.of(context).textTheme.labelMedium?.copyWith(
                  fontWeight: FontWeight.w700,
                  color: scheme.primary,
                ),
          ),
          if (location != null &&
              location.isNotEmpty &&
              !location.toLowerCase().contains('unknown')) ...[
            const SizedBox(height: 2),
            Text(
              location,
              style: ResultTokens.stepTitle(context),
            ),
          ],
          if (modeLine.isNotEmpty) ...[
            const SizedBox(height: 2),
            Text(modeLine, style: ResultTokens.stepMeta(context)),
          ],
          const SizedBox(height: 4),
          Text(
            step.instruction,
            style: ResultTokens.explanation(context),
          ),
        ],
      ),
    );
  }
}

class _LegBody extends StatelessWidget {
  const _LegBody({required this.leg, required this.isLast});

  final JourneyLeg leg;
  final bool isLast;

  @override
  Widget build(BuildContext context) {
    final metrics = <String>[
      if (legDurationLabel(leg) != null) legDurationLabel(leg)!,
      if (legDistanceLabel(leg) != null) legDistanceLabel(leg)!,
      if (legCostLabel(leg) != null) legCostLabel(leg)!,
    ];

    var title = modeLabel(leg.mode);
    if (isLast &&
        (leg.mode.toLowerCase() == 'walk' ||
            leg.mode.toLowerCase() == 'walking')) {
      title = 'Walk to destination';
    }

    final detail = <String>[
      if (leg.provider != null && leg.provider!.trim().isNotEmpty)
        leg.provider!,
      if (leg.routeId != null &&
          leg.routeId!.trim().isNotEmpty &&
          leg.routeId != leg.provider)
        leg.routeId!,
    ];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(title, style: ResultTokens.stepTitle(context)),
        if (detail.isNotEmpty)
          Text(detail.join(' · '), style: ResultTokens.stepMeta(context)),
        if (metrics.isNotEmpty)
          Text(metrics.join(' · '), style: ResultTokens.stepMeta(context)),
      ],
    );
  }
}
