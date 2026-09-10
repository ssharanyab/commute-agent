import 'package:flutter/material.dart';

import '../../theme/result_tokens.dart';

/// Compact metric chip — only renders the provided truthful label.
class MetricPill extends StatelessWidget {
  const MetricPill({
    super.key,
    required this.icon,
    required this.label,
  });

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: ResultTokens.pillFill(scheme),
        borderRadius: BorderRadius.circular(ResultTokens.radiusPill),
        border: Border.all(color: ResultTokens.hairline(scheme)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 16, color: ResultTokens.mutedText(scheme)),
          const SizedBox(width: 6),
          Text(
            label,
            style: ResultTokens.metric(context),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
        ],
      ),
    );
  }
}
