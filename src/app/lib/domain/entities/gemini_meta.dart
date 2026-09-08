class GeminiMeta {
  final bool available;
  final bool invoked;
  final bool adkInvoked;
  final String mode;

  const GeminiMeta({
    required this.available,
    required this.invoked,
    required this.adkInvoked,
    required this.mode,
  });

  String get statusLabel {
    if (invoked) return 'Gemini ($mode)';
    if (!available) return 'Gemini unavailable — deterministic fallback';
    return 'Deterministic fallback ($mode)';
  }
}
