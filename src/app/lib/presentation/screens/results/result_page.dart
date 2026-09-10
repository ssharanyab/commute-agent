import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../domain/entities/commute_plan.dart';
import '../../../domain/entities/commute_route.dart';
import '../../../domain/entities/context_change.dart';
import '../../../domain/entities/historical_signal.dart';
import '../../../domain/entities/journey.dart';
import '../../../domain/entities/replan_result.dart';
import '../../../domain/entities/top_journey.dart';
import '../../providers/commute_provider.dart';
import '../../theme/result_tokens.dart';
import '../../utils/labels.dart';
import '../../utils/mode_presentation.dart';
import '../../utils/user_facing_explanation.dart';
import '../../widgets/commute_widgets.dart';
import '../../widgets/journey_timeline.dart';
import '../../widgets/result/alternative_card.dart';
import '../../widgets/result/recommendation_card.dart';
import '../../widgets/result/result_bottom_actions.dart';

class ResultPage extends StatefulWidget {
  const ResultPage({super.key, required this.apiBaseUrl});

  final String apiBaseUrl;

  @override
  State<ResultPage> createState() => _ResultPageState();
}

class _ResultPageState extends State<ResultPage> {
  /// Local UI selection — does not mutate backend recommendation.
  String? _selectedIdentity;
  String? _selectionPlanKey;
  Object? _lastReplanToken;

  Future<void> _openReplanSheet(BuildContext context) async {
    final change = await showModalBottomSheet<ContextChange>(
      context: context,
      isScrollControlled: true,
      builder: (ctx) => const _ReplanSheet(),
    );
    if (change == null || !context.mounted) return;
    await context.read<CommuteProvider>().replanCommute(
          baseUrl: widget.apiBaseUrl,
          contextChange: change,
        );
  }

  Future<void> _openMapsHandoff({
    required BuildContext context,
    required String origin,
    required String destination,
    required String travelMode,
  }) async {
    final uri = googleMapsDirectionsUri(
      origin: origin,
      destination: destination,
      travelMode: travelMode,
    );
    try {
      final ok = await launchUrl(uri, mode: LaunchMode.externalApplication);
      if (!ok && context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text("Couldn't open Google Maps. Please try again."),
          ),
        );
      }
    } catch (_) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text("Couldn't open Google Maps. Please try again."),
          ),
        );
      }
    }
  }

  void _ensureSelectionSynced({
    required CommutePlan plan,
    required ReplanResult? replan,
    required List<TopJourneyOption> options,
    required TopJourneyOption? recommended,
  }) {
    final planKey =
        '${plan.decision?.recommendedRouteId ?? plan.recommendation?.routeId}'
        '|${options.map((o) => o.identity).join(',')}';
    final replanToken = replan;
    final needsReset = _selectionPlanKey != planKey ||
        !identical(_lastReplanToken, replanToken);
    final stale = _selectedIdentity != null &&
        options.isNotEmpty &&
        !options.any((o) => o.identity == _selectedIdentity);

    if (!needsReset && !stale) return;

    String? next;
    if (replan != null &&
        replan.recommendationChanged &&
        replan.newRecommendation != null) {
      final newId = replan.newRecommendation!.routeId;
      final match = options.where((o) => o.identity == newId);
      next = match.isNotEmpty ? match.first.identity : newId;
    } else {
      next = recommended?.identity ??
          (options.isNotEmpty ? options.first.identity : null);
    }

    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      setState(() {
        _selectionPlanKey = planKey;
        _lastReplanToken = replanToken;
        _selectedIdentity = next;
      });
    });
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<CommuteProvider>();
    final plan = provider.plan;
    final scheme = Theme.of(context).colorScheme;

    if (plan == null) {
      return Scaffold(
        backgroundColor: ResultTokens.background(scheme),
        appBar: AppBar(
          title: const Text('Your commute'),
          centerTitle: false,
          elevation: 0,
          scrolledUnderElevation: 0,
          backgroundColor: ResultTokens.background(scheme),
        ),
        body: const Center(child: Text('No plan available.')),
      );
    }

    final view = _RecommendationView.fromPlan(plan, provider.replanResult);
    final topOptions = _resolveTopOptions(plan, view);
    TopJourneyOption? recommendedOption;
    if (topOptions.isNotEmpty) {
      recommendedOption = topOptions.firstWhere(
        (o) => o.isRecommended,
        orElse: () => topOptions.first,
      );
    }
    final alternatives = topOptions
        .where(
          (o) =>
              recommendedOption == null ||
              o.identity != recommendedOption.identity,
        )
        .toList();

    _ensureSelectionSynced(
      plan: plan,
      replan: provider.replanResult,
      options: topOptions,
      recommended: recommendedOption,
    );

    final selected = _findSelected(topOptions, recommendedOption);
    final origin = (provider.lastPlanRequest?['origin'] as String?) ?? '';
    final destination =
        (provider.lastPlanRequest?['destination'] as String?) ?? '';
    final replan = provider.replanResult;
    final replanLoading = provider.isReplanLoading;
    final travelMode = selected != null
        ? mapsTravelModeForTopOption(selected)
        : mapsTravelModeFor(view.route, view.journey);
    final useTop5 = plan.topSelection != null && !(plan.topSelection!.isEmpty);
    final tripContext = (origin.isNotEmpty && destination.isNotEmpty)
        ? '$origin → $destination'
        : null;

    final recommendedModes = recommendedOption != null
        ? modeTokensForTopOption(recommendedOption)
        : (view.journey != null
            ? modeTokensForJourney(view.journey!)
            : (view.route != null
                ? modeTokensForRoute(view.route!)
                : const <String>[]));

    return Scaffold(
      backgroundColor: ResultTokens.background(scheme),
      appBar: AppBar(
        elevation: 0,
        scrolledUnderElevation: 0,
        backgroundColor: ResultTokens.background(scheme),
        centerTitle: false,
        titleSpacing: 0,
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Your commute',
              style: ResultTokens.pageTitle(context),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
            if (tripContext != null) ...[
              const SizedBox(height: 2),
              Text(
                tripContext,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: ResultTokens.tripContext(context),
              ),
            ],
          ],
        ),
        toolbarHeight: tripContext != null ? 72 : kToolbarHeight,
      ),
      body: Column(
        children: [
          Expanded(
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 640),
                child: SingleChildScrollView(
                  padding: const EdgeInsets.fromLTRB(
                    ResultTokens.spaceXl,
                    ResultTokens.spaceSm,
                    ResultTokens.spaceXl,
                    ResultTokens.spaceXxl,
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                    if (replan != null) ...[
                      _ReplanBanner(replan: replan),
                      const SizedBox(height: ResultTokens.spaceLg),
                    ],
                    if (recommendedOption != null || view.route != null)
                      RecommendationCard(
                        option: recommendedOption,
                        route: view.route,
                        journey: view.journey,
                        modes: recommendedModes,
                        sequenceFallback: recommendedOption != null
                            ? modeSequenceForTopOption(recommendedOption)
                            : view.sequence,
                        selected: selected != null &&
                            recommendedOption != null &&
                            selected.identity == recommendedOption.identity,
                        onSelect: recommendedOption == null
                            ? null
                            : () {
                                final id = recommendedOption!.identity;
                                setState(() => _selectedIdentity = id);
                              },
                        whyReason: _whyReason(
                          plan: plan,
                          option: recommendedOption,
                          useTop5: useTop5,
                        ),
                        whyBullets: useTop5
                            ? const <String>[]
                            : explanationForPlan(plan).reasons,
                      )
                    else
                      const _EmptyRecommendation(),
                    if (view.route?.historicalSignal != null) ...[
                      const SizedBox(height: ResultTokens.spaceMd),
                      _HistoricalCard(
                        signal: view.route!.historicalSignal!,
                        currentMinutes: view.route!.travelTimeMinutes,
                        durationKnown: view.route!.hasKnownDuration,
                      ),
                    ],
                    if ((selected?.steps.isNotEmpty ?? false) ||
                        (view.journey != null &&
                            (view.journey!.steps.isNotEmpty ||
                                view.journey!.legs.isNotEmpty))) ...[
                      const SizedBox(height: ResultTokens.spaceXxl),
                      Text(
                        'Your journey',
                        style: ResultTokens.sectionHeader(context),
                      ),
                      const SizedBox(height: ResultTokens.spaceMd),
                      JourneyTimeline(
                        journey: _journeyForSelection(
                          plan: plan,
                          selected: selected,
                          fallback: view.journey,
                        ),
                        steps: selected?.steps ?? const [],
                      ),
                    ],
                    if (alternatives.isNotEmpty) ...[
                      const SizedBox(height: ResultTokens.spaceXxl),
                      Text(
                        'Other ways to go',
                        key: const Key('other_ways_heading'),
                        style: ResultTokens.sectionHeader(context),
                      ),
                      const SizedBox(height: ResultTokens.spaceMd),
                      ...alternatives.map(
                        (alt) => Padding(
                          padding: const EdgeInsets.only(
                            bottom: ResultTokens.spaceMd,
                          ),
                          child: TopAlternativeCard(
                            option: alt,
                            selected: selected?.identity == alt.identity,
                            onTap: () => setState(
                              () => _selectedIdentity = alt.identity,
                            ),
                          ),
                        ),
                      ),
                    ] else if (!useTop5 && plan.routeCategories.isNotEmpty) ...[
                      const SizedBox(height: ResultTokens.spaceXxl),
                      Text(
                        'Other ways to go',
                        style: ResultTokens.sectionHeader(context),
                      ),
                      const SizedBox(height: ResultTokens.spaceMd),
                      ...visibleAlternatives(
                        categories: plan.routeCategories,
                        recommended: plan.recommendation,
                      ).map(
                        (alt) => Padding(
                          padding: const EdgeInsets.only(
                            bottom: ResultTokens.spaceMd,
                          ),
                          child: LegacyAlternativeCard(
                            title: alt.title,
                            route: alt.route,
                          ),
                        ),
                      ),
                    ],
                    if (provider.replanError != null) ...[
                      const SizedBox(height: ResultTokens.spaceLg),
                      ErrorBanner(message: provider.replanError!),
                    ],
                    if (view.route?.googlePolyline != null ||
                        view.route?.googleRouteToken != null)
                      const SizedBox.shrink(
                        key: Key('nav_payload_retained'),
                      ),
                  ],
                  ),
                ),
              ),
            ),
          ),
          ResultBottomActions(
            mapsEnabled: origin.isNotEmpty && destination.isNotEmpty,
            replanLoading: replanLoading,
            onOpenMaps: () => _openMapsHandoff(
              context: context,
              origin: origin,
              destination: destination,
              travelMode: travelMode,
            ),
            onReplan: () => _openReplanSheet(context),
          ),
        ],
      ),
    );
  }

  TopJourneyOption? _findSelected(
    List<TopJourneyOption> options,
    TopJourneyOption? recommended,
  ) {
    if (options.isEmpty) return recommended;
    final id = _selectedIdentity;
    if (id != null) {
      for (final o in options) {
        if (o.identity == id) return o;
      }
    }
    return recommended ?? options.first;
  }

  RecommendedJourney? _journeyForSelection({
    required CommutePlan plan,
    required TopJourneyOption? selected,
    required RecommendedJourney? fallback,
  }) {
    if (selected == null) return fallback;
    final id = selected.identity;
    if (plan.recommendedJourney?.candidateId == id) {
      return plan.recommendedJourney;
    }
    for (final j in plan.journeys) {
      if (j.candidateId == id) return j;
    }
    return fallback;
  }

  String _whyReason({
    required CommutePlan plan,
    required TopJourneyOption? option,
    required bool useTop5,
  }) {
    if (useTop5 && option != null) {
      return displayReason(option.reason);
    }
    return explanationForPlan(plan).summary;
  }
}

List<TopJourneyOption> _resolveTopOptions(
  CommutePlan plan,
  _RecommendationView view,
) {
  final selection = plan.topSelection;
  if (selection != null && !selection.isEmpty) {
    return selection.displayJourneys;
  }
  // Backward compatible: synthesize a single option from recommendation.
  final route = view.route;
  if (route == null) return const [];
  return [
    TopJourneyOption(
      routeId: route.routeId,
      candidateId: route.routeId,
      mode: route.mode,
      modeSignature: route.modeSignature,
      componentModes: route.componentModes,
      // Keep numeric values even when status is unknown so UI can show "~N min".
      duration: route.travelTimeMinutes,
      cost: route.cost,
      costStatus: route.costStatus,
      durationStatus: route.durationStatus,
      walkingDistanceMeters: view.journey?.walkingDistanceMeters,
      transfers: view.journey?.transferCount ?? route.transfers,
      isRecommended: true,
      reason: '',
      rank: 1,
    ),
  ];
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
    final scheme = Theme.of(context).colorScheme;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: ResultTokens.surfaceMuted(scheme),
        borderRadius: BorderRadius.circular(ResultTokens.radiusCard),
        border: Border.all(color: ResultTokens.hairline(scheme)),
      ),
      child: Padding(
        padding: const EdgeInsets.all(ResultTokens.spaceLg),
        child: Text(
          "We couldn't find a suitable way to make this trip with your "
          'current preferences.',
          style: Theme.of(context).textTheme.titleMedium,
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
        style: ResultTokens.stepMeta(context),
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

    final scheme = Theme.of(context).colorScheme;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: ResultTokens.surfaceMuted(scheme),
        borderRadius: BorderRadius.circular(ResultTokens.radiusRow),
        border: Border.all(color: ResultTokens.hairline(scheme)),
      ),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Historical context', style: ResultTokens.sectionHeader(context)),
            const SizedBox(height: 6),
            ...lines.map(
              (l) => Text(l, style: ResultTokens.stepMeta(context)),
            ),
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
            ? scheme.tertiaryContainer.withValues(alpha: 0.45)
            : ResultTokens.surfaceMuted(scheme),
        borderRadius: BorderRadius.circular(ResultTokens.radiusRow),
        border: Border.all(color: ResultTokens.hairline(scheme)),
      ),
      child: Padding(
        padding: const EdgeInsets.all(ResultTokens.spaceLg),
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
                  ? 'GoWise found a better option based on the '
                      'updated conditions.'
                  : 'GoWise checked again — your current plan still fits.',
              style: ResultTokens.explanation(context),
            ),
            if (safeReplanExplanation(replan.explanation) != null) ...[
              const SizedBox(height: 8),
              Text(
                safeReplanExplanation(replan.explanation)!,
                style: ResultTokens.stepMeta(context),
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
              'Tell GoWise what changed and it will re-evaluate.',
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
