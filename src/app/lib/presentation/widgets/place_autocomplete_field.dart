import 'dart:async';

import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';

import '../../core/config/app_config.dart';
import '../../data/places_api_client.dart';
import '../theme/planner_tokens.dart';

/// Origin/destination field with Bengaluru Places autocomplete via backend proxy.
/// Selecting a suggestion fills the text and supplies lat/lon to the parent.
class PlaceAutocompleteField extends StatefulWidget {
  const PlaceAutocompleteField({
    super.key,
    required this.controller,
    required this.baseUrl,
    required this.label,
    required this.hint,
    required this.prefixIcon,
    required this.onPlaceResolved,
    this.validator,
    this.embedded = false,
  });

  final TextEditingController controller;
  final String baseUrl;
  final String label;
  final String hint;
  final IconData prefixIcon;
  final ValueChanged<ResolvedPlace?> onPlaceResolved;
  final FormFieldValidator<String>? validator;

  /// Borderless style for use inside [RouteComposerCard].
  final bool embedded;

  @override
  PlaceAutocompleteFieldState createState() => PlaceAutocompleteFieldState();
}

class PlaceAutocompleteFieldState extends State<PlaceAutocompleteField> {
  final PlacesApiClient _client = PlacesApiClient();
  final FocusNode _focus = FocusNode();
  Timer? _debounce;
  Timer? _blurClear;
  List<PlaceSuggestion> _suggestions = const [];
  bool _loading = false;
  String? _lastError;
  /// After a pick, ignore autocomplete until the user edits away from this text.
  /// (One-shot suppress fails when TextEditingController notifies more than once.)
  String? _committedText;
  /// Bumps on select / clear so in-flight autocomplete cannot reopen the panel.
  int _searchEpoch = 0;
  bool _warmStarted = false;

  /// Programmatic bind used by route swap — preserves autocomplete contract.
  void bindSelection(String label, ResolvedPlace? place) {
    final text = label;
    _committedText = text.isEmpty ? null : text;
    _searchEpoch++;
    _suggestions = const [];
    _lastError = null;
    if (widget.controller.text != text) {
      widget.controller.value = TextEditingValue(
        text: text,
        selection: TextSelection.collapsed(offset: text.length),
      );
    }
    widget.onPlaceResolved(place);
    if (mounted) setState(() {});
  }

  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_onTextChanged);
    _focus.addListener(_onFocusChanged);
    _warmBackend();
  }

  @override
  void didUpdateWidget(covariant PlaceAutocompleteField oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.baseUrl.trim() != widget.baseUrl.trim()) {
      _warmStarted = false;
      _lastError = null;
      _client.abortInFlight();
      _warmBackend();
    }
  }

  void _warmBackend() {
    if (_warmStarted) return;
    _warmStarted = true;
    // Fire-and-forget; empty baseUrl = same-origin (/health).
    unawaited(_client.warmUp(widget.baseUrl.trim()));
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _blurClear?.cancel();
    widget.controller.removeListener(_onTextChanged);
    _focus.removeListener(_onFocusChanged);
    _focus.dispose();
    _client.close();
    super.dispose();
  }

  void _onFocusChanged() {
    if (_focus.hasFocus) {
      _blurClear?.cancel();
      return;
    }
    _blurClear?.cancel();
    _blurClear = Timer(const Duration(milliseconds: 180), () {
      if (!mounted || _focus.hasFocus) return;
      setState(() => _suggestions = const []);
    });
  }

  void _onTextChanged() {
    final text = widget.controller.text;
    if (_committedText != null) {
      if (text == _committedText) {
        // Programmatic fill or duplicate notify after select — keep panel closed.
        return;
      }
      // User edited away from the selected label.
      _committedText = null;
      widget.onPlaceResolved(null);
    } else {
      // Typing clears prior coordinate binding until a suggestion is chosen
      // (backend Google geocode can still resolve free text).
      widget.onPlaceResolved(null);
    }
    _debounce?.cancel();
    // Slightly longer debounce so rapid typing doesn't stack cold-start GETs.
    _debounce = Timer(const Duration(milliseconds: 450), _search);
  }

  Future<void> _search() async {
    if (_committedText != null) return;
    final q = widget.controller.text.trim();
    final base = widget.baseUrl.trim();
    if (q.length < 2) {
      debugPrint(
        '[PlacesField:${widget.label}] skip q="$q" (too short)',
      );
      if (mounted) {
        setState(() {
          _suggestions = const [];
          _lastError = null;
        });
      }
      return;
    }
    // Do not abortInFlight() on every keystroke — that cancels TLS mid-handshake
    // on flaky emulator networks and surfaces as TimeoutException.
    final epoch = ++_searchEpoch;
    debugPrint('[PlacesField:${widget.label}] search q="$q" base=$base');
    setState(() {
      _loading = true;
      _lastError = null;
    });
    try {
      final results = await _client.autocomplete(baseUrl: base, query: q);
      if (!mounted || epoch != _searchEpoch || _committedText != null) {
        debugPrint(
          '[PlacesField:${widget.label}] stale result ignored '
          'mounted=$mounted epochOk=${epoch == _searchEpoch} '
          'committed=${_committedText != null}',
        );
        return;
      }
      debugPrint(
        '[PlacesField:${widget.label}] got ${results.length} suggestions',
      );
      setState(() {
        _suggestions = results;
        _loading = false;
        _lastError = results.isEmpty
            ? 'No places found. Keep typing or check the API URL.'
            : null;
      });
    } catch (e) {
      debugPrint('[PlacesField:${widget.label}] search failed: $e');
      if (!mounted || epoch != _searchEpoch || _committedText != null) return;
      final timedOut = e.toString().contains('TimeoutException') ||
          e.toString().contains('Failed host lookup') ||
          e.toString().contains('SocketException');
      final localHint = AppConfig.defaultLocalBaseUrlForPlatform();
      setState(() {
        _suggestions = const [];
        _loading = false;
        _lastError = timedOut
            ? 'Places timed out ($base). Emulator often cannot reach Cloud Run — '
                'Advanced → Local ($localHint) with uvicorn on the host.'
            : 'Places request failed. Check network / API base URL.';
      });
    }
  }

  Future<void> _select(PlaceSuggestion suggestion) async {
    // Close immediately on tap (before details round-trip).
    _debounce?.cancel();
    _searchEpoch++;
    _client.abortInFlight();
    setState(() {
      _loading = true;
      _suggestions = const [];
      _lastError = null;
    });

    try {
      final place = await _client.details(
        baseUrl: widget.baseUrl.trim(),
        placeId: suggestion.placeId,
      );
      if (!mounted) return;
      final label = place?.displayLabel.isNotEmpty == true
          ? place!.displayLabel
          : suggestion.mainText;
      // Commit before mutating text so every subsequent notify is ignored.
      _committedText = label;
      widget.controller.value = TextEditingValue(
        text: label,
        selection: TextSelection.collapsed(offset: label.length),
      );
      widget.onPlaceResolved(place);
      _focus.unfocus();
    } finally {
      if (mounted) {
        setState(() {
          _loading = false;
          _suggestions = const [];
        });
      }
    }
  }

  InputDecoration _decoration(ColorScheme scheme) {
    if (widget.embedded) {
      return InputDecoration(
        labelText: widget.label,
        hintText: widget.hint,
        border: InputBorder.none,
        enabledBorder: InputBorder.none,
        focusedBorder: InputBorder.none,
        errorBorder: InputBorder.none,
        focusedErrorBorder: InputBorder.none,
        isDense: true,
        contentPadding: const EdgeInsets.symmetric(horizontal: 4, vertical: 10),
        suffixIcon: _loading
            ? const Padding(
                padding: EdgeInsets.all(12),
                child: SizedBox(
                  width: 16,
                  height: 16,
                  child: CupertinoActivityIndicator(radius: 8),
                ),
              )
            : null,
      );
    }
    return InputDecoration(
      labelText: widget.label,
      hintText: widget.hint,
      prefixIcon: Icon(widget.prefixIcon),
      suffixIcon: _loading
          ? const Padding(
              padding: EdgeInsets.all(12),
              child: SizedBox(
                width: 18,
                height: 18,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
            )
          : null,
    );
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TextFormField(
          controller: widget.controller,
          focusNode: _focus,
          decoration: _decoration(scheme),
          style: widget.embedded
              ? Theme.of(context).textTheme.bodyLarge?.copyWith(
                    fontWeight: FontWeight.w600,
                  )
              : null,
          validator: widget.validator,
          textInputAction: TextInputAction.next,
        ),
        if (_lastError != null) ...[
          const SizedBox(height: 6),
          Text(
            _lastError!,
            key: Key('places_error_${widget.label}'),
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: scheme.error,
                ),
          ),
        ],
        if (_suggestions.isNotEmpty)
          Material(
            elevation: widget.embedded ? 0 : 2,
            borderRadius: BorderRadius.circular(12),
            color: widget.embedded
                ? PlannerTokens.surfaceStrong(scheme)
                : scheme.surface,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: 220),
              child: ListView.separated(
                shrinkWrap: true,
                padding: const EdgeInsets.symmetric(vertical: 4),
                itemCount: _suggestions.length,
                separatorBuilder: (_, __) => Divider(
                  height: 1,
                  color: PlannerTokens.hairline(scheme),
                ),
                itemBuilder: (context, index) {
                  final s = _suggestions[index];
                  return ListTile(
                    dense: true,
                    leading: const Icon(CupertinoIcons.location, size: 18),
                    title: Text(s.mainText),
                    subtitle: s.secondaryText.isEmpty
                        ? null
                        : Text(
                            s.secondaryText,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                    onTap: () => _select(s),
                  );
                },
              ),
            ),
          ),
      ],
    );
  }
}
