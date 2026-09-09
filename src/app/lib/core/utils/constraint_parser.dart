// Deterministic parsing of a few supported hard constraints from free text.
// Arbitrary NL is NOT claimed to be fully understood.

class ConstraintParser {
  /// Parse supported hard mode exclusions from UI flags + optional notes.
  static List<String> excludedModes({
    required bool excludeCabs,
    bool excludeAutos = false,
    String notes = '',
  }) {
    final out = <String>{};
    if (excludeCabs) out.add('cab');
    if (excludeAutos) out.add('auto');
    out.addAll(parseExcludedModesFromText(notes));
    return out.toList()..sort();
  }

  /// Recognizes clear cab/taxi / auto exclusion phrases.
  static List<String> parseExcludedModesFromText(String raw) {
    final text = raw.trim().toLowerCase();
    if (text.isEmpty) return const [];

    final out = <String>{};
    final cabPatterns = <RegExp>[
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
    for (final p in cabPatterns) {
      if (p.hasMatch(text)) {
        out.add('cab');
        break;
      }
    }
    final autoPatterns = <RegExp>[
      RegExp(r"\bno\s+autos?\b"),
      RegExp(r"\bavoid\s+autos?\b"),
      RegExp(r"\bno\s+auto[- ]?rickshaws?\b"),
      RegExp(r"\bavoid\s+auto[- ]?rickshaws?\b"),
    ];
    for (final p in autoPatterns) {
      if (p.hasMatch(text)) {
        out.add('auto');
        break;
      }
    }
    return out.toList()..sort();
  }
}
