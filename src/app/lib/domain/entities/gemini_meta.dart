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

  /// Not for user-facing UI — Gemini/engine status must never be shown.
  String get statusLabel => '';
}
