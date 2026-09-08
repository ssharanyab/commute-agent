import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../core/config/app_config.dart';
import '../../../core/utils/bengaluru_departure.dart';
import '../../../core/utils/constraint_parser.dart';
import '../../../domain/entities/commute_request.dart';
import '../../../domain/entities/user_preferences.dart';
import '../../providers/commute_provider.dart';
import '../../widgets/commute_widgets.dart';
import '../results/result_page.dart';

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

  OptimizationProfile _profile = OptimizationProfile.fast;
  bool _avoidHeavyTraffic = true;
  bool _excludeCabs = false;
  bool _limitWalking = true;

  @override
  void initState() {
    super.initState();
    _baseUrl = TextEditingController(text: AppConfig.initialApiBaseUrl);
    _origin = TextEditingController(text: 'Electronic City, Bengaluru');
    _destination = TextEditingController(text: 'Koramangala, Bengaluru');
    _departure =
        TextEditingController(text: BengaluruDeparture.defaultDisplay());
    _maxWalk = TextEditingController(text: '20');
  }

  @override
  void dispose() {
    _baseUrl.dispose();
    _origin.dispose();
    _destination.dispose();
    _departure.dispose();
    _maxWalk.dispose();
    super.dispose();
  }

  Future<void> _plan() async {
    final provider = context.read<CommuteProvider>();
    if (provider.isLoading) return;

    final base = AppConfig.normalizeBaseUrl(_baseUrl.text);
    if (base.isEmpty) {
      provider.setConfigurationError(
        "Couldn't plan this commute",
        'Set API base URL (or pass --dart-define=API_BASE_URL=...).',
      );
      return;
    }
    if (!(_formKey.currentState?.validate() ?? false)) return;

    final departure = BengaluruDeparture.resolveForPlan(_departure.text);
    if (departure.adjusted) {
      _departure.text = departure.displayIst;
    }

    final excluded = ConstraintParser.excludedModes(
      excludeCabs: _excludeCabs,
      notes: '',
    );
    final maxWalk =
        _limitWalking ? double.tryParse(_maxWalk.text.trim()) : null;

    final prefs = _profile.toWeights(
      avoidHeavyTraffic: _avoidHeavyTraffic,
      maxWalkingMinutes: maxWalk,
      excludedModes: excluded,
    );

    final request = CommuteRequest(
      origin: _origin.text.trim(),
      destination: _destination.text.trim(),
      departureTimeIso8601: departure.apiIso8601,
      preferences: prefs,
    );

    final ok = await provider.planCommute(baseUrl: base, request: request);
    if (!mounted || !ok) return;
    await Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => ResultPage(apiBaseUrl: base)),
    );
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<CommuteProvider>();
    final loading = provider.isLoading;
    final scheme = Theme.of(context).colorScheme;

    return Scaffold(
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 560),
            child: ListView(
              padding: const EdgeInsets.fromLTRB(24, 28, 24, 40),
              children: [
                Text(
                  'Commute Agent',
                  style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                        fontWeight: FontWeight.w700,
                        letterSpacing: -0.6,
                      ),
                ),
                const SizedBox(height: 6),
                Text(
                  'Find the route that fits your priorities.',
                  style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                        color: scheme.onSurfaceVariant,
                      ),
                ),
                const SizedBox(height: 28),
                Form(
                  key: _formKey,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      TextFormField(
                        controller: _origin,
                        decoration: const InputDecoration(
                          labelText: 'From',
                          prefixIcon: Icon(Icons.trip_origin),
                        ),
                        validator: (v) =>
                            (v == null || v.trim().isEmpty) ? 'Required' : null,
                      ),
                      const SizedBox(height: 12),
                      TextFormField(
                        controller: _destination,
                        decoration: const InputDecoration(
                          labelText: 'To',
                          prefixIcon: Icon(Icons.flag_outlined),
                        ),
                        validator: (v) =>
                            (v == null || v.trim().isEmpty) ? 'Required' : null,
                      ),
                      const SizedBox(height: 12),
                      TextFormField(
                        controller: _departure,
                        decoration: const InputDecoration(
                          labelText: 'Departure (Bengaluru / IST)',
                          hintText: 'yyyy-MM-dd HH:mm',
                          prefixIcon: Icon(Icons.schedule),
                        ),
                      ),
                      const SizedBox(height: 20),
                      Text(
                        'Optimize for',
                        style: Theme.of(context).textTheme.titleSmall?.copyWith(
                              fontWeight: FontWeight.w600,
                            ),
                      ),
                      const SizedBox(height: 10),
                      Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: OptimizationProfile.values.map((p) {
                          final selected = _profile == p;
                          return ChoiceChip(
                            label: Text(p.label),
                            selected: selected,
                            onSelected: (_) => setState(() => _profile = p),
                          );
                        }).toList(),
                      ),
                      const SizedBox(height: 20),
                      Text(
                        'Constraints',
                        style: Theme.of(context).textTheme.titleSmall?.copyWith(
                              fontWeight: FontWeight.w600,
                            ),
                      ),
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        title: const Text('Avoid cabs'),
                        value: _excludeCabs,
                        onChanged: (v) => setState(() => _excludeCabs = v),
                      ),
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        title: const Text('Avoid heavy traffic'),
                        value: _avoidHeavyTraffic,
                        onChanged: (v) =>
                            setState(() => _avoidHeavyTraffic = v),
                      ),
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        title: const Text('Limit walking'),
                        value: _limitWalking,
                        onChanged: (v) => setState(() => _limitWalking = v),
                      ),
                      if (_limitWalking) ...[
                        TextFormField(
                          controller: _maxWalk,
                          decoration: const InputDecoration(
                            labelText: 'Max walking (minutes)',
                            prefixIcon: Icon(Icons.directions_walk),
                          ),
                          keyboardType: TextInputType.number,
                        ),
                        const SizedBox(height: 8),
                      ],
                      Theme(
                        data: Theme.of(context).copyWith(
                          dividerColor: Colors.transparent,
                        ),
                        child: ExpansionTile(
                          tilePadding: EdgeInsets.zero,
                          title: Text(
                            'Advanced',
                            style: Theme.of(context).textTheme.bodyMedium,
                          ),
                          children: [
                            TextFormField(
                              controller: _baseUrl,
                              decoration: const InputDecoration(
                                labelText: 'API base URL',
                                helperText:
                                    'dart-define wins; else http://127.0.0.1:8000',
                              ),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 20),
                      FilledButton(
                        onPressed: loading ? null : _plan,
                        child: loading
                            ? const Row(
                                mainAxisAlignment: MainAxisAlignment.center,
                                children: [
                                  SizedBox(
                                    height: 20,
                                    width: 20,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                      color: Colors.white,
                                    ),
                                  ),
                                  SizedBox(width: 12),
                                  Flexible(
                                    child: Text(
                                      'Finding the best route…',
                                      overflow: TextOverflow.ellipsis,
                                    ),
                                  ),
                                ],
                              )
                            : const Text('PLAN MY COMMUTE'),
                      ),
                      if (provider.errorTitle != null) ...[
                        const SizedBox(height: 16),
                        PlanErrorPanel(
                          title: provider.errorTitle!,
                          detail: provider.errorDetail ?? '',
                          onRetry: loading ? null : _plan,
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
