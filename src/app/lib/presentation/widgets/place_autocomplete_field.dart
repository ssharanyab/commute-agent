import 'dart:async';

import 'package:flutter/material.dart';

import '../../data/places_api_client.dart';

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
  });

  final TextEditingController controller;
  final String baseUrl;
  final String label;
  final String hint;
  final IconData prefixIcon;
  final ValueChanged<ResolvedPlace?> onPlaceResolved;
  final FormFieldValidator<String>? validator;

  @override
  State<PlaceAutocompleteField> createState() => _PlaceAutocompleteFieldState();
}

class _PlaceAutocompleteFieldState extends State<PlaceAutocompleteField> {
  final PlacesApiClient _client = PlacesApiClient();
  final FocusNode _focus = FocusNode();
  Timer? _debounce;
  Timer? _blurClear;
  List<PlaceSuggestion> _suggestions = const [];
  bool _loading = false;
  /// After a pick, ignore autocomplete until the user edits away from this text.
  /// (One-shot suppress fails when TextEditingController notifies more than once.)
  String? _committedText;
  /// Bumps on select / clear so in-flight autocomplete cannot reopen the panel.
  int _searchEpoch = 0;

  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_onTextChanged);
    _focus.addListener(_onFocusChanged);
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _blurClear?.cancel();
    widget.controller.removeListener(_onTextChanged);
    _focus.removeListener(_onFocusChanged);
    _focus.dispose();
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
    _debounce = Timer(const Duration(milliseconds: 320), _search);
  }

  Future<void> _search() async {
    if (_committedText != null) return;
    final q = widget.controller.text.trim();
    final base = widget.baseUrl.trim();
    if (q.length < 2 || base.isEmpty) {
      if (mounted) setState(() => _suggestions = const []);
      return;
    }
    final epoch = ++_searchEpoch;
    setState(() => _loading = true);
    try {
      final results = await _client.autocomplete(baseUrl: base, query: q);
      if (!mounted || epoch != _searchEpoch || _committedText != null) return;
      setState(() {
        _suggestions = results;
        _loading = false;
      });
    } catch (_) {
      if (!mounted || epoch != _searchEpoch || _committedText != null) return;
      setState(() {
        _suggestions = const [];
        _loading = false;
      });
    }
  }

  Future<void> _select(PlaceSuggestion suggestion) async {
    // Close immediately on tap (before details round-trip).
    _debounce?.cancel();
    _searchEpoch++;
    setState(() {
      _loading = true;
      _suggestions = const [];
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

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TextFormField(
          controller: widget.controller,
          focusNode: _focus,
          decoration: InputDecoration(
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
          ),
          validator: widget.validator,
          textInputAction: TextInputAction.next,
        ),
        if (_suggestions.isNotEmpty)
          Material(
            elevation: 2,
            borderRadius: BorderRadius.circular(10),
            color: scheme.surface,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: 220),
              child: ListView.separated(
                shrinkWrap: true,
                padding: const EdgeInsets.symmetric(vertical: 4),
                itemCount: _suggestions.length,
                separatorBuilder: (_, __) => const Divider(height: 1),
                itemBuilder: (context, index) {
                  final s = _suggestions[index];
                  return ListTile(
                    dense: true,
                    leading: const Icon(Icons.place_outlined, size: 20),
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
