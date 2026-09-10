import 'package:flutter/material.dart';

/// Visual tokens for the Result screen (presentation only).
class ResultTokens {
  const ResultTokens._();

  static const double radiusCard = 20;
  static const double radiusPill = 20;
  static const double radiusRow = 14;
  static const double radiusButton = 16;

  static const double spaceXs = 6;
  static const double spaceSm = 8;
  static const double spaceMd = 12;
  static const double spaceLg = 16;
  static const double spaceXl = 20;
  static const double spaceXxl = 24;
  static const double spaceSection = 32;

  static const double minTouch = 48;
  static const double timelineDot = 10;
  static const double timelineRail = 2;

  static Color background(ColorScheme scheme) => scheme.surface;

  static Color surface(ColorScheme scheme) => scheme.surface;

  static Color surfaceMuted(ColorScheme scheme) =>
      scheme.surfaceContainerHighest.withValues(alpha: 0.45);

  static Color hairline(ColorScheme scheme) =>
      scheme.outlineVariant.withValues(alpha: 0.55);

  static Color mutedText(ColorScheme scheme) => scheme.onSurfaceVariant;

  static Color accent(ColorScheme scheme) => scheme.primary;

  static Color recommendFill(ColorScheme scheme) =>
      scheme.primary.withValues(alpha: 0.08);

  static Color recommendBorder(ColorScheme scheme) =>
      scheme.primary.withValues(alpha: 0.35);

  static Color recommendStrongBorder(ColorScheme scheme) =>
      scheme.primary.withValues(alpha: 0.7);

  static Color pillFill(ColorScheme scheme) =>
      scheme.surface.withValues(alpha: 0.92);

  static TextStyle pageTitle(BuildContext context) {
    return Theme.of(context).textTheme.headlineSmall!.copyWith(
          fontWeight: FontWeight.w700,
          letterSpacing: -0.4,
          height: 1.15,
        );
  }

  static TextStyle tripContext(BuildContext context) {
    return Theme.of(context).textTheme.bodyMedium!.copyWith(
          color: mutedText(Theme.of(context).colorScheme),
          fontWeight: FontWeight.w500,
          height: 1.3,
        );
  }

  static TextStyle sectionHeader(BuildContext context) {
    return Theme.of(context).textTheme.titleSmall!.copyWith(
          fontWeight: FontWeight.w600,
          letterSpacing: -0.1,
        );
  }

  static TextStyle modeSequence(BuildContext context) {
    return Theme.of(context).textTheme.titleLarge!.copyWith(
          fontWeight: FontWeight.w700,
          height: 1.35,
          letterSpacing: -0.2,
        );
  }

  static TextStyle metric(BuildContext context) {
    return Theme.of(context).textTheme.labelLarge!.copyWith(
          fontWeight: FontWeight.w500,
        );
  }

  static TextStyle stepTitle(BuildContext context) {
    return Theme.of(context).textTheme.bodyLarge!.copyWith(
          fontWeight: FontWeight.w600,
          height: 1.3,
        );
  }

  static TextStyle stepMeta(BuildContext context) {
    return Theme.of(context).textTheme.bodySmall!.copyWith(
          color: mutedText(Theme.of(context).colorScheme),
          height: 1.3,
        );
  }

  static TextStyle explanation(BuildContext context) {
    return Theme.of(context).textTheme.bodyMedium!.copyWith(
          height: 1.35,
        );
  }

  static TextStyle badge(BuildContext context) {
    return Theme.of(context).textTheme.labelMedium!.copyWith(
          fontWeight: FontWeight.w700,
          color: accent(Theme.of(context).colorScheme),
          letterSpacing: 0.1,
        );
  }
}
