import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../core/config/app_config.dart';
import '../../../core/utils/bengaluru_departure.dart';
import '../../../core/utils/constraint_parser.dart';
import '../../../data/places_api_client.dart';
import '../../../domain/entities/commute_request.dart';
import '../../../domain/entities/user_preferences.dart';
import '../../providers/commute_provider.dart';
import '../../theme/planner_tokens.dart';
import '../../widgets/commute_widgets.dart';
import '../../widgets/place_autocomplete_field.dart';
import '../../widgets/planner/control_row.dart';
import '../../widgets/planner/preference_chip.dart';
import '../../widgets/planner/route_composer_card.dart';
import '../results/result_page.dart';

class PlannerPage extends StatefulWidget {
  const PlannerPage({super.key});

  @override
  State<PlannerPage> createState() => _PlannerPageState();
}

class _PlannerPageState extends State<PlannerPage> {
  final _formKey = GlobalKey<FormState>();
  final _originFieldKey = GlobalKey<PlaceAutocompleteFieldState>();
  final _destinationFieldKey = GlobalKey<PlaceAutocompleteFieldState>();

  late final TextEditingController _baseUrl;
  late final TextEditingController _origin;
  late final TextEditingController _destination;
  late final TextEditingController _departure;
  late final TextEditingController _maxWalk;

  ResolvedPlace? _originPlace;
  ResolvedPlace? _destinationPlace;

  OptimizationProfile _profile = OptimizationProfile.balanced;
  bool _excludeCabs = false;
  bool _excludeAutos = false;
  bool _limitWalking = false;
  bool _moreControlsOpen = true;

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

  String _preferenceIcon(OptimizationProfile p) {
    switch (p) {
      case OptimizationProfile.balanced:
        return '✨';
      case OptimizationProfile.fastest:
        return '⚡';
      case OptimizationProfile.cheapest:
        return '₹';
      case OptimizationProfile.lessWalking:
        return '🚶';
      case OptimizationProfile.moreReliable:
        return '🛡';
      case OptimizationProfile.lowerTraffic:
        return '🚦';
    }
  }

  void _swapRouteEnds() {
    final originText = _origin.text;
    final destinationText = _destination.text;
    final originPlace = _originPlace;
    final destinationPlace = _destinationPlace;
    _originFieldKey.currentState
        ?.bindSelection(destinationText, destinationPlace);
    _destinationFieldKey.currentState
        ?.bindSelection(originText, originPlace);
    setState(() {
      _originPlace = destinationPlace;
      _destinationPlace = originPlace;
    });
  }

  Future<void> _editDeparture() async {
    DateTime initial;
    try {
      initial = BengaluruDeparture.parseIstWallClock(_departure.text);
    } catch (_) {
      initial = BengaluruDeparture.nowIst().add(const Duration(hours: 1));
    }
    var pending = initial;

    await showCupertinoModalPopup<void>(
      context: context,
      builder: (ctx) {
        return Container(
          height: 320,
          color: CupertinoColors.systemBackground.resolveFrom(ctx),
          child: Column(
            children: [
              SizedBox(
                height: 48,
                child: Row(
                  children: [
                    CupertinoButton(
                      onPressed: () {
                        setState(() {
                          _departure.text =
                              BengaluruDeparture.defaultDisplay(
                            ahead: const Duration(minutes: 2),
                          );
                        });
                        Navigator.of(ctx).pop();
                      },
                      child: const Text('Leave now'),
                    ),
                    const Spacer(),
                    CupertinoButton(
                      onPressed: () {
                        setState(() {
                          _departure.text =
                              BengaluruDeparture.formatIstDisplay(pending);
                        });
                        Navigator.of(ctx).pop();
                      },
                      child: const Text('Done'),
                    ),
                  ],
                ),
              ),
              Expanded(
                child: CupertinoDatePicker(
                  mode: CupertinoDatePickerMode.dateAndTime,
                  initialDateTime: initial,
                  use24hFormat: true,
                  onDateTimeChanged: (v) => pending = v,
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  Future<void> _plan() async {
    final provider = context.read<CommuteProvider>();
    if (provider.isLoading) return;

    final base = AppConfig.normalizeBaseUrl(_baseUrl.text);
    // Empty base = same-origin (Cloud Run serves UI + API together).
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

    // "Lower traffic" preference carries avoidHeavyTraffic intent (UI switch removed).
    final avoidHeavyTraffic =
        _profile == OptimizationProfile.lowerTraffic;

    final prefs = _profile.toWeights(
      avoidHeavyTraffic: avoidHeavyTraffic,
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
    final canSubmit = _origin.text.trim().isNotEmpty &&
        _destination.text.trim().isNotEmpty;
    final base = AppConfig.normalizeBaseUrl(_baseUrl.text);

    return Scaffold(
      backgroundColor: PlannerTokens.background(scheme),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 560),
            child: Form(
              key: _formKey,
              child: ListView(
                padding: const EdgeInsets.fromLTRB(
                  PlannerTokens.spaceLg,
                  PlannerTokens.spaceMd,
                  PlannerTokens.spaceLg,
                  PlannerTokens.spaceXl,
                ),
                children: [
                  Text(
                    'GoWise',
                    key: const Key('planner_header'),
                    style: PlannerTokens.brandTitle(context),
                  ),
                  const SizedBox(height: PlannerTokens.spaceXs),
                  Text(
                    'Plan your journey',
                    style: PlannerTokens.heroTitle(context),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    "I'll compose the best way to get there.",
                    style: PlannerTokens.supporting(context),
                  ),
                  const SizedBox(height: PlannerTokens.spaceLg),
                  RouteComposerCard(
                    originKey: _originFieldKey,
                    destinationKey: _destinationFieldKey,
                    originController: _origin,
                    destinationController: _destination,
                    baseUrl: base,
                    onOriginResolved: (place) =>
                        setState(() => _originPlace = place),
                    onDestinationResolved: (place) =>
                        setState(() => _destinationPlace = place),
                    onSwap: _swapRouteEnds,
                  ),
                  if (_originPlace != null || _destinationPlace != null) ...[
                    const SizedBox(height: PlannerTokens.spaceXs),
                    Text(
                      'Place selected — coordinates will be sent with your plan.',
                      style: PlannerTokens.rowSubtitle(context),
                    ),
                  ],
                  const SizedBox(height: PlannerTokens.spaceMd),
                  _DepartureRow(
                    value: _departure.text,
                    onTap: _editDeparture,
                  ),
                  const SizedBox(height: PlannerTokens.spaceLg),
                  Text(
                    'How should I optimize?',
                    style: PlannerTokens.sectionLabel(context),
                  ),
                  const SizedBox(height: PlannerTokens.spaceSm),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: OptimizationProfile.values.map((p) {
                      final selected = _profile == p;
                      return PreferenceChip(
                        key: Key('pref_${p.name}'),
                        label: p.label,
                        icon: _preferenceIcon(p),
                        selected: selected,
                        onSelected: () => setState(() => _profile = p),
                      );
                    }).toList(),
                  ),
                  const SizedBox(height: PlannerTokens.spaceLg),
                  _MoreControlsSection(
                    open: _moreControlsOpen,
                    onToggle: () => setState(
                      () => _moreControlsOpen = !_moreControlsOpen,
                    ),
                    excludeCabs: _excludeCabs,
                    excludeAutos: _excludeAutos,
                    limitWalking: _limitWalking,
                    maxWalkController: _maxWalk,
                    onExcludeCabs: (v) => setState(() => _excludeCabs = v),
                    onExcludeAutos: (v) => setState(() => _excludeAutos = v),
                    onLimitWalking: (v) => setState(() => _limitWalking = v),
                    baseUrlController: _baseUrl,
                  ),
                  const SizedBox(height: PlannerTokens.spaceLg),
                  _ComposeButton(
                    loading: loading,
                    enabled: canSubmit,
                    onPressed: _plan,
                  ),
                  if (provider.errorTitle != null) ...[
                    const SizedBox(height: PlannerTokens.spaceMd),
                    PlanErrorPanel(
                      key: const Key('planner_error_panel'),
                      title: provider.errorTitle!,
                      detail: provider.errorDetail ?? '',
                      onRetry: loading || !canSubmit ? null : _plan,
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _DepartureRow extends StatelessWidget {
  const _DepartureRow({required this.value, required this.onTap});

  final String value;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final display = value.trim().isEmpty ? 'Leave now' : value;
    return Semantics(
      button: true,
      label: 'Departure $display',
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          key: const Key('departure_row'),
          onTap: onTap,
          borderRadius: BorderRadius.circular(PlannerTokens.radiusRow),
          child: Ink(
            decoration: BoxDecoration(
              color: PlannerTokens.surface(scheme),
              borderRadius: BorderRadius.circular(PlannerTokens.radiusRow),
              border: Border.all(color: PlannerTokens.hairline(scheme)),
            ),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
              child: Row(
                children: [
                  Icon(
                    CupertinoIcons.clock,
                    size: 20,
                    color: scheme.primary,
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Departure',
                          style: PlannerTokens.rowSubtitle(context),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          display,
                          style: PlannerTokens.rowTitle(context),
                        ),
                      ],
                    ),
                  ),
                  Icon(
                    CupertinoIcons.chevron_forward,
                    size: 18,
                    color: PlannerTokens.mutedText(scheme),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _MoreControlsSection extends StatelessWidget {
  const _MoreControlsSection({
    required this.open,
    required this.onToggle,
    required this.excludeCabs,
    required this.excludeAutos,
    required this.limitWalking,
    required this.maxWalkController,
    required this.onExcludeCabs,
    required this.onExcludeAutos,
    required this.onLimitWalking,
    required this.baseUrlController,
  });

  final bool open;
  final VoidCallback onToggle;
  final bool excludeCabs;
  final bool excludeAutos;
  final bool limitWalking;
  final TextEditingController maxWalkController;
  final ValueChanged<bool> onExcludeCabs;
  final ValueChanged<bool> onExcludeAutos;
  final ValueChanged<bool> onLimitWalking;
  final TextEditingController baseUrlController;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: PlannerTokens.surface(scheme).withValues(alpha: 0.65),
        borderRadius: BorderRadius.circular(PlannerTokens.radiusCard),
      ),
      child: Column(
        children: [
          InkWell(
            key: const Key('more_controls_toggle'),
            onTap: onToggle,
            borderRadius: BorderRadius.circular(PlannerTokens.radiusCard),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      'More control',
                      style: PlannerTokens.rowTitle(context),
                    ),
                  ),
                  Icon(
                    open
                        ? CupertinoIcons.chevron_up
                        : CupertinoIcons.chevron_down,
                    size: 18,
                    color: PlannerTokens.mutedText(scheme),
                  ),
                ],
              ),
            ),
          ),
          if (open)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  ControlRow(
                    key: const Key('exclude_cab'),
                    title: 'Avoid cab',
                    subtitle: 'Skip taxi and rideshare options',
                    value: excludeCabs,
                    onChanged: onExcludeCabs,
                  ),
                  ControlRow(
                    key: const Key('exclude_auto'),
                    title: 'Avoid auto',
                    subtitle: 'Skip auto-rickshaw options',
                    value: excludeAutos,
                    onChanged: onExcludeAutos,
                  ),
                  ControlRow(
                    title: 'Limit walking',
                    subtitle: 'Cap walking time when possible',
                    value: limitWalking,
                    onChanged: onLimitWalking,
                  ),
                  if (limitWalking) ...[
                    const SizedBox(height: 4),
                    TextFormField(
                      controller: maxWalkController,
                      decoration: InputDecoration(
                        labelText: 'Max walking (minutes)',
                        filled: true,
                        fillColor: PlannerTokens.surfaceStrong(scheme),
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(12),
                          borderSide: BorderSide.none,
                        ),
                      ),
                      keyboardType: TextInputType.number,
                    ),
                  ],
                  const SizedBox(height: PlannerTokens.spaceSm),
                  Theme(
                    data: Theme.of(context).copyWith(
                      dividerColor: Colors.transparent,
                    ),
                    child: ExpansionTile(
                      tilePadding: EdgeInsets.zero,
                      childrenPadding: EdgeInsets.zero,
                      title: Text(
                        'Advanced',
                        style: Theme.of(context).textTheme.bodyMedium,
                      ),
                      children: [
                        TextFormField(
                          controller: baseUrlController,
                          decoration: const InputDecoration(
                            labelText: 'API base URL',
                            hintText: 'Leave empty for same-origin',
                            helperText:
                                'Empty / relative = same host (Cloud Run). '
                                'Android emulator: Local (10.0.2.2). '
                                'Cloud Run chip = absolute demo URL.',
                          ),
                        ),
                        const SizedBox(height: 8),
                        Wrap(
                          spacing: 8,
                          runSpacing: 8,
                          children: [
                            ActionChip(
                              key: const Key('api_base_same_origin'),
                              label: const Text('Same origin'),
                              onPressed: () {
                                baseUrlController.text = '';
                              },
                            ),
                            ActionChip(
                              key: const Key('api_base_cloud'),
                              label: const Text('Cloud Run'),
                              onPressed: () {
                                baseUrlController.text =
                                    AppConfig.cloudRunDefaultBaseUrl;
                              },
                            ),
                            ActionChip(
                              key: const Key('api_base_local'),
                              label: const Text('Local (this device)'),
                              onPressed: () {
                                baseUrlController.text = AppConfig
                                    .defaultLocalBaseUrlForPlatform();
                              },
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

class _ComposeButton extends StatelessWidget {
  const _ComposeButton({
    required this.loading,
    required this.enabled,
    required this.onPressed,
  });

  final bool loading;
  final bool enabled;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return SizedBox(
      width: double.infinity,
      height: 54,
      child: FilledButton(
        key: const Key('plan_cta'),
        onPressed: (enabled && !loading) ? onPressed : null,
        style: FilledButton.styleFrom(
          backgroundColor: scheme.primary,
          foregroundColor: scheme.onPrimary,
          disabledBackgroundColor:
              scheme.primary.withValues(alpha: 0.35),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(PlannerTokens.radiusButton),
          ),
          elevation: 0,
          textStyle: Theme.of(context).textTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.w700,
                letterSpacing: -0.2,
              ),
        ),
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
                      'Planning your commute…',
                      key: Key('planning_loading'),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                ],
              )
            : const Text('Compose commute'),
      ),
    );
  }
}
