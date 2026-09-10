import 'package:flutter/material.dart';

import '../../theme/result_tokens.dart';
import '../../utils/mode_presentation.dart';

/// Horizontal, wrapping mode sequence from backend mode tokens.
class ModeSequenceRow extends StatelessWidget {
  const ModeSequenceRow({
    super.key,
    required this.modes,
    this.fallbackLabel = 'Route',
    this.compact = false,
  });

  final List<String> modes;
  final String fallbackLabel;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    if (modes.isEmpty) {
      return Text(
        fallbackLabel,
        style: compact
            ? Theme.of(context).textTheme.bodyLarge?.copyWith(
                  fontWeight: FontWeight.w600,
                )
            : ResultTokens.modeSequence(context),
      );
    }

    final style = compact
        ? Theme.of(context).textTheme.bodyLarge?.copyWith(
              fontWeight: FontWeight.w600,
              height: 1.3,
            )
        : ResultTokens.modeSequence(context);
    final arrowColor = ResultTokens.mutedText(Theme.of(context).colorScheme);

    return Wrap(
      crossAxisAlignment: WrapCrossAlignment.center,
      spacing: 4,
      runSpacing: 6,
      children: [
        for (var i = 0; i < modes.length; i++) ...[
          if (i > 0)
            Text(
              '→',
              style: style?.copyWith(
                color: arrowColor,
                fontWeight: FontWeight.w500,
              ),
            ),
          Text(modeChip(modes[i]), style: style),
        ],
      ],
    );
  }
}
