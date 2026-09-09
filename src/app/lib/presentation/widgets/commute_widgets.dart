import 'package:flutter/material.dart';

import '../../domain/entities/commute_route.dart';
import '../../domain/entities/context_change.dart';
import '../utils/labels.dart';

class RouteCard extends StatelessWidget {
  const RouteCard({super.key, required this.route, this.emphasize = false});

  final CommuteRoute route;
  final bool emphasize;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return DecoratedBox(
      decoration: BoxDecoration(
        color:
            emphasize
                ? scheme.primaryContainer.withValues(alpha: 0.45)
                : scheme.surfaceContainerHighest.withValues(alpha: 0.55),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              route.routeId,
              style: Theme.of(
                context,
              ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 6),
            Wrap(
              spacing: 12,
              runSpacing: 4,
              children: [
                Text('Mode: ${route.mode}'),
                Text(
                  'Time: ${formatDurationLabel(travelTimeMinutes: route.travelTimeMinutes, known: route.hasKnownDuration)}',
                ),
                if (route.distanceKm != null)
                  Text('Distance: ${route.distanceKm!.toStringAsFixed(1)} km'),
                Text(
                  'Cost: ${formatCostLabel(cost: route.cost, known: route.hasKnownCost, partialKnownCostInr: route.partialKnownCostInr)}',
                ),
                Text('Walk: ${route.walkingMinutes.toStringAsFixed(0)} min'),
                Text('Transfers: ${route.transfers}'),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              'Congestion ${route.congestionScore.toStringAsFixed(2)} · '
              'Reliability ${route.reliabilityScore.toStringAsFixed(2)}',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ),
      ),
    );
  }
}

class SectionTitle extends StatelessWidget {
  const SectionTitle(this.text, {super.key});
  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Text(
        text,
        style: Theme.of(
          context,
        ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w600),
      ),
    );
  }
}

class MetaLine extends StatelessWidget {
  const MetaLine(this.text, {super.key});
  final String text;

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: Theme.of(context).textTheme.labelLarge?.copyWith(
        color: Theme.of(context).colorScheme.primary,
      ),
    );
  }
}

class ChipWrap extends StatelessWidget {
  const ChipWrap({super.key, required this.items});
  final List<String> items;

  @override
  Widget build(BuildContext context) {
    if (items.isEmpty) return const Text('—');
    return Wrap(
      spacing: 6,
      runSpacing: 6,
      children:
          items
              .map(
                (e) => Chip(
                  label: Text(e),
                  visualDensity: VisualDensity.compact,
                  materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                ),
              )
              .toList(),
    );
  }
}

class ErrorBanner extends StatelessWidget {
  const ErrorBanner({super.key, required this.message});
  final String message;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: scheme.errorContainer,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Text(message, style: TextStyle(color: scheme.onErrorContainer)),
      ),
    );
  }
}

class PlanErrorPanel extends StatelessWidget {
  const PlanErrorPanel({
    super.key,
    required this.title,
    required this.detail,
    required this.onRetry,
  });

  final String title;
  final String detail;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: scheme.errorContainer,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              title,
              style: Theme.of(context).textTheme.titleSmall?.copyWith(
                color: scheme.onErrorContainer,
                fontWeight: FontWeight.w700,
              ),
            ),
            if (detail.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(detail, style: TextStyle(color: scheme.onErrorContainer)),
            ],
            const SizedBox(height: 12),
            Align(
              alignment: Alignment.centerLeft,
              child: OutlinedButton(
                onPressed: onRetry,
                style: OutlinedButton.styleFrom(
                  foregroundColor: scheme.onErrorContainer,
                  side: BorderSide(color: scheme.onErrorContainer),
                ),
                child: const Text('RETRY'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class ContextBlock extends StatelessWidget {
  const ContextBlock({super.key, required this.change});
  final ContextChange? change;

  @override
  Widget build(BuildContext context) {
    if (change == null) return const Text('—');
    final c = change!;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Source: ${c.contextSource}'),
        Text(
          'Traffic: ${c.trafficChanged} · Disruption: ${c.disruptionChanged} · '
          'Weather: ${c.weatherChanged}',
        ),
        Text(
          'Δ congestion ${c.congestionDelta} · Δ time ${c.travelTimeDeltaMinutes} min',
        ),
        if (c.description.isNotEmpty) Text(c.description),
      ],
    );
  }
}

class BeforeAfter extends StatelessWidget {
  const BeforeAfter({
    super.key,
    required this.before,
    required this.after,
    required this.previousId,
    required this.newId,
  });

  final Map<String, dynamic>? before;
  final Map<String, dynamic>? after;
  final String? previousId;
  final String? newId;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Route: ${previousId ?? '—'} → ${newId ?? '—'}'),
        Text('Score: ${_score(before)} → ${_score(after)}'),
        Text(
          'Reasons before: ${_reasons(before)}',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        Text(
          'Reasons after: ${_reasons(after)}',
          style: Theme.of(context).textTheme.bodySmall,
        ),
      ],
    );
  }

  String _score(Map<String, dynamic>? m) {
    if (m == null) return '—';
    final s = m['score'];
    return s == null ? '—' : '$s';
  }

  String _reasons(Map<String, dynamic>? m) {
    if (m == null) return '—';
    final r = m['reason_codes'];
    if (r is! List || r.isEmpty) return '—';
    return r.join(', ');
  }
}
