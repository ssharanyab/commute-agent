// Deterministic parsing of a few supported hard constraints from free text.
// Arbitrary NL is NOT claimed to be fully understood — only clear cab/taxi exclusions.

class ConstraintParser {
  /// Parse supported hard mode exclusions from optional notes + UI flags.
  static List<String> excludedModes({
    required bool excludeCabs,
    String notes = '',
  }) {
    final out = <String>{};
    if (excludeCabs) {
      out.add('cab');
    }
    out.addAll(parseExcludedModesFromText(notes));
    return out.toList()..sort();
  }

  /// Recognizes only clear cab/taxi exclusion phrases.
  static List<String> parseExcludedModesFromText(String raw) {
    final text = raw.trim().toLowerCase();
    if (text.isEmpty) return const [];

    final patterns = <RegExp>[
      RegExp(r"\bno\s+cabs?\b"),
      RegExp(r"\bno\s+taxis?\b"),
      RegExp(r"\bavoid\s+cabs?\b"),
      RegExp(r"\bavoid\s+taxis?\b"),
      RegExp(r"\bdon'?t\s+(?:use|take)\s+cabs?\b"),
      RegExp(r"\bdon'?t\s+(?:use|take)\s+(?:a\s+)?taxis?\b"),
      RegExp(r"\bdo\s+not\s+(?:use|take)\s+cabs?\b"),
      RegExp(r"\bdo\s+not\s+(?:use|take)\s+(?:a\s+)?taxis?\b"),
      RegExp(r"\bwithout\s+cabs?\b"),
      RegExp(r"\bwithout\s+taxis?\b"),
    ];
    for (final p in patterns) {
      if (p.hasMatch(text)) {
        return const ['cab'];
      }
    }
    return const [];
  }
}
