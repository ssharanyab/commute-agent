import 'package:flutter/material.dart';

import '../../../domain/entities/commute_route.dart';
import '../../../domain/entities/top_journey.dart';
import '../../theme/result_tokens.dart';
import '../../utils/labels.dart';
import '../../utils/mode_presentation.dart';
import 'mode_sequence_row.dart';

class TopAlternativeCard extends StatelessWidget {
  const TopAlternativeCard({
    super.key,
    required this.option,
    required this.selected,
    required this.onTap,
  });

  final TopJourneyOption option;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final durationText = formatDurationLabelOrBlank(
      travelTimeMinutes: option.duration ?? 0,
      known: option.hasKnownDuration,
    );
    final costText = formatCostLabelOrBlank(
      cost: option.cost ?? 0,
      known: option.hasKnownCost,
    );
    final walkText = walkingMetricLabel(
      option.hasKnownWalking ? option.walkingDistanceMeters : null,
    );
    final transferText = transferMetricLabel(option.transfers);
    final metrics = <String>[
      if (durationText != null) durationText,
      if (costText != null) costText,
      if (walkText != null) walkText,
      if (transferText != null) transferText,
    ];
    final reason = displayReason(option.reason);
    final showBadge = reason != 'Another option';

    return Material(
      color: Colors.transparent,
      child: InkWell(
        key: Key('alt_card_${option.identity}'),
        borderRadius: BorderRadius.circular(ResultTokens.radiusRow),
        onTap: onTap,
        child: Ink(
          decoration: BoxDecoration(
            color: ResultTokens.surface(scheme),
            borderRadius: BorderRadius.circular(ResultTokens.radiusRow),
            border: Border.all(
              color: selected
                  ? ResultTokens.recommendStrongBorder(scheme)
                  : ResultTokens.hairline(scheme),
              width: selected ? 1.6 : 1,
            ),
          ),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(14, 12, 10, 12),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      ModeSequenceRow(
                        modes: modeTokensForTopOption(option),
                        compact: true,
                      ),
                      if (metrics.isNotEmpty) ...[
                        const SizedBox(height: 6),
                        Text(
                          metrics.join(' · '),
                          style: ResultTokens.stepMeta(context),
                        ),
                      ],
                      const SizedBox(height: 8),
                      if (showBadge)
                        Container(
                          key: Key('alt_reason_${option.identity}'),
                          padding: const EdgeInsets.symmetric(
                            horizontal: 10,
                            vertical: 4,
                          ),
                          decoration: BoxDecoration(
                            color: ResultTokens.surfaceMuted(scheme),
                            borderRadius: BorderRadius.circular(999),
                          ),
                          child: Text(
                            reason,
                            style: Theme.of(context)
                                .textTheme
                                .labelMedium
                                ?.copyWith(fontWeight: FontWeight.w600),
                          ),
                        )
                      else
                        Text(
                          reason,
                          key: Key('alt_reason_${option.identity}'),
                          style: ResultTokens.stepMeta(context),
                        ),
                      if (selected) ...[
                        const SizedBox(height: 6),
                        Text(
                          'Selected',
                          style:
                              Theme.of(context).textTheme.labelMedium?.copyWith(
                                    color: scheme.primary,
                                    fontWeight: FontWeight.w700,
                                  ),
                        ),
                      ],
                    ],
                  ),
                ),
                Icon(
                  Icons.chevron_right_rounded,
                  color: ResultTokens.mutedText(scheme),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class LegacyAlternativeCard extends StatelessWidget {
  const LegacyAlternativeCard({
    super.key,
    required this.title,
    required this.route,
  });

  final String title;
  final CommuteRoute route;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final showBadge = title != 'Another option';
    final duration = formatDurationLabelOrBlank(
      travelTimeMinutes: route.travelTimeMinutes,
      known: route.hasKnownDuration,
    );
    final cost = formatCostLabelOrBlank(
      cost: route.cost,
      known: route.hasKnownCost,
      partialKnownCostInr: route.partialKnownCostInr,
    );
    final metrics = <String>[
      if (duration != null) duration,
      if (cost != null) cost,
    ];

    return DecoratedBox(
      decoration: BoxDecoration(
        color: ResultTokens.surface(scheme),
        borderRadius: BorderRadius.circular(ResultTokens.radiusRow),
        border: Border.all(color: ResultTokens.hairline(scheme)),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 10, 12),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  ModeSequenceRow(
                    modes: modeTokensForRoute(route),
                    compact: true,
                  ),
                  if (metrics.isNotEmpty) ...[
                    const SizedBox(height: 6),
                    Text(
                      metrics.join(' · '),
                      style: ResultTokens.stepMeta(context),
                    ),
                  ],
                  const SizedBox(height: 8),
                  Text(
                    title,
                    style: Theme.of(context).textTheme.labelMedium?.copyWith(
                          fontWeight: FontWeight.w700,
                          color: showBadge
                              ? scheme.primary
                              : ResultTokens.mutedText(scheme),
                        ),
                  ),
                ],
              ),
            ),
            Icon(
              Icons.chevron_right_rounded,
              color: ResultTokens.mutedText(scheme),
            ),
          ],
        ),
      ),
    );
  }
}
