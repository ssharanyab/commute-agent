import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../domain/entities/commute_plan.dart';
import '../../../domain/entities/commute_route.dart';
import '../../../domain/entities/context_change.dart';
import '../../../domain/entities/historical_signal.dart';
import '../../../domain/entities/journey.dart';
import '../../../domain/entities/replan_result.dart';
import '../../providers/commute_provider.dart';
import '../../utils/labels.dart';
import '../../utils/mode_presentation.dart';
import '../../widgets/commute_widgets.dart';
import '../../widgets/journey_timeline.dart';

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
    required String travelMode,
  }) async {
    final uri = googleMapsDirectionsUri(
      origin: origin,
      destination: destination,
      travelMode: travelMode,
    );
    await launchUrl(uri, mode: LaunchMode.externalApplication);
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<CommuteProvider>();
    final plan = provider.plan;
    if (plan == null) {
      return Scaffold(
        appBar: AppBar(title: const Text('Your commute')),
        body: const Center(child: Text('No plan available.')),
      );
    }

    final view = _RecommendationView.fromPlan(plan, provider.replanResult);
    final origin = (provider.lastPlanRequest?['origin'] as String?) ?? '';
    final destination =
        (provider.lastPlanRequest?['destination'] as String?) ?? '';
    final replan = provider.replanResult;
    final replanLoading = provider.isReplanLoading;
    final travelMode = mapsTravelModeFor(view.route, view.journey);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Your commute'),
        centerTitle: false,
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 640),
          child: ListView(
            padding: const EdgeInsets.fromLTRB(20, 8, 20, 40),
            children: [
              if (replan != null) ...[
                _ReplanBanner(replan: replan),
                const SizedBox(height: 16),
              ],
              if (view.route != null)
                _HeroRecommendation(
                  route: view.route!,
                  journey: view.journey,
                  sequence: view.sequence,
                )
              else
                const _EmptyRecommendation(),
              if (view.route?.historicalSignal != null) ...[
                const SizedBox(height: 12),
                _HistoricalCard(
                  signal: view.route!.historicalSignal!,
                  currentMinutes: view.route!.travelTimeMinutes,
                  durationKnown: view.route!.hasKnownDuration,
                ),
              ],
              if (view.journey != null && view.journey!.legs.isNotEmpty) ...[
                const SizedBox(height: 24),
                Text(
                  'YOUR JOURNEY',
                  style: Theme.of(context).textTheme.labelLarge?.copyWith(
                        fontWeight: FontWeight.w700,
                        letterSpacing: 0.5,
                      ),
                ),
                const SizedBox(height: 12),
                JourneyTimeline(journey: view.journey!),
              ],
              const SizedBox(height: 24),
              Text(
                'WHY THIS?',
                style: Theme.of(context).textTheme.labelLarge?.copyWith(
                      fontWeight: FontWeight.w700,
                      letterSpacing: 0.5,
                    ),
              ),
              const SizedBox(height: 8),
              Text(
                agentExplanationOrFallback(plan.explanation),
                style: Theme.of(context).textTheme.bodyMedium,
              ),
              if (plan.reasons.isNotEmpty) ...[
                const SizedBox(height: 12),
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
              ],
              if (plan.routeCategories.isNotEmpty) ...[
                const SizedBox(height: 24),
                Text(
                  'OTHER OPTIONS',
                  style: Theme.of(context).textTheme.labelLarge?.copyWith(
                        fontWeight: FontWeight.w700,
                        letterSpacing: 0.5,
                      ),
                ),
                const SizedBox(height: 10),
                ...plan.routeCategories.map(
                  (cat) => Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: _AlternativeTile(
                      title: categoryLabel(cat.category),
                      route: cat.route,
                    ),
                  ),
                ),
              ],
              const SizedBox(height: 24),
              FilledButton.tonal(
                key: const Key('replan_button'),
                onPressed:
                    replanLoading ? null : () => _openReplanSheet(context),
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
                          Text('Updating your commute…'),
                        ],
                      )
                    : const Text('Replan my commute'),
              ),
              const SizedBox(height: 10),
              OutlinedButton.icon(
                key: const Key('maps_handoff'),
                onPressed: (origin.isEmpty || destination.isEmpty)
                    ? null
                    : () => _openMapsHandoff(
                          origin: origin,
                          destination: destination,
                          travelMode: travelMode,
                        ),
                icon: const Icon(Icons.open_in_new),
                label: const Text('Open in Google Maps'),
              ),
              const SizedBox(height: 6),
              Text(
                'Opens Google Maps for navigation. Commute Agent remains '
                'your decision layer — Maps is for getting there.',
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
              ),
              if (provider.replanError != null) ...[
                const SizedBox(height: 12),
                ErrorBanner(message: provider.replanError!),
              ],
              // Keep polyline/token available to navigation layer without rendering a map.
              if (view.route?.googlePolyline != null ||
                  view.route?.googleRouteToken != null)
                const SizedBox.shrink(
                  key: Key('nav_payload_retained'),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Resolves authoritative recommendation from Decision Engine fields.
class _RecommendationView {
  final CommuteRoute? route;
  final RecommendedJourney? journey;
  final String sequence;

  const _RecommendationView({
    required this.route,
    required this.journey,
    required this.sequence,
  });

  factory _RecommendationView.fromPlan(
    CommutePlan plan,
    ReplanResult? replan,
  ) {
    // After a changed replan, show the new authoritative route from backend.
    if (replan != null &&
        replan.recommendationChanged &&
        replan.newRecommendation != null) {
      final route = replan.newRecommendation!;
      RecommendedJourney? journey;
      if (plan.recommendedJourney?.candidateId == route.routeId) {
        journey = plan.recommendedJourney;
      } else {
        for (final j in plan.journeys) {
          if (j.candidateId == route.routeId) {
            journey = j;
            break;
          }
        }
      }
      return _RecommendationView(
        route: route,
        journey: journey,
        sequence: journey != null
            ? modeSequenceForJourney(journey)
            : modeSequenceForRoute(route),
      );
    }

    final decisionId = plan.decision?.recommendedRouteId;
    var route = plan.recommendation;
    var journey = plan.recommendedJourney;

    // Prefer journey matching Decision Engine winner.
    if (decisionId != null) {
      if (journey == null || journey.candidateId != decisionId) {
        for (final j in plan.journeys) {
          if (j.candidateId == decisionId) {
            journey = j;
            break;
          }
        }
      }
      if (route == null || route.routeId != decisionId) {
        // Keep recommendation if it already matches; otherwise leave as-is
        // (backend recommendation should match decision).
        if (plan.recommendation?.routeId == decisionId) {
          route = plan.recommendation;
        }
      }
    }

    final sequence = journey != null
        ? modeSequenceForJourney(journey)
        : (route != null ? modeSequenceForRoute(route) : 'Route');

    return _RecommendationView(
      route: route,
      journey: journey,
      sequence: sequence,
    );
  }
}

class _EmptyRecommendation extends StatelessWidget {
  const _EmptyRecommendation();

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 0,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Text(
          'No suitable journey was found for these preferences.',
          style: Theme.of(context).textTheme.titleMedium,
        ),
      ),
    );
  }
}

class _HeroRecommendation extends StatelessWidget {
  const _HeroRecommendation({
    required this.route,
    required this.journey,
    required this.sequence,
  });

  final CommuteRoute route;
  final RecommendedJourney? journey;
  final String sequence;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final walkingMeters = journey?.walkingDistanceMeters ??
        ((route.accessWalkingMeters ?? 0) +
            (route.transferWalkingMeters ?? 0) +
            (route.egressWalkingMeters ?? 0));
    final transfers = journey?.transferCount ?? route.transfers;

    return Card(
      key: const Key('hero_recommendation'),
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
            const SizedBox(height: 10),
            Text(
              sequence,
              key: const Key('mode_sequence'),
              style: Theme.of(context).textTheme.titleLarge?.copyWith(
                    fontWeight: FontWeight.w700,
                    height: 1.3,
                  ),
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 16,
              runSpacing: 8,
              children: [
                _Stat(
                  icon: Icons.schedule,
                  text: formatDurationLabel(
                    travelTimeMinutes: route.travelTimeMinutes,
                    known: route.hasKnownDuration,
                  ),
                ),
                _Stat(
                  icon: Icons.currency_rupee,
                  text: formatCostLabel(
                    cost: route.cost,
                    known: route.hasKnownCost,
                    partialKnownCostInr: route.partialKnownCostInr,
                  ),
                ),
                _Stat(
                  icon: Icons.directions_walk,
                  text: walkingSummary(
                    walkingMinutes: route.walkingMinutes,
                    walkingMeters: walkingMeters > 0 ? walkingMeters : null,
                  ),
                ),
                _Stat(
                  icon: Icons.swap_horiz,
                  text: transferSummary(transfers),
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
        Flexible(
          child: Text(text, style: Theme.of(context).textTheme.titleSmall),
        ),
      ],
    );
  }
}

class _AlternativeTile extends StatelessWidget {
  const _AlternativeTile({required this.title, required this.route});

  final String title;
  final CommuteRoute route;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: scheme.surfaceContainerHighest.withValues(alpha: 0.4),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              title,
              style: Theme.of(context).textTheme.labelLarge?.copyWith(
                    fontWeight: FontWeight.w700,
                    color: scheme.primary,
                  ),
            ),
            const SizedBox(height: 6),
            Text(
              modeSequenceForRoute(route),
              style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                    fontWeight: FontWeight.w600,
                  ),
            ),
            const SizedBox(height: 6),
            Text(
              [
                formatDurationLabel(
                  travelTimeMinutes: route.travelTimeMinutes,
                  known: route.hasKnownDuration,
                ),
                formatCostLabel(
                  cost: route.cost,
                  known: route.hasKnownCost,
                  partialKnownCostInr: route.partialKnownCostInr,
                ),
              ].join(' · '),
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: scheme.onSurfaceVariant,
                  ),
            ),
          ],
        ),
      ),
    );
  }
}

class _HistoricalCard extends StatelessWidget {
  const _HistoricalCard({
    required this.signal,
    required this.currentMinutes,
    required this.durationKnown,
  });

  final HistoricalSignal signal;
  final double currentMinutes;
  final bool durationKnown;

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
      lines.add(above ? '$pct% above usual' : '$pct% below usual');
      lines.add(
        'Current: ${formatDurationLabel(travelTimeMinutes: currentMinutes, known: durationKnown)}',
      );
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

class _ReplanBanner extends StatelessWidget {
  const _ReplanBanner({required this.replan});

  final ReplanResult replan;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final changed = replan.recommendationChanged;
    return DecoratedBox(
      key: const Key('replan_banner'),
      decoration: BoxDecoration(
        color: changed
            ? scheme.tertiaryContainer.withValues(alpha: 0.55)
            : scheme.surfaceContainerHighest.withValues(alpha: 0.55),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              changed ? 'Your commute changed' : 'Your commute is unchanged',
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
            ),
            const SizedBox(height: 6),
            Text(
              changed
                  ? 'Commute Agent found a better option based on the '
                      'updated conditions.'
                  : 'Commute Agent checked again — your current plan still fits.',
              style: Theme.of(context).textTheme.bodyMedium,
            ),
            if (replan.explanation.trim().isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(
                replan.explanation.trim(),
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: scheme.onSurfaceVariant,
                    ),
              ),
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
              'Tell Commute Agent what changed and it will re-evaluate.',
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
              child: const Text('Update recommendation'),
            ),
          ],
        ),
      ),
    );
  }
}
