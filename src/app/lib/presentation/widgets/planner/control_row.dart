import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';

import '../../theme/planner_tokens.dart';

/// Cupertino-style labeled switch row for secondary planner controls.
class ControlRow extends StatelessWidget {
  const ControlRow({
    super.key,
    required this.title,
    required this.value,
    required this.onChanged,
    this.subtitle,
  });

  final String title;
  final String? subtitle;
  final bool value;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: PlannerTokens.spaceSm),
      child: Semantics(
        toggled: value,
        label: title,
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: () => onChanged(!value),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: PlannerTokens.rowTitle(context)),
                    if (subtitle != null && subtitle!.trim().isNotEmpty) ...[
                      const SizedBox(height: 2),
                      Text(subtitle!, style: PlannerTokens.rowSubtitle(context)),
                    ],
                  ],
                ),
              ),
              const SizedBox(width: 12),
              SizedBox(
                height: PlannerTokens.minTouch,
                child: Align(
                  alignment: Alignment.centerRight,
                  child: CupertinoSwitch(
                    value: value,
                    activeTrackColor: Theme.of(context).colorScheme.primary,
                    onChanged: onChanged,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
