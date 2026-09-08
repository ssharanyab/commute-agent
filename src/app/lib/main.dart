import 'package:flutter/material.dart';

import 'api_client.dart';
import 'config.dart';
import 'constraint_parser.dart';
import 'departure_time.dart';
import 'models.dart';

void main() {
  runApp(const CommuteAgentApp());
}

class CommuteAgentApp extends StatelessWidget {
  const CommuteAgentApp({super.key});

  @override
  Widget build(BuildContext context) {
    final base = ThemeData(
      useMaterial3: true,
      colorScheme: ColorScheme.fromSeed(
        seedColor: const Color(0xFF0F6E56),
        brightness: Brightness.light,
      ),
    );
    return MaterialApp(
      title: 'Patchamomma Commute',
      debugShowCheckedModeBanner: false,
      theme: base.copyWith(
        inputDecorationTheme: const InputDecorationTheme(
          border: OutlineInputBorder(),
          isDense: true,
        ),
        filledButtonTheme: FilledButtonThemeData(
          style: FilledButton.styleFrom(
            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
          ),
        ),
      ),
      home: const PlannerPage(),
    );
  }
}

class PlannerPage extends StatefulWidget {
  const PlannerPage({super.key});

  @override
  State<PlannerPage> createState() => _PlannerPageState();
}

class _PlannerPageState extends State<PlannerPage> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _baseUrl;
  late final TextEditingController _origin;
  late final TextEditingController _destination;
  late final TextEditingController _departure;
  late final TextEditingController _maxWalk;
  late final TextEditingController _timeWeight;
  late final TextEditingController _costWeight;
  late final TextEditingController _walkWeight;
  late final TextEditingController _constraintNotes;

  bool _avoidHeavyTraffic = true;
  bool _excludeCabs = false;
  bool _showPrefs = false;
  bool _loading = false;
  String? _errorTitle;
  String? _errorDetail;

  @override
  void initState() {
    super.initState();
    _baseUrl = TextEditingController(
      text: AppConfig.initialApiBaseUrl,
    );
    _origin = TextEditingController(text: 'Electronic City, Bengaluru');
    _destination = TextEditingController(text: 'Koramangala, Bengaluru');
    // Initial display only — PLAN re-validates / rebuilds departure at send time.
    _departure = TextEditingController(
      text: BengaluruDeparture.defaultDisplay(),
    );
    _maxWalk = TextEditingController(text: '20');
    _timeWeight = TextEditingController(text: '8');
    _costWeight = TextEditingController(text: '1');
    _walkWeight = TextEditingController(text: '1');
    _constraintNotes = TextEditingController();
  }

  @override
  void dispose() {
    _baseUrl.dispose();
    _origin.dispose();
    _destination.dispose();
    _departure.dispose();
    _maxWalk.dispose();
    _timeWeight.dispose();
    _costWeight.dispose();
    _walkWeight.dispose();
    _constraintNotes.dispose();
    super.dispose();
  }

  Future<void> _plan() async {
    setState(() {
      _errorTitle = null;
      _errorDetail = null;
      _loading = true;
    });
    final base = AppConfig.normalizeBaseUrl(_baseUrl.text);
    if (base.isEmpty) {
      setState(() {
        _loading = false;
        _errorTitle = "Couldn't plan this commute";
        _errorDetail =
            'Set API base URL (or pass --dart-define=API_BASE_URL=...).';
      });
      return;
    }
    if (!(_formKey.currentState?.validate() ?? false)) {
      setState(() => _loading = false);
      return;
    }

    final departure = BengaluruDeparture.resolveForPlan(_departure.text);
    if (departure.adjusted) {
      _departure.text = departure.displayIst;
    }

    final maxWalk = double.tryParse(_maxWalk.text.trim());
    final excluded = ConstraintParser.excludedModes(
      excludeCabs: _excludeCabs,
      notes: _constraintNotes.text,
    );
    final body = <String, dynamic>{
      'origin': _origin.text.trim(),
      'destination': _destination.text.trim(),
      'departure_time': departure.apiIso8601,
      'invoke_gemini': true,
      'preferences': {
        'avoid_heavy_traffic': _avoidHeavyTraffic,
        if (maxWalk != null) 'max_walking_minutes': maxWalk,
        if (excluded.isNotEmpty) 'excluded_modes': excluded,
        if (_showPrefs) ...{
          'time_weight': double.tryParse(_timeWeight.text) ?? 1.0,
          'cost_weight': double.tryParse(_costWeight.text) ?? 1.0,
          'walking_weight': double.tryParse(_walkWeight.text) ?? 1.0,
        },
      },
    };

    final client = CommuteApiClient(baseUrl: base);
    try {
      final plan = await client.plan(body);
      if (!mounted) return;
      if (!plan.ok || plan.error != null) {
        setState(() {
          _loading = false;
          _errorTitle = "Couldn't plan this commute";
          _errorDetail = _humanizePlanFailure(plan);
        });
        return;
      }
      setState(() => _loading = false);
      await Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => ResultPage(
            apiBaseUrl: base,
            planRequest: body,
            plan: plan,
          ),
        ),
      );
    } on ApiException catch (e) {
      setState(() {
        _loading = false;
        _errorTitle = "Couldn't plan this commute";
        _errorDetail = e.message;
      });
    } catch (e) {
      setState(() {
        _loading = false;
        _errorTitle = "Couldn't plan this commute";
        _errorDetail = 'Request failed: $e';
      });
    } finally {
      client.close();
    }
  }

  String _humanizePlanFailure(PlanResponse plan) {
    final detail = (plan.errorDetail ?? '').trim();
    final code = plan.error ?? '';
    if (code == 'MAPS_API_UNAVAILABLE') {
      if (detail.toLowerCase().contains('timestamp') ||
          detail.toLowerCase().contains('future')) {
        return 'Google Maps rejected the departure time. '
            'Choose a future time and try again.'
            '${detail.isEmpty ? '' : '\n\n$detail'}';
      }
      return 'Google Maps could not return routes.'
          '${detail.isEmpty ? '' : '\n\n$detail'}';
    }
    if (code == 'NO_ROUTES') {
      return 'No routes were found for this commute.'
          '${detail.isEmpty ? '' : '\n\n$detail'}';
    }
    if (code == 'NO_VALID_ROUTES') {
      return 'No route satisfies your hard constraints '
          '(for example excluded modes, walking, or cost limits).'
          '${detail.isEmpty ? '' : '\n\n$detail'}';
    }
    if (code.isNotEmpty) {
      return detail.isNotEmpty ? '$code\n\n$detail' : code;
    }
    return detail.isNotEmpty ? detail : 'The API returned an unsuccessful plan.';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 560),
            child: ListView(
              padding: const EdgeInsets.fromLTRB(24, 32, 24, 40),
              children: [
                Text(
                  'Patchamomma',
                  style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                        fontWeight: FontWeight.w700,
                        letterSpacing: -0.5,
                      ),
                ),
                const SizedBox(height: 4),
                Text(
                  'Commute planner',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                ),
                const SizedBox(height: 28),
                Form(
                  key: _formKey,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      TextFormField(
                        controller: _baseUrl,
                        decoration: const InputDecoration(
                          labelText: 'API base URL',
                          hintText: 'http://host:port',
                              helperText:
                                  'dart-define wins; else local http://127.0.0.1:8000',
                        ),
                        validator: (v) =>
                            (v == null || v.trim().isEmpty) ? 'Required' : null,
                      ),
                      const SizedBox(height: 16),
                      TextFormField(
                        controller: _origin,
                        decoration: const InputDecoration(labelText: 'Origin'),
                        validator: (v) =>
                            (v == null || v.trim().isEmpty) ? 'Required' : null,
                      ),
                      const SizedBox(height: 12),
                      TextFormField(
                        controller: _destination,
                        decoration:
                            const InputDecoration(labelText: 'Destination'),
                        validator: (v) =>
                            (v == null || v.trim().isEmpty) ? 'Required' : null,
                      ),
                      const SizedBox(height: 12),
                      TextFormField(
                        controller: _departure,
                        decoration: const InputDecoration(
                          labelText: 'Departure time (Bengaluru / IST)',
                          hintText: 'yyyy-MM-dd HH:mm',
                          helperText:
                              'Local India time (Asia/Kolkata). Sent to API as ISO-8601.',
                        ),
                      ),
                      const SizedBox(height: 8),
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        title: const Text('Avoid heavy traffic'),
                        value: _avoidHeavyTraffic,
                        onChanged: (v) =>
                            setState(() => _avoidHeavyTraffic = v),
                      ),
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        title: const Text('Exclude cabs / taxis'),
                        subtitle: const Text(
                          'Hard constraint — cab/DRIVE routes cannot be recommended',
                        ),
                        value: _excludeCabs,
                        onChanged: (v) => setState(() => _excludeCabs = v),
                      ),
                      TextFormField(
                        controller: _maxWalk,
                        decoration: const InputDecoration(
                          labelText: 'Maximum walking time (minutes)',
                        ),
                        keyboardType: TextInputType.number,
                      ),
                      const SizedBox(height: 12),
                      TextFormField(
                        controller: _constraintNotes,
                        decoration: const InputDecoration(
                          labelText: 'Constraint notes (optional)',
                          hintText: 'e.g. No cabs / Avoid taxis',
                          helperText:
                              'Only clear cab/taxi exclusions are applied as hard rules',
                        ),
                        maxLines: 2,
                      ),
                      const SizedBox(height: 8),
                      CheckboxListTile(
                        contentPadding: EdgeInsets.zero,
                        title: const Text('Preference weights (time / cost / walking)'),
                        value: _showPrefs,
                        onChanged: (v) =>
                            setState(() => _showPrefs = v ?? false),
                      ),
                      if (_showPrefs) ...[
                        const SizedBox(height: 8),
                        Row(
                          children: [
                            Expanded(
                              child: TextFormField(
                                controller: _timeWeight,
                                decoration: const InputDecoration(
                                  labelText: 'Time',
                                ),
                                keyboardType: TextInputType.number,
                              ),
                            ),
                            const SizedBox(width: 8),
                            Expanded(
                              child: TextFormField(
                                controller: _costWeight,
                                decoration: const InputDecoration(
                                  labelText: 'Cost',
                                ),
                                keyboardType: TextInputType.number,
                              ),
                            ),
                            const SizedBox(width: 8),
                            Expanded(
                              child: TextFormField(
                                controller: _walkWeight,
                                decoration: const InputDecoration(
                                  labelText: 'Walking',
                                ),
                                keyboardType: TextInputType.number,
                              ),
                            ),
                          ],
                        ),
                      ],
                      const SizedBox(height: 24),
                      FilledButton(
                        onPressed: _loading ? null : _plan,
                        child: _loading
                            ? const SizedBox(
                                height: 22,
                                width: 22,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  color: Colors.white,
                                ),
                              )
                            : const Text('PLAN COMMUTE'),
                      ),
                      if (_errorTitle != null) ...[
                        const SizedBox(height: 16),
                        _PlanErrorPanel(
                          title: _errorTitle!,
                          detail: _errorDetail ?? '',
                          onRetry: _loading ? null : _plan,
                        ),
                      ],
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class ResultPage extends StatefulWidget {
  const ResultPage({
    super.key,
    required this.apiBaseUrl,
    required this.planRequest,
    required this.plan,
  });

  final String apiBaseUrl;
  final Map<String, dynamic> planRequest;
  final PlanResponse plan;

  @override
  State<ResultPage> createState() => _ResultPageState();
}

class _ResultPageState extends State<ResultPage> {
  ReplanResponse? _replan;
  bool _replanLoading = false;
  String? _replanError;

  Future<void> _openReplanSheet() async {
    final change = await showModalBottomSheet<ContextChangePayload>(
      context: context,
      isScrollControlled: true,
      builder: (ctx) => const _ReplanSheet(),
    );
    if (change == null || !mounted) return;
    await _runReplan(change);
  }

  Future<void> _runReplan(ContextChangePayload change) async {
    setState(() {
      _replanLoading = true;
      _replanError = null;
    });
    final client = CommuteApiClient(baseUrl: widget.apiBaseUrl);
    try {
      final payload = {
        'request': widget.planRequest,
        'context_change': change.toJson(),
        'refresh_live_routes': false,
        'invoke_gemini': true,
      };
      final result = await client.replan(payload);
      if (!mounted) return;
      setState(() {
        _replan = result;
        _replanLoading = false;
        if (!result.ok && result.error != null) {
          _replanError = '${result.error} ${result.errorDetail ?? ''}'.trim();
        }
      });
    } on ApiException catch (e) {
      setState(() {
        _replanLoading = false;
        _replanError = e.message;
      });
    } catch (e) {
      setState(() {
        _replanLoading = false;
        _replanError = 'Replan failed: $e';
      });
    } finally {
      client.close();
    }
  }

  @override
  Widget build(BuildContext context) {
    final plan = widget.plan;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Recommendation'),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 40),
        children: [
          if (!plan.ok || plan.error != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: _ErrorBanner(
                message:
                    '${plan.error ?? 'Error'} ${plan.errorDetail ?? ''}'.trim(),
              ),
            ),
          _SectionTitle('Recommended route'),
          if (plan.recommendation != null)
            _RouteCard(route: plan.recommendation!, emphasize: true)
          else
            const Text('No recommendation.'),
          const SizedBox(height: 16),
          _SectionTitle('Reasons'),
          _ChipWrap(items: plan.reasons),
          const SizedBox(height: 16),
          _SectionTitle('Gemini explanation'),
          _MetaLine(plan.gemini.statusLabel),
          const SizedBox(height: 6),
          Text(plan.explanation.isEmpty ? '—' : plan.explanation),
          const SizedBox(height: 16),
          _SectionTitle('Provenance'),
          _ChipWrap(items: plan.dataSources),
          if (plan.historicalSignalUsed)
            const Padding(
              padding: EdgeInsets.only(top: 6),
              child: Text('Historical mobility signal used.'),
            ),
          if (plan.provenance?['notes'] is List) ...[
            const SizedBox(height: 6),
            Text(
              (plan.provenance!['notes'] as List).join('\n'),
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
          if (plan.warnings.isNotEmpty) ...[
            const SizedBox(height: 12),
            _SectionTitle('Warnings'),
            ...plan.warnings.map((w) => Text('• $w')),
          ],
          const SizedBox(height: 20),
          _SectionTitle('Alternatives'),
          if (plan.alternatives.isEmpty)
            const Text('No alternatives returned.')
          else
            ...plan.alternatives.map(
              (r) => Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: _RouteCard(route: r),
              ),
            ),
          const SizedBox(height: 24),
          FilledButton.tonal(
            onPressed: _replanLoading ? null : _openReplanSheet,
            child: _replanLoading
                ? const SizedBox(
                    height: 22,
                    width: 22,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Text('REPLAN / CONDITIONS CHANGED'),
          ),
          if (_replanError != null) ...[
            const SizedBox(height: 12),
            _ErrorBanner(message: _replanError!),
          ],
          if (_replan != null) ...[
            const SizedBox(height: 28),
            const Divider(),
            const SizedBox(height: 8),
            _SectionTitle('Adaptive replan'),
            _MetaLine(
              _replan!.recommendationChanged
                  ? 'Recommendation CHANGED'
                  : 'Recommendation unchanged',
            ),
            const SizedBox(height: 12),
            _SectionTitle('Changed context'),
            _ContextBlock(change: _replan!.contextChange),
            const SizedBox(height: 16),
            _SectionTitle('Previous recommendation'),
            if (_replan!.previousRecommendation != null)
              _RouteCard(route: _replan!.previousRecommendation!)
            else
              Text(_replan!.previousRouteId ?? '—'),
            const SizedBox(height: 12),
            _SectionTitle('New recommendation'),
            if (_replan!.newRecommendation != null)
              _RouteCard(
                route: _replan!.newRecommendation!,
                emphasize: true,
              )
            else
              Text(_replan!.newRouteId ?? '—'),
            const SizedBox(height: 12),
            _SectionTitle('Before / after'),
            _BeforeAfter(
              before: _replan!.before,
              after: _replan!.after,
              previousId: _replan!.previousRouteId,
              newId: _replan!.newRouteId,
            ),
            const SizedBox(height: 12),
            _SectionTitle('Why it changed (Gemini)'),
            _MetaLine(_replan!.gemini.statusLabel),
            const SizedBox(height: 6),
            Text(
              _replan!.explanation.isEmpty ? '—' : _replan!.explanation,
            ),
            if (_replan!.provenance?['replan_notes'] is List) ...[
              const SizedBox(height: 12),
              _SectionTitle('Replan provenance'),
              ...(_replan!.provenance!['replan_notes'] as List)
                  .map((n) => Text('• $n')),
            ],
            if (_replan!.dataSources.isNotEmpty) ...[
              const SizedBox(height: 8),
              _ChipWrap(items: _replan!.dataSources),
            ],
          ],
        ],
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
  bool _weather = false;
  String _source = 'simulated';
  final _deltaCongestion = TextEditingController(text: '0.55');
  final _deltaMinutes = TextEditingController(text: '22');
  final _description = TextEditingController(
    text: 'SIMULATED demo traffic spike on recommended route',
  );

  @override
  void dispose() {
    _deltaCongestion.dispose();
    _deltaMinutes.dispose();
    _description.dispose();
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
              'Simulate condition change',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 8),
            Text(
              'Shows adaptive replan without changing backend ranking logic.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Traffic changed'),
              value: _traffic,
              onChanged: (v) => setState(() => _traffic = v),
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Disruption changed'),
              value: _disruption,
              onChanged: (v) => setState(() => _disruption = v),
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Weather changed'),
              value: _weather,
              onChanged: (v) => setState(() => _weather = v),
            ),
            DropdownButtonFormField<String>(
              value: _source,
              decoration: const InputDecoration(labelText: 'Context source'),
              items: const [
                DropdownMenuItem(value: 'simulated', child: Text('simulated')),
                DropdownMenuItem(value: 'live', child: Text('live')),
                DropdownMenuItem(value: 'none', child: Text('none')),
              ],
              onChanged: (v) => setState(() => _source = v ?? 'simulated'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _deltaCongestion,
              decoration: const InputDecoration(
                labelText: 'Congestion delta',
              ),
              keyboardType: TextInputType.number,
            ),
            const SizedBox(height: 8),
            TextField(
              controller: _deltaMinutes,
              decoration: const InputDecoration(
                labelText: 'Travel time delta (minutes)',
              ),
              keyboardType: TextInputType.number,
            ),
            const SizedBox(height: 8),
            TextField(
              controller: _description,
              decoration: const InputDecoration(labelText: 'Description'),
              maxLines: 2,
            ),
            const SizedBox(height: 20),
            FilledButton(
              onPressed: () {
                Navigator.pop(
                  context,
                  ContextChangePayload(
                    trafficChanged: _traffic,
                    disruptionChanged: _disruption,
                    weatherChanged: _weather,
                    contextSource: _source,
                    congestionDelta:
                        double.tryParse(_deltaCongestion.text) ?? 0,
                    travelTimeDeltaMinutes:
                        double.tryParse(_deltaMinutes.text) ?? 0,
                    description: _description.text.trim(),
                  ),
                );
              },
              child: const Text('RUN REPLAN'),
            ),
          ],
        ),
      ),
    );
  }
}

class _RouteCard extends StatelessWidget {
  const _RouteCard({required this.route, this.emphasize = false});

  final RouteSummary route;
  final bool emphasize;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: emphasize
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
              style: Theme.of(context).textTheme.titleSmall?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
            ),
            const SizedBox(height: 6),
            Wrap(
              spacing: 12,
              runSpacing: 4,
              children: [
                Text('Mode: ${route.mode}'),
                Text('Time: ${route.travelTimeMinutes.toStringAsFixed(0)} min'),
                if (route.distanceKm != null)
                  Text('Distance: ${route.distanceKm!.toStringAsFixed(1)} km'),
                Text('Cost: ₹${route.cost.toStringAsFixed(0)}'),
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

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.text);
  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Text(
        text,
        style: Theme.of(context).textTheme.titleMedium?.copyWith(
              fontWeight: FontWeight.w600,
            ),
      ),
    );
  }
}

class _MetaLine extends StatelessWidget {
  const _MetaLine(this.text);
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

class _ChipWrap extends StatelessWidget {
  const _ChipWrap({required this.items});
  final List<String> items;

  @override
  Widget build(BuildContext context) {
    if (items.isEmpty) return const Text('—');
    return Wrap(
      spacing: 6,
      runSpacing: 6,
      children: items
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

class _ErrorBanner extends StatelessWidget {
  const _ErrorBanner({required this.message});
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
        child: Text(
          message,
          style: TextStyle(color: scheme.onErrorContainer),
        ),
      ),
    );
  }
}

class _PlanErrorPanel extends StatelessWidget {
  const _PlanErrorPanel({
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
              Text(
                detail,
                style: TextStyle(color: scheme.onErrorContainer),
              ),
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

class _ContextBlock extends StatelessWidget {
  const _ContextBlock({required this.change});
  final ContextChangePayload? change;

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

class _BeforeAfter extends StatelessWidget {
  const _BeforeAfter({
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
        Text(
          'Score: ${_score(before)} → ${_score(after)}',
        ),
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
