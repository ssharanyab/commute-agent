import 'package:flutter/material.dart';

/// Centralized visual tokens for the Planner screen (presentation only).
class PlannerTokens {
  const PlannerTokens._();

  static const double radiusCard = 20;
  static const double radiusPill = 22;
  static const double radiusButton = 16;
  static const double radiusRow = 14;

  static const double spaceXs = 6;
  static const double spaceSm = 10;
  static const double spaceMd = 16;
  static const double spaceLg = 24;
  static const double spaceXl = 32;

  static const double minTouch = 48;

  static Color background(ColorScheme scheme) => scheme.surface;

  static Color surface(ColorScheme scheme) =>
      scheme.surfaceContainerHighest.withValues(alpha: 0.55);

  static Color surfaceStrong(ColorScheme scheme) =>
      scheme.surfaceContainerHighest.withValues(alpha: 0.85);

  static Color hairline(ColorScheme scheme) =>
      scheme.outlineVariant.withValues(alpha: 0.55);

  static Color mutedText(ColorScheme scheme) => scheme.onSurfaceVariant;

  static Color primary(ColorScheme scheme) => scheme.primary;

  static Color onPrimary(ColorScheme scheme) => scheme.onPrimary;

  static Color chipSelectedFill(ColorScheme scheme) =>
      scheme.primary.withValues(alpha: 0.14);

  static Color chipSelectedBorder(ColorScheme scheme) =>
      scheme.primary.withValues(alpha: 0.55);

  static Color chipUnselectedFill(ColorScheme scheme) =>
      scheme.surfaceContainerHighest.withValues(alpha: 0.4);

  static TextStyle brandTitle(BuildContext context) {
    return Theme.of(context).textTheme.titleMedium!.copyWith(
          fontWeight: FontWeight.w600,
          letterSpacing: -0.2,
          color: Theme.of(context).colorScheme.onSurface.withValues(alpha: 0.72),
        );
  }

  static TextStyle heroTitle(BuildContext context) {
    return Theme.of(context).textTheme.headlineSmall!.copyWith(
          fontWeight: FontWeight.w700,
          letterSpacing: -0.5,
          height: 1.15,
        );
  }

  static TextStyle supporting(BuildContext context) {
    return Theme.of(context).textTheme.bodyMedium!.copyWith(
          color: mutedText(Theme.of(context).colorScheme),
          height: 1.35,
        );
  }

  static TextStyle sectionLabel(BuildContext context) {
    return Theme.of(context).textTheme.labelLarge!.copyWith(
          fontWeight: FontWeight.w600,
          letterSpacing: 0.2,
          color: mutedText(Theme.of(context).colorScheme),
        );
  }

  static TextStyle rowTitle(BuildContext context) {
    return Theme.of(context).textTheme.bodyLarge!.copyWith(
          fontWeight: FontWeight.w600,
        );
  }

  static TextStyle rowSubtitle(BuildContext context) {
    return Theme.of(context).textTheme.bodySmall!.copyWith(
          color: mutedText(Theme.of(context).colorScheme),
        );
  }
}
