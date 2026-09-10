import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';

import '../../theme/planner_tokens.dart';

/// Semantic preference pill — presentation only.
class PreferenceChip extends StatelessWidget {
  const PreferenceChip({
    super.key,
    required this.label,
    required this.icon,
    required this.selected,
    required this.onSelected,
  });

  final String label;
  final String icon;
  final bool selected;
  final VoidCallback onSelected;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Semantics(
      button: true,
      selected: selected,
      label: label,
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onSelected,
          borderRadius: BorderRadius.circular(PlannerTokens.radiusPill),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 180),
            curve: Curves.easeOut,
            constraints: const BoxConstraints(minHeight: PlannerTokens.minTouch),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              color: selected
                  ? PlannerTokens.chipSelectedFill(scheme)
                  : PlannerTokens.chipUnselectedFill(scheme),
              borderRadius: BorderRadius.circular(PlannerTokens.radiusPill),
              border: Border.all(
                color: selected
                    ? PlannerTokens.chipSelectedBorder(scheme)
                    : PlannerTokens.hairline(scheme),
                width: selected ? 1.4 : 1,
              ),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(icon, style: const TextStyle(fontSize: 15)),
                const SizedBox(width: 8),
                Text(
                  label,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        fontWeight:
                            selected ? FontWeight.w700 : FontWeight.w500,
                        color: selected
                            ? scheme.primary
                            : scheme.onSurface.withValues(alpha: 0.88),
                      ),
                ),
                if (selected) ...[
                  const SizedBox(width: 6),
                  Icon(
                    CupertinoIcons.checkmark_alt,
                    size: 16,
                    color: scheme.primary,
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
