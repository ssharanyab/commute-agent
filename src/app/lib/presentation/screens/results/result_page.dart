import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../domain/entities/commute_route.dart';
import '../../../domain/entities/context_change.dart';
import '../../../domain/entities/historical_signal.dart';
import '../../../domain/entities/replan_result.dart';
import '../../providers/commute_provider.dart';
import '../../utils/labels.dart';
import '../../widgets/commute_widgets.dart';
import '../../widgets/route_map.dart';

class ResultPage extends StatelessWidget {
  const ResultPage({super.key, required this.apiBaseUrl});

  final String apiBaseUrl;

  Future<void> _openReplanSheet(BuildContext context) async {
    final change = await showModalBottomSheet<ContextChange>(
      context: context,
      isScrollControlled: true,
      builder: (ctx) => const _ReplanSheet(),
    );
    if (change == null || !context.mounted) return;
    await context.read<CommuteProvider>().replanCommute(
          baseUrl: apiBaseUrl,
          contextChange: change,
        );
  }

  Future<void> _openMapsHandoff({
    required String origin,
    required String destination,
  }) async {
    final uri = Uri.parse(
      'https://www.google.com/maps/dir/?api=1'
      '&origin=${Uri.encodeComponent(origin)}'
      '&destination=${Uri.encodeComponent(destination)}'
      '&travelmode=driving',
    );
    await launchUrl(uri, mode: LaunchMode.externalApplication);
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<CommuteProvider>();
    final plan = provider.plan;
    if (plan == null) {
      return Scaffold(
        appBar: AppBar(title: const Text('Your route')),
        body: const Center(child: Text('No plan available.')),
      );
    }

    final rec = plan.recommendation;
    final origin = (provider.lastPlanRequest?['origin'] as String?) ?? '';
    final destination =
        (provider.lastPlanRequest?['destination'] as String?) ?? '';
    final replan = provider.replanResult;
    final replanLoading = provider.isReplanLoading;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Your route'),
        centerTitle: false,
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 40),
        children: [
          RouteMap(encodedPolyline: rec?.googlePolyline),
          const SizedBox(height: 16),
          if (rec != null)
            _RecommendationCard(route: rec)
          else
            const _EmptyRecommendation(),
          if (rec?.historicalSignal != null) ...[
            const SizedBox(height: 12),
            _HistoricalCard(
              signal: rec!.historicalSignal!,
              currentMinutes: rec.travelTimeMinutes,
            ),
          ],
          const SizedBox(height: 20),
          Text(
            'Why this route?',
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
          ),
          const SizedBox(height: 8),
          if (plan.reasons.isEmpty)
            Text(
              'Selected as the best fit for your preferences.',
              style: Theme.of(context).textTheme.bodyMedium,
            )
          else
            ...plan.reasons
                .where((r) => r.toUpperCase() != 'CONSTRAINT_VIOLATION')
                .map(
                  (r) => Padding(
                    padding: const EdgeInsets.only(bottom: 6),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Icon(
                          Icons.check_circle_outline,
                          size: 18,
                          color: Theme.of(context).colorScheme.primary,
                        ),
                        const SizedBox(width: 8),
                        Expanded(child: Text(reasonLabel(r))),
                      ],
                    ),
                  ),
                ),
          if (plan.explanation.trim().isNotEmpty) ...[
            const SizedBox(height: 12),
            Text(
              plan.explanation.trim(),
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
            ),
          ],
          if (plan.routeCategories.isNotEmpty) ...[
            const SizedBox(height: 24),
            Text(
              'Other options',
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
            ),
            const SizedBox(height: 10),
            SizedBox(
              height: 118,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                itemCount: plan.routeCategories.length,
                separatorBuilder: (_, __) => const SizedBox(width: 10),
                itemBuilder: (context, i) {
                  final cat = plan.routeCategories[i];
                  return _CategoryCard(
                    title: categoryLabel(cat.category),
                    route: cat.route,
                  );
                },
              ),
            ),
          ],
          const SizedBox(height: 24),
          FilledButton.tonal(
            key: const Key('replan_button'),
            onPressed: replanLoading ? null : () => _openReplanSheet(context),
            child: replanLoading
                ? const Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                      SizedBox(width: 10),
                      Text('Updating route…'),
                    ],
                  )
                : const Text('REPLAN'),
          ),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            key: const Key('maps_handoff'),
            onPressed: (origin.isEmpty || destination.isEmpty)
                ? null
                : () => _openMapsHandoff(
                      origin: origin,
                      destination: destination,
                    ),
            icon: const Icon(Icons.navigation_outlined),
            label: const Text('OPEN IN GOOGLE MAPS'),
          ),
          const SizedBox(height: 6),
          Text(
            'Opens Google Maps with your origin and destination. '
            'This may not match the exact selected route geometry.',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
          ),
          if (provider.replanError != null) ...[
            const SizedBox(height: 12),
            ErrorBanner(message: provider.replanError!),
          ],
          if (replan != null) ...[
            const SizedBox(height: 24),
            _ReplanSummary(replan: replan),
          ],
        ],
      ),
    );
  }
}

class _EmptyRecommendation extends StatelessWidget {
  const _EmptyRecommendation();

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Text(
          'No route matches your current constraints.',
          style: Theme.of(context).textTheme.titleMedium,
        ),
      ),
    );
  }
}

class _RecommendationCard extends StatelessWidget {
  const _RecommendationCard({required this.route});

  final CommuteRoute route;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Card(
      elevation: 0,
      color: scheme.primaryContainer.withValues(alpha: 0.45),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'BEST FOR YOU',
              style: Theme.of(context).textTheme.labelLarge?.copyWith(
                    color: scheme.primary,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 0.6,
                  ),
            ),
            const SizedBox(height: 8),
            Text(
              modeLabel(route.mode),
              style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
            ),
            const SizedBox(height: 10),
            Wrap(
              spacing: 16,
              runSpacing: 6,
              children: [
                _Stat(
                  icon: Icons.schedule,
                  text: '${route.travelTimeMinutes.toStringAsFixed(0)} min',
                ),
                _Stat(
                  icon: Icons.currency_rupee,
                  text: '₹${route.cost.toStringAsFixed(0)}',
                ),
                if (route.walkingMinutes > 0)
                  _Stat(
                    icon: Icons.directions_walk,
                    text: '${route.walkingMinutes.toStringAsFixed(0)} min walk',
                  ),
                if (route.transfers > 0)
                  _Stat(
                    icon: Icons.swap_horiz,
                    text: '${route.transfers} transfer${route.transfers == 1 ? '' : 's'}',
                  ),
              ],
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              children: [
                Chip(
                  label: Text(
                    'Reliability: ${reliabilityBand(route.reliabilityScore)}',
                  ),
                  visualDensity: VisualDensity.compact,
                ),
                if (route.congestionScore <= 0.35)
                  const Chip(
                    label: Text('Low traffic'),
                    visualDensity: VisualDensity.compact,
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _Stat extends StatelessWidget {
  const _Stat({required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 18),
        const SizedBox(width: 4),
        Text(text, style: Theme.of(context).textTheme.titleMedium),
      ],
    );
  }
}

class _HistoricalCard extends StatelessWidget {
  const _HistoricalCard({
    required this.signal,
    required this.currentMinutes,
  });

  final HistoricalSignal signal;
  final double currentMinutes;

  @override
  Widget build(BuildContext context) {
    if (!signal.hasCoverage) {
      return Text(
        'Limited historical data',
        style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
      );
    }

    final expected = signal.expectedMinutes;
    final std = signal.stdMinutes;
    final lines = <String>[];
    if (expected != null && std != null && std > 0) {
      final low = (expected - std).clamp(0, 999).toStringAsFixed(0);
      final high = (expected + std).toStringAsFixed(0);
      lines.add('Usually $low–$high min');
    } else if (expected != null) {
      lines.add('Usually ~${expected.toStringAsFixed(0)} min');
    }
    if (signal.reliabilityScore != null) {
      lines.add('Reliability: ${reliabilityBand(signal.reliabilityScore!)}');
    }
    if (signal.deviationPercent != null) {
      final pct = signal.deviationPercent!.abs().toStringAsFixed(0);
      final above = signal.deviationPercent! > 0;
      lines.add(
        above ? '$pct% above usual' : '$pct% below usual',
      );
      lines.add('Current: ${currentMinutes.toStringAsFixed(0)} min');
    }

    if (lines.isEmpty) return const SizedBox.shrink();

    return Card(
      elevation: 0,
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Historical context',
              style: Theme.of(context).textTheme.labelLarge?.copyWith(
                    fontWeight: FontWeight.w600,
                  ),
            ),
            const SizedBox(height: 6),
            ...lines.map((l) => Text(l)),
          ],
        ),
      ),
    );
  }
}

class _CategoryCard extends StatelessWidget {
  const _CategoryCard({required this.title, required this.route});

  final String title;
  final CommuteRoute route;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 150,
      child: Card(
        elevation: 0,
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title.toUpperCase(),
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      fontWeight: FontWeight.w700,
                      color: Theme.of(context).colorScheme.primary,
                    ),
              ),
              const SizedBox(height: 6),
              Text(
                modeLabel(route.mode),
                style: Theme.of(context).textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
              ),
              const Spacer(),
              Text('${route.travelTimeMinutes.toStringAsFixed(0)} min'),
              Text('₹${route.cost.toStringAsFixed(0)}'),
            ],
          ),
        ),
      ),
    );
  }
}

class _ReplanSummary extends StatelessWidget {
  const _ReplanSummary({required this.replan});

  final ReplanResult replan;

  @override
  Widget build(BuildContext context) {
    final changed = replan.recommendationChanged;
    final prev = replan.previousRecommendation;
    final next = replan.newRecommendation;
    return Card(
      elevation: 0,
      color: Theme.of(context).colorScheme.secondaryContainer.withValues(
            alpha: 0.4,
          ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              changed ? 'ROUTE UPDATED' : 'ROUTE UNCHANGED',
              style: Theme.of(context).textTheme.labelLarge?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
            ),
            const SizedBox(height: 12),
            Text(
              'Before',
              style: Theme.of(context).textTheme.labelMedium,
            ),
            Text(
              prev == null
                  ? (replan.previousRouteId ?? '—')
                  : '${modeLabel(prev.mode)} · ${prev.travelTimeMinutes.toStringAsFixed(0)} min',
            ),
            const SizedBox(height: 8),
            Text(
              'After',
              style: Theme.of(context).textTheme.labelMedium,
            ),
            Text(
              next == null
                  ? (replan.newRouteId ?? '—')
                  : '${modeLabel(next.mode)} · ${next.travelTimeMinutes.toStringAsFixed(0)} min',
            ),
            if (replan.explanation.trim().isNotEmpty) ...[
              const SizedBox(height: 12),
              Text(
                'Why did it change?',
                style: Theme.of(context).textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
              ),
              const SizedBox(height: 4),
              Text(replan.explanation.trim()),
            ],
          ],
        ),
      ),
    );
  }
}

class _ReplanSheet extends StatefulWidget {
  const _ReplanSheet();

  @override
  State<_ReplanSheet> createState() => _ReplanSheetState();
}

class _ReplanSheetState extends State<_ReplanSheet> {
  bool _traffic = true;
  bool _disruption = false;
  final _deltaCongestion = TextEditingController(text: '0.55');
  final _deltaMinutes = TextEditingController(text: '22');

  @override
  void dispose() {
    _deltaCongestion.dispose();
    _deltaMinutes.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 20,
        bottom: MediaQuery.of(context).viewInsets.bottom + 24,
      ),
      child: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              'Conditions changed?',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 8),
            Text(
              'Simulate a context change to re-evaluate your route.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Traffic spike'),
              value: _traffic,
              onChanged: (v) => setState(() => _traffic = v),
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Disruption'),
              value: _disruption,
              onChanged: (v) => setState(() => _disruption = v),
            ),
            TextField(
              controller: _deltaMinutes,
              decoration: const InputDecoration(
                labelText: 'Extra travel time (minutes)',
              ),
              keyboardType: TextInputType.number,
            ),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: () {
                Navigator.pop(
                  context,
                  ContextChange(
                    trafficChanged: _traffic,
                    disruptionChanged: _disruption,
                    contextSource: 'simulated',
                    congestionDelta:
                        double.tryParse(_deltaCongestion.text) ?? 0.55,
                    travelTimeDeltaMinutes:
                        double.tryParse(_deltaMinutes.text) ?? 0,
                    description: 'Simulated condition change',
                  ),
                );
              },
              child: const Text('UPDATE RECOMMENDATION'),
            ),
          ],
        ),
      ),
    );
  }
}
