import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../core/config/app_config.dart';
import '../../../core/utils/bengaluru_departure.dart';
import '../../../core/utils/constraint_parser.dart';
import '../../../data/places_api_client.dart';
import '../../../domain/entities/commute_request.dart';
import '../../../domain/entities/user_preferences.dart';
import '../../providers/commute_provider.dart';
import '../../widgets/commute_widgets.dart';
import '../../widgets/place_autocomplete_field.dart';
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

  ResolvedPlace? _originPlace;
  ResolvedPlace? _destinationPlace;

  OptimizationProfile _profile = OptimizationProfile.balanced;
  bool _avoidHeavyTraffic = true;
  bool _excludeCabs = false;
  bool _excludeAutos = false;
  bool _limitWalking = false;

  @override
  void initState() {
    super.initState();
    _baseUrl = TextEditingController(text: AppConfig.initialApiBaseUrl);
    _origin = TextEditingController();
    _destination = TextEditingController();
    _departure =
        TextEditingController(text: BengaluruDeparture.defaultDisplay());
    _maxWalk = TextEditingController(text: '20');
    _baseUrl.addListener(() => setState(() {}));
    _origin.addListener(() => setState(() {}));
    _destination.addListener(() => setState(() {}));
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
        "Couldn't reach Commute Agent.",
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
      excludeAutos: _excludeAutos,
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
      preferenceProfile: _profile.preferenceProfileName,
      originLat: _originPlace?.latitude,
      originLon: _originPlace?.longitude,
      destinationLat: _destinationPlace?.latitude,
      destinationLon: _destinationPlace?.longitude,
      originEndpoint: _originPlace?.toEndpointJson(),
      destinationEndpoint: _destinationPlace?.toEndpointJson(),
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
    final hasInput =
        _origin.text.trim().isNotEmpty || _destination.text.trim().isNotEmpty;

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
                  key: const Key('planner_header'),
                  style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                        fontWeight: FontWeight.w700,
                        letterSpacing: -0.6,
                      ),
                ),
                const SizedBox(height: 6),
                Text(
                  'Your commute, intelligently composed.',
                  style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                        color: scheme.onSurfaceVariant,
                      ),
                ),
                const SizedBox(height: 24),
                if (!hasInput && !loading && provider.errorTitle == null)
                  _EmptyPrompt(scheme: scheme),
                Form(
                  key: _formKey,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      PlaceAutocompleteField(
                        key: const Key('origin_place_field'),
                        controller: _origin,
                        baseUrl: AppConfig.normalizeBaseUrl(_baseUrl.text),
                        label: 'Origin',
                        hint: 'Where are you starting?',
                        prefixIcon: Icons.trip_origin,
                        onPlaceResolved: (place) =>
                            setState(() => _originPlace = place),
                        validator: (v) =>
                            (v == null || v.trim().isEmpty) ? 'Required' : null,
                      ),
                      const SizedBox(height: 12),
                      PlaceAutocompleteField(
                        key: const Key('destination_place_field'),
                        controller: _destination,
                        baseUrl: AppConfig.normalizeBaseUrl(_baseUrl.text),
                        label: 'Destination',
                        hint: 'Search a Bengaluru place',
                        prefixIcon: Icons.flag_outlined,
                        onPlaceResolved: (place) =>
                            setState(() => _destinationPlace = place),
                        validator: (v) =>
                            (v == null || v.trim().isEmpty) ? 'Required' : null,
                      ),
                      if (_originPlace != null || _destinationPlace != null)
                        Padding(
                          padding: const EdgeInsets.only(top: 6),
                          child: Text(
                            'Place selected — coordinates will be sent with your plan.',
                            style: Theme.of(context)
                                .textTheme
                                .bodySmall
                                ?.copyWith(color: scheme.onSurfaceVariant),
                          ),
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
                        'Preference',
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
                        'Avoid',
                        style: Theme.of(context).textTheme.titleSmall?.copyWith(
                              fontWeight: FontWeight.w600,
                            ),
                      ),
                      const SizedBox(height: 8),
                      SwitchListTile(
                        key: const Key('exclude_cab'),
                        contentPadding: EdgeInsets.zero,
                        title: const Text('Avoid cab'),
                        value: _excludeCabs,
                        onChanged: (v) => setState(() => _excludeCabs = v),
                      ),
                      SwitchListTile(
                        key: const Key('exclude_auto'),
                        contentPadding: EdgeInsets.zero,
                        title: const Text('Avoid auto'),
                        value: _excludeAutos,
                        onChanged: (v) => setState(() => _excludeAutos = v),
                      ),
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        title: const Text('Prefer lower traffic'),
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
                                    'Use 10.0.2.2:8000 on Android emulator',
                              ),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 20),
                      FilledButton(
                        key: const Key('plan_cta'),
                        onPressed: loading ? null : _plan,
                        child: loading
                            ? const Column(
                                children: [
                                  Row(
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
                                          'Planning your commute…',
                                          key: Key('planning_loading'),
                                          overflow: TextOverflow.ellipsis,
                                        ),
                                      ),
                                    ],
                                  ),
                                  SizedBox(height: 6),
                                  Text(
                                    'Comparing travel options for you.',
                                    style: TextStyle(
                                      fontSize: 12,
                                      color: Colors.white70,
                                    ),
                                  ),
                                ],
                              )
                            : const Text('Plan my commute'),
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

class _EmptyPrompt extends StatelessWidget {
  const _EmptyPrompt({required this.scheme});
  final ColorScheme scheme;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 20),
      child: DecoratedBox(
        decoration: BoxDecoration(
          color: scheme.surfaceContainerHighest.withValues(alpha: 0.45),
          borderRadius: BorderRadius.circular(16),
        ),
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Where are you heading?',
                style: Theme.of(context).textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
              ),
              const SizedBox(height: 6),
              Text(
                "Enter your origin and destination — Commute Agent will "
                'compose the best way to get there.',
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: scheme.onSurfaceVariant,
                    ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
