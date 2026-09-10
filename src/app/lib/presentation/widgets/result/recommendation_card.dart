import 'package:flutter/material.dart';

import '../../../domain/entities/commute_route.dart';
import '../../../domain/entities/journey.dart';
import '../../../domain/entities/top_journey.dart';
import '../../theme/result_tokens.dart';
import '../../utils/labels.dart';
import '../../utils/mode_presentation.dart';
import 'metric_pill.dart';
import 'mode_sequence_row.dart';

/// Premium recommended journey card (presentation only).
class RecommendationCard extends StatefulWidget {
  const RecommendationCard({
    super.key,
    required this.option,
    required this.route,
    required this.journey,
    required this.modes,
    required this.sequenceFallback,
    required this.selected,
    required this.onSelect,
    required this.whyReason,
    this.whyBullets = const [],
  });

  final TopJourneyOption? option;
  final CommuteRoute? route;
  final RecommendedJourney? journey;
  final List<String> modes;
  final String sequenceFallback;
  final bool selected;
  final VoidCallback? onSelect;
  final String whyReason;
  final List<String> whyBullets;

  @override
  State<RecommendationCard> createState() => _RecommendationCardState();
}

class _RecommendationCardState extends State<RecommendationCard> {
  late bool _whyExpanded;

  @override
  void initState() {
    super.initState();
    // Show grounded bullets when present; user can collapse.
    _whyExpanded = widget.whyBullets.isNotEmpty;
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final durationText = widget.option != null
        ? formatDurationLabelOrBlank(
            travelTimeMinutes: widget.option!.duration ?? 0,
            known: widget.option!.hasKnownDuration,
          )
        : formatDurationLabelOrBlank(
            travelTimeMinutes: widget.route?.travelTimeMinutes ?? 0,
            known: widget.route?.hasKnownDuration ?? false,
          );
    final costText = widget.option != null
        ? formatCostLabelOrBlank(
            cost: widget.option!.cost ?? 0,
            known: widget.option!.hasKnownCost,
          )
        : formatCostLabelOrBlank(
            cost: widget.route?.cost ?? 0,
            known: widget.route?.hasKnownCost ?? false,
            partialKnownCostInr: widget.route?.partialKnownCostInr,
          );

    final walkText = widget.option != null
        ? walkingMetricLabel(
            widget.option!.hasKnownWalking
                ? widget.option!.walkingDistanceMeters
                : null,
          )
        : walkingSummary(
            walkingMinutes: widget.route?.walkingMinutes ?? 0,
            walkingMeters: widget.journey?.walkingDistanceMeters ??
                ((widget.route?.accessWalkingMeters ?? 0) +
                    (widget.route?.transferWalkingMeters ?? 0) +
                    (widget.route?.egressWalkingMeters ?? 0)),
          );

    final transfers = widget.option?.transfers ??
        widget.journey?.transferCount ??
        widget.route?.transfers ??
        0;
    final transferText = widget.option != null
        ? transferMetricLabel(transfers)
        : transferSummary(transfers);

    final borderColor = widget.selected
        ? ResultTokens.recommendStrongBorder(scheme)
        : ResultTokens.recommendBorder(scheme);

    return Material(
      color: Colors.transparent,
      child: InkWell(
        key: const Key('hero_recommendation'),
        borderRadius: BorderRadius.circular(ResultTokens.radiusCard),
        onTap: widget.onSelect,
        child: Ink(
          decoration: BoxDecoration(
            color: ResultTokens.recommendFill(scheme),
            borderRadius: BorderRadius.circular(ResultTokens.radiusCard),
            border: Border.all(color: borderColor, width: widget.selected ? 2 : 1.2),
          ),
          child: Padding(
            padding: const EdgeInsets.all(ResultTokens.spaceXl),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(Icons.star_rounded, size: 18, color: scheme.primary),
                    const SizedBox(width: 6),
                    Flexible(
                      child: Text(
                        'Recommended',
                        style: ResultTokens.badge(context),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                    const SizedBox(width: 8),
                    Text(
                      'Best for you',
                      style: ResultTokens.badge(context).copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: ResultTokens.spaceLg),
                ModeSequenceRow(
                  key: const Key('mode_sequence'),
                  modes: widget.modes,
                  fallbackLabel: widget.sequenceFallback,
                ),
                const SizedBox(height: ResultTokens.spaceLg),
                Wrap(
                  spacing: ResultTokens.spaceSm,
                  runSpacing: ResultTokens.spaceSm,
                  children: [
                    if (durationText != null)
                      MetricPill(
                        icon: Icons.schedule_rounded,
                        label: durationText,
                      ),
                    if (costText != null)
                      MetricPill(
                        icon: Icons.currency_rupee_rounded,
                        label: costText,
                      ),
                    if (walkText != null && walkText.isNotEmpty)
                      MetricPill(
                        icon: Icons.directions_walk_rounded,
                        label: walkText,
                      ),
                    if (transferText != null)
                      MetricPill(
                        icon: Icons.swap_horiz_rounded,
                        label: transferText,
                      ),
                  ],
                ),
                const SizedBox(height: ResultTokens.spaceLg),
                _WhyThisRow(
                  summary: widget.whyReason,
                  bullets: widget.whyBullets,
                  expanded: _whyExpanded,
                  onToggle: () => setState(() => _whyExpanded = !_whyExpanded),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _WhyThisRow extends StatelessWidget {
  const _WhyThisRow({
    required this.summary,
    required this.bullets,
    required this.expanded,
    required this.onToggle,
  });

  final String summary;
  final List<String> bullets;
  final bool expanded;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final canExpand = bullets.isNotEmpty;

    return Material(
      color: scheme.surface.withValues(alpha: 0.72),
      borderRadius: BorderRadius.circular(ResultTokens.radiusRow),
      child: InkWell(
        borderRadius: BorderRadius.circular(ResultTokens.radiusRow),
        onTap: canExpand ? onToggle : null,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(Icons.auto_awesome, size: 16, color: scheme.primary),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Why this?',
                      style: Theme.of(context).textTheme.labelLarge?.copyWith(
                            fontWeight: FontWeight.w700,
                          ),
                    ),
                  ),
                  if (canExpand)
                    Icon(
                      expanded
                          ? Icons.expand_less_rounded
                          : Icons.chevron_right_rounded,
                      size: 20,
                      color: ResultTokens.mutedText(scheme),
                    ),
                ],
              ),
              const SizedBox(height: 6),
              Text(
                summary,
                key: const Key('why_summary'),
                style: ResultTokens.explanation(context).copyWith(
                  color: ResultTokens.mutedText(scheme),
                ),
              ),
              if (expanded && bullets.isNotEmpty) ...[
                const SizedBox(height: 10),
                ...bullets.map(
                  (r) => Padding(
                    padding: const EdgeInsets.only(bottom: 6),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Icon(
                          Icons.check_circle_outline,
                          size: 16,
                          color: scheme.primary,
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(r, style: ResultTokens.explanation(context)),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
