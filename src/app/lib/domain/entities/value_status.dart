/// Backend known/unknown/unavailable semantics (Phase 6E/6F).
///
/// Never treat [unknown] numeric placeholders as authoritative values.
enum ValueStatus {
  known,
  unknown,
  unavailable;

  static ValueStatus fromWire(
    String? raw, {
    ValueStatus whenMissing = ValueStatus.unknown,
  }) {
    final text = (raw ?? '').trim().toLowerCase();
    if (text.isEmpty) return whenMissing;
    switch (text) {
      case 'known':
        return ValueStatus.known;
      case 'unavailable':
        return ValueStatus.unavailable;
      case 'unknown':
        return ValueStatus.unknown;
      default:
        return ValueStatus.unknown;
    }
  }

  String get wire => name;
}
