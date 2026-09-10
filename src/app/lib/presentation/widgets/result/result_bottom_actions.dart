import 'package:flutter/material.dart';

import '../../theme/result_tokens.dart';

/// Sticky bottom action bar for Maps + Replan.
class ResultBottomActions extends StatelessWidget {
  const ResultBottomActions({
    super.key,
    required this.onOpenMaps,
    required this.onReplan,
    required this.mapsEnabled,
    required this.replanLoading,
  });

  final VoidCallback? onOpenMaps;
  final VoidCallback? onReplan;
  final bool mapsEnabled;
  final bool replanLoading;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Material(
      elevation: 0,
      color: scheme.surface.withValues(alpha: 0.96),
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(
            ResultTokens.spaceLg,
            ResultTokens.spaceMd,
            ResultTokens.spaceLg,
            ResultTokens.spaceMd,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Divider(height: 1, color: ResultTokens.hairline(scheme)),
              const SizedBox(height: ResultTokens.spaceMd),
              Row(
                children: [
                  Expanded(
                    child: FilledButton.tonal(
                      key: const Key('maps_handoff'),
                      onPressed: mapsEnabled ? onOpenMaps : null,
                      style: FilledButton.styleFrom(
                        minimumSize:
                            const Size.fromHeight(ResultTokens.minTouch),
                        padding: const EdgeInsets.symmetric(horizontal: 10),
                        shape: RoundedRectangleBorder(
                          borderRadius:
                              BorderRadius.circular(ResultTokens.radiusButton),
                        ),
                      ),
                      child: const FittedBox(
                        fit: BoxFit.scaleDown,
                        child: Text('Open in Maps'),
                      ),
                    ),
                  ),
                  const SizedBox(width: ResultTokens.spaceMd),
                  Expanded(
                    child: FilledButton(
                      key: const Key('replan_button'),
                      onPressed: replanLoading ? null : onReplan,
                      style: FilledButton.styleFrom(
                        minimumSize:
                            const Size.fromHeight(ResultTokens.minTouch),
                        padding: const EdgeInsets.symmetric(horizontal: 10),
                        shape: RoundedRectangleBorder(
                          borderRadius:
                              BorderRadius.circular(ResultTokens.radiusButton),
                        ),
                      ),
                      child: replanLoading
                          ? const Row(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                SizedBox(
                                  width: 18,
                                  height: 18,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                  ),
                                ),
                                SizedBox(width: 8),
                                Flexible(
                                  child: Text(
                                    'Updating…',
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                ),
                              ],
                            )
                          : const FittedBox(
                              fit: BoxFit.scaleDown,
                              child: Text('Replan'),
                            ),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
